import os
import zipfile

import pymupdf

from pdf_worker import epub_mimetype, inbox
from pdf_worker.convert import convert_pdf

TEXT = ["Chapter One\n\nIt was a quiet morning in the village.", "The end of the story."]


def test_born_digital_pdf_and_epub_are_finished_in_one_run(make_pdf, tmp_path):
    root = tmp_path / "root"
    (root / inbox.INBOX).mkdir(parents=True)
    pdf = make_pdf(TEXT)
    epub = tmp_path / "book.epub"
    convert_pdf(pdf, epub, "epub", title="Book", author="A. Writer", language="en")
    _mimetype_last(epub, root / inbox.INBOX / "book.epub")
    os.replace(pdf, root / inbox.INBOX / "sample.pdf")
    (root / inbox.INBOX / "notes.docx").write_text("not a book")

    results = {r.name: r.state for r in inbox.process(root)}

    assert results == {"book.epub": "finished", "notes.docx": "skipped", "sample.pdf": "finished"}
    out = root / inbox.OUTBOX
    assert sorted(p.name for p in out.iterdir()) == [
        "book.epub",
        "book.pdf",
        "drafts",
        "sample.epub",
        "sample.pdf",
    ]
    assert epub_mimetype.problem(out / "book.epub") is None
    assert epub_mimetype.problem(out / "sample.epub") is None
    # Every EPUB has its contents as a page; an EPUB input's PDF is laid out like a
    # converted PDF's: a contents page with links (after the cover) and an outline.
    for stem in ("book", "sample"):
        with zipfile.ZipFile(out / f"{stem}.epub") as z:
            assert '<itemref idref="nav"/>' in z.read("OEBPS/content.opf").decode()
    with pymupdf.open(out / "book.pdf") as pdf:
        assert pdf.get_toc()
        assert any(link["kind"] == pymupdf.LINK_GOTO for link in pdf[1].get_links())
    assert sorted(p.name for p in (root / inbox.WORK / inbox.CONVERTED).iterdir()) == [
        "book.epub",
        "sample.pdf",
    ]
    assert [p.name for p in (root / inbox.INBOX).iterdir()] == ["notes.docx"]


def test_book_to_review_waits_in_drafts_until_reviewed(make_pdf, tmp_path, monkeypatch):
    monkeypatch.setattr(inbox.review, "open_rows", lambda fixes: ["row"])
    root = tmp_path / "root"
    (root / inbox.INBOX).mkdir(parents=True)
    os.replace(make_pdf(TEXT), root / inbox.INBOX / "sample.pdf")
    drafts, work = root / inbox.OUTBOX / inbox.DRAFTS, root / inbox.WORK / "sample.pdf"

    [first] = inbox.process(root)
    assert first.state == "draft"
    assert sorted(p.name for p in drafts.iterdir()) == ["sample.epub", "sample.pdf"]
    assert (root / inbox.INBOX / "sample.pdf").exists()

    [second] = inbox.process(root)  # no decisions saved since the draft
    assert second.state == "waiting"

    fixes = work / "sample.fixes.tsv"  # what `review` does when it saves decisions
    fixes.write_text("id\n")
    later = (work / inbox.DRAFT_MARK).stat().st_mtime + 10
    os.utime(fixes, (later, later))
    [third] = inbox.process(root)

    assert third.state == "finished"
    assert "1 row(s) to review left undecided" in third.detail
    assert "grade " in third.detail
    assert "**Grade" in (work / "report.md").read_text()
    assert "Text: the PDF's own text layer" in (work / "report.md").read_text()
    assert list(drafts.iterdir()) == []
    assert (root / inbox.OUTBOX / "sample.epub").exists()
    assert (root / inbox.WORK / inbox.CONVERTED / "sample.pdf").exists()
    assert not (work / inbox.DRAFT_MARK).exists()


def test_one_book_with_its_formats_kept_for_the_rebuild(make_pdf, tmp_path, monkeypatch):
    monkeypatch.setattr(inbox.review, "open_rows", lambda fixes: ["row"])
    root = tmp_path / "root"
    (root / inbox.INBOX).mkdir(parents=True)
    os.replace(make_pdf(TEXT), root / inbox.INBOX / "other.pdf")
    book = make_pdf(TEXT, name="sample.pdf")

    settings = {"formats": ["md", "searchable"], "title": "My Title"}
    [first] = inbox.process(root, book=book, settings=settings)

    assert first.state == "draft"
    assert book.exists()  # copied, not moved
    drafts = root / inbox.OUTBOX / inbox.DRAFTS
    assert sorted(p.name for p in drafts.iterdir()) == ["sample.md", "sample.searchable.pdf"]
    assert "My Title" in (drafts / "sample.md").read_text()
    work = root / inbox.WORK / "sample.pdf"
    fixes = work / "sample.fixes.tsv"
    fixes.write_text("id\n")
    later = (work / inbox.DRAFT_MARK).stat().st_mtime + 10
    os.utime(fixes, (later, later))

    [second] = inbox.process(root, book=root / inbox.INBOX / "sample.pdf")  # no settings now

    assert second.state == "finished"
    out = root / inbox.OUTBOX
    assert sorted(p.name for p in out.iterdir()) == ["drafts", "sample.md", "sample.searchable.pdf"]
    assert (root / inbox.INBOX / "other.pdf").exists()  # not processed


def test_clean_keeps_the_inbox_books_and_the_finished_files(tmp_path):
    root = tmp_path / "root"
    work, outbox = root / inbox.WORK, root / inbox.OUTBOX
    for folder in (root / inbox.INBOX, work / "waiting.pdf", work / "done.pdf",
                   work / inbox.CONVERTED, outbox / inbox.DRAFTS):  # fmt: skip
        folder.mkdir(parents=True)
    for path in (root / inbox.INBOX / "waiting.pdf", work / "waiting.pdf" / "waiting.pdf",
                 work / "done.pdf" / "done.pdf", work / inbox.CONVERTED / "done.pdf",
                 outbox / inbox.DRAFTS / "waiting.epub", outbox / inbox.DRAFTS / "gone.epub",
                 outbox / "done.epub"):  # fmt: skip
        path.write_text("x")

    found = inbox.cleanable(root)
    inbox.clean(found)

    assert found == [
        work / "converted" / "done.pdf",
        work / "done.pdf",
        outbox / inbox.DRAFTS / "gone.epub",
    ]
    left = sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())
    assert left == [
        "file_inbox/waiting.pdf",
        "file_outbox/done.epub",
        "file_outbox/drafts/waiting.epub",
        "file_work/waiting.pdf/waiting.pdf",
    ]


def _mimetype_last(epub, out):
    """A copy of ``epub`` with its mimetype entry moved to the end, as some tools write it."""
    with zipfile.ZipFile(epub) as z, zipfile.ZipFile(out, "w") as o:
        infos = sorted(z.infolist(), key=lambda i: i.filename == "mimetype")
        for info in infos:
            o.writestr(info, z.read(info))
    assert epub_mimetype.problem(out)
