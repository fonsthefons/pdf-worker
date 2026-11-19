import re
import zipfile
from pathlib import Path

from pdf_worker.drop_notes import drop_notes
from pdf_worker.epub import write_epub
from pdf_worker.inline import BOLD, END_BOLD
from pdf_worker.markdown_export import write_markdown
from pdf_worker.output import Metadata
from pdf_worker.structure import ListItem, Note, Paragraph, cut_label
from pdf_worker.text_export import write_text

BLOCKS = [
    Paragraph("Intro."),
    ListItem("first[^1]", "a)", 1),
    ListItem("inner", "1.", 2),
    ListItem("second", "b)", 1),
    ListItem("odd", "d)", 1),  # not the one after "b)": Pandoc would call it "c)"
    Paragraph("After."),
    ListItem("plain", "", 1),  # no label: a bullet
    Note("1", "A note."),
]


def test_list_items_pass_drop_notes() -> None:
    items = [b for b in drop_notes(BLOCKS) if isinstance(b, ListItem)]
    assert items[0].text == "first"


def test_text_indents_by_depth(tmp_path: Path) -> None:
    out = tmp_path / "b.txt"
    write_text(BLOCKS, out, Metadata("T"))
    assert "\na) first[1]\n    1. inner\nb) second\n" in out.read_text()
    assert "d) odd\n\nAfter.\n\nplain\n\n" in out.read_text()


def test_markdown_keeps_labels(tmp_path: Path) -> None:
    out = tmp_path / "b.md"
    write_markdown(BLOCKS, out, Metadata("T"))
    text = out.read_text()
    assert "Intro.\n\na) first[^1]\n    1. inner\nb) second\n\nd\\) odd\n\nAfter." in text
    # "d)" is escaped: Pandoc would renumber it "c)"
    assert "After.\n\n- plain\n\n" in text


def test_markdown_bullets_of_any_sign_stay_a_list(tmp_path: Path) -> None:
    # Word's nested lists: "o", U+F0B7 and the like are bullets, not escaped paragraphs.
    items = [ListItem("outer", "", 1), ListItem("inner", "o", 2), ListItem("dash", "–", 1)]
    write_markdown(items, tmp_path / "w.md", Metadata("T"))
    assert "- outer\n    - inner\n- dash\n" in (tmp_path / "w.md").read_text()


def test_cut_label_ignores_style_markers() -> None:
    assert cut_label(f"{BOLD}1.{END_BOLD} Duda", "1.") == ("1.", "Duda")
    assert cut_label(f"{BOLD}a) Title{END_BOLD} text", "") == ("a)", f"{BOLD}Title{END_BOLD} text")
    assert cut_label(" point", "") == ("", "point")


def test_epub_nests_lists_and_shows_labels(tmp_path: Path) -> None:
    write_epub(BLOCKS, tmp_path / "b.epub", Metadata("T"))
    with zipfile.ZipFile(tmp_path / "b.epub") as z:
        html = z.read("OEBPS/c001.xhtml").decode()
    flat = re.sub(r"<(li|ol|span)[^>]*>", r"<\1>", html)
    assert "<ol>\n<li><span>a)</span>first<" in flat  # the note reference sits inside the item
    assert "<ol>\n<li><span>1.</span>inner</li>\n</ol></li>\n<li><span>b)</span>second</li>" in flat
    assert flat.count("<ol>") == flat.count("</ol>") == 3  # list, nested list, list after "After."
    assert "</ol>\n<p" in flat  # the list ends before the next paragraph
