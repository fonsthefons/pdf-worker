import contextlib
import json

import pymupdf

from pdf_worker import missing_refs, paddle_ocr

RECT = pymupdf.Rect(50, 50, 400, 200)


def _blocks(text):
    return [
        ["text", pymupdf.Rect(RECT), text],
        ["footnote", pymupdf.Rect(50, 500, 400, 520), "⁷ Seven."],
        ["footnote", pymupdf.Rect(50, 520, 400, 540), "⁸ Eight."],
    ]


def test_missing_numbers_are_notes_without_a_reference():
    assert missing_refs.missing_numbers(_blocks("uno⁷ y causa.")) == [8]
    assert missing_refs.missing_numbers(_blocks("uno⁷ y causa⁸.")) == []


def test_restore_puts_the_reference_after_the_one_word_found():
    calls = []

    def nothing(page, region, number):
        calls.append("nothing")

    def causa(page, region, number):
        calls.append("causa")
        return "causa"

    blocks = _blocks("uno⁷ mixto y causa. Fin")
    with pymupdf.open() as doc:
        found = missing_refs.restore(
            doc.new_page(), blocks, [("a", nothing), ("b", causa), ("c", causa)]
        )
    assert found == [(8, "b")]
    assert blocks[0][2] == "uno⁷ mixto y causa⁸. Fin"
    assert calls == ["nothing", "causa"]  # stops at the first try that finds it


def test_restore_skips_a_word_found_twice_or_before_the_previous_reference():
    blocks = _blocks("causa uno⁷ causa y causa.")
    with pymupdf.open() as doc:
        assert missing_refs.restore(doc.new_page(), blocks, [("a", lambda *_: "causa")]) == []
        blocks = _blocks("causa uno⁷ mixto y causa.")
        assert missing_refs.restore(doc.new_page(), blocks, [("a", lambda *_: "causa")]) == [
            (8, "a")
        ]
    assert blocks[0][2] == "causa uno⁷ mixto y causa⁸."


def test_text_layer_finds_a_smaller_number_after_a_word():
    with pymupdf.open() as doc:
        page = doc.new_page()
        page.insert_text((60, 100), "mixto y causa", fontsize=11)
        x = 60 + pymupdf.get_text_length("mixto y causa", fontsize=11)
        page.insert_text((x, 100), "8", fontsize=7)
        page.insert_text((60, 130), "Frag. 8 y", fontsize=11)  # same size: text, not a reference
        assert missing_refs.text_layer(page, RECT, 8) == "causa"
        assert missing_refs.text_layer(page, RECT, 9) is None


def test_a_reading_shows_the_number_after_a_word():
    assert missing_refs._after_word(["mixto", "y", "causa8."], 8) == ["causa"]
    assert missing_refs._after_word(["y", "causa", "8."], 8) == ["causa"]
    assert missing_refs._after_word(["Frag.", "8"], 8) == []
    assert missing_refs._after_word(["causa8."], 9) == []


def test_paddle_crop_reads_the_reference(monkeypatch, tmp_path):
    monkeypatch.setenv("PDF_WORKER_PADDLE_CACHE", str(tmp_path))
    monkeypatch.setattr(paddle_ocr, "paddle_python", lambda: tmp_path / "python")
    starts = []

    @contextlib.contextmanager
    def server(python, progress=False):
        starts.append(1)
        yield "http://server/"

    def worker(python, pdf, pages, results, work, url, progress, dpi=None):
        assert pymupdf.open(pdf).page_count == 1 and dpi
        row = {"page": 0, "blocks": [{"label": "text", "text": "mixto y causa $ ^{8} $."}]}
        results.write_text(json.dumps(row), encoding="utf-8")

    monkeypatch.setattr(paddle_ocr, "_mlx_server", server)
    monkeypatch.setattr(paddle_ocr, "_run_worker", worker)
    clips = missing_refs.PaddleClips()
    with pymupdf.open() as doc:
        page = doc.new_page()
        assert clips(page, RECT, 8) == "causa"
        assert clips(page, RECT, 9) is None
    clips.close()
    assert starts == [1]  # one server for every crop
    assert not list(tmp_path.glob(".clips.*"))  # work files removed
