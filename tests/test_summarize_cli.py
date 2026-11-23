from types import SimpleNamespace

import pytest
from test_summarize import FakeChat, book, example_tree  # noqa: F401  (book is a fixture)

from pdf_worker import cli
from pdf_worker import summarize as sm
from pdf_worker.cli import main


class CliChat(FakeChat):
    def __init__(self, model=None, left=100, key="k"):
        super().__init__()
        self.client = SimpleNamespace(key=key)
        self.left = left

    def requests_left(self):
        return self.left


@pytest.fixture
def chat(monkeypatch):
    made = []

    def make(model=None):
        made.append(CliChat(model))
        return made[0]

    monkeypatch.setattr(sm, "ModelChat", make)
    return made


def terminal(monkeypatch, answers):
    monkeypatch.setattr("sys.stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr("sys.stdout.isatty", lambda: True, raising=False)
    given = iter(answers)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(given))


def test_parser_options():
    args = cli.build_parser().parse_args(
        ["summarize", "b", "--section", "7", "--section", "II. > 1.", "--level", "all",
         "--detail", "brief", "--keep-bold", "--skip", "x", "--to", "md"]
    )  # fmt: skip
    assert (args.section, args.level, args.detail, args.keep_bold, args.skip, args.to) == (
        ["7", "II. > 1."], "all", "brief", True, ["x"], ["md"],
    )  # fmt: skip
    assert cli.build_parser().parse_args(["summarize", "b", "--level", "2"]).level == 2
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["summarize", "b", "--level", "x"])


def test_outline_prints_tree_and_estimates_without_sending(book, capsys, chat):  # noqa: F811
    path = book(example_tree())
    assert main(["summarize", str(path), "--outline"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("   1  1 Uno  (300 words")
    assert out[1].startswith("   2    1.1 A  (100 words")
    assert out[-1].startswith("requests at most: level 0 4, level 1 4, level 2 8, level 3 10")
    assert out[-1].endswith(", all 10")
    assert not chat


def test_non_terminal_summarizes_whole_book_at_level_0(book, tmp_path, capsys, chat):  # noqa: F811
    path = book(example_tree())
    out_dir = tmp_path / "out"
    assert main(["summarize", str(path), "--out-dir", str(out_dir), "--to", "md"]) == 0
    captured = capsys.readouterr()
    assert (out_dir / "libro.summary-0.blocks.jsonl").exists()
    assert f"Wrote {out_dir / 'libro.summary-0.md'}" in captured.out
    assert "[2/4] 2 Dos" in captured.err
    assert (tmp_path / "libro.summaries.json").exists()


def test_section_and_level_options(book, tmp_path, chat):  # noqa: F811
    path = book(example_tree())
    out_dir = tmp_path / "out"
    argv = ["summarize", str(path), "--section", "2", "--level", "1", "--to", "md"]
    assert main([*argv, "--out-dir", str(out_dir)]) == 0
    assert (out_dir / "libro.summary-1-s2.md").exists()


def test_interactive_flow_retries_invalid_answers(book, tmp_path, capsys, chat, monkeypatch):  # noqa: F811
    path = book(example_tree())
    terminal(monkeypatch, ["99", "2", "x", "1", "huge", "brief", "maybe", "y", ""])
    out_dir = tmp_path / "out"
    assert main(["summarize", str(path), "--out-dir", str(out_dir), "--to", "md"]) == 0
    out = capsys.readouterr().out
    assert "no part 99" in out and " requests; 100 left today." in out
    assert (out_dir / "libro.summary-1-s2.md").exists()


def test_interactive_declined_and_warning(book, tmp_path, capsys, chat, monkeypatch):  # noqa: F811
    path = book(example_tree())
    monkeypatch.setattr(sm, "ModelChat", lambda model=None: CliChat(model, left=1))
    terminal(monkeypatch, ["", "all", "", "", "n"])
    assert main(["summarize", str(path), "--out-dir", str(tmp_path / "out")]) == 0
    assert "WARNING" in capsys.readouterr().out
    assert not (tmp_path / "out").exists()


def test_zero_requests_left_warns_and_given_options_are_not_asked(
    book, tmp_path, capsys, monkeypatch  # noqa: F811
):
    path = book(example_tree())
    monkeypatch.setattr(sm, "ModelChat", lambda model=None: CliChat(model, left=0))
    terminal(monkeypatch, ["", "all", "n"])  # sections, level, go: no detail / bold question
    args = ["summarize", str(path), "--detail", "brief", "--keep-bold", "--out-dir", str(tmp_path)]
    assert main(args) == 0
    assert "WARNING" in capsys.readouterr().out


def test_missing_key_and_unknown_format(book, capsys, monkeypatch):  # noqa: F811
    path = book(example_tree())
    monkeypatch.setattr(sm, "ModelChat", lambda model=None: CliChat(key=""))
    assert main(["summarize", str(path)]) == 1
    assert "OPENROUTER_API_KEY" in capsys.readouterr().err
    assert main(["summarize", str(path), "--to", "mobi"]) == 1
    assert "unknown format" in capsys.readouterr().err
