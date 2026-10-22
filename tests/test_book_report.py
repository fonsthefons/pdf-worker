from pdf_worker.book_report import BookReport, count_rows, markdown
from pdf_worker.fixes import Fix


def report(**kwargs) -> BookReport:
    defaults = dict(name="b.pdf", how="test", ocr=False, pages=100, book_words=10_000)
    return BookReport(**(defaults | kwargs))


def test_rows_are_sorted_into_found_possible_left_out_and_decided():
    r = report(ocr=True)
    count_rows(
        r,
        [
            Fix("1", "3", "spelling", "teologia", type="accent"),
            Fix("2", "4", "chars", "Кant"),
            Fix("3", "5", "margin-est", "23c"),
            Fix("4", "6", "greek-dropped", "λόγος"),
            Fix("5", "7", "spelling", "fue", action="ignore"),
            Fix("6", "8", "spelling", "gone", status="stale"),
            Fix("7", "9", "spelling", "x", action="replace", value="y", status="stale"),
            Fix("8", "9", "spelling", "a b", action="replace", value="ab", type="auto: split"),
        ],
    )
    assert r.corrected == {"words split in two, joined": 1}  # not a decision
    assert r.found == {
        "odd characters (look-alike letters, stray symbols)": 1,
        "review fixes that no longer apply": 1,
    }
    assert r.possible == {
        "spelling: accent probably lost": 1,
        "margin references placed by estimate": 1,
    }
    assert sum(r.left_out.values()) == 1
    assert r.decided == 1
    assert r.open_rows == 4
    assert r.grade == "B"  # OCR'd with a spelling row open
    assert "**Grade B** (draft)" in markdown(r, "draft")


def test_grade_follows_words_kept_empty_pages_and_open_rows():
    assert report().grade == "A"
    assert report(source_words=10_500).grade == "A"  # 95% kept
    assert report(source_words=12_500).grade == "C"  # 80% kept
    assert report(source_words=20_000).grade == "D"  # 50% kept
    assert report(empty_pages=11).grade == "D"
    r = report()
    r.possible["x"] = 60  # 6 per 1,000 words
    assert r.grade == "C"
    r.possible["x"] = 10  # 1 per 1,000 words
    assert r.grade == "B"


def test_ocr_text_without_a_spelling_check_is_at_best_b():
    assert report(ocr=True, language="es").grade == "A"
    latin = report(ocr=True, language="la")
    assert latin.grade == "B"
    assert "no spelling check" in markdown(latin, "final")
    assert report(ocr=False, language="la").grade == "A"  # born-digital: nothing to check
