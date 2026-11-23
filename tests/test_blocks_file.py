from pdf_worker.blocks_file import TYPES, read_blocks, read_metadata, write_blocks
from pdf_worker.output import Metadata
from pdf_worker.structure import (
    Gloss,
    Heading,
    Image,
    ListItem,
    Note,
    Paragraph,
    SectionStart,
    Table,
)

BLOCKS = [
    Heading("Uno", 1, page=0, top=72.5),
    Paragraph("Texto con saltos\nraros «ñ»[^p1-1]", small=True, page=0, top=90.0),
    ListItem("item", "a)", 2, page=1),
    Note("p1-1", "Una nota.", continued=True),
    Gloss(("línea 1", "línea 2")),
    Image(b"\xff\xd8\x00\xffbytes", 10, 20),
    Table((("a", "b"), ("c", "d"))),
    SectionStart("notes"),
]


def test_every_block_type_round_trips(tmp_path):
    assert set(TYPES) == {type(b).__name__ for b in BLOCKS}
    meta = Metadata("Título", author="Autor", language="es", year="2010")
    path = tmp_path / "book.blocks.jsonl"

    write_blocks(iter(BLOCKS), meta, path)

    assert read_metadata(path) == meta
    assert list(read_blocks(path)) == BLOCKS
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1 + len(BLOCKS)
