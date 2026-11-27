#!/usr/bin/env bash
# The same commands as help.sh, as task cards in a browser page (control-panel).
cd "$(dirname "$0")"
exec .venv/bin/python -m control_panel pdf_worker.cli:build_parser --cmd .venv/bin/pdf-worker --tasks ui.json "$@"
