"""Start a long command detached, logging its output inside the repo.

Usage: .venv/bin/python tools/run_logged.py NAME COMMAND [ARGS...]

The log is scratch/logs/NAME.log; its last line is "exit CODE after N s" when the
command ends. Use this instead of a background shell, whose output lands outside the repo.
"""

import subprocess
import sys
from pathlib import Path

logs = Path(__file__).resolve().parent.parent / "scratch" / "logs"
logs.mkdir(parents=True, exist_ok=True)
log = logs / f"{sys.argv[1]}.log"
wrapper = (
    "import subprocess, sys, time\n"
    "start = time.time()\n"
    "with open(sys.argv[1], 'w', buffering=1) as out:\n"
    "    code = subprocess.call(sys.argv[2:], stdout=out, stderr=subprocess.STDOUT)\n"
    "    out.write(f'exit {code} after {time.time() - start:.0f} s\\n')\n"
)
subprocess.Popen(
    [sys.executable, "-c", wrapper, str(log), *sys.argv[2:]],
    start_new_session=True,
    stdin=subprocess.DEVNULL,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
print(log)
