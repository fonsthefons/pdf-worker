import json

import pytest
from ai_client import AIClientError

from pdf_worker import summarize as sm
from pdf_worker.blocks_file import read_blocks, write_blocks
from pdf_worker.inline import BOLD, END_BOLD, contents_entry, page_mark, styled
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


def words(n, word="palabra"):
    return " ".join([word] * n) + "."


@pytest.fixture
def book(tmp_path):
    def _book(blocks, name="libro"):
        path = tmp_path / f"{name}.blocks.jsonl"
        write_blocks(blocks, Metadata("El libro", language="es"), path)
        return path

    return _book


class FakeChat:
    def __init__(self, reply=None, context=sm.CEILING_WORDS):
        self.calls = []
        self.reply = reply or (lambda user, n: f"Resumen de {_part(user)}. {words(10, 'idea')}")
        self.context = context

    def __call__(self, system, user):
        self.calls.append(user)
        return self.reply(user, len(self.calls)), "fake"

    def context_words(self):
        return self.context


def _part(user):
    return next(line for line in user.splitlines() if line.startswith("Part: "))[6:]


def example_tree():
    # 1 > 1.1-1.3; 2 > 2.1 > 2.1.a-b
    return [
        Heading("1 Uno", 1),
        Heading("1.1 A", 2),
        Paragraph(words(100)),
        Heading("1.2 B", 2),
        Paragraph(words(100)),
        Heading("1.3 C", 2),
        Paragraph(words(100)),
        Heading("2 Dos", 1),
        Paragraph(words(90, "intro")),
        Heading("2.1 D", 2),
        Heading("2.1.a E", 3),
        Paragraph(words(100)),
        Heading("2.1.b F", 3),
        Paragraph(words(100)),
    ]


def shown(blocks):
    """Each heading's title with whether a summary follows it."""
    out = []
    for block in blocks:
        if isinstance(block, Heading):
            out.append([block.text, False])
        else:
            out[-1][1] = True
    return [tuple(row) for row in out]


def test_outline_tree_depths_and_text(book):
    path = book(
        [
            Heading(page_mark(0, "1") + "I. Primero[^1]", 1),
            Paragraph("Texto " + page_mark(1, "2") + "con nota[^2] y más."),
            Note("1", "Una nota."),
            Gloss(("glosa",)),
            Image(b"x", 1, 1),
            Heading("1. Sub", 2),
            ListItem("un punto", "a)", 1),
            Table((("x", "y"), ("z", "w"))),
            Heading("II. Segundo", 1),
        ]
    )
    outline = sm.load_outline(path)
    assert outline.meta.title == "El libro"
    first, second = outline.root.children
    assert (first.title, first.number, first.depth, first.level) == ("I. Primero", 1, 1, 1)
    assert first.paragraphs == ["Texto con nota y más."]
    sub = first.children[0]
    assert (sub.number, sub.depth, sub.level) == (2, 2, 2)
    assert sub.paragraphs == ["a) un punto", "x | y\nz | w"]
    assert (second.number, second.depth) == (3, 1)
    assert first.words == 5 + 3 + 6


def test_skips_named_sections_and_prefixes(book):
    path = book(
        [
            Heading("Índice", 1),
            Paragraph(contents_entry("Uno ....... 5")),
            Heading("1. Uno", 1),
            Paragraph(contents_entry("Uno ....... 5")),
            Paragraph("Texto."),
            SectionStart("notes"),
            Heading("Notas del editor", 1),
            Paragraph("1. Una nota."),
            SectionStart("main"),
            Heading("2. Dos", 1),
            Heading("Apéndice", 1),
            Heading("III. Bibliografía", 1),
            Paragraph("Autor, Libro."),
        ]
    )
    outline = sm.load_outline(path, skip=["apénd"])
    assert [n.title for n in outline.nodes()] == ["1. Uno", "2. Dos"]
    assert outline.root.children[0].paragraphs == ["Texto."]


def test_outline_echo_dropped_only_before_the_body(book):
    path = book(
        [
            Heading("Capítulo 1", 1),
            Heading("Conclusión", 2),
            Heading("Capítulo 2", 1),
            Heading("Prólogo", 1),
            Paragraph("Breve."),
            Heading("Capítulo 1", 1),
            Paragraph(words(300)),
            Heading("Conclusión", 2),
            Paragraph("Fin uno."),
            Heading("Capítulo 2", 1),
            Heading("Conclusión", 2),
            Paragraph("Fin dos."),
        ]
    )
    titles = [(n.title, n.depth) for n in sm.load_outline(path).nodes()]
    assert titles == [
        ("Prólogo", 1),
        ("Capítulo 1", 1),
        ("Conclusión", 2),
        ("Capítulo 2", 1),
        ("Conclusión", 2),
    ]


def test_select_by_number_and_path(book):
    outline = sm.load_outline(book(example_tree()))
    assert [n.title for n in sm.select(outline, [2, "6"])] == ["1.1 A", "2.1 D"]
    assert sm.select(outline, ["2 > 2.1 > 2.1.b"])[0].title == "2.1.b F"
    assert sm.select(outline, ["2.1.a"])[0].number == 7
    assert sm.select(outline, []) == outline.root.children
    with pytest.raises(sm.SummarizeError, match="no part matches.*2.1 D"):
        sm.select(outline, ["2 > x"])
    with pytest.raises(sm.SummarizeError, match="no part matches"):
        sm.select(outline, ["1 > 1."])  # "1." is not "1.1"
    with pytest.raises(sm.SummarizeError, match="no part 99"):
        sm.select(outline, [99])


@pytest.mark.parametrize(
    "level, expected",
    [
        (
            "all",
            [
                ("1 Uno", False),
                ("1.1 A", True),
                ("1.2 B", True),
                ("1.3 C", True),
                ("2 Dos", False),
                ("2.1 D", False),
                ("2.1.a E", True),
                ("2.1.b F", True),
            ],
        ),
        (
            2,
            [
                ("1 Uno", False),
                ("1.1 A", True),
                ("1.2 B", True),
                ("1.3 C", True),
                ("2 Dos", False),
                ("2.1 D", True),
            ],
        ),
        (0, [("1 Uno", True), ("2 Dos", True)]),
    ],
)
def test_levels(book, tmp_path, level, expected):
    outline = sm.load_outline(book(example_tree()))
    chat = FakeChat()
    blocks = sm.summarize(outline, outline.root.children, level, chat, tmp_path / "c.json")
    assert shown(blocks) == expected
    assert len(chat.calls) == sum(summarized for _, summarized in expected)


def test_chosen_node_keeps_its_ancestors_and_deeper_than_level_is_one_summary(book, tmp_path):
    outline = sm.load_outline(book(example_tree()))
    chosen = sm.select(outline, ["2.1.a", "2.1.b"])
    blocks = sm.summarize(outline, chosen, 1, FakeChat(), tmp_path / "c.json")
    assert shown(blocks) == [
        ("2 Dos", False),
        ("2.1 D", False),
        ("2.1.a E", True),
        ("2.1.b F", True),
    ]
    assert blocks[2] == Heading("2.1.a E", 3)


def test_introduction_goes_to_the_first_child(book, tmp_path):
    outline = sm.load_outline(book(example_tree()))
    chat = FakeChat()
    sm.summarize(outline, sm.select(outline, [5]), "all", chat, tmp_path / "c.json")
    first, second = chat.calls
    assert "Introduction to 2 Dos\n\nintro intro" in first
    assert "Introduction" not in second
    assert _part(first) == "2 Dos > 2.1 D > 2.1.a E"


def test_short_part_quoted_without_request(book, tmp_path):
    outline = sm.load_outline(book([Heading("Uno", 1), Paragraph("Poco texto aquí.")]))
    chat = FakeChat()
    blocks = sm.summarize(outline, outline.root.children, 0, chat, tmp_path / "c.json")
    assert blocks == [Heading("Uno", 1), Paragraph("Poco texto aquí.")]
    assert chat.calls == []


def test_over_the_ceiling_children_then_merge(book, tmp_path):
    outline = sm.load_outline(book(example_tree()))
    chat = FakeChat(context=150)
    blocks = sm.summarize(outline, sm.select(outline, [1]), 0, chat, tmp_path / "c.json")
    assert len(chat.calls) == 4  # 1.1, 1.2, 1.3, then the merge
    assert "1.1 A\n\nResumen de 1 Uno > 1.1 A." in chat.calls[-1]
    assert "summaries of the part's pieces" in chat.calls[-1]
    assert shown(blocks) == [("1 Uno", True)]


def test_long_leaf_split_at_paragraph_ends(book, tmp_path):
    path = book([Heading("Uno", 1), *[Paragraph(words(100, f"p{i}")) for i in range(3)]])
    outline = sm.load_outline(path)
    chat = FakeChat(context=250)
    sm.summarize(outline, outline.root.children, 0, chat, tmp_path / "c.json")
    assert len(chat.calls) == 3
    assert "p0" in chat.calls[0] and "p1" in chat.calls[0] and "p2" not in chat.calls[0]
    assert "p2" in chat.calls[1] and "Merge" in chat.calls[2]


def test_length_retry(book, tmp_path):
    outline = sm.load_outline(book([Heading("Uno", 1), Paragraph(words(100))]))
    chat = FakeChat(reply=lambda user, n: words(500, "largo") if n == 1 else "Bien resumido.")
    blocks = sm.summarize(outline, outline.root.children, 0, chat, tmp_path / "c.json")
    assert len(chat.calls) == 2 and "500 words" in chat.calls[1]
    assert blocks[1:] == [Paragraph("Bien resumido.")]


def test_bold_phrases(book, tmp_path):
    text = (
        f"La {BOLD}gracia{END_BOLD} {BOLD}santificante{END_BOLD}, "
        f"«{BOLD}ex opere operato{END_BOLD}», {BOLD}de{END_BOLD} y "
        f"{BOLD}gracia santificante.{END_BOLD} "
    )
    path = book([Heading("Uno", 1), Paragraph(text + words(90))])
    outline = sm.load_outline(path)
    node = outline.root.children[0]
    assert node.bold == ["gracia santificante", "ex opere operato"]

    def reply(user, n):
        assert "word for word" in user
        if n == 1:
            return "# Título\n\nLa **Gracia   Santificante** obra.\n- Otra idea."
        return "La Gracia Santificante obra.\n\nOtra idea."

    chat = FakeChat(reply=reply)
    blocks = sm.summarize(outline, [node], 0, chat, tmp_path / "c.json", keep_bold=True)
    assert len(chat.calls) == 2 and "left out: ex opere operato" in chat.calls[1]
    assert blocks[1:] == [
        Paragraph("La " + styled("Gracia Santificante", bold=True) + " obra."),
        Paragraph("Otra idea."),
        Paragraph("Términos destacados: ex opere operato"),
    ]


def test_markdown_stripped():
    assert sm._strip_markdown("## A\n**b** y *c*\n\n- d") == "A\n\nb y c\n\nd"


def test_cache_hit_resume_and_fresh(book, tmp_path):
    outline = sm.load_outline(book(example_tree()))
    cache = tmp_path / "libro.summaries.json"
    nodes = outline.root.children
    assert sm.estimate(outline, nodes, "all", cache) == 2 * 5  # each part: one retry at most

    def failing(user, n):
        if n == 3:
            raise sm.SummarizeError("quota")
        return f"Resumen de {_part(user)}. {words(10, 'idea')}"

    with pytest.raises(sm.SummarizeError, match="stopped after 2 of 10 requests"):
        sm.summarize(outline, nodes, "all", FakeChat(reply=failing), cache)
    assert len(json.loads(cache.read_text())) == 2
    assert sm.estimate(outline, nodes, "all", cache) == 2 * 3
    chat = FakeChat()
    first = sm.summarize(outline, nodes, "all", chat, cache)
    assert len(chat.calls) == 3
    again = FakeChat()
    assert sm.summarize(outline, nodes, "all", again, cache) == first and again.calls == []
    sm.summarize(outline, nodes, "all", again, cache, fresh=True)
    assert len(again.calls) == 5


class FakeClient:
    def __init__(self, fail=(), per_day=False):
        self.key, self.fail, self.per_day, self.sent = "k", set(fail), per_day, []

    def pick_models(self, model=None):
        return [model] if model else ["a", "b"]

    def requests_left(self):
        return 10

    def catalog(self):
        return {"a": {"context_length": 16_000}}

    def chat(self, user, system, model, fallbacks, **options):
        assert fallbacks is False
        self.sent.append(model)
        if model in self.fail:
            raise AIClientError("down", status=503, per_day=self.per_day)
        return "ok"


def test_model_chat_sticks_to_a_model_and_moves_on(monkeypatch):
    client = FakeClient(fail={"a"})
    monkeypatch.setattr(sm.ai_client, "get_client", lambda name: client)
    chat = sm.ModelChat()
    assert chat.context_words() == 10_000 * 2 // 3 - sm.PROMPT_WORDS
    assert chat("s", "u") == ("ok", "b")
    assert chat("s", "u") == ("ok", "b")
    assert client.sent == ["a", "a", "b", "b"]  # a model gets a second try before it is dropped
    assert chat.context_words() == int(sm.DEFAULT_CONTEXT / 1.6 * 2 / 3) - sm.PROMPT_WORDS
    client.fail.add("b")
    with pytest.raises(sm.SummarizeError, match="every model failed"):
        chat("s", "u")


def test_model_chat_stops_on_the_daily_quota(monkeypatch):
    monkeypatch.setattr(sm.ai_client, "get_client", lambda name: FakeClient({"a"}, per_day=True))
    with pytest.raises(sm.SummarizeError, match="daily quota"):
        sm.ModelChat()("s", "u")


def test_write_summary_round_trips_headings(book, tmp_path):
    outline = sm.load_outline(book(example_tree()))
    blocks = sm.summarize(outline, outline.root.children, 2, FakeChat(), tmp_path / "c.json")
    meta = sm.summary_meta(outline.meta)
    assert meta.title == "Resumen: El libro"
    name = sm.summary_name("libro", 2, [])
    out = tmp_path / "out"
    saved, md = sm.write_summary(blocks, meta, out, name, ["md"])
    assert saved.name == "libro.summary-2.blocks.jsonl" and md.name == "libro.summary-2.md"
    assert list(read_blocks(saved)) == blocks
    headings = [line for line in md.read_text().splitlines() if line.startswith("#")]
    assert headings == ["#" * b.level + " " + b.text for b in blocks if isinstance(b, Heading)]


def test_names_and_places(tmp_path):
    work = tmp_path / "file_work" / "libro.pdf"
    work.mkdir(parents=True)
    blocks = work / "libro.blocks.jsonl"
    write_blocks([], Metadata("x"), blocks)
    (tmp_path / "file_inbox").mkdir()
    assert sm.find_blocks(tmp_path / "file_inbox" / "libro.pdf") == blocks
    assert sm.find_blocks(work) == blocks
    assert sm.find_blocks(blocks) == blocks
    with pytest.raises(sm.SummarizeError, match="no blocks file"):
        sm.find_blocks(tmp_path)
    assert sm.default_out_dir(blocks) == tmp_path / "file_outbox"
    assert sm.default_out_dir(tmp_path / "x.blocks.jsonl") == tmp_path
    node = sm.Node("x", 1, number=21)
    assert sm.summary_name("libro", 1, [node]) == "libro.summary-1-s21"
    assert sm.summary_name("libro", "all", []) == "libro.summary-all"


@pytest.mark.parametrize("order", [[7, 5], [5, 7], [8, 3, 6]])
def test_plan_sorted_without_nested_duplicates(book, order):
    outline = sm.load_outline(book(example_tree()))
    plan = sm._plan(outline, sm.select(outline, order), "all")
    titles = [node.title for node, _, _ in plan]
    assert titles == sorted(set(titles), key=[n.title for n in outline.nodes()].index)


def test_heading_with_its_own_text_is_no_echo(book):
    path = book(
        [
            Heading("Capítulo 1", 1),
            Paragraph(words(150)),
            Heading("Capítulo 1", 1),
            Paragraph(words(300)),
        ]
    )
    assert [n.title for n in sm.load_outline(path).nodes()] == ["Capítulo 1", "Capítulo 1"]


def test_quota_stop_with_fresh_says_run_without_fresh(book, tmp_path):
    outline = sm.load_outline(book([Heading("Uno", 1), Paragraph(words(100))]))

    def quota(user, n):
        raise sm.SummarizeError("quota")

    for fresh, said in [(False, "run again to continue"), (True, "run again without --fresh")]:
        with pytest.raises(sm.SummarizeError, match=said):
            sm.summarize(
                outline, outline.root.children, 0, FakeChat(quota), tmp_path / "c.json", fresh=fresh
            )


def test_node_text_over_the_limit_is_split_before_the_merge(book, tmp_path):
    blocks = [Heading("Uno", 1), *[Paragraph(words(100, f"p{i}")) for i in range(3)]]
    outline = sm.load_outline(book([*blocks, Heading("1.1 A", 2), Paragraph(words(10))]))
    chat = FakeChat(context=150)
    sm.summarize(outline, outline.root.children, 0, chat, tmp_path / "c.json")
    assert len(chat.calls) == 4  # three pieces of its own text, then the merge
    assert all(len(call.split()) < 250 for call in chat.calls)


def test_find_whole_words_and_unicode_forms():
    assert sm._find("observar el ser", "ser") == (12, 15)
    assert sm._find("observar", "ser") is None
    assert sm._find("Crédito  vivo", "CRÉDITO") == (0, 8)
    assert sm._find("el crédito", "crédito") == (3, 10)


def test_short_part_quote_has_no_introduction_label(book, tmp_path):
    path = book([Heading("Dos", 1), Paragraph("Intro corta."), Heading("D", 2), Paragraph("Poco.")])
    outline = sm.load_outline(path)
    blocks = sm.summarize(outline, outline.root.children, "all", FakeChat(), tmp_path / "c.json")
    assert blocks[2:] == [Paragraph("Intro corta."), Paragraph("Poco.")]


def test_model_chat_daily_429_message_is_the_quota_and_transient_failures_retry(monkeypatch):
    class Daily(FakeClient):
        def chat(self, user, system, model, fallbacks, **options):
            raise AIClientError("429 free-models-per-day limit exceeded", status=429)

    monkeypatch.setattr(sm.ai_client, "get_client", lambda name: Daily())
    with pytest.raises(sm.SummarizeError, match="daily quota"):
        sm.ModelChat()("s", "u")

    class Flaky(FakeClient):
        def chat(self, user, system, model, fallbacks, **options):
            self.sent.append(model)
            if len(self.sent) == 1:
                raise AIClientError("timeout", status=503)
            return "ok"

    client = Flaky()
    monkeypatch.setattr(sm.ai_client, "get_client", lambda name: client)
    assert sm.ModelChat()("s", "u") == ("ok", "a")
    assert client.sent == ["a", "a"]


def test_exact_numbering_in_a_path(book):
    path = book([Heading(t, 1) for t in ("1. Uno", "10. Diez", "11. Once")])
    outline = sm.load_outline(path)
    assert [n.title for n in sm.select(outline, ["1."])] == ["1. Uno"]
    assert [n.title for n in sm.select(outline, ["10."])] == ["10. Diez"]
