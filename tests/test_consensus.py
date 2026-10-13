import json
from collections import Counter

import pymupdf

from pdf_worker.consensus import FIXES_KEY, Token, page_tokens, vote
from pdf_worker.layout import page_lines


def _tokens(*words):
    return [Token(w, (10.0 * i, 0.0, 10.0 * i + 8, 10.0)) for i, w in enumerate(words)]


COUNTS = Counter({"por": 50, "parte": 40, "parce": 1, "así": 30, "asi": 10, "el": 99, "ol": 1})


def test_a_word_both_other_readings_agree_on_wins():
    tokens = _tokens("por", "parce", "nuestra")

    fixes = vote(tokens, [["por", "parte", "nuestra"], ["por", "parte", "nuestra"]], COUNTS)

    assert [f[4:] for f in fixes] == [["parce", "parte"]]
    assert fixes[0][:4] == [10.0, 0.0, 18.0, 10.0]


def test_no_fix_without_agreement_or_against_the_books_words():
    tokens = _tokens("por", "parce", "el")

    split = vote(tokens, [["por", "parte", "el"], ["por", "porte", "el"]], COUNTS)
    rare = vote(tokens, [["por", "parce", "ol"], ["por", "parce", "ol"]], COUNTS)

    assert split == [] and rare == []


def test_accents_follow_the_vote_and_case_is_kept():
    fixes = vote(_tokens("Asi"), [["así"], ["así"]], COUNTS)

    assert fixes[0][5] == "Así"
    assert vote(_tokens("así"), [["asi"], ["asi"]], COUNTS) == []  # never removed


def test_page_lines_read_the_fixed_words(tmp_path):
    path = tmp_path / "fixed.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "por parce nuestra", fontsize=11)
    token = next(t for t in page_tokens(page) if t.text == "parce")
    fix = [[*token.bbox, "parce", "parte"]]
    doc.xref_set_key(page.xref, FIXES_KEY, pymupdf.get_pdf_str(json.dumps(fix)))
    doc.save(path)

    with pymupdf.open(path) as saved:
        lines = page_lines(saved[0])

    assert lines[0].text == "por parte nuestra"
