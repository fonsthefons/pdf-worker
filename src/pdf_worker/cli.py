"""Command-line entry point. Each feature registers itself as a subcommand."""

import argparse
import codecs
import os
import re
import shlex
import subprocess
import sys
import time
import webbrowser
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

from pdf_worker import (
    __version__,
    ebook_to_pdf,
    find_book,
    groq,
    kindle,
    ocr,
    review,
    virus_check,
)
from pdf_worker import convert as conversion
from pdf_worker.errors import PdfWorkerError
from pdf_worker.fixes import default_fixes_path, read_fixes
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


def _progress(stage: str):
    """An ``on_page(done, total)`` that shows ``stage``'s share done and the time left.

    On a terminal one line is rewritten; in a log a line is written every 5%."""
    tty = sys.stderr.isatty()
    first = start = None  # the first count seen (cached pages are not timed) and when
    step = -1  # the last 5% step written

    def on_page(done: int, total: int) -> None:
        nonlocal first, start, step
        if first is None:
            first, start = done, time.monotonic()
        pct = 100 * done // max(total, 1)
        if not tty and pct // 5 == step and done < total:
            return
        step = pct // 5
        line = f"{stage}: {pct}% ({done}/{total} pages)"
        if first < done < total:
            left = (time.monotonic() - start) / (done - first) * (total - done)
            line += f", {_duration(left)} left"
        if tty:
            sys.stderr.write(f"\r\033[K{line}" + ("\n" if done >= total else ""))
        else:
            sys.stderr.write(line + "\n")
        sys.stderr.flush()

    return on_page


def _duration(seconds: float) -> str:
    minutes = round(seconds / 60)
    if minutes < 1:
        return "under a minute"
    return (
        f"about {minutes} min"
        if minutes < 60
        else f"about {minutes // 60} h {minutes % 60:02d} min"
    )


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
    parser.add_argument(
        "--title", help="Book title (default: found via ISBN, PDF metadata, title page, file name)."
    )
    parser.add_argument(
        "--author", help="Author (default: found via ISBN, PDF metadata, title page)."
    )
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
        help="Don't add a text cover (title, author, translator) to EPUB, PDF or Word.",
    )
    parser.add_argument(
        "--notes",
        choices=conversion.NOTE_PLACES,
        default="page",
        help="Reflowed PDF: footnotes at the foot of their page (default) or all at the "
        "end of the book. 'none' (any format): leave out the notes and their references "
        "(margin references stay).",
    )
    parser.add_argument(
        "--margin-refs",
        action=argparse.BooleanOptionalAction,
        help="Keep the section numbers printed in the margin of classical editions "
        "(Stephanus '22b' in Plato). Default: kept when found on at least a fifth of "
        "the pages (other books have none; ink in their margins makes false ones).",
    )
    parser.add_argument(
        "--estimate-margin-refs",
        action="store_true",
        help="With --margin-refs (implied): add margin references the scan lost between "
        "two found ones, spread evenly over the words between them; shown as '[~23c]', "
        "pink where labels are coloured.",
    )
    parser.add_argument(
        "--fixes",
        type=Path,
        help="Review file of OCR fixes, applied to the text and updated with suspicious "
        "words, notes and margin references (default: <pdf stem>.fixes.tsv next to the PDF).",
    )
    _add_ocr_options(parser)
    parser.set_defaults(handler=_run_convert)


def _run_convert(args: argparse.Namespace) -> int:
    fmt = args.to or (args.output and conversion.format_for_path(args.output)) or "epub"
    output = args.output or conversion.default_output_path(args.pdf, fmt)
    options = dict(
        author=args.author,
        language=args.language,
        images=args.images,
        cover=args.cover,
        notes_at=args.notes,
        margin_refs=args.margin_refs,
        estimate_margin_refs=args.estimate_margin_refs,
        fixes_path=args.fixes or default_fixes_path(args.pdf),  # not the OCR'd copy's
    )
    if args.ocr in ("redo", "force") and args.engine == "paddle":
        # The book is built from Paddle's blocks themselves, not from a text layer.
        _apply_engine_options(args)
        from pdf_worker.document import open_pdf
        from pdf_worker.paddle_ocr import paddle_pages

        with open_pdf(args.pdf) as doc:
            count = doc.page_count
        rows = paddle_pages(
            args.pdf,
            list(range(count)),
            progress=sys.stderr.isatty(),
            on_page=_progress("Step 1/2, OCR"),
        )
        print(f"OCR ({args.ocr}, paddle): {len(rows)} of {count} page(s) read")
        report = conversion.convert_pdf(
            args.pdf,
            output,
            fmt,
            title=args.title,
            paddle_rows=rows,
            on_page=_progress("Step 2/2, building the book"),
            **options,
        )
        return _print_convert_summary(report, output, fmt)
    with _maybe_ocr(args, output) as pdf:
        # The OCR'd copy has no useful metadata of its own: use the original's.
        report = conversion.convert_pdf(
            pdf, output, fmt, title=args.title, source_pdf=args.pdf, **options
        )
    return _print_convert_summary(report, output, fmt)


def _print_metadata(report: conversion.ConvertReport) -> None:
    """ "Title: 'Timeo' (title page); author: Platón (PDF metadata); ..." """
    meta, sources = report.metadata, report.metadata_sources
    parts = [f"Title: {meta.title!r} ({sources.get('title', '?')})"]
    for name in ("author", "translator", "publisher", "year"):
        if getattr(meta, name):
            parts.append(f"{name}: {getattr(meta, name)} ({sources[name]})")
    print("; ".join(parts))


def _print_convert_summary(report: conversion.ConvertReport, output: Path, fmt: str) -> int:
    stats, meta = report.stats, report.metadata
    print(f"Wrote {output} ({fmt}): {meta.title!r}, language {meta.language}")
    _print_metadata(report)
    print(
        f"{stats.chapters} chapter file(s), {stats.headings} heading(s), "
        f"{stats.paragraphs} paragraph(s), {stats.notes} note(s), "
        f"{stats.glosses} margin gloss block(s), {stats.images} picture(s)"
    )
    for line in report.restored_refs:
        print(line)
    if report.facing_pages:
        print(f"Bilingual edition: {report.facing_pages} facing page(s) in the original dropped")
    if report.reread_words:
        print(f"{report.reread_words} garbled word(s) read again (Greek or the book's language)")
    if report.fixes_path:
        new = ", ".join(f"{n} {kind}" for kind, n in report.new_fixes.items()) or "none"
        print(f"Review file {report.fixes_path}: new rows: {new}")
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
    parser.add_argument(
        "--title", help="Book title (default: found via ISBN, PDF metadata, title page, file name)."
    )
    parser.add_argument(
        "--author", help="Author (default: found via ISBN, PDF metadata, title page)."
    )
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
    vote = report.vote_report
    if vote and vote.pages:
        print(
            f"Second readings (Tesseract, Apple Vision): {vote.fixes} word(s) fixed "
            f"on {vote.pages} scanned page(s)."
        )
    elif vote and vote.skipped:
        print(f"Second readings skipped: {vote.skipped}.")
    stats, meta = report.conversion.stats, report.conversion.metadata
    size_mb = report.size_bytes / (1024 * 1024)
    print(
        f"Wrote {report.output_path} ({size_mb:.1f} MB): {meta.title!r}, language {meta.language}"
    )
    _print_metadata(report.conversion)
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


def _add_find_book_command(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "find-book",
        help="Find a free book online, download the best copy and check its quality.",
        description="Search open libraries (Project Gutenberg, Standard Ebooks, Internet "
        "Archive, Open Library, Wikisource, OpenAlex, Elejandría, textos.info, DOAB, "
        "HathiTrust, and sites from the config file) for a book, download the best match "
        "and suggest what to do next. Without options it asks for the details. With --url "
        "or --file it skips the search and checks that book.",
    )
    given = parser.add_mutually_exclusive_group()
    given.add_argument(
        "--url",
        help="Download this book (a PDF or EPUB link, or an archive.org/details page) "
        "instead of searching.",
    )
    given.add_argument("--file", type=Path, help="Check this PDF or EPUB instead of searching.")
    parser.add_argument(
        "--config",
        type=Path,
        help=f"Config file with extra sites and an OpenAlex key (default: "
        f"{find_book.DEFAULT_CONFIG}, if it exists).",
    )
    parser.add_argument("--title", default="", help="Book title.")
    parser.add_argument("--author", default="", help="Author.")
    parser.add_argument("--isbn", default="", help="ISBN (fills in title and author).")
    parser.add_argument("--year", type=int, help="Year of the edition you want.")
    parser.add_argument("--translator", default="", help="Translator of the edition.")
    parser.add_argument(
        "--language", default="", help="Language code(s) such as 'es' or 'en,es' (default: any)."
    )
    parser.add_argument(
        "--format", choices=find_book.FORMATS, help="Preferred format (default: any)."
    )
    parser.add_argument(
        "-d",
        "--dir",
        type=Path,
        default=Path("."),
        help="Folder for the download (default: the current folder).",
    )
    parser.set_defaults(handler=_run_find_book)


def _ask(prompt: str, default: str = "") -> str:
    shown = f" [{default}]" if default else ""
    try:
        answer = input(f"{prompt}{shown}: ").strip()
    except EOFError:
        answer = ""
    return answer or default


def _ask_numbers(prompt: str, count: int, default: str = "") -> list[int] | None:
    """Ask for numbers between 1 and ``count`` ('2' or '1,3'); None means quit."""
    while True:
        answer = _ask(prompt, default)
        if not answer:
            return []
        if answer.lower() in ("q", "quit"):
            return None
        numbers = [int(n) for n in re.findall(r"\d+", answer)]
        if numbers and all(1 <= n <= count for n in numbers):
            return numbers
        print(f"Please answer with numbers from 1 to {count}.")


def _book_query(args: argparse.Namespace) -> find_book.BookQuery:
    year = re.search(r"\d{4}", str(args.year or ""))
    languages = (find_book.normalize_language(c) for c in re.split(r"[,\s]+", args.language))
    return find_book.BookQuery(
        title=args.title.strip(),
        author=args.author.strip(),
        isbn=find_book.normalize_isbn(args.isbn),
        year=int(year[0]) if year else None,
        translator=args.translator.strip(),
        languages=tuple(dict.fromkeys(c for c in languages if c)),
        fmt=args.format if args.format in find_book.FORMATS else None,
    )


def _run_find_book(args: argparse.Namespace) -> int:
    interactive = sys.stdin.isatty()
    language = next(iter(_book_query(args).languages), None)
    if args.file:
        return _check_and_offer(args.file, language, interactive)
    if args.url:
        candidate = find_book.candidate_from_url(args.url)
        print(f"Downloading from {candidate.source}...")
        return _download_and_offer(candidate, args.dir, language, interactive)
    settings = find_book.load_settings(args.config)
    if interactive and not (args.title or args.author or args.isbn):
        print("Describe the book (press Enter to skip a question).")
        args.title = _ask("Title")
        args.author = _ask("Author")
        args.isbn = _ask("ISBN")
        args.year = _ask("Year of the edition")
        args.translator = _ask("Translator")
        args.language = _ask("Language(s): es, en,es ... or 'any'", "en,es")
        args.format = _ask("Preferred format: pdf, epub or any", "any")
    query = _book_query(args)
    extra = "".join(f", {site.name}" for site in settings.sites)
    print(
        "Searching Project Gutenberg, Standard Ebooks, Internet Archive, Open Library, "
        f"Wikisource, OpenAlex, Elejandría, textos.info, DOAB, HathiTrust{extra}..."
    )
    result = find_book.find_candidates(query, settings)
    for warning in result.warnings:
        print(f"Warning: skipped {warning}", file=sys.stderr)
    shown = result.candidates[:10]
    if not shown:
        raise find_book.FindBookError(
            "Nothing found. Try fewer words, another spelling or another language."
        )
    for number, candidate in enumerate(shown, 1):
        print(f"{number:>2}. {_describe(candidate)}")
    best = next((n for n, c in enumerate(shown, 1) if _downloadable(c)), None)
    if best is None:
        print("None of these can be downloaded directly; open one in your browser.")
        return 0
    choice = [best]
    if interactive:
        choice = _ask_numbers("Download which? (number, q to quit)", len(shown), str(best))
        if not choice:
            return 0
    chosen = shown[choice[0] - 1]
    if not _downloadable(chosen):
        print(f"{chosen.source} has no direct download; open it in your browser: {chosen.page}")
        return 0
    print(f"Downloading from {chosen.source}...")
    language = chosen.language or next(iter(query.languages), None)
    return _download_and_offer(chosen, args.dir, language, interactive)


def _downloadable(candidate: find_book.Candidate) -> bool:
    return bool(candidate.url or candidate.resolve)


def _download_and_offer(
    candidate: find_book.Candidate, folder: Path, language: str | None, interactive: bool
) -> int:
    path = find_book.download(candidate, folder)
    print(f"Saved {path} ({path.stat().st_size / (1024 * 1024):.1f} MB)")
    return _check_and_offer(path, language, interactive)


def _check_and_offer(path: Path, language: str | None, interactive: bool) -> int:
    """Print the quality check and the next steps; in a terminal, offer to run them."""
    check = find_book.check_download(path, language)
    print(f"Quality: {check.summary}")
    print("Next steps:")
    print("   0. Use it as it is")
    for number, step in enumerate(check.steps, 1):
        print(f"  {number:>2}. {step.description}: pdf-worker {shlex.join(step.argv)}")
    if not interactive:
        return 0
    numbers = _ask_numbers("Run now? (number(s) such as 1 or 1,2; Enter to skip)", len(check.steps))
    for number in numbers or []:
        argv = check.steps[number - 1].argv
        print(f"\n$ pdf-worker {shlex.join(argv)}")
        code = main(argv)
        if code:
            return code
    return 0


def _describe(candidate: find_book.Candidate) -> str:
    facts = ", ".join(str(f) for f in (candidate.year, candidate.language) if f)
    by = f" — {candidate.authors[:40]}" if candidate.authors else ""
    kind = (candidate.fmt or "file") if _downloadable(candidate) else "web page only"
    where = f"{candidate.source}, {kind}"
    return f"{candidate.title[:70]}{by}{f' ({facts})' if facts else ''} [{where}]"


def _add_ebook_to_pdf_command(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "ebook-to-pdf",
        help="Lay out an EPUB (or FB2, MOBI, text) as an A5 PDF.",
        description="Lay out an EPUB (or FB2, MOBI, plain text) as an A5 PDF with the "
        "book's table of contents as bookmarks.",
    )
    parser.add_argument("ebook", type=Path, help="Input ebook file.")
    parser.add_argument(
        "-o", "--output", type=Path, help="Output PDF (default: next to the input)."
    )
    parser.set_defaults(handler=_run_ebook_to_pdf)


def _run_ebook_to_pdf(args: argparse.Namespace) -> int:
    output = args.output or ebook_to_pdf.default_output_path(args.ebook)
    pages = ebook_to_pdf.ebook_to_pdf(args.ebook, output)
    print(f"Wrote {output} ({pages} pages)")
    return 0


def _add_review_command(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "review",
        help="Review a book's suspicious words on a local web page.",
        description="Show the spelling and odd-character rows of the review file still to "
        "decide on a local web page, each with its scan line and a model's suggestion "
        "(Groq: needs GROQ_API_KEY in the environment or in .env; only text is sent). "
        "'Save decisions' writes them into the review file; convert the PDF again to "
        "apply them.",
    )
    parser.add_argument("pdf", type=Path, help="The PDF given to convert (paddle engine).")
    parser.add_argument(
        "--fixes", type=Path, help="Review file (default: <pdf stem>.fixes.tsv next to the PDF)."
    )
    parser.add_argument("--no-model", action="store_true", help="Don't ask the model.")
    parser.add_argument("--port", type=int, default=review.PORT, help="Local port of the page.")
    parser.add_argument(
        "--paddle-cache",
        type=Path,
        help="Folder of PaddleOCR-VL's files, as given to convert (default: "
        "~/.cache/pdf-worker/paddle).",
    )
    parser.set_defaults(handler=_run_review)


def _run_review(args: argparse.Namespace) -> int:
    _apply_engine_options(args)
    fixes_path = args.fixes or default_fixes_path(args.pdf)
    if not fixes_path.exists():
        raise PdfWorkerError(f"No review file {fixes_path}: convert the PDF first.")
    rows = review.open_rows(read_fixes(fixes_path))
    if not rows:
        print(f"Nothing to review in {fixes_path}.")
        return 0
    folder = review.review_folder(args.pdf)
    print(f"{len(rows)} rows to review; cutting their scan lines...")
    packets = review.packets(args.pdf, rows, folder)
    proposals = folder / "proposals.jsonl"
    key = "" if args.no_model else groq.api_key()
    if key:
        print(f"Asking {groq.MODEL} on Groq (the rows' text is sent to api.groq.com)...")
        try:
            counts = review.propose(
                packets,
                proposals,
                lambda system, user: groq.generate(system, user, key),
                _progress("Model"),
            )
            print(f"Model: {dict(counts) or 'nothing new to ask'}")
        except groq.GroqError as exc:
            print(f"Model stopped: {exc} (the suggestions so far are kept)")
    elif not args.no_model:
        print("No GROQ_API_KEY: no model suggestions.")
    stem = fixes_path.name.removesuffix(".fixes.tsv")
    page = review.page_html(stem, packets, review.read_proposals(proposals))

    def on_decisions(tsv: str) -> str:
        counts = review.merge(fixes_path, tsv, folder)
        print(f"Saved into {fixes_path}: {dict(counts)}")
        return (
            f"Saved {sum(counts.values()) - counts['skipped']} decisions into {fixes_path.name}. "
            f"To apply them, convert {args.pdf.name} again."
        )

    try:
        server = review.serve(page, on_decisions, args.port)
    except OSError as exc:
        raise PdfWorkerError(f"Port {args.port} is busy ({exc}); try --port.") from exc
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Review page: {url} (Ctrl+C to stop when you have saved)")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


# The cheat sheet printed by `pdf-worker help`: (section, [(command, what it does)]).
CHEAT_SHEET = [
    (
        "Find a free book online",
        [
            ("pdf-worker find-book", "Asks for title, author, ISBN...; downloads the best"),
            ('pdf-worker find-book --title "Confesiones" --language es', "Same, no questions"),
            ("pdf-worker find-book --file book.pdf", "Check a book you have; next steps"),
            ("pdf-worker ebook-to-pdf book.epub", "Lay out an EPUB as an A5 PDF"),
            ("pdf-worker virus-check", "Check a download for malware (VirusTotal)"),
            ("pdf-worker virus-check https://...", "Same, for a link before downloading"),
        ],
    ),
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
            ("pdf-worker review scan.pdf", "Fix the OCR's suspicious words on a web page"),
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

# Printed after the cheat sheet: where files come from and where results go.
FILE_NOTES = """\
Files
  book.pdf is the path to your PDF: relative to the folder you are in, or a full path
  such as ~/Downloads/book.pdf. Tip: type the command, then drag the PDF from Finder
  into the terminal to fill in its path.
  Names with spaces need quotes, but keep ~ outside them: ~/Downloads/"My Book.pdf".
  Output goes next to the PDF, with the same name: ~/Downloads/book.pdf gives
  ~/Downloads/book.epub, or book.md (plus book_images/ for pictures) with --to md.
  An existing file is replaced.
  -o sets another place; the format then comes from its extension:
    pdf-worker convert ~/Downloads/book.pdf -o ~/Documents/Books/book.md
  Options start with two dashes (--to, --ocr); only -o and -j have one."""


def _add_virus_check_command(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "virus-check",
        help="Check a file or a link for malware with VirusTotal.",
        description="Look a file up on VirusTotal by its hash (nothing is uploaded), or have "
        "VirusTotal check a link. Without a target it asks: pick a file in a dialog, or "
        f"paste a URL. Needs {virus_check.KEY_VARIABLE} in the environment or .env. "
        "Exit code 2 when something flags it as malicious or suspicious.",
    )
    parser.add_argument("target", nargs="?", help="A file, or an http(s) URL.")
    parser.add_argument(
        "--upload",
        action="store_true",
        help="Upload a file VirusTotal doesn't know (it is shared with security companies).",
    )
    parser.set_defaults(handler=_run_virus_check)


def _pick_file() -> str:
    """A file chosen in the macOS dialog (starting in Downloads), or a typed path."""
    script = (
        'POSIX path of (choose file with prompt "File to check for malware" '
        "default location (path to downloads folder))"
    )
    try:
        chosen = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    except FileNotFoundError:  # not on a Mac
        return _ask("Path of the file")
    return chosen.stdout.strip()


def _run_virus_check(args: argparse.Namespace) -> int:
    key = virus_check.api_key()
    target, asking = args.target, not args.target
    if asking:
        choice = _ask("Check a (f)ile on this computer or a (u)RL?", "f").lower()
        target = _ask("URL") if choice.startswith("u") else _pick_file()
        if not target:
            print("Nothing chosen.")
            return 0
    if re.match(r"https?://", target):
        print("Asking VirusTotal about the link (a new one can take a few minutes)...")
        reports = virus_check.check_url(target, key)
    else:
        path = Path(target).expanduser()
        reports = [virus_check.check_file(path, key, args.upload)]
        if reports[0].verdict == "unknown" and asking and not args.upload:
            answer = _ask(
                "VirusTotal doesn't know this file. Upload it? It is shared with security "
                "companies (y/N)",
                "n",
            )
            if answer.lower().startswith("y"):
                print("Uploading and waiting for the analysis (a few minutes)...")
                reports = [virus_check.check_file(path, key, upload=True)]
    for report in reports:
        print(f"{report.target}: {report.verdict.upper()}")
        if report.stats is not None:
            counts = ", ".join(f"{name} {n}" for name, n in report.stats.items() if n)
            print(f"  engines: {counts}")
            print(f"  details: {report.link}")
        elif not args.upload:
            print("  Not seen by VirusTotal before; --upload sends it for a scan.")
    return 2 if any(r.verdict in ("malicious", "suspicious") for r in reports) else 0


def _add_help_command(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "help",
        help="List all commands with a one-line description.",
        description="List all commands with a one-line description.",
    )
    parser.set_defaults(handler=_run_help)


def _run_help(args: argparse.Namespace) -> int:
    width = max(len(command) for _, rows in CHEAT_SHEET for command, _ in rows)
    print(f"pdf-worker is installed at {Path(sys.executable).parent / 'pdf-worker'}")
    for section, rows in CHEAT_SHEET:
        print(f"\n{section}")
        for command, description in rows:
            print(f"  {command:<{width}}  {description}")
    print(f"\n{FILE_NOTES}")
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
    _add_find_book_command(subparsers)
    _add_ebook_to_pdf_command(subparsers)
    _add_review_command(subparsers)
    _add_virus_check_command(subparsers)
    _add_help_command(subparsers)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.handler(args)
    except PdfWorkerError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
