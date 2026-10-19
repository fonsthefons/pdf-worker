"""Convert a PDF into a reflowable book: EPUB (Kindle-friendly), Markdown, HTML, clean
plain text, Word (.docx) or a reflowed PDF.

Pipeline: layout analysis -> footnote detection -> structure (headings, paragraphs,
notes) -> writer. Every stage works page by page.
"""

import re
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field, replace
from pathlib import Path

from pdf_worker import margin_estimates
from pdf_worker.cover import cover_jpeg, find_translator
from pdf_worker.document import open_pdf
from pdf_worker.docx_export import write_docx
from pdf_worker.drop_notes import drop_notes
from pdf_worker.epub import write_epub
from pdf_worker.errors import PdfWorkerError
from pdf_worker.fixes import Review, default_fixes_path, read_fixes, write_fixes
from pdf_worker.html_export import write_html
from pdf_worker.inline import MARGIN_REF_RE
from pdf_worker.layout import analyze_document
from pdf_worker.markdown_export import write_markdown
from pdf_worker.ocr_check import mostly_scanned
from pdf_worker.output import Metadata, WriteStats
from pdf_worker.pdf_export import write_pdf
from pdf_worker.structure import Block, Heading, Paragraph, iter_blocks
from pdf_worker.text_export import write_text

FORMATS = {
    "epub": ".epub",
    "md": ".md",
    "html": ".html",
    "txt": ".txt",
    "docx": ".docx",
    "pdf": ".pdf",
}
# Where a reflowed PDF sets its footnotes; "none" leaves notes out of every format.
NOTE_PLACES = ("page", "end", "none")
_TITLE_PAGES = 6  # searched for a translator's name

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
# Producer junk that PDF tools put into the title field.
_OCR_SUFFIX_RE = re.compile(r"(?:\.ocr)+$", re.IGNORECASE)
_JUNK_TITLE_RE = re.compile(
    r"^(microsoft word|untitled|document\d*$)|\.(docx?|pdf|indd|tiff?|jpe?g|png)$"
    # A bare file name such as "201-635.job" or "book_final.qxd".
    r"|^[\w\-]+\.[a-z]{2,4}$",
    re.I,
)


class UnsupportedFormatError(PdfWorkerError):
    """The requested output format is not supported."""


@dataclass
class ConvertReport:
    output_path: Path
    metadata: Metadata
    stats: WriteStats
    restored_refs: list[str] = field(default_factory=list)  # see pdf_worker.missing_refs
    fixes_path: Path | None = None  # the review file, see pdf_worker.fixes
    new_fixes: dict[str, int] = field(default_factory=dict)  # rows added, per kind


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
    notes_at: str = "page",
    paddle_rows: list[dict] | None = None,
    on_page: Callable[[int, int], None] | None = None,
    margin_refs: bool = False,
    estimate_margin_refs: bool = False,
    fixes_path: str | Path | None = None,
) -> ConvertReport:
    """Convert ``pdf_path`` to ``fmt`` at ``output_path`` (written atomically).

    ``images`` keeps the pictures; ``cover`` adds a text cover (title, author,
    translator; ``pdf_worker.cover``) to an EPUB, PDF or Word book; ``notes_at``
    ("page" or "end") places a PDF's footnotes, "none" drops the notes and their
    references in every format. With ``paddle_rows`` (PaddleOCR-VL's
    blocks, see ``paddle_ocr.paddle_pages``) the book is built from them instead of the
    PDF's text layer (``pdf_worker.paddle_book``); ``on_page(done, total)`` then
    follows the pages. ``margin_refs`` keeps the margin references of classical editions
    ("22b", ``pdf_worker.margin_refs``); other books have none, and ink in their margins
    would only make false ones. ``estimate_margin_refs`` (implies ``margin_refs``) adds
    those the scan lost between two found ones (``pdf_worker.margin_estimates``).
    The review file ``fixes_path`` (default ``<pdf stem>.fixes.tsv`` next to the PDF;
    ``pdf_worker.fixes``) is applied to the text, then updated with what looks wrong.
    """
    margin_refs = margin_refs or estimate_margin_refs
    if fmt not in FORMATS:
        raise UnsupportedFormatError(f"Unsupported format {fmt!r}; choose from {sorted(FORMATS)}")
    if notes_at not in NOTE_PLACES:
        raise UnsupportedFormatError(f"Notes go at {' or '.join(NOTE_PLACES)}, not {notes_at!r}")
    output_path = Path(output_path)
    if output_path.resolve() == Path(pdf_path).resolve():
        raise UnsupportedFormatError(f"The output would overwrite the input: {output_path}")
    keep_images = images and fmt != "txt"
    restored: list[str] = []
    with open_pdf(pdf_path) as doc:
        info = doc.metadata or {}
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
            )
        else:
            profile = analyze_document(doc)
            sample = profile.text_sample
            blocks = iter_blocks(doc, profile, images=keep_images)
            if not margin_refs:
                blocks = _without_margin_refs(blocks)
        meta = Metadata(
            title=title or _title_from(info, pdf_path),
            author=author or (info.get("author") or "").strip(),
            language=language or guess_language(sample),
            translator=find_translator(_title_page_texts(doc, paddle_rows)),
        )
        if estimate_margin_refs:
            blocks = margin_estimates.estimate_margin_refs(blocks)
        fixes_path = Path(fixes_path) if fixes_path else default_fixes_path(pdf_path)
        # A born-digital text has no OCR misreadings to flag.
        ocr_text = paddle_rows is not None or mostly_scanned(doc)
        review = Review(read_fixes(fixes_path), meta.language, spelling=ocr_text)
        blocks = review.apply(blocks)
        if notes_at == "none":
            blocks = drop_notes(blocks)
        if fmt == "epub":
            stats = write_epub(blocks, output_path, meta, cover=cover_jpeg(meta) if cover else None)
        elif fmt == "pdf":
            stats = write_pdf(blocks, output_path, meta, notes_at=notes_at, cover=cover)
        elif fmt == "docx":
            stats = write_docx(blocks, output_path, meta, cover=cover)
        else:
            writer = {
                "md": write_markdown,
                "html": write_html,
                "txt": write_text,
            }[fmt]
            stats = writer(blocks, output_path, meta)
    new_fixes = review.finish()
    if review.fixes:
        write_fixes(fixes_path, review.fixes)
    return ConvertReport(
        output_path=output_path,
        metadata=meta,
        stats=stats,
        restored_refs=restored,
        fixes_path=fixes_path if review.fixes else None,
        new_fixes=new_fixes,
    )


def _title_page_texts(doc, paddle_rows: list[dict] | None) -> Iterator[str]:
    """The text blocks of the first pages, where a translator would be named."""
    if paddle_rows is not None:
        for row in sorted(paddle_rows, key=lambda r: r["page"]):
            if row["page"] < _TITLE_PAGES:
                yield from (b.get("text", "") for b in row["blocks"])
    for page_no in range(min(_TITLE_PAGES, doc.page_count)):
        yield from (b[4] for b in doc.load_page(page_no).get_text("blocks"))


def _without_margin_refs(blocks: Iterable[Block]) -> Iterator[Block]:
    for block in blocks:
        if isinstance(block, Heading | Paragraph) and MARGIN_REF_RE.search(block.text):
            block = replace(block, text=MARGIN_REF_RE.sub("", block.text))
        yield block


def pdf_title(pdf_path: str | Path) -> str:
    """The book title convert would use: PDF metadata, else the file name."""
    with open_pdf(pdf_path) as doc:
        return _title_from(doc.metadata or {}, pdf_path)


def _title_from(info: dict, pdf_path: str | Path) -> str:
    """The PDF's title, else its file name without our own suffixes ("book.ocr.pdf")."""
    stem = _OCR_SUFFIX_RE.sub("", Path(pdf_path).stem)
    return _clean_title(info.get("title", "")) or stem.replace("_", " ").strip() or stem


def _clean_title(title: str) -> str:
    title = (title or "").strip()
    return "" if not title or _JUNK_TITLE_RE.search(title) else title
