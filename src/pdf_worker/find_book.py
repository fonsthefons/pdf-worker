"""Find a book in open, legal online libraries, download the best copy and check it.

Libraries searched (all free, public-domain or open-access):

* Project Gutenberg: clean EPUBs of public-domain books (OPDS search).
* Standard Ebooks: carefully edited public-domain EPUBs (English only).
* Internet Archive: scanned books, freely downloadable ones only (no lending items).
* Open Library: turns an ISBN into title and author, and adds its free scans.
* Wikisource: transcribed texts in any language, exported as EPUB.
* OpenAlex: recent open-access academic books, with their free PDF when it has one.
* DOAB (open-access academic books) and HathiTrust: links to open in a browser;
  their downloads are behind bot checks or a login.
* Sites the user adds in the config file (``find-book.toml``): an OPDS catalogue or
  a search page linking to PDF/EPUB files.

Cervantes Virtual, PhilArchive, OAPEN and SciELO Books block automated access, and
Google Books needs an API key, so they are not searched.
"""

import html
import json
import os
import re
import tempfile
import tomllib
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from difflib import SequenceMatcher
from pathlib import Path

import pymupdf

from pdf_worker.document import open_pdf
from pdf_worker.ebook_to_pdf import quiet_mupdf
from pdf_worker.errors import PdfWorkerError
from pdf_worker.ocr import default_output_path as ocr_default_output_path
from pdf_worker.ocr_check import assess_text_layer

USER_AGENT = "pdf-worker/0.1 (personal book finder)"
FORMATS = ("pdf", "epub")
DEFAULT_CONFIG = Path.home() / ".config" / "pdf-worker" / "find-book.toml"
_ATOM = "{http://www.w3.org/2005/Atom}"
# Language names and codes seen in the catalogues -> ISO 639-1.
_LANGUAGES = {
    "en": ("en", "eng", "english"),
    "es": ("es", "spa", "spanish", "español", "castellano"),
    "la": ("la", "lat", "latin"),
    "fr": ("fr", "fre", "fra", "french"),
    "de": ("de", "ger", "deu", "german"),
    "it": ("it", "ita", "italian"),
    "el": ("el", "gre", "ell", "grc", "greek"),
    "pt": ("pt", "por", "portuguese"),
}
_TESSERACT = {"en": "eng", "es": "spa", "la": "lat", "fr": "fra", "de": "deu", "it": "ita"}
_STOPWORDS = {
    "the", "and", "for", "with", "los", "las", "del", "con", "por", "una", "une", "des",
    "der", "die", "das",
}  # fmt: skip


class FindBookError(PdfWorkerError):
    """No usable result, or a download that failed."""


@dataclass(frozen=True)
class BookQuery:
    title: str = ""
    author: str = ""
    isbn: str = ""
    year: int | None = None
    translator: str = ""
    languages: tuple[str, ...] = ()  # ISO 639-1 codes; empty means any
    fmt: str | None = None  # preferred format: "pdf", "epub" or None


@dataclass
class Candidate:
    source: str
    title: str
    page: str  # the book's web page
    authors: str = ""
    year: int | None = None
    language: str | None = None  # ISO 639-1 when known
    fmt: str | None = None  # "pdf" / "epub", or None: open the page in a browser
    url: str | None = None  # direct download, when known without another request
    details: str = ""  # other text that may name the translator or the edition
    isbns: tuple[str, ...] = ()
    ia_id: str = ""  # Internet Archive identifier
    # Finds the file's URL on download, when the search did not give it (one request
    # or more, so only for the chosen book).
    resolve: Callable[["Candidate"], str] | None = field(default=None, repr=False)
    quality: int = 0  # how good this source's files usually are
    score: float = 0.0


@dataclass(frozen=True)
class Site:
    """A site from the config file; ``search`` holds ``{query}`` for the search words."""

    name: str
    search: str
    quality: int = 5


# Free Spanish library with an OPDS search (EPUB, PDF and MOBI of each text).
TEXTOS_INFO = Site("textos.info", "https://www.textos.info/busqueda.atom&query={query}", 8)


@dataclass(frozen=True)
class Settings:
    sites: tuple[Site, ...] = ()
    openalex_api_key: str = ""


def load_settings(path: Path | None = None) -> Settings:
    """Read the config file; no file at the default place means no settings.

    Example ``~/.config/pdf-worker/find-book.toml``::

        openalex_api_key = "..."   # optional, free at openalex.org/settings/api

        [[sites]]
        name = "My library"
        search = "https://books.example.org/opds/search?q={query}"
    """
    if path is None:
        path = DEFAULT_CONFIG
        if not path.is_file():
            return Settings()
    try:
        data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise FindBookError(f"Could not read the config file {path}: {exc}") from exc
    sites = []
    for number, site in enumerate(data.get("sites", []), 1):
        name, search = str(site.get("name", "")).strip(), str(site.get("search", ""))
        if not name or "{query}" not in search or not search.startswith(("http://", "https://")):
            raise FindBookError(
                f"{path}: site {number} needs a name and a search URL (http...) with {{query}}"
            )
        sites.append(Site(name, search, int(site.get("quality", 5))))
    return Settings(tuple(sites), str(data.get("openalex_api_key", "")))


@dataclass
class SearchResult:
    query: BookQuery  # with title and author filled in from the ISBN when missing
    candidates: list[Candidate]  # best first
    warnings: list[str] = field(default_factory=list)


@dataclass
class NextStep:
    description: str
    argv: list[str]  # pdf-worker arguments


@dataclass
class QualityCheck:
    fmt: str
    summary: str
    steps: list[NextStep]


def normalize_language(value: str | None) -> str | None:
    value = (value or "").strip().lower()
    for code, names in _LANGUAGES.items():
        if value in names:
            return code
    return value[:2] if len(value) == 2 else None


def normalize_isbn(value: str) -> str:
    return re.sub(r"[^0-9Xx]", "", value).upper()


# --- HTTP ---------------------------------------------------------------------------


def _request(url: str) -> urllib.request.Request:
    return urllib.request.Request(url, headers={"User-Agent": USER_AGENT})


def _get(url: str, timeout: float = 30) -> bytes:
    with urllib.request.urlopen(_request(url), timeout=timeout) as response:
        return response.read()


def _json(url: str):
    return json.loads(_get(url))


# --- Searching ----------------------------------------------------------------------


def find_candidates(query: BookQuery, settings: Settings | None = None) -> SearchResult:
    """Search every library at once and rank the results, best first."""
    settings = settings or Settings()
    warnings: list[str] = []
    ia_ids: list[str] = []
    if query.isbn:
        try:
            query, ia_ids = _open_library(query)
        except (OSError, ValueError) as exc:
            warnings.append(f"Open Library: {exc}")
    if not (query.title or query.author or query.isbn):
        raise FindBookError("Give at least a title, an author or an ISBN.")
    searches = {
        "Project Gutenberg": lambda: _gutenberg(query),
        "Standard Ebooks": lambda: _standard_ebooks(query),
        "Internet Archive": lambda: _internet_archive(query, ia_ids),
        "Wikisource": lambda: _wikisource(query),
        "OpenAlex": lambda: _openalex(query, settings.openalex_api_key),
        "DOAB": lambda: _doab(query),
        "HathiTrust": lambda: _hathitrust(query),
        "OpenStax": lambda: _openstax(query),
        "Open Textbook Library": lambda: _open_textbooks(query),
    }
    if not query.languages or "en" in query.languages:
        searches["Global Grey"] = lambda: _global_grey(query)
    if not query.languages or "es" in query.languages:
        searches["Elejandría"] = lambda: _elejandria(query)
        searches["textos.info"] = lambda: _site(TEXTOS_INFO, query)
    for site in settings.sites:
        searches[site.name] = lambda site=site: _site(site, query)
    candidates: list[Candidate] = []
    with ThreadPoolExecutor(max_workers=len(searches)) as pool:
        futures = {name: pool.submit(search) for name, search in searches.items()}
        for name, future in futures.items():
            try:
                candidates += future.result()
            except (OSError, ValueError, KeyError, ET.ParseError) as exc:
                warnings.append(f"{name}: {exc}")
    ranked = []
    for candidate in candidates:
        score = score_candidate(candidate, query)
        if score is not None:
            candidate.score = score
            ranked.append(candidate)
    ranked.sort(key=lambda c: c.score, reverse=True)
    return SearchResult(query, _dedupe(ranked), warnings)


def _dedupe(candidates: list[Candidate]) -> list[Candidate]:
    seen, unique = set(), []
    for candidate in candidates:
        key = candidate.url or candidate.ia_id or candidate.page
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def _terms(text: str) -> str:
    """Words only: punctuation would be search syntax in some catalogues."""
    return " ".join(re.findall(r"\w+", text))


def _key_terms(query: BookQuery) -> list[str]:
    """The title's words, else the author's: author spellings vary (Dostoyevsky).

    Short words and stopwords are left out: Gutenberg finds nothing for 't.and'."""
    words = _terms(query.title).split() or _terms(query.author).split()
    return [w for w in words if len(w) > 2 and w.lower() not in _STOPWORDS]


def _open_library(query: BookQuery) -> tuple[BookQuery, list[str]]:
    """Fill title, author and language from the ISBN; return the work's free scans."""
    try:
        edition = _json(f"https://openlibrary.org/isbn/{query.isbn}.json")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return query, []  # not in Open Library
        raise
    fields = "author_name,ia,ebook_access"
    data = _json(f"https://openlibrary.org/search.json?isbn={query.isbn}&fields={fields}&limit=1")
    work = (data.get("docs") or [{}])[0]
    # The edition's own title and language: the work's may be the original's (Russian).
    languages = [
        normalize_language(lang.get("key", "").rsplit("/", 1)[-1])
        for lang in edition.get("languages", [])
    ]
    query = replace(
        query,
        title=query.title or edition.get("title", ""),
        author=query.author or ", ".join(work.get("author_name", [])[:1]),
        languages=query.languages or tuple(lang for lang in languages if lang),
    )
    ia = work.get("ia", []) if work.get("ebook_access") == "public" else []
    return query, ia[:50]


def _gutenberg(query: BookQuery) -> list[Candidate]:
    # Plain words: the "t." title prefix finds nothing for "t.Don t.Quijote".
    terms = " ".join(_key_terms(query))
    if not terms:
        return []
    candidates = []
    for language in query.languages or (None,):
        search = terms + (f" l.{language}" if language else "")
        url = "https://www.gutenberg.org/ebooks/search.opds/?" + urllib.parse.urlencode(
            {"query": search}
        )
        for entry in ET.fromstring(_get(url)).iter(f"{_ATOM}entry"):
            number = re.search(r"/ebooks/(\d+)\.opds$", entry.findtext(f"{_ATOM}id", ""))
            if not number:
                continue  # navigation entries ("sort by ...")
            title = entry.findtext(f"{_ATOM}title", "")
            named = re.search(r"\s*\((\w+)\)$", title)
            candidates.append(
                Candidate(
                    source="Project Gutenberg",
                    title=title[: named.start()] if named else title,
                    authors=entry.findtext(f"{_ATOM}content", ""),
                    language=language or normalize_language(named and named[1]) or "en",
                    fmt="epub",
                    url=f"https://www.gutenberg.org/ebooks/{number[1]}.epub3.images",
                    page=f"https://www.gutenberg.org/ebooks/{number[1]}",
                    quality=10,
                )
            )
    return candidates


def _standard_ebooks(query: BookQuery) -> list[Candidate]:
    if query.languages and "en" not in query.languages:
        return []
    terms = " ".join(_key_terms(query))
    if not terms:
        return []
    url = "https://standardebooks.org/ebooks?" + urllib.parse.urlencode({"query": terms})
    html = _get(url).decode("utf-8", "replace")
    candidates = []
    for slug, block in re.findall(
        r'<li typeof="schema:Book" about="/ebooks/([^"]+)">(.*?)</li>', html, re.S
    ):
        names = re.findall(r'property="schema:name">([^<]*)<', block)
        parts = slug.split("/")
        base = f"https://standardebooks.org/ebooks/{slug}"
        candidates.append(
            Candidate(
                source="Standard Ebooks",
                title=_unescape(names[0]) if names else parts[1].replace("-", " "),
                authors=", ".join(_unescape(n) for n in names[1:]),
                details=" ".join(parts[2:]).replace("-", " "),  # the translator
                language="en",
                fmt="epub",
                # Without ?source=download the site answers with a "download started" page.
                url=f"{base}/downloads/{'_'.join(parts)}.epub?source=download",
                page=base,
                quality=15,
            )
        )
    return candidates


def _unescape(text: str) -> str:
    return html.unescape(text).strip()


def _internet_archive(query: BookQuery, ia_ids: list[str]) -> list[Candidate]:
    parts = [
        f"{key}:({_terms(value)})"
        for key, value in (("title", query.title), ("creator", query.author))
        if _terms(value)
    ]
    searches = [" AND ".join(parts)] if parts else []
    if query.isbn:
        searches.append(f"isbn:{query.isbn}")
    if ia_ids:
        searches.append(f"identifier:({' OR '.join(ia_ids)})")
    if not searches:
        return []
    q = (
        "(" + " OR ".join(f"({s})" for s in searches) + ") AND mediatype:texts"
        " AND -access-restricted-item:true"
    )
    params = [("q", q), ("rows", "40"), ("output", "json")]
    params += [
        ("fl[]", name)
        for name in ("identifier", "title", "creator", "year", "language", "format", "isbn")
    ]
    data = _json("https://archive.org/advancedsearch.php?" + urllib.parse.urlencode(params))
    candidates = []
    for doc in data.get("response", {}).get("docs", []):
        formats = set(_as_list(doc.get("format")))
        text_pdf = bool(formats & {"Text PDF", "Additional Text PDF"})
        has_pdf = text_pdf or "Image Container PDF" in formats
        has_epub = "EPUB" in formats
        # The archive's EPUBs are made from its OCR, often messy: prefer the scan's PDF.
        fmt = "epub" if has_epub and (query.fmt == "epub" or not has_pdf) else None
        fmt = fmt or ("pdf" if has_pdf else None)
        if not fmt:
            continue
        identifier = doc["identifier"]
        candidates.append(
            Candidate(
                source="Internet Archive",
                title=_first(doc.get("title")),
                authors="; ".join(_as_list(doc.get("creator"))),
                year=_year(doc.get("year")),
                language=normalize_language(_first(doc.get("language"))),
                fmt=fmt,
                page=f"https://archive.org/details/{identifier}",
                ia_id=identifier,
                resolve=_archive_file_url,
                isbns=tuple(normalize_isbn(i) for i in _as_list(doc.get("isbn"))),
                quality=3 if fmt == "pdf" and text_pdf else 0,  # else OCR first
            )
        )
    return candidates


def _as_list(value) -> list[str]:
    if value is None:
        return []
    return [str(v) for v in value] if isinstance(value, list) else [str(value)]


def _first(value) -> str:
    values = _as_list(value)
    return values[0] if values else ""


def _year(value) -> int | None:
    match = re.search(r"\d{4}", _first(value))
    return int(match[0]) if match else None


def _wikisource(query: BookQuery) -> list[Candidate]:
    terms = _terms(query.title) or _terms(query.author)
    if not terms:
        return []
    candidates = []
    for language in query.languages or ("en", "es"):
        params = urllib.parse.urlencode(
            {
                "action": "query",
                "list": "search",
                "srsearch": terms,
                "srnamespace": 0,
                "srlimit": 10,
                "format": "json",
            }
        )
        data = _json(f"https://{language}.wikisource.org/w/api.php?{params}")
        for hit in data.get("query", {}).get("search", []):
            title = hit["title"]
            if "/" in title:
                continue  # a chapter of a work, not the work
            page = urllib.parse.quote(title.replace(" ", "_"))
            candidates.append(
                Candidate(
                    source="Wikisource",
                    title=title,
                    details=re.sub(r"<[^>]+>", "", hit.get("snippet", "")),
                    language=language,
                    fmt="epub",
                    url=f"https://ws-export.wmcloud.org/?format=epub&lang={language}&page={page}",
                    page=f"https://{language}.wikisource.org/wiki/{page}",
                    quality=5,
                )
            )
    return candidates


def _doab(query: BookQuery) -> list[Candidate]:
    terms = _terms(f"{query.title} {query.author}") or query.isbn
    url = "https://directory.doabooks.org/open-search/discover?" + urllib.parse.urlencode(
        {"query": terms, "format": "atom"}
    )
    candidates = []
    for entry in ET.fromstring(_get(url)).iter(f"{_ATOM}entry"):
        title = entry.findtext(f"{_ATOM}title", "")
        if title == "Untitled":
            continue
        authors = [a.findtext(f"{_ATOM}name", "") for a in entry.iter(f"{_ATOM}author")]
        published = entry.findtext(f"{_ATOM}published", "")
        candidates.append(
            Candidate(
                source="DOAB",
                title=title,
                authors=", ".join(a for a in authors if a),
                year=_year(published),
                details=entry.findtext(f"{_ATOM}summary", ""),
                page=entry.findtext(f"{_ATOM}id", ""),
                quality=5,
            )
        )
    return candidates


def _hathitrust(query: BookQuery) -> list[Candidate]:
    if not query.isbn:
        return []  # its catalogue API only looks up identifiers
    data = _json(f"https://catalog.hathitrust.org/api/volumes/brief/isbn/{query.isbn}.json")
    records = data.get("records", {})
    candidates = []
    for item in data.get("items", []):
        if not item.get("usRightsString", "").startswith("Full"):
            continue
        record = records.get(item.get("fromRecord"), {})
        candidates.append(
            Candidate(
                source="HathiTrust",
                title=_first(record.get("titles")) or query.title,
                year=_year(record.get("publishDates")),
                details=item.get("enumcron") or "",
                isbns=(query.isbn,),
                page=item.get("itemURL", ""),
            )
        )
    return candidates


def _openalex(query: BookQuery, api_key: str = "") -> list[Candidate]:
    words = " ".join(_key_terms(query))
    if not words:
        return []
    field = "title.search" if _terms(query.title) else "raw_author_name.search"
    filters = [f"{field}:{words}", "type:book|book-chapter", "is_oa:true"]
    if query.languages:
        filters.append("language:" + "|".join(query.languages))
    params = {
        "filter": ",".join(filters),
        "per_page": 25,
        "select": "id,title,publication_year,language,locations,authorships",
    }
    if api_key:
        params["api_key"] = api_key
    data = _json("https://api.openalex.org/works?" + urllib.parse.urlencode(params))
    candidates = []
    for work in data.get("results", []):
        locations = work.get("locations") or []
        pdf = next((loc["pdf_url"] for loc in locations if loc.get("pdf_url")), None)
        page = next(
            (loc["landing_page_url"] for loc in locations if loc.get("landing_page_url")),
            work["id"],
        )
        candidates.append(
            Candidate(
                source="OpenAlex",
                title=work.get("title") or "",
                authors=", ".join(
                    a["author"]["display_name"] for a in work.get("authorships", [])[:3]
                ),
                year=work.get("publication_year"),
                language=normalize_language(work.get("language")),
                # The format shows when the file arrives; the URL usually says it.
                fmt="epub" if pdf and ".epub" in pdf.lower() else ("pdf" if pdf else None),
                url=pdf,
                page=page,
                quality=5,
            )
        )
    return candidates


_ELEJANDRIA = "https://www.elejandria.com"
_ELEJANDRIA_BOOK_RE = re.compile(
    rb"<loc>(https://www\.elejandria\.com/libro/([^/<]+)/([^/<]+)/\d+)</loc>"
)


def _elejandria(query: BookQuery) -> list[Candidate]:
    """Spanish public-domain and free-licence ebooks, edited (PDF and EPUB).

    Its search runs in the browser (Google), so the sitemap, which lists every book
    as /libro/<title>/<author>/<id>, is searched instead (about 400 KB)."""
    wanted = _words(" ".join(_key_terms(query)))
    if not wanted:
        return []
    candidates = []
    for url, title, author in _ELEJANDRIA_BOOK_RE.findall(_get(f"{_ELEJANDRIA}/sitemap.xml")):
        title = title.decode("utf-8", "replace").replace("-", " ")
        author = author.decode("utf-8", "replace").replace("-", " ")
        if not wanted & _words(f"{title} {author}"):
            continue
        candidates.append(
            Candidate(
                source="Elejandría",
                title=title.capitalize(),
                authors=author.title(),
                language="es",
                fmt=query.fmt or "epub",
                page=url.decode(),
                resolve=_elejandria_file_url,
                quality=10,
            )
        )
    return candidates


def _elejandria_file_url(candidate: Candidate) -> str:
    """The book page's 'Descargar en ePub/PDF' button leads, past a 'download
    started' page, to /libro/link_descarga_libro/<book>/<file>: the file itself."""
    try:
        page = _get(candidate.page).decode("utf-8", "replace")
    except OSError as exc:
        raise FindBookError(f"Elejandría: {exc}") from exc
    buttons = re.findall(
        r'href="[^"]*/libro/descargar/[^"]*/(\d+)/(\d+)"[^>]*>.*?Descargar en (\w+)</a>',
        page,
        re.S,
    )
    for book, file, fmt in sorted(buttons, key=lambda b: b[2].lower() != candidate.fmt):
        if fmt.lower() in FORMATS:
            return f"{_ELEJANDRIA}/libro/link_descarga_libro/{book}/{file}"
    raise FindBookError(f"Elejandría has no PDF or EPUB of this book: {candidate.page}")


_FILE_LINK_RE = re.compile(
    r"<a\s[^>]*?href=[\"']([^\"']+?\.(pdf|epub)(?:\?[^\"']*)?)[\"'][^>]*>(.*?)</a>", re.I | re.S
)


def _openstax(query: BookQuery) -> list[Candidate]:
    """Peer-reviewed open textbooks (English and Spanish), each with a free PDF.

    There is no search: the whole list (about 130 books) is one small request."""
    wanted = _words(" ".join(_key_terms(query)))
    if not wanted:
        return []
    url = (
        "https://openstax.org/apps/cms/api/v2/pages/?type=books.Book&limit=250"
        "&fields=title,book_state,high_resolution_pdf_url"
    )
    candidates = []
    for book in _json(url).get("items", []):
        pdf = book.get("high_resolution_pdf_url")
        if book.get("book_state") != "live" or not pdf or not wanted & _words(book["title"]):
            continue
        candidates.append(
            Candidate(
                source="OpenStax",
                title=book["title"],
                language=normalize_language(book["meta"].get("locale")),
                fmt="pdf",
                url=pdf,
                page=book["meta"].get("html_url", url),
                quality=10,
            )
        )
    return candidates


def _open_textbooks(query: BookQuery) -> list[Candidate]:
    """Open Textbook Library (University of Minnesota): openly licensed academic books.

    Most link to the publisher's page (often Pressbooks, which blocks scripts), so only
    a format link that is itself a .pdf or .epub becomes a download."""
    words = " ".join(_key_terms(query))
    if not words:
        return []
    url = "https://open.umn.edu/opentextbooks/textbooks.json?" + urllib.parse.urlencode(
        {"q": words}
    )
    candidates = []
    for book in _json(url).get("data", []):
        files = [
            (ext, f["url"])
            for f in book.get("formats", [])
            if (ext := Path(urllib.parse.urlparse(f.get("url") or "").path).suffix.lower()[1:])
            in ("pdf", "epub")
        ]
        files.sort(key=lambda f: f[0] != (query.fmt or "epub"))
        people = [c for c in book.get("contributors", []) if c.get("contribution") == "Author"]
        candidates.append(
            Candidate(
                source="Open Textbook Library",
                title=book.get("title") or "",
                authors=", ".join(
                    f"{c.get('first_name') or ''} {c.get('last_name') or ''}".strip()
                    for c in people
                ),
                year=book.get("copyright_year"),
                language=normalize_language(book.get("language")),
                fmt=files[0][0] if files else None,
                url=files[0][1] if files else None,
                page=book.get("url") or url,
                isbns=tuple(
                    normalize_isbn(i) for i in (book.get("isbn13"), book.get("isbn10")) if i
                ),
                quality=5,
            )
        )
    return candidates


_GLOBAL_GREY = "https://www.globalgreyebooks.com"
# The read-online pages, /<folder>/<author>_<title>_complete-text.html, link to the
# book's download page ("Download ebook instead"), whose address can't be guessed.
_GLOBAL_GREY_BOOK_RE = re.compile(
    rb"<loc>(https://www\.globalgreyebooks\.com/(?:online-ebooks|online-books-2)/"
    rb"([^_<]+)_([^<]+)_complete-text\.html)</loc>"
)
_GLOBAL_GREY_EBOOK_RE = re.compile(r"href=\"([^\"]+-ebook\.html)\"")


def _global_grey(query: BookQuery) -> list[Candidate]:
    """English public-domain classics, carefully formatted (PDF, EPUB, AZW3).

    Its search is Google's, so the sitemap (author and title in each address) is searched."""
    wanted = _words(" ".join(_key_terms(query)))
    if not wanted:
        return []
    candidates = []
    for page, author, title in _GLOBAL_GREY_BOOK_RE.findall(_get(f"{_GLOBAL_GREY}/sitemap.xml")):
        author, title = author.decode(), title.decode()
        if not wanted & _words(f"{title} {author}".replace("-", " ")):
            continue
        candidates.append(
            Candidate(
                source="Global Grey",
                title=title.replace("-", " ").capitalize(),
                authors=author.replace("-", " ").title(),
                language="en",
                fmt=query.fmt if query.fmt in ("pdf", "epub") else "epub",
                page=page.decode(),
                resolve=_global_grey_file_url,
                quality=10,
            )
        )
    return candidates


def _global_grey_file_url(candidate: Candidate) -> str:
    try:
        page = _get(candidate.page).decode("utf-8", "replace")
        ebook = _GLOBAL_GREY_EBOOK_RE.search(page)
        ebook_url = urllib.parse.urljoin(candidate.page, html.unescape(ebook[1])) if ebook else ""
        page = _get(ebook_url).decode("utf-8", "replace") if ebook else ""
    except OSError as exc:
        raise FindBookError(f"Global Grey: {exc}") from exc
    links = sorted(_FILE_LINK_RE.findall(page), key=lambda link: link[1].lower() != candidate.fmt)
    if not links:
        raise FindBookError(f"Global Grey has no PDF or EPUB of this book: {candidate.page}")
    return urllib.parse.urljoin(ebook_url, html.unescape(links[0][0]))


def _site(site: Site, query: BookQuery) -> list[Candidate]:
    """A site from the config file: an OPDS feed, or a page that links to the files."""
    words = " ".join(_key_terms(query))
    if not words:
        return []
    url = site.search.replace("{query}", urllib.parse.quote_plus(words))
    body = _get(url)
    if body.lstrip().startswith(b"<?xml") or b"<feed" in body[:2000]:
        return _opds_candidates(site, url, ET.fromstring(body))
    candidates = []
    for href, ext, text in _FILE_LINK_RE.findall(body.decode("utf-8", "replace")):
        link = urllib.parse.urljoin(url, html.unescape(href))
        title = " ".join(_unescape(re.sub(r"<[^>]+>", " ", text)).split())
        name = urllib.parse.unquote(Path(urllib.parse.urlparse(link).path).stem)
        candidates.append(
            Candidate(
                source=site.name,
                title=title if len(title) > 3 else name.replace("_", " ").replace("-", " "),
                details=name,
                fmt=ext.lower(),
                url=link,
                page=url,
                quality=site.quality,
            )
        )
    return candidates


def _opds_candidates(site: Site, base: str, feed: ET.Element) -> list[Candidate]:
    types = {"application/pdf": "pdf", "application/epub+zip": "epub"}
    candidates = []
    for entry in feed.iter(f"{_ATOM}entry"):
        links = list(entry.iter(f"{_ATOM}link"))
        files = [
            (types[link.get("type", "").split(";")[0]], link.get("href", ""))
            for link in links
            if "acquisition" in link.get("rel", "") and link.get("type", "").split(";")[0] in types
        ]
        files.sort(key=lambda f: f[0] != "epub")  # an OPDS catalogue's EPUB is its own text
        page = next((link.get("href") for link in links if link.get("href")), base)
        authors = [a.findtext(f"{_ATOM}name", "") for a in entry.iter(f"{_ATOM}author")]
        candidates.append(
            Candidate(
                source=site.name,
                title=entry.findtext(f"{_ATOM}title", ""),
                authors=", ".join(a for a in authors if a),
                year=_year(entry.findtext("{http://purl.org/dc/terms/}issued")),
                language=normalize_language(entry.findtext("{http://purl.org/dc/terms/}language")),
                fmt=files[0][0] if files else None,
                url=urllib.parse.urljoin(base, files[0][1]) if files else None,
                page=urllib.parse.urljoin(base, page),
                quality=site.quality,
            )
        )
    return candidates


# --- Ranking ------------------------------------------------------------------------


def _words(text: str) -> set[str]:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return {w for w in re.findall(r"\w+", text) if len(w) > 2 and w not in _STOPWORDS}


def score_candidate(candidate: Candidate, query: BookQuery) -> float | None:
    """How well a result fits the query; None when it is clearly another book."""
    score = float(candidate.quality)
    if query.isbn and query.isbn in candidate.isbns:
        score += 50
    elif query.title:
        wanted, found = _words(query.title), _words(candidate.title)
        if wanted:
            share = len(wanted & found) / len(wanted)
            if share < 0.5:
                return None
            extra = len(found - wanted) / max(len(found), 1)  # "Commentary on X" for X
            score += 40 * share - 15 * extra
    people = _words(f"{candidate.authors} {candidate.details} {candidate.title}")
    if query.author:
        if _similar(_words(_surname(query.author)), people):
            score += 20
        elif not query.title:
            return None
        else:
            score -= 10
    if query.translator and _similar(_words(_surname(query.translator)), people):
        score += 15
    if query.languages and candidate.language:
        score += 10 if candidate.language in query.languages else -30
    if query.year and candidate.year:
        score += 10 - min(abs(query.year - candidate.year), 20)
    if candidate.fmt is None:
        score -= 25  # only a page to open in a browser
    elif query.fmt == candidate.fmt:
        score += 30  # asked for explicitly: beats a better-edited copy in the other format
    elif query.fmt is None and candidate.fmt == "epub" and candidate.quality > 0:
        score += 15  # a real (not OCR-made) EPUB gives a clean PDF and EPUB with no OCR
    return score


def _similar(names: set[str], words: set[str]) -> bool:
    """A name among the words, allowing other spellings (Dostoevsky / Dostoyevsky)."""
    return any(SequenceMatcher(None, n, w).ratio() >= 0.8 for n in names for w in words)


def _surname(name: str) -> str:
    """'Cervantes, Miguel de' -> 'Cervantes'; 'Miguel de Cervantes' -> 'Cervantes'."""
    return name.split(",")[0] if "," in name else (name.split() or [""])[-1]


# --- Downloading --------------------------------------------------------------------


def download(candidate: Candidate, folder: Path) -> Path:
    """Download ``candidate`` into ``folder``; return the file's path.

    The format comes from the file's first bytes, not from what the site claimed."""
    if not (candidate.url or candidate.resolve):
        raise FindBookError(f"{candidate.source} has no direct download: {candidate.page}")
    url = candidate.url or candidate.resolve(candidate)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=folder, prefix=".find-book.", suffix=".tmp")
    try:
        # Wikisource builds its EPUB on request: long books take minutes.
        with (
            os.fdopen(fd, "wb") as out,
            urllib.request.urlopen(_request(url), timeout=300) as response,
        ):
            head = response.read(1024 * 64)
            fmt = "pdf" if head.startswith(b"%PDF") else "epub" if head.startswith(b"PK") else None
            if fmt is None:
                raise FindBookError(
                    f"{candidate.source} sent a web page instead of the book; "
                    f"try it in a browser: {candidate.page}"
                )
            out.write(head)
            while chunk := response.read(1024 * 1024):
                out.write(chunk)
        output = folder / f"{safe_filename(candidate)}.{fmt}"
        os.replace(tmp_name, output)
    except OSError as exc:
        raise FindBookError(f"Download from {candidate.source} failed: {exc}") from exc
    finally:
        Path(tmp_name).unlink(missing_ok=True)
    return output


def _archive_file_url(candidate: Candidate) -> str:
    try:
        files = _json(f"https://archive.org/metadata/{candidate.ia_id}/files").get("result", [])
    except (OSError, ValueError) as exc:
        raise FindBookError(f"Internet Archive: {exc}") from exc
    wanted = (
        ("EPUB",)
        if candidate.fmt == "epub"
        else ("Text PDF", "Additional Text PDF", "Image Container PDF")
    )
    for fmt in wanted:  # best first: a PDF with the archive's OCR text
        for item in files:
            if item.get("format") == fmt and item.get("private") != "true":
                name = urllib.parse.quote(item["name"])
                return f"https://archive.org/download/{candidate.ia_id}/{name}"
    raise FindBookError(f"Internet Archive item {candidate.ia_id} has no free {candidate.fmt}")


def candidate_from_url(url: str) -> Candidate:
    """A book the user points at directly (``find-book --url``)."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise FindBookError(f"Not a web address: {url}")
    name = urllib.parse.unquote(Path(parsed.path).stem) or parsed.netloc
    return Candidate(source=parsed.netloc, title=name, page=url, url=url)


def safe_filename(candidate: Candidate) -> str:
    author = re.split(r"[;,(]", candidate.authors)[0].strip()
    name = f"{author} - {candidate.title}" if author else candidate.title
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", name)
    return re.sub(r"\s+", " ", name).strip(" .")[:120] or "book"


# --- Checking -----------------------------------------------------------------------


def check_download(path: Path, language: str | None = None) -> QualityCheck:
    """Is the file usable as it is? Suggest the pdf-worker commands to run next."""
    path = Path(path)
    if path.suffix.lower() == ".epub":
        return _check_epub(path)
    with open_pdf(path) as doc:
        pages = doc.page_count
        report = assess_text_layer(doc)
    ocr_lang = _TESSERACT.get(language or "")
    name = str(path)
    if report.mode is None:
        return QualityCheck(
            "pdf",
            f"{pages} pages; {report.reason}. Usable as it is.",
            [
                NextStep("Make an EPUB", ["convert", name, "--to", "epub"]),
                NextStep("Make a clean, reflowed A5 PDF", ["convert", name, "--to", "pdf"]),
            ],
        )
    lang = ["--lang", ocr_lang] if ocr_lang else []
    ocr_copy = str(ocr_default_output_path(path))
    return QualityCheck(
        "pdf",
        f"{pages} pages; {report.reason}: it needs OCR ({report.mode}) before converting.",
        [
            NextStep("OCR it into a searchable PDF", ["ocr", name, "--mode", report.mode, *lang]),
            NextStep(
                "Make an EPUB of the OCR'd copy (after 1)", ["convert", ocr_copy, "--to", "epub"]
            ),
            NextStep(
                "Make a clean A5 PDF of the OCR'd copy (after 1)",
                ["convert", ocr_copy, "--to", "pdf"],
            ),
        ],
    )


def _check_epub(path: Path) -> QualityCheck:
    with quiet_mupdf():
        try:
            book = pymupdf.open(path, filetype="epub")
        except (pymupdf.FileDataError, RuntimeError) as exc:
            raise FindBookError(f"{path} is not a valid EPUB: {exc}") from exc
        with book:
            pages = book.page_count
            sample = range(0, pages, max(1, pages // 20))
            chars = sum(len(book.load_page(i).get_text().strip()) for i in sample)
    steps = [NextStep("Make a PDF of it", ["ebook-to-pdf", str(path)])]
    if not pages or chars < 200 * len(sample):
        summary = (
            "An EPUB with little text (pages as pictures, or empty): try the source's PDF, "
            "or check it by hand."
        )
    else:
        summary = f"A valid EPUB, about {pages} pages of text. Usable as it is."
    return QualityCheck("epub", summary, steps)
