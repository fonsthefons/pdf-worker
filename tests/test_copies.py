import pymupdf

from pdf_worker.copies import rank_copies

TEXT = "Chapter One\n\nIt was a quiet morning in the village, and nobody was awake yet."


def test_a_copy_needing_no_ocr_beats_one_without_text(make_pdf):
    good = make_pdf([TEXT] * 3, name="good.pdf")
    empty = make_pdf(["", "", ""], name="empty.pdf")

    ranked = rank_copies([empty, good])

    assert [c.path.name for c in ranked] == ["good.pdf", "empty.pdf"]
    assert ranked[0].ocr == "none"
    assert "3 pages, OCR: none" in ranked[0].summary()


def test_single_pages_beat_two_page_spreads(make_pdf, tmp_path):
    single = make_pdf([TEXT] * 3, name="single.pdf")
    spread = tmp_path / "spread.pdf"
    with pymupdf.open() as doc:
        for _ in range(3):
            doc.new_page(width=842, height=595).insert_text((72, 72), TEXT)
        doc.save(spread)

    ranked = rank_copies([spread, single])

    assert [(c.path.name, c.spreads) for c in ranked] == [
        ("single.pdf", False),
        ("spread.pdf", True),
    ]
