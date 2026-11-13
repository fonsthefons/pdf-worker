import json
import sqlite3

import pytest

from pdf_worker.errors import PdfWorkerError
from pdf_worker.kindle_positions import (
    Highlight,
    highlights_from_db,
    palmdoc,
    read_azw3,
    span_text,
    title_key,
    trailing_size,
)


def test_palmdoc_literals_runs_spaces_and_back_references():
    # "abc", back 3 copy 3, space + "h", 2 raw bytes ("é")
    assert palmdoc(b"abc\x80\x18\xe8\x02\xc3\xa9") == "abcabc hé".encode()


def test_trailing_entries_and_multibyte_bytes():
    rec = b"hello" + b"\x00" + b"\xaa\x82"  # multibyte count 0 (1 byte), one 2-byte entry
    assert trailing_size(rec, 0b11) == 3
    assert trailing_size(rec, 0) == 0


def test_span_text_rounds_out_to_words_and_drops_markup():
    stream = b'<p id="b1" class="c">Hola mun&amp;do</p>\n<p aid="3Q28F">Voy a dar</p>'
    assert span_text(stream, stream.index(b"la"), stream.index(b"do<")) == "Hola mun&do"
    assert span_text(stream, stream.index(b'F">'), stream.index(b"Voy") + 3) == "Voy"
    assert span_text(stream, stream.index(b"do<"), stream.index(b" a ")) == "mun&do Voy"


def test_read_azw3_rejects_other_files(tmp_path):
    other = tmp_path / "x.azw3"
    other.write_bytes(b"\0" * 100)
    with pytest.raises(PdfWorkerError, match="not an AZW3"):
        read_azw3(other)


def test_title_key():
    assert title_key("La distinción: Criterio") == title_key("La_distincion__Criterio")


def make_db(path, rows):
    con = sqlite3.connect(path)
    con.execute(
        "create table nonsyncable_annotations (annotation_id text, book_id text, dataset int, "
        "start_position text, end_position text, created_time int, modified_time int, "
        "serialized_payload text)"
    )
    for i, (book_id, dataset, start, end) in enumerate(rows):
        pos = [json.dumps({"longPosition": str(p), "shortPosition": p}) for p in (start, end)]
        con.execute(
            "insert into nonsyncable_annotations values (?, ?, ?, ?, ?, 0, 0, '{}')",
            (f"a{i}", book_id, dataset, *pos),
        )
    con.commit()
    con.close()
    return path


LECCIONES = "d601-EBOK-Lecciones_preliminares_de_filos:36B66A99-0"
DUNE = "9ac3-EBOK-Dune:B3AAE4AA-0"
STREAM = b"<p>Uno dos tres cuatro cinco seis</p>"


def test_book_chosen_by_title(tmp_path):
    db = make_db(
        tmp_path / "k.db",
        [(LECCIONES, 1, 22, 31), (LECCIONES, 1, 3, 9), (LECCIONES, 2, 0, 0), (DUNE, 1, 3, 9)],
    )

    found = highlights_from_db(db, "Lecciones preliminares de filosofía", STREAM)

    assert found == [Highlight("Uno dos", 3, 9), Highlight("cinco seis", 22, 31)]


def test_short_title_must_match_whole(tmp_path):
    db = make_db(tmp_path / "k.db", [(DUNE, 1, 3, 9)])

    with pytest.raises(PdfWorkerError, match="those with some: Dune"):
        highlights_from_db(db, "Dune Messiah", STREAM)


def test_several_books_match(tmp_path):
    other = "c3-EBOK-Lecciones_preliminares_de_filos:00ABFDC1-0"
    db = make_db(tmp_path / "k.db", [(LECCIONES, 1, 3, 9), (other, 1, 3, 9)])

    with pytest.raises(PdfWorkerError, match="Several") as error:
        highlights_from_db(db, "Lecciones preliminares de filosofía", STREAM)
    assert LECCIONES in str(error.value) and other in str(error.value)
