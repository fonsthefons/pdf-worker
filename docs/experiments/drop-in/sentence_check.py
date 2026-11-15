"""Flagged words settled three ways, scored against the reference (drop-in experiment, S6).
Nothing is converted and nothing in ai-client is changed.

  sentence_check.py run BOOK.md FIXES.tsv OUT.json --mode today|sentences|lists [--model ID]
  sentence_check.py score OUT.json...
  sentence_check.py selftest

Flags: the open ``spelling`` rows of the review file (no action); ``today`` also takes its
``auto:`` rows (split and learned words the build applied). Each is found in BOOK.md by its
row's context (the first place it fits).
- today: what the pipeline does now: auto rows applied, open rows left for a human.
- sentences (books with at most 300 open flags): each flag's sentence, numbered, sent to one free
  OpenRouter model (``--model``; default the best that ``discover()`` lists and is up), packed
  into as few requests as its context holds; the model answers ``{number: corrected sentence}``
  for the sentences it changes. A correction is kept only if every change is within two words of
  a flagged word and at most three words change (per flagged word of the sentence); otherwise, on
  an error, a timeout (60 s) or bad JSON, the flags stay open. A sentence not returned un-flags
  its words.
- lists: no model. A flag whose words are all in ai-client's Latin, German, French or English
  Hunspell dictionary, or look like a Greek transliteration, is un-flagged; the rest stay open.

score: the book's reference (tools/quality.py PAIRS, by BOOK.md's stem) settles each flag: the
five words on each side of it in ours must occur, in order, once in the reference with at most
the flag's length + 3 words between; those words are the truth. Unaligned flags are left out and
counted. right: a wrong word corrected to the reference, or a right word un-flagged; wrong: a
wrong word changed otherwise, or un-flagged; harmed: a right word (or a neighbour) changed;
left: still open. Foreign: aligned flags whose word is right and passes the lists rule. Books
with terms in greek_truth.json also get tools/greek_score.py on the corrected Markdown.
"""

import csv
import json
import re
import sys
import threading
import time
import unicodedata
from bisect import bisect_left
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))
import greek_score  # noqa: E402
from book_score import read_reference  # noqa: E402
from regression import _write_atomic  # noqa: E402

OUT = ROOT / "scratch" / "drop-in" / "s6"
SIDE = 5  # anchor words each side
MAX_OPEN = 300
TIMEOUT = 60
NEAR, MAX_CHANGED = 2, 3
SENTENCE_SIDE = 40  # words kept each side of a flag when no sentence end is nearer
CONTEXT_CHARS = 40  # ai_client.check.CONTEXT_CHARS: the flag sits this far into its context
CHARS_PER_TOKEN = 3  # an overestimate for Spanish
LISTS = ("la", "de", "fr", "en")
LANGUAGES = {"es": "Spanish", "en": "English"}
_TOKEN = re.compile(r"[^\W_]+")
# Not text: front matter, note references, margin labels, images, link targets.
_HIDE = re.compile(
    r"\A---\n.*?\n---\n|\[\^[^\]]+\]|\*\*\\\[[^\]\\]+\\\]\*\*|!\[[^\]]*\]\([^)]*\)|\]\([^)]*\)",
    re.S,
)
_PLAIN = re.compile(r"[*\\#_>]")
_GREEK = re.compile("[Ͱ-Ͽἀ-῿]")
_COUNT = re.compile(r"^×\d+ ")
_STOP = re.compile(r"[.!?…][\"”»’)\]]*(?=\s)|\n\s*\n")
# shortcut: a rough look of transliterated Greek (long vowels, ou, k, y, ph/th/kh/rh/ps and a
# Greek ending); "lógos" passes no test. A list of transliterations would do better.
_TRANSLIT = re.compile(
    r"[ēōêôûŷ]|^(?=\w*(?:ph|th|kh|rh|ps|ou|k|y\w))\w+(?:os|on|ē|ia|eia|ai|oi|is|ma|es|ós|ón|ía)$",
    re.I,
)
SYSTEM = """You proofread sentences of a {language} book read by OCR. In each numbered sentence a
spell checker flagged the words listed under it. Many flagged words are right: names, rare words,
and words of other languages (Greek transliterations, Latin, German, French, English) must stay
exactly as printed. Correct a flagged word only when it is clearly an OCR misreading, changing as
little as possible; never rewrite anything else. Answer only with a JSON object holding the
sentences you changed, {{"number": "the whole corrected sentence"}}, or {{}} if none."""


def key(token: str) -> str:
    return unicodedata.normalize("NFKC", token).lower()


class Book:
    def __init__(self, md: Path):
        self.text = md.read_text(encoding="utf-8")
        self.masked = _HIDE.sub(lambda m: " " * len(m.group()), self.text)
        self.tokens = [m.span() for m in _TOKEN.finditer(self.masked)]
        self.starts = [a for a, _ in self.tokens]
        self.keys = [key(self.text[a:b]) for a, b in self.tokens]
        self.where: dict[str, list[int]] = defaultdict(list)
        for i, k in enumerate(self.keys):
            self.where[k].append(i)
        lang = re.search(r"^lang: *(\w+)", self.text[:2000], re.M)
        self.language = LANGUAGES.get(lang.group(1) if lang else "es", "Spanish")

    def locate(self, find: str, context: str, value: str | None = None) -> tuple[int, int] | None:
        """Token span of the flag in the book; ``value``: the text the build put in its place."""
        context = _COUNT.sub("", context)
        spots = [m.start() for m in re.finditer(re.escape(find), context)]
        if not spots:
            return None
        at = min(spots, key=lambda i: abs(i - CONTEXT_CHARS))
        shown = find if value is None else value
        context = context[:at] + shown + context[at + len(find) :]
        toks = list(_TOKEN.finditer(context))
        inside = [i for i, m in enumerate(toks) if m.start() < at + len(shown) and m.end() > at]
        if not inside:
            return None
        lo = 1 if inside[0] > 0 else 0  # the context's ends may cut a word
        hi = len(toks) - 1 if inside[-1] < len(toks) - 1 else len(toks)
        seq = [key(m.group()) for m in toks[lo:hi]]
        for p in self.where.get(seq[0], ()):
            if self.keys[p : p + len(seq)] == seq:
                return p + inside[0] - lo, p + inside[-1] + 1 - lo
        return None

    def sentence(self, s: int, e: int) -> tuple[int, int]:
        """Token range of the sentence holding tokens s..e."""
        start, end = self.tokens[s][0], self.tokens[e - 1][1]
        before = [m.end() for m in _STOP.finditer(self.masked, max(0, start - 4000), start)]
        after = _STOP.search(self.masked, end)
        a = bisect_left(self.starts, before[-1]) if before else 0
        b = bisect_left(self.starts, after.end()) if after else len(self.tokens)
        return max(a, s - SENTENCE_SIDE), min(b, e + SENTENCE_SIDE)

    def plain(self, a: int, b: int) -> str:
        return " ".join(
            _PLAIN.sub(" ", self.masked[self.tokens[a][0] : self.tokens[b - 1][1]]).split()
        )


def read_flags(book: Book, fixes: Path, auto: bool) -> list[dict]:
    flags = []
    with fixes.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            is_auto = row["action"] == "replace" and row["type"].startswith("auto")
            if row["kind"] != "spelling" or (row["action"] and not (auto and is_auto)):
                continue
            span = book.locate(row["find"], row["context"], row["value"] if is_auto else None)
            flags.append({
                "id": row["id"], "page": row["page"], "find": row["find"], "type": row["type"],
                "auto": is_auto, "span": list(span) if span else None,
                "orig": [key(t) for t in _TOKEN.findall(row["find"])], "action": "left",
            })  # fmt: skip
    return flags


# --- modes ------------------------------------------------------------------------------


def dictionaries() -> list:
    from ai_client import config
    from ai_client._vendor.spylls.hunspell import Dictionary

    return [Dictionary.from_files(str(config.DICTIONARIES / lang)) for lang in LISTS]


def _bare(word: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", word) if not unicodedata.combining(c))


def foreign(word: str, dicts: list) -> bool:
    """All of ``word``'s words in a list or transliterated Greek. An accented word counts only
    where its accents matter (as ai-client's ``Words.foreign``): the Latin list ignores accents
    and would take OCR's "pára" for "para"."""
    words = _TOKEN.findall(word)
    has = lambda d, w: d.lookup(w) or d.lookup(w.lower())  # noqa: E731
    listed = lambda d, w: has(d, w) and (_bare(w) == w or not has(d, _bare(w)))  # noqa: E731
    return bool(words) and all(
        _TRANSLIT.search(w) or any(listed(d, w) for d in dicts) for w in words
    )


def lists_mode(flags: list[dict]) -> None:
    dicts = dictionaries()
    for flag in flags:
        flag["action"] = "keep" if foreign(flag["find"], dicts) else "left"


def gate(old: list[str], new: list[str], flagged: list[tuple[int, int]]) -> list | None:
    """The changes from ``old`` to ``new`` words if all are near a flagged span (s, e) and few."""
    norm = lambda ws: [unicodedata.normalize("NFC", w) for w in ws]  # noqa: E731
    ops = SequenceMatcher(None, norm(old), norm(new), autojunk=False).get_opcodes()
    ops = [op for op in ops if op[0] != "equal"]
    changed = sum(max(i2 - i1, j2 - j1) for _, i1, i2, j1, j2 in ops)
    near = lambda i1, i2: any(i1 >= s - NEAR and i2 <= e + NEAR for s, e in flagged)  # noqa: E731
    if changed > MAX_CHANGED * len(flagged) or not all(near(i1, i2) for _, i1, i2, _, _ in ops):
        return None
    return ops


def parse(answer: str) -> dict | None:
    start, end = answer.find("{"), answer.rfind("}")
    try:
        found = json.loads(answer[start : end + 1]) if 0 <= start < end else None
    except ValueError:
        return None
    return found if isinstance(found, dict) else None


def pack(lines: list[str], context: int, max_out: int, prompt: int) -> list[list[int]]:
    """Line indexes per request: the lines in and, at worst, all back out must fit."""
    batches, size = [], 0
    for i, line in enumerate(lines):
        n = len(line) // CHARS_PER_TOKEN + 1
        if batches and 2 * (size + n) + prompt <= context and size + n <= max_out:
            batches[-1].append(i)
            size += n
        else:
            batches.append([i])
            size = n
    return batches


class NotRun(Exception):
    pass


def call(send) -> str | dict:
    """``send()``'s answer, or {"error": why} on an error or after TIMEOUT seconds by the clock
    (the HTTP timeout bounds each socket read only); a late call is left running, unread."""
    box: dict = {"error": f"no answer in {TIMEOUT} s"}

    def work():
        try:
            box["answer"] = send()
        except Exception as e:
            box["error"] = f"{type(e).__name__}: {str(e)[:200]}"

    thread = threading.Thread(target=work, daemon=True)
    thread.start()
    thread.join(TIMEOUT)
    return box.get("answer", box)


def sentences_mode(book: Book, flags: list[dict], model: str | None, out: dict) -> None:
    if len(flags) > MAX_OPEN:
        raise NotRun(f"{len(flags)} open flags (more than {MAX_OPEN})")
    from ai_client import get_client

    client = get_client("openrouter")
    if not client.key:
        raise NotRun("no OPENROUTER_API_KEY")
    left = client.requests_left()
    if left is not None and left <= 0:
        raise NotRun("no free OpenRouter requests left today")
    model = model or next((m for m in client.discover() if client.is_up(m)), None)
    if not model:
        raise NotRun("no free text model up")
    entry = client.catalog().get(model, {})
    context = entry.get("context_length") or 32_000
    max_out = (entry.get("top_provider") or {}).get("max_completion_tokens") or context // 2
    out |= {"model": model, "context": context, "max_out": max_out, "left_before": left}
    # Sentences (token ranges), merged where they overlap, with their flags.
    spans = sorted((book.sentence(*f["span"]), i) for i, f in enumerate(flags) if f["span"])
    groups: list[list] = []  # [a, b, flag indexes]
    for (a, b), i in spans:
        if groups and a < groups[-1][1]:
            groups[-1][1] = max(groups[-1][1], b)
            groups[-1][2].append(i)
        else:
            groups.append([a, b, [i]])
    finds = [", ".join(dict.fromkeys(flags[i]["find"] for i in its)) for _, _, its in groups]
    lines = [
        f"{n}. {book.plain(a, b)}\n   flagged: {finds[n - 1]}"
        for n, (a, b, _) in enumerate(groups, 1)
    ]
    system = SYSTEM.format(language=book.language)
    batches = pack(lines, context, max_out, len(system) // CHARS_PER_TOKEN + 50)
    out |= {"sentences": len(groups), "requests": len(batches), "seconds": 0.0, "errors": []}
    options = {"model": model, "fallbacks": False, "timeout": TIMEOUT, "retries": 0}
    for batch in batches:
        start = time.monotonic()
        user = "\n".join(lines[n] for n in batch)
        answer = call(lambda user=user: client.chat(user, system, temperature=0, **options))
        if isinstance(answer, str):
            found = parse(answer)
            error = "" if found is not None else f"bad JSON: {answer[:200]!r}"
        else:  # a failed or late call never blocks: the flags stay open
            found, error = None, answer["error"]
        took = time.monotonic() - start
        out["seconds"] += took
        if found is not None and took > TIMEOUT:
            found, error = None, f"answered after {took:.0f} s"
        if error:
            out["errors"].append(error)
        for n in batch:
            a, b, its = groups[n]
            new = found.get(str(n + 1)) if found is not None else None
            if found is None or (new is not None and not isinstance(new, str)):
                continue  # left open
            if new is None:
                for i in its:
                    flags[i]["action"] = "keep"
                continue
            spans_in = [(flags[i]["span"][0] - a, flags[i]["span"][1] - a) for i in its]
            old = [book.text[x:y] for x, y in book.tokens[a:b]]
            ops = gate(old, _TOKEN.findall(new), spans_in)
            if ops is None:
                continue
            for _, i1, i2, j1, j2 in ops:
                words = _TOKEN.findall(new)[j1:j2]
                out["edits"].append([a + i1, a + i2, words])
            for i in its:
                flags[i]["action"] = "change" if ops else "keep"


def run(md: Path, fixes: Path, out_path: Path, mode: str, model: str | None) -> None:
    book = Book(md)
    flags = read_flags(book, fixes, auto=mode == "today")
    out = {"md": str(md), "fixes": str(fixes), "mode": mode, "model": None, "not_run": None,
           "requests": 0, "seconds": 0.0, "errors": [], "edits": [], "flags": flags}  # fmt: skip
    start = time.monotonic()
    if mode == "today":
        for flag in flags:
            flag["action"] = "change" if flag["auto"] else "left"
    elif mode == "lists":
        lists_mode(flags)
        out["seconds"] = time.monotonic() - start
    elif mode == "sentences":
        try:
            sentences_mode(book, flags, model, out)
        except NotRun as e:
            out["not_run"] = str(e)
    else:
        sys.exit(f"unknown mode {mode}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    _write_atomic(out_path, json.dumps(out, ensure_ascii=False, indent=1))
    acts = defaultdict(int)
    for flag in flags:
        acts[flag["action"]] += 1
    why = f", not run: {out['not_run']}" if out["not_run"] else ""
    print(f"{md.stem} {mode}: {len(flags)} flags {dict(acts)}, {out['requests']} requests, "
          f"{out['seconds']:.0f} s{why}")  # fmt: skip


# --- score ------------------------------------------------------------------------------


def window(keys: list[str], lo: int, hi: int, edits: list) -> list[str]:
    """keys[lo:hi] with the edits inside it applied (insertions at its edges left out)."""
    out, i = [], lo
    for a, b, words in sorted(edits, key=lambda x: (x[0], x[1])):
        if lo <= a and b <= hi and (a < b or lo < a < hi) and a >= i:
            out += keys[i:a] + [key(w) for w in words]
            i = b
    return out + keys[i:hi]


def judge(
    keys: list[str], flag: dict, edits: list, ref: list[str], index: dict
) -> tuple[str, bool]:
    """(outcome, the flagged word is right); outcome "unlocated" or "unaligned" when not judged."""
    if not flag["span"]:
        return "unlocated", False
    s, e = flag["span"]
    lo, hi = s - SIDE, e + SIDE
    orig = flag["orig"] if flag["auto"] else keys[s:e]
    if lo < 0 or hi > len(keys):
        return "unaligned", False
    left, right = keys[lo:s], keys[e:hi]
    pairs = [(p, q) for p in index.get(tuple(left), ()) for q in index.get(tuple(right), ())
             if p + SIDE <= q <= p + SIDE + len(orig) + 3]  # fmt: skip
    if len(pairs) != 1:
        return "unaligned", False
    p, q = pairs[0]
    ok = orig == ref[p + SIDE : q]
    base, new = left + orig + right, window(keys, lo, hi, edits)
    if new != base:
        return ("harmed" if ok else "right" if new == ref[p : q + SIDE] else "wrong"), ok
    if flag["action"] == "left":
        return "left", ok
    return ("right" if ok else "wrong"), ok


def ngrams(ws: list[str]) -> dict[tuple, list[int]]:
    index: dict[tuple, list[int]] = defaultdict(list)
    for i in range(len(ws) - SIDE + 1):
        index[tuple(ws[i : i + SIDE])].append(i)
    return index


def apply_text(book: Book, edits: list) -> str:
    text, done = book.text, set()
    for a, b, words in sorted(edits, key=lambda x: (x[0], x[1]), reverse=True):
        if (a, b) in done:
            continue
        done.add((a, b))
        if a < b:
            text = text[: book.tokens[a][0]] + " ".join(words) + text[book.tokens[b - 1][1] :]
        elif a < len(book.tokens):
            at = book.tokens[a][0]
            text = text[:at] + " ".join(words) + " " + text[at:]
    return text


def score(paths: list[Path]) -> None:
    import quality

    refs = {label: ref for label, _, ref, _, _ in quality.PAIRS}
    truth = greek_score.load_truth()
    dicts = dictionaries()
    cache: dict[str, tuple] = {}
    print("| book | mode | model | flags | aligned | unaligned | right | wrong | harmed | left "
          "| word right / wrong | foreign | requests | seconds | Greek |")  # fmt: skip
    print("|" + "---|" * 15)
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        md = Path(data["md"])
        label = md.stem
        if label not in cache:
            ref = read_reference(refs[label]).words
            cache[label] = (Book(md), ref, ngrams(ref))
        book, ref, index = cache[label]
        model = (data.get("model") or "-").split("/")[-1]
        if data["not_run"]:
            print(f"| {label} | {data['mode']} | {model} | {len(data['flags'])} | not run: "
                  f"{data['not_run']} |" + " |" * 10)  # fmt: skip
            continue
        for auto in (False, True):
            flags = [f for f in data["flags"] if f["auto"] == auto]
            if auto and not flags:
                continue
            counts, rights, foreigns = defaultdict(int), 0, 0
            for flag in flags:
                outcome, ok = judge(book.keys, flag, data["edits"], ref, index)
                counts[outcome] += 1
                aligned = outcome not in ("unaligned", "unlocated")
                rights += aligned and ok
                foreigns += aligned and ok and foreign(flag["find"], dicts)
            aligned = len(flags) - counts["unaligned"] - counts["unlocated"]
            # greek_truth.json has terms of timeo and if only: elsewhere, Greek words edited.
            touched = [w for a, b, ws in data["edits"] for w in book.keys[a:b] + ws]
            greek = f"{sum(bool(_GREEK.search(w)) for w in touched)} edited"
            terms = [t for t in truth if t["book"] == label]
            if terms and not auto:
                out = OUT / "greek" / path.stem / f"{label}.md"
                out.parent.mkdir(parents=True, exist_ok=True)
                _write_atomic(out, apply_text(book, data["edits"]))
                found = greek_score.score(terms, out)
                greek = ", ".join(
                    f"{k} {s['found']}/{s['found'] + len(s['missing'])}" for k, s in found.items()
                )
            mode = data["mode"] + (" (auto rows)" if auto else "")
            share = f"{foreigns} ({100 * foreigns / aligned:.0f}%)" if aligned else "0"
            cells = [label, mode, model, len(flags), aligned,
                     f"{counts['unaligned']}+{counts['unlocated']}",
                     *(counts[k] for k in ("right", "wrong", "harmed", "left")),
                     f"{rights} / {aligned - rights}", share, data["requests"],
                     f"{data['seconds']:.0f}", greek]  # fmt: skip
            print("| " + " | ".join(map(str, cells)) + " |")
        if data["errors"]:
            print(f"<!-- {label} {model} errors: {data['errors'][:3]} -->")


# --- selftest ---------------------------------------------------------------------------


def selftest() -> None:
    work = OUT / "selftest"
    work.mkdir(parents=True, exist_ok=True)
    md = work / "book.md"
    body = (
        "Uno dos tres cuatro cinco seis siete ocho nueve diez once doce. El hombre "
        "tiene un alma racional y dice que la ousía es una sustancia primera del mundo. "
        "Luego vino el fin de todo lo que había sido escrito por los sabios antiguos."
    )
    _write_atomic(
        md,
        f"---\nlang: es\n---\n\n{body.replace('alma', 'aIma').replace('sabios', 'sabios[^1]')}\n",
    )
    book = Book(md)
    assert book.language == "Spanish" and "1" not in book.keys
    span = book.locate("aIma", "El hombre tiene un aIma racional y dice que la")
    assert span and book.keys[span[0]] == "aima", span
    ousia = book.locate("ousía", "×2 y dice que la ousía es una sustancia primera")
    ref = [key(w) for w in _TOKEN.findall(body)]
    index = ngrams(ref)
    flag = {"span": list(span), "auto": False, "orig": ["aima"], "action": "left"}
    good = {"span": list(ousia), "auto": False, "orig": ["ousía"], "action": "keep"}
    assert judge(book.keys, flag, [], ref, index) == ("left", False)
    assert judge(book.keys, flag, [[span[0], span[1], ["alma"]]], ref, index) == ("right", False)
    assert judge(book.keys, flag, [[span[0], span[1], ["arma"]]], ref, index) == ("wrong", False)
    assert judge(book.keys, good, [], ref, index) == ("right", True)
    assert judge(book.keys, good, [[ousia[0], ousia[1], ["ousia"]]], ref, index) == ("harmed", True)
    assert judge(book.keys, {**flag, "action": "keep"}, [], ref, index) == ("wrong", False)
    a, b = book.sentence(*span)
    assert (
        book.plain(a, b)
        == "El hombre tiene un aIma racional y dice que la ousía es una sustancia primera del mundo"
    )
    old = _TOKEN.findall("El hombre tiene un aIma racional y dice")
    assert gate(old, _TOKEN.findall("El hombre tiene un alma racional y dice"), [(4, 5)])
    far, many = (
        "El hombre tiene un alma racional y dijo",
        "Los hombres tienen un alma racional y dice",
    )
    assert gate(old, _TOKEN.findall(far), [(4, 5)]) is None
    assert gate(old, _TOKEN.findall(many), [(4, 5)]) is None
    assert gate(old, old, [(4, 5)]) == []
    assert (
        parse('```json\n{"1": "x"}\n```') == {"1": "x"}
        and parse("no") is None
        and parse("[1]") is None
    )
    assert pack(["x" * 30] * 4, 60, 1000, 10) == [[0, 1], [2, 3]]
    assert call(lambda: "{}") == "{}" and call(lambda: 1 / 0)["error"].startswith(
        "ZeroDivisionError"
    )
    assert apply_text(book, [[span[0], span[1], ["alma"]]]).count("un alma racional") == 1
    dicts = dictionaries()
    assert foreign("Wesen", dicts) and foreign("ousía", dicts) and foreign("phýsis", dicts)
    assert foreign("interprètes", dicts) and not foreign("pára", dicts)
    assert foreign("aIma", dicts)  # French "aima": a list un-flags a misread word too
    assert not foreign("hornbre", dicts) and not foreign("cómparaciones", dicts)
    print("ok")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["run"] and len(args) >= 6 and args[4] == "--mode":
        chosen = args[args.index("--model") + 1] if "--model" in args else None
        run(Path(args[1]), Path(args[2]), Path(args[3]), args[5], chosen)
    elif args[:1] == ["score"] and len(args) > 1:
        score([Path(a) for a in args[1:]])
    elif args == ["selftest"]:
        selftest()
    else:
        sys.exit(__doc__)
