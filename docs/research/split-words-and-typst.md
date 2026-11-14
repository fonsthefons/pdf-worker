# Split words ("haber - la", "vi - ven cia") and a Typst PDF writer

Date: 2026-11-13.

## Goal and criteria

1. Split words: OCR leftovers such as "haber - la vivido" and "vi - ven cia real" should
   come out as "haberla vivido" and "vivencia real". Success: on the test books, at least
   80% fewer split words left, and no new false joins in a sample of 100 joins
   ("sino que", "per la" and "confies en" must stay apart).
2. Typst: is generating the reflowed PDF with Typst simple enough to be worth it?
   Success: tagged PDF (paragraphs copy as one line), footnotes at the foot of the page
   without our multi-pass loop, Spanish hyphenation, and a writer no bigger than today's
   `pdf_export.py`.

## Findings

### Split words

- `join_lines` (`src/pdf_worker/structure.py:199-248`) is not where these words survive.
  It only joins *line ends*: `-` followed by a lowercase line, or a soft hyphen. "haber -
  la" sits *inside* one line, as OCR wrote it, so `join_lines` never sees it as a break.
- Other line-end joiners: `styles._join_hyphens` (`styles.py:117`) and Paddle's
  `_BROKEN_WORD_RE` (`paddle_book.py:52`, which handles "Pro- tarco" only).
- The general split-word rule moved to ai-client in commit 5aa981f:
  `ai_client/check.py:388-419`. `fixes.Review` applies its `split` flags automatically
  (`fixes.py:74`, `:240`). It already handles `" - "` and `"- "` gaps
  (`check.py:413`), but only when one part is a *fragment*, meaning not a dictionary word
  (`check.py:407-409`).
- Why "haber - la" stays: both "haber" and "la" are real words, so neither is a fragment
  and the pair is never joined. The fragment test is right for a plain space ("sino
  que", "per la", "confies en"; rejected after checks in PROGRESS.md:2649-2651). It is too
  strict when a hyphen sits between spaces: in prose a spaced hyphen is almost always an
  OCR line break. An author's dash is "—" or "–".
- Why "vi - ven cia" stays: the rule only looks at *pairs*. "vi"+"ven" makes "viven",
  which would be a wrong join. "ven"+"cia" is not a word. Only the triple makes the right
  word, and no rule tries three parts.
- History: split words went 23 → 18 (PROGRESS.md:2240-2260); one measurement counted 126
  ("Paran á", "so bre", PROGRESS.md:4096); after the dictionary rule, 0-3 left per 15
  pages, mostly capitalised (PROGRESS.md:2716-2754).

### Typst

- Past decision: "no Typst for now (notes go at the end; MuPDF layout is enough)"
  (PROGRESS.md:2524-2526). The options were costed in PROGRESS.md:3954-3959: Typst via
  Pandoc's writer, about 1-2 h.
- What has changed since: the user's new complaint that paragraphs in the reflowed PDF
  copy as separate lines. MuPDF Story writes untagged PDF (assumed; nothing in the repo
  tags it). Typst 0.14 (Oct 2025) writes **tagged PDF by default** and offers PDF/UA-1 as
  an option (https://typst.app/blog/2025/typst-0.14). Whether a viewer then pastes a
  paragraph as one line depends on the viewer: *assumed*, to be checked in Preview and
  Acrobat.
- PyPI `typst` 0.15.2: Apache-2.0, bundled compiler, macOS arm64 wheel about 30 MB.
  `typst.compile(bytes)` returns the PDF bytes (https://pypi.org/project/typst/).
- `#footnote[...]` puts notes at the foot of the page natively
  (https://typst.app/docs/reference/model/footnote/). That would replace the up-to-12-pass
  loop in `pdf_export.py:97-110`.
- `set text(lang: "es")` brings Spanish hyphenation and quotes. Justified text hyphenates
  by default (https://typst.app/docs/reference/text/text/).
- Margin references ("22b"): the `marginalia` package or `place()`
  (https://typst.app/universe/package/marginalia). Polytonic Greek needs a font chosen
  explicitly; not checked.
- `pandoc -t typst` exists (https://pandoc.org/MANUAL.html). Pandoc is already used for
  Word output (README.md:144). Our Markdown → Pandoc → Typst would make a quick test
  without new code; margin references and our page numbering would be lost in that test.
- Escaping: generating Typst markup by hand means escaping `# * _ @ < $ \` [ ] \\` and
  others. Pandoc's writer does that for us.

## Options

| Option | Quality | Cost / effort | Risks | Evidence |
|---|---|---|---|---|
| S1. In `check.py`: a gap of `" - "` (hyphen with spaces) joins when the joined word is a dictionary word, even if both parts are words | Fixes "haber - la", "acontecimien - tos" | ~10 lines + tests in ai-client | A real spaced dash between two words that also join into a word; rare (assumed) | Rule and reasons read in code; frequency not measured |
| S2. S1 + a three-part join (`a - b c`, `a b c`) when the parts are not all real and the triple is a dictionary word, tried before pairs | Also fixes "vi - ven cia" | ~25 lines + tests | Wrong joins of three short real words; mitigated by needing a hyphen or a fragment among them | Not measured |
| S3. Change `join_lines` | Nothing for these cases (they are not line ends) | — | — | Code read |
| T1. Keep MuPDF Story; tag nothing | Copy stays line-by-line | 0 | User's complaint stays | — |
| T2. Spike: our Markdown → `pandoc -t typst` → `typst` compile | Tagged PDF, real footnotes, hyphenation; no margin refs | ~1 h, no code in `src/` | 30 MB dependency; Greek fonts | Web docs; not tried |
| T3. Native Typst writer from blocks (like `html_export`) | Everything T2 has, plus margin refs, cover and folios | ~1-2 days | Escaping; another writer to maintain | Estimate |

## Recommendation

- Split words: **S2** (S1 first, then the triple), in ai-client's `check.py`, not in
  `join_lines`. Measure the joins it makes on the test books before merging.
- Typst: run spike **T2** before writing any code. Go on to T3 only if the spike shows
  that paragraphs paste as one line and the pages look at least as good as Story's.
  Otherwise keep Story, as the July decision did.

## Open questions

- Do Preview, Acrobat and Kindle paste a tagged Typst paragraph as one line? (assumed yes)
- Which test books contain "x - y" spaced splits, and how many? (not counted)
- Which font covers polytonic Greek in Typst (needed for the Timeo)?

## Proposed experiment

A. Split words: run `tools/regression.py build scratch/reg-before`, change `check.py`
   (S1, then S2), run `build scratch/reg-after`, then `compare`. Score:
   (1) split words left, counted with a regex for `\b\w+ - \w+\b` and the review file's
   `auto: split` rows, before and after;
   (2) every new join listed, with 100 sampled by hand for false joins.
   Cost: two regression builds (cached Paddle rows), about 30 min.
B. Typst spike: two books (the Timeo and one Spanish prose book). Run `convert --to md`,
   then `pandoc -t typst`, then `.venv/bin/python -m typst` compile (install `typst` into
   the venv). Score: StructTreeRoot present; paragraphs pasting as one line in Preview;
   footnotes on their page; build time and size against `--to pdf`; five pages looked at
   side by side. Cost: about 1 h, no `src/` changes.

## Results (2026-11-13)

### A. Split words: fail, ai-client branch left unmerged

- Builds: `scratch/reg-before` (628 s) and `scratch/reg-after` (654 s), both exit 0.
  `regression.py compare`: the numbers are the same for all 8 books, and no headings were lost
  or added. Some heading texts changed because space-split words got joined, e.g.
  "Cap ítu lo III" → "Capítulo III" (metafisica, lugones, timeo_greek, niebla, kant).
- Hyphen splits counted with `scratch/split_score.py`: 165 before, 162 after (−2%; the bar was
  −80%). Only 2 new joins: "con - sigo" → consigo (right) and "parte - o" → "parteo" (wrong:
  Kant's "en parte - o quizá", a dash). That is 1 wrong out of 2, far over the bar of 1 in 100.
- The regex mostly finds dashes that set off a phrase ("-no sólo especulativo-"), not split
  words. The few real split words left ("man - tiene", "16- gicos", "so- j lución") were not
  joined. A better test needs a count that tells dashes from splits and a look at why
  "man - tiene" stays split.
- Verdict: fails the ≥80% drop and the ≤1-wrong bar. The ai-client branch
  `feature/split-words-typst` is kept unmerged (committed there, 28df88b) for a later attempt.

### B. Typst spike: promising

Two books, `convert --to md` + pandoc `-t typst` + `typst.compile` (typst 0.15.2), against
today's `--to pdf` ("story"). Times are the whole run; compile itself took 0.8 s and 2.5 s.

| book | pdf | time | size | pages | tagged | `[34b]` bold | missing glyphs | notes on their page (3 sampled) |
|---|---|---|---|---|---|---|---|---|
| lugones | story | 186 s | 2.58 MB | 215 | no | no refs | 0 | 0/3 (`--notes end`) |
| lugones | typst | 184 s | 2.17 MB | 190 | yes | no refs | 0 | 3/3 |
| timeo | story | 56 s | 2.34 MB | 192 | no | not bold | 0 | 0/3 (at the back) |
| timeo | typst | 52 s | 2.15 MB | 148 | yes | 354/354 | 0 | 2/3 (third unclear) |

- Pandoc's Typst template sets letter paper, 1.25in margins and its own font inside `conf()`.
  So the `#set` rules have to come after `#show: doc => conf(...)`, not at the top of the file.
- The Greek check is weak: only 14 Greek characters are left in the Timeo (its facing Greek
  pages are dropped).
- Still to check by the user: whether a paragraph pastes as one line in Preview, and the PNGs by
  eye (`scratch/typst/png/`, PDFs in `scratch/typst/`).
- Next: if those look good, use `/plan-feature` to plan a Typst PDF writer. typst is installed
  in the venv but not added to `pyproject.toml`.
