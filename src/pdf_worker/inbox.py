"""Turn every book in ``file_inbox`` into a clean EPUB and PDF in ``file_outbox``.

Each book gets a folder ``file_work/<file name>/`` for what is made on the way: the PDF
the book is built from (``<stem>.pdf``: a copy, an OCR'd copy, or an ebook laid out as a
PDF), its review file and review crops. So ``pdf-worker review file_work/<name>/<stem>.pdf``
works with no options.

A book whose review file has rows to decide gets drafts in ``file_outbox/drafts`` and
waits. Once ``review`` has saved decisions, the next run rebuilds it into ``file_outbox``,
deletes the drafts and moves the original to ``file_work/converted``. A book with nothing
to review (an EPUB, most born-digital PDFs) is finished in one run.

An EPUB is rebuilt the same way as a converted PDF (``pdf_worker.epub_reader``): notes
as pop-ups, no front matter, a text cover. One it can't read is published as it is.

Every build of a PDF or ebook writes ``report.md`` in its work folder: errors found,
possible errors, what was fixed automatically and a grade (``pdf_worker.book_report``).
"""

import json
import os
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pdf_worker import (
    book_report,
    convert,
    ebook_to_pdf,
    epub_mimetype,
    epub_reader,
    kindle,
    review,
)
from pdf_worker.document import open_pdf
from pdf_worker.errors import PdfWorkerError
from pdf_worker.fixes import default_fixes_path, read_fixes
from pdf_worker.ocr_check import assess_text_layer

INBOX, WORK, OUTBOX = "file_inbox", "file_work", "file_outbox"
DRAFTS, CONVERTED = "drafts", "converted"
EBOOKS = {".fb2", ".mobi", ".txt"}  # laid out as a PDF, then built like a PDF
PADDLE_MARK = "paddle"  # in a work folder: build from PaddleOCR-VL's blocks
DRAFT_MARK = "draft"  # in a work folder: drafts are out, waiting for the review
PREPARED = "prepared.json"  # in a work folder: how the text was obtained


@dataclass
class BookResult:
    name: str
    state: str  # finished, draft, waiting, skipped, failed
    detail: str = ""
    review_pdf: Path | None = None  # draft/waiting: the PDF to give `pdf-worker review`


def process(
    root: str | Path,
    engine: str = "tesseract",
    say: Callable[[str], None] = lambda message: None,
    on_step: Callable[[str, str], Callable[[int, int], None]] | None = None,
) -> list[BookResult]:
    """Process every file in ``root/file_inbox``; a failing book doesn't stop the rest."""
    root = Path(root)
    for folder in (root / INBOX, root / WORK / CONVERTED, root / OUTBOX / DRAFTS):
        folder.mkdir(parents=True, exist_ok=True)
    results = []
    for path in sorted((root / INBOX).iterdir()):
        if path.name.startswith(".") or not path.is_file():
            continue
        say(f"{path.name}:")
        try:
            results.append(_process_book(root, path, engine, say, on_step))
        except PdfWorkerError as exc:
            results.append(BookResult(path.name, "failed", str(exc)))
    return results


def _process_book(root, original, engine, say, on_step) -> BookResult:
    suffix = original.suffix.lower()
    outbox = root / OUTBOX
    if suffix == ".epub":
        epub = outbox / original.name
        detail = _rebuild_epub(original, epub, say)
        say("  laying out the PDF")
        ebook_to_pdf.ebook_to_pdf(epub, outbox / f"{original.stem}.pdf")
        return _finish(root, original, f"{detail}, PDF laid out")
    if suffix != ".pdf" and suffix not in EBOOKS:
        return BookResult(original.name, "skipped", "not a PDF or an ebook")

    work = root / WORK / original.name
    work.mkdir(exist_ok=True)
    pdf = work / f"{original.stem}.pdf"
    fixes = default_fixes_path(pdf)
    draft_mark = work / DRAFT_MARK
    reviewed = draft_mark.exists()
    if reviewed and not (fixes.exists() and fixes.stat().st_mtime > draft_mark.stat().st_mtime):
        return BookResult(original.name, "waiting", f"review it: pdf-worker review '{pdf}'", pdf)
    if not pdf.exists():
        _prepare(original, pdf, engine, say)

    target = outbox if reviewed else outbox / DRAFTS
    say("  building the EPUB and the PDF")
    conversion = _build(original, pdf, target, on_step)
    rows = read_fixes(fixes)
    left = len(review.open_rows(rows))
    final = reviewed or not left
    graded = _write_report(original, pdf, conversion, rows, "final" if final else "draft")
    if final:
        if target != outbox:
            for out in _outputs(target, original):
                os.replace(out, outbox / out.name)
        undecided = f"; {left} row(s) to review left undecided" if left else ""
        return _finish(root, original, graded + undecided)
    draft_mark.touch()
    return BookResult(
        original.name,
        "draft",
        f"{graded}; {left} row(s) to review: pdf-worker review '{pdf}'",
        pdf,
    )


def _write_report(original, pdf, conversion, rows, state) -> str:
    """Write ``report.md`` in the book's work folder; return a one-line summary."""
    work = pdf.parent
    info = json.loads((work / PREPARED).read_text()) if (work / PREPARED).exists() else {}
    report = book_report.BookReport(
        original.name,
        how=info.get("how", "not recorded (prepared before reports existed)"),
        ocr=info.get("ocr", False),
        language=conversion.metadata.language,
        notes=info.get("notes", []),
        corrected=info.get("corrected", {}),
    )
    report.corrected["lost note references found again"] = len(conversion.restored_refs)
    report.corrected["garbled words read again (Greek or the book's language)"] = (
        conversion.reread_words
    )
    report.left_out["facing pages of a bilingual edition's original"] = conversion.facing_pages
    book_report.count_rows(report, rows)
    paddle = (work / PADDLE_MARK).exists()  # built from Paddle's blocks, not the layer
    book_report.count_words(report, pdf, conversion.output_path, compare=not paddle)
    path = work / "report.md"
    _write_text(path, book_report.markdown(report, state))
    return f"grade {report.grade}, {report.open_rows} open row(s); report: '{path}'"


def _write_text(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _rebuild_epub(epub: Path, output: Path, say) -> str:
    """Rebuild the EPUB like a converted PDF (``pdf_worker.epub_reader``); one it can't
    read is published as it is."""
    say("  rebuilding the EPUB")
    try:
        report = epub_reader.rebuild_epub(epub, output)
    except Exception as exc:  # an unreadable EPUB must not stop the other books
        _publish_epub(epub, output)
        return f"EPUB kept as it is ({exc or type(exc).__name__})"
    return f"EPUB rebuilt ({report.stats.notes} note(s), {len(report.dropped)} page(s) left out)"


def _publish_epub(epub: Path, output: Path) -> None:
    """Copy the EPUB to ``output``, its mimetype entry repaired if needed."""
    fd, tmp = tempfile.mkstemp(dir=output.parent, suffix=".epub.tmp")
    os.close(fd)
    try:
        shutil.copyfile(epub, tmp)
        if epub_mimetype.problem(tmp):
            epub_mimetype.fix(tmp)
        os.replace(tmp, output)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _prepare(original: Path, pdf: Path, engine: str, say) -> None:
    """Write ``pdf``, the PDF the book is built from, and ``prepared.json``: how its
    text was obtained, for the report."""
    if original.suffix.lower() in EBOOKS:
        say("  laying out the ebook as a PDF")
        ebook_to_pdf.ebook_to_pdf(original, pdf)
        _write_text(pdf.parent / PREPARED, json.dumps({"how": "ebook laid out as a PDF"}))
        return
    with open_pdf(original) as doc:
        assessment = assess_text_layer(doc)
    say(f"  text layer: {assessment.reason}")
    info = {
        "ocr": bool(assessment.mode) or assessment.scanned_pages >= 0.5,
        "notes": [
            f"Text-layer check (sampled pages): {assessment.text_pages:.0%} with text, "
            f"{assessment.scanned_pages:.0%} scanned, {assessment.suspect_words:.1%} words "
            f"look misread, {assessment.jittery_lines:.0%} jittery lines"
        ],
    }
    if engine == "paddle" and assessment.mode:
        # Built from Paddle's blocks of the original; the review finds its crops by content.
        (pdf.parent / PADDLE_MARK).touch()
        _copy(original, pdf)
        info["how"] = f"PaddleOCR-VL ({assessment.reason})"
        _write_text(pdf.parent / PREPARED, json.dumps(info))
        return
    if assessment.mode:
        say(f"  OCR ({assessment.mode}, {engine})")
    with kindle.ocr_and_vote(original, pdf.parent, assessment, engine=engine) as (
        source,
        ocr_report,
        vote_report,
    ):
        _copy(source, pdf)
    if ocr_report:
        guessed = " (guessed)" if ocr_report.languages_guessed else ""
        info["how"] = (
            f"Tesseract OCR, mode {ocr_report.mode}, language "
            f"{'+'.join(ocr_report.languages)}{guessed} ({assessment.reason})"
        )
    else:
        info["how"] = f"the PDF's own text layer ({assessment.reason})"
    if vote_report and vote_report.skipped:
        info["notes"].append(f"Second readings skipped: {vote_report.skipped}")
    elif vote_report:
        info["corrected"] = {
            "words changed by second readings (Tesseract + Apple Vision)": vote_report.fixes
        }
    _write_text(pdf.parent / PREPARED, json.dumps(info))


def _copy(source: Path, target: Path) -> None:
    fd, tmp = tempfile.mkstemp(dir=target.parent, suffix=".pdf.tmp")
    os.close(fd)
    try:
        shutil.copyfile(source, tmp)
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _build(original: Path, pdf: Path, folder: Path, on_step) -> convert.ConvertReport:
    """Write the EPUB and the PDF into ``folder``; return the EPUB's report."""
    rows = None
    if (pdf.parent / PADDLE_MARK).exists():
        from pdf_worker.paddle_ocr import paddle_pages

        with open_pdf(pdf) as doc:
            rows = paddle_pages(pdf, list(range(doc.page_count)))
    reports = [
        convert.convert_pdf(
            pdf,
            out,
            fmt,
            paddle_rows=rows,
            on_step=None if rows else on_step,
            # The original's PDF metadata and file name, not the copy's.
            source_pdf=original if original.suffix.lower() == ".pdf" else pdf,
        )
        for fmt, out in zip(("epub", "pdf"), _outputs(folder, original), strict=True)
    ]
    return reports[0]


def _outputs(folder: Path, original: Path) -> list[Path]:
    # shortcut: book.pdf and book.epub in one inbox write the same outputs; the later
    # one wins. Name them by file name if both forms of a book ever arrive together.
    return [folder / f"{original.stem}.epub", folder / f"{original.stem}.pdf"]


def _finish(root: Path, original: Path, detail: str) -> BookResult:
    """The book is in the outbox: drop its drafts and file the original away."""
    for draft in _outputs(root / OUTBOX / DRAFTS, original):
        draft.unlink(missing_ok=True)
    (root / WORK / original.name / DRAFT_MARK).unlink(missing_ok=True)
    os.replace(original, root / WORK / CONVERTED / original.name)
    return BookResult(original.name, "finished", detail)
