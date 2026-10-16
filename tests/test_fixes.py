from pdf_worker.fixes import Fix, Review, default_fixes_path, read_fixes, write_fixes
from pdf_worker.inline import margin_ref, page_mark, plain
from pdf_worker.structure import Heading, Note, Paragraph


def _book():
    return [
        Heading("Timeo", 1),
        Paragraph(
            page_mark(26, "27") + "Dijo ipodrias Herder y Būtzow. " + margin_ref("21a") + "Sí."
        ),
        Paragraph(margin_ref("~21b") + "Sócrates habló pero calló[^c9-2] luego."),
        Paragraph(page_mark(27, "28") + "Otra " + margin_ref("21e") + "Būtzow vez."),
        Note("c3-6", "Una nota."),
    ]


def _run(fixes, blocks=None, language="es"):
    review = Review(fixes, language)
    out = list(review.apply(blocks or _book()))
    return out, review.finish(), review


def test_flags_suspicious_items():
    _, added, review = _run([])
    rows = {(f.kind, f.find, f.page) for f in review.fixes}
    assert ("spelling", "ipodrias", "27") in rows
    assert ("chars", "Būtzow", "27") in rows
    assert ("note-no-ref", "c3-6", "28") in rows
    assert ("ref-no-note", "c9-2", "27") in rows
    assert ("margin-est", "~21b", "27") in rows
    assert ("margin-missing", "21c..21d", "27") in rows
    assert added["chars"] == 1  # Būtzow twice: one row
    assert next(f for f in review.fixes if f.find == "Būtzow").context.startswith("×2 ")


def test_applies_actions():
    fixes = [
        Fix("1", "27", "spelling", "ipodrias", action="replace", value="¿podrías"),
        Fix("2", "*", "chars", "Būtzow", action="replace", value="Bützow"),
        Fix("3", "28", "note-no-ref", "c3-6", action="attach", value="Otra"),
        Fix("4", "27", "ref-no-note", "c9-2", action="drop"),
        Fix("5", "27", "margin-est", "~21b", action="move", value="pero"),
        Fix("6", "27", "margin-missing", "21c..21d", action="add", value='"21c before luego"'),
        Fix("7", "27", "spelling", "Sócrates", action="ignore"),
    ]
    out, added, review = _run(fixes)
    text = " ".join(plain(b.text) for b in out)
    assert "¿podrías" in text and "Būtzow" not in text and text.count("Bützow") == 2
    assert "Otra[^c3-6]" in out[3].text
    assert "[^c9-2]" not in out[2].text
    assert out[2].text.startswith("Sócrates habló " + margin_ref("21b") + "pero")
    assert margin_ref("21c") + "luego" in out[2].text
    assert [f.status for f in review.fixes[:7]] == ["applied"] * 7
    new = {(f.kind, f.find) for f in review.fixes[7:]}
    assert {("spelling", "ipodrias"), ("spelling", "Sócrates"), ("chars", "Būtzow")}.isdisjoint(new)
    assert {"note-no-ref", "ref-no-note", "margin-est"}.isdisjoint(added)
    assert ("margin-missing", "21d") in new


def test_rebuild_keeps_user_rows_and_marks_stale(tmp_path):
    path = default_fixes_path(tmp_path / "book.ocr.pdf")
    assert path.name == "book.fixes.tsv"
    _, _, review = _run([])
    typo = next(f for f in review.fixes if f.find == "ipodrias")
    typo.action, typo.value = "replace", "podrías"
    review.fixes.append(Fix("99", "27", "spelling", "gone", action="replace", value="x"))
    write_fixes(path, review.fixes)
    before = read_fixes(path)

    out, added, review = _run(read_fixes(path))
    write_fixes(path, review.fixes)

    assert "podrías" in out[1].text
    assert [(f.id, f.action) for f in read_fixes(path)] == [(f.id, f.action) for f in before]
    by_find = {f.find: f for f in review.fixes}
    assert by_find["ipodrias"].status == "applied"
    assert by_find["gone"].status == "stale"
    assert by_find["Būtzow"].status == ""  # still flagged, waiting for an action
    assert added == {}


def test_ambiguous_find_changes_only_the_first():
    blocks = [Paragraph(page_mark(0, "1") + "teh cat and teh dog")]
    out, _, review = _run([Fix("1", "1", "spelling", "teh", action="replace", value="the")], blocks)
    assert plain(out[0].text) == "the cat and teh dog"
    assert review.fixes[0].status == "ambiguous"


def test_no_spelling_check_for_other_languages():
    _, added, _ = _run([], language="la")
    assert "spelling" not in added and "chars" not in added  # macrons are Latin
