# pdf-worker

Python (>=3.11) toolkit of PDF features. Library code in `src/pdf_worker/`, CLI in `cli.py`.

## Conventions
- One module per feature (e.g. `text_extraction.py`); keep library logic free of
  printing/argparse so it can be reused. The CLI is a thin layer: each feature adds an
  `_add_<feature>_command` function registering a subcommand.
- Open PDFs via `pdf_worker.document.open_pdf` (context manager; consistent errors).
- PDFs can be huge: process page-by-page and stream output; never load whole-document
  text into memory. When inspecting PDFs during development, sample pages with code
  rather than dumping full contents.
- Raise `PdfWorkerError` subclasses (`errors.py`) for expected failures; the CLI turns
  them into a clean `Error:` message with exit code 1.
- Write output files atomically (temp file + `os.replace`).
- Tests: unit tests generate tiny PDFs with the `make_pdf` fixture; tests against
  `test_pdfs/` are marked `integration`.

## Commands
Run each as its own call, from the repo root (`/Users/fons/Documents/programs/pdf-worker`):
- Tests: `/Users/fons/Documents/programs/pdf-worker/.venv/bin/pytest /Users/fons/Documents/programs/pdf-worker`
- Fast tests: `/Users/fons/Documents/programs/pdf-worker/.venv/bin/pytest -m "not integration" /Users/fons/Documents/programs/pdf-worker`
- Lint: `/Users/fons/Documents/programs/pdf-worker/.venv/bin/ruff check /Users/fons/Documents/programs/pdf-worker`
- Format: `/Users/fons/Documents/programs/pdf-worker/.venv/bin/ruff format /Users/fons/Documents/programs/pdf-worker`
- CLI: `/Users/fons/Documents/programs/pdf-worker/.venv/bin/pdf-worker extract-text <pdf> -o /Users/fons/Documents/programs/pdf-worker/scratch/<name>.txt`
- Dev tools in `tools/` (run with the venv's python): `find_text.py` (pages with a phrase),
  `page_lines.py` (the lines the pipeline sees on a page), `page_parts.py` (each line of a
  page with its part: furniture / footnote / body), `render_clip.py` (a page area as
  PNG), `epub_score.py` (an EPUB against a reference), `check_and_fix.py` (EPUBs whose
  `mimetype` entry isn't first/stored get repacked in place; `--check` only reports),
  `regression.py` (`build OUT_DIR` converts the eight test books to Markdown with their
  numbers; `compare BEFORE AFTER` shows numbers, headings lost/added and writes diffs:
  run it before and after a change to the pipeline). Reuse these before writing scratch
  scripts; scratch/ is for throwaway files and is emptied from time to time.

# Working rules for this repo

These rules exist so that every command runs without needing my approval. I often leave tasks running unattended, and a single approval prompt stops all progress until I come back. Follow them strictly.

## Stay inside the repo

- Work only inside this repository. Never read, write, or run anything in folders outside it.
- At the start of a session, run `pwd` once to get the repo's absolute path. Use that absolute path in every command.
- Never use `cd`. Always pass absolute paths to commands instead.
- Don't use `/tmp`, `/private/tmp`, or any system temp folder. Put temporary and scratch files in `scratch/` inside this repo (it is gitignored).
- Install Python packages into this repo's virtual environment (`.venv/`) with `/Users/fons/Documents/programs/pdf-worker/.venv/bin/pip install ...`, then add the package to `pyproject.toml` (runtime deps under `dependencies`, tooling under `dev`). Don't use `pip3`.
- If `.venv/` is missing, recreate it with `python3 -m venv /Users/fons/Documents/programs/pdf-worker/.venv`, then `/Users/fons/Documents/programs/pdf-worker/.venv/bin/python -m pip install -e /Users/fons/Documents/programs/ai-client`, then `/Users/fons/Documents/programs/pdf-worker/.venv/bin/pip install -e '/Users/fons/Documents/programs/pdf-worker[dev]'`.
- Every AI call (Groq, the MLX-VLM server for PaddleOCR-VL, Apple Vision) goes through the
  shared `ai-client` repo (`/Users/fons/Documents/programs/ai-client`, stdlib only). Its keys
  (`GROQ_API_KEY`) come from the environment or `ai-client/.env`, not this repo's `.env`;
  missing AI features belong in ai-client, not here.
- Long commands: never use the Bash tool's background mode (Claude Code keeps its output
  under `/private/tmp`). Start them with `tools/run_logged.py NAME COMMAND...`, which
  detaches the command and logs to `scratch/logs/NAME.log` (last line: `exit CODE after N s`);
  `tools/wait_log.py LOG` waits for that line and prints the log's end.
- Temp files: `TMPDIR` and `PIP_CACHE_DIR` point into `scratch/` (set in `.claude/settings.local.json`), and pytest's `tmp_path` lives in `scratch/pytest` (set in `tests/conftest.py`). If `scratch/tmp` is missing, create it with `mkdir -p`. Code you write must not hard-code `/tmp`.
- Don't write to Claude's auto-memory folder (it is outside the repo). Record lasting notes in this file or in `PROGRESS.md` instead.

## Reading and editing files

- Use the Read tool to look at files, not `cat`, `head`, `tail`, or `sed -n`.
- Use the Edit and Write tools for all file changes. Never modify files with `sed -i`, `awk`, `perl -i`, or shell redirects (`>`, `>>`).
- Use the Grep and Glob tools to search, not shell `grep` or `find`, where possible.
- Never Read a whole PDF or a large extracted `.txt`. Write a script in `scratch/` that samples the pages or lines you need, or use Read with `offset`/`limit`.

## Running code

- Never use heredocs (`<<EOF`), `node -e`, `bash -c`, `eval`, or `source`.
- Put any code you need to run, even a one-liner, in a file under `scratch/` and run that file.
- If the repo has a virtual environment, run Python as `<repo>/.venv/bin/python` (and `<repo>/.venv/bin/pip`, `<repo>/.venv/bin/python -m pytest`) instead of activating it.

## Shell commands

- Keep commands simple: one command per call.
- No chains with `&&`, `||`, or `;`, no pipes (`|`), no subshells (`$(...)`, backticks), and no variables in paths.
- Use only the absolute paths of real files and folders in this repo, written out in full.

## When something is blocked

- If a step seems to require breaking one of these rules or going outside the repo, don't do it. Write it down in `PROGRESS.md` under "Blocked", skip it, and continue with the next step.
- Don't stop to ask me questions while a task is running. Make the most reasonable choice, note it in `PROGRESS.md`, and keep going.

## Pull requests

- You are free to merge PRs
- Open every PR against `main`, never stacked on another PR's branch: `--delete-branch` on
  the first one closes the PR built on it (as happened to #52).

## Progress log

- Keep `PROGRESS.md` up to date: after each phase or major step, add what you did, the main commands you ran, the files you created or changed, and anything that was blocked.

<!-- code-review-graph MCP tools -->
## MCP Tools: code-review-graph

**This project has a knowledge graph. Start with the code-review-graph
MCP tools to narrow scope, then read the source.** The graph is cheaper than scanning files and
gives you structural context (callers, dependents, test coverage) that file search cannot.

### When to use graph tools FIRST

- **Exploring code**: `semantic_search_nodes_tool` or `query_graph_tool` instead of Grep
- **Understanding impact**: `get_impact_radius_tool` instead of manually tracing imports
- **Code review**: `detect_changes_tool` + `get_review_context_tool` instead of reading entire files
- **Finding relationships**: `query_graph_tool` with callers_of/callees_of/imports_of/tests_for
- **Architecture questions**: `get_architecture_overview_tool` + `list_communities_tool`

### Verify in the source

- Narrow scope with the graph, then read the source. Do not change code from graph output alone.
- For any non-trivial change, read the implementation and the relevant tests before concluding.
- Verify the exact source when touching behavior, database logic, migrations, retries, fallbacks,
  recovery, or compatibility code.
- When the graph and the source disagree, the source wins. The graph may be stale or may not
  model that relationship.
- An empty graph result can mean "not indexed" or "not statically visible", not "does not exist".

### Key Tools

| Tool | Use when |
| ------ | ---------- |
| `detect_changes_tool` | Reviewing code changes — gives risk-scored analysis |
| `get_review_context_tool` | Need source snippets for review — token-efficient |
| `get_impact_radius_tool` | Understanding blast radius of a change |
| `get_affected_flows_tool` | Finding which execution paths are impacted |
| `query_graph_tool` | Tracing callers, callees, imports, tests, dependencies |
| `semantic_search_nodes_tool` | Finding functions/classes by name or keyword |
| `get_architecture_overview_tool` | Understanding high-level codebase structure |
| `refactor_tool` | Planning renames, finding dead code |

### Workflow

1. The graph auto-updates on file changes (via hooks).
2. Use `detect_changes_tool` for code review.
3. Use `get_affected_flows_tool` to understand impact.
4. Use `query_graph_tool` pattern="tests_for" to check coverage.
<!-- /code-review-graph MCP tools -->
