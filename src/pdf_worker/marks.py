"""A book's marks: examples of each kind of line a person marked, where sections start,
and two notes settings (docs/marks-plan.md, "The marks file").

``<book>.marks.json`` sits next to the PDF; the version before the last save is kept as
``<book>.marks.prev.json``. Coordinates are PDF points in the space of
``layout.page_lines``' boxes; pages are 1-based. Marks are the person's work: the
pipeline only reads them.
"""

import hashlib
import json
import os
import re
import shutil
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

from pdf_worker.document import open_pdf
from pdf_worker.errors import PdfWorkerError

VERSION = 1
KINDS = (
    "title",
    "heading",
    "body",
    "running-head",
    "page-number",
    "footnote",
    "note-ref",
    "endnote",
    "contents",
    "bibliography",
    "index",
    "caption",
    "ignore",
)
SECTION_KINDS = (
    "front",
    "contents",
    "introduction",
    "main",
    "notes",
    "bibliography",
    "index",
    "appendix",
    "back",
)
NOTES = ("page", "chapter", "book", "none")  # where a note's text is printed
NUMBERING = ("page", "chapter", "book")  # where note numbers start again at 1
SCOPES = ("style", "here")
LEVELS = (1, 2, 3, 4)

Point = tuple[float, float]
Box = Sequence[float]  # x0, y0, x1, y1


class MarksError(PdfWorkerError):
    """A marks file that can't be read, or that belongs to another PDF."""


@dataclass
class PdfInfo:
    name: str
    pages: int
    sha256: str


@dataclass
class Settings:
    notes: str | None = None  # None: today's rules decide
    numbering: str | None = None


@dataclass
class Section:
    page: int
    kind: str
    keep: bool = True


@dataclass
class Mark:
    id: str
    page: int
    kind: str
    shape: list[Point]
    texts: list[str] = field(default_factory=list)
    level: int | None = None  # headings only
    scope: str = "style"


@dataclass
class Marks:
    pdf: PdfInfo
    settings: Settings = field(default_factory=Settings)
    sections: list[Section] = field(default_factory=list)
    marks: list[Mark] = field(default_factory=list)
    version: int = VERSION


def default_marks_path(pdf_path: str | Path) -> Path:
    """``book.pdf`` and ``book.ocr.pdf`` -> ``book.marks.json``."""
    pdf_path = Path(pdf_path)
    stem = re.sub(r"(?:\.ocr)+$", "", pdf_path.stem, flags=re.I)
    return pdf_path.with_name(f"{stem}.marks.json")


def prev_path(path: Path) -> Path:
    return path.with_name(path.name.removesuffix(".json") + ".prev.json")


def pdf_info(pdf_path: str | Path) -> PdfInfo:
    pdf_path = Path(pdf_path)
    with open_pdf(pdf_path) as doc:
        pages = doc.page_count
    digest = hashlib.sha256()
    with pdf_path.open("rb") as data:
        for chunk in iter(lambda: data.read(1 << 20), b""):
            digest.update(chunk)
    return PdfInfo(pdf_path.name, pages, digest.hexdigest())


def new_marks(pdf_path: str | Path) -> Marks:
    return Marks(pdf_info(pdf_path))


def from_dict(data: object) -> Marks:
    """The marks in ``data`` (a marks file's JSON), checked: only the format's fields,
    kinds and values; anything else is a ``MarksError``."""
    top = _fields(data, "marks file", {"version", "pdf", "settings", "sections", "marks"})
    if top.get("version") != VERSION:
        raise MarksError(f"Unknown marks file version {top.get('version')!r} (expected {VERSION})")
    pdf = _fields(top.get("pdf"), "pdf", {"name", "pages", "sha256"})
    info = PdfInfo(
        _typed(pdf.get("name"), str, "pdf.name"),
        _typed(pdf.get("pages"), int, "pdf.pages"),
        _typed(pdf.get("sha256"), str, "pdf.sha256"),
    )
    raw = _fields(top.get("settings", {}), "settings", {"notes", "numbering"})
    settings = Settings(
        _choice(raw.get("notes"), NOTES, "settings.notes", optional=True),
        _choice(raw.get("numbering"), NUMBERING, "settings.numbering", optional=True),
    )
    sections = []
    for i, item in enumerate(_typed(top.get("sections", []), list, "sections")):
        where = f"sections[{i}]"
        raw = _fields(item, where, {"page", "kind", "keep"})
        sections.append(
            Section(
                _page(raw.get("page"), info.pages, where),
                _choice(raw.get("kind"), SECTION_KINDS, f"{where}.kind"),
                _typed(raw.get("keep", True), bool, f"{where}.keep"),
            )
        )
    marks = []
    for i, item in enumerate(_typed(top.get("marks", []), list, "marks")):
        where = f"marks[{i}]"
        raw = _fields(item, where, {"id", "page", "kind", "level", "scope", "shape", "texts"})
        kind = _choice(raw.get("kind"), KINDS, f"{where}.kind")
        level = raw.get("level")
        if kind == "heading":
            level = _choice(level, LEVELS, f"{where}.level")
        elif level is not None:
            raise MarksError(f"{where}: only a heading has a level")
        shape = _typed(raw.get("shape"), list, f"{where}.shape")
        if len(shape) < 3 or not all(
            isinstance(p, list)
            and len(p) == 2
            and all(isinstance(c, (int, float)) and not isinstance(c, bool) for c in p)
            for p in shape
        ):
            raise MarksError(f"{where}.shape: 3 or more [x, y] corners")
        texts = _typed(raw.get("texts", []), list, f"{where}.texts")
        if not all(isinstance(t, str) for t in texts):
            raise MarksError(f"{where}.texts: a list of strings")
        marks.append(
            Mark(
                _typed(raw.get("id"), str, f"{where}.id"),
                _page(raw.get("page"), info.pages, where),
                kind,
                [(float(x), float(y)) for x, y in shape],
                texts,
                level,
                _choice(raw.get("scope", "style"), SCOPES, f"{where}.scope"),
            )
        )
    ids = [m.id for m in marks]
    if len(set(ids)) != len(ids):
        raise MarksError("Two marks share an id")
    return Marks(info, settings, sections, marks)


def to_dict(marks: Marks) -> dict:
    data = asdict(marks)
    data["settings"] = {k: v for k, v in data["settings"].items() if v is not None}
    for mark in data["marks"]:
        mark["shape"] = [list(p) for p in mark["shape"]]
        if mark["level"] is None:
            del mark["level"]
    return {k: data[k] for k in ("version", "pdf", "settings", "sections", "marks")}


def check_pdf(marks: Marks, info: PdfInfo) -> None:
    """A ``MarksError`` when ``marks`` were made on another PDF than ``info``'s."""
    if marks.pdf.pages != info.pages:
        raise MarksError(
            f"The marks are for a PDF of {marks.pdf.pages} pages; {info.name} has {info.pages}"
        )
    if marks.pdf.sha256 != info.sha256:
        raise MarksError(f"The marks were made on another file than {info.name} (sha256 differs)")


def load(path: str | Path, pdf_path: str | Path | None = None) -> Marks:
    """The marks file at ``path``, checked (``from_dict``) and, with ``pdf_path``, made
    on that PDF (same page count and hash)."""
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise MarksError(f"No marks file {path}") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MarksError(f"Can't read the marks file {path}: {exc}") from exc
    try:
        marks = from_dict(data)
    except MarksError as exc:
        raise MarksError(f"{path}: {exc}") from exc
    if pdf_path is not None:
        check_pdf(marks, pdf_info(pdf_path))
    return marks


def save(path: str | Path, marks: Marks) -> None:
    """Write ``marks`` to ``path`` atomically; the file it replaces becomes
    ``<book>.marks.prev.json``."""
    path = Path(path)
    text = json.dumps(to_dict(marks), ensure_ascii=False, indent=1) + "\n"
    if path.exists():
        _replace(prev_path(path), lambda tmp: shutil.copyfile(path, tmp))
    _replace(path, lambda tmp: tmp.write_text(text, encoding="utf-8"))


def _replace(path: Path, write) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        write(tmp)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def inside(point: Point, shape: Sequence[Point]) -> bool:
    """Whether ``point`` lies inside the polygon ``shape`` (even-odd rule)."""
    x, y = point
    found = False
    for (x0, y0), (x1, y1) in zip(shape, [*shape[1:], shape[0]], strict=True):
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            found = not found
    return found


def _middle(box: Box) -> Point:
    return ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)


def lines_in(shape: Sequence[Point], lines: Iterable) -> list:
    """The lines (anything with a ``bbox``) whose box's middle lies inside ``shape``."""
    return [line for line in lines if inside(_middle(line.bbox), shape)]


def words_in(shape: Sequence[Point], words: Iterable[Sequence]) -> list:
    """The words (``(x0, y0, x1, y1, text, ...)``, as ``Page.get_text("words")``) whose
    box's middle lies inside ``shape``."""
    return [word for word in words if inside(_middle(word[:4]), shape)]


def _fields(value: object, where: str, allowed: set[str]) -> dict:
    if not isinstance(value, dict):
        raise MarksError(f"{where}: expected an object")
    unknown = set(value) - allowed
    if unknown:
        raise MarksError(f"{where}: unknown field(s) {', '.join(sorted(unknown))}")
    return value


def _typed(value: object, kind: type, where: str):
    # bool is an int in Python: a page of True is not a page.
    if not isinstance(value, kind) or (kind is int and isinstance(value, bool)):
        raise MarksError(f"{where}: expected {kind.__name__}, got {value!r}")
    return value


def _choice(value: object, choices: Sequence, where: str, optional: bool = False):
    if value is None and optional:
        return None
    if isinstance(value, bool) or value not in choices:
        raise MarksError(f"{where}: {value!r} is not one of {', '.join(map(str, choices))}")
    return value


def _page(value: object, pages: int, where: str) -> int:
    page = _typed(value, int, f"{where}.page")
    if not 1 <= page <= pages:
        raise MarksError(f"{where}.page: {page} is not a page of the PDF (1-{pages})")
    return page
