import shutil
import subprocess
import zipfile

import pymupdf
import pytest

from pdf_worker.cli import main
from pdf_worker.convert import UnsupportedFormatError, convert_pdf, guess_language
from pdf_worker.structure import join_lines

BODY = 11
LINE = 14
EPUBCHECK = shutil.which("epubcheck") or (
    "/opt/homebrew/bin/epubcheck" if shutil.which("/opt/homebrew/bin/epubcheck") else None
)

# Lines of about the same width, so they all reach the right margin.
FULL = [
    "The quick brown fox jumps over the lazy dog and keeps running far",
    "away across the green fields until the evening light finally fades",
    "into a calm and quiet night where every sound seems to have gone",
]


def _body(y, text):
    return (72, y, text, BODY)


def _paragraph(top, lines, last):
    """A paragraph: full-width ``lines`` then a short ``last`` line."""
    items = [_body(top + LINE * i, text) for i, text in enumerate(lines)]
    items.append(_body(top + LINE * len(lines), last))
    return items


def _md(make_layout_pdf, tmp_path, pages, **kwargs):
    pdf = make_layout_pdf(pages)
    out = tmp_path / "book.md"
    report = convert_pdf(pdf, out, "md", **kwargs)
    return out.read_text(encoding="utf-8"), report


def test_join_lines_undoes_hyphenation_and_joins_refs():
    assert join_lines(["a hyphen-", "ated word"]) == "a hyphenated word"
    assert join_lines(["Well-", "Known"]) == "Well- Known"
    assert join_lines(["a claim.", "[^1]", "Next"]) == "a claim.[^1] Next"


def test_headings_paragraphs_and_hyphenation(make_layout_pdf, tmp_path):
    page = [
        (72, 80, "Chapter One", 18),
        *_paragraph(120, FULL[:2], "and a short hyphen-"),
        _body(120 + LINE * 3, "ated ending."),
        *_paragraph(200, FULL[1:], "Second paragraph ends here."),
    ]
    text, report = _md(make_layout_pdf, tmp_path, [page], title="Test Book")

    assert text.startswith('---\ntitle: "Test Book"\nlang: en\n---\n')
    assert "\n# Chapter One\n" in text
    assert f"{FULL[0]} {FULL[1]} and a short hyphenated ending.\n\n" in text
    assert f"{FULL[1]} {FULL[2]} Second paragraph ends here.\n" in text
    assert report.stats.headings == 1
    assert report.stats.paragraphs == 2


def test_paragraph_continues_across_pages(make_layout_pdf, tmp_path):
    pages = [
        [*_paragraph(100, FULL[:2], FULL[2])],  # last line is full width: no ending
        [_body(100, "and it ends on the next page."), *_paragraph(200, FULL[:1], "Done.")],
    ]
    text, _ = _md(make_layout_pdf, tmp_path, pages)

    assert f"{FULL[2]} and it ends on the next page.\n\n" in text


def test_running_headers_and_page_numbers_are_dropped(make_layout_pdf, tmp_path):
    pages = [
        [
            (72, 30, "My Running Header", 9),
            *_paragraph(100, FULL, f"Page {n} text."),
            (290, 815, str(n), 9),
        ]
        for n in range(1, 5)
    ]
    text, _ = _md(make_layout_pdf, tmp_path, pages)

    assert "My Running Header" not in text
    assert "Page 3 text." in text
    assert "\n3\n" not in text


def test_footnotes_become_markdown_notes(make_layout_pdf, tmp_path):
    marker_x = 72 + pymupdf.get_text_length("A claim", fontsize=BODY)
    page = [
        _body(100, "A claim"),
        (marker_x + 0.5, 95, "1", 7),
        *_paragraph(130, FULL, "Filler paragraph."),
        *_paragraph(200, FULL, "More filler."),
        (72, 760, "1 The footnote text.", 8),
    ]
    text, report = _md(make_layout_pdf, tmp_path, [page])

    assert "A claim[^p1-1]\n" in text
    assert text.endswith("[^p1-1]: The footnote text.\n\n")
    assert report.stats.notes == 1


def test_markdown_escapes_syntax(make_layout_pdf, tmp_path):
    page = [
        *_paragraph(100, FULL, "Ends with *stars* here."),
        _body(200, "# Not a heading."),
        _body(240, "12. Numbered."),
    ]
    text, _ = _md(make_layout_pdf, tmp_path, [page])

    assert r"Ends with \*stars\* here." in text
    assert "\n\\# Not a heading.\n" in text
    assert "\n12\\. Numbered.\n" in text


def _epub(make_layout_pdf, tmp_path):
    marker_x = 72 + pymupdf.get_text_length("A claim", fontsize=BODY)
    pages = [
        [
            (72, 80, "Chapter One", 18),
            _body(120, "A claim"),
            (marker_x + 0.5, 115, "1", 7),
            *_paragraph(150, FULL, "Filler & <markup> paragraph."),
            (72, 760, "1 The footnote text.", 8),
        ],
        [(72, 80, "Chapter Two", 18), *_paragraph(120, FULL, "Second chapter.")],
    ]
    pdf = make_layout_pdf(pages)
    out = tmp_path / "book.epub"
    report = convert_pdf(pdf, out, "epub", title="Test Book", author="A. Writer", language="en")
    return out, report


def test_epub_layout_metadata_and_linked_notes(make_layout_pdf, tmp_path):
    out, report = _epub(make_layout_pdf, tmp_path)

    with zipfile.ZipFile(out) as zf:
        first = zf.infolist()[0]
        assert first.filename == "mimetype" and first.compress_type == zipfile.ZIP_STORED
        assert zf.read("mimetype") == b"application/epub+zip"
        opf = zf.read("OEBPS/content.opf").decode()
        chapter = zf.read("OEBPS/c001.xhtml").decode()
        notes = zf.read("OEBPS/notes.xhtml").decode()
        nav = zf.read("OEBPS/nav.xhtml").decode()

    assert "<dc:title>Test Book</dc:title>" in opf
    assert "<dc:creator>A. Writer</dc:creator>" in opf
    assert "<dc:language>en</dc:language>" in opf
    assert 'href="notes.xhtml#n1" epub:type="noteref"' in chapter
    assert 'id="r1"' in chapter
    assert "Filler &amp; &lt;markup&gt; paragraph." in chapter
    assert 'epub:type="footnote"' in notes
    assert 'href="c001.xhtml#r1" role="doc-backlink"' in notes
    assert "The footnote text." in notes
    assert 'text. <a class="back" href="c001.xhtml#r1" role="doc-backlink">↩</a></p>' in notes
    assert "Chapter One" in nav and "Chapter Two" in nav
    assert report.stats.notes == 1


@pytest.mark.skipif(EPUBCHECK is None, reason="epubcheck not installed")
def test_epub_passes_epubcheck(make_layout_pdf, tmp_path):
    out, _ = _epub(make_layout_pdf, tmp_path)

    result = subprocess.run([EPUBCHECK, str(out)], capture_output=True, text=True)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "No errors or warnings detected" in result.stdout


def test_guess_language():
    assert guess_language("El perro de la casa que está en el jardín con los niños") == "es"
    assert guess_language("The dog of the house is in the garden with the children") == "en"
    assert guess_language("Puer et puella in horto sunt, sed non est ad villam") == "la"
    assert guess_language("") == "en"


def test_unsupported_format_is_rejected(make_layout_pdf, tmp_path):
    pdf = make_layout_pdf([[_body(100, "text")]])

    with pytest.raises(UnsupportedFormatError):
        convert_pdf(pdf, tmp_path / "out.odt", "odt")
    with pytest.raises(UnsupportedFormatError, match="overwrite the input"):
        convert_pdf(pdf, pdf, "pdf")


def test_cli_convert_picks_format_from_extension(make_layout_pdf, tmp_path, capsys):
    pdf = make_layout_pdf([[*_paragraph(100, FULL, "End.")]], name="book.pdf")

    assert main(["convert", str(pdf), "-o", str(tmp_path / "out.md")]) == 0
    assert (tmp_path / "out.md").read_text(encoding="utf-8").startswith("---")
    assert "(md)" in capsys.readouterr().out

    assert main(["convert", str(pdf)]) == 0
    assert zipfile.is_zipfile(pdf.with_suffix(".epub"))
