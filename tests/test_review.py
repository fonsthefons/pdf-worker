import json
import threading
import urllib.error
import urllib.request

from pdf_worker import review
from pdf_worker.fixes import Fix, read_fixes, write_fixes


def fix(id_, kind="spelling", find="becho", **kwargs):
    return Fix(id=id_, page="12", kind=kind, find=find, context=f"un {find} raro", **kwargs)


def test_open_rows_are_undecided_found_words_and_stuck_replacements():
    fixes = [
        fix("1"),
        fix("2", status="stale"),  # gone from the text
        fix("3", action="ignore", status="applied"),
        fix("4", action="replace", value="hecho", status="stale"),  # didn't apply
        fix("5", kind="note-no-ref"),  # notes stay in the TSV
    ]

    assert [f.id for f in review.open_rows(fixes)] == ["1", "4"]


def packet(id_, find="becho"):
    return {
        "id": id_,
        "kind": "spelling",
        "type": "ocr1",
        "find": find,
        "prefill": "",
        "context": "",
    }


def test_propose_keeps_valid_answers_and_never_asks_twice(tmp_path):
    path = tmp_path / "proposals.jsonl"
    sent = []

    def generate(system, user):
        rows = json.loads(user)
        sent.append([r["id"] for r in rows])
        answers = {
            "1": {"action": "replace", "value": "hecho", "confidence": "high"},
            "2": {"action": "replace", "value": "Cambridge", "confidence": "high"},  # far
            "3": {"action": "maybe", "confidence": "high"},
        }
        return (
            "```json\n"
            + json.dumps({"rows": [answers[r["id"]] | {"id": r["id"]} for r in rows]})
            + "\n```"
        )

    rows = [packet("1"), packet("2", "Cprk"), packet("3")]
    counts = review.propose(rows, path, generate)
    again = review.propose(rows, path, generate)

    assert sent == [["1", "2", "3"]] and not again
    assert counts == {"suggested": 2, "invalid": 1}
    found = review.read_proposals(path)
    assert (found["1"]["value"], found["1"]["confidence"]) == ("hecho", "high")
    assert found["2"]["confidence"] == "low"
    assert found["3"]["action"] == ""


def test_propose_skips_an_unreadable_answer_to_ask_again_later(tmp_path):
    path = tmp_path / "proposals.jsonl"

    counts = review.propose([packet("1")], path, lambda system, user: "Sorry, I can't.")

    assert counts == {"unreadable batches": 1} and review.read_proposals(path) == {}


def test_merge_sets_decisions_and_backs_up_the_review_file(tmp_path):
    path = tmp_path / "book.fixes.tsv"
    write_fixes(path, [fix("1"), fix("2"), fix("3", find="def")])
    decisions = (
        "id\taction\tvalue\tfind\n"
        "1\treplace\thecho\t\n"
        "2\tignore\t\t\n"
        "3\treplace\tdefiniciones\tdef niciones\n"
        "9\treplace\tx\t\n"  # unknown row
        "1\treplace\t\t\n"  # a replace with no value
    )

    counts = review.merge(path, decisions, tmp_path)

    assert counts == {"replace": 2, "ignore": 1, "skipped": 2}
    rows = {f.id: (f.find, f.action, f.value) for f in read_fixes(path)}
    assert rows == {
        "1": ("becho", "replace", "hecho"),
        "2": ("becho", "ignore", ""),
        "3": ("def niciones", "replace", "definiciones"),
    }
    [backup] = tmp_path.glob("book.fixes.2*.tsv")
    assert [f.action for f in read_fixes(backup)] == ["", "", ""]


def test_page_holds_the_rows_safely(tmp_path):
    row = {**packet("1", "</script>"), "page": "3", "action": "", "crop": ""}

    page = review.page_html("Mi <libro>", [row], {"1": {"action": "ignore", "confidence": "high"}})

    assert not any(key in page for key in ("__ROWS__", "__TITLE__", "__STEM_JSON__"))
    assert "Mi &lt;libro&gt;" in page and '"Mi <libro>"' in page
    assert "<\\/script>" in page and page.count("</script>") == 1


def test_packets_without_a_scan_cache_keep_the_rows_context(make_pdf, tmp_path, monkeypatch):
    monkeypatch.setenv("PDF_WORKER_PADDLE_CACHE", str(tmp_path / "paddle"))
    pdf = make_pdf(["texto"])

    [row] = review.packets(pdf, [fix("1")], review.review_folder(pdf))

    assert (row["context"], row["crop"], row["prefill"]) == ("un becho raro", "", "")
    assert review.review_folder(pdf).name == "sample.review"


def test_server_shows_the_page_and_hands_over_the_decisions():
    got = []
    server = review.serve("<p>page</p>", lambda tsv: got.append(tsv) or "Saved 1", port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urllib.request.urlopen(base + "/") as response:
            assert response.read() == b"<p>page</p>"
        post = urllib.request.Request(base + "/decisions.tsv", data=b"id\taction\n1\tignore\n")
        with urllib.request.urlopen(post) as response:
            assert response.read() == b"Saved 1"
        assert got == ["id\taction\n1\tignore\n"]
        try:
            urllib.request.urlopen(base + "/../.env")
            raise AssertionError("served a file")
        except urllib.error.HTTPError as error:
            assert error.code == 404
    finally:
        server.shutdown()
        server.server_close()
