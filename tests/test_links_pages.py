import re
import shutil
import subprocess
import zipfile

import pymupdf
import pytest

from pdf_worker.convert import convert_pdf
from pdf_worker.inline import page_mark, plain
from pdf_worker.structure import join_lines

EPUBCHECK = shutil.which("epubcheck") or shutil.which("/opt/homebrew/bin/epubcheck")
BODY = 11
FILLER = [
    "The quick brown fox jumps over the lazy dog and keeps running far",
    "away across the green fields until the evening light finally fades",
    "into a calm and quiet night where every sound seems to have gone.",
]


def _book(tmp_path, links=True):
    """Contents page linking to two chapters; printed page numbers 41, 42, 43."""
    path = tmp_path / "book.pdf"
    doc = pymupdf.open()
    contents = doc.new_page()
    contents.insert_text((72, 80), "Contents", fontsize=18)
    entries = [("Chapter One ....... 42", 1), ("Chapter Two ....... 43", 2)]
    for i, (entry, _) in enumerate(entries):
        contents.insert_text((72, 120 + 20 * i), entry, fontsize=BODY)
    contents.insert_text((72, 200), "Read more on the web site.", fontsize=BODY)
    for title in ("Chapter One", "Chapter Two"):
        page = doc.new_page()
        page.insert_text((72, 80), title, fontsize=18)
        for i, text in enumerate(FILLER * 3):
            page.insert_text((72, 120 + 15 * i), text, fontsize=BODY)
    for number, page in enumerate(doc, start=41):
        page.insert_text((290, 815), str(number), fontsize=9)
    if links:
        contents = doc[0]  # page handles go stale once the document is iterated
        for i, (_, target) in enumerate(entries):
            rect = pymupdf.Rect(70, 108 + 20 * i, 250, 124 + 20 * i)
            to = pymupdf.Point(72, 60)
            contents.insert_link(
                {"kind": pymupdf.LINK_GOTO, "from": rect, "page": target, "to": to}
            )
        contents.insert_link(
            {
                "kind": pymupdf.LINK_URI,
                "from": pymupdf.Rect(70, 188, 230, 204),
                "uri": "https://example.org/more?a=1&b=2",
            }
        )
    doc.save(path)
    doc.close()
    return path


def _epub_files(path):
    with zipfile.ZipFile(path) as zf:
        return {n: zf.read(n).decode("utf-8") for n in zf.namelist() if n.endswith(".xhtml")}


def test_contents_links_point_to_chapters(tmp_path):
    out = tmp_path / "book.epub"
    convert_pdf(_book(tmp_path), out, "epub")

    files = _epub_files(out)
    text = "".join(files.values())
    hrefs = re.findall(r'<a href="(c\d+\.xhtml#[^"]+)">Chapter (One|Two)', text)
    assert {name for _, name in hrefs} == {"One", "Two"}
    for href, name in hrefs:
        target_file, anchor = href.split("#")
        target = files[f"OEBPS/{target_file}"]
        at = target.index(f'id="{anchor}"')
        assert f"Chapter {name}" in plain(re.sub("<[^>]+>", "", target[at : at + 200]))
    assert 'href="https://example.org/more?a=1&amp;b=2"' in text


def test_page_list_uses_printed_page_numbers(tmp_path):
    out = tmp_path / "book.epub"
    convert_pdf(_book(tmp_path), out, "epub")

    files = _epub_files(out)
    nav = files["OEBPS/nav.xhtml"]
    assert 'epub:type="page-list"' in nav
    assert re.findall(r'#pg\d+">(\d+)</a>', nav) == ["41", "42", "43"]
    body = "".join(v for k, v in files.items() if re.search(r"c\d+\.xhtml", k))
    assert 'epub:type="pagebreak" role="doc-pagebreak" id="pg1" aria-label="42"' in body


@pytest.mark.skipif(EPUBCHECK is None, reason="epubcheck not installed")
def test_links_and_pages_pass_epubcheck(tmp_path):
    out = tmp_path / "book.epub"
    convert_pdf(_book(tmp_path), out, "epub")

    result = subprocess.run([EPUBCHECK, str(out)], capture_output=True, text=True)

    assert "No errors or warnings detected" in result.stdout, result.stdout


def test_markdown_keeps_web_links_and_drops_markers(tmp_path):
    out = tmp_path / "book.md"
    convert_pdf(_book(tmp_path), out, "md")

    text = out.read_text(encoding="utf-8")
    assert "[Read more on the web site.](<https://example.org/more?a=1&b=2>)" in text
    assert "" not in text and "" not in text


def test_join_lines_keeps_page_marks_and_dehyphenates():
    mark = page_mark(4, "5")

    joined = join_lines(["a long hyphen-", mark + "ated word"])

    assert plain(joined) == "a long hyphenated word"
    assert mark in joined
