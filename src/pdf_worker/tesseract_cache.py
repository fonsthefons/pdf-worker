"""Tesseract's output kept on disk, keyed by the image and the arguments.

A rebuild of a scanned book renders the same pages and crops again and asks Tesseract the
same questions (margin marks, dropped note numbers, Greek words); Paddle's pages are
cached already, so Tesseract was most of a rebuild's time. Folder:
``PDF_WORKER_TESSERACT_CACHE`` (default ``~/.cache/pdf-worker/tesseract``).
"""

import hashlib
import os
import subprocess
import tempfile
from pathlib import Path


def cache_dir() -> Path:
    default = Path.home() / ".cache" / "pdf-worker" / "tesseract"
    return Path(os.environ.get("PDF_WORKER_TESSERACT_CACHE", default))


def run(tesseract: str, args: list[str], image: bytes) -> bytes:
    """Tesseract's stdout for ``image`` (PNG bytes) with ``args`` (after the program).

    shortcut: the key leaves out Tesseract's version and models; clear the folder after
    upgrading Tesseract."""
    key = hashlib.sha256("\0".join(args).encode() + b"\0" + image).hexdigest()
    path = cache_dir() / key[:2] / key
    try:
        return path.read_bytes()
    except OSError:
        pass
    result = subprocess.run([tesseract, *args], input=image, capture_output=True, check=False)
    if result.returncode == 0:  # a failed run is not remembered
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".")
        with os.fdopen(fd, "wb") as out:
            out.write(result.stdout)
        os.replace(tmp, path)
    return result.stdout
