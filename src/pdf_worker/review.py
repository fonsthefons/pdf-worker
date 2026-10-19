"""Review the open rows of a book's review file on a local web page.

For each spelling or odd-character row still to decide, the page shows the scan line
(cut from the PDF where the Paddle OCR cache places the word), the text around it, and
a model's suggestion (Groq, text only: no images are sent). The page is served on
127.0.0.1; its Export button merges the decisions into ``<stem>.fixes.tsv`` (after a
backup), and the next ``convert`` applies them. Note and margin rows stay in the TSV.

Files go in ``<stem>.review/`` next to the PDF: the crops and ``proposals.jsonl`` (the
model's answers, so rows already asked about are never sent again).
"""

import base64
import csv
import difflib
import html
import io
import json
import re
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pymupdf

from pdf_worker import paddle_ocr
from pdf_worker.errors import PdfWorkerError
from pdf_worker.fixes import Fix, default_fixes_path, read_fixes, write_fixes
from pdf_worker.mixed_script import _tsv
from pdf_worker.ocr import available_languages, tesseract_path

KINDS = ("spelling", "chars")
ACTIONS = {"replace", "ignore", "attach", "drop", "accept", "move", "add"}
PORT = 8765  # fixed: the browser keeps the page's choices per address
BATCH = 25  # rows per model request: prompt and answer fit Groq's 8000-token budget
DPI = 200
CONTEXT = 150  # characters of scan text each side of the word
MAX_WIDTH = 900  # px of line kept around the word


def review_folder(pdf: Path) -> Path:
    return pdf.with_name(default_fixes_path(pdf).name.removesuffix(".fixes.tsv") + ".review")


def open_rows(fixes: list[Fix]) -> list[Fix]:
    """Undecided rows still found in the text, and replacements that no longer apply."""
    return [
        f
        for f in fixes
        if f.kind in KINDS
        and (
            (not f.action and f.status != "stale")
            or (f.action == "replace" and f.status == "stale")
        )
    ]


def packets(pdf: Path, rows: list[Fix], folder: Path) -> list[dict]:
    """One dict per row: the row, wider context and a crop (PNG path) from the scan."""
    scan = paddle_ocr._read_rows(paddle_ocr._pages_cache(pdf))
    pages = _page_index(scan)
    try:
        tesseract = tesseract_path()
        language = "spa" if "spa" in available_languages() else "eng"
    except PdfWorkerError:  # no Tesseract: no crops, but still a review
        tesseract = language = ""
    (folder / "crops").mkdir(parents=True, exist_ok=True)
    result = []
    with pymupdf.open(pdf) as doc:
        for fix in rows:
            page = scan.get(pages.get(fix.page, -1))
            block = page and next(
                (
                    b
                    for b in page["blocks"]
                    if fix.find in b.get("text", "") and len(b.get("bbox", [])) == 4
                ),
                None,
            )
            png = folder / "crops" / f"{fix.id}.png"
            if block and tesseract and not png.exists():
                _crop(doc, page, block, fix.find, png, tesseract, language)
            context = fix.context
            if block:
                text = block["text"]
                middle = text.find(fix.find) + len(fix.find) // 2
                context = " ".join(text[max(0, middle - CONTEXT) : middle + CONTEXT].split())
            result.append(
                {
                    **asdict(fix),
                    "prefill": fix.value,
                    "context": context,
                    "crop": str(png) if png.exists() else "",
                }
            )
    return result


def _page_index(scan: dict[int, dict]) -> dict[str, int]:
    """Printed page label -> PDF page index, as the Paddle build labels pages."""
    labels: dict[str, int] = {}
    for page, row in sorted(scan.items()):
        number = next((b["text"].strip() for b in row["blocks"] if b.get("label") == "number"), "")
        labels.setdefault(number if number.isdigit() else str(page + 1), page)
    return labels


def _crop(doc, row: dict, block: dict, find: str, out: Path, tesseract: str, language: str):
    """Save the scan line holding ``find`` (the whole block when Tesseract can't place it)."""
    page = doc.load_page(row["page"])
    sx = page.rect.width / (row.get("width") or page.rect.width)
    sy = page.rect.height / (row.get("height") or page.rect.height)
    x0, y0, x1, y1 = block["bbox"]
    rect = pymupdf.Rect(x0 * sx, y0 * sy, x1 * sx, y1 * sy) + (-3, -3, 3, 3)
    words = _tsv(page.get_pixmap(dpi=DPI, clip=rect).tobytes("png"), tesseract, language)
    target = (find.split() or [find])[0]
    best = max(words, key=lambda w: _similar(w.text, target), default=None)
    if best is not None and _similar(best.text, target) >= 0.5:
        line = [w.box for w in words if w.line == best.line]
        centre = (best.box[0] + best.box[2]) / 2
        lx0 = max(min(b[0] for b in line), centre - MAX_WIDTH / 2)
        lx1 = min(max(b[2] for b in line), centre + MAX_WIDTH / 2)
        ly0, ly1 = min(b[1] for b in line), max(b[3] for b in line)
        scale = 72 / DPI
        rect = pymupdf.Rect(
            rect.x0 + (lx0 - 8) * scale,
            rect.y0 + (ly0 - 3) * scale,
            rect.x0 + (lx1 + 8) * scale,
            rect.y0 + (ly1 + 3) * scale,
        )
    page.get_pixmap(dpi=DPI, clip=rect).save(out)


def _similar(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


# --- Model suggestions ----------------------------------------------------------------

PROMPT = """You review OCR errors in a scanned book. Each row is a word the spell checker
flagged ("spelling") or a word with odd characters ("chars"), with the text around it as
the OCR read it. For each row decide:
- "replace": the OCR misread the word; "value" is the word as PRINTED in the book (keep
  its case; you may fix a word split by a line break by giving the joined word only if
  "find" is just one part of it: then value is that part corrected, never the whole
  phrase).
- "ignore": the word is printed like this (a name, a foreign or old word, a correct
  word the dictionary lacks); "value" is "".
Propose the printed word, not a plausible one: you do not see the scan. OCR misreads a
few letters, so the printed word shares most letters with "find" ("Cprk" is "Cork",
not "Cambridge"). If the context does not decide between readings (e.g. "Gual" vs
"cual" is clear, but two real words are possible), give confidence "low". "type" is a
hint from a rule ("accent": one accent off, the fix is in "prefill"; "ocr1: x?": one
letter off, x is only a guess).
Answer with one JSON object: {"rows": [{"id": "...", "action": "replace"|"ignore",
"value": "...", "confidence": "high"|"medium"|"low", "reason": "one short line"}]},
one entry per input row, same ids. No other text."""


def read_proposals(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    lines = path.read_text(encoding="utf-8").splitlines()
    return {p["id"]: p for p in map(json.loads, filter(None, lines))}


def propose(
    rows: list[dict], path: Path, generate: Callable[[str, str], str], on_batch=None
) -> Counter:
    """Ask the model about the rows it hasn't answered yet; append its answers to ``path``.

    ``generate(system, user)`` returns the model's text. A batch whose answer can't be
    read is skipped (asked again next time); other errors stop the pass."""
    done = read_proposals(path)
    todo = [r for r in rows if r["id"] not in done]
    counts: Counter = Counter()
    with path.open("a", encoding="utf-8") as out:
        for start in range(0, len(todo), BATCH):
            batch = todo[start : start + BATCH]
            keys = ("id", "kind", "type", "find", "prefill", "context")
            batch_json = json.dumps([{k: r[k] for k in keys} for r in batch], ensure_ascii=False)
            answer = generate(PROMPT, batch_json)
            try:
                answer = re.sub(r"^```(?:json)?|```$", "", answer.strip()).strip()
                answers = {str(a.get("id")): a for a in json.loads(answer)["rows"]}
            except (ValueError, KeyError, TypeError, AttributeError):
                counts["unreadable batches"] += 1
                continue
            for row in batch:
                proposal = answers.get(row["id"])
                if proposal is None:
                    counts["missing"] += 1
                    continue
                ok = _valid(proposal, row)
                counts["suggested" if ok else "invalid"] += 1
                confidence = proposal.get("confidence", "") if ok else ""
                value = (proposal.get("value") or "") if ok else ""
                if ok and proposal["action"] == "replace" and _similar(row["find"], value) < 0.6:
                    confidence = "low"  # OCR misreads a few letters, not a whole word
                record = {
                    "id": row["id"],
                    "action": proposal["action"] if ok else "",
                    "value": value,
                    "confidence": confidence,
                    "reason": str(proposal.get("reason", ""))[:200],
                }
                out.write(json.dumps(record, ensure_ascii=False) + "\n")
                out.flush()
            if on_batch:
                on_batch(min(start + BATCH, len(todo)), len(todo))
    return counts


def _valid(proposal: dict, row: dict) -> bool:
    action, value = proposal.get("action"), proposal.get("value") or ""
    if action not in ("replace", "ignore") or proposal.get("confidence") not in (
        "high",
        "medium",
        "low",
    ):
        return False
    return action == "ignore" or (bool(value.strip()) and value != row["find"])


# --- The page and its server ----------------------------------------------------------


def page_html(title: str, rows: list[dict], proposals: dict[str, dict]) -> str:
    items = []
    for row in rows:
        p = proposals.get(row["id"], {})
        crop = row["crop"] and Path(row["crop"]).read_bytes()
        items.append(
            {
                **{k: row[k] for k in ("id", "page", "kind", "type", "find", "prefill", "context")},
                "action": row["action"],
                "value": row["prefill"] if row["action"] else "",
                # Embedded, so the page needs nothing else from the disk.
                "crop": crop and "data:image/png;base64," + base64.b64encode(crop).decode(),
                "proposal_action": p.get("action", ""),
                "proposal_value": p.get("value", ""),
                "confidence": p.get("confidence", ""),
                "reason": p.get("reason", ""),
            }
        )
    template = (Path(__file__).parent / "review_page.html").read_text(encoding="utf-8")
    # "</" inside the JSON would end the script element.
    script = {"__ROWS__": items, "__STEM_JSON__": title}
    for key, value in script.items():
        template = template.replace(
            key, json.dumps(value, ensure_ascii=False).replace("</", "<\\/")
        )
    return template.replace("__TITLE__", html.escape(title))


def merge(fixes_path: Path, decisions_tsv: str, backup_folder: Path) -> Counter:
    """Set action/value (and a widened find) of each decided row; back the file up first."""
    backup = backup_folder / f"{fixes_path.stem}.{time.strftime('%Y%m%d-%H%M%S')}.tsv"
    backup.write_bytes(fixes_path.read_bytes())
    fixes = read_fixes(fixes_path)
    by_id = {fix.id: fix for fix in fixes}
    counts: Counter = Counter()
    for d in csv.DictReader(io.StringIO(decisions_tsv), delimiter="\t"):
        fix = by_id.get((d.get("id") or "").strip())
        action, value = (d.get("action") or "").strip(), (d.get("value") or "").strip()
        if fix is None or action not in ACTIONS or (action == "replace" and not value):
            counts["skipped"] += 1
            continue
        # A widened find covers a word split in two ("def niciones" -> "definiciones").
        find = (d.get("find") or "").strip() if action == "replace" else ""
        fix.find, fix.action, fix.value = find or fix.find, action, value
        counts[action] += 1
    write_fixes(fixes_path, fixes)
    return counts


def serve(page: str, on_decisions: Callable[[str], str], port: int = PORT) -> ThreadingHTTPServer:
    """A server on 127.0.0.1 for the page; a POST of decisions.tsv calls ``on_decisions``
    with its text and sends back what it returns. Call ``serve_forever()`` on it."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path not in ("/", "/review.html"):
                self.send_error(404)
                return
            self._reply(page, "text/html; charset=utf-8")

        def do_POST(self):
            size = int(self.headers.get("Content-Length") or 0)
            if self.path != "/decisions.tsv" or not 0 < size < 10_000_000:
                self.send_error(400)
                return
            try:
                message = on_decisions(self.rfile.read(size).decode("utf-8"))
            except (OSError, UnicodeDecodeError) as exc:
                self.send_error(500, str(exc))
                return
            self._reply(message, "text/plain; charset=utf-8")

        def _reply(self, text: str, kind: str):
            body = text.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)
