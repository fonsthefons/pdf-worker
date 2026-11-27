from pathlib import Path

from control_panel.__main__ import main

UI_JSON = Path(__file__).resolve().parents[1] / "ui.json"


def test_ui_tasks_match_the_cli(capsys):
    """ui.json names real commands and options: fails when the CLI changes under it."""
    code = main(["pdf_worker.cli:build_parser", "--cmd", "pdf-worker", "--tasks", str(UI_JSON), "--check"])
    assert code == 0, capsys.readouterr().err
