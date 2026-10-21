"""Wait until a tools/run_logged.py log ends, then print its last lines.

Usage: .venv/bin/python tools/wait_log.py LOG [LINES]
"""

import sys
import time
from pathlib import Path

log = Path(sys.argv[1])
while True:
    lines = log.read_text(errors="replace").splitlines() if log.exists() else []
    if lines and lines[-1].startswith("exit "):
        print("\n".join(lines[-int(sys.argv[2]) if len(sys.argv) > 2 else -15 :]))
        break
    time.sleep(5)
