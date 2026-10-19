"""Check a file or a URL for malware with VirusTotal (API v3).

The key is ``VIRUS_TOTAL_API_KEY``, from the environment or a ``.env`` file in the
current folder. A file is looked up by its SHA-256, so nothing is uploaded unless asked:
an uploaded file is shared with VirusTotal's partners. A URL is checked by VirusTotal
itself (it fetches the link); when the link serves a file, that file's verdict is added.
The free key allows 4 requests a minute, so waiting for an analysis polls slowly.
"""

import base64
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path

from pdf_worker import groq
from pdf_worker.errors import PdfWorkerError

API_URL = "https://www.virustotal.com/api/v3"
GUI_URL = "https://www.virustotal.com/gui"
KEY_VARIABLE = "VIRUS_TOTAL_API_KEY"
SMALL_UPLOAD = 32 * 1024 * 1024  # bigger files need a one-off upload URL
POLL_SECONDS = 20
POLL_LIMIT = 30  # 10 minutes


class VirusTotalError(PdfWorkerError):
    pass


@dataclass
class Report:
    target: str
    stats: dict[str, int] | None  # None: VirusTotal doesn't know it
    link: str = ""

    @property
    def verdict(self) -> str:
        if self.stats is None:
            return "unknown"
        if self.stats.get("malicious", 0):
            return "malicious"
        return "suspicious" if self.stats.get("suspicious", 0) else "clean"


def api_key(env_file: Path = Path(".env")) -> str:
    key = groq.api_key(env_file, KEY_VARIABLE)
    if not key:
        raise VirusTotalError(f"No VirusTotal key: set {KEY_VARIABLE} in the environment or .env.")
    return key


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def url_id(url: str) -> str:
    return base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")


def _request(key: str, url: str, data: bytes | None = None, content_type: str = "") -> dict | None:
    """The JSON answer, or None for 404 (not known to VirusTotal)."""
    headers = {"x-apikey": key, "accept": "application/json"}
    if content_type:
        headers["content-type"] = content_type
    url = url if url.startswith("http") else API_URL + url
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data, headers), timeout=300) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        if e.code == 401:
            raise VirusTotalError("VirusTotal rejected the API key.") from e
        if e.code == 429:
            raise VirusTotalError("VirusTotal quota used up (free key: 4/minute, 500/day).") from e
        raise VirusTotalError(f"VirusTotal answered {e.code} {e.reason}.") from e
    except urllib.error.URLError as e:
        raise VirusTotalError(f"Could not reach VirusTotal: {e.reason}") from e


def _wait(key: str, analysis_id: str) -> None:
    for _ in range(POLL_LIMIT):
        answer = _request(key, f"/analyses/{analysis_id}") or {}
        if answer.get("data", {}).get("attributes", {}).get("status") == "completed":
            return
        time.sleep(POLL_SECONDS)
    raise VirusTotalError("VirusTotal's analysis did not finish in 10 minutes; try again later.")


def _file_report(key: str, digest: str, target: str) -> Report:
    answer = _request(key, f"/files/{digest}")
    stats = answer["data"]["attributes"].get("last_analysis_stats") if answer else None
    return Report(target, stats, f"{GUI_URL}/file/{digest}" if answer else "")


def check_file(path: Path, key: str, upload: bool = False) -> Report:
    """Look the file up by hash; with ``upload``, send an unknown file and wait."""
    if not path.is_file():
        raise VirusTotalError(f"No such file: {path}")
    digest = sha256(path)
    report = _file_report(key, digest, str(path))
    if report.stats is not None or not upload:
        return report
    target = "/files"
    if path.stat().st_size > SMALL_UPLOAD:
        target = _request(key, "/files/upload_url")["data"]
    boundary = uuid.uuid4().hex
    # shortcut: the body is built in memory (VirusTotal's limit is 650 MB), stream it if that hurts
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n".encode()
        + path.read_bytes()
        + f"\r\n--{boundary}--\r\n".encode()
    )
    answer = _request(key, target, body, f"multipart/form-data; boundary={boundary}")
    _wait(key, answer["data"]["id"])
    return _file_report(key, digest, str(path))


def check_url(url: str, key: str) -> list[Report]:
    """The URL's verdict, plus the served file's when VirusTotal fetched one."""
    answer = _request(key, f"/urls/{url_id(url)}")
    if answer is None:
        posted = _request(
            key,
            "/urls",
            urllib.parse.urlencode({"url": url}).encode(),
            "application/x-www-form-urlencoded",
        )
        _wait(key, posted["data"]["id"])
        answer = _request(key, f"/urls/{url_id(url)}")
        if answer is None:
            raise VirusTotalError("VirusTotal finished the analysis but has no report for the URL.")
    attributes = answer["data"]["attributes"]
    reports = [Report(url, attributes.get("last_analysis_stats"), f"{GUI_URL}/url/{url_id(url)}")]
    content = attributes.get("last_http_response_content_sha256")
    if content:
        reports.append(_file_report(key, content, "file served by the URL"))
    return reports
