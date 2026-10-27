from pdf_worker.cli import main


def test_extract_text_writes_next_to_input_by_default(make_pdf, capsys):
    pdf = make_pdf(["hello world"], name="doc.pdf")

    exit_code = main(["extract-text", str(pdf)])

    assert exit_code == 0
    assert "hello world" in pdf.with_suffix(".txt").read_text(encoding="utf-8")
    assert "1 pages" in capsys.readouterr().out


def test_extract_text_honours_output_and_escaped_separator(make_pdf, tmp_path):
    pdf = make_pdf(["a", "b"])
    out = tmp_path / "custom.txt"

    main(["extract-text", str(pdf), "-o", str(out), "--page-separator", r"\n==\n"])

    assert "\n==\n" in out.read_text(encoding="utf-8")


def test_extract_text_warns_about_empty_pages(make_pdf, capsys):
    pdf = make_pdf(["text", ""])

    main(["extract-text", str(pdf)])

    assert "no text layer" in capsys.readouterr().err


def test_help_lists_every_command(capsys):
    assert main(["help"]) == 0

    out = capsys.readouterr().out
    for command in (
        "kindle",
        "convert",
        "extract-text",
        "ocr",
        "find-book",
        "ebook-to-pdf",
        "help",
    ):
        assert f"pdf-worker {command}" in out
    assert "Output goes next to the PDF" in out


def test_no_command_shows_help(capsys):
    assert main([]) == 0

    assert "pdf-worker kindle book.pdf" in capsys.readouterr().out


def test_progress_in_a_log_writes_every_five_percent(capsys):
    from pdf_worker.cli import _progress

    on_page = _progress("OCR")
    for done in range(0, 101):
        on_page(done, 100)

    lines = capsys.readouterr().err.splitlines()
    assert len(lines) == 21
    assert lines[0] == "OCR: 0% (0/100 pages)"
    assert lines[10] == "OCR: 50% (50/100 pages), under a minute left"
    assert lines[-1] == "OCR: 100% (100/100 pages)"


def test_extract_text_reports_errors_without_traceback(tmp_path, capsys):
    exit_code = main(["extract-text", str(tmp_path / "missing.pdf")])

    assert exit_code == 1
    assert capsys.readouterr().err.startswith("Error:")


def _fake_inbox(monkeypatch, tmp_path, states):
    """``inbox.process`` returns one book per call, in the given states."""
    from pdf_worker import inbox

    pdf = tmp_path / "work" / "book.pdf"
    calls = iter(states)
    monkeypatch.setattr(
        inbox,
        "process",
        lambda *a, **k: [
            inbox.BookResult("book.pdf", state, "", pdf if state != "finished" else None)
            for state in [next(calls)]
        ],
    )
    return pdf


def test_process_prints_next_steps_without_a_terminal(monkeypatch, tmp_path, capsys):
    pdf = _fake_inbox(monkeypatch, tmp_path, ["draft"])

    main(["process", str(tmp_path)])

    out = capsys.readouterr().out
    assert f"1. pdf-worker review {pdf}" in out
    assert f"2. pdf-worker process {tmp_path}" in out


def test_process_reviews_and_rebuilds_when_asked(monkeypatch, tmp_path, capsys):
    from pdf_worker import cli

    pdf = _fake_inbox(monkeypatch, tmp_path, ["draft", "finished"])
    reviewed = []
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cli, "_ask_yes", lambda prompt: True)
    monkeypatch.setattr(cli, "_run_review", lambda args: reviewed.append(args.pdf))

    main(["process", str(tmp_path)])

    out = capsys.readouterr().out
    assert reviewed == [pdf]
    assert "finished  book.pdf" in out
    assert "To finish later" not in out


def test_process_review_now_but_rebuild_later(monkeypatch, tmp_path, capsys):
    from pdf_worker import cli

    _fake_inbox(monkeypatch, tmp_path, ["draft"])
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cli, "_ask_yes", lambda prompt: prompt.startswith("Review"))
    monkeypatch.setattr(cli, "_run_review", lambda args: None)

    main(["process", str(tmp_path)])

    out = capsys.readouterr().out
    assert f"1. pdf-worker process {tmp_path}" in out
    assert "pdf-worker review" not in out.split("To finish later")[1]
