import zipfile

import pytest

from pdf_worker.epub_reader import EpubReadError, rebuild_epub

_OPF = """<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
<dc:title>Book Title</dc:title>{creator}
<dc:language>en-GB</dc:language></metadata>
<manifest>{items}<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
</manifest><spine toc="ncx">{refs}</spine></package>"""
_NCX = """<?xml version="1.0"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/"><navMap>{}</navMap></ncx>"""


def _page(body: str) -> str:
    return f'<html xmlns="http://www.w3.org/1999/xhtml"><head><title>x</title></head><body>{body}</body></html>'


def _epub(path, docs: dict[str, str], creator="<dc:creator>A. Writer</dc:creator>", toc=""):
    items = "".join(
        f'<item id="d{i}" href="{name}" media-type="application/xhtml+xml"/>'
        for i, name in enumerate(docs)
    )
    refs = "".join(f'<itemref idref="d{i}"/>' for i in range(len(docs)))
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        rootfiles = '<rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles>'
        zf.writestr("META-INF/container.xml", f"<container>{rootfiles}</container>")
        zf.writestr("OEBPS/content.opf", _OPF.format(items=items, refs=refs, creator=creator))
        zf.writestr("OEBPS/toc.ncx", _NCX.format(toc))
        for name, body in docs.items():
            zf.writestr(f"OEBPS/{name}", _page(body))
    return path


CHAPTER = (
    "<h1>Chapter One</h1>"
    '<p>It was a <i>quiet</i> morning<a href="notes.xhtml#nt1" id="rf1"><sup>[1]</sup></a>'
    ' in the village<a href="notes.xhtml#rf2-note" id="rf2">2</a>.</p>'
)
NOTES = (
    "<h1>Notes</h1>"
    '<p id="nt1"><sup>[1]</sup> First note. <a href="ch1.xhtml#rf1">&lt;&lt;</a></p>'
    "<p>Its second paragraph.</p>"
    '<p><a id="rf2-note" href="ch1.xhtml#rf2">2</a>. Second note.</p>'
)
LICENCE = (
    '<footer class="pg-boilerplate pgheader"><div>*** END OF THE PROJECT GUTENBERG EBOOK'
    " ***</div><p>Creating the works from print editions...</p></footer>"
)


def test_notes_become_pop_ups_and_front_matter_goes(tmp_path):
    source = _epub(
        tmp_path / "in.epub",
        {
            "cover.xhtml": "<div></div>",
            "title.xhtml": "<h1>Book Title</h1><p>A. Writer</p>",
            "info.xhtml": "<p>ISBN 978-0-00-000000-0. All rights reserved.</p>",
            "ch1.xhtml": CHAPTER,
            "notes.xhtml": NOTES,
            "licence.xhtml": LICENCE,
        },
    )
    report = rebuild_epub(source, tmp_path / "out.epub")

    assert report.dropped == ["OEBPS/cover.xhtml", "OEBPS/title.xhtml", "OEBPS/info.xhtml"]
    assert report.metadata.title == "Book Title" and report.metadata.language == "en"
    assert report.stats.notes == 2
    with zipfile.ZipFile(tmp_path / "out.epub") as zf:
        chapters = "".join(zf.read(n).decode() for n in zf.namelist() if "/c0" in n)
        notes = zf.read("OEBPS/notes.xhtml").decode()
    assert chapters.count('epub:type="noteref"') == 2
    assert "<i>quiet</i>" in chapters
    assert "ISBN" not in chapters and "[1]" not in chapters and "Notes" not in chapters
    assert "First note." in notes and "Second note." in notes
    assert "&lt;&lt;" not in notes and "[1]" not in notes
    assert ">2</a>. Second note." in notes  # the writer's number, not the book's too
    assert "First note.</p><p>Its second paragraph." in notes
    assert "GUTENBERG" not in chapters and "print editions" not in chapters


def _point(title: str, src: str, inner: str = "") -> str:
    label = f"<navLabel><text>{title}</text></navLabel>"
    return f'<navPoint>{label}<content src="{src}"/>{inner}</navPoint>'


def test_contents_entries_make_headings_and_links_go_to_their_block(tmp_path):
    one = (
        '<p class="titulo">Part One</p><p id="s1">Two words.</p>'
        '<p>Some text, then back to <a href="ch2.xhtml#poem">the poem</a>.</p>'
        "<blockquote><p>Quoted.</p></blockquote><ul><li>Item</li></ul>"
        "<table><tr><td>a</td><td>b</td></tr><tr><td>c</td><td>d</td></tr></table>"
    )
    two = (
        f"<p>{'Long opening text that is not a title at all. ' * 5}</p>"
        '<p id="poem">Roses are red,<br/>Violets are blue.</p>'
    )
    prose = "<h1>Prose</h1>" + "<p>Lines broken<br/>as printed, all<br/>through it.</p>" * 3
    toc = _point("Part One", "ch1.xhtml", _point("Two words", "ch1.xhtml#s1"))
    toc += _point("Chapter Two", "ch2.xhtml")
    docs = {"ch1.xhtml": one, "ch2.xhtml": two, "ch3.xhtml": prose}
    source = _epub(tmp_path / "in.epub", docs, toc=toc)

    report = rebuild_epub(source, tmp_path / "out.epub")

    assert report.stats.headings == 4 and report.stats.tables == 1
    with zipfile.ZipFile(tmp_path / "out.epub") as zf:
        text = "".join(zf.read(n).decode() for n in sorted(zf.namelist()) if "/c0" in n)
    assert '<h1 id="h1">Part One</h1>' in text
    assert '<h2 id="h2">Two words.</h2>' in text
    assert '<h1 id="h3">Chapter Two</h1><p id=' in text.replace("\n", "")
    assert "Roses are red,<br/>Violets are blue." in text
    assert "Lines broken as printed, all through it." in text
    poem = text[: text.index("Roses")].rsplit('<p id="', 1)[1].split('"')[0]
    assert f'#{poem}">the poem</a>' in text
    assert '<p id="b2" class="small">Quoted.</p>' in text
    assert "• Item" in text and "<td>c</td><td>d</td>" in text


def test_missing_author_comes_from_the_title_page(tmp_path):
    source = _epub(
        tmp_path / "in.epub",
        {"title.xhtml": "<h1>Book Title</h1><p>Por Ana Writer</p>", "ch1.xhtml": CHAPTER},
        creator="",
    )

    report = rebuild_epub(source, tmp_path / "out.epub")

    assert report.metadata.title == "Book Title"  # the package's
    assert report.metadata.author == "Ana Writer"


def test_notes_it_cannot_link_keep_the_epub_as_it_is(tmp_path):
    refs = "".join(f'<a href="notes.xhtml#gone{i}">{i}</a>' for i in range(3))
    source = _epub(
        tmp_path / "in.epub",
        {"ch1.xhtml": f"<h1>One</h1><p>Text{refs}.</p>", "notes.xhtml": "<p>Notes</p>"},
    )
    with pytest.raises(EpubReadError, match="3 note reference"):
        rebuild_epub(source, tmp_path / "out.epub")
    assert not (tmp_path / "out.epub").exists()
