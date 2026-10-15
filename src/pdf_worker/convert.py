"""Convert a PDF into a reflowable book: EPUB (Kindle-friendly), Markdown, HTML, clean
plain text, Word (.docx) or a reflowed PDF.

Pipeline: layout analysis -> footnote detection -> structure (headings, paragraphs,
notes) -> writer. Every stage works page by page.
"""

import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from pdf_worker import margin_estimates
from pdf_worker.document import open_pdf
from pdf_worker.docx_export import write_docx
from pdf_worker.drop_notes import drop_notes
from pdf_worker.epub import write_epub
from pdf_worker.errors import PdfWorkerError
from pdf_worker.html_export import write_html
from pdf_worker.images import render_cover
from pdf_worker.layout import analyze_document
from pdf_worker.markdown_export import write_markdown
from pdf_worker.output import Metadata, WriteStats
from pdf_worker.pdf_export import write_pdf
from pdf_worker.structure import iter_blocks
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
    estimate_margin_refs: bool = False,
) -> ConvertReport:
    """Convert ``pdf_path`` to ``fmt`` at ``output_path`` (written atomically).

    ``images`` keeps the pictures; ``cover`` makes page 1 the EPUB cover; ``notes_at``
    ("page" or "end") places a PDF's footnotes, "none" drops the notes and their
    references in every format. With ``paddle_rows`` (PaddleOCR-VL's
    blocks, see ``paddle_ocr.paddle_pages``) the book is built from them instead of the
    PDF's text layer (``pdf_worker.paddle_book``); ``on_page(done, total)`` then
    follows the pages. ``estimate_margin_refs`` adds the margin references the scan lost
    between two found ones (``pdf_worker.margin_estimates``).
    """
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
                doc, paddle_rows, images=keep_images, restored=restored, on_page=on_page
            )
        else:
            profile = analyze_document(doc)
            sample = profile.text_sample
            blocks = iter_blocks(doc, profile, images=keep_images)
        if estimate_margin_refs:
            blocks = margin_estimates.estimate_margin_refs(blocks)
        if notes_at == "none":
            blocks = drop_notes(blocks)
        meta = Metadata(
            title=title or _title_from(info, pdf_path),
            author=author or (info.get("author") or "").strip(),
            language=language or guess_language(sample),
        )
        if fmt == "epub":
            cover_jpeg = render_cover(doc.load_page(0)) if cover and doc.page_count else None
            stats = write_epub(blocks, output_path, meta, cover=cover_jpeg)
        elif fmt == "pdf":
            stats = write_pdf(blocks, output_path, meta, notes_at=notes_at)
        else:
            writer = {
                "md": write_markdown,
                "html": write_html,
                "txt": write_text,
                "docx": write_docx,
            }[fmt]
            stats = writer(blocks, output_path, meta)
    return ConvertReport(
        output_path=output_path, metadata=meta, stats=stats, restored_refs=restored
    )


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
