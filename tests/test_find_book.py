import io
import json
import urllib.parse
import zipfile

import pymupdf
import pytest

from pdf_worker import find_book
from pdf_worker.cli import main
from pdf_worker.ebook_to_pdf import ebook_to_pdf
from pdf_worker.find_book import BookQuery, Candidate, score_candidate

GUTENBERG_FEED = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<entry><id>https://www.gutenberg.org/ebooks/search.opds/?sort_order=title</id>
<title>Sort Alphabetically by Title</title></entry>
<entry><id>https://www.gutenberg.org/ebooks/2000.opds</id>
<title>Don Quijote (Spanish)</title><content type="text">Miguel de Cervantes Saavedra</content>
</entry></feed>"""

STANDARD_HTML = b"""<ol class="ebooks-list grid">
<li typeof="schema:Book" about="/ebooks/fyodor-dostoevsky/crime-and-punishment/constance-garnett">
<p><a href="x"><span property="schema:name">Crime and Punishment</span></a></p>
<p class="author"><a><span property="schema:name">Fyodor Dostoevsky</span></a></p>
</li></ol>"""

ARCHIVE_JSON = {
    "response": {
        "docs": [
            {
                "identifier": "scan1",
                "title": "Confesiones",
                "creator": ["Agustin, San"],
                "year": "1905",
                "language": "spa",
                "format": ["Text PDF", "EPUB", "DjVuTXT"],
            },
            {"identifier": "audio1", "title": "Confesiones", "format": ["MP3"]},
        ]
    }
}


@pytest.fixture(autouse=True)
def no_user_config(monkeypatch, tmp_path):
    """Tests never read the user's own ~/.config/pdf-worker/find-book.toml."""
    monkeypatch.setattr(find_book, "DEFAULT_CONFIG", tmp_path / "find-book.toml")


def fake_get(responses):
    """A ``_get`` that answers from ``{url fragment: bytes}``; other URLs fail."""

    def _get(url, timeout=30, accept=""):
        for fragment, body in responses.items():
            if fragment in url:
                return body
        raise OSError(f"no fake response for {url}")

    return _get


def make_epub(path, text):
    """A minimal EPUB 3 with one chapter of ``text``."""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?><container version="1.0" '
            'xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
            '<rootfile full-path="content.opf" media-type="application/oebps-package+xml"/>'
            "</rootfiles></container>",
        )
        z.writestr(
            "content.opf",
            '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0" '
            'unique-identifier="id"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
            '<dc:identifier id="id">x</dc:identifier><dc:title>Test Book</dc:title>'
            "<dc:language>en</dc:language></metadata><manifest>"
            '<item id="c1" href="c1.xhtml" media-type="application/xhtml+xml"/></manifest>'
            '<spine><itemref idref="c1"/></spine></package>',
        )
        z.writestr(
            "c1.xhtml",
            '<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml">'
            f"<head><title>c1</title></head><body><p>{text}</p></body></html>",
        )
    return path


# --- Sources ------------------------------------------------------------------------


def test_gutenberg_skips_navigation_and_reads_language(monkeypatch):
    monkeypatch.setattr(find_book, "_get", fake_get({"gutenberg.org": GUTENBERG_FEED}))

    [book] = find_book._gutenberg(BookQuery(title="Don Quijote"))

    assert (book.title, book.language) == ("Don Quijote", "es")
    assert book.url == "https://www.gutenberg.org/ebooks/2000.epub3.images"


def test_gutenberg_query_leaves_out_stopwords(monkeypatch):
    urls = []

    def _get(url, timeout=30):
        urls.append(url)
        return GUTENBERG_FEED

    monkeypatch.setattr(find_book, "_get", _get)
    find_book._gutenberg(BookQuery(title="Crime and Punishment", languages=("en",)))

    assert "query=Crime+Punishment+l.en" in urls[0]


def test_standard_ebooks_links_the_file_not_the_download_page(monkeypatch):
    monkeypatch.setattr(find_book, "_get", fake_get({"standardebooks.org": STANDARD_HTML}))

    [book] = find_book._standard_ebooks(BookQuery(title="Crime and Punishment"))

    assert book.authors == "Fyodor Dostoevsky"
    assert book.details == "constance garnett"
    assert book.url.endswith(
        "fyodor-dostoevsky_crime-and-punishment_constance-garnett.epub?source=download"
    )


def test_internet_archive_prefers_the_scan_pdf_and_skips_non_books(monkeypatch):
    body = json.dumps(ARCHIVE_JSON).encode()
    monkeypatch.setattr(find_book, "_get", fake_get({"archive.org": body}))

    [book] = find_book._internet_archive(BookQuery(title="Confesiones"), [])
    [as_epub] = find_book._internet_archive(BookQuery(title="Confesiones", fmt="epub"), [])

    assert (book.fmt, book.ia_id, book.year, book.language) == ("pdf", "scan1", 1905, "es")
    assert as_epub.fmt == "epub"


def test_a_failing_library_becomes_a_warning(monkeypatch):
    monkeypatch.setattr(find_book, "_get", fake_get({"gutenberg.org": GUTENBERG_FEED}))

    result = find_book.find_candidates(BookQuery(title="Don Quijote", languages=("es",)))

    assert [c.source for c in result.candidates] == ["Project Gutenberg"]
    assert any(w.startswith("Internet Archive:") for w in result.warnings)


OPENALEX_JSON = {
    "results": [
        {
            "id": "https://openalex.org/W1",
            "title": "Filosofía de la religión",
            "publication_year": 2019,
            "language": "es",
            "authorships": [{"author": {"display_name": "Ana Pérez"}}],
            "locations": [
                {"landing_page_url": "https://repo.example/1", "pdf_url": None},
                {
                    "landing_page_url": "https://repo.example/2",
                    "pdf_url": "https://repo.example/2.pdf",
                },
            ],
        },
        {"id": "https://openalex.org/W2", "title": "Sin PDF", "locations": []},
    ]
}


def test_openalex_takes_a_free_pdf_or_links_the_page(monkeypatch):
    urls = []

    def _get(url, timeout=30):
        urls.append(url)
        return json.dumps(OPENALEX_JSON).encode()

    monkeypatch.setattr(find_book, "_get", _get)

    with_pdf, link_only = find_book._openalex(
        BookQuery(title="Filosofía de la religión", languages=("es",)), api_key="k"
    )

    assert (with_pdf.fmt, with_pdf.url, with_pdf.page) == (
        "pdf",
        "https://repo.example/2.pdf",
        "https://repo.example/1",
    )
    assert (with_pdf.authors, with_pdf.year, with_pdf.language) == ("Ana Pérez", 2019, "es")
    assert (link_only.url, link_only.page) == (None, "https://openalex.org/W2")
    assert "language%3Aes" in urls[0] and "api_key=k" in urls[0]


ELEJANDRIA_SITEMAP = b"""<urlset>
<url><loc>https://www.elejandria.com/autor/agustin-de-hipona/383</loc></url>
<url><loc>https://www.elejandria.com/libro/la-ciudad-de-dios/agustin-de-hipona/2533</loc></url>
<url><loc>https://www.elejandria.com/libro/orgullo-y-prejuicio/jane-austen/20</loc></url>
</urlset>"""

ELEJANDRIA_PAGE = b"".join(
    b'<a class="btn" href="https://www.elejandria.com/libro/descargar/la-ciudad-de-dios/'
    b'agustin-de-hipona/2533/%s"><img alt="Descargar en %s" /> Descargar en %s</a>\n'
    % (file, fmt, fmt)
    for file, fmt in ((b"91", b"PDF"), (b"92", b"ePub"))
)


def test_elejandria_searches_the_sitemap_and_reads_the_formats_from_the_page(monkeypatch):
    pages = {"sitemap.xml": ELEJANDRIA_SITEMAP, "/libro/la-ciudad": ELEJANDRIA_PAGE}
    monkeypatch.setattr(find_book, "_get", fake_get(pages))

    [found] = find_book._elejandria(BookQuery(title="La ciudad de Dios"))

    assert (found.title, found.authors, found.language) == (
        "La ciudad de dios",
        "Agustin De Hipona",
        "es",
    )
    assert (found.fmt, found.url) == (
        "epub",
        "https://www.elejandria.com/libro/link_descarga_libro/2533/92",
    )
    [as_pdf] = find_book._elejandria(BookQuery(title="La ciudad de Dios", fmt="pdf"))
    assert (as_pdf.fmt, as_pdf.url[-8:]) == ("pdf", "/2533/91")
    pages["/libro/la-ciudad"] = ELEJANDRIA_PAGE.split(b"\n")[0]  # PDF only: not called an EPUB
    [pdf_only] = find_book._elejandria(BookQuery(title="La ciudad de Dios", fmt="epub"))
    assert pdf_only.fmt == "pdf"


OML_RESULTS = b"""<div class="item_img"><a
href="/index.php/es/libros/literatura/book/literatura-espanola-132/niebla-1433"><img
src="/components/x_thm.jpg" alt="Niebla - Miguel de Unamuno" /></a></div>
<div class="item_img"><a
href="/index.php/es/libros/literatura/book/literatura-norteamericana-175/cartas-866"><img
src="/components/y_thm.jpg" alt="Cartas desde La Tierra - Mark Twain" /></a></div>"""
OML_BOOK = b"""<a target="_blank" class="" href="https://onemorelibrary.com/index.php?option=com_djclassifieds&amp;format=raw&amp;view=download&amp;task=download&amp;fid=24006"><div
class="iconos-de-descarga"><img src="/images/icon-download-pdf.png"></div><div
class="djc_file"><span>Niebla - Miguel de Unamuno - PDF</span><br
/><span class="djc_filesize small">pdf | 915.33 KB | 7825 descargas</span></div></a>
<a target="_blank" class="" href="https://onemorelibrary.com/index.php?option=com_djclassifieds&amp;format=raw&amp;view=download&amp;task=download&amp;fid=24008"><div
class="djc_file"><span>Niebla - Miguel de Unamuno - EPUB</span><br
/><span class="djc_filesize small">epub | 300 KB | 10 descargas</span></div></a>
<a href="https://onemorelibrary.com/index.php?option=com_djclassifieds&amp;format=raw&amp;view=download&amp;task=download&amp;fid=24009"><div
class="djc_file"><span>Niebla - MOBI</span><br
/><span class="djc_filesize small">mobi | 400 KB | 3 descargas</span></div></a>"""


def test_one_more_library_searches_then_reads_the_book_page(monkeypatch):
    pages = {"search=Niebla": OML_RESULTS, "/niebla-1433": OML_BOOK}
    monkeypatch.setattr(find_book, "_get", fake_get(pages))

    [found] = find_book._onemorelibrary(BookQuery(title="Niebla", author="Unamuno"))

    assert (found.title, found.authors, found.language) == ("Niebla", "Miguel de Unamuno", "es")
    assert (found.fmt, found.url[-9:]) == ("epub", "fid=24008")
    [as_pdf] = find_book._onemorelibrary(BookQuery(title="Niebla", fmt="pdf"))
    assert (as_pdf.fmt, as_pdf.url[-9:]) == ("pdf", "fid=24006")
    # A title the site doesn't hold word for word: the author's books are searched.
    pages = {
        "search=Niebla+nivola": b"0 libros",
        "search=Unamuno": OML_RESULTS,
        "/niebla": OML_BOOK,
    }
    monkeypatch.setattr(find_book, "_get", fake_get(pages))
    [by_author] = find_book._onemorelibrary(BookQuery(title="Niebla nivola", author="Unamuno"))
    assert by_author.title == "Niebla"


GLOBAL_GREY_SITEMAP = b"""<urlset>
<url><loc>https://www.globalgreyebooks.com/recently-added.html</loc></url>
<url><loc>https://www.globalgreyebooks.com/online-ebooks/marcus-aurelius_meditations_complete-text.html</loc></url>
<url><loc>https://www.globalgreyebooks.com/online-books-2/john-stuart-mill_on-liberty_complete-text.html</loc></url>
</urlset>"""


def test_global_grey_searches_the_sitemap_and_follows_the_download_page(monkeypatch):
    monkeypatch.setattr(
        find_book,
        "_get",
        fake_get(
            {
                "sitemap.xml": GLOBAL_GREY_SITEMAP,
                "_complete-text.html": b'<a href="/meditations-ebook.html">Download</a>',
                "-ebook.html": b'<a href="ebooks/m.pdf">PDF</a> <a href="ebooks/m.epub">EPUB</a>',
            }
        ),
    )

    [found] = find_book._global_grey(BookQuery(title="Meditations", author="Marcus Aurelius"))

    assert (found.title, found.authors, found.fmt) == ("Meditations", "Marcus Aurelius", "epub")
    assert found.resolve(found) == "https://www.globalgreyebooks.com/ebooks/m.epub"


def test_ccel_reads_the_title_index_and_finds_the_files_on_the_book_page(monkeypatch):
    index = (
        b'<a href="/ccel/augustine/confess.html">Confessions of Saint Augustine\n   </a>'
        b'<a href="https://ccel.org/ccel/patrick/confession">Confession of St. Patrick</a>'
        b'<a href="/ccel/calvin/institutes">Institutes of the Christian Religion</a>'
    )
    book = (
        b'<a href="/ccel/a/augustine/confess/cache/confess.pdf">PDF</a>'
        b'<a href="/ccel/augustine/confess.epub">EPUB</a>'
    )
    monkeypatch.setattr(
        find_book, "_get", fake_get({"/index/title/C": index, "/ccel/augustine/confess": book})
    )

    found = find_book._ccel(BookQuery(title="The Confessions", author="Augustine"))

    assert [c.title for c in found] == ["Confessions of Saint Augustine"]
    assert found[0].resolve(found[0]) == "https://ccel.org/ccel/augustine/confess.epub"


def test_cervantes_searches_the_catalogue_by_title_words(monkeypatch):
    rows = {
        "results": {
            "bindings": [
                {
                    "t": {"value": "Niebla  / Miguel de Unamuno"},
                    "url": {"value": "https://www.cervantesvirtual.com/obra/niebla--0/"},
                    "date": {"value": "https://data.cervantesvirtual.com/date/1914"},
                }
            ]
        }
    }
    asked = []

    def _get(url, timeout=30, accept=""):
        asked.append((url, accept))
        return json.dumps(rows).encode()

    monkeypatch.setattr(find_book, "_get", _get)

    [found] = find_book._cervantes(BookQuery(title="Niebla", author="Unamuno"))

    assert (found.title, found.authors, found.year, found.fmt) == (
        "Niebla",
        "Miguel de Unamuno",
        1914,
        None,  # the site turns scripts away: a page to open in a browser
    )
    assert "niebla" in urllib.parse.unquote(asked[0][0]) and "json" in asked[0][1]


OPENSTAX_JSON = {
    "items": [
        {
            "title": "Introducción a la estadística",
            "book_state": "live",
            "high_resolution_pdf_url": "https://assets.example/estadistica.pdf",
            "meta": {"locale": "es", "html_url": "https://openstax.org/details/books/e"},
        },
        {
            "title": "Introductory Statistics",
            "book_state": "retired",
            "high_resolution_pdf_url": "https://assets.example/old.pdf",
            "meta": {"locale": "en"},
        },
    ]
}


def test_openstax_matches_live_books_by_title(monkeypatch):
    monkeypatch.setattr(
        find_book, "_get", fake_get({"openstax": json.dumps(OPENSTAX_JSON).encode()})
    )

    [found] = find_book._openstax(BookQuery(title="Introducción a la estadística"))

    assert (found.fmt, found.url, found.language) == (
        "pdf",
        "https://assets.example/estadistica.pdf",
        "es",
    )


OPEN_TEXTBOOKS_JSON = {
    "data": [
        {
            "title": "An Introduction to Philosophy",
            "url": "https://open.umn.edu/opentextbooks/textbooks/intro",
            "language": "eng",
            "copyright_year": 2023,
            "isbn13": "978-1-00",
            "contributors": [{"contribution": "Author", "first_name": "Ana", "last_name": "Ruiz"}],
            "formats": [
                {"type": "Online", "url": "https://press.example/intro/"},
                {"type": "PDF", "url": "https://press.example/intro.pdf"},
            ],
        },
        {
            "title": "Ethics",
            "url": "https://open.umn.edu/x",
            "formats": [{"url": "https://p.example/"}],
        },
    ]
}


def test_open_textbooks_download_only_direct_files(monkeypatch):
    monkeypatch.setattr(
        find_book, "_get", fake_get({"q=Introduction": json.dumps(OPEN_TEXTBOOKS_JSON).encode()})
    )

    with_pdf, link_only = find_book._open_textbooks(
        BookQuery(title="An Introduction to Philosophy")
    )

    assert (with_pdf.fmt, with_pdf.url, with_pdf.authors) == (
        "pdf",
        "https://press.example/intro.pdf",
        "Ana Ruiz",
    )
    assert (with_pdf.language, with_pdf.year, with_pdf.isbns) == ("en", 2023, ("978100",))
    assert (link_only.fmt, link_only.url, link_only.page) == (None, None, "https://open.umn.edu/x")


OPDS_FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>Niebla</title><author><name>Miguel de Unamuno</name></author>
<link type="application/pdf" href="/unamuno/niebla/pdf" rel="http://opds-spec.org/acquisition"/>
<link type="application/epub+zip" href="/unamuno/niebla/epub" rel="http://opds-spec.org/acquisition"/>
</entry>
<entry><title>Only a page</title>
<link type="text/html" href="https://lib.example/page" rel="alternate"/></entry>
</feed>"""

SEARCH_PAGE = b"""<html><body>
<a href="/files/Niebla%20(1914).pdf">Niebla, 1914 edition</a>
<a href="/about">About</a>
<a href='https://cdn.example/niebla.epub?dl=1'><b>Niebla</b> EPUB</a>
</body></html>"""


def test_a_config_site_can_be_an_opds_feed_or_a_page_of_file_links(monkeypatch):
    feed = find_book.Site("Feed", "https://lib.example/opds?q={query}")
    page = find_book.Site("Page", "https://other.example/search/{query}", quality=2)
    monkeypatch.setattr(
        find_book, "_get", fake_get({"lib.example": OPDS_FEED, "other.example": SEARCH_PAGE})
    )
    query = BookQuery(title="Niebla")

    book1, book2 = find_book._site(feed, query)
    pdf, epub = find_book._site(page, query)

    assert (book1.authors, book1.fmt, book1.url) == (
        "Miguel de Unamuno",
        "epub",
        "https://lib.example/unamuno/niebla/epub",
    )
    assert (book2.fmt, book2.url, book2.page) == (None, None, "https://lib.example/page")
    assert (pdf.title, pdf.fmt, pdf.url) == (
        "Niebla, 1914 edition",
        "pdf",
        "https://other.example/files/Niebla%20(1914).pdf",
    )
    assert (epub.title, epub.fmt, epub.quality) == ("Niebla EPUB", "epub", 2)


def test_config_file_adds_sites_and_rejects_bad_ones(tmp_path):
    good = tmp_path / "good.toml"
    good.write_text(
        'openalex_api_key = "k"\n[[sites]]\nname = "Mine"\n'
        'search = "https://lib.example/s?q={query}"\n',
        encoding="utf-8",
    )
    bad = tmp_path / "bad.toml"
    bad.write_text('[[sites]]\nname = "No query"\nsearch = "https://lib.example/"\n')

    settings = find_book.load_settings(good)

    assert settings == find_book.Settings(
        (find_book.Site("Mine", "https://lib.example/s?q={query}"),), "k"
    )
    with pytest.raises(find_book.FindBookError, match="site 1 needs"):
        find_book.load_settings(bad)
    with pytest.raises(find_book.FindBookError, match="Could not read"):
        find_book.load_settings(tmp_path / "missing.toml")


def test_a_book_from_a_url():
    candidate = find_book.candidate_from_url("https://lib.example/files/Mi%20libro.pdf")

    assert (candidate.source, candidate.title, candidate.url) == (
        "lib.example",
        "Mi libro",
        "https://lib.example/files/Mi%20libro.pdf",
    )
    with pytest.raises(find_book.FindBookError):
        find_book.candidate_from_url("file:///etc/passwd")


def test_an_internet_archive_page_downloads_the_item_pdf(monkeypatch):
    files = {"result": [{"name": "a b.pdf", "format": "Text PDF"}]}
    pages = {"/metadata/scan1": json.dumps(files).encode()}
    monkeypatch.setattr(find_book, "_get", fake_get(pages))

    candidate = find_book.candidate_from_url("https://archive.org/details/scan1/page/n5/mode/2up")

    assert (candidate.ia_id, candidate.fmt, candidate.url) == ("scan1", "pdf", None)
    assert candidate.resolve(candidate) == "https://archive.org/download/scan1/a%20b.pdf"


def test_isbn_fills_in_title_author_and_language(monkeypatch):
    edition = {"title": "Crime and punishment", "languages": [{"key": "/languages/eng"}]}
    work = {
        "docs": [{"author_name": ["Fyodor Dostoyevsky"], "ia": ["cp1"], "ebook_access": "public"}]
    }
    monkeypatch.setattr(
        find_book,
        "_get",
        fake_get(
            {
                "openlibrary.org/isbn/": json.dumps(edition).encode(),
                "openlibrary.org/search.json": json.dumps(work).encode(),
            }
        ),
    )

    query, ia_ids = find_book._open_library(BookQuery(isbn="0140449132"))

    assert (query.title, query.author, query.languages) == (
        "Crime and punishment",
        "Fyodor Dostoyevsky",
        ("en",),
    )
    assert ia_ids == ["cp1"]


# --- Ranking ------------------------------------------------------------------------


def book(**kwargs):
    return Candidate(**{"source": "Test", "title": "Crime and Punishment", "page": "p"} | kwargs)


def test_score_drops_other_books_and_tolerates_spellings():
    query = BookQuery(title="Crime and Punishment", author="Dostoevsky")

    assert score_candidate(book(title="War and Peace"), query) is None
    assert score_candidate(book(authors="Fyodor Dostoyevsky"), query) > score_candidate(
        book(authors="Someone Else"), query
    )


def test_score_prefers_asked_format_language_and_translator():
    query = BookQuery(title="Crime and Punishment", languages=("en",), fmt="pdf")

    assert score_candidate(book(fmt="pdf"), query) > score_candidate(
        book(fmt="epub", quality=15), query
    )
    assert score_candidate(book(fmt="pdf", language="en"), query) > score_candidate(
        book(fmt="pdf", language="fr"), query
    )
    assert score_candidate(book(fmt="pdf"), query) > score_candidate(book(), query)  # link only
    any_format = BookQuery(title="Crime and Punishment")
    assert score_candidate(book(fmt="epub", quality=5), any_format) > score_candidate(
        book(fmt="pdf", quality=5), any_format
    )
    assert score_candidate(book(fmt="epub"), any_format) == score_candidate(  # IA's OCR EPUB
        book(fmt="pdf"), any_format
    )
    garnett = BookQuery(title="Crime and Punishment", translator="Constance Garnett")
    assert score_candidate(book(details="constance garnett"), garnett) > score_candidate(
        book(), garnett
    )


def test_score_puts_the_asked_translation_and_year_above_a_better_source():
    # Lisi's Timeo (Gredos 1992) on Internet Archive, whose record doesn't name him, vs
    # another Timeo as an edited EPUB with no year.
    query = BookQuery(
        title="Timeo", author="Platon", year=1992, translator="Francisco Lisi", languages=("es",)
    )
    gredos = book(title="Diálogos VI Filebo Timeo Critias", authors="Platón", year=1992, fmt="pdf")
    other = book(title="Timeo", authors="Platon", fmt="epub", quality=10)
    for candidate in (gredos, other):
        candidate.language = "es"

    assert score_candidate(gredos, query) > score_candidate(other, query)


# --- Downloading and checking ---------------------------------------------------------


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_download_saves_the_book_atomically(monkeypatch, tmp_path):
    monkeypatch.setattr(
        find_book.urllib.request, "urlopen", lambda *a, **k: FakeResponse(b"PK\x03\x04data")
    )

    # The site said PDF; the bytes say EPUB, and they win.
    path = find_book.download(
        book(fmt="pdf", url="https://example.org/b", authors="F. Dostoevsky"), tmp_path
    )

    assert path == tmp_path / "F. Dostoevsky - Crime and Punishment.epub"
    assert path.read_bytes() == b"PK\x03\x04data"
    assert [p.name for p in tmp_path.iterdir()] == [path.name]


def test_download_refuses_a_web_page(monkeypatch, tmp_path):
    monkeypatch.setattr(
        find_book.urllib.request, "urlopen", lambda *a, **k: FakeResponse(b"<html>")
    )

    with pytest.raises(find_book.FindBookError, match="web page"):
        find_book.download(book(fmt="pdf", url="https://example.org/b"), tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_check_pdf_with_text_suggests_processing(make_pdf):
    pdf = make_pdf(["Some text"] * 3)
    check = find_book.check_download(pdf)

    assert "Usable as it is" in check.summary
    assert [s.argv for s in check.steps] == [["process", str(pdf)]]


def test_check_scan_says_it_needs_ocr(make_pdf):
    pdf = make_pdf(["", "", ""])

    check = find_book.check_download(pdf, language="la")

    assert "needs OCR" in check.summary
    assert [s.argv for s in check.steps] == [["process", str(pdf)]]


def test_check_epub_and_lay_it_out_as_pdf(tmp_path):
    epub = make_epub(tmp_path / "book.epub", "out of pity﻿—for I repeat. " * 40)

    check = find_book.check_download(epub)
    pages = ebook_to_pdf(epub, tmp_path / "book.pdf")

    assert "valid EPUB" in check.summary
    assert check.steps[0].argv == ["process", str(epub)]
    with pymupdf.open(tmp_path / "book.pdf") as pdf:
        assert pdf.page_count == pages
        assert pdf.metadata["title"] == "Test Book"
        text = pdf.load_page(0).get_text()
    assert "pity—for I repeat" in text
    assert sorted(p.name for p in tmp_path.iterdir()) == ["book.epub", "book.pdf"]


# --- CLI ----------------------------------------------------------------------------


def test_find_book_cli_downloads_the_best_and_suggests_steps(monkeypatch, make_pdf, capsys):
    pdf = make_pdf(["Some text"])
    links = book(source="DOAB", score=99)
    best = book(source="Internet Archive", fmt="pdf", resolve=lambda c: "u", score=50)
    monkeypatch.setattr(
        find_book,
        "find_candidates",
        lambda q, settings: find_book.SearchResult(q, [links, best], ["DOAB: timed out"]),
    )
    monkeypatch.setattr(find_book, "download", lambda c, folder: pdf)

    assert main(["find-book", "--title", "Crime and Punishment", "--language", "en,spa"]) == 0

    captured = capsys.readouterr()
    assert "2. Crime and Punishment [Internet Archive, pdf]" in captured.out
    assert "1. Crime and Punishment [DOAB, web page only]" in captured.out
    assert f"Saved {pdf}" in captured.out
    assert f"pdf-worker process {pdf}" in captured.out
    assert "Warning: skipped DOAB: timed out" in captured.err


def test_find_book_cli_needs_some_detail(capsys):
    assert main(["find-book"]) == 1
    assert "at least a title" in capsys.readouterr().err


def test_find_book_cli_checks_a_given_file(make_pdf, capsys):
    pdf = make_pdf(["", ""])

    assert main(["find-book", "--file", str(pdf), "--language", "es"]) == 0

    out = capsys.readouterr().out
    assert "needs OCR" in out
    assert f"pdf-worker process {pdf}" in out


def test_find_book_asks_for_details_and_runs_the_chosen_step(
    monkeypatch, make_pdf, tmp_path, capsys
):
    from pdf_worker import cli

    pdf = make_pdf(["Some text"] * 2)
    queries = []

    def find_candidates(query, settings):
        queries.append(query)
        return find_book.SearchResult(query, [book(fmt="pdf", url="u")])

    # Title, author, ISBN, year, translator, languages, format; then the download
    # choice (Enter: the best) and the step to run (1: process).
    answers = iter(["Confesiones", "Agustín", "", "1905", "", "es", "pdf", "", "1"])
    monkeypatch.chdir(tmp_path)  # process's folder is ./file_conversion
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    monkeypatch.setattr(cli, "_ask_yes", lambda prompt: False)
    monkeypatch.setattr(find_book, "find_candidates", find_candidates)
    monkeypatch.setattr(find_book, "download", lambda c, folder: pdf)

    assert main(["find-book"]) == 0

    assert queries == [
        BookQuery(title="Confesiones", author="Agustín", year=1905, languages=("es",), fmt="pdf")
    ]
    outbox = tmp_path / "file_conversion" / "file_outbox"
    assert list(outbox.rglob(f"{pdf.stem}.epub"))
