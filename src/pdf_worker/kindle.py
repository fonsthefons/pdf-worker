"""One step from any PDF to a Kindle-ready EPUB.

Checks the text layer (``pdf_worker.ocr_check``), OCRs into a temporary copy when the
PDF needs it, then converts with pictures, cover, footnotes, links and page numbers.
"""

from dataclasses import dataclass
from pathlib import Path

from pdf_worker import convert, ocr
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
    if use_ocr and assessment.mode:
        with ocr.ocr_temporary_copy(
            pdf_path,
            output_path.parent,
            languages=ocr_languages,
            mode=assessment.mode,
            progress=progress,
            engine=engine,
        ) as (ocr_pdf, ocr_report):
            conversion = convert.convert_pdf(
                ocr_pdf, output_path, "epub", title=title, author=author, language=language
            )
    else:
        ocr_report = None
        conversion = convert.convert_pdf(
            pdf_path, output_path, "epub", title=title, author=author, language=language
        )
    return KindleReport(
        output_path=output_path,
        assessment=assessment,
        conversion=conversion,
        ocr_report=ocr_report,
        size_bytes=output_path.stat().st_size,
    )
