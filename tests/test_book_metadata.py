import json

import pymupdf

from pdf_worker import find_book
from pdf_worker.book_metadata import _person, _year, find_isbn, find_metadata
from pdf_worker.convert import _title_page_texts, convert_pdf

BODY = [
    (72, 300 + 14 * i, "Plain running text of the book, line after line.", 11) for i in range(20)
]


def _find(path, info=None, language="es"):
    with pymupdf.open(path) as doc:
        texts = list(_title_page_texts(doc, None))
        return find_metadata(doc, texts, info or {}, path, language)


def test_byline_beats_an_account_name_in_the_metadata(make_layout_pdf):
    cover = [(72, 80, "INTRODUCCION AL CRISTIANISMO", 16), (72, 110, "Por Joseph Ratzinger", 11)]
    pdf = make_layout_pdf([cover + BODY, BODY])

    meta, sources = _find(pdf, {"title": "INTRODUCCION AL CRISTIANISMO", "author": "MANUEL"})

    assert meta.title == "Introduccion al cristianismo"
    assert (meta.author, sources["author"]) == ("Joseph Ratzinger", "title page")


def test_author_above_the_title_when_the_file_name_names_both(make_layout_pdf):
    page = [(72, 80, "Immanuel Kant", 14), (72, 120, "Critica de la razon pura", 24)]
    pdf = make_layout_pdf([page, BODY], name="Critica de la Razon Pura - Immanuel Kant.pdf")

    meta, _ = _find(pdf, {"title": " ", "author": "win98"})

    assert (meta.title, meta.author) == ("Critica de la razon pura", "Immanuel Kant")


def test_a_heading_is_no_author_without_a_source_naming_it(make_layout_pdf):
    page = [(72, 80, "LINGVA LATINA", 25), (72, 120, "PER SE ILLVSTRATA", 15.6)]
    page += [(72, 150, "PARS I", 12.7), (72, 180, "FAMILIA ROMANA", 15.5)]
    pdf = make_layout_pdf([page, BODY], name="Familia Romana Lingua Latina.pdf")

    meta, _ = _find(pdf, language="la")

    assert (meta.title, meta.author) == ("Lingva Latina", "")


def test_plausible_metadata_stays(make_layout_pdf):
    pdf = make_layout_pdf([[(72, 80, "Distinction", 18)] + BODY])

    meta, sources = _find(pdf, {"title": "Distinction", "author": "Bourdieu, Pierre"}, "en")

    assert (meta.title, meta.author, sources["author"]) == (
        "Distinction",
        "Pierre Bourdieu",
        "PDF metadata",
    )


def test_isbn_fills_what_the_pages_dont_say(make_layout_pdf, monkeypatch):
    responses = {
        "isbn/0140449132.json": {"title": "Crime and Punishment", "publishers": ["Penguin"],
                                 "publish_date": "March 2003"},
        "search.json": {"docs": [{"author_name": ["Fyodor Dostoyevsky"]}]},
    }  # fmt: skip
    monkeypatch.setattr(
        find_book,
        "_get",
        lambda url, timeout=30: json.dumps(
            next(v for k, v in responses.items() if k in url)
        ).encode(),
    )
    pages = [[(72, 80, "CRIME AND PUNISHMENT", 24)], [(72, 80, "ISBN 0-14-044913-2", 9)], BODY]
    pdf = make_layout_pdf(pages)

    meta, sources = _find(pdf, language="en")

    assert (meta.title, sources["title"]) == ("Crime and Punishment", "title page")
    assert (meta.author, meta.publisher, meta.year) == ("Fyodor Dostoyevsky", "Penguin", "2003")
    assert sources["author"] == "ISBN 0140449132"


def test_offline_isbn_lookup_is_skipped(make_layout_pdf, monkeypatch):
    def offline(url, timeout=30):
        raise OSError("no network")

    monkeypatch.setattr(find_book, "_get", offline)
    pdf = make_layout_pdf([[(72, 80, "ISBN 0-14-044913-2", 9)] + BODY], name="My_Book.pdf")

    meta, _ = _find(pdf, language="en")

    assert (meta.title, meta.author) == ("My Book", "")


def test_metadata_reaches_the_epub(make_layout_pdf, tmp_path):
    page = [(72, 60, "INTRODUCCION AL CRISTIANISMO", 16), (72, 80, "Por Joseph Ratzinger", 11)]
    page += [(72, 120, "(c) 1968, 2001 Editorial Sigueme", 9)]
    out = tmp_path / "book.epub"

    report = convert_pdf(make_layout_pdf([page + BODY]), out, "epub", cover=False)

    with pymupdf.open(out) as epub:
        assert epub.metadata["author"] == "Joseph Ratzinger"
    assert (report.metadata.year, report.metadata.publisher) == ("2001", "")


def test_helpers():
    assert _person("Gibbon, Edward, 1737-1794") == "Edward Gibbon"
    assert _person("FREDERICK COPLESTON, S.I.") == "Frederick Copleston"
    assert find_isbn(["ISBN-13: 978-0-14-044913-6", "ISBN 0-14-044913-2"]) == "9780140449136"
    assert find_isbn(["ISBN 0-14-044913-3"]) == ""  # bad check digit
    assert _year(["© J o s é Z a m o r a , 2 0 10", "First published in 1984"]) == "2010"
