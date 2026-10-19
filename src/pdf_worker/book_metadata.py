"""The book's title, author, translator, publisher and year, found in the book itself.

A PDF's own metadata is often wrong: Word puts the typist's account name in the author
field ("MANUEL"). Sources, best first: the PDF's metadata when it looks plausible; the
front pages (title page: the biggest type, "Por Joseph Ratzinger"; copyright page);
an ISBN printed there, looked up in Open Library (skipped when offline; its records
have typos, "Frederik Compleston", so the book's own pages come first); the file name.
"""

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from datetime import date
from difflib import get_close_matches
from pathlib import Path

import pymupdf

from pdf_worker import find_book  # a module: find_book imports convert, which imports this
from pdf_worker.cover import find_translator, name_case
from pdf_worker.output import Metadata

PAGES = 6  # the front matter searched: title page, copyright page
_BIG = 1.25  # a title page has type this much bigger than the body's
_LOOKUP_TIMEOUT = 10  # seconds per Open Library request

# Producer junk that PDF tools put into the title field.
_OCR_SUFFIX_RE = re.compile(r"(?:\.ocr)+$", re.IGNORECASE)
_JUNK_TITLE_RE = re.compile(
    r"^(microsoft word|untitled|document\d*$)|\.(docx?|pdf|indd|tiff?|jpe?g|png)$"
    # A bare file name such as "201-635.job" or "book_final.qxd".
    r"|^[\w\-]+\.[a-z]{2,4}$",
    re.I,
)
# Computer account names that Word and Acrobat put into the author field.
_ACCOUNT_RE = re.compile(
    r"\d|@|_|\b(user|usuario|admin\w*|owner|propietario|microsoft|adobe|windows|pc|hp|dell"
    r"|lenovo|acer|asus)\b",
    re.I,
)
_LIFE_DATES_RE = re.compile(
    r",?\s*\(?\d{3,4}\??-(?:\d{3,4})?\??\)?\s*$"
)  # "Gibbon, Edward, 1737-1794"
_ORDER_RE = re.compile(r",\s*(?:[A-Za-z]{1,2}\.\s?){2,}$")  # "COPLESTON, S.I.", ", Ph.D."
_BYLINE_RE = re.compile(r"^(?:(?:por|by|von|par|prof|dr|lic)\.?\s+)+(.+)$", re.I)
_PARTICLES = {"de", "del", "la", "las", "los", "y", "e", "da", "di", "du", "le", "van", "von"}
_TITLE_SMALL_WORDS = {"a", "an", "the", "of", "and", "or", "in", "on", "to", "for", "by", "at"}
_NUMERAL_RE = re.compile(r"^(?=[IVX])X{0,3}(?:IX|IV|V?I{0,3})$")  # "VI", not "DI" or "MI"
_ISBN_RE = re.compile(r"ISBN(?:-1[03])?[^0-9]{0,6}([0-9][0-9 -]{8,16}[0-9Xx])")
_RIGHTS_RE = re.compile(
    r"©|\(c\)|copyright|derechos|rights|edici[oó]n|edition|édition|auflage|published|"
    r"publicad|impres|printed|dep[oó]sito legal",
    re.I,
)
_YEAR_RE = re.compile(r"\b(1[5-9]\d\d|20\d\d)\b")
_PUBLISHER_RE = re.compile(
    r"\b(?:editorial|editores|ediciones|edizioni|[ée]ditions|verlag|press|publishing|"
    r"publishers|books)\b",
    re.I,
)
_LETTERSPACED_RE = re.compile(r"\b(?:\w ){2,}\w\b")  # "A B A D A EDITORES"
_PUBLISHER_JUNK_RE = re.compile(
    r"^[©\s]*(?:(?:published|distributed) by\s+)?|,?\s*\b(?:s\.\s?[al]|ltd|inc|co|gmbh|llc)\b\.?"
    r"|[\s,.]+$",
    re.I,
)


@dataclass(frozen=True)
class _Line:
    text: str
    size: float


def find_metadata(
    doc: pymupdf.Document,
    texts: list[str],
    info: dict,
    pdf_path: str | Path,
    language: str,
    title: str | None = None,
    author: str | None = None,
) -> tuple[Metadata, dict[str, str]]:
    """The book's metadata and, per field, where it was found ("title page").

    ``texts`` are the text blocks of the first pages; ``info`` and ``pdf_path`` the
    metadata and path of the original PDF (not of an OCR'd copy); ``title`` and
    ``author``, when given, win.
    """
    pages, body = _front_lines(doc)
    title_page = next((p for p in pages if any(ln.size >= body * _BIG for ln in p)), [])
    runs = _runs(title_page, body)
    file_title = title_from_file(pdf_path)
    meta_title = _recase(_clean_title(info.get("title", "")), language)
    meta_author = _person(info.get("author") or "")
    if not _plausible_author(meta_author, title_page):
        meta_author = ""
    isbn = find_isbn(texts)
    page_words = _words(" ".join(ln.text for ln in title_page))
    edition = _edition(isbn, _words(file_title) | _words(meta_title) | page_words)
    names = _words(meta_author) | _words(edition.get("author", ""))
    byline = _byline(title_page, runs, names, _words(file_title))
    isbn_source = f"ISBN {isbn}"
    options = {
        "title": [
            (title, "given"),
            (meta_title, "PDF metadata"),
            (_recase(_page_title(title_page, runs, byline, file_title), language), "title page"),
            (edition.get("title"), isbn_source),
            (file_title, "file name"),
        ],
        "author": [
            (author, "given"),
            (meta_author, "PDF metadata"),
            (_person(byline), "title page"),
            (_person(edition.get("author", "")), isbn_source),
        ],
        "translator": [(find_translator(texts), "title page")],
        "publisher": [
            (_publisher(line for page in pages for line in page), "front pages"),
            (edition.get("publisher"), isbn_source),
        ],
        "year": [(_year(texts), "copyright page"), (edition.get("year"), isbn_source)],
    }
    chosen = {
        name: next(((v.strip(), s) for v, s in values if v and v.strip()), ("", ""))
        for name, values in options.items()
    }
    meta = Metadata(language=language, **{name: v for name, (v, _) in chosen.items()})
    return meta, {name: s for name, (v, s) in chosen.items() if v}


def title_from_file(pdf_path: str | Path) -> str:
    """The file name without our own suffixes ("My_Book.ocr.pdf" -> "My Book")."""
    stem = _OCR_SUFFIX_RE.sub("", Path(pdf_path).stem)
    return stem.replace("_", " ").strip() or stem


def find_isbn(texts: list[str]) -> str:
    """The first valid ISBN printed in ``texts``, digits only; "" if none."""
    for text in texts:
        for match in _ISBN_RE.finditer(text):
            digits = re.sub(r"[^0-9X]", "", match.group(1).upper())
            # The match may run on into a following number ("ISBN 84-206-1234-5 1990").
            for isbn in (digits[:13], digits[:10]):
                if _valid_isbn(isbn):
                    return isbn
    return ""


def _valid_isbn(isbn: str) -> bool:
    if len(isbn) == 10 and "X" not in isbn[:-1]:
        values = [10 if c == "X" else int(c) for c in isbn]
        return sum((10 - i) * v for i, v in enumerate(values)) % 11 == 0
    if len(isbn) == 13 and isbn.isdigit():
        return sum(int(c) * (3 if i % 2 else 1) for i, c in enumerate(isbn)) % 10 == 0
    return False


def _edition(isbn: str, book_words: set[str]) -> dict[str, str]:
    """Open Library's record of the ISBN, if its title shares a word with the book's.

    A copyright page may print the ISBN of another book or volume, hence the check."""
    if not isbn:
        return {}
    try:
        edition = find_book.isbn_edition(isbn, timeout=_LOOKUP_TIMEOUT)
    except (OSError, ValueError):
        return {}  # offline or Open Library down: the book's own pages will do
    return edition if _words(edition.get("title", "")) & book_words else {}


def _front_lines(doc: pymupdf.Document) -> tuple[list[list[_Line]], float]:
    """The lines of the first pages, without running heads and watermarks; body size."""
    pages = []
    for page_no in range(min(PAGES, doc.page_count)):
        lines = []
        for block in doc.load_page(page_no).get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                text = " ".join("".join(s["text"] for s in line["spans"]).split())
                if text:
                    lines.append(_Line(text, round(max(s["size"] for s in line["spans"]), 1)))
        pages.append(lines)
    sizes = Counter()
    for line in (line for lines in pages for line in lines):
        sizes[line.size] += len(line.text)
    if not sizes:
        return [], 0.0
    # On most pages: "www.lectulandia.com - Página 3", "Page Proof Pending Publication".
    # Not "PLATÓN" "TIMEO", repeated on the cover, half-title and title page.
    seen = Counter(key for lines in pages for key in {_key(ln.text) for ln in lines})
    pages = [[ln for ln in lines if seen[_key(ln.text)] < 4] for lines in pages]
    return pages, sizes.most_common(1)[0][0]


def _key(text: str) -> str:
    return re.sub(r"\d+", "", text.casefold())


def _runs(lines: list[_Line], body: float) -> list[_Line]:
    """Lines bigger than the body joined while their size holds ("THE 9/11" "REPORT")."""
    runs: list[_Line] = []
    joinable = False
    for line in lines:
        if line.size <= body:
            joinable = False
            continue
        if joinable and abs(runs[-1].size - line.size) < 0.6:
            runs[-1] = _Line(f"{runs[-1].text} {line.text}", runs[-1].size)
        else:
            runs.append(line)
        joinable = True
    return runs


def _byline(lines: list[_Line], runs: list[_Line], names: set[str], file_words: set[str]) -> str:
    """The author's name as printed on the title page, or "".

    A name after "Por", "By" or "Prof. Dr."; else, on a sparse title page, a big
    name-like line above the title whose words all appear (near enough) in ``names``
    (from other sources), or in the file name along with the title's: "Immanuel Kant"
    above "Crítica de la razón pura" in "Critica de la Razon Pura - Immanuel Kant.pdf".
    Without these checks any short heading ("THE SUPREME COURT"; "LINGVA LATINA" in
    "Familia Romana Lingua Latina.pdf") could pass for a name."""
    for line in lines[:15]:
        match = _BYLINE_RE.match(line.text)
        if match and _name_like(match.group(1)):
            return match.group(1)
    if not _sparse(lines):
        return ""
    for i, run in enumerate(runs):
        others = [k for k in range(len(runs)) if k != i]
        title = max(others, key=lambda k: runs[k].size, default=-1)
        words = _words(run.text)
        if title <= i or not words or not _name_like(run.text):
            continue
        in_file_name = _known(words, file_words) and _known(_words(runs[title].text), file_words)
        if _known(words, names) or in_file_name:
            return run.text
    return ""


def _known(words: set[str], hints: set[str]) -> bool:
    """Every word in ``hints``, give or take a typo ("Bordieu", "Compleston")."""
    return bool(hints) and all(get_close_matches(w, list(hints), n=1, cutoff=0.8) for w in words)


def _sparse(lines: list[_Line]) -> bool:
    """Few lines and hardly any running text: a title page, not a chapter's first page."""
    return len(lines) <= 12 and sum(len(ln.text) > 50 for ln in lines) <= 2


def _page_title(lines: list[_Line], runs: list[_Line], byline: str, file_title: str) -> str:
    """The biggest type on the title page that isn't the author's name, or "".

    Trusted on a sparse page (a real title page), or when the file name agrees; else a
    first page such as a report's cover ("OFFICIAL REPORTS") would win over the name."""
    candidates = [run for run in runs if run.text != byline]
    if not candidates:
        return ""
    title = max(candidates, key=lambda run: run.size).text
    return title if _sparse(lines) or _words(title) & _words(file_title) else ""


def _name_like(text: str) -> bool:
    words = text.split()
    return (
        0 < len(words) <= 5
        and len(text) <= 50
        and not re.search(r"\d", text)
        and all(w[0].isupper() or w.lower() in _PARTICLES for w in words)
    )


def _plausible_author(author: str, title_page: list[_Line]) -> bool:
    if not author or _ACCOUNT_RE.search(author):
        return False
    if len(author.split()) > 1:
        return True
    # One word ("MANUEL") is an account name, unless the title page prints it ("Platón").
    return any(_fold(ln.text) == _fold(author) for ln in title_page)


def _person(name: str) -> str:
    """ "Gibbon, Edward, 1737-1794" -> "Edward Gibbon"; "JOSEPH RATZINGER" -> "Joseph Ratzinger"."""
    name = _LIFE_DATES_RE.sub("", " ".join(name.split()))
    name = _ORDER_RE.sub("", name).strip(" ,.")
    last, comma, first = name.partition(", ")
    if comma and _name_like(first) and _name_like(last):
        name = f"{first} {last}"
    return name_case(name)


def _clean_title(title: str) -> str:
    title = (title or "").strip()
    return "" if not title or _JUNK_TITLE_RE.search(title) else title


def _recase(title: str, language: str) -> str:
    """An all-capitals title in the language's usual case: "Introducción al cristianismo",
    "The 9/11 Commission Report"."""
    if not title.isupper():
        return title
    words = []
    for i, word in enumerate(title.lower().split()):
        if _NUMERAL_RE.match(word.upper()):
            word = word.upper()
        elif i == 0 or (language in ("en", "la") and word not in _TITLE_SMALL_WORDS):
            word = word[:1].upper() + word[1:]
        words.append(word)
    return " ".join(words)


def _publisher(lines) -> str:
    """A short front-page line naming a publisher: "EDITORIAL ARIEL, S.A." -> "Editorial Ariel"."""
    for line in lines:
        text = _LETTERSPACED_RE.sub(lambda m: m.group().replace(" ", ""), line.text)
        text = _PUBLISHER_JUNK_RE.sub("", text)
        if re.search(r"http|www\.|\.com|@", text) or not text[:1].isupper():
            continue  # "at http://books.google.com/"
        if _PUBLISHER_RE.search(text) and len(text.split()) <= 5:
            return name_case(text)
    return ""


def _year(texts: list[str]) -> str:
    """The latest year on a short copyright or edition line ("© 1984, 2010" -> "2010")."""
    years = []
    for line in (line for text in texts for line in text.splitlines()):
        if len(line) <= 70 and _RIGHTS_RE.search(line):
            line = re.sub(r"(?<=\d) (?=\d)", "", line)  # letterspaced "2 0 10"
            years += [int(y) for y in _YEAR_RE.findall(line)]
    years = [y for y in years if y <= date.today().year]
    return str(max(years)) if years else ""


def _fold(text: str) -> str:
    """Lowercase without accents: "Platón" -> "platon"."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"\w+", _fold(text)) if len(w) >= 4}
