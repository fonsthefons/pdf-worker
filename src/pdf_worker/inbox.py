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

A book's settings (the formats to make, title, author...) are kept in its work folder's
``settings.json``, so the rebuild after the review makes the same files.

A folder in the inbox holds several PDFs of one book: the best for the build is used
(``pdf_worker.copies``), the outputs are named after the folder, and the result line and
report say which copy was used and why. The choice is kept (``copy.json``).
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
    copies,
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
SETTINGS = "settings.json"  # in a work folder: the book's formats and convert options
CHOSEN = "copy.json"  # in a folder book's work folder: the copy used, and why
# What a book can be made into; "searchable" is the PDF the book was built from (OCR'd).
FORMATS = (*convert.FORMATS, "searchable")
DEFAULT_FORMATS = ("epub", "pdf")
BOOK_OPTIONS = ("title", "author", "language", "notes_at", "margin_refs")  # convert_pdf's
_LAYOUT_SAID: set[str] = set()  # why the layout model is missing, once said


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
    book: str | Path | None = None,
    settings: dict | None = None,
) -> list[BookResult]:
    """Process every file in ``root/file_inbox``; a failing book doesn't stop the rest.
    ``book``: only this file, copied into the inbox first if it isn't there. ``settings``
    (``formats``, ``BOOK_OPTIONS``) are saved for each book processed and used by its
    later runs too."""
    root = Path(root)
    for folder in (root / INBOX, root / WORK / CONVERTED, root / OUTBOX / DRAFTS):
        folder.mkdir(parents=True, exist_ok=True)
    if book and Path(book).resolve().parent != (root / INBOX).resolve():
        shutil.copy2(book, root / INBOX / Path(book).name)
    results = []
    for path in sorted((root / INBOX).iterdir()):
        if path.name.startswith("."):
            continue
        if book and path.name != Path(book).name:
            continue
        say(f"{path.name}:")
        try:
            results.append(_process_book(root, path, engine, say, on_step, settings or {}))
        except PdfWorkerError as exc:
            results.append(BookResult(path.name, "failed", str(exc)))
    return results


def cleanable(root: str | Path) -> list[Path]:
    """What belongs to no book left in the inbox: work folders, the finished books'
    originals (``file_work/converted``) and drafts. The outbox's finished files stay."""
    root = Path(root)
    pending = [p for p in _listed(root / INBOX) if not p.name.startswith(".")]
    stems = [_stem(p) + "." for p in pending]  # "book." + "epub", "searchable.pdf"
    pending = [p.name for p in pending]
    out = []
    for path in _listed(root / WORK):
        if path.name == CONVERTED:
            out += _listed(path)
        elif path.name not in pending:
            out.append(path)
    out += [p for p in _listed(root / OUTBOX / DRAFTS) if not p.name.startswith(tuple(stems))]
    return out


def clean(paths: list[Path]) -> None:
    """Delete what ``cleanable`` listed."""
    for path in paths:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)


def _listed(folder: Path) -> list[Path]:
    return sorted(folder.iterdir()) if folder.is_dir() else []


def _stem(entry: Path) -> str:
    """The name of a book's outputs: a file's stem, or a folder's whole name."""
    return entry.name if entry.is_dir() else entry.stem


def _process_book(root, entry, engine, say, on_step, given) -> BookResult:
    """``entry``: a book's file, or a folder of copies of it (the best one is used)."""
    name, stem = entry.name, _stem(entry)
    outbox, work = root / OUTBOX, root / WORK / entry.name
    original, chosen = entry, ""
    if entry.is_dir():
        original, chosen = _chosen_copy(entry, work, say)
        if original is None:
            return BookResult(name, "skipped", "no PDF in the folder")
    suffix = original.suffix.lower()
    if suffix == ".epub":
        detail = _rebuild_epub(original, outbox / f"{stem}.epub", outbox / f"{stem}.pdf", say)
        # shortcut: EPUB inputs always give EPUB + PDF; convert reads PDFs only.
        other = [f for f in given.get("formats", ()) if f not in DEFAULT_FORMATS]
        skipped = f"; not made from an EPUB: {', '.join(other)}" if other else ""
        return _finish(root, entry, f"{detail}{skipped}")
    if suffix != ".pdf" and suffix not in EBOOKS:
        return BookResult(name, "skipped", "not a PDF or an ebook")

    work.mkdir(exist_ok=True)
    settings = _settings(work, given)
    formats = settings.get("formats", DEFAULT_FORMATS)
    pdf = work / f"{stem}.pdf"
    fixes = default_fixes_path(pdf)
    draft_mark = work / DRAFT_MARK
    reviewed = draft_mark.exists()
    chosen = f"{chosen}; " if chosen else ""
    if reviewed and not (fixes.exists() and fixes.stat().st_mtime > draft_mark.stat().st_mtime):
        return BookResult(name, "waiting", f"{chosen}to review", pdf)
    if not pdf.exists():
        _prepare(original, pdf, engine, say)
    layout = None if (work / PADDLE_MARK).exists() else _layout_rows(pdf, say, on_step)

    target = outbox if reviewed else outbox / DRAFTS
    say(f"  building: {', '.join(formats)}")
    conversion = _build(original, stem, pdf, target, on_step, settings, layout)
    note = ""
    if "searchable" in formats and (work / PADDLE_MARK).exists():
        note = "; no searchable PDF (PaddleOCR-VL adds no text layer)"
    elif "searchable" in formats:
        _copy(pdf, _outputs(target, stem, ["searchable"])[0])
    rows = read_fixes(fixes)
    left = len(review.open_rows(rows))
    final = reviewed or not left
    state = "final" if final else "draft"
    graded = chosen + _write_report(name, pdf, conversion, rows, state, chosen) + note
    if final:
        if target != outbox:
            for out in _outputs(target, stem, formats):
                if out.exists():
                    os.replace(out, outbox / out.name)
        undecided = f"; {left} row(s) to review left undecided" if left else ""
        return _finish(root, entry, graded + undecided)
    draft_mark.touch()
    return BookResult(name, "draft", f"{graded}; {left} row(s) to review", pdf)


def _chosen_copy(folder: Path, work: Path, say) -> tuple[Path | None, str]:
    """The folder's best PDF (``pdf_worker.copies``) and why; chosen once, so the runs
    after the review build the same copy."""
    work.mkdir(parents=True, exist_ok=True)
    saved = work / CHOSEN
    if saved.exists():
        choice = json.loads(saved.read_text())
        if (folder / choice["copy"]).exists():
            return folder / choice["copy"], choice["why"]
    pdfs = [p for p in _listed(folder) if p.suffix.lower() == ".pdf" and p.name[0] != "."]
    if not pdfs:
        return None, ""
    say(f"  comparing {len(pdfs)} copies")
    ranked = copies.rank_copies(pdfs)
    for check in ranked:
        say(f"    {check.path.name}: {check.summary()}")
    why = f"copy used: {ranked[0].path.name} ({ranked[0].summary()})"
    if ranked[1:]:
        why += "; not used: " + "; ".join(f"{c.path.name} ({c.summary()})" for c in ranked[1:])
    _write_text(saved, json.dumps({"copy": ranked[0].path.name, "why": why}))
    return ranked[0].path, why


def _settings(work: Path, given: dict) -> dict:
    """The book's saved settings, updated with (and saved with) the ones ``given`` now."""
    path = work / SETTINGS
    saved = json.loads(path.read_text()) if path.exists() else {}
    if given:
        saved |= given
        _write_text(path, json.dumps(saved))
    return saved


def _write_report(name, pdf, conversion, rows, state, chosen="") -> str:
    """Write ``report.md`` in the book's work folder; return a one-line summary."""
    work = pdf.parent
    info = json.loads((work / PREPARED).read_text()) if (work / PREPARED).exists() else {}
    report = book_report.BookReport(
        name,
        how=info.get("how", "not recorded (prepared before reports existed)"),
        ocr=info.get("ocr", False),
        language=conversion.metadata.language,
        notes=info.get("notes", []) + ([chosen.removesuffix("; ")] if chosen else []),
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


def _rebuild_epub(epub: Path, output: Path, pdf: Path, say) -> str:
    """Rebuild the EPUB and lay out its PDF like a converted PDF's
    (``pdf_worker.epub_reader``); one it can't read is published as it is, its PDF
    laid out from it."""
    say("  rebuilding the EPUB and laying out the PDF")
    try:
        report = epub_reader.rebuild_epub(epub, output, pdf_path=pdf)
    except Exception as exc:  # an unreadable EPUB must not stop the other books
        _publish_epub(epub, output)
        ebook_to_pdf.ebook_to_pdf(output, pdf)
        return f"EPUB kept as it is ({exc or type(exc).__name__}), PDF laid out"
    notes, dropped = report.stats.notes, len(report.dropped)
    return f"EPUB rebuilt ({notes} note(s), {dropped} page(s) left out), PDF laid out"


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


def _layout_rows(pdf: Path, say, on_step) -> dict[int, dict] | None:
    """The layout model's boxes for every page (``paddle_ocr.layout_pages``); not used
    yet. Without them (no Paddle environment, or the model failed) the book is built as
    before; that is said once a run."""
    from pdf_worker.ocr import OcrError
    from pdf_worker.paddle_ocr import layout_pages

    say("  looking at the pages")
    try:
        return layout_pages(pdf, on_step and on_step("Looking at the pages", "pages"))
    except OcrError as exc:
        if str(exc) not in _LAYOUT_SAID:
            _LAYOUT_SAID.add(str(exc))
            say(f"  no layout model, going on without it: {exc}")
        return None


def _build(
    original: Path, stem: str, pdf: Path, folder: Path, on_step, settings, layout=None
) -> convert.ConvertReport:
    """Write the book's formats into ``folder``; return the EPUB's report. The EPUB is
    always made (the report counts its words): in the work folder when not asked for.
    ``layout``: the layout model's rows, for a book built from the text layer."""
    rows = None
    if (pdf.parent / PADDLE_MARK).exists():
        from pdf_worker.paddle_ocr import paddle_pages

        with open_pdf(pdf) as doc:
            rows = paddle_pages(pdf, list(range(doc.page_count)))
    formats = settings.get("formats", DEFAULT_FORMATS)
    built = ["epub", *(f for f in formats if f not in ("epub", "searchable"))]
    homes = [folder if f in formats else pdf.parent for f in built]
    reports = [
        convert.convert_pdf(
            pdf,
            _outputs(home, stem, [fmt])[0],
            fmt,
            paddle_rows=rows,
            on_step=None if rows else on_step,
            # The original's PDF metadata and file name, not the copy's.
            source_pdf=original if original.suffix.lower() == ".pdf" else pdf,
            layout_rows=layout,
            **{k: settings[k] for k in BOOK_OPTIONS if k in settings},
        )
        for fmt, home in zip(built, homes, strict=True)
    ]
    return reports[0]


def _outputs(folder: Path, stem: str, formats=FORMATS) -> list[Path]:
    # shortcut: book.pdf and book.epub in one inbox write the same outputs; the later
    # one wins. Name them by file name if both forms of a book ever arrive together.
    return [
        folder / f"{stem}{'.searchable.pdf' if f == 'searchable' else convert.FORMATS[f]}"
        for f in formats
    ]


def _finish(root: Path, entry: Path, detail: str) -> BookResult:
    """The book is in the outbox: drop its drafts and file its file (or folder) away."""
    for draft in _outputs(root / OUTBOX / DRAFTS, _stem(entry)):
        draft.unlink(missing_ok=True)
    (root / WORK / entry.name / DRAFT_MARK).unlink(missing_ok=True)
    filed = root / WORK / CONVERTED / entry.name
    if filed.is_dir():  # an earlier run's folder of copies
        shutil.rmtree(filed)
    os.replace(entry, filed)
    return BookResult(entry.name, "finished", detail)
