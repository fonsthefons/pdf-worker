from pdf_worker.fixes import Fix, Review, default_fixes_path, read_fixes, write_fixes
from pdf_worker.inline import margin_ref, page_mark, plain, styled
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


def test_replace_spans_a_split_word():
    blocks = [Paragraph(page_mark(0, "1") + "Más que def niciones de diccionario.")]
    fix = Fix("1", "1", "spelling", "def niciones", action="replace", value="definiciones")
    out, _, review = _run([fix], blocks)
    assert "Más que definiciones de diccionario." in plain(out[0].text)
    assert review.fixes[0].status == "applied"
    # A margin reference or note mark between the halves stays, before the word.
    text = "Más que def " + margin_ref("21a") + "niciones[^3] de nada."
    out, _, review = _run([fix], [Paragraph(page_mark(0, "1") + text)])
    assert (
        out[0].text
        == page_mark(0, "1") + "Más que " + margin_ref("21a") + "definiciones[^3] de nada."
    )
    assert review.fixes[0].status == "applied"
    # Split by a page break: the row is on the page before (or after) the break.
    text = page_mark(0, "1") + "Más que def " + page_mark(1, "2") + "niciones de nada."
    out, _, review = _run([fix], [Paragraph(text)])
    assert (
        out[0].text == page_mark(0, "1") + "Más que " + page_mark(1, "2") + "definiciones de nada."
    )
    assert review.fixes[0].status == "applied"


def test_replace_in_italics():
    text = (
        page_mark(0, "1")
        + "la "
        + styled("Enciclopedt·a", italic=True)
        + " de "
        + styled("Pu", italic=True)
        + " sible."
    )
    fixes = [
        Fix("1", "1", "spelling", "Enciclopedt·a", action="replace", value="Enciclopedia"),
        Fix("2", "1", "spelling", "Pu sible", action="replace", value="Posible"),
    ]
    out, _, review = _run(fixes, [Paragraph(text)])
    assert styled("Enciclopedia", italic=True) in out[0].text
    assert plain(out[0].text) == "la Enciclopedia de Posible."
    assert [f.status for f in review.fixes[:2]] == ["applied", "applied"]


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


def test_spelling_knows_inflections_and_long_foreign_words():
    text = (
        "Si pudiésemos explicaras diciéndoselo: no ban sido, he abandoned becho. "
        "Basarlo, evitarle, basándoselo; averiguemos. Weltanschauung, pensiero, veritas, "
        "connaissance. Rehúye la inherencia, correctísima y riquísimos; considerémoslo."
    )
    _, _, review = _run([], [Paragraph(page_mark(0, "1") + text)])
    assert {f.find for f in review.fixes if f.kind == "spelling"} == {"ban", "becho", "averiguemos"}


def test_joins_words_split_at_line_breaks():
    text = (
        "la inmor-talidad y place-res e invo- "
        + margin_ref("108d")
        + "car por ciones al "
        + page_mark(1, "2")
        + "gún; cosa-en-sí, físico-químico, sino que, Jean-Jacques, acallar á Don, confies en."
    )
    out, _, _ = _run([], [Paragraph(page_mark(0, "1") + text)])
    assert out[0].text == page_mark(0, "1") + (
        "la inmortalidad y placeres e "
        + margin_ref("108d")
        + "invocar porciones "
        + page_mark(1, "2")
        + "algún; cosa-en-sí, físico-químico, sino que, Jean-Jacques, acallar á Don, confies en."
    )
    # A fragment before a longer part, both words joined known.
    out, _, _ = _run([], [Paragraph(page_mark(0, "1") + "lo deter minado y su conoci miento")])
    assert plain(out[0].text) == "lo determinado y su conocimiento"


def test_spelling_rows_say_the_likely_error_reliable_first():
    text = "Zqxwrt dijo Eutifrón: si pudieramos, Pusible, Bcrvir. Una nota[^c1-1] en Būtzow."
    _, _, review = _run([], [Paragraph(page_mark(0, "1") + text)])
    rows = [(f.kind, f.type, f.find, f.value) for f in review.fixes]
    assert rows[:2] == [("chars", "", "Būtzow", ""), ("ref-no-note", "", "c1-1", "")]
    assert rows[2:] == [
        ("spelling", "accent", "pudieramos", "pudiéramos"),
        ("spelling", "swap", "Bcrvir", "Hervir"),
        ("spelling", "ocr1: fusible?", "Pusible", ""),
        ("spelling", "name", "Zqxwrt", ""),
        ("spelling", "name", "Eutifrón", ""),
    ]
    assert not any(f.action for f in review.fixes)


def test_no_rows_for_all_caps_or_names_the_book_repeats():
    text = (
        "Según MEZCLADO y SCHŌNEBAUM, Zqxwrt y Zqxwrt; Bohatec, Bohatec, Bohatec y Bohatcc. "
        "Pudieramos. Pudieramos."
    )
    _, _, review = _run([], [Paragraph(page_mark(0, "1") + text)])
    rows = {(f.kind, f.find): f.type for f in review.fixes}
    assert rows == {("spelling", "Bohatcc"): "name: Bohatec?", ("spelling", "Pudieramos"): "accent"}


def test_old_spelling_is_not_flagged_in_an_old_edition():
    words = "Ponia lleuauamos, dezir cabeça; dixo seys veces, yglesia, tauerna, dellas. Fué becho. "
    old = "Vino á casa ó á la plaza, á pie y á caballo. " * 2
    _, _, review = _run([], [Paragraph(page_mark(0, "1") + old + words)])
    assert {f.find for f in review.fixes if f.kind == "spelling"} == {"becho"}
    # A modern book keeps them: there they are misreadings.
    _, _, review = _run([], [Paragraph(page_mark(0, "1") + words)])
    assert {f.find for f in review.fixes if f.kind == "spelling"} >= {"Ponia", "dezir", "becho"}


def test_spelling_only_in_the_body():
    blocks = [
        Heading("Capítulo", 1),
        Paragraph(page_mark(0, "1") + "Texto becho."),
        Note("1", "Nota cfecto, ВоHATEC."),
        Paragraph("Letra pequeña dcdicaban.", small=True),
        Heading("Bibliografía", 1),
        Heading("Ediciones", 2),
        Paragraph("Philologie Būtzow."),
        Heading("Diálogo", 1),
        Paragraph("Otra vez mendaba."),
        Paragraph("MAIGRON, L., Le roman historique, París, 1898, $ Būtzow."),
        Paragraph("Gesammelte kleinere Schriften, 6 vols., Halle, 1775."),
    ]
    _, _, review = _run([], blocks)
    assert {f.find for f in review.fixes if f.kind == "spelling"} == {"becho", "mendaba"}
    # Odd letters are flagged in notes, not in bibliographies or entry-like paragraphs.
    assert {f.find for f in review.fixes if f.kind == "chars"} == {"ВоHATEC"}


def test_bibliography_subheadings_of_the_same_level_stay_in_it():
    blocks = [
        Heading("BREVE BIBLIOGRAFIA", 2),
        Heading("Obras generales", 2),
        Paragraph(page_mark(0, "1") + "Philologie mendaba."),
        Heading("Capítulos I-II: La Ilustración", 2),
        Heading("Estudios", 2),
        Paragraph("Otra dcdicaban."),
        Heading("Capítulo IX", 2),
        Paragraph("Texto becho."),
    ]
    _, _, review = _run([], blocks)
    assert {f.find for f in review.fixes if f.kind == "spelling"} == {"becho"}


def test_no_spelling_check_for_text_that_was_not_ocrd():
    review = Review([], "es", spelling=False)
    list(review.apply(_book()))
    added = review.finish()
    assert "spelling" not in added and added["chars"]  # "ipodrias" is the author's


def test_convert_checks_spelling_only_in_ocr_text(make_pdf, tmp_path, monkeypatch):
    from pdf_worker import convert

    pdf = make_pdf(["Un hombre becho de piedra, dijo el pastor del pueblo."])

    def spelling():
        return [f.find for f in read_fixes(default_fixes_path(pdf)) if f.kind == "spelling"]

    convert.convert_pdf(pdf, tmp_path / "out.txt", "txt", language="es")
    assert spelling() == []
    monkeypatch.setattr(convert, "mostly_scanned", lambda doc: True)  # as if OCR'd
    convert.convert_pdf(pdf, tmp_path / "out.txt", "txt", language="es")
    assert spelling() == ["becho"]


def test_no_spelling_check_for_other_languages():
    _, added, _ = _run([], language="la")
    assert "spelling" not in added and "chars" not in added  # macrons are Latin
