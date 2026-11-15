# Drop-in experiment: what every step's agent must know

Plan: top of `PROGRESS.md` ("Plan: drop-in-experiment", 2026-11-14). Results: `docs/results.md`.
An agent gets only its own step's lines, so the shared facts are here.

## Goal

Find out, with numbers, what stops "drop a file in the inbox, get a good PDF, EPUB and Typst
file in the outbox" from working every time, and measure candidate answers against today's
pipeline. This is an experiment: change nothing in `src/` and no product default. Scripts go
in `docs/experiments/drop-in/`, outputs in `scratch/drop-in/`. No paid model calls.

## Priorities (the user's, in order; weigh every result by them)

1. Body text right and complete, never garbled. Note text in the body, or body text in a
   note, is the note error that counts. A lost note or note text is the lesser error: when
   unsure, drop the note rather than risk it in the body.
2. Margin references (Stephanus "17a", Bekker "402a5") kept and in their place: much more
   important than notes.
3. Contents with the original titles, subtitles and sections: wanted, not the main focus.
   User, 2026-11-15, after the baseline: the main headings (the ones in the book's contents
   table: parts, chapters) matter and must come out right; a main heading lost, turned into
   body text or split is a real failure. An extra subheading that is not in the contents
   table is not that bad: count it apart and weigh it lightly.
4. Notes split across pages, missing note numbers, note position and content: handled if
   cheap, not a focus. Bibliography: minimum work.

Success: born-digital PDFs and EPUBs need no human step, lose no text, have a contents table
whose links work, and notes kept out of the body. Scans need at most a short look at doubtful
pages, never full marking. Foreign terms inside Spanish (Greek, Latin, German, French,
English) come out right.

AI: local first. Sentences and page images of the test books may go to OpenRouter free
models. Every AI step can be turned off, and a failed or late call never blocks: the
no-model answer is kept. Every AI call goes through ai-client
(`/Users/fons/Documents/programs/ai-client`: `OpenRouter` provider, free models only,
`get_client("openrouter").requests_left()`; `mlx_vlm.py`; `apple_vision.py`; the word check
`ai_client/check.py`).

## Rules

- Never Read a whole PDF or a converted book. Sample pages with scripts; read summaries.
- Never write marks files or outputs next to the test PDFs. Work on copies under
  `scratch/drop-in/`.
- The repo's CLAUDE.md working rules apply: absolute paths, one command per call, no pipes
  or chains, code in files, `.venv/bin/python`.
- Long commands (over a few minutes): start with
  `.venv/bin/python tools/run_logged.py NAME COMMAND...` (logs to `scratch/logs/NAME.log`),
  then run `.venv/bin/python tools/wait_log.py scratch/logs/NAME.log` with the Bash timeout
  set to 600000 ms. `wait_log.py` waits without end, so the call times out after 10 minutes
  while the job is still running: that is expected, run the same wait again, as many times
  as it takes (a build can take two hours), until it prints the log's `exit CODE after N s`
  line. Never use the Bash tool's background mode.
- One heavy build at a time (two Paddle builds collide on the crop cache).
- Never stop to ask. If a part can't be done, write what was done and why the rest wasn't
  into your step's result file `scratch/drop-in/results/S<n>.md`, and finish: later steps
  read that file. A step that ends without its result file stalls the whole night's run.

## Books

Quality set: the pairs of `tools/quality.py` (philosophy, copleston, ratzinger, lugones,
platon_bad, dialogos, niebla, pepita, marianela, gaviota), each with a reference no model
wrote. Hand-made marks exist for four:

- `test_pdfs/philosophy.marks.json`
- `test_pdfs/platon_dialogos_vi_bad.marks.json`
- `test_pdfs/new_test_books/Introduction to Christianity by Ratzinger.marks.json`
- `test_pdfs/new_test_books/copleston/Historia de la Filosofía Tomo 1 - Copleston.marks.json`

Audit set (no reference; pages sampled only), under `test_pdfs/books_sd/`:

- `Antropología Filosófica.pdf`
- `De Anima - Aristóteles (traduccion_tomas_calvo_martinez).pdf` (Bekker numbers; compare
  with `De Anima - Aristóteles - clean_txt.pdf`)
- `Filosofia del Hombre - Roger Verneaux bad 1.pdf`
- `Metafisica - Tomas Alvira bad 1.pdf`
- `Epistemología General Verneaux.pdf`
- `La Biblia en su entorno.pdf`
- `reale_y_antiseri/Historia de Filosofía Antigua Tomo 1.pdf`
- `reale_y_antiseri/Historia De La Filosofía Tomo V.pdf`
- `Introduction to Christianity by Ratzinger.epub`
- `copleston/4 - De Descartes a Leibniz Frederick Copleston.epub`
- `AF/Prometeo Encadenado Bilingüe.epub`
- `AF/The Four Loves by C.S. Lewis.epub`

and two with Stephanus numbers: `test_pdfs/Timeo_by_Platón_no_intro.pdf`,
`test_pdfs/platon_dialogos_vi_bad.pdf`.
