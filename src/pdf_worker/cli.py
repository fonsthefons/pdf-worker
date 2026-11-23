"""Command-line entry point. Each feature registers itself as a subcommand."""

import argparse
import codecs
import os
import re
import select
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
    epub_reader,
    find_book,
    groq,
    highlights,
    inbox,
    kindle,
    ocr,
    review,
    virus_check,
)
from pdf_worker import convert as conversion
from pdf_worker import summarize as summ
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


def _progress(stage: str, unit: str = "pages"):
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
        line = f"{stage}: {pct}% ({done}/{total} {unit})"
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
        default="end",
        help="Reflowed PDF: footnotes all at the end of the book (default) or at the foot "
        "of their page. 'none' (any format): leave out the notes and their references "
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
    parser.add_argument(
        "--no-marks",
        dest="marks",
        action="store_false",
        help="Ignore the book's marks file (<pdf stem>.marks.json, made with 'pdf-worker "
        "mark'), which otherwise says which lines are running heads, footnotes...",
    )
    parser.add_argument(
        "--no-tags",
        dest="tags",
        action="store_false",
        help="Ignore a tagged PDF's structure tree, which otherwise says which lines are "
        "paragraphs, list items or headings (running heads stay with the rules).",
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
        marks=args.marks,
        tags=args.tags,
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
            pdf, output, fmt, title=args.title, source_pdf=args.pdf, on_step=_progress, **options
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
        "Archive, Open Library, Wikisource, OpenAlex, Elejandría, textos.info, One More "
        "Library, DOAB, HathiTrust, and sites from the config file) for a book, download the "
        "best match and suggest what to do next. Without options it asks for the details. "
        "With --url or --file it skips the search and checks that book.",
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
        default=Path("file_conversion") / "file_inbox",
        help="Folder for the download (default: ./file_conversion/file_inbox, for `process`).",
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
        f"Wikisource, OpenAlex, Elejandría, textos.info, One More Library, DOAB, "
        f"HathiTrust{extra}..."
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


def _add_highlights_command(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "highlights",
        help="Write a PDF with a Kindle's highlights of the book.",
        description="Write BOOK.highlighted.pdf: the book (an EPUB, or a PDF laid out from "
        "it) with the highlights read on the Kindle. Copy the Kindle's "
        "ksdk_annotation_v1.db and the book's .azw3 over MTP first (README).",
    )
    parser.add_argument("book", type=Path, help="The EPUB or PDF to highlight.")
    parser.add_argument(
        "--kindle-db", type=Path, required=True, help="The Kindle's ksdk_annotation_v1.db."
    )
    parser.add_argument(
        "--azw3", type=Path, required=True, help="The book's AZW3 copied from the Kindle."
    )
    parser.add_argument("-o", "--output", type=Path, help="Output PDF (default: next to BOOK).")
    parser.set_defaults(handler=_run_highlights)


def _run_highlights(args: argparse.Namespace) -> int:
    for path, what in ((args.kindle_db, "Kindle database"), (args.azw3, "AZW3 file")):
        if not path.is_file():
            raise PdfWorkerError(
                f"{what} not found: {path}. Copy ksdk_annotation_v1.db and the book's .azw3 "
                "off the Kindle over MTP (see the README, 'Highlights from a Kindle')."
            )
    report = highlights.highlight_book(args.book, args.kindle_db, args.azw3, args.output)
    print(
        f"Wrote {report.output_path}: {report.highlighted} highlight(s), "
        f'{report.notes_attached} note(s) on "{report.title}"'
    )
    for text in report.unmatched:
        print(f"  not found: {text[:70]}")
    if report.notes_unattached:
        print(f"  notes not attached: {report.notes_unattached}")
    return 0


def _add_rebuild_epub_command(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "rebuild-epub",
        help="Rebuild an EPUB like a converted PDF: pop-up notes, no front matter.",
        description="Read an EPUB's text and notes and write it again the way `convert` "
        "writes a PDF: notes that open as pop-ups, the cover, title, copyright and "
        "contents pages left out, a text cover. Headings come from the book's contents, "
        "links inside the book go to their place, and tables, quotes, lists and verse "
        "line breaks are kept.",
    )
    parser.add_argument("epub", type=Path, help="Input EPUB file.")
    parser.add_argument(
        "-o", "--output", type=Path, help="Output EPUB (default: <name>.rebuilt.epub)."
    )
    parser.add_argument(
        "--no-cover",
        dest="cover",
        action="store_false",
        help="Don't add a text cover (title, author, translator).",
    )
    parser.set_defaults(handler=_run_rebuild_epub)


def _run_rebuild_epub(args: argparse.Namespace) -> int:
    output = args.output or epub_reader.default_output_path(args.epub)
    report = epub_reader.rebuild_epub(args.epub, output, cover=args.cover)
    stats, meta = report.stats, report.metadata
    print(f"Wrote {output}: {meta.title!r} by {meta.author or '?'}, language {meta.language}")
    print(
        f"{stats.chapters} chapter file(s), {stats.headings} heading(s), "
        f"{stats.paragraphs} paragraph(s), {stats.notes} note(s), {stats.images} picture(s)"
    )
    print(f"Left out: {', '.join(report.dropped) or 'nothing'}")
    if report.unlinked:
        print(f"{report.unlinked} note reference(s) lead nowhere (kept as plain text)")
    return 0


def _add_review_command(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "review",
        help="Review a book's suspicious words on a local web page.",
        description="Show the spelling and odd-character rows of the review file still to "
        "decide on a local web page, each with its scan line and a model's suggestion "
        "(Groq: needs GROQ_API_KEY in the environment or in ai-client/.env; only text is sent). "
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


def _add_mark_command(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "mark",
        help="Mark examples of a book's kinds of lines on a local web page.",
        description="Open a local web page to mark examples of each kind of line (headings, "
        "footnotes, running heads...), where sections start, and where notes are printed. "
        "Every change is saved at once into <pdf stem>.marks.json next to the PDF "
        "(docs/marks-plan.md); convert follows it (--no-marks ignores it).",
    )
    parser.add_argument("pdf", type=Path, help="The PDF to mark.")
    parser.add_argument("--port", type=int, default=0, help="Local port (default: a free one).")
    parser.add_argument("--no-browser", action="store_true", help="Don't open the browser.")
    parser.add_argument(
        "--paddle-cache",
        type=Path,
        help="Folder of PaddleOCR-VL's files, as given to convert (default: "
        "~/.cache/pdf-worker/paddle); a scan whose rows are cached there shows them.",
    )
    parser.set_defaults(handler=_run_mark)


def _run_mark(args: argparse.Namespace) -> int:
    from pdf_worker import marking
    from pdf_worker.document import open_pdf
    from pdf_worker.marks import default_marks_path

    _apply_engine_options(args)
    with open_pdf(args.pdf) as doc:
        print("Reading the book...")
        book = marking.Book(doc, args.pdf, default_marks_path(args.pdf))
        try:
            server = marking.serve(book, args.port)
        except OSError as exc:
            raise PdfWorkerError(f"Port {args.port} is busy ({exc}); try --port.") from exc
        url = f"http://127.0.0.1:{server.server_address[1]}/"
        print(f"Marking page: {url} (every change is saved; Ctrl+C to stop)")
        if not args.no_browser:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
        lacking = book.missing()
        print("\nStill to check:" if lacking else "\nNothing missing.")
        for item in lacking:
            print(f"  - {item}")
    return 0


PROCESS_FOLDER = Path("file_conversion")


def _add_process_command(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "process",
        help="Turn every book in file_inbox (or one file) into a clean EPUB and PDF in "
        "file_outbox.",
        description="Build every PDF or ebook in FOLDER/file_inbox into an EPUB and a PDF "
        "(OCR when needed). Given a FILE, only that book: it is copied into "
        "./file_conversion/file_inbox and goes through the same folders. Books with words "
        "to review get drafts in file_outbox/drafts; `process` offers the review, then the "
        "rebuild. Steps of a book: OCR (scans), mark (--mark), build, review, done. "
        "Intermediate files go in file_work; finished originals move to "
        "file_work/converted. A book's --to and options are kept for its later runs.",
    )
    parser.add_argument(
        "folder",
        type=Path,
        nargs="?",
        default=PROCESS_FOLDER,
        metavar="FOLDER_OR_FILE",
        help="Folder holding file_inbox (default: ./file_conversion), or one book.",
    )
    parser.add_argument(
        "--to",
        type=lambda text: [f.strip() for f in text.split(",") if f.strip()],
        help=f"Formats to make, comma-separated, from {', '.join(inbox.FORMATS)} "
        "('searchable': the OCR'd copy of the original PDF). Default: epub,pdf,typ.",
    )
    parser.add_argument(
        "--mark",
        action="store_true",
        help="Stop each new book once its text is ready (after OCR) to mark it "
        "(`pdf-worker mark`), then build it following the marks. The marks are kept in "
        "file_work/<book>/ beside the PDF the book is built from; a <stem>.marks.json "
        "beside a text PDF in file_inbox is used too.",
    )
    parser.add_argument(
        "--sentence-check",
        action=argparse.BooleanOptionalAction,
        help="Scans only: a free OpenRouter model settles each suspect word from its "
        "sentence (corrects it, or finds it right) instead of leaving a row to review; "
        "rows it can't settle stay. Kept for the book's later runs until "
        "--no-sentence-check (the rows it wrote stay). Off by default: no model call "
        "unless set for the book.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Only delete what belongs to no book left in file_inbox: work folders, the "
        "finished books' originals (file_work/converted) and drafts. The finished files in "
        "file_outbox stay. Asks first on a terminal.",
    )
    book = parser.add_argument_group("one book only (with FILE)")
    book.add_argument("--title", help="Book title (default: found in the book).")
    book.add_argument("--author", help="Author (default: found in the book).")
    book.add_argument("--language", help="Language code such as 'es' (default: guessed).")
    book.add_argument(
        "--notes",
        choices=conversion.NOTE_PLACES,
        help="Reflowed PDF: notes at the end (default) or at the foot of their page; "
        "'none' leaves notes out.",
    )
    book.add_argument(
        "--margin-refs",
        action=argparse.BooleanOptionalAction,
        help="Keep the margin section numbers of classical editions (default: when found).",
    )
    _add_engine_options(parser)
    parser.set_defaults(handler=_run_process)


def _run_process(args: argparse.Namespace) -> int:
    if args.clean:
        return _clean(args.folder)
    _apply_engine_options(args)
    # A file, or a folder of copies of one book inside an inbox, is one book.
    one = args.folder.is_file() or args.folder.parent.name == inbox.INBOX
    args.book = args.folder if one else None
    if args.book:
        in_inbox = args.book.parent.name == inbox.INBOX
        args.folder = args.book.parent.parent if in_inbox else PROCESS_FOLDER
    options = {
        "title": args.title,
        "author": args.author,
        "language": args.language,
        "notes_at": args.notes,
        "margin_refs": args.margin_refs,
    }
    args.settings = {k: v for k, v in options.items() if v is not None}
    if args.settings and not args.book:
        raise PdfWorkerError(
            "--title, --author, --language, --notes and --margin-refs need a single FILE."
        )
    if args.to:
        if unknown := set(args.to) - set(inbox.FORMATS):
            raise PdfWorkerError(f"unknown format(s) for --to: {', '.join(sorted(unknown))}")
        args.settings["formats"] = args.to
    if args.mark:
        args.settings["mark"] = True
    if args.sentence_check is not None:
        args.settings["sentence_check"] = args.sentence_check
    results = _process_folder(args)
    rebuild = "pdf-worker process" + (
        "" if args.folder == PROCESS_FOLDER else f" {shlex.quote(str(args.folder))}"
    )
    later, reviewed = [], []
    for result in (r for r in results if r.mark_pdf):
        if sys.stdin.isatty() and _ask_yes(f"Mark {result.name} now?"):
            print("Close the marking page with Ctrl+C here when done.")
            options = {"pdf": result.mark_pdf, "port": 0, "no_browser": False}
            _run_mark(argparse.Namespace(**(vars(args) | options)))
            reviewed.append(result.name)
        else:
            print(f"To mark {result.name}: pdf-worker mark {shlex.quote(str(result.mark_pdf))}")
            later.append(result.name)
    for result in (r for r in results if r.review_pdf):
        if sys.stdin.isatty() and _ask_yes(f"Review {result.name} now?"):
            _run_review(
                argparse.Namespace(
                    pdf=result.review_pdf,
                    fixes=None,
                    no_model=False,
                    port=review.PORT,
                    paddle_cache=args.paddle_cache,
                )
            )
            reviewed.append(result.name)
        else:
            later.append(result.name)
    if reviewed and _ask_yes("Rebuild the reviewed books now?"):
        args.settings = {}  # saved with each book on the first run
        results = _process_folder(args)
        # Still a draft or waiting after the rebuild: nothing was saved in review, or skipped.
        later = [r.name for r in results if r.review_pdf]
    else:
        later += reviewed
    if later:
        # `process` offers the review of a waiting book, then the rebuild.
        print("To review and finish later, run (every book in turn, or just one):")
        print(f"  {rebuild}")
        for name in later:
            print(f"  pdf-worker process {shlex.quote(str(args.folder / inbox.INBOX / name))}")
    return 1 if any(r.state == "failed" for r in results) else 0


def _clean(folder: Path) -> int:
    if not folder.is_dir():
        raise PdfWorkerError(f"--clean needs the folder holding file_inbox, not {folder}")
    paths = inbox.cleanable(folder)
    if not paths:
        print(f"Nothing to clean in {folder}.")
        return 0
    size = sum(f.stat().st_size for p in paths for f in [p, *p.rglob("*")] if f.is_file())
    print("To delete (no book in file_inbox needs them):")
    for path in paths:
        print(f"  {path}")
    if sys.stdin.isatty() and not _ask_yes(f"Delete {len(paths)} item(s), {size / 2**20:.1f} MB?"):
        print("Nothing deleted.")
        return 0
    inbox.clean(paths)
    print(f"Deleted {len(paths)} item(s), {size / 2**20:.1f} MB.")
    return 0


def _process_folder(args: argparse.Namespace) -> list[inbox.BookResult]:
    say = lambda message: print(message, flush=True)  # noqa: E731 (in step with stderr's progress)
    results = inbox.process(
        args.folder,
        args.engine,
        say=say,
        on_step=_progress,
        book=args.book,
        settings=args.settings,
    )
    if not results:
        print(f"Nothing in {args.folder / inbox.INBOX}.")
    for result in results:
        print(f"{result.state:<9} {result.name}" + (f": {result.detail}" if result.detail else ""))
    return results


def _ask_yes(prompt: str, seconds: int = 60) -> bool:
    """A y/N question on the terminal; no answer within ``seconds`` counts as no."""
    print(f"{prompt} [y/N] (no answer in {seconds} s = no): ", end="", flush=True)
    ready, _, _ = select.select([sys.stdin], [], [], seconds)
    if not ready:
        print("no answer")
        return False
    return sys.stdin.readline().strip().lower() in ("y", "yes")


# The cheat sheet printed by `pdf-worker help`: (section, [(command, what it does)]).
CHEAT_SHEET = [
    (
        "Find a free book online",
        [
            ("pdf-worker find-book", "Asks for title, author, ISBN...; downloads the best"),
            ('pdf-worker find-book --title "Confesiones" --language es', "Same, no questions"),
            ("pdf-worker find-book --file book.pdf", "Check a book you have; next steps"),
            ("pdf-worker ebook-to-pdf book.epub", "Lay out an EPUB as an A5 PDF"),
            (
                "pdf-worker highlights book.epub --kindle-db D --azw3 B",
                "Kindle highlights in a PDF",
            ),
            ("pdf-worker rebuild-epub book.epub", "Pop-up notes, headings, no front matter"),
            ("pdf-worker virus-check", "Check a download for malware (VirusTotal)"),
            ("pdf-worker virus-check https://...", "Same, for a link before downloading"),
        ],
    ),
    (
        "Every book in file_conversion/file_inbox",
        [
            ("pdf-worker process", "EPUB + PDF in file_outbox; offers review, then rebuild"),
            ("pdf-worker process book.pdf", "Only this book (copied into file_inbox)"),
            ("pdf-worker process --to epub,md,searchable", "Other formats (kept for rebuilds)"),
            ("pdf-worker process --mark", "Mark each new book first, then build, then review"),
            ("pdf-worker process", "Again later: reviews waiting books, finishes reviewed ones"),
            ("pdf-worker process --clean", "Delete work files and originals of finished books"),
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
            ("pdf-worker mark book.pdf", "Mark examples of headings, notes... on a web page"),
        ],
    ),
    (
        "Summarize a converted book",
        [
            ("pdf-worker summarize book.pdf --outline", "Numbered outline, requests per level"),
            ("pdf-worker summarize book.pdf", "Asks what to summarize (free OpenRouter model)"),
            (
                "pdf-worker summarize book.pdf --section 7 --level 3",
                "Part 7, summaries at outline depth 3 (levels count from the top heading)",
            ),
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


def _level(text: str) -> int | str:
    if text == "all":
        return text
    if not text.isdigit():
        raise argparse.ArgumentTypeError(f"{text!r}: a number (0, 1, 2...) or 'all'")
    return int(text)


def _add_summarize_command(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "summarize",
        help="Summarize a converted book, part by part, with a free model.",
        description="Summarize a book already converted (its .blocks.jsonl, see `convert`) "
        "part by part with one of OpenRouter's free models, and write the summary like a "
        "book. Answers are cached beside the blocks file, so a run stopped by the daily "
        "quota resumes where it stopped. Needs OPENROUTER_API_KEY (environment, or "
        "/Users/fons/Documents/programs/ai-client/.env). With no --section/--level/--outline "
        "on a terminal it shows the book's outline and asks what to do.",
        epilog="examples:\n"
        "  pdf-worker summarize book.pdf --outline\n"
        "      the numbered outline and the requests each level would cost; sends nothing\n"
        "  pdf-worker summarize book.pdf --section 'II. > 1.' --level 1 --detail brief\n"
        "  pdf-worker summarize book.pdf --section 7 --section 12 --keep-bold --to md\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "book",
        type=Path,
        help="The book: its .blocks.jsonl, its work folder in file_work/, or the book in "
        "file_inbox/ (convert it first).",
    )
    parser.add_argument(
        "--section",
        action="append",
        default=[],
        metavar="S",
        help="A part to summarize (repeatable; default: the whole book). Either a number "
        "from --outline ('--section 7') or a heading path whose steps start the titles, "
        "case ignored: --section 'II. > 1.' is part 1. of part II.",
    )
    parser.add_argument(
        "--level",
        type=_level,
        metavar="N|all",
        help="How finely to split: the outline's depth. 0 (default): one summary per "
        "chosen part. 1: one per top heading (I., II.); 2: one per its subheadings (II. > "
        "1.); 3: the next (II. > 1. > a)... with numbering 1 / 1.1 / 2.1.a, level 1 gives "
        "1 and 2, level 2 gives 1.1 and 2.1, level 3 gives 2.1.a. Shallower headings are "
        "kept as titles. all: one per deepest part (a part without subheadings is one "
        "summary at any level).",
    )
    parser.add_argument(
        "--detail",
        choices=tuple(summ.DETAIL),
        default="normal",
        help="How long each summary is: brief (about 8%% of the original), normal (15%%, "
        "default) or full (30%%).",
    )
    parser.add_argument(
        "--keep-bold",
        action="store_true",
        help="Keep the book's bold phrases word for word, in bold (a second request asks "
        "for any the summary left out; the rest are listed at the end).",
    )
    parser.add_argument(
        "--skip",
        action="append",
        default=[],
        metavar="T",
        help="Leave out the parts whose title starts with T (repeatable), besides the "
        "contents, notes, index and bibliography that are always left out.",
    )
    parser.add_argument(
        "--outline",
        action="store_true",
        help="Print the numbered outline (number, title, words, bold phrases) and the "
        "most requests each level would take, for the whole book; sends nothing.",
    )
    parser.add_argument("--lang", help="Language of the summary (default: the book's).")
    parser.add_argument("--model", help="An OpenRouter free model (default: the best one up).")
    parser.add_argument(
        "--fresh", action="store_true", help="Ignore the cached answers and ask again."
    )
    parser.add_argument(
        "--to",
        type=lambda text: [f.strip() for f in text.split(",") if f.strip()],
        default=["pdf", "md"],
        help=f"Formats to write, comma-separated, from {', '.join(conversion.FORMATS)} "
        "(default: pdf,md). The summary's .blocks.jsonl is always written.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        help="Folder for the results (default: file_outbox for a book in file_work, "
        "else the blocks file's folder).",
    )
    parser.set_defaults(handler=_run_summarize)


def _yes(default: bool):
    """A parser for `_ask`: y/n, the empty answer being ``default``."""

    def parse(text: str) -> bool:
        if text.lower() not in ("", "y", "yes", "n", "no"):
            raise ValueError("y or n")
        return default if not text else text.lower() in ("y", "yes")

    return parse


def _ask_parsed(prompt: str, parse):
    """``input(prompt)`` until ``parse(answer)`` returns without a ValueError."""
    while True:
        try:
            return parse(input(f"{prompt}: ").strip())
        except ValueError as exc:
            print(f"  {exc}")


def _print_outline(outline, estimates: dict) -> None:
    for node in outline.nodes():
        bold = f", {len(node.bold)} bold" if node.bold else ""
        indent = "  " * (node.depth - 1)
        print(f"{node.number:>4}  {indent}{node.title}  ({node.words} words{bold})")
    print(
        "requests at most: "
        + ", ".join(f"{'all' if k == 'all' else f'level {k}'} {v}" for k, v in estimates.items())
    )


def _summarize_questions(args: argparse.Namespace, outline, depth: int) -> None:
    """Fill ``args`` from the user's answers."""

    def sections(text: str):
        specs = [part.strip() for part in text.split(",") if part.strip()]
        try:
            summ.select(outline, specs)
        except summ.SummarizeError as exc:
            raise ValueError(exc) from exc
        return specs

    def level(text: str):
        try:
            value = _level(text)
        except argparse.ArgumentTypeError as exc:
            raise ValueError(exc) from exc
        return value

    def detail(text: str):
        if text not in summ.DETAIL:
            raise ValueError("brief, normal or full")
        return text

    args.section = _ask_parsed("Sections (numbers like 7,12; empty = whole book)", sections)
    args.level = _ask_parsed(f"Level (0 = one summary, 1-{depth}, all)", level)
    if args.detail == "normal":  # not given on the command line
        args.detail = _ask_parsed(
            "Detail (brief/normal/full) [normal]", lambda t: detail(t or "normal")
        )
    if not args.keep_bold:
        args.keep_bold = _ask_parsed("Keep bold phrases word for word? [y/N]", _yes(False))


def _run_summarize(args: argparse.Namespace) -> int:
    for fmt in args.to:
        if fmt not in conversion.FORMATS:
            raise PdfWorkerError(
                f"unknown format {fmt!r}; choose from {', '.join(conversion.FORMATS)}"
            )
    blocks_path = summ.find_blocks(args.book)
    stem = blocks_path.name[: -len(inbox.BLOCKS)]
    cache = blocks_path.with_name(f"{stem}.summaries.json")
    outline = summ.load_outline(blocks_path, args.skip)
    depth = max((node.depth for node in outline.nodes()), default=0)
    opts = {"lang": args.lang, "detail": args.detail, "keep_bold": args.keep_bold}
    if args.outline:
        top = summ.select(outline, [])
        levels = [*range(depth + 1), "all"]
        _print_outline(outline, {k: summ.estimate(outline, top, k, cache, **opts) for k in levels})
        return 0
    chat = summ.ModelChat(args.model)
    if not chat.client.key:
        raise PdfWorkerError(
            "OPENROUTER_API_KEY is not set: put it in the environment or in "
            "/Users/fons/Documents/programs/ai-client/.env"
        )
    asking = (
        sys.stdin.isatty() and sys.stdout.isatty() and not (args.section or args.level is not None)
    )
    if asking:
        levels = [*range(depth + 1), "all"]
        _print_outline(
            outline,
            {k: summ.estimate(outline, summ.select(outline, []), k, cache, **opts) for k in levels},
        )
        _summarize_questions(args, outline, depth)
        opts = {"lang": args.lang, "detail": args.detail, "keep_bold": args.keep_bold}
    level = 0 if args.level is None else args.level
    nodes = summ.select(outline, args.section)
    needed = summ.estimate(outline, nodes, level, cache, **opts)
    if asking:
        left = chat.requests_left()
        over = left is not None and needed > left
        warn = "  WARNING: more than the free requests left today" if over else ""
        print(f"At most {needed} requests; {'unknown' if left is None else left} left today.{warn}")
        if not _ask_parsed("Go? [Y/n]", _yes(True)):
            return 0

    def on_progress(done: int, total: int, path: str) -> None:
        print(f"[{done}/{total}] {path}", file=sys.stderr)

    def on_wait(model: str, seconds: int, attempt: int, error: Exception) -> None:
        print(f"{model} is down ({error}); wait {attempt}: {seconds} s", file=sys.stderr)

    chat.on_wait = on_wait
    try:
        blocks = summ.summarize(
            outline, nodes, level, chat, cache, fresh=args.fresh, on_progress=on_progress, **opts
        )
    finally:  # a stopped run reports its notes too
        for note in chat.notes:
            print(f"Note: {note}", file=sys.stderr)
        answered = ", ".join(f"{model} {n}" for model, n in chat.answered.items())
        print(f"Answers: {answered or 'none (all cached)'}", file=sys.stderr)
    name = summ.summary_name(stem, level, nodes if args.section else [])
    out_dir = args.out_dir or summ.default_out_dir(blocks_path)
    for path in summ.write_summary(
        blocks, summ.summary_meta(outline.meta, args.lang), out_dir, name, args.to
    ):
        print(f"Wrote {path}")
    return 0


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
    _add_highlights_command(subparsers)
    _add_rebuild_epub_command(subparsers)
    _add_review_command(subparsers)
    _add_mark_command(subparsers)
    _add_process_command(subparsers)
    _add_virus_check_command(subparsers)
    _add_summarize_command(subparsers)
    _add_help_command(subparsers)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.handler(args)
    except PdfWorkerError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
