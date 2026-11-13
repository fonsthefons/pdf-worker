import pymupdf
import pytest
from test_find_book import make_epub

from pdf_worker import highlights
from pdf_worker.highlights import highlight_book
from pdf_worker.kindle_positions import Highlight


@pytest.fixture
def kindle(monkeypatch):
    """Make highlight_book read these highlights instead of a Kindle's database."""

    def _use(*items):
        found = [
            Highlight(text, 100 * i, 100 * i + 50, note) for i, (text, note) in enumerate(items)
        ]
        monkeypatch.setattr(highlights, "read_kindle_db", lambda db, azw3: found)

    return _use


def run(pdf, **kwargs):
    return highlight_book(pdf, "kindle.db", "book.azw3", **kwargs)


def marked(pdf):
    """(page, words under the annotation, its content) for every annotation."""
    out = []
    with pymupdf.open(pdf) as doc:
        for page in doc:
            words = page.get_text("words")
            for annot in page.annots():
                assert annot.type[0] == pymupdf.PDF_ANNOT_HIGHLIGHT
                points = annot.vertices
                rects = [pymupdf.Quad(*points[i : i + 4]).rect for i in range(0, len(points), 4)]
                centers = [
                    (w[4], pymupdf.Point((w[0] + w[2]) / 2, (w[1] + w[3]) / 2)) for w in words
                ]
                under = [word for word, c in centers if any(c in r for r in rects)]
                out.append((page.number, " ".join(under), annot.info["content"]))
    return out


def test_cli_writes_the_highlighted_pdf(make_pdf, kindle, tmp_path, capsys):
    from pdf_worker.cli import main

    pdf = make_pdf(["Words before alpha beta, gamma delta and after."])
    kindle(("alpha beta gamma delta", None), ("not in the book", None))
    (tmp_path / "k.db").write_bytes(b"")
    (tmp_path / "b.azw3").write_bytes(b"")

    code = main(
        [
            "highlights",
            str(pdf),
            "--kindle-db",
            str(tmp_path / "k.db"),
            "--azw3",
            str(tmp_path / "b.azw3"),
        ]
    )

    assert code == 0
    assert pdf.with_name("sample.highlighted.pdf").exists()
    out = capsys.readouterr().out
    assert "1 highlight(s)" in out and "not found: not in the book" in out


def test_cli_missing_file_is_a_clean_error(make_pdf, tmp_path):
    from pdf_worker.cli import main

    pdf = make_pdf(["x"])
    argv = ["highlights", str(pdf), "--kindle-db", str(tmp_path / "no.db"), "--azw3", "no.azw3"]
    assert main(argv) == 1


def test_exact_match(make_pdf, kindle):
    pdf = make_pdf(["Words before alpha beta, gamma delta and after."])
    kindle(("alpha beta gamma delta", None))

    report = run(pdf)

    assert report.output_path == pdf.with_name("sample.highlighted.pdf")
    assert (report.highlighted, report.unmatched) == (1, [])
    assert marked(report.output_path) == [(0, "alpha beta, gamma delta", "")]


def test_match_across_a_page_break(make_pdf, kindle):
    pdf = make_pdf(["one two three alpha beta", "gamma delta four five"])
    kindle(("alpha beta gamma delta", None))

    report = run(pdf)

    assert marked(report.output_path) == [(0, "alpha beta", ""), (1, "gamma delta", "")]


def test_word_hyphenated_over_two_lines(make_pdf, kindle):
    pdf = make_pdf(["the filo-\nsophy of it"])
    kindle(("the filosophy of", None))

    report = run(pdf)

    assert marked(report.output_path) == [(0, "the filo- sophy of", "")]


def test_repeated_phrase_taken_in_kindle_order(make_pdf, kindle):
    pdf = make_pdf(["delta epsilon here\nalpha beta gamma\ndelta epsilon there"])
    kindle(("alpha beta gamma", None), ("delta epsilon", None))

    report = run(pdf)

    assert marked(report.output_path) == [(0, "alpha beta gamma", ""), (0, "delta epsilon", "")]
    with pymupdf.open(report.output_path) as doc:
        page = doc[0]
        first, second = [annot.rect for annot in page.annots()]
    assert second.y0 > first.y0  # below "alpha": the third line, not the first


def test_fuzzy_match_over_a_note_number(make_pdf, kindle):
    pdf = make_pdf(["so one two three four five 17 six seven eight nine ten end"])
    kindle(("one two three four five six seven eight nine ten", None))

    report = run(pdf)

    assert report.unmatched == []
    assert marked(report.output_path) == [
        (0, "one two three four five 17 six seven eight nine ten", "")
    ]


def test_highlight_contained_in_another_is_dropped(make_pdf, kindle):
    pdf = make_pdf(["beta gamma first\nthen alpha beta gamma"])
    kindle(("alpha beta gamma", None), ("beta gamma", "inner note"))

    report = run(pdf)

    assert marked(report.output_path) == [(0, "alpha beta gamma", "")]
    assert (report.highlighted, report.notes_unattached) == (1, 1)


def test_unmatched_reported(make_pdf, kindle):
    pdf = make_pdf(["alpha beta gamma"])
    kindle(("alpha beta", None), ("not in this book", "lost note"))

    report = run(pdf)

    assert report.unmatched == ["not in this book"]
    assert (report.highlighted, report.notes_attached, report.notes_unattached) == (1, 0, 1)


def test_note_is_the_first_annotations_content(make_pdf, kindle):
    pdf = make_pdf(["one two alpha beta", "gamma delta three"])
    kindle(("alpha beta gamma delta", "my note"))

    report = run(pdf, output_path=pdf.parent / "out" / "marked.pdf")

    assert report.notes_attached == 1
    assert marked(pdf.parent / "out" / "marked.pdf") == [
        (0, "alpha beta", "my note"),
        (1, "gamma delta", ""),
    ]


def test_output_must_not_be_the_input(make_pdf, kindle):
    pdf = make_pdf(["alpha"])
    kindle(("alpha", None))

    with pytest.raises(highlights.PdfWorkerError, match="overwrite"):
        run(pdf, output_path=pdf)


def test_epub_input_is_laid_out_and_left_alone(tmp_path, kindle):
    epub = make_epub(tmp_path / "book.epub", "It was the best of times, it was the worst of times.")
    before = epub.read_bytes()
    kindle(("the worst of times", None))

    report = run(epub)

    assert report.title == "Test Book"
    assert marked(report.output_path) == [(0, "the worst of times.", "")]
    assert epub.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["book.epub", "book.highlighted.pdf"]
