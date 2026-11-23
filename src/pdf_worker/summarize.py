"""Summaries of a converted book, part by part, from its saved blocks (``blocks_file``).

The book's headings make an outline (``load_outline``); the parts asked for (``select``)
are summarized down to a level of that outline (``summarize``) by a chat model
(``ModelChat``: OpenRouter's free models, through ai-client), and the summary is written
like a book (``write_summary``). Every answer is cached beside the blocks file, so a run
stopped by the daily quota resumes where it stopped.
"""

import hashlib
import json
import os
import re
import tempfile
import time
import unicodedata
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field, replace
from pathlib import Path

import ai_client

from pdf_worker.blocks_file import read_blocks, read_metadata, write_blocks
from pdf_worker.convert import FORMATS, write_format
from pdf_worker.errors import PdfWorkerError
from pdf_worker.inbox import BLOCKS, INBOX, OUTBOX, WORK
from pdf_worker.inline import (
    BOLD,
    END_BOLD,
    END_ITALIC,
    ITALIC,
    Style,
    is_contents_entry,
    pieces,
    plain,
    styled,
)
from pdf_worker.output import Metadata
from pdf_worker.structure import (
    REF_RE,
    Block,
    Heading,
    ListItem,
    Paragraph,
    SectionStart,
    Table,
)

PROMPT_VERSION = 2  # part of every cache key: change it when the prompts change
CEILING_WORDS = 30_000  # a part longer than this is summarized from its pieces' summaries
PIECE_WORDS = 1_500  # longer parts are summarized in pieces: models keep more of short texts
SHORT_WORDS = 80  # a part shorter than this is quoted, not summarized
DETAIL = {"brief": 8, "normal": 15, "full": 30}  # the summary's usual share of the original, %
TOKENS_PER_WORD = 1.6
DEFAULT_CONTEXT = 32_000  # tokens, for a model the catalogue doesn't size
PROMPT_WORDS = 600  # room for the instructions and the part's heading path
ECHO_WORDS = 100  # a heading with more text of its own is no outline echo
BODY_WORDS = 300 # a part with this much text of its own: the book's body has started
SKIP_TITLES = {
    "contents",
    "indice",
    "sumario",
    "tabla de contenido",
    "bibliografia",
    "bibliography",
    "references",
    "referencias",
    "obras citadas",
    "index",
    "notas",
    "notes",
}
SKIP_SECTIONS = {"contents", "notes", "bibliography", "index"}  # SectionStart kinds
SUMMARY_WORD = {
    "es": "Resumen",
    "en": "Summary",
    "fr": "Résumé",
    "it": "Riassunto",
    "de": "Zusammenfassung",
    "pt": "Resumo",
    "la": "Summarium",
}
MISSING_LABEL = {"es": "Términos destacados", "en": "Highlighted terms"}

SYSTEM = (
    "You write a faithful summary of one part of an academic or religious text. Use only "
    "what the text says, no outside knowledge. Keep the main ideas: the part's thesis, each "
    "step of its argument, key definitions and distinctions, and its conclusions. Keep who "
    "holds each main idea: tell the author's own views apart from those of anyone quoted "
    "(a Father of the Church, a Pope, a philosopher, Scripture). Quote only a sentence that "
    "carries a thesis; give another quotation's point in a few words, or leave it out. "
    "Leave out explanations of metaphors, lists of examples or items (say what they have "
    "in common instead), supporting quotations, digressions, repetition and restatements "
    "of a point already made. Keep technical and doctrinal terms and Latin or Greek terms "
    "as the text has them. Aim for about {percent}% of the original. Write prose "
    "paragraphs only: no headings, no lists, no Markdown, no preamble. Write in the "
    "language with the code '{lang}'."
)
TARGET = (
    " Write about {target} words: the original has {original}. Reach that length by "
    "saying each idea in fewer words, not by leaving ideas out."
)
PART = "Part (where it sits in the book; headings, not text to summarize): "
PIECE = "This is piece {k} of {n} of the part"
GOES_ON = " and continues the previous one: don't introduce the part again."
PREVIOUS = "The summary of the previous piece ends: «{previous}». Don't repeat it."
MERGE = (
    "The text below holds summaries of the part's pieces, each after its title, after the "
    "part's own text if it has any. Merge them into one summary of the whole part: usually "
    "about {percent}% of the {original} words of the original they stand for."
)
KEEP = (
    "Use each of these phrases word for word, in the original language, without "
    "formatting: {phrases}"
)
RETRY = "\n\nYour last answer had {words} words; this part needs about {guide}. Write it again."
FOLLOW = (
    "\n\nYour summary:\n\n{answer}\n\nWrite it again so that it also uses, word for word, "
    "these phrases it left out: {missing}"
)

MODELS = ("baidu/ernie-5.5-flash-preview:free", "nvidia/nemotron-3-ultra-550b-a55b:free")
WAITS = (30, 60, 120, 300, 600)  # s before each new try of a model that is down
_sleep = time.sleep  # tests replace it

_STYLE_MARK ={(True, True): ITALIC, (True, False): END_ITALIC, (False, True): BOLD}
# Numbering before a title: "II. ", "3 ", "1.2) ", "IV.- ".
_NUMBERING_RE = re.compile(r"^(?:(?:\d+(?:\.\d+)*|[IVXLC]+)(?:[.)\-–—:]+\s*|\s+))+")
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)*[.)]?|[ivxlc]+[.)]")  # a path part that is a numbering
_DAILY_RE = re.compile(r"per[- ]?day|free-models-per-day", re.IGNORECASE)
_PHRASE_STRIP = " \t\n.,;:!?¡¿\"'«»“”‘’„()[]{}—–-"


class SummarizeError(PdfWorkerError):
    pass


@dataclass(eq=False)
class Node:
    title: str  # plain
    level: int  # the Heading's
    paragraphs: list[str] = field(default_factory=list)  # own text, style markers kept
    children: list["Node"] = field(default_factory=list)
    parent: "Node | None" = field(default=None, repr=False)
    number: int = 0  # 1..n in reading order
    depth: int = 0  # 1 = a top heading

    @property
    def bold(self) -> list[str]:
        return _bold(self.paragraphs)

    @property
    def words(self) -> int:
        return _words(self.paragraphs) + sum(child.words for child in self.children)


@dataclass
class Outline:
    meta: Metadata
    root: Node  # no title; its children are the top headings

    def nodes(self) -> list[Node]:
        return list(_walk(self.root))


def find_blocks(path: str | Path) -> Path:
    """The blocks file for ``path``: a ``.blocks.jsonl``, a work folder holding one, or a
    book in ``file_inbox/`` (its work folder's)."""
    path = Path(path)
    if path.name.endswith(BLOCKS) and path.is_file():
        return path
    folder = path
    if path.parent.name == INBOX:
        folder = path.parent.parent / WORK / path.name
    found = sorted(folder.glob(f"*{BLOCKS}")) if folder.is_dir() else []
    if len(found) != 1:
        what = "several blocks files" if found else "no blocks file"
        raise SummarizeError(f"{what} for {path} (convert the book first)")
    return found[0]


def load_outline(path: str | Path, skip: Iterable[str] = ()) -> Outline:
    """The book's headings as a tree, each with its own text; contents, notes, indexes,
    bibliographies, an outline echoed before the body and the ``skip`` titles left out."""
    root = Node("", 0)
    stack = [root]
    dropping = False
    for block in read_blocks(path):
        if isinstance(block, SectionStart):
            dropping = block.kind in SKIP_SECTIONS
        elif dropping:
            continue
        elif isinstance(block, Heading):
            while stack[-1] is not root and stack[-1].level >= block.level:
                stack.pop()
            node = Node(" ".join(_clean(block.text, plain_text=True).split()), block.level)
            stack[-1].children.append(node)
            stack.append(node)
        elif text := _text(block):
            stack[-1].paragraphs.append(text)
    prefixes = tuple(prefix.casefold() for prefix in skip)
    _prune(root, lambda n: _norm(n.title) in SKIP_TITLES or n.title.casefold().startswith(prefixes))
    _link(root, 0)
    _drop_echo(root)
    _link(root, 0)
    for number, node in enumerate(_walk(root), 1):
        node.number = number
    return Outline(read_metadata(path), root)


def select(outline: Outline, specs: Iterable[int | str]) -> list[Node]:
    """The parts named by ``specs``: numbers, or heading paths "II. > 1." whose every part
    starts a descendant's title (case ignored). No specs: the top headings."""
    specs = list(specs)
    if not specs:
        return list(outline.root.children)
    nodes = outline.nodes()
    chosen = []
    for spec in specs:
        if isinstance(spec, int) or str(spec).strip().isdigit():
            number = int(spec)
            if not 1 <= number <= len(nodes):
                raise SummarizeError(f"no part {number}: the parts are 1 to {len(nodes)}")
            chosen.append(nodes[number - 1])
            continue
        found = [outline.root]
        for part in str(spec).split(">"):
            prefix = " ".join(part.split()).casefold()
            matches = [m for f in found for m in _matching(f, prefix)]
            if len(matches) != 1:
                shown = matches or [c for f in found for c in f.children]
                listed = "; ".join(f"{n.number} {n.title}" for n in shown[:30])
                what = "several parts match" if matches else "no part matches"
                raise SummarizeError(f"{what} {part.strip()!r} in {spec!r}: {listed}")
            found = matches
        chosen.append(found[0])
    return chosen


def estimate(
    outline: Outline, nodes: list[Node], level: int | str, cache_path: str | Path, **opts
) -> int:
    """The requests ``summarize`` makes at most (cached answers cost none)."""
    # shortcut: sized for PIECE_WORDS; a model with a smaller context splits more parts.
    return _count(outline, nodes, level, cache_path, min(PIECE_WORDS, CEILING_WORDS), **opts)


def summarize(
    outline: Outline,
    nodes: list[Node],
    level: int | str,
    chat,
    cache_path: str | Path,
    lang: str | None = None,
    detail: str = "normal",
    keep_bold: bool = False,
    fresh: bool = False,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> list[Block]:
    """Headings and summary paragraphs for ``nodes`` down to ``level`` (an outline depth,
    0: one summary per node, "all": the deepest). ``chat(system, user) -> (text, model)``."""
    opts = {"lang": lang, "detail": detail, "keep_bold": keep_bold, "fresh": fresh}
    limit = min(PIECE_WORDS, CEILING_WORDS, chat.context_words())
    total = _count(outline, nodes, level, cache_path, limit, **opts)
    run = _Run(outline, chat, cache_path, limit, True, on_progress, total, **opts)
    try:
        return run.blocks(_plan(outline, nodes, level))
    except SummarizeError as error:
        again = "run again without --fresh to continue" if fresh else "run again to continue"
        raise SummarizeError(
            f"stopped after {run.requests} of {total} requests ({error}); they are cached, "
            + again
        ) from error


def summary_meta(meta: Metadata, lang: str | None = None) -> Metadata:
    """The book's metadata for its summary: "Resumen: <title>"."""
    lang = lang or meta.language
    word = SUMMARY_WORD.get(lang.split("-")[0], SUMMARY_WORD["en"])
    return replace(meta, title=f"{word}: {meta.title}", language=lang)


def write_summary(
    blocks: list[Block], meta: Metadata, out_dir: str | Path, name: str, formats: Iterable[str]
) -> list[Path]:
    """``<name>.blocks.jsonl`` and ``<name>.<format>`` for each format, in ``out_dir``."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    saved = out_dir / f"{name}{BLOCKS}"
    write_blocks(blocks, meta, saved)
    written = [saved]
    for fmt in formats:
        path = out_dir / f"{name}{FORMATS[fmt]}"
        write_format(fmt, read_blocks(saved), path, meta, "none", True, lambda *a: None)
        written.append(path)
    return written


def summary_name(stem: str, level: int | str, nodes: list[Node]) -> str:
    """``<stem>.summary-<level>``, with ``-s<numbers>`` for chosen parts (none: the book)."""
    chosen = f"-s{'-'.join(str(node.number) for node in nodes)}" if nodes else ""
    return f"{stem}.summary-{level}{chosen}"


def default_out_dir(blocks_path: str | Path) -> Path:
    """``<root>/file_outbox`` for a work folder's blocks file, else its own folder."""
    folder = Path(blocks_path).parent
    if folder.parent.name == WORK:
        return folder.parent.parent / OUTBOX
    return folder


class ModelChat:
    """``(system, user) -> (text, model)`` by the given model or else ``MODELS`` in turn:
    the first ai-client can use is kept; a down one is waited for (``WAITS``), a gone one
    is left for the next."""

    def __init__(self, model: str | None = None):
        self.client = ai_client.get_client("openrouter")
        self.candidates = [model] if model else list(MODELS)
        self.model: str | None = None  # the current one, chosen on first use
        self.notes: list[str] = []  # models left out, and why
        self.answered: dict[str, int] = {}
        self.on_wait: Callable[[str, int, int, Exception], None] | None = None

    def _next(self) -> str:
        """The first candidate left that ai-client can use; the ones before it are noted."""
        if not self.client.key:
            raise SummarizeError("OPENROUTER_API_KEY is not set")
        while self.candidates:
            why = self.client.problem(self.candidates[0])
            if not why:
                self.model = self.candidates[0]
                return self.model
            self.notes.append(f"{self.candidates.pop(0)} is {why}")
        raise SummarizeError("no model left: " + "; ".join(self.notes))

    def __call__(self, system: str, user: str) -> tuple[str, str]:
        model = self.model or self._next()
        waits = 0  # of WAITS, for this request
        while True:
            left = self.client.requests_left()
            if left is not None and left <= 0:
                raise SummarizeError("the free requests for today are used")
            try:
                text = self.client.chat(user, system, model=model, fallbacks=False, temperature=0.2)
            except ai_client.AIClientError as error:
                if error.per_day or _DAILY_RE.search(str(error)):
                    raise SummarizeError(f"the daily quota is used: {error}") from error
                # the catalog behind problem() is ai-client's, fetched again every 10 minutes
                why = self.client.problem(model)
                status = error.status
                if why:
                    self.notes.append(f"{self.candidates.pop(0)} is {why}")
                    model, waits = self._next(), 0
                elif status == "length" or (
                    isinstance(status, int) and 400 <= status < 500 and status not in (408, 429)
                ):  # the same request fails the same way: waiting won't help
                    raise SummarizeError(f"{model} refused the request ({error})") from error
                elif waits == len(WAITS):
                    raise SummarizeError(
                        f"{model} is down ({error}); run again later: finished parts are cached"
                    ) from error
                else:
                    if self.on_wait:
                        self.on_wait(model, WAITS[waits], waits + 1, error)
                    _sleep(WAITS[waits])
                    waits += 1
                continue
            self.answered[model] = self.answered.get(model, 0) + 1
            return text, model

    def context_words(self) -> int:
        """How many words of a part fit the current model's context, less the prompt and
        room for the answer."""
        entry = self.client.catalog().get(self.model or self._next(), {})
        words = (entry.get("context_length") or DEFAULT_CONTEXT) / TOKENS_PER_WORD
        return max(SHORT_WORDS, int(words * 2 / 3) - PROMPT_WORDS)

    def requests_left(self) -> int | None:
        return self.client.requests_left()


# The outline.


def _walk(node: Node) -> Iterator[Node]:
    """``node``'s descendants in reading order."""
    for child in node.children:
        yield child
        yield from _walk(child)


def _link(node: Node, depth: int) -> None:
    node.depth = depth
    for child in node.children:
        child.parent = node
        _link(child, depth + 1)


def _prune(node: Node, drop: Callable[[Node], bool]) -> None:
    node.children = [child for child in node.children if not drop(child)]
    for child in node.children:
        _prune(child, drop)


def _drop_echo(root: Node) -> None:
    """Drop the headings printed before the body (an outline) that recur later as
    headings, with their own text; their children move up in their place."""
    nodes = list(_walk(root))
    body = next((i for i, node in enumerate(nodes) if _words(node.paragraphs) >= BODY_WORDS), None)
    if body is None:
        return
    ancestors = {id(node) for node in _ancestors(nodes[body])}
    echo = set()
    for i, node in enumerate(nodes[:body]):
        title = _norm(node.title)
        later = (_norm(other.title) for other in nodes[i + 1 :])
        small = _words(node.paragraphs) < ECHO_WORDS
        if title and small and id(node) not in ancestors and title in later:
            echo.add(id(node))
    _splice(root, echo)


def _splice(node: Node, drop: set[int]) -> None:
    for child in node.children:
        _splice(child, drop)
    kept = []
    for child in node.children:
        kept += child.children if id(child) in drop else [child]
    node.children = kept


def _matching(node: Node, prefix: str) -> Iterator[Node]:
    """The highest descendants of ``node`` whose title starts with ``prefix`` (a bare
    numbering like "1." must be the title's whole number)."""
    exact = _NUMBER_RE.fullmatch(prefix)
    for child in node.children:
        title = " ".join(child.title.split()).casefold()
        if (
            title.split(" ")[0].rstrip(".)") == prefix.rstrip(".)")
            if exact
            else title.startswith(prefix)
        ):
            yield child
        else:
            yield from _matching(child, prefix)


def _norm(title: str) -> str:
    """A title without its numbering and accents, casefolded."""
    title = _NUMBERING_RE.sub("", title.strip())
    title = unicodedata.normalize("NFKD", title)
    title = "".join(c for c in title if not unicodedata.combining(c))
    return " ".join(title.casefold().split()).strip(" .:;")


def _clean(text: str, plain_text: bool = False) -> str:
    """Block text without note references, page marks, links and margin references;
    style markers kept unless ``plain_text``."""
    out = []
    for piece in pieces(REF_RE.sub("", text)):
        if isinstance(piece, str):
            out.append(piece)
        elif isinstance(piece, Style) and not plain_text:
            out.append(_STYLE_MARK.get((piece.italic, piece.on), END_BOLD))
    return "".join(out)


def _text(block: Block) -> str:
    if isinstance(block, Paragraph) and not is_contents_entry(block.text):
        return _clean(block.text).strip()
    if isinstance(block, ListItem):
        return _clean(f"{block.label} {block.text}").strip()
    if isinstance(block, Table):
        return "\n".join(" | ".join(_clean(cell) for cell in row) for row in block.rows)
    return ""


def _words(texts: Iterable[str]) -> int:
    return sum(len(plain(text).split()) for text in texts)


def _bold(texts: Iterable[str]) -> list[str]:
    """The bold phrases of ``texts``: spans apart by whitespace only joined, punctuation
    and quotes around them dropped, those under 3 characters left out, each once."""
    phrases = []
    for text in texts:
        runs, bold = [], False
        for piece in pieces(text):
            if isinstance(piece, Style) and not piece.italic:
                bold = piece.on
            elif isinstance(piece, str):
                runs.append(piece if bold or not piece.strip() else "\0")
        for span in "".join(runs).split("\0"):
            span = " ".join(span.split()).strip(_PHRASE_STRIP)
            if len(span) >= 3 and span not in phrases:
                phrases.append(span)
    return phrases


# What is shown.


def _plan(outline: Outline, nodes: list[Node], level: int | str) -> list[tuple]:
    """(node, summarized, introduction) in reading order: the chosen nodes' ancestors and
    the nodes down to ``level`` as headings, summaries at ``level`` and on leaves above."""
    depth = max((node.depth for node in outline.nodes()), default=0) if level == "all" else level
    depth = int(depth)
    shown: set[int] = set()
    plan = []

    def walk(node: Node, intro: list) -> None:
        if id(node) in shown:
            return
        shown.add(id(node))
        if depth == 0 or node.depth >= depth or not node.children:
            plan.append((node, True, intro))
            return
        plan.append((node, False, []))
        intro = [*intro, (node.title, node.paragraphs)] if node.paragraphs else intro
        for i, child in enumerate(node.children):
            walk(child, intro if i == 0 else [])

    picked = {id(node) for node in nodes}
    for chosen in sorted(nodes, key=lambda node: node.number):
        if any(id(a) in picked for a in _ancestors(chosen)[:-1]):
            continue  # inside another chosen part
        for ancestor in _ancestors(chosen)[:-1]:
            if id(ancestor) not in shown:
                shown.add(id(ancestor))
                plan.append((ancestor, False, []))
        walk(chosen, [])
    return plan


def _ancestors(node: Node) -> list[Node]:
    """From the top heading down to ``node`` itself."""
    path = []
    while node is not None and node.depth > 0:
        path.append(node)
        node = node.parent
    return path[::-1]


def _units(node: Node, intro: list, descendants: bool = True, labels: bool = True) -> list[str]:
    """A part's input: the forwarded introduction (each after a label line), its own text,
    its descendants' with their titles."""
    units = []
    for title, paragraphs in intro:
        units += [f"Introduction to {title}"] * labels + paragraphs
    units += node.paragraphs
    for child in _walk(node) if descendants else ():
        units += [child.title, *child.paragraphs]
    return units


class _Run:
    def __init__(self, outline, chat, cache_path, limit, write, on_progress=None, total=0, **opts):
        self.meta, self.chat, self.limit, self.write = outline.meta, chat, limit, write
        self.cache_path = Path(cache_path)
        self.cache = (
            json.loads(self.cache_path.read_text("utf-8")) if self.cache_path.exists() else {}
        )
        self.lang = opts["lang"] or outline.meta.language
        self.detail, self.percent = opts["detail"], DETAIL[opts["detail"]]
        self.keep_bold, self.fresh = opts["keep_bold"], opts["fresh"]
        self.on_progress, self.total, self.requests = on_progress, total, 0

    def blocks(self, plan: list[tuple]) -> list[Block]:
        out: list[Block] = []
        for node, summarized, intro in plan:
            out.append(Heading(node.title, node.level))
            if summarized:
                text = self.summary(node, intro)
                phrases = _bold(_units(node, intro)) if self.keep_bold else []
                out += _paragraphs(text, phrases, self.lang)
        return out

    def summary(self, node: Node, intro: list = ()) -> str:
        """The node's summary, by the rule for its size: quoted, asked, or from its
        children's (or, for a leaf, its pieces') summaries: joined at full detail, else
        merged."""
        path = " > ".join(n.title for n in _ancestors(node))
        units = _units(node, list(intro))
        words = _words(units)
        phrases = _bold(units) if self.keep_bold else []
        if words < SHORT_WORDS:
            quoted = _units(node, list(intro), labels=False)
            return "\n\n".join(plain(unit) for unit in quoted)
        if words <= self.limit:
            return self.ask(path, units, words, phrases)
        if self.detail == "full":
            if not node.children:
                return "\n\n".join(self.pieces(path, units))
            own = self.summary(replace(node, children=[]), intro)
            parts = [own, *(self.summary(child) for child in node.children)]
            return "\n\n".join(part for part in parts if part)
        if node.children:
            own = _units(node, list(intro), descendants=False)
            parts = self.pieces(path, own) if _words(own) > self.limit else own
            for child in node.children:
                parts += [child.title, self.summary(child)]
            return self.ask(path, parts, words, phrases, merge=True)
        return self.ask(path, self.pieces(path, units), words, phrases, merge=True)

    def pieces(self, path: str, units: list[str]) -> list[str]:
        """Summaries of ``units`` in pieces under the limit, split at paragraph ends."""
        parts, chunk = [], []
        for unit in units:
            if chunk and _words([*chunk, unit]) > self.limit:
                parts.append(chunk)
                chunk = []
            chunk.append(unit)
        parts.append(chunk)
        answers: list[str] = []  # in order: each piece is told how the previous one ended
        for k, chunk in enumerate(parts, 1):
            bold = _bold(chunk) if self.keep_bold else []
            previous = answers[-1].split("\n\n")[-1] if answers else ""
            piece = (k, len(parts), previous) if len(parts) > 1 else None
            answers.append(self.ask(path, chunk, _words(chunk), bold, piece=piece))
        return answers

    def ask(
        self,
        path: str,
        units: list[str],
        original: int,
        phrases: list[str],
        merge=False,
        piece: tuple[int, int, str] | None = None,
    ) -> str:
        text = "\n\n".join(plain(unit) for unit in units)
        guide = round(original * self.percent / 100)
        user = f"Book: {self.meta.title}\n{PART}{path}\n"
        if piece:
            k, n, previous = piece
            user += PIECE.format(k=k, n=n) + (GOES_ON if k > 1 else ".") + "\n"
            if k > 1:
                user += PREVIOUS.format(previous=previous) + "\n"
        if merge:
            user += MERGE.format(percent=self.percent, original=original) + "\n"
        if phrases:
            user += KEEP.format(phrases="; ".join(phrases)) + "\n"
        user += f"\n---\n\n{text}"
        key = json.dumps(
            [PROMPT_VERSION, user, self.lang, self.detail, phrases], ensure_ascii=False
        )
        key = hashlib.sha256(key.encode("utf-8")).hexdigest()
        if not self.fresh and key in self.cache:
            return self.cache[key]["summary"]
        system = SYSTEM.format(percent=self.percent, lang=self.lang)
        system += TARGET.format(target=guide, original=original)
        answer, model = self.send(system, user, path)
        try:
            words = len(answer.split())
            # <=: an empty answer retries even when the guide rounds to 0 (so _count sees it)
            if words > len(text.split()) or words <= guide / 10:
                retry = RETRY.format(words=words, guide=guide)
                answer, model = self.send(system, user + retry, path)
            missing = [phrase for phrase in phrases if not _find(answer, phrase)]
            if missing:
                follow = FOLLOW.format(answer=answer, missing="; ".join(missing))
                again, model = self.send(system, user + follow, path)
                answer = again or answer
        except SummarizeError:
            if self.write and answer:  # keep the answer already paid for
                self.cache[key] = {"summary": answer, "model": model}
                _save(self.cache, self.cache_path)
            raise
        if self.write:
            self.cache[key] = {"summary": answer, "model": model}
            _save(self.cache, self.cache_path)
        return answer

    def send(self, system: str, user: str, path: str) -> tuple[str, str]:
        text, model = self.chat(system, user)
        self.requests += 1
        if self.on_progress:
            self.on_progress(self.requests, self.total, path)
        return _strip_markdown(text), model


class _Counter:
    """A chat that answers nothing and counts: every part it is asked costs its retries."""

    def __init__(self, context: int):
        self.context, self.calls = context, 0

    def __call__(self, system: str, user: str) -> tuple[str, str]:
        self.calls += 1
        return "", ""

    def context_words(self) -> int:
        return self.context


def _count(outline, nodes, level, cache_path, limit, **opts) -> int:
    opts = {"lang": None, "detail": "normal", "keep_bold": False, "fresh": False, **opts}
    counter = _Counter(limit)
    _Run(outline, counter, cache_path, limit, write=False, **opts).blocks(
        _plan(outline, nodes, level)
    )
    return counter.calls


def _strip_markdown(text: str) -> str:
    """The answer without Markdown, one paragraph per line."""
    text = re.sub(r"\*\*|__|\*", "", text)
    lines = (re.sub(r"^\s*(?:#+|-)\s+", "", line) for line in text.splitlines())
    return "\n\n".join(" ".join(line.split()) for line in lines if line.strip())


def _find(text: str, phrase: str) -> tuple[int, int] | None:
    """Where ``phrase`` is in ``text``, as whole words (case, composed or decomposed
    accents and runs of whitespace ignored); the span is in ``text``'s own characters."""

    def fold(string: str) -> tuple[str, list[int], list[int]]:
        clusters: list[list[int]] = []  # a combining mark joins the character before it
        for i, char in enumerate(string):
            if clusters and unicodedata.combining(char):
                clusters[-1][1] = i + 1
            else:
                clusters.append([i, i + 1])
        chars, starts, ends = "", [], []
        for start, end in clusters:
            cluster = string[start:end]
            if cluster.isspace():
                if chars.endswith(" "):
                    continue
                cluster = " "
            folded = unicodedata.normalize("NFC", cluster).casefold()
            chars += folded
            starts += [start] * len(folded)
            ends += [end] * len(folded)
        return chars, starts, ends

    chars, starts, ends = fold(text)
    target = fold(phrase)[0].strip()
    start = chars.find(target) if target else -1
    while start >= 0:
        end = start + len(target)
        if not (start and chars[start - 1].isalnum()) and not (
            end < len(chars) and chars[end].isalnum()
        ):
            return starts[start], ends[end - 1]
        start = chars.find(target, start + 1)
    return None


def _paragraphs(text: str, phrases: list[str], lang: str) -> list[Block]:
    """The summary's paragraphs with ``phrases`` in bold; those it lacks listed last."""
    out: list[Block] = []
    found = set()
    for paragraph in text.split("\n\n"):
        if not paragraph.strip():
            continue
        spans = []
        for phrase in phrases:
            if span := _find(paragraph, phrase):
                found.add(phrase)
                if all(span[1] <= a or span[0] >= b for a, b in spans):
                    spans.append(span)
        for a, b in sorted(spans, reverse=True):
            paragraph = paragraph[:a] + styled(paragraph[a:b], bold=True) + paragraph[b:]
        out.append(Paragraph(paragraph))
    if missing := [phrase for phrase in phrases if phrase not in found]:
        label = MISSING_LABEL.get(lang.split("-")[0], MISSING_LABEL["en"])
        out.append(Paragraph(f"{label}: {'; '.join(missing)}"))
    return out


def _save(cache: dict, path: Path) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(cache, out, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)
