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


def test_extract_text_reports_errors_without_traceback(tmp_path, capsys):
    exit_code = main(["extract-text", str(tmp_path / "missing.pdf")])

    assert exit_code == 1
    assert capsys.readouterr().err.startswith("Error:")
