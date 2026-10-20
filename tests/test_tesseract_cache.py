import subprocess

from pdf_worker import tesseract_cache


def test_the_same_image_and_arguments_run_tesseract_once(monkeypatch):
    calls = []

    def fake_run(argv, input, capture_output, check):
        calls.append(argv)
        failed = input == b"bad"
        return subprocess.CompletedProcess(argv, 1 if failed else 0, b"" if failed else b"text")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert tesseract_cache.run("tess", ["stdin", "stdout"], b"png") == b"text"
    assert tesseract_cache.run("tess", ["stdin", "stdout"], b"png") == b"text"
    assert len(calls) == 1
    tesseract_cache.run("tess", ["stdin", "stdout", "--psm", "7"], b"png")  # other arguments
    tesseract_cache.run("tess", ["stdin", "stdout"], b"bad")
    tesseract_cache.run("tess", ["stdin", "stdout"], b"bad")  # a failure is not kept
    assert len(calls) == 4
