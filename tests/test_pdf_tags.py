from pathlib import Path

import pymupdf
import pytest

from pdf_worker.convert import convert_pdf
from pdf_worker.footnotes import layout_page
from pdf_worker.layout import analyze_document
from pdf_worker.pdf_tags import read_tags


def _tagged_pdf(path: Path, pages: list[list[tuple]]) -> Path:
    """Write a tagged PDF. Each page is a list of ``(role, label, lines)``: role "P",
    "H1", "Div" (an element the tags don't follow), "LI" (consecutive ones make one L,
    ``label`` its Lbl, set at x 72) or "Artifact"; ``lines`` are ``(x, baseline, text)``."""
    doc = pymupdf.open()
    objects: dict[int, str] = {}  # xref -> its dictionary, written at the end
    top = doc.get_new_xref()
    kids: list[int] = []  # the Document element's
    parents: list[list[int]] = []  # per page: MCID -> its element

    def element(role: str, parent: int, page_xref: int, k: str) -> str:
        return f"<</Type/StructElem/S/{role}/P {parent} 0 R/Pg {page_xref} 0 R/K {k}>>"

    for number, elements in enumerate(pages):
        page = doc.new_page()
        page.insert_font(fontname="helv")
        owners: list[int] = []
        stream: list[str] = []
        list_xref = None

        def show(lines, tag, owner, stream=stream, owners=owners, height=page.rect.height) -> str:
            mcids = []
            for x, y, text in lines:
                if owner is None:
                    stream.append("/Artifact BMC")
                else:
                    stream.append(f"/{tag} <</MCID {len(owners)}>> BDC")
                    mcids.append(str(len(owners)))
                    owners.append(owner)
                text = text.replace("(", r"\(").replace(")", r"\)")
                stream.append(f"BT /helv 11 Tf {x} {height - y} Td ({text}) Tj ET EMC")
            return "[" + " ".join(mcids) + "]"

        for role, label, lines in elements:
            if role == "Artifact":
                show(lines, "", None)
                list_xref = None
                continue
            if role != "LI":
                xref = doc.get_new_xref()
                objects[xref] = element(role, top, page.xref, show(lines, role, xref))
                kids.append(xref)
                list_xref = None
                continue
            if list_xref is None:
                list_xref = doc.get_new_xref()
                objects[list_xref] = []  # its LIs, filled below
                kids.append(list_xref)
            item = doc.get_new_xref()
            lbl = doc.get_new_xref()
            body = doc.get_new_xref()
            lbl_k = show([(72, lines[0][1], label)], "Lbl", lbl)
            body_k = show(lines, "LBody", body)
            objects[lbl] = element("Lbl", item, page.xref, lbl_k)
            objects[body] = element("LBody", item, page.xref, body_k)
            objects[item] = f"<</Type/StructElem/S/LI/P {list_xref} 0 R/K [{lbl} 0 R {body} 0 R]>>"
            objects[list_xref].append(item)
        contents = doc.get_new_xref()
        doc.update_object(contents, "<<>>")
        doc.update_stream(contents, "\n".join(stream).encode())
        doc.xref_set_key(page.xref, "Contents", f"{contents} 0 R")
        doc.xref_set_key(page.xref, "StructParents", str(number))
        parents.append(owners)
    for xref, value in objects.items():
        if isinstance(value, list):  # an L
            refs = " ".join(f"{i} 0 R" for i in value)
            value = f"<</Type/StructElem/S/L/P {top} 0 R/K [{refs}]>>"
        doc.update_object(xref, value)
    refs = " ".join(f"{i} 0 R" for i in kids)
    doc.update_object(top, f"<</Type/StructElem/S/Document/K [{refs}]>>")
    nums = " ".join(
        f"{n} [{' '.join(f'{o} 0 R' for o in owners)}]" for n, owners in enumerate(parents)
    )
    tree = doc.get_new_xref()
    doc.update_object(tree, f"<</Nums [{nums}]>>")
    root = doc.get_new_xref()
    doc.update_object(
        root,
        f"<</Type/StructTreeRoot/K {top} 0 R/ParentTree {tree} 0 R"
        f"/ParentTreeNextKey {len(parents)}>>",
    )
    doc.xref_set_key(doc.pdf_catalog(), "StructTreeRoot", f"{root} 0 R")
    doc.xref_set_key(doc.pdf_catalog(), "MarkInfo", "<</Marked true>>")
    doc.save(path)
    doc.close()
    return path


PAGE = [
    ("Artifact", None, [(72, 40, "Running Head Of The Book")]),
    ("H1", None, [(72, 80, "Chapter One")]),
    (
        "P",
        None,
        [
            (72, 110, "The first paragraph runs over two lines of text and does not end"),
            (72, 124, "here but on the line below it."),
        ],
    ),
    ("LI", "a)", [(90, 150, "first item of the list, which is long enough to fill the line")]),
    ("LI", "b)", [(90, 164, "second item")]),
]


@pytest.fixture
def tagged(tmp_path: Path) -> Path:
    return _tagged_pdf(tmp_path / "tagged.pdf", [PAGE])


def test_read_tags_elements_labels_and_artifacts(tagged: Path) -> None:
    with pymupdf.open(tagged) as doc:
        tags = read_tags(doc)
    assert tags is not None
    boxes = tags[0]
    assert [b.kind for b in boxes] == ["h1", "p", "p", "li", "li", "li", "li"]
    p1, p2 = boxes[1:3]
    assert p1.element == p2.element  # two lines, one P
    a_label, a_body, b_label, _ = boxes[3:]
    assert a_label.element == a_body.element != b_label.element  # Lbl and LBody: their LI
    assert (a_body.label, a_body.depth, b_label.label) == ("a)", 1, "b)")
    assert all("Running" not in str(b) for b in boxes)


def test_read_tags_none_without_tree_or_when_unsound(make_pdf, tmp_path: Path) -> None:
    with pymupdf.open(make_pdf(["Plain text"])) as doc:
        assert read_tags(doc) is None
    div = [("Div", None, [(72, 80, "Text in an element the tags don't follow")])]
    with pymupdf.open(_tagged_pdf(tmp_path / "div.pdf", [div])) as doc:
        assert read_tags(doc) is None


def test_layout_page_follows_tags(tagged: Path) -> None:
    with pymupdf.open(tagged) as doc:
        profile = analyze_document(doc)
        profile.tags = read_tags(doc)
        layout = layout_page(doc[0], 0, profile)

    def line(start: str):
        return next(bl for bl in layout.lines if bl.text.strip().startswith(start))

    # Outside the tree is not furniture by itself (PyMuPDF shows an element's lines on the
    # next page so too): the furniture rules decide, and keep it on a one-page book.
    assert line("Running").tag is None
    heading = line("Chapter")
    assert heading.title and heading.kind is None and heading.tag.kind == "h1"
    assert line("here but").starts is None  # inside the P: the rules decide
    assert line("b)").starts is True and line("b)").tag.label == "b)"  # a new LI


def test_convert_follows_tags_unless_told_not_to(tagged: Path, tmp_path: Path) -> None:
    out = tmp_path / "tagged.md"
    convert_pdf(tagged, out, "md")
    text = out.read_text()
    assert "# Chapter One" in text
    assert "\na) first item" in text and "\nb) second item" in text  # one list, labels kept
    assert "does not end here but" in text
    convert_pdf(tagged, out, "md", tags=False)
    assert "Running Head" in out.read_text()


def test_convert_item_wrapped_and_after_a_page_break(tmp_path: Path) -> None:
    # Its second line looks like a new item ("2."), but one LI is one item; its label comes
    # after the page's mark (the new page's first block).
    lines = [
        (90, 80, "third item on the next page, long enough to fill the line"),
        (90, 94, "2. wrap"),
    ]
    out = tmp_path / "two.md"
    convert_pdf(_tagged_pdf(tmp_path / "two.pdf", [PAGE, [("LI", "c)", lines)]]), out, "md")
    assert (
        "\nc) third item on the next page, long enough to fill the line 2. wrap\n"
        in out.read_text()
    )


def test_read_tags_unsound_when_each_line_is_a_p(tmp_path: Path) -> None:
    # Some exports tag every printed line as a P: a page of them is left to the rules.
    lines = [("P", None, [(72, 80 + 14 * i, f"line {i} of a long paragraph")]) for i in range(16)]
    with pymupdf.open(_tagged_pdf(tmp_path / "lines.pdf", [lines])) as doc:
        assert read_tags(doc) is None
    with pymupdf.open(_tagged_pdf(tmp_path / "few.pdf", [lines[:14]])) as doc:
        assert read_tags(doc) is not None  # a short list of one-line Ps is fine


def test_layout_page_tops_and_marks(tmp_path: Path) -> None:
    pages = [
        [("P", None, [(72, 80, "A paragraph that may run on from the page before.")])],
        [("LI", "-", [(90, 80, "an item at the page's top")])],  # not like "1." (ITEM_RE)
        [
            ("Artifact", None, [(72, 80, "a paragraph's line carried over, untagged, and")]),
            ("P", None, [(72, 94, "its rest, tagged as a new P (Chrome's print).")]),
            ("H1", None, [(72, 130, "A Heading")]),
        ],
        [
            ("Artifact", None, [(72, 80, "an item's line carried over, untagged.")]),
            ("H1", None, [(72, 110, "Another Heading")]),
        ],
    ]
    with pymupdf.open(_tagged_pdf(tmp_path / "tops.pdf", pages)) as doc:
        profile = analyze_document(doc)
        profile.tags = read_tags(doc)
        assert layout_page(doc[0], 0, profile).lines[0].starts is None  # a P: the rules'
        assert layout_page(doc[1], 1, profile).lines[0].starts is True  # an LI: new
        third = layout_page(doc[2], 2, profile).lines
        assert [bl.starts for bl in third[1:3]] == [None, True]
        assert layout_page(doc[3], 3, profile).lines[1].starts is True  # an H after run-on
        # The marks win fully: a line they call body text is no title by its H tag.
        profile.kinds = {2: [None, None, "body"]}
        assert not layout_page(doc[2], 2, profile).lines[2].title


def test_convert_untagged_run_on_continues_an_item(tmp_path: Path) -> None:
    # Chrome's print leaves an element's lines on the next page outside the tree.
    second = [
        ("Artifact", None, [(90, 80, "and the end of the item, carried over.")]),
        ("P", None, [(72, 110, "Then a paragraph.")]),
    ]
    out = tmp_path / "run.md"
    convert_pdf(_tagged_pdf(tmp_path / "run.pdf", [PAGE[:4], second]), out, "md")
    text = out.read_text()
    assert "fill the line and the end of the item, carried over.\n" in text
    assert "\n\nThen a paragraph." in text


def test_convert_adjacent_headings_stay_apart(tmp_path: Path) -> None:
    page = [
        ("H1", None, [(72, 80, "First Title")]),
        ("H1", None, [(72, 100, "Second Title")]),
        ("H2", None, [(72, 130, "Part One of"), (72, 144, "the Heading")]),
        ("P", None, [(72, 170, "Some text.")]),
    ]
    out = tmp_path / "h.md"
    convert_pdf(_tagged_pdf(tmp_path / "h.pdf", [page]), out, "md")
    text = out.read_text()
    assert "# First Title\n" in text and "# Second Title\n" in text
    assert "## Part One of the Heading\n" in text
