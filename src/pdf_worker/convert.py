"""Convert a PDF into a reflowable book: EPUB (Kindle-friendly), Markdown, HTML, clean
plain text, Word (.docx) or a reflowed PDF.

Pipeline: layout analysis -> footnote detection -> structure (headings, paragraphs,
notes) -> saved blocks (``pdf_worker.blocks_file``) -> one writer per format. Every
stage works page by page.
"""

import os
import re
import tempfile
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field, replace
from pathlib import Path

import pymupdf

from pdf_worker import (
    bilingual,
    book_metadata,
    follow_marks,
    font_sizes,
    glued_refs,
    margin_estimates,
    outline,
    pdf_tags,
)
from pdf_worker.blocks_file import read_blocks, write_blocks
from pdf_worker.cover import cover_jpeg
from pdf_worker.document import open_pdf
from pdf_worker.docx_export import write_docx
from pdf_worker.drop_notes import drop_notes
from pdf_worker.epub import write_epub
from pdf_worker.errors import PdfWorkerError
from pdf_worker.fixes import Review, default_fixes_path, read_fixes, write_fixes
from pdf_worker.html_export import write_html
from pdf_worker.index_links import link_index
from pdf_worker.inline import MARGIN_REF_RE, plain
from pdf_worker.layout import analyze_document
from pdf_worker.margin_refs import in_book, page_marks
from pdf_worker.markdown_export import write_markdown
from pdf_worker.marks import Settings
from pdf_worker.ocr_check import assess_text_layer
from pdf_worker.output import Metadata, WriteStats
from pdf_worker.structure import (
    REF_RE,
    Block,
    Heading,
    Image,
    ListItem,
    Note,
    Paragraph,
    iter_blocks,
)
from pdf_worker.text_export import write_text
from pdf_worker.tidy import tidy
from pdf_worker.typst_export import write_pdf

FORMATS = {
    "epub": ".epub",
    "md": ".md",
    "html": ".html",
    "txt": ".txt",
    "docx": ".docx",
    "pdf": ".pdf",
    "typ": ".typ",  # the reflowed PDF's Typst source
}
# Where a reflowed PDF sets its footnotes; "none" leaves notes out of every format.
NOTE_PLACES = ("page", "end", "none")

# Very common short words per language, for a cheap language guess.
_STOPWORDS = {
    "en": "the of and to in is that it for as with was on be by this are not",
    "es": "de la que el en los se del las por un con una para es al lo como más",
    "fr": "de la le les et des en du un une est que pour dans qui pas sur au",
    "de": "der die und den das ist des nicht ein eine zu mit von sich auf für",
    "it": "di il che la per un del non della le una sono con gli si è nel",
    "pt": "de que não do da em um para com uma os no se na por mais as dos",
    "la": "et in est non ad cum sed quod ut qui quae etiam enim esse sunt atque",
}
_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)


class UnsupportedFormatError(PdfWorkerError):
    """The requested output format is not supported."""


@dataclass
class ConvertReport:
    output_path: Path
    metadata: Metadata
    stats: WriteStats
    metadata_sources: dict[str, str] = field(default_factory=dict)  # field -> "title page"
    restored_refs: list[str] = field(default_factory=list)  # see pdf_worker.missing_refs
    fixes_path: Path | None = None  # the review file, see pdf_worker.fixes
    new_fixes: dict[str, int] = field(default_factory=dict)  # rows added, per kind
    facing_pages: int = 0  # left out: the original of a bilingual edition
    reread_words: int = 0  # garbled words read again (Greek), see pdf_worker.bilingual


def stopword_scores(text: str) -> dict[str, int]:
    """Stopword hits per ISO 639-1 language, e.g. ``{"en": 0, "es": 4, ...}``."""
    words = Counter(word.lower() for word in _WORD_RE.findall(text))
    return {
        language: sum(words[word] for word in stopwords.split())
        for language, stopwords in _STOPWORDS.items()
    }


def guess_language(text: str) -> str:
    """Best-guess ISO 639-1 code from stopword frequencies; ``en`` if unsure."""
    scores = stopword_scores(text)
    best = max(scores, key=scores.get)
    return best if scores[best] >= 5 else "en"


def default_output_path(pdf_path: str | Path, fmt: str) -> Path:
    """``book.pdf`` -> ``book.epub`` etc. A reflowed PDF is ``book.reflowed.pdf`` (not
    the input itself) and clean text ``book.clean.txt`` (``book.txt`` is extract-text's)."""
    suffix = {"pdf": ".reflowed.pdf", "txt": ".clean.txt"}.get(fmt, FORMATS[fmt])
    return Path(pdf_path).with_suffix(suffix)


def format_for_path(path: str | Path) -> str | None:
    suffix = Path(path).suffix.lower()
    return next((fmt for fmt, ext in FORMATS.items() if ext == suffix), None)


def convert_pdf(
    pdf_path: str | Path,
    output_path: str | Path,
    fmt: str = "epub",
    title: str | None = None,
    author: str | None = None,
    language: str | None = None,
    images: bool = True,
    cover: bool = True,
    notes_at: str = "end",
    paddle_rows: list[dict] | None = None,
    on_page: Callable[[int, int], None] | None = None,
    on_step: Callable[[str, str], Callable[[int, int], None]] | None = None,
    margin_refs: bool | None = None,
    estimate_margin_refs: bool = False,
    fixes_path: str | Path | None = None,
    source_pdf: str | Path | None = None,
    layout_rows: dict[int, dict] | None = None,
    marks: bool = True,
    tags: bool = True,
    sentence_check: bool = False,
    also: dict[str, str | Path] | None = None,
    blocks_path: str | Path | None = None,
) -> ConvertReport:
    """Convert ``pdf_path`` to ``fmt`` at ``output_path`` (written atomically), and to
    each format of ``also`` (format -> path). The book's structure is built once, saved
    to ``blocks_path`` (``pdf_worker.blocks_file``; default: a temporary file) and every
    format is written from it. The report's ``stats`` are ``fmt``'s.

    Title, author, translator, publisher and year not given are found in the book
    (``pdf_worker.book_metadata``); when ``pdf_path`` is an OCR'd copy, ``source_pdf`` is
    the original, whose PDF metadata and file name are used.

    ``images`` keeps the pictures; ``cover`` adds a text cover (title, author,
    translator; ``pdf_worker.cover``) to an EPUB, PDF or Word book; ``notes_at``
    ("end" or "page") places a PDF's footnotes, "none" drops the notes and their
    references in every format. With ``paddle_rows`` (PaddleOCR-VL's
    blocks, see ``paddle_ocr.paddle_pages``) the book is built from them instead of the
    PDF's text layer (``pdf_worker.paddle_book``); ``on_page(done, total)`` then
    follows the pages. Built from the text layer, ``on_step(step, unit)`` gives each slow
    step's ``on_page``. ``margin_refs`` keeps the margin references of classical editions
    ("22b", ``pdf_worker.margin_refs``); other books have none, and ink in their margins
    would only make false ones, so by default (None) they are kept only when found on
    enough pages (``margin_refs.in_book``). ``estimate_margin_refs`` (implies
    ``margin_refs``) adds those the scan lost between two found ones
    (``pdf_worker.margin_estimates``).
    The review file ``fixes_path`` (default ``<pdf stem>.fixes.tsv`` next to the PDF;
    ``pdf_worker.fixes``) is applied to the text, then updated with what looks wrong.
    ``layout_rows`` (``paddle_ocr.layout_pages``, books built from the text layer) go
    to the ``DocumentProfile``'s ``layout``; not used yet.
    With ``marks``, the book's marks file (``<pdf stem>.marks.json``, ``pdf_worker.marks``),
    if there is one, says which lines are running heads, page numbers, footnotes, note
    numbers... and where notes are printed (``pdf_worker.follow_marks``).
    With ``tags``, a tagged PDF's sound structure tree says which lines make a paragraph,
    list item or heading (``pdf_worker.pdf_tags``); furniture and page tops stay with the
    rules, the layout model's titles still count and the marks still win.
    With ``sentence_check``, a model settles the spelling flags from their sentences
    (``check.settle``; ``pdf_worker.fixes``).
    """
    if estimate_margin_refs:
        margin_refs = True
    outputs = {fmt: Path(output_path), **{f: Path(p) for f, p in (also or {}).items()}}
    for each, path in outputs.items():
        if each not in FORMATS:
            raise UnsupportedFormatError(
                f"Unsupported format {each!r}; choose from {sorted(FORMATS)}"
            )
        if path.resolve() == Path(pdf_path).resolve():
            raise UnsupportedFormatError(f"The output would overwrite the input: {path}")
    if notes_at not in NOTE_PLACES:
        raise UnsupportedFormatError(f"Notes go at {' or '.join(NOTE_PLACES)}, not {notes_at!r}")
    output_path = outputs[fmt]
    keep_images = images and set(outputs) != {"txt"}
    restored: list[str] = []
    source_pdf = source_pdf or pdf_path
    with open_pdf(source_pdf) as source:
        info = source.metadata or {}
    facing, reread, unsure = set(), 0, []
    greek: list[Paragraph] = []  # Greek paragraphs left out
    marked = follow_marks.load(pdf_path) if marks else None
    settings = marked.settings if marked else Settings()
    margin_marks = follow_marks.margin_boxes(marked) if marked else []
    if margin_refs is None and margin_marks:
        margin_refs = True  # the person marked some: the book has them

    steps = ["re-reading garbled words", "reading the layout", "building the book"]
    steps += ["laying out the PDF"] * ("pdf" in outputs) + ["sorting the flagged words"]

    def step(name: str, unit: str = "pages") -> Callable[[int, int], None] | None:
        if not on_step:
            return None
        return on_step(f"Step {steps.index(name) + 1}/{len(steps)}, {name}", unit)

    with open_pdf(pdf_path) as doc:
        in_section = follow_marks.page_sections(marked, doc.page_count) if marked else {}
        section_kinds = {index: section.kind for index, section in in_section.items()}
        left_out = {index for index, section in in_section.items() if not section.keep}
        if paddle_rows is not None:
            from pdf_worker.paddle_book import iter_paddle_blocks, text_sample

            sample = text_sample(paddle_rows)
            blocks = iter_paddle_blocks(
                doc,
                paddle_rows,
                images=keep_images,
                restored=restored,
                on_page=on_page,
                margin_refs=margin_refs,
                kinds=follow_marks.paddle_kinds(doc, paddle_rows, marked) if marked else None,
                numbering=settings.numbering,
                sections=section_kinds,
                skip=left_out,
                margin_marks=margin_marks,
            )
        else:
            font_sizes.mark_misreporting(doc)
            language, facing = bilingual.facing_pages(doc)
            reread, unsure = _reread_words(
                doc, language, facing, step("re-reading garbled words", "lines")
            )
            glued_refs.mark_glued_refs(doc, skip=facing)
            profile = analyze_document(
                doc,
                on_page=step("reading the layout"),
                notes=settings.notes,
                notes_pages={index for index, kind in section_kinds.items() if kind == "notes"},
                layout=layout_rows,
            )
            profile.tags = (tags and pdf_tags.read_tags(doc)) or {}
            profile.sections = section_kinds
            if marked:
                profile.kinds, profile.note_refs, profile.rule_levels = follow_marks.text_kinds(
                    doc, marked
                )
            sample = profile.text_sample
            blocks = iter_blocks(
                doc,
                profile,
                images=keep_images,
                skip=facing | left_out,
                on_page=step("building the book"),
            )
            blocks = bilingual.drop_greek(blocks, greek, language, bool(facing))
            if margin_refs is None:
                with_refs = sum(bool(page_marks(p)) for p in doc)
                margin_refs = profile.bracketed_refs or in_book(with_refs, doc.page_count)
            if not margin_refs:
                blocks = _without_margin_refs(blocks)
            elif profile.bracketed_refs:
                blocks = margin_estimates.recover_margin_refs(blocks)
        meta, sources = book_metadata.find_metadata(
            doc,
            list(_title_page_texts(doc, paddle_rows)),
            info,
            source_pdf,
            language or guess_language(sample),
            title=title,
            author=author,
        )
        if estimate_margin_refs:
            blocks = margin_estimates.estimate_margin_refs(blocks)
        fixes_path = Path(fixes_path) if fixes_path else default_fixes_path(pdf_path)
        # Born-digital text is checked too: its rare words, once kept, teach the check.
        source = fixes_path.name.removesuffix(".fixes.tsv")
        scanned = paddle_rows is not None or assess_text_layer(doc).scanned_pages >= 0.5
        review = Review(
            read_fixes(fixes_path),
            meta.language,
            source=source,
            italics=scanned,
            sentence_check=sentence_check,
        )
        blocks = _referenced_notes(tidy(review.apply(blocks), meta.language))
        if notes_at == "none":
            blocks = drop_notes(blocks)
        if marked:
            blocks = follow_marks.sections(blocks, marked)
        saved = Path(blocks_path) if blocks_path else None
        if saved is None:
            handle, name = tempfile.mkstemp(dir=output_path.parent, suffix=".blocks.jsonl")
            os.close(handle)
        try:
            if scanned:
                write_blocks(blocks, meta, saved or name)
            else:
                # Two passes over the saved blocks: the headings' levels, then the book.
                handle, built = tempfile.mkstemp(dir=output_path.parent, suffix=".blocks.jsonl")
                os.close(handle)
                try:
                    write_blocks(blocks, meta, built)
                    levels = outline.collect(read_blocks(built), doc.get_toc(), bool(marked))
                    write_blocks(outline.apply(read_blocks(built), levels), meta, saved or name)
                finally:
                    Path(built).unlink(missing_ok=True)
            written = {
                each: _write(each, read_blocks(saved or name), path, meta, notes_at, cover, step)
                for each, path in outputs.items()
            }
        finally:
            if saved is None:
                Path(name).unlink(missing_ok=True)
        stats = written[fmt]
    for index, kind, taken, other in unsure:  # re-read words to check (bilingual.mark_words)
        labels = profile.page_labels
        page = labels[index] if index < len(labels) else str(index + 1)
        review.flag(kind, page, taken, other)
    new_fixes = review.finish(on_word=step("sorting the flagged words", "words"))
    if greek:
        labels = profile.page_labels
        new_fixes["greek-dropped"] = review.left_out(
            "greek-dropped",
            [
                (labels[b.page] if 0 <= b.page < len(labels) else str(b.page + 1), plain(b.text))
                for b in greek
            ],
        )
    if review.fixes:
        write_fixes(fixes_path, review.fixes)
    return ConvertReport(
        output_path=output_path,
        metadata=meta,
        stats=stats,
        metadata_sources=sources,
        restored_refs=restored,
        fixes_path=fixes_path if review.fixes else None,
        new_fixes=new_fixes,
        facing_pages=len(facing),
        reread_words=reread,
    )


def _write(
    fmt: str, blocks: Iterator[Block], path: Path, meta, notes_at, cover, step
) -> WriteStats:
    """Write the saved ``blocks`` as ``fmt``: index entries linked where links work,
    no pictures in plain text."""
    if fmt == "txt":
        blocks = (block for block in blocks if not isinstance(block, Image))
    if fmt in ("epub", "html", "pdf", "typ"):
        blocks = link_index(blocks)
    if fmt == "epub":
        return write_epub(blocks, path, meta, cover=cover_jpeg(meta) if cover else None)
    if fmt in ("pdf", "typ"):
        return write_pdf(
            blocks,
            path,
            meta,
            notes_at=notes_at,
            cover=cover,
            on_pass=step("laying out the PDF", "passes") if fmt == "pdf" else None,
        )
    if fmt == "docx":
        return write_docx(blocks, path, meta, cover=cover)
    writer = {"md": write_markdown, "html": write_html, "txt": write_text}[fmt]
    return writer(blocks, path, meta)


def _reread_words(
    doc: pymupdf.Document,
    language: str,
    facing: set[int],
    on_line: Callable[[int, int], None] | None,
) -> tuple[int, list[tuple[int, str, str, str]]]:
    """Garbled words read again (``bilingual.mark_words``), when Tesseract has the models."""
    from pdf_worker.ocr import GREEK_LANGUAGE, TESSERACT_CODES, available_languages, tesseract_path

    code = TESSERACT_CODES.get(language)
    try:
        if not code or not {code, GREEK_LANGUAGE} <= available_languages():
            return 0, []
        greek = bilingual.quotes_greek(doc, facing)
        return bilingual.mark_words(
            doc, tesseract_path(), language, facing, on_line=on_line, greek=greek
        )
    except PdfWorkerError:  # no Tesseract
        return 0, []


def _title_page_texts(doc, paddle_rows: list[dict] | None) -> Iterator[str]:
    """The text blocks of the first pages: title page, copyright page."""
    if paddle_rows is not None:
        for row in sorted(paddle_rows, key=lambda r: r["page"]):
            if row["page"] < book_metadata.PAGES:
                yield from (b.get("text", "") for b in row["blocks"])
    for page_no in range(min(book_metadata.PAGES, doc.page_count)):
        yield from (b[4] for b in doc.load_page(page_no).get_text("blocks"))


def _referenced_notes(blocks: Iterable[Block]) -> Iterator[Block]:
    """Leave out notes of the notes section that nothing in the text refers to (an
    reference OCR lost, or one on pages not converted), and stand-ins for missing notes
    whose reference went (a page number's digit read as one, dropped with it). They come
    after their references, unlike a page's footnotes, which are kept."""
    seen: set[str] = set()
    for block in blocks:
        stray = isinstance(block, Note) and block.label.startswith(("c", "o"))
        if stray and block.label not in seen:
            continue
        if isinstance(block, Heading | Paragraph | ListItem | Note):
            seen.update(REF_RE.findall(block.text))
        yield block


def _without_margin_refs(blocks: Iterable[Block]) -> Iterator[Block]:
    for block in blocks:
        if isinstance(block, Heading | Paragraph | ListItem) and MARGIN_REF_RE.search(block.text):
            block = replace(block, text=MARGIN_REF_RE.sub("", block.text))
        yield block
