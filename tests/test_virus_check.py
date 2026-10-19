import pytest

from pdf_worker import virus_check
from pdf_worker.cli import main


def fake_api(monkeypatch, answers):
    calls = []

    def request(key, url, data=None, content_type=""):
        calls.append(url)
        return answers.get(url.removeprefix(virus_check.API_URL))

    monkeypatch.setattr(virus_check, "_request", request)
    monkeypatch.setattr(virus_check, "POLL_SECONDS", 0)
    return calls


def stats(malicious=0, undetected=60):
    return {
        "data": {
            "attributes": {
                "last_analysis_stats": {"malicious": malicious, "undetected": undetected}
            }
        }
    }


def test_url_id_is_unpadded_base64url():
    assert virus_check.url_id("http://a.b/?x") == "aHR0cDovL2EuYi8_eA"


def test_known_file_is_looked_up_by_hash_without_upload(monkeypatch, tmp_path):
    path = tmp_path / "book.pdf"
    path.write_bytes(b"%PDF-1.4 tiny")
    digest = virus_check.sha256(path)
    calls = fake_api(monkeypatch, {f"/files/{digest}": stats(malicious=3)})

    report = virus_check.check_file(path, "key")

    assert report.verdict == "malicious"
    assert calls == [f"/files/{digest}"]


def test_unknown_file_is_not_uploaded_unless_asked(monkeypatch, tmp_path):
    path = tmp_path / "book.pdf"
    path.write_bytes(b"x")
    calls = fake_api(monkeypatch, {})

    assert virus_check.check_file(path, "key").verdict == "unknown"
    assert len(calls) == 1


def test_url_check_adds_the_served_file(monkeypatch):
    url = "https://example.org/book.pdf"
    answer = stats()
    answer["data"]["attributes"]["last_http_response_content_sha256"] = "abc"
    fake_api(monkeypatch, {f"/urls/{virus_check.url_id(url)}": answer, "/files/abc": stats(1)})

    reports = virus_check.check_url(url, "key")

    assert [r.verdict for r in reports] == ["clean", "malicious"]


def test_cli_exit_code_flags_malware(monkeypatch, tmp_path, capsys):
    path = tmp_path / "book.pdf"
    path.write_bytes(b"y")
    monkeypatch.setenv(virus_check.KEY_VARIABLE, "key")
    fake_api(monkeypatch, {f"/files/{virus_check.sha256(path)}": stats(malicious=2)})

    assert main(["virus-check", str(path)]) == 2
    assert "MALICIOUS" in capsys.readouterr().out


def test_missing_key_is_a_clean_error(monkeypatch, tmp_path):
    monkeypatch.delenv(virus_check.KEY_VARIABLE, raising=False)
    with pytest.raises(virus_check.VirusTotalError):
        virus_check.api_key(tmp_path / ".env")
