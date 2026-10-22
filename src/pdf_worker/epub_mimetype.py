"""The EPUB's `mimetype` entry: check it, and repack books that get it wrong.

The first ZIP entry must be `mimetype`, stored uncompressed with no extra field, holding
`application/epub+zip`; file-type sniffers (VirusTotal, `file`) read it at byte 30 and
call a book without it a plain ZIP.
"""

import copy
import os
import struct
import tempfile
import zipfile
from pathlib import Path

MIMETYPE = b"application/epub+zip"


def problem(path: str | Path) -> str | None:
    """Why the book breaks the mimetype rule, or None if it follows it."""
    with open(path, "rb") as f:
        head = f.read(30 + len("mimetype") + len(MIMETYPE))
    if head[:4] != b"PK\x03\x04":
        return "not a ZIP file"
    (method,) = struct.unpack("<H", head[8:10])
    name_len, extra_len = struct.unpack("<HH", head[26:30])
    if head[30 : 30 + name_len] != b"mimetype":
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
        where = f"entry {names.index('mimetype') + 1}" if "mimetype" in names else "missing"
        return f"first entry is not mimetype (mimetype is {where})"
    if method != zipfile.ZIP_STORED:
        return "mimetype is compressed"
    if extra_len:
        return "mimetype has an extra field"
    if head[38:] != MIMETYPE:
        return f"mimetype holds {head[38:]!r}"
    return None


def fix(path: str | Path) -> None:
    """Rewrite the book in place with a correct mimetype entry first."""
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(path)), suffix=".epub.tmp")
    os.close(fd)
    try:
        with zipfile.ZipFile(path) as z, zipfile.ZipFile(tmp, "w") as o:
            o.writestr(zipfile.ZipInfo("mimetype"), MIMETYPE, zipfile.ZIP_STORED)
            for info in z.infolist():
                if info.filename != "mimetype":
                    o.writestr(copy.copy(info), z.read(info))  # writestr mutates the ZipInfo
        os.replace(tmp, path)
    except BaseException:
        os.remove(tmp)
        raise
