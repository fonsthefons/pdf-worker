"""Score a reflowed Platón book (.txt from convert) against the good ePub-made PDF.

Usage: python tests/platon_score.py <ours.txt> [--pages 6-175] [--verbose | --show refs,mref]
(also used by ``test_paddle_book_platon.py``). The default pages, 6-23, are what
test_platon_bad_3 covers; 6-175 is the whole book.

Ground truth: platon_dialogos_vi_good.pdf's pages (Introducción, Nota bibliográfica,
Filebo 11a-...), their notes (linked pages in the final "Notas" section), the margin
references (labels in the right margin) and paragraph starts (indented lines).
Our side: the txt writer's format: paragraphs separated by blank lines, refs "[n]",
margin refs "[11b]", notes as "[n] text" lines at the end (numbering restarts per part).
Both sides count a new part when note references restart at 1, and a new dialogue when
the margin numbers go down (Filebo 67 -> Timeo 17): labels are "<dialogue>:<label>".
"""

import difflib
import re
import sys
import unicodedata
from pathlib import Path

import pymupdf

GOOD = str(Path(__file__).resolve().parents[1] / "test_pdfs" / "platon_dialogos_vi_good.pdf")
PAGES = range(6, 24)  # 1-based: what test_platon_bad_3 covers
REF_RE = re.compile(r"\[(\d+)\]")
MREF_RE = re.compile(r"\[(\d+[a-e])\]")
WORD_RE = re.compile(r"\w+", re.UNICODE)


def norm(word: str) -> str:
    return unicodedata.normalize("NFC", word).lower()


def words_of(text: str) -> list[str]:
    return [norm(w) for w in WORD_RE.findall(text)]


# -- ground truth ------------------------------------------------------------------------
class _Counter:
    """Part and dialogue numbers, from note numbers and margin numbers as they come."""

    def __init__(self) -> None:
        self.part = self.last_ref = 0
        self.dialogue = self.last_num = 0

    def ref(self, n: int) -> tuple[int, int]:
        if n == 1 and self.last_ref > 1:
            self.part += 1
        self.last_ref = n
        return (self.part, n)

    def mref(self, label: str) -> str:
        num = int(re.match(r"\d+", label).group())
        if num < self.last_num:
            self.dialogue += 1
        self.last_num = num
        return f"{self.dialogue}:{label}"


def good_truth(pages=PAGES):
    """Body tokens with events, from the good PDF.

    Returns words (list), events: list of (kind, word index, value) where kind is
    'para' (paragraph starts before word), 'ref' ((part, n) after word index-1),
    'mref' (label, a line's word indexes), and notes {(part, n): text}."""
    words: list[str] = []
    events = []
    notes = {}
    label_num = None
    count = _Counter()
    with pymupdf.open(GOOD) as doc:
        for p in pages:
            page = doc[p - 1]
            page_refs = {}  # note number -> key, for the links below
            margin = []  # (y, label)
            lines = []  # (y0, y1, x0, [spans])
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    text = "".join(s["text"] for s in line["spans"]).strip()
                    x0, y0, _, y1 = line["bbox"]
                    if not text or y0 > 800:
                        continue  # footer "www.lectulandia.com - Página n"
                    if x0 > 500 and re.fullmatch(r"\d+|[a-e]", text):
                        margin.append((y0, text))
                        continue
                    lines.append((y0, y1, x0, line["spans"]))
            lines.sort(key=lambda item: item[0])
            line_words = []  # per line: word index range
            for y0, y1, x0, spans in lines:
                heading = any(s["size"] > 16 for s in spans)
                start = len(words)
                if heading or x0 > 60 or not words:
                    events.append(("para", start, None))
                # Spans split words (small caps "S"+"ÓC", substitute-font letters
                # "aret"+"é"): join the line's text, refs as placeholders.
                text = ""
                refs = []
                for s in spans:
                    m = REF_RE.fullmatch(s["text"].strip())
                    if m and s["flags"] & 1:  # superscript
                        key = count.ref(int(m.group(1)))
                        page_refs[key[1]] = key
                        refs.append(key)
                        text += f" \x00{len(refs) - 1} "
                        continue
                    text += s["text"]
                for token in re.split(r"(\x00\d+)", text):
                    if token.startswith("\x00"):
                        events.append(("ref", len(words), refs[int(token[1:])]))
                    else:
                        words.extend(words_of(token))
                line_words.append((y0, y1, start, len(words)))
            for y, label in sorted(margin):
                if label.isdigit():
                    label_num, label = label, label + "a"
                elif label_num is None:
                    continue  # pages starting mid-section: no number yet
                else:
                    label = f"{label_num}{label}"
                label = count.mref(label)
                hit = [k for k, lw in enumerate(line_words) if lw[0] - 4 <= y <= lw[1]]
                if hit:
                    # The ePub sets the label near its own line, which wraps differently
                    # from the print: one line either side counts.
                    k = hit[0]
                    lo = line_words[max(0, k - 1)][2]
                    hi = line_words[min(len(line_words) - 1, k + 1)][3]
                    events.append(("mref", line_words[k][2], (label, lo, hi)))
            # notes: follow the links of this page's refs
            for link in page.get_links():
                target = link.get("page")
                if target is None:
                    continue
                m = REF_RE.search(page.get_textbox(link["from"]))
                if not m or int(m.group(1)) not in page_refs:
                    continue
                text = doc[target].get_text()
                text = re.sub(r"www\.lectulandia\.com - Página \d+", "", text)
                text = text.replace("<<", "")
                text = REF_RE.sub("", text, count=1)
                notes[page_refs[int(m.group(1))]] = " ".join(text.split())
    return words, events, notes


# -- our output --------------------------------------------------------------------------
def our_side(path: str):
    raw = Path(path).read_text(encoding="utf-8")
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", raw) if p.strip()]
    body, note_paras = [], []
    for para in paragraphs:
        (note_paras if re.match(r"\[\d+\] ", para) else body).append(para)
    notes = {}
    part_index, last = 0, 0
    for para in note_paras:
        n = int(REF_RE.match(para).group(1))
        if n <= last:
            part_index += 1
        last = n
        notes[(part_index, n)] = " ".join(para[REF_RE.match(para).end() :].split())
    words: list[str] = []
    events = []
    count = _Counter()
    for para in body:
        events.append(("para", len(words), None))
        for token in re.split(r"(\[\d+[a-e]?\])", para):
            m = MREF_RE.fullmatch(token)
            if m:
                events.append(("mref", len(words), count.mref(m.group(1))))
                continue
            m = REF_RE.fullmatch(token)
            if m:
                events.append(("ref", len(words), count.ref(int(m.group(1)))))
                continue
            words.extend(words_of(token))
    return words, events, notes


# -- scoring -----------------------------------------------------------------------------
def score(ours_path: str, verbose=False, pages=PAGES) -> dict[str, float]:
    """Print the scores (and with ``verbose`` every difference, or only those of the
    sections named in it: words, para, refs, notes, mref); return the main ones."""

    shown: dict[str, int] = {}

    def shows(section: str) -> bool:
        """Whether to print a difference of ``section`` (at most 30 each with --show)."""
        if not (verbose is True or (bool(verbose) and section in verbose)):
            return False
        shown[section] = shown.get(section, 0) + 1
        return verbose is True or shown[section] <= 30

    gw, gev, gnotes = good_truth(pages)
    ow, oev, onotes = our_side(ours_path)
    sm = difflib.SequenceMatcher(None, gw, ow, autojunk=False)
    # Good words before our first / after our last match are outside our range.
    blocks = [b for b in sm.get_matching_blocks() if b.size]
    g_lo, g_hi = blocks[0].a, blocks[-1].a + blocks[-1].size
    g2o = {}
    for b in blocks:
        for k in range(b.size):
            g2o[b.a + k] = b.b + k
    ops = [op for op in sm.get_opcodes() if op[0] != "equal" and op[2] > g_lo and op[1] < g_hi]
    # A long stretch of good text we lack entirely: a page the scan doesn't have.
    gaps = [op for op in ops if op[2] - op[1] > 30 and op[4] - op[3] < 3]
    ops = [op for op in ops if op not in gaps]
    gap_words = sum(i2 - i1 for _, i1, i2, _, _ in gaps)
    errors = sum(max(i2 - i1, j2 - j1) for _, i1, i2, j1, j2 in ops)
    total = g_hi - g_lo - gap_words
    print(
        f"WORDS  good={total} ours={len(ow)}  word error rate={errors / total:.1%}"
        f"  (not in the scan: {gap_words} words)"
    )
    for _, i1, i2, _, _ in gaps:
        print(f"   not in the scan: {' '.join(gw[i1 : i1 + 8])} ... {' '.join(gw[i2 - 5 : i2])}")
    if shows("words"):
        for op, i1, i2, j1, j2 in ops[:400]:
            print(f"   {op:7} good={' '.join(gw[i1:i2])!r} ours={' '.join(ow[j1:j2])!r}")

    def near(gi: int) -> int | None:
        for d in range(0, 4):
            for k in (gi - d, gi + d):
                if k in g2o:
                    return g2o[k] + (gi - k)
        return None

    # Paragraph starts
    gpara = [i for kind, i, _ in gev if kind == "para" and g_lo <= i < g_hi]
    o_lo = near(g_lo) or 0  # our front matter (title pages) is outside the good range
    opara = {i for kind, i, _ in oev if kind == "para" and i >= o_lo}
    hit = [i for i in gpara if near(i) is not None and any(abs(near(i) - o) <= 1 for o in opara)]
    missed = [i for i in gpara if i not in hit]
    good_set = {near(i) for i in gpara}
    extra = [o for o in opara if not any(g is not None and abs(g - o) <= 1 for g in good_set)]
    print(f"PARAGRAPHS good={len(gpara)} found={len(hit)} missed={len(missed)} extra={len(extra)}")
    if shows("para"):
        for i in missed[:25]:
            print("   missed start:", " ".join(gw[max(0, i - 4) : i]), "|", " ".join(gw[i : i + 6]))
        for o in sorted(extra)[:25]:
            print("   extra break: ", " ".join(ow[max(0, o - 4) : o]), "|", " ".join(ow[o : o + 6]))

    # Footnote references: present at the right word?
    oref = {v: i for kind, i, v in oev if kind == "ref"}
    gref = [(v, i) for kind, i, v in gev if kind == "ref" and g_lo <= i <= g_hi]
    ok = wrong_place = missing = 0
    for key, i in gref:
        part, n = key
        if key not in oref:
            missing += 1
            if shows("refs"):
                print(f"   ref missing {part} {n}: ...{' '.join(gw[max(0, i - 5) : i])}")
            continue
        target = near(i)
        if target is not None and abs(oref[key] - target) <= 1:
            ok += 1
        else:
            wrong_place += 1
            if shows("refs"):
                at = oref[key]
                print(
                    f"   ref misplaced {part} {n}: good ...{' '.join(gw[max(0, i - 4) : i])}"
                    f" | ours ...{' '.join(ow[max(0, at - 4) : at])}"
                )
    extra_refs = len(oref) - ok - wrong_place
    print(
        f"REFS   good={len(gref)} ok={ok} misplaced={wrong_place} missing={missing}"
        f" extra={extra_refs}"
    )

    # Note texts
    used = {key for key, i in gref}
    sims = []
    for key, text in sorted(gnotes.items()):
        part, n = key
        if key not in used:
            continue
        ours = onotes.get(key, "")
        ratio = difflib.SequenceMatcher(None, words_of(text), words_of(ours)).ratio()
        sims.append(ratio)
        if shows("notes") and ratio < 0.9:
            print(f"   note {part} {n} sim={ratio:.2f}")
            print(f"      good: {text[:160]}\n      ours: {ours[:160]}")
    good_notes = sum(1 for s in sims if s >= 0.9)
    print(
        f"NOTES  good={len(sims)} ours={len(onotes)} close(>=0.9)={good_notes}"
        f" mean similarity={sum(sims) / max(1, len(sims)):.2f}"
    )

    # Margin references: on the right line?
    omref = {}
    for kind, i, v in oev:
        if kind == "mref":
            omref.setdefault(v, i)
    gm = [v for kind, _, v in gev if kind == "mref" and g_lo <= v[1] < g_hi]
    m_ok = m_missing = m_wrong = 0
    for label, start, end in gm:
        if label not in omref:
            m_missing += 1
            if shows("mref"):
                print(f"   mref missing {label}: line {' '.join(gw[start:end])[:60]}")
            continue
        lo, hi = near(start), near(end)
        at = omref[label]
        if lo is not None and hi is not None and lo - 1 <= at <= hi + 1:
            m_ok += 1
        else:
            m_wrong += 1
            if shows("mref"):
                print(
                    f"   mref {label} wrong line: ours before {' '.join(ow[at : at + 6])!r}"
                    f" | good lines {' '.join(gw[start:end])!r}"
                )
    extra_m = len(omref) - m_ok - m_wrong
    print(
        f"MARGIN good={len(gm)} ok={m_ok} wrong line={m_wrong} missing={m_missing} extra={extra_m}"
    )
    return {
        "word_error_rate": errors / total,
        "paragraph_extra": len(extra),
        "paragraph_missed": len(missed),
        "refs_ok": ok,
        "notes_mean": sum(sims) / max(1, len(sims)),
        "margin_ok": m_ok,
    }


if __name__ == "__main__":
    pages = PAGES
    if "--pages" in sys.argv:
        first, last = sys.argv[sys.argv.index("--pages") + 1].split("-")
        pages = range(int(first), int(last) + 1)
    verbose = "--verbose" in sys.argv
    if "--show" in sys.argv:  # --show refs,mref
        verbose = set(sys.argv[sys.argv.index("--show") + 1].split(","))
    score(sys.argv[1], verbose, pages)
