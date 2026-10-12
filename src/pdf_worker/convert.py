"""Convert a PDF into a reflowable book: EPUB (Kindle-friendly) or Markdown.

Pipeline: layout analysis -> footnote detection -> structure (headings, paragraphs,
notes) -> writer. Every stage works page by page.
"""

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from pdf_worker.document import open_pdf
from pdf_worker.epub import write_epub
from pdf_worker.errors import PdfWorkerError
from pdf_worker.layout import analyze_document
from pdf_worker.markdown_export import write_markdown
from pdf_worker.output import Metadata, WriteStats
from pdf_worker.structure import iter_blocks

FORMATS = {"epub": ".epub", "md": ".md"}

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
_JUNK_TITLE_RE = re.compile(r"^(microsoft word|untitled|document\d*$)|\.(docx?|pdf|indd)$", re.I)


class UnsupportedFormatError(PdfWorkerError):
    """The requested output format is not supported."""


@dataclass
class ConvertReport:
    output_path: Path
    metadata: Metadata
    stats: WriteStats


def guess_language(text: str) -> str:
    """Best-guess ISO 639-1 code from stopword frequencies; ``en`` if unsure."""
    words = Counter(word.lower() for word in _WORD_RE.findall(text))
    scores = {
        language: sum(words[word] for word in stopwords.split())
        for language, stopwords in _STOPWORDS.items()
    }
    best = max(scores, key=scores.get)
    return best if scores[best] >= 5 else "en"


def default_output_path(pdf_path: str | Path, fmt: str) -> Path:
    return Path(pdf_path).with_suffix(FORMATS[fmt])


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
) -> ConvertReport:
    """Convert ``pdf_path`` to ``fmt`` at ``output_path`` (written atomically)."""
    if fmt not in FORMATS:
        raise UnsupportedFormatError(f"Unsupported format {fmt!r}; choose from {sorted(FORMATS)}")
    output_path = Path(output_path)
    with open_pdf(pdf_path) as doc:
        profile = analyze_document(doc)
        info = doc.metadata or {}
        meta = Metadata(
            title=title or _title_from(info, pdf_path),
            author=author or (info.get("author") or "").strip(),
            language=language or guess_language(profile.text_sample),
        )
        writer = write_epub if fmt == "epub" else write_markdown
        stats = writer(iter_blocks(doc, profile), output_path, meta)
    return ConvertReport(output_path=output_path, metadata=meta, stats=stats)


def pdf_title(pdf_path: str | Path) -> str:
    """The book title convert would use: PDF metadata, else the file name."""
    with open_pdf(pdf_path) as doc:
        return _title_from(doc.metadata or {}, pdf_path)


def _title_from(info: dict, pdf_path: str | Path) -> str:
    return _clean_title(info.get("title", "")) or Path(pdf_path).stem


def _clean_title(title: str) -> str:
    title = (title or "").strip()
    return "" if not title or _JUNK_TITLE_RE.search(title) else title
