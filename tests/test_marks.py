import json
import math
import threading
import urllib.error
import urllib.request

import pymupdf
import pytest

from pdf_worker import marking, marks
from pdf_worker.layout import page_lines
from pdf_worker.marks import Mark, MarksError, Section


def _sample(pdf) -> dict:
    info = marks.pdf_info(pdf)
    return {
        "version": 1,
        "pdf": {"name": info.name, "pages": info.pages, "sha256": info.sha256},
        "settings": {"notes": "page", "numbering": "chapter"},
        "sections": [{"page": 1, "kind": "main", "keep": True}],
        "marks": [
            {
                "id": "m1",
                "page": 2,
                "kind": "heading",
                "level": 1,
                "scope": "style",
                "shape": [[70, 60], [300, 60], [300, 80], [70, 80]],
                "texts": ["CAPÍTULO I"],
            }
        ],
    }


def test_default_marks_path_drops_ocr(tmp_path):
    assert marks.default_marks_path(tmp_path / "book.pdf") == tmp_path / "book.marks.json"
    assert marks.default_marks_path(tmp_path / "book.ocr.pdf") == tmp_path / "book.marks.json"


def test_save_and_load_round_trip_keeping_the_previous_version(make_pdf, tmp_path):
    pdf = make_pdf(["one", "CAPÍTULO I"])
    path = marks.default_marks_path(pdf)
    first = marks.from_dict(_sample(pdf))
    marks.save(path, first)
    assert not marks.prev_path(path).exists()
    assert marks.load(path, pdf) == first
    assert marks.to_dict(first) == _sample(pdf)

    second = marks.from_dict(_sample(pdf))
    second.sections.append(Section(2, "notes", keep=False))
    second.marks.append(Mark("m2", 2, "footnote", [(0, 0), (10, 0), (10, 10)], ["1 Text"]))
    marks.save(path, second)
    assert marks.load(path, pdf) == second
    assert marks.load(marks.prev_path(path), pdf) == first
    assert marks.prev_path(path).name == "sample.marks.prev.json"
    assert sorted(p.name for p in tmp_path.iterdir() if p.name.startswith(".")) == []


@pytest.mark.parametrize(
    "change, message",
    [
        (lambda d: d.update(version=2), "version"),
        (lambda d: d["marks"][0].update(kind="headline"), "kind"),
        (lambda d: d["marks"][0].update(level=5), "level"),
        (lambda d: d["marks"][0].update(colour="red"), "unknown field"),
        (lambda d: d["marks"][0].update(shape=[[0, 0], [1, 1]]), "corners"),
        (lambda d: d["marks"][0].update(page=3), "not a page"),
        (lambda d: d["sections"][0].update(kind="preface"), "kind"),
        (lambda d: d["settings"].update(notes="margin"), "settings.notes"),
        (lambda d: d["marks"].append(dict(d["marks"][0])), "share an id"),
    ],
)
def test_load_refuses_what_is_not_in_the_format(make_pdf, change, message):
    pdf = make_pdf(["one", "two"])
    data = _sample(pdf)
    change(data)
    path = marks.default_marks_path(pdf)
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(MarksError, match=message):
        marks.load(path)


def test_load_refuses_marks_made_on_another_pdf(make_pdf):
    pdf = make_pdf(["one", "two"])
    path = marks.default_marks_path(pdf)
    marks.save(path, marks.from_dict(_sample(pdf)))
    longer = make_pdf(["one", "two", "three"], name="longer.pdf")
    with pytest.raises(MarksError, match="3"):
        marks.load(path, longer)
    other = make_pdf(["one", "deux"], name="other.pdf")
    with pytest.raises(MarksError, match="sha256"):
        marks.load(path, other)


def test_load_of_a_missing_or_broken_file_is_a_marks_error(tmp_path):
    with pytest.raises(MarksError, match="No marks file"):
        marks.load(tmp_path / "none.marks.json")
    broken = tmp_path / "broken.marks.json"
    broken.write_text("{", encoding="utf-8")
    with pytest.raises(MarksError, match="Can't read"):
        marks.load(broken)


def _slanted_page(path, angle: float) -> None:
    """Three slanted lines 14 pt apart, as on a skewed scan."""
    doc = pymupdf.open()
    page = doc.new_page()
    turn = pymupdf.Matrix(-angle)  # PDF y grows down on the page: rise to the right
    for k, text in enumerate(["above the line", "the middle line", "below the line"]):
        dy = 14 * k
        start = pymupdf.Point(100 - math.sin(math.radians(angle)) * dy, 300 + dy)
        page.insert_text(start, text * 3, fontsize=11, morph=(start, turn))
    doc.save(path)
    doc.close()


def test_a_skewed_shape_takes_a_slanted_line_and_leaves_its_neighbours(tmp_path):
    angle = 8.0
    _slanted_page(tmp_path / "skewed.pdf", angle)
    with pymupdf.open(tmp_path / "skewed.pdf") as doc:
        lines = page_lines(doc[0])
    assert len(lines) == 3
    middle = lines[1]
    # A thin shape along the middle line, turned by the same angle.
    cx, cy = (middle.bbox[0] + middle.bbox[2]) / 2, (middle.bbox[1] + middle.bbox[3]) / 2
    a = math.radians(angle)
    along, across = (math.cos(a), -math.sin(a)), (math.sin(a), math.cos(a))
    shape = [
        (
            cx + sx * 200 * along[0] + sy * 5 * across[0],
            cy + sx * 200 * along[1] + sy * 5 * across[1],
        )
        for sx, sy in [(-1, -1), (1, -1), (1, 1), (-1, 1)]
    ]
    assert [line.text for line in marks.lines_in(shape, lines)] == [middle.text]
    # The upright box around the middle line would take its neighbours too.
    x0, y0, x1, y1 = middle.bbox
    upright = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    assert len(marks.lines_in(upright, lines)) == 3


def _call(url, data=None):
    body = json.dumps(data).encode() if data is not None else None
    try:
        with urllib.request.urlopen(urllib.request.Request(url, body), timeout=10) as reply:
            return reply.status, reply.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def test_the_marking_page_serves_a_page_and_saves_only_valid_marks(make_pdf, monkeypatch, tmp_path):
    monkeypatch.setenv("PDF_WORKER_PADDLE_CACHE", str(tmp_path / "paddle"))
    pdf = make_pdf(["one line", "CAPÍTULO I"])
    path = marks.default_marks_path(pdf)
    with pymupdf.open(pdf) as doc:
        book = marking.Book(doc, pdf, path)
        server = marking.serve(book)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            status, body = _call(f"{url}/page/2.json")
            view = json.loads(body)
            assert status == 200 and [line["text"] for line in view["lines"]] == ["CAPÍTULO I"]
            assert view["blocks"] and view["words"][0][4] == "CAPÍTULO"
            assert _call(f"{url}/page/2.png")[1][:4] == b"\x89PNG"
            assert _call(f"{url}/page/3.json")[0] == 404

            data = _sample(pdf)
            box = view["lines"][0]["bbox"]
            data["marks"][0]["shape"] = [[box[0], box[1]], [box[2], box[1]], [box[2], box[3]]]
            data["marks"][0]["shape"].append([box[0], box[3]])
            data["marks"][0]["texts"] = ["CAPÍTULO I"]
            status, body = _call(f"{url}/marks.json", data)
            assert status == 200 and json.loads(body)["stale"] == []
            assert marks.load(path, pdf) == marks.from_dict(data)

            data["marks"][0]["texts"] = ["Chapter One"]
            assert json.loads(_call(f"{url}/marks.json", data)[1])["stale"][0]["id"] == "m1"

            data["marks"][0]["kind"] = "headline"
            status, body = _call(f"{url}/marks.json", data)
            assert status == 400 and "kind" in json.loads(body)["error"]
            assert marks.load(path).marks[0].kind == "heading"
            assert json.loads(_call(f"{url}/marks.json")[1])["marks"][0]["kind"] == "heading"
        finally:
            server.shutdown()
            server.server_close()


def test_a_scan_shows_the_lines_of_its_paddle_rows():
    doc = pymupdf.open()
    page = doc.new_page(width=300, height=400)
    row = {
        "width": 600,
        "height": 800,
        "blocks": [{"label": "text", "bbox": [100, 100, 500, 140], "text": "uno dos\ntres"}],
    }
    lines, words, blocks = marking._paddle_view(page, row)
    assert [(line.text, line.bbox) for line in lines] == [
        ("uno dos", (50, 50, 250, 60)),
        ("tres", (50, 60, 250, 70)),
    ]
    assert [w[4] for w in words] == ["uno", "dos", "tres"]
    assert words[1][0] > words[0][2] and blocks[0]["label"] == "text"


def test_words_in_takes_words_by_their_middle():
    words = [(10, 10, 20, 20, "a"), (30, 10, 40, 20, "b"), (50, 10, 60, 20, "c")]
    shape = [(25, 0), (45, 0), (45, 30), (25, 30)]
    assert [w[4] for w in marks.words_in(shape, words)] == ["b"]
    assert marks.inside((10, 10), [(0, 0), (30, 0), (0, 30)])
    assert not marks.inside((25, 25), [(0, 0), (30, 0), (0, 30)])
