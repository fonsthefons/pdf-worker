"""Command-line entry point. Each feature registers itself as a subcommand."""

import argparse
import codecs
import sys
from collections.abc import Sequence
from pathlib import Path

from pdf_worker import __version__
from pdf_worker import convert as conversion
from pdf_worker.errors import PdfWorkerError
from pdf_worker.text_extraction import (
    DEFAULT_PAGE_SEPARATOR,
    default_output_path,
    extract_text_to_file,
)


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
    parser.set_defaults(handler=_run_extract_text)


def _run_extract_text(args: argparse.Namespace) -> int:
    output = args.output or default_output_path(args.pdf)
    separator = codecs.decode(args.page_separator, "unicode_escape")
    report = extract_text_to_file(
        args.pdf, output, page_separator=separator, footnotes=args.footnotes
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
        help="Convert a PDF into an EPUB (Kindle-friendly) or Markdown book.",
        description="Rebuild a PDF as a reflowable book: headings, paragraphs and "
        "footnotes become EPUB 3 or Markdown.",
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
    parser.set_defaults(handler=_run_convert)


def _run_convert(args: argparse.Namespace) -> int:
    fmt = args.to or (args.output and conversion.format_for_path(args.output)) or "epub"
    output = args.output or conversion.default_output_path(args.pdf, fmt)
    report = conversion.convert_pdf(
        args.pdf, output, fmt, title=args.title, author=args.author, language=args.language
    )
    stats, meta = report.stats, report.metadata
    print(f"Wrote {output} ({fmt}): {meta.title!r}, language {meta.language}")
    print(
        f"{stats.chapters} chapter file(s), {stats.headings} heading(s), "
        f"{stats.paragraphs} paragraph(s), {stats.notes} note(s)"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pdf-worker", description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)
    _add_extract_text_command(subparsers)
    _add_convert_command(subparsers)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.handler(args)
    except PdfWorkerError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
