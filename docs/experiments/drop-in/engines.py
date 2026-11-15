"""Convert a PDF to Markdown with a candidate engine (drop-in experiment, step S7).

Run with the engines venv, not the repo's:
  scratch/drop-in/venv-engines/bin/python docs/experiments/drop-in/engines.py \
      {docling,mineru} PDF OUT.md [--pages FIRST-LAST]

Pages are 1-based and inclusive; without --pages the whole book. Caches, weights and
MinerU's state live under scratch/drop-in/engines/home, never in ~.
"""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HOME = ROOT / "scratch" / "drop-in" / "engines" / "home"
HOME.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MINERU_HOME", str(HOME / "mineru"))
os.environ.setdefault("HF_HOME", str(HOME / "hf"))
os.environ.setdefault("XDG_CACHE_HOME", str(HOME / "cache"))
BIN = Path(sys.executable).parent


def _span(pages: str | None) -> tuple[int, int]:
    if not pages:
        return 1, sys.maxsize
    first, last = pages.split("-")
    return int(first), int(last)


def docling(pdf: Path, pages: str | None) -> str:
    from docling.document_converter import DocumentConverter

    result = DocumentConverter().convert(pdf, page_range=_span(pages))
    return result.document.export_to_markdown()


def mineru(pdf: Path, pages: str | None) -> str:
    cli = str(BIN / "mineru")
    out = HOME / "mineru-out.md"
    out.unlink(missing_ok=True)
    subprocess.run([str(BIN / "mineru-models-download"), "--tier", "basic"], check=True)
    subprocess.run([cli, "server", "start"], check=True)
    try:
        for key, value in [
            ("parse_server.local.managed_tier", "basic"),
            ("parse_server.local.mode", "managed"),
        ]:
            subprocess.run([cli, "config", "set", key, value], check=True)
        command = [
            cli,
            "parse",
            str(pdf),
            "--pages",
            pages or "all",
            "--wait",
            "86400",
            "--no-marker",
            "-o",
            str(out),
        ]
        for _ in range(20):  # the managed parse server needs ~30 s to come up
            done = subprocess.run(command, capture_output=True, text=True)
            if "engine available" not in done.stderr + done.stdout:
                break
            time.sleep(15)
        print(done.stdout, done.stderr, file=sys.stderr)
        done.check_returncode()
    finally:
        subprocess.run([cli, "server", "stop"])
    return out.read_text(encoding="utf-8")


ENGINES = {"docling": docling, "mineru": mineru}


def main(argv: list[str]) -> None:
    options = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    options.add_argument("engine", choices=ENGINES)
    options.add_argument("pdf", type=Path)
    options.add_argument("out", type=Path)
    options.add_argument("--pages")
    args = options.parse_args(argv)
    text = ENGINES[args.engine](args.pdf.resolve(), args.pages)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.out.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, args.out)


if __name__ == "__main__":
    main(sys.argv[1:])
