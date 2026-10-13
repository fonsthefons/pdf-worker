"""Command-line entry point. Each feature registers itself as a subcommand."""

import argparse
import codecs
import os
import sys
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

from pdf_worker import __version__, kindle, ocr
from pdf_worker import convert as conversion
from pdf_worker.errors import PdfWorkerError
from pdf_worker.text_extraction import (
    DEFAULT_PAGE_SEPARATOR,
    default_output_path,
    extract_text_to_file,
)


def _add_ocr_options(parser: argparse.ArgumentParser) -> None:
    """``--ocr [MODE]`` / ``--ocr-lang`` for commands that read a PDF's text."""
    parser.add_argument(
        "--ocr",
        nargs="?",
        const="skip",
        choices=ocr.MODES,
        metavar="MODE",
        help="OCR the PDF first. MODE: skip (default; only pages without text), "
        "redo (replace a bad OCR layer) or force (OCR every page).",
    )
    parser.add_argument(
        "--ocr-lang",
        help="Tesseract language(s) for --ocr, e.g. 'spa' or 'lat+eng' "
        "(default: guessed from the document).",
    )
    _add_engine_options(parser, "--ocr-engine")


def _add_engine_options(parser: argparse.ArgumentParser, flag: str = "--engine") -> None:
    parser.add_argument(
        flag,
        dest="engine",
        choices=ocr.ENGINES,
        default="tesseract",
        help="OCR engine: tesseract (default, fast) or paddle (PaddleOCR-VL: slow, much "
        "better on diacritics such as Latin macrons; needs its own setup, see README).",
    )
    parser.add_argument(
        "--paddle-cache",
        type=Path,
        help="Folder for PaddleOCR-VL model files (default: ~/.cache/pdf-worker/paddle).",
    )


def _apply_engine_options(args: argparse.Namespace) -> None:
    if getattr(args, "paddle_cache", None):
        os.environ["PDF_WORKER_PADDLE_CACHE"] = str(args.paddle_cache)


@contextmanager
def _maybe_ocr(args: argparse.Namespace, output: Path) -> Iterator[Path]:
    """Yield the PDF to read: the input, or a temporary OCR'd copy next to ``output``."""
    if not args.ocr:
        yield args.pdf
        return
    _apply_engine_options(args)
    with ocr.ocr_temporary_copy(
        args.pdf,
        output.parent,
        languages=args.ocr_lang,
        mode=args.ocr,
        progress=sys.stderr.isatty(),
        engine=args.engine,
    ) as (pdf, report):
        _print_ocr_summary(report)
        yield pdf


def _print_ocr_summary(report: ocr.OcrReport) -> None:
    guessed = " (guessed)" if report.languages_guessed else ""
    macrons = ", Latin macrons restored" if report.macrons_restored else ""
    pages = f", {len(report.pages)} page(s) only" if report.pages else ""
    underlines = ", underlines erased" if report.underlines_erased else ""
    print(
        f"OCR ({report.mode}, {'+'.join(report.languages)}{guessed}{macrons}{pages}"
        f"{underlines}): "
        f"pages without text {len(report.empty_pages_before)} -> "
        f"{len(report.empty_pages_after)} of {report.page_count}"
    )


def _add_ocr_command(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "ocr",
        help="Add a searchable text layer to a scanned PDF (Tesseract or PaddleOCR-VL).",
        description="OCR a PDF with Tesseract (via OCRmyPDF) or PaddleOCR-VL and write a "
        "searchable PDF.",
    )
    parser.add_argument("pdf", type=Path, help="Input PDF file.")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output PDF path (default: next to the input, as <name>.ocr.pdf).",
    )
    parser.add_argument(
        "--lang",
        help="Tesseract language(s), e.g. 'spa' or 'lat+eng' (default: guessed). "
        "List installed ones with: tesseract --list-langs",
    )
    parser.add_argument(
        "--mode",
        choices=ocr.MODES,
        default="skip",
        help="skip: only pages without text (default). redo: replace an existing, bad "
        "OCR layer. force: rasterize and OCR every page (loses digital text).",
    )
    parser.add_argument(
        "-j", "--jobs", type=int, help="Pages to OCR in parallel (default: all CPU cores)."
    )
    parser.add_argument(
        "--no-latin-macrons",
        dest="latin_macrons",
        action="store_false",
        default=None,
        help="With Latin, keep Tesseract's accented vowels (à, ü...) instead of turning "
        "them into macrons (ā, ū...).",
    )
    _add_engine_options(parser)
    parser.set_defaults(handler=_run_ocr)


def _run_ocr(args: argparse.Namespace) -> int:
    output = args.output or ocr.default_output_path(args.pdf)
    _apply_engine_options(args)
    report = ocr.ocr_pdf(
        args.pdf,
        output,
        languages=args.lang,
        mode=args.mode,
        jobs=args.jobs,
        progress=sys.stderr.isatty(),
        latin_macrons=args.latin_macrons,
        engine=args.engine,
    )
    print(f"Wrote {output}")
    _print_ocr_summary(report)
    if report.empty_pages_after:
        pages = ", ".join(map(str, report.empty_pages_after))
        print(f"Note: still no text on page(s) {pages} (blank or pictures only?)")
    return 0


def _add_extract_text_command(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "extract-text",
        help="Extract the text layer of a PDF into a .txt file.",
        description="Extract the text layer of a PDF into a UTF-8 .txt file.",
    )
    parser.add_argument("pdf", type=Path, help="Input PDF file.")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output .txt path (default: next to the input, with a .txt extension).",
    )
    parser.add_argument(
        "--page-separator",
        default=DEFAULT_PAGE_SEPARATOR,
        help=r"String written between pages; escapes like '\n' are honoured "
        r"(default: form feed '\f').",
    )
    parser.add_argument(
        "--no-footnotes",
        dest="footnotes",
        action="store_false",
        help="Don't mark footnotes/endnotes; output the raw text layer.",
    )
    _add_ocr_options(parser)
    parser.set_defaults(handler=_run_extract_text)


def _run_extract_text(args: argparse.Namespace) -> int:
    output = args.output or default_output_path(args.pdf)
    separator = codecs.decode(args.page_separator, "unicode_escape")
    with _maybe_ocr(args, output) as pdf:
        report = extract_text_to_file(
            pdf, output, page_separator=separator, footnotes=args.footnotes
        )

    print(f"Wrote {report.char_count:,} characters from {report.page_count} pages to {output}")
    if args.footnotes:
        print(
            f"Marked {report.footnote_count} footnote(s) and "
            f"{report.footnote_reference_count} reference(s)"
        )
    for problem, labels in (
        ("referenced but not found", report.undefined_footnotes),
        ("found but never referenced", report.unreferenced_footnotes),
    ):
        if labels:
            shown = ", ".join(labels[:20]) + (" ..." if len(labels) > 20 else "")
            print(f"Warning: {len(labels)} footnote(s) {problem}: {shown}", file=sys.stderr)
    if report.empty_pages:
        pages = ", ".join(map(str, report.empty_pages))
        print(
            f"Warning: {len(report.empty_pages)} page(s) had no text layer "
            f"(likely scanned images): {pages}",
            file=sys.stderr,
        )
    return 0


def _add_convert_command(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "convert",
        help="Convert a PDF into EPUB, Markdown, HTML, clean text, Word or a reflowed PDF.",
        description="Rebuild a PDF as a reflowable book: headings, paragraphs and "
        "footnotes become EPUB 3, Markdown, HTML, clean text, Word or an A5 PDF.",
    )
    parser.add_argument("pdf", type=Path, help="Input PDF file.")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output path (default: next to the input, with the format's extension).",
    )
    parser.add_argument(
        "--to",
        choices=sorted(conversion.FORMATS),
        help="Output format (default: from the -o extension, else epub).",
    )
    parser.add_argument("--title", help="Book title (default: PDF metadata or file name).")
    parser.add_argument("--author", help="Author (default: PDF metadata).")
    parser.add_argument(
        "--language", help="Language code such as 'es' (default: guessed from the text)."
    )
    parser.add_argument(
        "--no-images",
        dest="images",
        action="store_false",
        help="Leave out pictures (figures, and illustrations found in scans).",
    )
    parser.add_argument(
        "--no-cover",
        dest="cover",
        action="store_false",
        help="Don't use the first page as the EPUB cover.",
    )
    _add_ocr_options(parser)
    parser.set_defaults(handler=_run_convert)


def _run_convert(args: argparse.Namespace) -> int:
    fmt = args.to or (args.output and conversion.format_for_path(args.output)) or "epub"
    output = args.output or conversion.default_output_path(args.pdf, fmt)
    # The OCR'd copy has no useful metadata of its own; keep the original's title.
    title = args.title or (args.ocr and conversion.pdf_title(args.pdf))
    with _maybe_ocr(args, output) as pdf:
        report = conversion.convert_pdf(
            pdf,
            output,
            fmt,
            title=title,
            author=args.author,
            language=args.language,
            images=args.images,
            cover=args.cover,
        )
    stats, meta = report.stats, report.metadata
    print(f"Wrote {output} ({fmt}): {meta.title!r}, language {meta.language}")
    print(
        f"{stats.chapters} chapter file(s), {stats.headings} heading(s), "
        f"{stats.paragraphs} paragraph(s), {stats.notes} note(s), "
        f"{stats.glosses} margin gloss block(s), {stats.images} picture(s)"
    )
    return 0


def _add_kindle_command(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "kindle",
        help="One step from any PDF to a Kindle-ready EPUB (OCRs scans when needed).",
        description="Check the PDF's text layer, OCR it if it is missing or poor, and "
        "build an EPUB with footnotes, pictures, cover, links and page numbers.",
    )
    parser.add_argument("pdf", type=Path, help="Input PDF file.")
    parser.add_argument(
        "-o", "--output", type=Path, help="Output .epub (default: next to the input)."
    )
    parser.add_argument("--title", help="Book title (default: PDF metadata or file name).")
    parser.add_argument("--author", help="Author (default: PDF metadata).")
    parser.add_argument("--language", help="Language code such as 'es' (default: guessed).")
    parser.add_argument(
        "--no-ocr", dest="use_ocr", action="store_false", help="Never OCR, even scans."
    )
    parser.add_argument(
        "--ocr-lang", help="Tesseract language(s) for OCR, e.g. 'lat' (default: guessed)."
    )
    _add_engine_options(parser)
    parser.set_defaults(handler=_run_kindle)


def _run_kindle(args: argparse.Namespace) -> int:
    _apply_engine_options(args)
    report = kindle.make_kindle_book(
        args.pdf,
        args.output,
        title=args.title,
        author=args.author,
        language=args.language,
        use_ocr=args.use_ocr,
        ocr_languages=args.ocr_lang,
        progress=sys.stderr.isatty(),
        engine=args.engine,
    )
    assessment = report.assessment
    if report.ocr_report:
        print(f"Text layer: {assessment.reason}, so it was OCR'd ({assessment.mode}).")
        _print_ocr_summary(report.ocr_report)
    elif assessment.mode:
        print(f"Text layer: {assessment.reason}; OCR skipped (--no-ocr).")
    else:
        print(f"Text layer: {assessment.reason}; no OCR needed.")
    stats, meta = report.conversion.stats, report.conversion.metadata
    size_mb = report.size_bytes / (1024 * 1024)
    print(
        f"Wrote {report.output_path} ({size_mb:.1f} MB): {meta.title!r}, language {meta.language}"
    )
    print(
        f"{stats.headings} heading(s), {stats.paragraphs} paragraph(s), {stats.notes} note(s), "
        f"{stats.images} picture(s)"
    )
    if report.too_big_for_email:
        print(
            "Note: over 50 MB, too big for Send to Kindle by e-mail; use the Send to "
            "Kindle app or web page instead.",
            file=sys.stderr,
        )
    return 0


# The cheat sheet printed by `pdf-worker help`: (section, [(command, what it does)]).
CHEAT_SHEET = [
    (
        "Kindle book in one step",
        [
            ("pdf-worker kindle book.pdf", "EPUB for Kindle; OCRs scans when needed"),
            ("pdf-worker kindle scan.pdf --ocr-lang lat", "Same, telling OCR the language"),
            ("pdf-worker kindle scan.pdf --engine paddle", "Same, with slow but sharper OCR"),
            ("pdf-worker kindle book.pdf --no-ocr", "Same, but never OCR"),
        ],
    ),
    (
        "Convert to another format",
        [
            ("pdf-worker convert book.pdf", "EPUB ebook (the default)"),
            ("pdf-worker convert book.pdf --to md", "Markdown, pictures in a folder"),
            ("pdf-worker convert book.pdf --to html", "One web page, pictures included"),
            ("pdf-worker convert book.pdf --to txt", "Clean text, one paragraph per line"),
            ("pdf-worker convert book.pdf --to docx", "Word, with footnotes (needs Pandoc)"),
            ("pdf-worker convert book.pdf --to pdf", "New A5 PDF, easy to read on a tablet"),
            ("pdf-worker convert scan.pdf --ocr redo", "Redo a scan's bad OCR, then convert"),
        ],
    ),
    (
        "Raw text",
        [
            ("pdf-worker extract-text book.pdf", "The PDF's text as .txt, notes marked"),
            ("pdf-worker extract-text book.pdf --no-footnotes", "Same, without marking notes"),
        ],
    ),
    (
        "OCR (make scans searchable)",
        [
            ("pdf-worker ocr scan.pdf", "Add text to pages that have none"),
            ("pdf-worker ocr scan.pdf --mode redo", "Replace a bad existing text layer"),
            ("pdf-worker ocr scan.pdf --lang lat+eng", "Set the OCR language(s)"),
            ("pdf-worker ocr scan.pdf --engine paddle", "Slow but sharper OCR (Apple Silicon)"),
        ],
    ),
    (
        "Help",
        [
            ("pdf-worker help", "Show this list"),
            ("pdf-worker <command> --help", "Every option of one command"),
        ],
    ),
]


def _add_help_command(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "help",
        help="List all commands with a one-line description.",
        description="List all commands with a one-line description.",
    )
    parser.set_defaults(handler=_run_help)


def _run_help(args: argparse.Namespace) -> int:
    width = max(len(command) for _, rows in CHEAT_SHEET for command, _ in rows)
    print("Run from the repo folder as .venv/bin/pdf-worker. -o FILE sets the output path.")
    for section, rows in CHEAT_SHEET:
        print(f"\n{section}")
        for command, description in rows:
            print(f"  {command:<{width}}  {description}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pdf-worker",
        description=__doc__,
        epilog="Run 'pdf-worker help' for examples of every command.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    # With no command, show the cheat sheet.
    parser.set_defaults(handler=_run_help)
    subparsers = parser.add_subparsers(dest="command")
    _add_extract_text_command(subparsers)
    _add_convert_command(subparsers)
    _add_ocr_command(subparsers)
    _add_kindle_command(subparsers)
    _add_help_command(subparsers)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.handler(args)
    except PdfWorkerError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
