"""One step from any PDF to a Kindle-ready EPUB.

Checks the text layer (``pdf_worker.ocr_check``), OCRs into a temporary copy when the
PDF needs it, lets more OCR engines vote on the words of scanned pages
(``pdf_worker.consensus``), then converts with pictures, cover, footnotes, links and
page numbers.
"""

import os
import tempfile
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path

from pdf_worker import consensus, convert, ocr
from pdf_worker.document import open_pdf
from pdf_worker.ocr_check import TextLayerReport, assess_text_layer

# Send to Kindle by e-mail accepts files up to 50 MB.
EMAIL_LIMIT_BYTES = 50 * 1024 * 1024


@dataclass
class KindleReport:
    output_path: Path
    assessment: TextLayerReport
    conversion: convert.ConvertReport
    ocr_report: ocr.OcrReport | None = None
    size_bytes: int = 0
    vote_report: consensus.VoteReport | None = None

    @property
    def too_big_for_email(self) -> bool:
        return self.size_bytes > EMAIL_LIMIT_BYTES


def default_output_path(pdf_path: str | Path) -> Path:
    return Path(pdf_path).with_suffix(".epub")


def make_kindle_book(
    pdf_path: str | Path,
    output_path: str | Path | None = None,
    title: str | None = None,
    author: str | None = None,
    language: str | None = None,
    use_ocr: bool = True,
    ocr_languages: str | None = None,
    progress: bool = False,
    engine: str = "tesseract",
) -> KindleReport:
    """Build ``output_path`` (an EPUB) from ``pdf_path``, OCRing first if needed."""
    pdf_path = Path(pdf_path)
    output_path = Path(output_path) if output_path else default_output_path(pdf_path)
    with open_pdf(pdf_path) as doc:
        assessment = assess_text_layer(doc)
    title = title or convert.pdf_title(pdf_path)
    ocr_report = vote_report = None
    with ExitStack() as stack:
        source = pdf_path
        if use_ocr and assessment.mode:
            source, ocr_report = stack.enter_context(
                ocr.ocr_temporary_copy(
                    pdf_path,
                    output_path.parent,
                    languages=ocr_languages,
                    mode=assessment.mode,
                    progress=progress,
                    engine=engine,
                    pages=assessment.pages,
                )
            )
        if use_ocr and assessment.scanned_pages >= 0.5 and engine == "tesseract":
            voted = stack.enter_context(_temporary_pdf(output_path.parent, pdf_path.stem))
            languages = ocr_report.languages if ocr_report else ocr.guess_ocr_languages(pdf_path)
            vote_report = consensus.vote_pdf(
                source,
                voted,
                languages,
                original=pdf_path if ocr_report else None,
                redone=_redone_pages(assessment, ocr_report),
            )
            if vote_report.pages:
                source = voted
        conversion = convert.convert_pdf(
            source, output_path, "epub", title=title, author=author, language=language
        )
    return KindleReport(
        output_path=output_path,
        assessment=assessment,
        conversion=conversion,
        ocr_report=ocr_report,
        size_bytes=output_path.stat().st_size,
        vote_report=vote_report,
    )


def _redone_pages(assessment: TextLayerReport, ocr_report: ocr.OcrReport | None) -> list[int]:
    """Pages (1-based) whose text Tesseract wrote in the OCR step."""
    if ocr_report is None:
        return []
    if ocr_report.pages:
        return ocr_report.pages
    if assessment.mode == "skip":
        return ocr_report.empty_pages_before
    return list(range(1, ocr_report.page_count + 1))


@contextmanager
def _temporary_pdf(folder: Path, stem: str) -> Iterator[Path]:
    """A temporary PDF path in ``folder``, deleted afterwards."""
    folder.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=folder, prefix=f".{stem}.voted.", suffix=".pdf")
    os.close(fd)
    try:
        yield Path(name)
    finally:
        Path(name).unlink(missing_ok=True)
