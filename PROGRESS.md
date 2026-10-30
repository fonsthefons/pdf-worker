# Progress

## Layout plan, Phase 5: headings (2026-10-30, branch `layout/phase-5-headings`)
**Draft: some books get worse; the user's call (plan: "if a book gets worse, record the
page and line and ask the user").** As the plan writes it, in `footnotes.layout_page`:
a body line in a `doc_title` or `paragraph_title` box gets `BodyLine.title` (also on
chapter-notes pages, so the notes' group headings are still dropped). In `structure`, only
such lines are headings: the heading-size test (`size >= body * HEADING_RATIO`) and
`_implicit_heading_level` (short all-caps or bold line) are deleted, with `_Builder.bold`.
The level comes from the size: the nearest heading size (`heading_level`), else one below
every larger heading size (a title in body type sits under them all). Without rows a
book has no headings (no fallback, as the plan says). Running heads stay dropped
(furniture goes first).
- Tests: `test_a_line_in_a_title_box_is_a_heading_its_level_from_its_size`,
  `test_large_type_outside_a_title_box_is_not_a_heading` (both with and without rows; all
  4 failed before). Four tests that relied on the size test now pass made-up title rows
  (new `title_rows` fixture in `tests/conftest.py`: every line of 12 pt or more boxed
  `paragraph_title`). Fast tests 355 passed; ruff clean.
- `regression.py build scratch/regress/p5head_after` (630 s, log
  `scratch/logs/p5head_after.log`), `compare` against `p5para_c` (main's code with rows):

  | Book | Paragraphs | Headings |
  |---|---|---|
  | kant | 892 -> 883 | 43 -> 52 (22 lost, 31 new) |
  | timeo_web | 680 -> 682 | 3 -> 1 |
  | metafisica | 1,741 -> 1,505 | 59 -> 290 (17 lost, ~250 new) |
  | lugones | 998 -> 999 | 12 -> 13 |
  | dilexit | 243 | 59 -> 60 (4 lost, 5 new) |
  | dialogos | 1,479 -> 1,481 | 28 -> 26 (8 lost, 6 new) |
  | timeo_greek | 223 -> 227 | 7 -> 3 |
  | niebla | 2,831 -> 2,844 | 54 -> 37 (30 lost, 11 new) |
- Better, as Phase 4 said: Kant's "Tesis" / "Prueba" / "Antítesis" (p. 195 on), "A)
  Primera analogía", "Analítica transcendental"; Kant p. 59's table rows ("DE LA
  CANTIDAD", "CUALIDAD") are no longer headings. Metafísica's section titles (p. 98 "El
  ser, acto que engloba todas las perfecciones", "Origen histórico de la ciencia del
  ente") and its chapter labels ("C a pít u lo I"). Niebla's running heads and OCR lines
  in large type ("98 MIGUEL DE UNAMUNO", "lestia.", "P^a^e.da^^^^-") are gone; its chapter
  numerals "III", "VI", "IX" ... now all headings. Lugones' "Las dos conquistas", "Las
  ruinas"; Diálogos' bibliography subheads "1. Ediciones", "2. Comentarios".
- **Worse:**
  1. Kant: the model boxes the chapter and section labels as `text` (p. 87: "Doctrina
     transcendental del Juicio...", "PRIMER CAPÍTULO", "Del esquematismo de los conceptos
     puros del entendimiento" all `text`), so "### PRIMER / SEGUNDO / TERCER CAPÍTULO",
     "PRIMERA / SEGUNDA / TERCERA SECCIÓN", "REFUTACIÓN DEL IDEALISMO" become paragraphs
     (they were `_implicit_heading_level` headings). Also the marks "- III -", "- VII -".
  2. Diálogos: the dialogue titles "## TIMEO" (twice) become bold paragraphs ("**TIMEO**"),
     with "Platón", "Traducción y notas de", "Notas".
  3. Dilexit: "CARTA ENCÍCLICA", "¿Qué expresamos cuando decimos “corazón”?", "ESTE ES EL
     CORAZÓN QUE TANTO AMÓ" (a chapter title, its "V." now a heading of its own) become
     paragraphs; new heading "104. San Bernardo retomó el simbolismo..." (a numbered
     paragraph).
  4. Metafísica: the 17.5 pt divider "INTRODUCCION" (Phase 1 kept it on purpose) and
     "PRIMERA PARTE", "LA CAUSALIDAD", "Noción de persona", "Ente y unidad" become
     paragraphs. New wrong headings: numbers split from their titles ("1." / "N o c ió n
     de ente", dozens of bare "1." ... "6."), footnotes "3. Ibidem.", "7. Ibidem, c. 66.",
     garbled running heads "METAFISICA", "METAFISCIA", "LA CA CAUSALIDAD" (known limit, but
     now headings instead of text), "En preparación:".
  5. Niebla: "POST-PROLOGO", "NIEBLA" (title page) become paragraphs; new "Digitized by
     the Internet Archive", "in 2014".
  6. Timeo web: "TIMEO", "O DE LA NATURALEZA" merge into one heading (fine); "Platón"
     lost. Timeo Greek: title-page lines ("PLATÓN", "JOSÉ MARÍA ZAMORA CALVO") lost.
  Options for the user: (a) take it as it is; (b) keep `_implicit_heading_level` beside
  the model (restores Kant's chapter labels and Dilexit's capitals, but also Kant p. 59's
  table rows); (c) keep the size test too for lines larger than any title box on the page
  (dividers, dialogue titles), a new rule; (d) join a bare number ("1.", "V.") to the
  title line after it, a new rule.
  The code is as the plan writes it; the PR is a draft until the user decides.
- **Test set for the decision (2026-10-30, same branch; nothing heavy run).** The user
  picks from a test set of the books they will convert (`test_pdfs/new_test_books/`):
  - `test_pdfs/` is gitignored (`.gitignore:18`), so the test PDFs, `manifest.json` and
    `truth.json` stay local; nothing of them is committed.
  - 13 books, 129 pages (`test_pdfs/book_tests_pdfs/<label>.pdf`, `manifest.json`: source
    file, source page, role): Antropología, De Anima (the Paper Capture scan), Verneaux
    Epistemología (one of the two identical copies) and Filosofía del Hombre twice (the
    ABBYY scan and the Paper Capture one, the "bad" scan), Ratzinger, La Biblia en su
    entorno, Alvira bad 2 (bad 1 is regression's `metafisica`), Copleston I (the folder's
    only PDF: its nine EPUBs are rebuilt by `epub_reader`, which takes headings from the
    HTML, so these rules never touch them), and four Reale y Antiseri volumes (Antigua,
    Medieval, Renacimiento, T6). Skipped: the second copy of Antigua T1, Tomo 04, Tomo V,
    VII (same layout as the four), "Epistemology 1985" and "epistemologia" (same title).
    Pages picked by role from font sizes, chapter labels and numbered lines
    (`scratch/htest/candidates.py`, `chapters.py`, `extract.py`): chapter openings,
    numbered sections, contents, footnotes, lists, a concept map, body. No page with a
    real table turned up cheaply.
  - `truth.json`: 184 headings with levels (ranked within a book), judged from 55 dpi page
    images (`scratch/htest/png/`) and the PDF's lines; an `uncertain` list per book
    (small-caps run-in lines, anthology titles, levels guessed). Ratzinger checked
    against its EPUB (itself a conversion: it lacks two headings the PDF sets like the
    others and tags the contents entries; noted).
  - Variants selectable without changing the default: `structure.HEADING_RULES` (empty =
    the PR). "implicit" (b, the old `_implicit_heading_level` and `_Builder.bold`, back
    behind the switch), "larger" (c), "number" (d), and "size" + "no_titles" for main's
    old rules. Test `test_heading_rules_compared_beside_the_title_boxes` (5 cases). This
    also mends `tools/parts_report.py`, whose `_watch_add` passed `emphasized` to an `add`
    that no longer took it.
  - `tools/headings_test.py`: `run OUT_DIR` (layout model per book, one at a time, then 7
    variants: old, a, a+b, a+c, a+d, a+c+d, a+b+c+d; "c+d" and "b+c+d" read as on top of
    a), `score OUT_DIR`, `selftest`. Builds headings with `iter_blocks` + `tidy` (no
    Tesseract re-reading, no word check: they make no headings). Checked only with the
    selftest, a fake `headings.json` (`scratch/htest/fake_headings.py`) and a run with
    empty rows on two books (`scratch/htest/dry_run.py`): no model run.
  - Limits: each small PDF is analysed alone, so the profile (body size, heading sizes,
    running heads by repetition) comes from 10 pages, not the book; levels are compared
    pairwise within a book, so only their order counts.
  - Next (docs/layout-plan.md, Phase 5 headings): the user runs
    `.venv/bin/python tools/run_logged.py headings_test .venv/bin/python
    tools/headings_test.py run scratch/headings_test` and picks from
    `scratch/headings_test/report.md`.

## Layout plan, Phase 5: paragraphs (2026-10-29, branch `layout/phase-5-paragraphs`)
**User's choice (b), done (second half of this entry).** First run, as the plan wrote it:
no new paragraph inside one `text` box, as the plan says, in `footnotes.layout_page`:
between two body lines of a page in the same `text` box `BodyLine.starts` is False;
at a box's edge (another box, no box, a page's first line) it stays None and
`structure._starts_paragraph`'s rules decide; no start is added at a new box. Chapter-notes
pages keep no rows (as for the bibliography). The bibliography's `reference_content`
handling is unchanged. No rule deleted: the rules still decide at every box edge and on
books without rows.
- Test: `test_no_new_paragraph_inside_one_text_box` (with and without rows; failed before).
- Check: fast tests 345 passed; ruff clean. `regression.py build scratch/regress/p5para_after`
  against `scratch/regress/p5bib_after` (main's code), breaks lost / new with
  `scratch/para_joins.py BEFORE.md AFTER.md`, turns with `scratch/turns_lost.py`,
  dialogue dashes with `scratch/dash_starts.py` (build 643 s, log `scratch/logs/p5para_after.log`):

  | Book | Paragraphs | Splits | Headings | Breaks lost / new |
  |---|---|---|---|---|
  | kant | 906 -> 871 | 8 -> 7 | 43 -> 40 | 41 / 49 (mostly marks joined to titles) |
  | timeo_web | 772 -> 680 | 599 -> 599 | 3 | |
  | metafisica | 1,952 -> 1,692 | 394 -> 233 | 67 -> 56 | 280 / 32 |
  | lugones | 1,073 -> 997 | 92 -> 65 | 12 | |
  | dilexit | 268 -> 242 | 1 -> 0 | 59 | 26 / 2 |
  | dialogos | 1,489 -> 1,459 | 19 -> 5 | 28 | 30 / 0 |
  | timeo_greek | 293 -> 207 | 90 -> 36 | 7 -> 4 | |
  | niebla | 4,307 -> 2,508 | 2,000 -> 352 | 54 | |
- Better (most of the change): Timeo web loses its wrong splits (p. 6, a justified
  column the model keeps whole: "conocimientos encanecidos por el tiempo." / "Esto se
  debe..."); Metafísica's paragraphs broken at bold-italic sentences ("***E l principio
  de no contradicción...***") and at quotes ending "»" join; Lugones' OCR specks ("•",
  "~~") and hyphenated words ("jesuí-" / "tas (1).") join; Dilexit's mid-sentence breaks
  before a capital ("Por eso" / "Newman encontraba") join. Diálogos' 1,177 speaker turns
  all stay; its numbered paragraphs, and Dilexit's 218, all stay.
- **Worse (plan: "if a book gets worse, record the page and line and ask the user"):**
  1. Kant p. 87 (and the second and third chapters): the model boxes the line
     "Doctrina transcendental del Juicio (o Analítica de los principios)" with
     "PRIMER CAPÍTULO" as one `text` box, so the three chapter headings "### PRIMER /
     SEGUNDO / TERCER CAPÍTULO" are lost into that line's paragraph.
  2. Kant: section marks and their titles become one paragraph ("- § 7 -" + "Explicación",
     p. 38; "- II -" + "Estamos en posesión...", the mark joined to body text), and list
     rows run together ("1º." / "Concepto vacío, sin objeto," / "ens rationis" ...;
     "Infinitos." / "3").
  3. Diálogos p. 159 (and p. 91): the bibliography under "3. Traducciones" is one `text`
     box, so its 9 entries ("F. ADORNO, ...", "J. GARCÍA BACCA, ...") become one paragraph;
     p. 86 the summary items "1.2. Estructura de los elementos (53c-61c). — ..." and
     "2. Las cualidades sensibles (61c-68d). — ..." join the item before.
  4. Timeo Greek p. 6: the turn "TIM.—Claro que sí" joins "SÓC.—¿Seguramente ... ausente?
     [17b]": the model's boxes are right, but the OCR line "parte del ausente? [I7b]" is
     placed lower in the text layer and lies mostly in the next turn's box.
  5. Niebla: 197 of its 1,630 dialogue lines lose their break and join the line before
     (p. 31: "¿Paternos o maternos?" + "—Sólo sé que son tíos."). The model boxes each
     turn right, but this skewed scan's OCR lines sit off the page image, so a line can
     lie mostly in the next turn's box. Its other ~1,600 removed breaks are the OCR
     size-jitter splits the plan meant to remove (splits 2,000 -> 352).
  6. Headings made from a short isolated line (`_implicit_heading_level`) are lost when
     the line shares a box: Kant's three above, Metafísica's "LIBROS DE INICIACION
     FILOSOFICA"; same-level headings in one box merge (Metafísica's authors "TOMAS ALVIRA
     LUIS CLAVELL TOMAS MELENDO", Timeo Greek's title page). Metafísica's other lost
     "headings" were OCR body lines ("dad se identifica, así, con el ente, ...").
  Not changed: Timeo web's 599 splits (not looked into; Phase 4 saw p. 22's justified
  lines become table rows through `CELL`, which paragraph starts don't touch).
  Options for the user: (a) take it as it is (the gains are far larger in number);
  (b) keep the rule's split inside a box for lines that start like an item or a heading
  (a numbering, "§", a bibliography entry's "INITIAL. SURNAME", a dialogue dash): a new
  rule; (c) use the box only on born-digital pages, where lines and boxes agree (items 4
  and 5 are OCR scans), also a new rule; (d) wait for the headings part, which may label
  some of these lines as titles.
  The code is as the plan writes it; the PR is a draft until the user decides.

**User chose (b).** `footnotes._starts_item`: inside one `text` box, a line that starts
like a new item, and the line after it, keep today's rules (`starts` None): a bare number
("3"), a numbering ("1º.", "1.2.", "85."), a dash or "§" (dialogue lines, OCR "__",
"- § 7 -", "- II -"), a speaker's turn ("TIM.—", "TrM.-"), a bibliography entry
("J. GARCÍA BACCA", "GRABMANN, M.:"), or a line all in capitals with 4+ letters
("PRIMER CAPÍTULO"). "The line after" skips blank lines (Kant puts " " lines between a
mark and its title; with them counted, "- II -" still joined "De la razón pura...").
- Tests: `test_a_line_that_starts_an_item_keeps_todays_split_inside_a_text_box` (5 kinds)
  and `test_a_line_after_a_section_mark_keeps_todays_split_inside_a_text_box`; all 6 failed
  without `_starts_item`. Fast tests 351 passed; ruff clean.
- `regression.py build scratch/regress/p5para_c` (639 s, log `scratch/logs/p5para_c.log`),
  `compare` against `p5bib_after`:

  | Book | Paragraphs | Splits | Headings | Breaks lost / new |
  |---|---|---|---|---|
  | kant | 906 -> 892 | 8 -> 7 | 43 (none lost) | 14 / 10 |
  | timeo_web | 772 -> 680 | 599 | 3 | |
  | metafisica | 1,952 -> 1,741 | 394 -> 235 | 67 -> 59 | 227 / 30 |
  | lugones | 1,073 -> 998 | 92 -> 66 | 12 | |
  | dilexit | 268 -> 243 | 1 -> 0 | 59 | 25 / 2 |
  | dialogos | 1,489 -> 1,479 | 19 -> 16 | 28 | 10 / 3 |
  | timeo_greek | 293 -> 223 | 90 -> 39 | 7 (none lost) | 71 / 23 |
  | niebla | 4,307 -> 2,831 | 2,000 -> 634 | 54 | 1,594 / 556 |

- The items listed as worse above are back. Kant keeps its chapter headings, marks, and
  "1º." rows. Diálogos keeps p. 159's entries and p. 86's items; only joins inside one
  entry or sentence remain. All speaker turns stay: Diálogos 1,177, Timeo Greek 36.
  Niebla keeps 1,628 of its 1,630 dialogue lines; its remaining joins are the
  line-by-line OCR splits (the prologue had every line as its own paragraph).
  Metafísica's 8 lost "headings" were bibliography lines or body sentences cut by OCR
  ("LEIN, Die Transzendentalienlehre...", "dad se identifica, así, ..."); its authors and
  "LIBROS DE INICIACION FILOSOFICA" stay.
- Still joined (not one of the user's kinds; read as harmless):
  - Kant's two-line titles become one line: "Libro segundo De los raciocinios
    dialécticos...", "Primera división De la lógica transcendental".
  - Kant's dedication "...Barón de Zedlitz. Señor:".
  - Kant breaks the page doesn't show, which the model joins: p. 38 "...no ofrece
    dificultad. Concedo todo el argumento".
  - Niebla's 2 dialogue lines after "dijo:" / "en voz alta:".

## Layout plan, Phase 5: bibliography (2026-10-29, branch `layout/phase-5-bibliography`)
One `reference_content` box = one bibliography entry, decided in `footnotes.layout_page`:
- `layout.boxes(page, row, lines)`: each line's box index (`box_labels` now uses it).
- `BodyLine.starts`: between two body lines of a page both in `reference_content` boxes,
  True at a new box, False inside one; otherwise None and `structure._starts_paragraph`'s
  rules decide (it now takes the `BodyLine`). `BodyLine`s are copied with
  `dataclasses.replace` in `structure`/`margins`, so the field survives.
- My choices: (1) only between two boxed lines: the first line of a page (an entry may run
  on from the page before) and a box after an unboxed line keep today's rule (Lugones
  p. 365: "William H. Prescott.-Histo,y of ... and" has no box, its next line does).
  (2) Not on pages of chapter notes (`chapter_notes.note_pages`): the model boxes notes
  alike, and on Timeo Greek p. 215 its boxes are a line off the notes (note 26's two
  lines in boxes 18 and 19). (3) The review's bibliography (`fixes._is_reference`, the
  back-matter headings) stays: the model also labels notes sections `reference_content`
  (Dilexit pp. 57-68, Diálogos' endnotes), and telling them apart would be a new rule.
  So no rule is deleted: today's paragraph rule still serves every other line.
- `tools/regression.py build` now passes the cached layout rows (`layout_pages`, with
  `PDF_WORKER_PADDLE_CACHE` defaulting to `scratch/paddle-home`), as the inbox does.
- Tests: `test_a_bibliography_entry_is_the_layout_models_box` (with and without rows;
  failed before the change), `test_a_notes_page_the_model_boxes_as_references_keeps_its_note_paragraphs`
  (fails without (2)).
- Check: fast tests 343 passed; ruff clean. `regression.py build scratch/regress/p5bib_base`
  (main + rows, 635 s) and `p5bib_after` (637 s), `compare`: only Metafísica changes,
  paragraphs 1,980 -> 1,952, splits 412 -> 394; the other seven books byte for byte the
  same (Lugones p. 365's boxes hold one line each, or agree with today's rule). Read the
  whole Metafísica diff (pp. 222-226): every change is an entry joined ("Gilson ... M a-"
  / "drid 1967.") or two entries parted ("Dummett ... (1954). Elders, L.: ...").
- Seen, not changed: "S an g u in eti" (p. 226) is no longer auto-fixed to "San": its
  block now follows a whole "ROLAND-GOSSELIN, M.D.: ..." entry, so `_is_reference`
  (year + commas after an entry) takes it for a reference and the review skips it, as
  it should. A word hyphenated across italic runs joins as "***’A******quin***"
  (`join_lines`, as before for any italic break; before, the halves were two paragraphs).

## After Phase 4: the user's choices, and two spelling-review fixes (2026-10-29)
User: Phase 5 parts are bibliography, paragraphs (rewritten: no new paragraph inside one
`text` box) and headings (added); contents, margins and footnotes keep their rules.
`docs/layout-plan.md` updated (PR #73). Fixed in `fixes.py`, branch `fix/review-bibliography`:
- `Review._section`: a heading of the bibliography's level now also ends it when none of
  the next 6 blocks is an entry (`_LOOK_AHEAD`, read ahead in `apply`). Diálogos'
  "BIBLIOGRAFÍA" (p. 90, 159) now ends at "TIMEO" / "CRITIAS", so the Timeo and Critias are
  spell-checked again. Philosophy's "BREVE BIBLIOGRAFÍA" (pp. 401-423, subheadings
  "Textos"/"Estudios" of its own level) stays one section, as before. Checked with
  `scratch/review_levels.py PDF OUT` on both books.
- `_is_reference`: a short line with a year and 3+ commas counts as an entry only right
  after another entry (Lugones p. 8 "escribió en 1770, ..." was skipped).
Tests: `test_bibliography_with_entries_straight_under_it_ends_at_its_level`,
`test_a_year_and_commas_alone_is_not_an_entry`; the subheadings test now has entries
under its subheadings, as the real book does. Fast tests 340 passed; ruff clean. Not run:
`regression.py` (the Timeo and Critias now get the spelling check's auto fixes, so
Diálogos' Markdown is expected to change).

## Layout plan, Phase 4: the model against today's rules (2026-10-29, branch `layout/phase-4`)
New `tools/parts_report.py OUT_DIR [LABEL...] [--show PAGE...]`: builds the eight books
as `regression.py build` does (Markdown, cached layout rows passed in) while watching the
pipeline's own functions (wrappers that return what they return; the eight `.md` files
are byte for byte those of `scratch/regress/phase3`), then counts per part the lines
both call that part, only the rule, only the model, with the 5 pages holding most of each.
Furniture is left out. Lines are matched through their spans (the pipeline trims and
joins lines but keeps the span objects). `--show` prints a page's lines with the rule's
parts (R region, F note kept, B bibliography, M margin, H heading, P paragraph, S start)
beside the model's label. Run: `run_logged.py parts_report4 ... parts_report.py
scratch/parts_report4` (613 s; log `scratch/logs/parts_report4.log`). Build each run
into a new folder: a reused `<label>.fixes.tsv` changes words (seen: 8 in Metafísica).
`tools/page_parts.py` now does convert's preparation (font sizes, glued references),
follows the note running on from the page before (it showed such notes as body), and
calls the lines a chapter-notes page leaves "endnote". In CLAUDE.md's dev tools.

| Part (lines; contents: pages) | Both | Only the rule | Only the model |
|---|---|---|---|
| footnote region (`_find_region`) | 935 | 474 | 37 |
| footnotes kept as notes | 41 | 31 | 931 |
| contents pages | 4 | 0 | 0 |
| bibliography (`Review.reference`) | 223 | 4,237 | 1,381 |
| margins (`split_columns`) | 699 | 189 | 4 |
| paragraph starts (in `text` boxes) | 6,420 | 3,198 | 1,179 (1,002 in a page's first box) |
| headings | 177 | 104 | 353 |

By book (both / rule only / model only):
- footnote region: metafisica 637/372/17, lugones 297/32/8, niebla 1/49/0, dialogos
  0/9/0, timeo_greek 0/12/0, kant 0/0/2, dilexit 0/0/10.
- footnotes kept: metafisica 41/31/613, lugones 0/0/305, kant 0/0/2, dilexit 0/0/10,
  niebla 0/0/1.
- contents: metafisica 4/0/0 (pp. 5-8; the only printed contents in the set).
- bibliography: metafisica 118/83/72, lugones 0/56/12, dilexit 0/0/379, dialogos
  105/4,095/34, timeo_greek 0/3/884.
- margins: dialogos 699/1/0, metafisica 0/176/0, timeo_greek 0/10/4, lugones, niebla 0/1/0.
- paragraph starts: kant 788/35/141, timeo_web 106/661/93, metafisica 931/396/54, lugones
  704/104/200, dilexit 232/26/51, dialogos 1,429/38/352, timeo_greek 117/141/142, niebla
  2,113/1,797/146.
- headings: kant 21/22/31, timeo_web 0/3/1, metafisica 45/28/288, lugones 10/3/6,
  dilexit 55/4/5, dialogos 20/8/6, timeo_greek 2/6/1, niebla 24/30/15.

What the example pages show, and my recommendation per part:
1. **Footnotes: don't switch the region.** `_find_region` finds nearly every region the
   model sees (935 of 972 lines) and more: Metafísica p. 145's notes 3-5 are `text` /
   `paragraph_title` to the model. Rule-only regions elsewhere (Niebla p. 177, OCR
   jitter) are dropped later anyway. The real loss is after the region: 931 note lines
   whose region is found are put back into the body by `_collect_footnotes` because no
   marker is accepted: Metafísica p. 95 (notes "5.", "6." against references
   "individual5"), p. 98 (the page before's notes come out as a table "| 8. |
   Metafisica..."), Lugones p. 83 ("(1)" markers), p. 50 (a note running on from p. 49).
   And the rule's 31 own lines are its mistake: Metafísica p. 141, an 8.5 pt passage
   joined to note p139-5. Fixing marker matching is outside the plan: **the user's call.**
   Model mistakes seen: Kant p. 71 a section title as `footnote`; Dilexit p. 56 the
   endnotes.
2. **Contents: keep the rule.** Both agree on all 4 pages; nothing to gain on this set
   (switching would only trade one rule for another).
3. **Bibliography: switch (as Phase 5 says: one `reference_content` box = one entry).**
   Metafísica pp. 222-226: the model's boxes are the entries; today almost every line is
   its own paragraph (`--show 224`: "PS" on the wrapped lines). Care: the model also
   labels notes sections `reference_content` (Dilexit pp. 58-63, Timeo Greek p. 215 on,
   Diálogos p. 349): one box per note, fine for paragraphs, but they must not become a
   bibliography; a run-on chapter bibliography (Metafísica p. 36) is `text` to it (stays
   as today). Found on the way, not fixed (no new rules): the review's bibliography
   flag starts at Diálogos's "BIBLIOGRAFÍA" (p. 90, level 2) and never ends, as
   `Review._section` ends it only at a higher level or a "capítulo" heading, so the
   Timeo and Critias (4,095 lines) skip the spelling check; `_is_reference` takes
   Lugones' footnotes (p. 83 "1553; Frobisher en 1577; ...") and a body paragraph (p. 8,
   "escribió en 1770") for references.
4. **Margins: keep the rule.** Diálogos' 699 margin lines agree exactly; rule-only lines
   are Metafísica's contents pages' page-number column (dropped with the page anyway).
5. **Paragraph starts: switch only with a change the plan doesn't have.** Of the
   model's 1,179 own starts, 1,002 are a page's first box (paragraphs running on: Kant
   p. 3, Diálogos p. 7; Phase 5's exception), so about 177 are new. The 3,198 rule-only
   starts are mostly the rule splitting what the model keeps whole: Niebla p. 171 (OCR
   size jitter: the model's 6 boxes are the page's 6 paragraphs, today about 10), Timeo
   web p. 22 (justified lines read as word fragments and joined as table rows),
   Metafísica p. 224 (each bibliography line). Phase 5 as written keeps today's rules
   inside a box, so it adds ~177 starts and removes none of these. The gain needs "no new
   paragraph inside a `text` box": **the user's call.**
6. **Headings (not a Phase 5 candidate): worth considering.** The model finds 353 heading
   lines the rule misses: Metafísica 288 (small-type section titles, p. 98 "El acto de
   ser, fundamento último...", "El ser, acto que engloba...": bold or italic paragraphs
   today), Kant 31 ("Tesis", "Prueba", "Antítesis", p. 195). The rule's own 104 are
   mostly its mistakes: Kant p. 59 table rows "DE LA CANTIDAD", Metafísica p. 126 two
   9.5 pt body lines, Niebla p. 28 OCR specks in large type; title pages either way.
   Model mistakes: Kant p. 195 "Segunda oposición de las ideas transcendentales" as
   `text`, Niebla p. 18 a garbled running head.

Check: fast tests 338 passed; ruff clean. Scratch helpers: `scratch/region_check.py`
(region found / notes kept on given pages), `scratch/review_levels.py` (headings and the
review's bibliography level), `scratch/same_md.py`; PNGs in `scratch/parts_png/`.
**Stopped here for the user's choice of parts (plan: end of Phase 4).**

## Layout plan, Phase 3: the layout model for every book (2026-10-29, branch `layout/phase-3`)
- `paddle_worker.py --layout-only`: PP-DocLayoutV3 alone (threshold 0.3, layout_nms),
  pages at 150 dpi, rows `{"page", "width", "height", "blocks": [{"label", "score",
  "bbox"}]}` with the pixmap's size. `--server`/`--model` are needed only without it.
- `paddle_ocr.layout_pages(pdf, on_page)` -> `{page: row}`, cached in
  `cache_dir()/layout/` keyed by `LAYOUT_MODEL` + file hash. The cache-and-resume code of
  `paddle_pages` moved into `_cached_rows`, shared by both; `_run_worker` with no server
  passes `--layout-only`.
- `layout.box_labels(page, row, lines)`; `DocumentProfile.layout` (not used yet);
  `convert_pdf(..., layout_rows=)`; `inbox`: books built from the text layer get
  `layout_pages` before the build (progress "Looking at the pages"); without the Paddle
  environment, or if the model fails (my choice: any `OcrError`, since nothing uses the
  rows yet), it says so once per run and builds as before.
- `tools/page_parts.py`: a label column, `--png OUT.png` draws the boxes; it keeps the
  model cache in `scratch/paddle-home` unless `PDF_WORKER_PADDLE_CACHE` is set (as the
  tests do), so development runs write nothing outside the repo.
- Seen: a page number "- 3 -" whose `number` box covers only the "3" gets no label
  (the box covers less than half the line), as the rule says. Note for Phase 4.
- Tests: `tests/test_layout_boxes.py` (box_labels with a made-up row; the worker as an
  integration test, passed in 8 s), two inbox tests (said once; rows reach
  `convert_pdf`). `test_inbox.py` runs with the Paddle environment pointed away.
- Check: fast tests 338 passed; ruff clean; `regression.py compare
  scratch/regress/phase2b scratch/regress/phase3`: same numbers, empty diffs for all
  eight books (build 668 s).
- Layout rows of the eight books cached in `scratch/paddle-home/layout/` (run with
  `scratch/cache_layout.py` via `run_logged.py cache_layout`, 3,083 s, about 1.5 s a
  page): kant 206 pages/1,036 boxes, timeo_web 56/314, metafisica 227/1,903, lugones
  370/1,439, dilexit 69/573, dialogos 545/3,234, timeo_greek 261/1,913, niebla 326/2,925.
  Phase 4 must read them with `PDF_WORKER_PADDLE_CACHE` set to `scratch/paddle-home`
  (`tools/page_parts.py` does that by default).

## Layout plan, Phase 2: merge exact duplicates (2026-10-29, branch `layout/phase-2`)
- `LONG_LINE_SHARE = 0.35` now lives only in `margin_refs` (`margins` imports it;
  `margins` already imported `margin_refs`, no cycle).
- Digit/superscript tables: `note_numbers` exports `SUP_DIGITS`, `TO_SUP`, `FROM_SUP`
  (used by `sup`/`from_sup`); `layout._SUPERSCRIPT_DIGITS`/`_FROM_SUPERSCRIPT`,
  `glued_refs._TO_SUP`, `paddle_ocr._TO_SUPERSCRIPT` deleted. They translate digit
  *strings* (with "", "?" or leading zeros around), so the tables are shared, not
  `sup()`/`from_sup()` (those take/return an `int`).
- Bare number **not merged** (my choice): Phase 1 changed `layout._PRINTED_NUMBER_RE`
  to `\d(?: ?\d){0,3}` (OCR-spaced digits), so it no longer equals
  `margins._NUMBER_RE` (`\d{1,4}`); merging would change results.
- Not merged, listed as the plan says: the "number starting a note" patterns
  `layout._PLAIN_NOTE_RE`, `glued_refs._NOTE_START_RE`, `margins._LEADING_NUMBER_RE`,
  `footnotes._DEF_START_RE` (1-3 vs 1-4 digits, different followers).
- Check: fast tests 335 passed; ruff clean; `regression.py compare
  scratch/regress/phase1d scratch/regress/phase2b`: same numbers and empty diffs for
  all eight books (build 614 s).
- The branch also carries the user's two commits moving the repo under
  `~/Documents/programs` (made on this branch after the first run's WIP commit).

## Layout plan, Phase 1: headers and footers by repetition (2026-10-28, branch `layout/phase-1`, PR #69)
**Final state, after the user's answers (the first run's stop is below).**
User decisions (2026-10-28):
1. Keep the old "repeated on many pages" rule beside the size rule; 1.05 stays. Done
   literally: `_MARGIN_ZONE` (10%) and `running_texts` are back: in the zone, a bare page
   number or a line whose key is in the zone on 20% of pages (and 3) is furniture, any
   size (`analyze_document` counts zone keys again; the deleted `_MIN_SMALL_RUNNING`
   rule stays deleted). First tried a share rule on the top/bottom rows instead: OCR gave
   some Niebla heads 17 pt (a heading size) and skewed scans put heads and page numbers
   outside the rows (p. 37: "NIEBLA" baseline 35.6, "31" at 49.1), and a heading-size
   guard against it dropped Timeo Greek's title-page "Platón". The zone does neither.
   `furniture()` now takes `page_height`. Test: `test_a_running_head_bigger_than_the_
   body_on_many_pages_is_dropped`.
2. Every page number goes, but only the number: rule 2a ("its row holds a bare page
   number") counts a row only when no line of body text (not a page number, size >=
   `SMALL_RATIO` 0.92 of the body; `SMALL_RATIO` moved from `footnotes` to `layout`) is
   in it. `test_margins::test_glosses_are_separated_from_the_body` passes. A head at body
   size beside its number now relies on 2b or the zone rule.
3. Timeo Greek p. 8 ("TIMEO" kept mid-sentence): accepted limit.
`tools/page_parts.py` added to CLAUDE.md's dev tools.

Regression, final (`scratch/regress/base` -> `scratch/regress/phase1d`):

| Book | Paragraphs | Headings | Notes | Splits |
|---|---|---|---|---|
| kant, timeo_web, dilexit | same | same | same | same (diffs empty) |
| metafisica | 2,192 -> 1,980 | 68 -> 67 | 18 -> 6 | **510 -> 412** |
| lugones | 1,129 -> 1,073 | 12 | 3 -> 1 | 122 -> 92 |
| dialogos | 1,486 -> 1,489 | 28 | 413 -> 415 | 22 -> 19 |
| timeo_greek | 309 -> 293 | 7 | 786 | 95 -> 90 |
| niebla | 4,311 -> 4,307 | 56 -> 54 | 1 | 2,002 -> 2,000 |

Words lost per book (`scratch/lost_words.py BEFORE AFTER LABEL...`) are heads, page
numbers and markup/hyphenation shifts, except:
- Metafísica: the contents page's top row ("LA CAUSA EFICIENTE....", known limit); the
  lost heading "adecuación entre la inteligencia..." was a sentence cut by a running head,
  now whole. p. 192 "METAFISICA" (top 10.8%, no copy 2 pages away) stays: known limit.
- Lugones: OCR page numbers ("5°-", "27°-", "3°4-": key "#" in the zone on 20% of pages)
  leave the text, their sentences join; the title page's "1904" goes; "II -" (misread
  page number) stays once mid-sentence.
- Dialogos: endnotes "[25] A. E. Taylor, *Commentary*, pág. 22." and "[27] ... pág. 23."
  are lost: alike by key at a page edge 2 pages apart (the plan's known limit). Gained:
  ~8 speaker turns ("PRO. —Y tanto.") and several mid-paragraph lines the deleted
  small-repeat rule had dropped.
- Niebla: 7 garbled heads go (the new key: "UNAMÜNO" = "UNAMUNO"); 4 garbled beyond the
  key stay ("MIGUfiL OE UNA MUÑO", "MIGUEL DE ¡ NAMLÍNO"; known limit). Their heads
  (8.9-9.9 pt over a 9.2 body) count as body text beside the page number, so 2a can't help.
Fast tests 335 passed; ruff clean.

**First run (stopped):** Built as the plan says: `layout.running_key` (case folded, accents dropped, letters and
digits only, digit runs `#`; `_ROMAN_RE` gone), `PAGE_NUMBER_RE`/`_PRINTED_NUMBER_RE`
take OCR-spaced digits ("1 5 6"), new `layout.edge_rows`, `DocumentProfile.edge_pages` +
`furniture(page_index, lines)` in place of `running_texts`/`browser_margins`/`is_running`
(`_MARGIN_ZONE`, `_RUNNING_SHARE`, `_MIN_SMALL_RUNNING`, `_BROWSER_FOOTER_RE` deleted);
`footnotes.layout_page` drops furniture first (`PageLayout.furniture`, also the `skip`
of `_find_region`); `structure._running_title` (top-row furniture; `_HEAD_ZONE` and the
`is_running`/heads filters gone; `add_page` lost its unused `page_height`). New
`tools/page_parts.py PDF PAGE`. Six new tests in `test_convert.py` (1, 4, 5 failed on
main as required). `extract-text` now loses headers, footers and page numbers too.

Test changes (my choice, not in the plan):
- `test_footnotes.py::test_page_footnote_is_linked_and_moved_to_page_end` asserted the
  page number "7" under the notes stays in the body; the plan leaves furniture out of the
  body, so it now asserts "7" is gone (the plan said this file passes unchanged; it can't).
- `test_images.py::_digital_book`: its two pages were word for word the same, so the top
  and bottom lines became running heads; each page now has its own word.

Regression (`scratch/regress/base` -> `scratch/regress/phase1`, 622 s):

| Book | Paragraphs | Headings | Notes | Splits |
|---|---|---|---|---|
| kant | same | same | same | same (diff empty) |
| timeo_web | same | same | same | same (diff empty) |
| metafisica | 2,192 -> 1,980 | 68 -> 67 | 18 -> 6 | **510 -> 412** |
| lugones | 1,129 -> 1,114 | 12 | 3 -> 1 | 122 -> 115 |
| dilexit | same | same | same | same (diff empty) |
| dialogos | 1,486 -> 1,489 | 28 | 413 | 22 -> 19 |
| timeo_greek | 309 -> 292 | 7 -> 6 | 786 | 95 -> 86 |
| niebla | 4,311 -> 4,391 | **56 -> 136** | 1 | 2,002 -> 2,069 |

Metafísica's lost notes were page numbers read as notes ("[^p19-2]: 3", "5 9") and two
notes-section pages glued into one bogus page footnote (p. 196, 206): no real note lost.
Lugones: OCR-spaced page numbers ("17 1 -", "24 1 -", "23-") leave the text and their
sentences join (2 bogus notes gone); the title page's "1904" goes (a bare number in the
bottom row); one page number misread "II -" is now kept mid-sentence ("justo me- / II - /
dio"; it was dropped by the old Roman-numeral key).

**Why stopped (the plan: "if a book gets worse, record the page and line and ask"):**
1. **Niebla gets worse**: 80 running heads "MIGUEL DE UNAMUNO" / "NIEBLA" (e.g. PDF
   p. 40, top row "34" + "MIGUEL  DE  UNAMUNO") are kept and become headings. They are
   9.9 pt, body 9.2 pt: over the rule's `size <= body_size * 1.05` (9.66), so neither 2a
   (the row holds "34") nor 2b applies; 120 of 123 copies kept
   (`scratch/head_sizes.py`). The old 20%-of-pages rule dropped them.
2. **A body line beside a gutter line number goes** (`test_margins.py::
   test_glosses_are_separated_from_the_body` fails, left failing): the last body line
   "and that is the end." shares the bottom row with the line number "10", which rule 1
   takes for a page number, so rule 2a drops the line. Any book with line numbers in
   the margin (Platón editions) loses such lines.
3. **Timeo Greek**: a "TIMEO" head (6.1 pt) with no page number on its row and no copy in
   the top row 2 pages away is kept, now mid-sentence (PDF p. 8, "TIMEO" above "han de
   administrar justicia"); the first "TIMEO" joins the title ("TIMEO PLATÓN TIMAIO:E",
   was the heading "PLATÓN TIMAIO:E"). Its "TI MEO" and "2 33" heads/numbers do go.

Questions for the user: (1) loosen the size limit (how far: Niebla needs ~1.08), or keep
the old share-of-pages rule beside it for bigger heads? (2) For rule 2a, should a
"page number" be required to be the only number of its row / not in a column of
numbers, or should 2a go? (3) Timeo Greek p. 8: accept as a known limit?
Diffs: `scratch/regress/phase1/*.diff`. Fast tests: 333 passed, 1 failed (point 2);
ruff clean.

## Layout plan, Phase 0: before/after tool and baseline (2026-10-28, branch `layout/phase-0`)
New `tools/regression.py`: `build OUT_DIR` converts the plan's eight test books to
Markdown (title = label, author "-", no cover, review file in `OUT_DIR`) and writes
`<label>.json` (paragraphs, headings, notes, splits); `compare BEFORE AFTER` prints the
numbers before -> after, headings lost/added and writes `AFTER/<label>.diff`. Baseline
`scratch/regress/base` on main (7bd7409), 630 s for all eight:

| Book | Paragraphs | Headings | Notes | Splits |
|---|---|---|---|---|
| kant | 906 | 43 | 0 | 8 |
| timeo_web | 772 | 3 | 0 | 599 |
| metafisica | 2,192 | 68 | 18 | 510 |
| lugones | 1,129 | 12 | 3 | 122 |
| dilexit | 268 | 59 | 227 | 1 |
| dialogos | 1,486 | 28 | 413 | 22 |
| timeo_greek | 309 | 7 | 786 | 95 |
| niebla | 4,311 | 56 | 1 | 2,002 |

Metafísica 510 splits from the Markdown (511 counted from the EPUB in PR #67). Built a
second time (`scratch/regress/base2`): `compare` shows no change in any book, so the build
is deterministic. Added to CLAUDE.md's dev tools. Fast tests 328 passed; ruff clean.

## PLAN: the parts of a page as a reader sees them (2026-10-28, `docs/layout-plan.md`)
User: recognise headers, footers, page numbers, footnotes, contents and bibliography the
way a reader does, with fewer rules, built later at medium effort. User's choices: the
layout model, time doesn't matter, one test book per kind. Measured first: PP-DocLayoutV3
alone (no text reading) runs at 1.5 s per page; it called Metafísica's running heads
titles on 61 of 97 pages ("INTRODUCCION" never a header) and Kant's section headings
header/footer. So headers, footers and page numbers go by repetition (the same small line
at the same edge of a page at most 2 pages away; prototype: Metafísica ~410 lines
dropped, 3 garbled heads missed; Timeo 110; Kant none), and the model is kept for
contents, bibliography, footnotes and paragraphs, part by part after a comparison the user
decides on (Phase 4). Prototype scripts: `scratch/layout_only.py` (Paddle Python),
`layout_lines.py`, `layout_votes.py`, `edge_rule2.py`. Phase 0 done (above); next: Phase 1.

## Paragraphs: a block set in from the margin (2026-10-27, branch `fix/inset-blocks`, PR #67)
Building Metafísica's second copy to compare showed the chosen copy split an inset
small-type passage into one paragraph per line: each line was indented against the
margin. `structure._starts_paragraph`: an indented line starts a paragraph only when it
is set in from the line before, or the line before ended a sentence (a list of one-line
entries). Metafísica 1,118 -> 511 sentences broken across paragraphs (most of the rest:
running heads at 10.8% of the page, outside the 10% margin zone); Kant, Platón Timeo,
Dilexit nos unchanged; Lugones 2 joins, one right, one a bibliography entry without a
final full stop. Copy 2 built for comparison: grade B, 239 rows to review against 163.
Test: `test_a_block_set_in_from_the_margin_is_one_paragraph`.

## Best of several copies (2026-10-27, branch `feature/best-copy`)
User: a folder in `file_inbox` holds PDFs of one book; use the best, say which. New
`copies.py` (`rank_copies`): OCR needed (none < pages with no text < whole book), then
spreads (most pages landscape), then non-split spelling flags per 1,000 words in a
20-page sample. `inbox` handles folders (outputs/work named after the folder, choice in
`copy.json`, folder filed in `converted`); CLI takes a folder inside an inbox as one book.
Metafísica - Tomás Alvira: "bad 1" (227 pp, OCR only pages with no text, 13.6/1000) over
"bad 2" (127 pp two-page spreads, underlined: whole-book OCR, 14.2/1000); built as a
draft, grade B, 163 rows to review. Tests: test_copies.py, test_inbox.py.

## find-book: One More Library (2026-10-27, branch `feature/onemorelibrary`)
User asked to add onemorelibrary.com/index.php/es/. A Joomla (DJ-Classifieds) site, no
sitemap, no API. `find_book._onemorelibrary` (Spanish only): its search page
(`resultados-de-busqueda?se=1&layout=blog&search=`) wants every word, so the title's key
words are searched, then the author's when nothing comes back; results are "Title -
Author" cover labels; the first 5 book pages are read for their files (PDF, EPUB; MOBI and
others skipped). Live: Niebla, Rinconete y Cortadillo (EPUB 33 KB valid, PDF 29 pages
good); no Quijote of Cervantes in its catalogue. Test with the site's markup in
`test_find_book.py`. Prototype scripts `scratch/oml_*.py`.

## No spelling rows for italics in born-digital books (2026-10-27, branch `feature/no-italic-flags`)
User asked to drop flags inside italic text. `Review(italics=False)` gives no rows for
words in italics (auto split/learned fixes still apply); `convert_pdf` passes
`italics=scanned` (Paddle, or `assess_text_layer` scanned share >= 0.5): in a scan italic
words are misread like the rest (Lugones: 83 of 557 rows were italic, many OCR errors
like "seftores", "fdcil"), so scans keep them. Born-digital: Bourdieu 38 -> 34
(aisthesis, askesis, experimentalis, Republique); Trump v CASA 137 -> 121, 10 of the 16
real problems hidden: lost ligatures ("Griffn", "Mayfower") and split halves ("ployees")
in italic case names. Italics come only from fonts flagged italic (Kant, Dilexit nos,
Magnifica Humanitas have none). Scripts: `scratch/spelling_rows.py`, `rows_diff.py`.
- `test_pdfs/` lacks "Familia Romana Lingua Latina.pdf" and the Ratzinger PDF now: 3
  integration tests skip.

## `process --clean` (2026-10-27, branch `feature/process-clean`)
User asked: delete everything not still in the inbox or outbox. `inbox.cleanable(root)`
lists work folders of books not in `file_inbox`, everything in `file_work/converted` and
drafts of books not in `file_inbox`; `inbox.clean` deletes them. `process --clean` prints
the list and size, asks on a terminal (`_ask_yes`, 60 s = no), then deletes; it builds
nothing. Tests in test_inbox and test_cli. On `file_conversion` it would leave only the
outbox's EPUB + PDF (dry run, `scratch/clean_dry_run.py`); not run there.

## Contents pages and outlines (2026-10-27, branch `feature/contents-pages`)
User: the PDF had no clickable contents. Found: EPUBs kept their contents only as the
reader's menu (nav not in the spine); an EPUB input's PDF came from `ebook_to_pdf` (outline
only); a converted PDF had a contents page but no outline.
- `epub.py`: nav in the spine after the cover, styled (`nav#toc`, no list numbers).
- `epub_reader.rebuild_epub(pdf_path=)`: also lays the book out with `pdf_export.write_pdf`;
  `inbox` uses it for EPUB inputs (`ebook_to_pdf` only for an EPUB kept as it is).
- `pdf_export`: outline from the headings MuPDF's Story reports while laying out
  (`_outline`; the contents page's own heading, the title, left out).
- Millán Puelles from mercaba.org (scraped, `scratch/mercaba_*.py`): 22 chapters, 154
  notes, epubcheck clean; PDF contents pp. 2-9 with links, 164 outline entries.
- Not done: bracketed `[n]` notes restarting per chapter (the PDF edition's), user: skip.
Full suite passed (320 fast, 17 integration).

## Chapter lines taken for running heads (2026-10-27, branch `fix/bold-chapter-heads`)
User: "CAPÍTULO VI" missing in Millán Puelles. It (bold, body size) sits in the top 10% of
its page, and "CAPÍTULO IV/V/VI/VII/IX/XI" all read "capítulo #": 4+ margin lines at body
size, so the small-running rule (`_MIN_SMALL_RUNNING`) dropped them (III, VIII, X kept:
other spelling or lower). Now a margin text seen in bold isn't running by that rule (the
20%-of-pages rule is unchanged). Book: chapters I-XI all headings again. Test in
`test_convert.py` (fails without the fix). Full suite passed (320 fast, 17 integration).

## Note size, browser header and footer (2026-10-27, branch `fix/sizes-and-browser-margins`)
User asked: one size for all text (headings apart), notes smaller in the notes section,
no browser header/URL lines. Found: "small" paragraphs already had the body's size in
every writer (EPUB CSS only drops the indent), and notes were 11 pt like the body.
- Notes: `aside.note p { font-size: 0.9em }` (EPUB, and the PDF's notes at the end);
  page-foot notes `_NOTE_CSS` 9.9 pt.
- `layout._BROWSER_FOOTER_RE` (URL, "(3 de 32)", date): on a page with that footer, its
  small margin lines (< body size) are running text (`DocumentProfile.browser_margins`),
  however few pages repeat them. Millán Puelles' contents (header = the 30 pt title,
  protected) and prólogo (2 pages, under `_MIN_SMALL_RUNNING`) kept them; now 0 left,
  the title kept. Test in `test_convert.py`. Full suite passed (319 fast, 17 integration).

## Paragraphs cut before a note number (2026-10-27, branch `fix/superscript-gap`)
Millán Puelles (a web page printed by a browser): a line holding a superscript note number
("PLATÓN[2]") is set lower by the number's rise (11 pt at 17.5 pt), so its gap was 1.42
lines and `structure._starts_paragraph` (> 1.3) cut the paragraph. Now the gap is measured
less `Line.superscript_rise`. Book: mid-sentence paragraph breaks 106 -> 8, paragraphs
1239 -> 1135 (`scratch/mid_sentence_splits.py`). Test in `test_convert.py`. Full suite
passed (integration: 17).
- Seen, not fixed: the browser's running head ("FUNDAMENTOS DE LA FILOSOFÍA", 9 pt) and
  footer URL stay in the text as small paragraphs; 376 of 1163 paragraphs are small type
  (notes 12.9 pt, bibliography 14, contents 15 in the original; body 17.5).

## PLAN: one command, `process` (user, 2026-10-27; phase 1 built, branch `feature/process-options`)
Phase 1 done: `inbox.process(book=, settings=)`, `settings.json` per work folder,
`FORMATS`/`DEFAULT_FORMATS`/`BOOK_OPTIONS` in inbox.py; the EPUB is always built (the
report counts its words), into the work folder when not asked for; `searchable` =
`<stem>.searchable.pdf` (not with Paddle); EPUB inputs: EPUB + PDF only (noted in the
result). `process` prints only `pdf-worker process` for later (it re-offers the review).
`find-book` downloads into `file_conversion/file_inbox`, its one next step is
`process FILE` (the OCR mode/language hints are gone: `process` decides). Tests:
test_inbox (one book + formats + rebuild), test_cli (2 new), test_find_book updated.
Fast suite 317 passed. Not checked on a real book yet.

Keep `process`, `find-book`, `virus-check` (+ `help`). Phase 1, `process` gets:
- `--to epub,pdf,md,html,txt,docx,searchable` (default `epub,pdf`); `searchable` hands
  out the OCR'd PDF from `file_work` (replaces `ocr`).
- A FILE instead of the folder: that one book, copied into `file_inbox` and run through
  every folder like the rest (user: a single file must go through all the folders).
  `--title/--author/--language/--notes/--margin-refs` allowed only with a file.
- `review` no longer typed: `process` asks (waiting books are asked again).
- `find-book` saves into `file_inbox` by default.
Phase 2 (later, once phase 1 is checked to replace them): delete `convert`, `kindle`,
`ocr`, `rebuild-epub`, `ebook-to-pdf`, `review`; `extract-text` becomes a `tools/` script.
Update tests and README with each phase.

## Review counts, auto rows, links (2026-10-27, branch `fix/auto-rows-stale`)
- The draft line's "90 open rows" (book_report: found + possible) vs "70 rows to review"
  (`review.open_rows`) on Millán Puelles: 28 note rows (ref-no-note 21, note-no-ref 7)
  count in the report but review only shows spelling/chars (decided in the TSV); and 8
  `auto: split` rows were `stale` on the rebuild, so review showed them as "replacements
  that no longer apply" and kept the book a draft. Cause: `_check` makes the fix again
  before the review rows apply, so the row's `find` is gone. `Review.finish` now marks an
  auto row the check redid as `applied` (test in `test_split_and_learned_words_...`).
  Script: `scratch/count_kinds.py <fixes.tsv>`.
- ai-client PR (`fix/skip-links`): words inside web addresses and emails aren't checked
  ("mercaba.org/Filosofia/Millan" gave accent rows).

## `process` folders moved under `file_conversion/` (2026-10-26, branch `feature/epub-reader`)
User renamed the repo's `pdf-worker/` subfolder to `file_conversion/` (holds `file_inbox`,
`file_work`, `file_outbox`). `pdf-worker process` now defaults to `./file_conversion`
(cli.py); `help` examples, README and `.gitignore` updated. Fast suite 311 passed.
- `process` follow-up (user asked): for each draft/waiting book it asks "Review now?" (y/N,
  60 s timeout = no; only on a terminal) and runs `review`; after a review it asks
  "Rebuild now?" and runs `process` again. Whatever is declined is printed as numbered
  commands ("To finish later, run:"). `BookResult.review_pdf` carries the PDF for review.
  Tests in `tests/test_cli.py` (3); fast suite 314 passed.
- Bibliography entries "AUTHOR: Title; AUTHOR: Title" (Millán Puelles, whose
  "BIBLIOGRAFÍA Cap 2" titles are body-size paragraphs, not headings) are now reference
  paragraphs: no spelling rows (`fixes._AUTHOR_LIST_RE`, needs a ";"). On that book it
  catches 27 paragraphs, all bibliography. Test added to `test_fixes.py`.
- ai-client PR #7 (`fix/foreign-accents`): a word with more accents than the Spanish form,
  spelled so in another language ("médiéval"), is no longer an `accent` flag.
  `Words.foreign(accented=True)` skips languages that ignore accents: the Latin dictionary
  (ICONV strips them) accepts "cambiár" as "cambiar". Also opened PR #6 for the unmerged
  `feat/whisper-dir-and-sweep` commit; the two don't overlap.

## EPUBs rebuilt like converted PDFs (2026-10-23, branch `feature/epub-reader`)
Asked by the user: every output EPUB has the same structure, EPUB inputs included (notes
that open as pop-ups), with the front matter left out and a text cover.
- New `src/pdf_worker/epub_reader.py`: two passes over the spine (stdlib `html.parser`);
  the first finds note references and their targets, the second makes structure blocks
  for `epub.write_epub`. Raises `EpubReadError` when >2 (and >1%) of the note references
  lead nowhere, or there's no text. New CLI `rebuild-epub`; `process` rebuilds EPUBs
  (falls back to the old copy-as-is on any error) and lays the PDF out from the rebuilt one.
- Tests: `tests/test_epub_reader.py` (two note styles, front matter, fallback).
- Sample run (`scratch/rebuild_samples.py`, 16 EPUBs in `test_pdfs/`): all rebuilt, 0
  unlinked references. Plato 11.8 MB -> 7.4 MB (6,153 notes); Copleston I-IX 600-1,400
  notes each, front matter (cover, synopsis, title, info) dropped; The Idiot starts at
  "PART I". `tools/epub_score.py`: italics and curly quotes identical; words lost are the
  front matter and contents pages.
- Size: smaller for big Calibre books, roughly the same (-10% to +6%) for others: the
  writer gives every paragraph an id and every note two back links, and adds the text
  cover JPEG.
- Known gaps: class-styled headings (Wikisource "El imperio jesuítico" has 1 heading),
  tables, SVG, verse breaks, internal non-note links, Stephanus numbers printed inline
  (`<span class="numarg">`, Plato) stay inline text, not margin refs.
- Follow-up (same day): Project Gutenberg's header and licence (`class="pg-boilerplate"`)
  left out; notes' later paragraphs (no id of their own) joined to their note on notes
  pages (Copleston and Plato had "Notas" pages left in the text); markers like `[32a]`;
  pages with an ebook tool's imprint ("ePub r1.4", "Editor digital") dropped anywhere
  (Plato is 7 volumes joined: 25 pages of repeated front matter out, 7.1 MB); headings
  right before a note dropped (a notes page's "Notas", often a file of its own). Title
  and author: the package's when present; the title-page lookup (`book_metadata`, MuPDF
  layout of the EPUB) only fills missing fields. Tried as the main source it was worse:
  author found in 1 of 6, Plato -> "Diálogos I", Doña Perfecta -> "pg15725", 9 s on Plato.
- Follow-up 2 (same day, user picked gaps 1, 4, 5): headings from the NCX contents
  (Wikisource Lugones 1 -> 11 headings); internal links resolved by giving blocks the
  document's spine index as `page` and their end position in the source as `top`, so the
  writer's page-target lookup lands on the block holding the target (Doña Perfecta: 716
  links to "page, line" anchors land on the right paragraph); `Table` blocks (Plato's
  textual-variant tables: 14); blockquote/li/dd as `small`, bullets/numbers kept; `<br>`
  as `inline.LINE_BREAK` (new; the EPUB writer emits `<br/>`); documents whose broken
  paragraphs mostly start lines in lower case are joined (Gutenberg's printed lines:
  5,778 `<br/>` in Doña Perfecta -> 0; The Idiot's poems keep theirs); SVG files via
  `<img>` rasterised. Same 16-book run: all rebuilt, 0 unlinked. Left: inline `<svg>`
  drawings, nav-only EPUBs (none in the samples), lower-case modern verse would be joined.
- Local `main` was stale (PR #49); the branch is off `origin/main`. An empty branch
  `feature/epub-rebuild` (off the stale main) was left behind: delete it with
  `git branch -d feature/epub-rebuild`.

## Timeo no-intro: old build vs new word check (2026-10-22, ai-client PR #5)
User asked to compare `timeo/timeo_no_intro2.epub` (built 2026-10-21, `convert` of
`test_pdfs/Timeo_by_Platón_no_intro.pdf`, defaults) with the new system.
`scratch/timeo_compare/build.py` rebuilds it into scratch (review file and ai-client
decisions copied there); `compare.py` diffs the EPUBs word by word, sorted by cause.
- Same notes (788), references (789), stand-ins (44), headings, paragraphs and margin
  labels (354); no note text changed. Body text: only split words joined.
- The old build had no word check at all for this book (a ClearScan redraw isn't
  "mostly scanned"); now 48 open spelling rows: accents (probabilidád, razon, segun,
  todavia), OCR misreadings (rnteligencia, moddo, uniforrne, movimieʜtos, unjuego...),
  and halves of words a paragraph cut (below).
- Automatic joins: first 13 (one wrong: "e n e l oro" -> "loro"); after ai-client #5
  (a hyphen with spaces around it, "acontecimien - tos"; a one-letter tail, "fluj o";
  spaced-out letters never joined) 23, all right.
- Left (pdf-worker, structure): a paragraph cut at a line break leaves a soft hyphen at
  its end ("púr­", "porcio­", "refrige­", "sufi­") and the word's other half starts the next
  paragraph ("guiendo", "garse"): the two blocks aren't joined across that break.

## Word check handed to ai-client (2026-10-22, branch `feature/ai-client-check`; ai-client PR #4)
Decided with the user: pdf-worker keeps the structure (headings, notes, margins, metadata,
styles, OCR votes, macrons); every word-level correction moves to ai-client. pdf-worker
cleans the text (body only; page marks, margin/note refs and styles taken out) and maps
the flags back. Born-digital books are checked too, with the normal review (their rare
words, once kept, teach the check). Old-spelling rules: copied to ai-client
(`old_spelling.py`), not used. Glossary per book: not now (measure later).
- ai-client (`feat/ocr-guesses`): pdf-worker's OCR guesses (accent, swap b/h c/e, one
  edit; `Flag.how`), "ban" -> "han" (a Wikipedia-only word whose swap is 100x as common),
  pdf-worker's split rules (Hunspell tells fragments; never an author's hyphen: lines are
  joined before, so "head-master", "vice-versa" stay), a sentence-start word takes the
  common accents, a pronoun's accent only on the verb's stress, decisions path read when
  called, guesses cached. 490 accepted / 536 rejected decisions imported from the
  philosophy and Platón review files (`scratch/import_decisions.py`).
- pdf-worker `fixes.Review`: `check.text` per body block before the review rows apply;
  `split` and `learned` flags applied and written as `replace` rows typed `auto: split` /
  `auto: learned` (status applied; set to `ignore` to undo); other flags become spelling
  rows (types accent, swap, seen, ocr1, near, name, unknown); decided word rows recorded
  once in ai-client's decisions at the next build, source = the review file's stem
  (`merge` doesn't know the book's language). Book-level filters stay here (words seen 3+
  times, names the book repeats). `dictionaries/` and `spylls` removed; report counts
  the auto rows under "Fixed automatically". Tests redirect `DECISIONS_FILE` (conftest).
- Check on books (`scratch/check_books.py`): Introducción 2 open rows; Kant 59 rows,
  1 auto split ("in tuición"); Gibbon 1872 126 rows, no auto fix (before the split fix
  Gibbon/Kant got 6 wrong joins each: "head-master", "vice-versa").
- Not done yet: the LLM pass as the last step before review (replacing `review.propose`),
  with italic spans' flags dropped.

## TODO: use ai-client's post-checks (`ai_client.check`) (noted 2026-10-22; steps 1-5 done above, LLM pass open)
ai-client now has `ai_client.check`: per-language post-checks (split words, names, spelling with suggestions,
optional LLM context pass) plus learned decisions. See ai-client's README, "Post-checks". Contract: **ai-client only
checks real text; pdf-worker passes clean body text.**

1. Pass clean text only:
   - body text (no notes, bibliographies, indexes, ALL CAPS headings), as `Review` already selects;
   - with ligatures normalized (ﬁ ﬂ ﬀ ﬃ ﬄ → fi fl ff ffi ffl): done at extraction
     (`document.TEXT_FLAGS`, 2026-10-22);
   - never text extracted back from a reflowed PDF (its typesetter adds ~1,000 ligatures).
2. Per book: `words = check.Words(language)` with the book's detected language ("es" or "en"),
   `decisions = check.Decisions(language)`, `source` = the PDF stem.
3. Write the flags into `<stem>.fixes.tsv` as rows with an empty action (kind, page, find, context, value = suggestion),
   so the existing review page shows them. `split` and `learned` flags may be applied automatically; the rest stay for review.
4. In review.py's Export (`merge`), for every decided row call
   `check.record(flag, accepted=..., source=stem, language=language, value=...)`:
   `replace` → accepted with the new value; `ignore` → rejected (kept: never flagged again).
5. Then remove the duplication: switch fixes.py's spelling check (`_knows`, the Spanish clitic/superlative rules,
   foreign dictionaries, `dictionaries/`) to ai-client's `check.Words`. ai-client has the same rules and dictionary
   files (es, en, de, fr, it, la, es.extra.txt) and vendors spylls. Until then, changes to those rules must be made
   in both repos.

Baseline (whole raw text layer, no OCR/fixes first): Kant 0.8 flags/1k words, Introducción a la Filosofía 3.8/1k,
Gibbon 1872 scan 15.8/1k (mostly real OCR errors: Csesar, Eoman, prsefect, plus 1,317 line-break hyphenations
correctly joined). Known gaps: transliterated Greek (lógos), run-together words (laspalabrasy), first-letter
OCR errors (lntroduction), Latin/French not in the dictionaries (realitas, coessentiel).

Caveats: this plan leans on transcribe's `course_of` and its knowledge-base glossary, and pdf-worker's Review,
fixes.tsv columns and merge (found by reading the code). Not checked: whether transcribe has a single review step
where `record()` fits. The word lists live only on this machine (`~/.cache/ai-client/`); another machine has to
rebuild them with `python -m ai_client.lexicon es|en`.

## Encyclical notes test, ligatures (2026-10-22, branch `feature/ligatures-endnotes`)
- `test_convert_endnotes_pdf_to_valid_epub` (244 notes, expected 224): `glued_refs` took
  climbing plain numbers for references ("AAS 42 (1950)", "AAS 53 (1961)" in the notes
  pages, "el pasado 7 de diciembre"), and since 615a167 a superscript with no note gets a
  stand-in note. A trusted run must now hold half the numbers of its span
  (`_MIN_RUN_DENSITY`; the Timeo's real runs: 0.76, 0.55; the encyclical's false one 0.18).
  Encyclical: 224 notes. Timeo_by_Platón: notes with text 774 -> 775, stand-ins 272 -> 160,
  noterefs 1060 -> 944 (`scratch/glued_check.py`).
- Ligatures: `document.TEXT_FLAGS` (text-only, without `TEXT_PRESERVE_LIGATURES`): MuPDF
  splits ﬁ ﬂ ﬀ ﬃ ﬄ into letters. Used by `page_lines`, `consensus`, `glued_refs` and
  `styles` (so their words match). Introducción a la Filosofía: 5 ligatures -> 0.
- Tests: 323 passed (full suite, integration included).

## `pdf-worker process`: inbox -> work -> outbox (2026-10-22, branch `feature/inbox`)
User asked: `file_inbox` (books to convert), an intermediate folder (any name), and
`file_outbox` (clean files). User decided: one command (no folder watcher); EPUB + PDF for
every book; drafts in `file_outbox/drafts`, replaced by the finished files in the outbox
root once reviewed; originals of finished books move to `<intermediate>/converted`.
- New `inbox.py` + `process` subcommand (`pdf-worker process [FOLDER]`, `--engine`).
  Intermediate folder: `file_work/<file name>/` holds `<stem>.pdf` (copy / OCR'd copy /
  ebook laid out), so `pdf-worker review file_work/<name>/<stem>.pdf` needs no options.
- "Reviewed" = the review file is newer than the `draft` mark written with the drafts
  (`review` saving decisions rewrites it). Until then the book is reported `waiting`.
  Born-digital books with no open rows and EPUBs finish in one run.
- `kindle.ocr_and_vote` pulled out of `make_kindle_book` (no change in behaviour) and reused.
- `epub_mimetype.py` (from `tools/check_and_fix.py`, which now imports it): EPUB inputs
  are copied to the outbox with the mimetype entry repaired.
- `.gitignore`: the three folders. README section "Process a folder of books"; cheat sheet.
- Tests `tests/test_inbox.py` (2); fast suite 301 passed. Smoke runs in `scratch/inbox_smoke`
  (Copleston EPUB, 2 born-digital PDFs: finished in one run) and `scratch/inbox_scan`
  (6 pages rasterized from "Introducción a la Filosofía 1": OCR -> draft with 16 rows ->
  `waiting` -> decisions saved via `review.merge` (`scratch/fake_review.py`) -> finished).
- Per-book report (user asked; user decided a low grade does NOT hold a book in drafts):
  new `book_report.py`; `inbox` writes `file_work/<name>/report.md` on every build and
  prints the grade. `prepared.json` in the work folder keeps how the text was obtained
  (assessment numbers, OCR mode/language, second-reading fixes) for the later rebuild.
  Grade A-D from words kept (book EPUB words / source PDF layer words, letters only),
  empty pages and open review rows per 1,000 words; OCR'd text in a language without a
  spelling check (not es/en) is at best B. Calibration on `scratch/report_smoke`:
  born-digital Ratzinger 100% kept, Trump v CASA 97%, Timeo 99% (all A); 6 rasterized
  philosophy pages 101%, 27 open rows (10/1,000 words: C, draft); Familia (Latin OCR) B.
  Tests `tests/test_book_report.py` (3); fast suite 304 passed.
- Left as is: the reflowed PDF uses `convert`'s default `--notes end` (page-foot notes can
  overlap the text); a book in both PDF and EPUB form with the same stem writes the same
  outbox names; Tesseract-OCR'd books get no scan crops on the review page (known, see the
  PLAN section).

## EPUB mimetype check/fix (2026-10-22, on `main`, not committed)
VirusTotal reported Copleston volumes 2, 3, 4, 6 and 7 (`test_pdfs/copleston-epubs/`) as
plain ZIPs: their first entry was `META-INF/`, with `mimetype` as the 4th entry, so the
`application/epub+zip` signature wasn't at byte 38. New `tools/check_and_fix.py BOOK.epub...`
checks the OCF rule (first entry, stored, no extra field, exact content) and repacks bad
books in place (atomic; other entries copied unchanged). Ran it on all 9: 5 fixed, 4 already
ok. Checked on a copy of vol. 2 that names and contents match the original.

## AI calls through ai-client (2026-10-22, branch `feature/ai-client`)
Every AI call now goes through `/Users/fons/Documents/programs/ai-client` (installed with
`.venv/bin/python -m pip install -e /Users/fons/Documents/programs/ai-client`; listed as `ai-client`
in `pyproject.toml`).
- `groq.py`: thin wrapper over `ai_client.Groq` (same model, temperature 0.2,
  reasoning_effort low, token budget, 429 retries); `GroqError` kept. The key now comes from
  the environment or `ai-client/.env`. `virus_check.api_key` keeps its own `.env` lookup.
- `paddle_ocr._mlx_server` wraps `ai_client.mlx_vlm.server` (new in ai-client PR #2);
  `consensus` uses `ai_client.apple_vision` (new in ai-client PR #2).
- Check: `scratch/ai_client_check/check.py before|after --paddle` + `compare.py`. Payloads,
  Apple Vision words and Paddle rows are identical before and after. Differences: User-Agent
  `ai-client` instead of `pdf-worker`; error texts ("Groq error 400" instead of "Groq API error
  400", longer cut-short text, "Groq: " prefix on the too-long prompt); a rate-limit wait now
  prints "  Groq rate limit reached; waiting Ns"; a Paddle server that exits while starting
  says "The MLX-VLM server stopped while starting" (no "for PaddleOCR-VL").
- Tests: 315/316 pass. `test_convert_endnotes_pdf_to_valid_epub` (244 notes, expected 224)
  fails on main too, so it's unrelated to this refactor.
- Smoke test after the merge (main): `scratch/mini/run_all.py` (inputs cut by
  `scratch/mini/make_inputs.py`: 3 digital pages, 2 scan pages with and without text, a small
  EPUB) ran 20 paths in 106 s, all exit 0. They were extract-text, convert to all 6 formats,
  convert with a fixes file and with `--ocr redo`, ocr with tesseract and with paddle (the
  MLX-VLM server via ai-client), convert with `--ocr-engine paddle`, kindle on a scan
  (Apple Vision second reading) and on a digital PDF, ebook-to-pdf, find-book `--file`,
  virus-check on a link, and review's Groq step (5 rows, 5 suggestions).

## EPUB QUALITY PLAN (agreed with user 2026-10-19; phases 0-5 done; Tesseract cache, find_book CCEL + Cervantes done; PRs #31-#38 merged by the user 2026-10-20)
From "Philosophy EPUB vs reference" below. The user wants both EPUB (Kindle reading) and
PDF (annotating) from every book, so fixes go in the shared extraction/cleanup stages, not
in one writer. One PR per phase; run the reference score after each.

0. **Groundwork (fast).** Confirm the PDF output is built from the same extracted text as
   the EPUB. Sample pages of the philosophy PDF to find why accents are missing (dropped
   combining glyphs in extraction, or absent in the source). Turn `scratch/epub_compare.py`
   + `scratch/epub_worddiff.py` into a repeatable "score against reference" check.
1. **Quick wins (fast).** No h1 from copyright lines or long sentences. Curly quotes and
   apostrophes in text cleanup (both outputs). Rejoin hyphen-split words (leftover
   "leza", "ción", "miento").
2. **Italics + h3 (user's top priority, largest change).** Carry italic/bold font flags
   from PDF spans to `<i>`/`<b>` in both outputs; detect h3 subheadings from font
   size/weight. Accent protection (3) depends on this.
3. **Accents.** If (0) shows extraction drops them, fix at the root. Otherwise dictionary
   approach (pattern of `restore_macrons`): restore only when the unaccented word is not a
   word and exactly one accented form is (categorico → categórico); ambiguous ones
   (publico/público/publicó, esta/está) go to a report. Protect italics, quotes,
   bibliography and foreign-language notes (French "Paris" is right). Misread letters
   (empiismo, Königssberg, desarrolloos) as suggestions from the same check.
4. **Notes (discuss first).** First detect the missed note references (ours 689 sup + 684
   aside vs 1419 in the reference). Then layout: proposed EPUB popup footnotes
   (`epub:type` noteref/footnote, back-links, text at chapter end), PDF notes at page foot.
   Ask user: original has footnotes or endnotes? Match the original or optimise for reading?
5. **Index as links (discuss first).** Keep the book's index; link each page number to its
   `page_mark` anchor (page-level, not word-level; ask user if fine). Show original page
   numbers in the PDF margin for citing. Hard part: parsing sub-entries, ranges, "ss.",
   "passim", "véase" (link to other entries), printed vs PDF page offset.

Phase 0 results (2026-10-19, branch `feature/epub-quality-0`):
- Same text: `convert_pdf` builds one block stream (Paddle or text layer -> margin
  estimates -> `Review.apply` -> `drop_notes`) and hands it to whichever writer; PDF and
  EPUB differ only in layout (`notes_at` is PDF-only).
- Accents (`scratch/accent_probe.py`, crops in `scratch/accent_probe/`): the scan prints
  them (categórico in italics, teología/conclusión in small print, Difícilmente, albedrío
  in body text); Paddle drops some: categorico 18 vs categórico 44, teologia 8/95,
  conclusion 9/40, albedrio 4/0. Bibliography entries print "Paris" (correct as is).
  The PDF's own text layer (`scratch/text_layer_accents.py`) has every accent: París 194,
  Berlín 65, categórico 58, teología 99, no unaccented forms (it also writes "París" for a
  printed "Paris" in the bibliography). So phase 3 = fix at the root: where a Paddle word
  equals a text-layer word on the same page with its accents stripped, take the
  text-layer form. The dictionary approach is only the fallback for scans with no layer.
- Score: `tools/epub_score.py REF.epub OURS.epub` (replaces the two scratch scripts).
  Baseline, `scratch/fixed_philo/book_1-462.epub` vs `test_pdfs/philosophy_epub_good.epub`:
  words 198574 / 206683, docs 29 / 59, h1 11 / 25, h2 162 / 185, h3 81 / 0, italic
  2750 / 0, sup 1419 / 689, noteref links 0 / 689, bad headings 2 / 2, straight quotes
  56 / 467, curly 2423 / 2056, lost accents 136 (64 words), split words 23, words not
  in the reference 2423. "split words" has some false hits ("restaurar los").
- Fixed on the way: `import pdf_worker.paddle_ocr` (or `ocr`) failed with a circular
  import (ocr -> convert -> book_metadata -> find_book -> ocr); `book_metadata` now
  imports `find_book` inside `_edition`. `scratch/book_build.py` works again.

Phase 1 results (2026-10-19, branch `feature/epub-quality-1`, on top of phase 0):
- New `tidy.py` (`tidy(blocks)`, run in `convert_pdf` after `Review.apply`, so every
  format gets it and review finds still see the OCR's straight quotes): curly quotes and
  apostrophes (d’Holbach, “la canalla”; a quote after a page mark opens); copyright
  headings (©, ISBN, "Impreso en", "Depósito legal" ...) -> small paragraph; a heading of
  8+ words ending in "." -> paragraph. Tests `tests/test_tidy.py`.
- Copyright lines were h2 in the current build (not h1 as first noted).
- `fixes.py` `_join_split`: also joins across a space when the first part is not a word,
  the second has 3+ letters and the joined word is known ("deter minado", "conoci
  miento", "ab soluto", "provo que"). Checked every new join on both books
  (`scratch/join_check.py`): 9, all right. Test added to
  `test_joins_words_split_at_line_breaks`.
- Rebuilt philosophy EPUB (`scratch/phase1_philo/`, review file backed up as
  `scratch/philosophy.fixes.before-phase1.tsv`). Score: bad headings 2 -> 0, straight
  quotes 467 -> 4 (the 4 are HTML attributes), curly 2056 -> 2519, split words 23 -> 18,
  h2 185 -> 182. Review file: 4 rows went stale (fragments now joined: ignored "conoci",
  "com", "pre", and the replace "teo ría"); 1 new row ("pre" in "pre-kantiano", now
  under the 2-occurrence limit).
- Left: "su ministrar", "des cubrimiento", "bus carse" (both halves are words), "Critic a",
  "acompañ a" (one-letter tail), "Mon tesquieu", "Les sing" (names).
- Seen for phase 2: Paddle writes some italics as Markdown, `*De l'esprit*` (31 lines in
  the txt): a source of italics besides font flags.

Phase 2 results (2026-10-19, branch `feature/epub-quality-2`, on top of phase 1):
- Italic/bold travel as inline markers (`inline.ITALIC`/`END_ITALIC`/`BOLD`/`END_BOLD`,
  private-use U+E010-E013, around whole words, punctuation outside). `plain()` drops
  them; EPUB/HTML/PDF render `<i>`/`<b>` and Markdown/Word `*`/`**`, styling each text
  piece by the state at it, so unpaired markers (left by review fixes) can't break XHTML.
- Sources (new `styles.py`): text-layer books: span font flags (`footnotes._render_line`
  -> `styles.span_text`); body lines only, not text-layer footnotes yet. Paddle books:
  the philosophy scan's own text layer has Times-Italic (its words are worse than
  Paddle's), so each Paddle block's words are aligned (difflib, letters without accents)
  with the layer's words inside its rect and take their partner's style; a block whose
  words mostly don't match gets none. Plus Paddle's own Markdown `*...*`.
- h3: the reference's 81 h3 are all bibliography "Textos"/"Estudios" under numbered
  authors ("1. BAYLE"), same size as body text, so not a font-size rule: `tidy` puts a
  short capitalised heading (<= 2 words, no digits, not all caps) after a numbered
  heading of the same level one level down. Headings lose italic/bold markers.
- Fixed on the way: review finds match across style markers (`fixes._word_pattern`);
  `join_lines` dehyphenates across markers; margin-mark trimming (`margins.py`) sees
  through an italic "b"; `extract-text` output strips the markers.
- Score (`scratch/phase2_philo/`): italic tags 0 -> 3717 (ref 2750); italic words 10382
  vs ref 9037, 88% of the ref's italic words found (`scratch/italic_words.py`). Our
  extras are mostly the index's "véase también" (italic in print; the ref has no index),
  "a priori", "infra"; misses: "Crítica" (accent lost, phase 3), "ibid". h3 0 -> 65
  (ref 81; "Textos"/"Estudios" under unnumbered "Capítulos X-XVI: Kant" stay h2). XHTML:
  60/60 files parse. Review file unchanged by the rebuild. Ratzinger (born-digital):
  422 italics, all sampled right ("Verum quia factum", "Divina Comedia").
- Note: `test_pdfs/Introduction to Christianity by Ratzinger.epub` is our own earlier
  output, not a reference.

Phase 3 results (2026-10-19, branch `feature/epub-quality-3`):
- `styles.apply_layer` (was `apply_styles`): a Paddle word aligned (equal key) with a
  text-layer word takes the layer's accents when every other letter is the same and the
  Paddle word has no accent of its own ("público" stays, not the layer's "publicó"); a
  different letter is a misreading, left alone. The layer's line-end hyphens are joined
  first ("cate-" "górico"), and Paddle words are split at em dashes ("categorico.—El").
  `layer_words` no longer returns [] for a layer without italics (accents need it).
- Fixed on the way (phase 2 bug): a note ref after an italic word got the end marker
  inside it (`[^2<END>]`); `_WORD_RE` keeps trailing refs outside the style.
- Score (`scratch/phase3_philo/`): lost accents 136 (64 words) -> 51 (32 words). Left:
  Munich 14, Simon 3, Baron 2 (the layer has them unaccented, right as printed), French/
  English titles (Considerations, Maximes, Revolution) and ~20 single words where the
  layer misreads the word too. Italic words 10382 -> 10752, 89% of the ref's. Words not
  in the reference 2411 -> 2384. XHTML 60/60 parse; review file unchanged.
- Not done: the dictionary fallback for scans without a usable text layer (plan item 3);
  no book needs it yet.

Phase 4 results (2026-10-19, branch `feature/epub-quality-4`):
- No missed note references: the reference's 1419 `<sup>` = 686 notes x2 (ref + note
  number) + 47 bibliography ordinals ("2.ª ed."). Ours: 689 refs, same per chapter.
- User decided: notes numbered 1-N through the book; EPUB keeps one notes file at the end
  (popup footnotes, back-links); PDF notes at the page foot with the EPUB's numbers.
- `epub._EpubBuilder._number`: numbers come from the order references are first seen,
  not the printed labels (which restart at 1 per page). A note met before its reference
  waits for it; a note with no reference is numbered after the last one; notes.xhtml is
  written in number order. HTML and PDF are built from the EPUB, so they follow; Word
  (Pandoc) already numbered 1-N.
- txt/md keep the printed labels (`[^p12-1]`): `tests/platon_score.py` matches notes by
  printed number. A first try renumbering in the shared pipeline broke it (refs_ok 9).
- Trade-off: EPUB/PDF numbers no longer match the printed book; cite by page.
- Tests: fast 257, full 274 pass. Built `scratch/phase4_philo/`; check with
  `scratch/phase4_check.py EPUB PDF`.

Phase 5 results (2026-10-20, branch `feature/epub-quality-5`):
- User decided: index links go to the word on the printed page, else the page top; no
  "véase" links; the index shows no page numbers in EPUB, HTML and PDF, only numbered
  marks per entry ("Kant [1] [2] [3]"); the reflowed PDF shows its own page numbers only.
- Page labels (Paddle path): pages without a printed number took index + 1 (39 of 461
  wrong, labels 1-5 used twice). `paddle_book.printed_labels`: a reading counts when a
  neighbouring reading agrees; other pages count on from the last one that counts (scan
  gaps keep working); before printed page 1, Roman numerals. Now all 461 = index + 5.
- `index_links.link_index` (EPUB/HTML/PDF only; txt/md/docx keep the numbers): from an
  "Índice"/"Index" heading to the next heading of the same level, page groups become
  numbered link marks with target `w:<page>:<headword key>`. Digits inside page marks and
  margin refs are skipped; an index already linked in the PDF is left alone. The EPUB
  keeps per page the word keys (4-6 letter prefixes, crc32 in sorted arrays) of each
  paragraph part and links to the first that has the entry's headword.
- Philosophy: 4634 index links, 2470 to the paragraph with the word, 2164 to the page top,
  0 broken; 24 numbers left plain (years in the bibliography, groups with a misread number).
  Score as phase 4 except words not in reference 2384 -> 2282. XHTML 0 errors.
- Builds are slow (~12 min EPUB, ~40 with PDF): Tesseract runs again on every page; Paddle
  is cached. Next: cache Tesseract per page (user asked for it).

Tesseract cache (2026-10-20, branch `feature/tesseract-cache`):
- `tesseract_cache.run`: every Tesseract read of a page or crop (margin_refs, mixed_script,
  consensus; missing_refs via margin_refs) keeps its stdout on disk, keyed by image +
  arguments (`PDF_WORKER_TESSERACT_CACHE`, default `~/.cache/pdf-worker/tesseract`). Failed
  runs are not kept. Tests use a per-test folder (`tests/conftest.py`).
- `missing_refs.PaddleClips` keeps each crop's text in `<paddle cache>/clips` (keyed by PDF
  path, page, region); the Paddle server starts only for crops not read before.
- Philosophy EPUB rebuild: 1070 s cold -> 159 s warm, output identical (66/66 files).
- `scratch/book_build.py` writes `OUTDIR/build.log` (time, page n/462) and keeps both
  caches in `scratch/`.
- Shortcuts: cache keys leave out Tesseract's version (clear the folder after an upgrade);
  crop keys use the PDF path (a PDF changed in place keeps old crop readings).

Second reference book: user to supply a good EPUB of the **same edition** as one of their
PDFs, ideally with a different note style (endnotes vs footnotes), scanned vs text-layer,
or another language. Score both books from phase 2 onward so fixes don't overfit.
Risk: phases 2 and 4 change the core pipeline, so rebuilt books may differ from earlier output.

## PLAN — start here (written 2026-10-19): make the pipeline work for all books
State: branch `feature/find-book-review` (since merged into main, a4f614e): find-book +
ebook-to-pdf, bibliography fix, find-book ranking/Elejandría/--url, `pdf-worker review`,
spelling only on OCR'd text. Fast tests pass (233). Works end to end on Platón,
philosophy (Paddle scans, review rounds 1-2 merged and rebuilt) and Marianela (Elejandría
born-digital PDF). Not ready for "all books": too few kinds tested.
Philosophy: 0 open spelling rows; 5 note-no-ref + 1 ref-no-note (TSV by hand).
Platón: 3 stuck replaces (below), 50 note/margin rows (TSV by hand).

Steps, in order (ask the user before merging the branch):
1. Stuck fixes (small, shows in every review round):
   a. `review.open_rows` shows stale replaces whose value is already in the text
      (philosophy: 5). Skip them: needs the built text, or mark them in `Review.finish`
      (value found on the page -> not stale).
   b. Replaces that never apply: words OCR ran together ('juiciocomún' -> 'juicio común',
      'mezclóde', Platón ids 437, 465) and a word split by a margin ref ('estre [74a] cha',
      id 508). Find why the find doesn't match the blocks at apply time (hyphen joins
      after apply? margin ref inserted before?) and fix it once in `fixes.py`.
2. Test 3-4 books unlike the ones done; for each count problems per step (find, OCR,
   build, review rows, rebuild) and fix what breaks:
   - an English scan (spelling check in English, find-book in English);
   - a modern Spanish scan with no notes;
   - a book with pictures or tables;
   - a two-column book.
   Use find-book to get them (legal sources only). Paddle is 12-24 s/page: pick short
   books (< 200 pp.) or a page range with `scratch/book_build.py`.
3. Tesseract path (easy PDFs only, user 2026-10-19): `review` has no crops without the
   Paddle cache; Timeo via Tesseract lost all margin refs, linked no notes and made one
   chapter per page. Decide with the user whether to fix or just document it.
4. Notes and margin rows stay manual (the model can't see where a number sits on the
   scan). Maybe later: show them on the review page with the scan crop, user only.
5. Older open items: reflowed PDF notes can overlap the text (`--notes end` workaround,
   see TODO at the end); Paddle wrong letters (ū, ę, Cyrillic look-alikes); spelling only
   for es/en.
6. Merge `feature/find-book-review` into main once the user agrees.
Not to do: the 1903 Marianela scan (user: the digital version is enough).

## Book metadata from the book itself (2026-10-19, merged: PR #30)
Asked: PDF metadata is often wrong (Ratzinger's author was "MANUEL", Word's account
name); find title, author, translator, language, publisher and year in the text.
User decisions: title in the edition's own language; ISBN lookup on by default with a
quiet fallback offline; no AI fallback yet.
- New `book_metadata.py` (`find_metadata`), called from `convert_pdf` (so `convert` and
  `kindle`). Order per field: given flag > PDF metadata if plausible (account names,
  single words not printed on the title page are rejected; "Gibbon, Edward, 1737-1794"
  -> "Edward Gibbon") > front pages (title page by type size, "Por X" bylines,
  publisher line, copyright year) > ISBN via Open Library (`find_book.isbn_edition`,
  10 s timeout; its records have typos, so it comes after the pages) > file name.
  All-caps titles recased ("Introducción al cristianismo", "The 9/11 Commission Report").
- Language: unchanged (guessed from the text, which is the edition's).
- `convert_pdf(source_pdf=...)`: an OCR'd copy uses the original's metadata and file
  name (replaces the removed `pdf_title`). CLI prints where each field came from.
- Written to EPUB (dc:publisher, dc:date, translator as contributor) and Markdown/Word
  YAML (publisher, date). PDF output: only title/author (PDF has no publisher field).
- Checked on 15 test_pdfs with `scratch/try_metadata.py`; tests in
  `tests/test_book_metadata.py`. Full suite 264 passed; ruff clean.
- Known limits: paddle-only books (no text layer) get no type-size title page; the
  file-name title keeps "by X" / "- X" parts when it is the fallback.

## Feature: `find-book` and `ebook-to-pdf` (2026-10-17, on `main`, not committed)
Asked: a command that prompts for book details, finds a PDF/EPUB/text in online
libraries, downloads the best, checks quality and suggests (and offers to run) the next
step. User: personal use; sources Gutenberg, Internet Archive, Standard Ebooks,
Wikisource/HathiTrust "and more places"; search by title, author, ISBN, edition;
English and Spanish, academic (philosophy, theology), novels, classics in translation;
usually wants a clean PDF and an EPUB; offer to run the next step.
- `src/pdf_worker/find_book.py`: searches (in parallel, stdlib `urllib` only) Gutenberg
  (OPDS search; plain words: the `t.` prefix found nothing for "t.Don t.Quijote"),
  Standard Ebooks (search page; file URL needs `?source=download`, else a "download
  started" HTML page), Internet Archive (advancedsearch, no `access-restricted-item`;
  file picked from `/metadata/<id>/files`, Text PDF first), Open Library (ISBN -> the
  edition's title and language, the work's author and free IA scans), Wikisource
  (search API + ws-export EPUB), DOAB (OpenSearch Atom; link only), HathiTrust (ISBN
  only; link only). Ranking: title-word share, author surname with fuzzy spelling
  (Dostoevsky/Dostoyevsky), translator, language, year, asked format (+30), source
  quality; with no format asked, a real (non-IA) EPUB gets +15 since it yields a clean
  PDF and EPUB with no OCR. Download is streamed to a temp file, checked by magic bytes
  (%PDF / PK), then `os.replace`. Check: `assess_text_layer` for PDFs (steps: convert to epub/pdf, or
  ocr then convert the `.ocr.pdf`), MuPDF text sample for EPUBs (step: ebook-to-pdf).
- `src/pdf_worker/ebook_to_pdf.py` + `ebook-to-pdf` command: MuPDF lays the EPUB out on
  A5 with margins (`apply_css @page`), keeps the TOC as bookmarks. Removes U+FEFF/U+2060
  first (MuPDF drew "pity﻿—for I" as "pity —forI"). `convert_to_pdf(from, to)`
  fails for ranges not starting at 0, so the PDF is built in one go (in memory).
- CLI: `find-book` (flags or prompts when run in a terminal with no details),
  `ebook-to-pdf`; cheat sheet + README section. Tests: `tests/test_find_book.py` (16,
  no network: `_get`/`urlopen` faked).
- Live runs (scratch/books): Confesiones/es (IA text PDF), Crime and Punishment +
  Garnett (Standard Ebooks EPUB), ISBN 0140449132 (Standard Ebooks), De civitate Dei/la
  pdf (IA scan -> OCR steps with `--lang lat`), Don Quijote/es (Gutenberg EPUB);
  ebook-to-pdf on Crime and Punishment (562 A5 pages, checked a rendered page).
- Default download folder is the current folder (`-d` to change), like the other
  commands' "next to the input"; not scratch/books as first proposed.

### Modern books and Spanish sites (2026-10-17, same branch, not committed)
User asked for sources of modern books. Shadow libraries (LibGen, Anna's Archive,
Z-Library) were declined; DRM removal too. User chose: OpenAlex, `--url`/`--file`, a
config file for their own sites; then "add good Spanish sites (e.g. Elejandría)".
- OpenAlex (`_openalex`): `/works` with `title.search` (or `raw_author_name.search`),
  `type:book|book-chapter`, `is_oa:true`, `language:`; the first location with a
  `pdf_url` is the download, else link only. Optional `openalex_api_key` in the config
  (keyless requests share a small daily budget per IP).
- Elejandría (`_elejandria`): its search is Google CSE in the browser (and /buscar is
  disallowed in robots.txt), so the 400 KB sitemap (2341 books as
  /libro/<title>/<author>/<id>) is matched instead. On download, the book page's
  "Descargar en ePub/PDF" button gives /libro/link_descarga_libro/<id>/<file>: the file.
  Its EPUBs can be page images (Zorrilla: 380 pages, 21k characters); the check flags
  that and says to try the PDF.
- textos.info: built-in `Site` on its OPDS search `busqueda.atom&query=`.
- Config file `~/.config/pdf-worker/find-book.toml` (`--config`): `[[sites]]` with
  `name`, `search` (`{query}`), optional `quality`. A site may answer OPDS (acquisition
  links, EPUB preferred) or HTML (links to .pdf/.epub become results).
- `Candidate.resolve` replaces the Internet-Archive-only lookup: finds the file URL on
  download. `download` now takes the format from the file's first bytes (%PDF / PK).
- `--url` downloads and checks one link; `--file` checks a local file. MuPDF's CSS error
  messages are hidden while checking/laying out EPUBs (`quiet_mupdf`).
- Tests: 22 in `tests/test_find_book.py` (OpenAlex, Elejandría, config sites OPDS/HTML,
  config validation, `--url`, `--file`); a fixture keeps the user's real config out.
- Live: Confesiones/es (textos.info first, Elejandría second), Niebla/es with a test
  config site (`scratch/find-book-test.toml`), Elejandría PDF and EPUB downloads,
  `--url` (Gutenberg), `--file`.
- Also tried, blocked: Biblioteca Digital Hispánica (BNE "Revisión de Seguridad" page),
  SciELO Books (bunny-shield challenge), Freeditorial (search 404). BNE items reach
  OpenAlex via Hispana as links. Possible later: eBiblio lending links (no public API).
- No format asked: a real (non-IA) EPUB gets +15 in ranking (clean PDF + EPUB, no OCR).
- README: "Pipeline overview" section (text diagram + table of sources).

### More sources: ebook stores and open textbooks (2026-10-17, not committed)
User asked about free books on Amazon, Apple Books and other ebook sites. Amazon/Apple
free titles are DRM'd $0 purchases with no download API: not usable. Probed
(`scratch/probe_sites.py`, `probe_robots.py`, `probe_details.py`):
- Added `_openstax`: CMS API list (~130 books, 11 Spanish), live ones with a PDF,
  matched by title locally. Quality 10.
- Added `_open_textbooks` (Open Textbook Library, `textbooks.json?q=`; only `q` filters):
  a format URL ending .pdf/.epub becomes the download, else link only. Most point to
  Pressbooks (403 to scripts). Quality 5.
- Added `_global_grey` (English only): sitemap `<author>_<title>_complete-text.html`;
  resolve follows "Download ebook instead" (-ebook.html, not guessable from the slug) to
  the .epub/.pdf links. Quality 10. Live: Meditations EPUB (valid, 303 pages) and
  OpenStax "Introducción a la estadística" PDF (935 pages, good text) downloaded and
  checked (`scratch/try_new_sources.py`, `try_new_download.py`).
- Left out: Smashwords (robots.txt forbids /books/search and /books/download),
  Feedbooks (robots.txt disallows all but /), ManyBooks and Kobo (403), LibreTexts
  (no public search API; its pages come via OTL), Google Books (429 again).
- Tests: 3 new (25 in test_find_book.py); fast suite 220 passed; ruff clean.

### Blocked / left out (find-book)
- DOAB item pages and OAPEN (API and pages) sit behind an Anubis bot check; DOAB's REST
  API answers "address not allowed". DOAB stays as link-only results; OAPEN left out.
- Cervantes Virtual and PhilArchive: Cloudflare bot challenge. Left out (not bypassed).
- Google Books: keyless quota is 0 ("Queries per day" limit 0); would need an API key.
- CCEL: its search URL returns the home page; Perseus has no simple download. Left out.
- Interactive prompts were tested with faked `input`, not in a real terminal.

## REVIEW PLAN (agreed with user 2026-10-16) — in progress, branch `feature/review-plan`
Goal: every conversion follows one book structure, and the user fixes OCR errors in a
review file (edited in Cursor) instead of in the output. Cheap after OCR (Paddle is
cached), so rebuilding often is fine. Decided: no Typst for now (notes go at the end;
MuPDF layout is enough); no index/bibliography work (kept as plain text); margin refs
accuracy (Platón 645/714 right line, 38 wrong, 31 missing, 5 extra) is good enough.
Book order: cover -> book's own title/edition pages -> generated contents -> preface ->
text -> appendices/bibliography/index -> notes. Front matter is fine as is.
1. Text cover, all formats: title + author (+ translator if metadata/title page gives
   one) in big type, replacing the page-1 scan. PDF/docx: first page. EPUB: that page
   rendered to an image (Kindle needs an image for the library thumbnail).
2. Reflowed PDF: the new PDF's own page numbers, centred at the foot, not on the cover.
   (Printed edition's page numbers not wanted in the PDF.)
3. One file `<pdf stem>.fixes.tsv` next to the PDF (`--fixes PATH` overrides). Columns:
   `id, page, kind, find, context, action, value, status`. Each build: applies rows with
   an action to the blocks before any writer (so writers stay unchanged); appends new
   suspicious items with empty action; keeps user rows; marks rows whose `find` vanished
   `stale`. Written atomically. Actions: replace, ignore, attach, drop, accept, move, add.
   `find` = exact text on that page (page `*` = whole book); if it occurs twice, apply to
   the first and flag as ambiguous. Examples:
   - `27 spelling ipodrias replace ¿podrías` (that page only)
   - `* spelling Eutifrón ignore` (never flagged again)
   - `* chars Būtzow replace Bützow` (whole book)
   - `804 note-no-ref c3-6 attach Herder` (superscript inserted after "Herder")
   - `285 ref-no-note c9-2 drop` (orphan superscript removed)
   - `27 margin-est ~21b accept` / `move Sócrates` (estimate -> normal / moved)
   - `31 margin-missing 21c..21e add "21d before pero"`
4. Kinds flagged: spelling (es/en only, `pyspellchecker` into .venv + pyproject; only
   words occurring <= 2 times in the book; skip italics and Greek; other languages: no
   spelling check), odd chars (ū for ü, Cyrillic look-alikes, stray `$`), note-no-ref,
   ref-no-note, margin-est, margin-missing. Wrong-line margin refs can't be detected.
5. Unit tests (apply fixes; merge on rebuild keeps user rows, marks stale). Trial on
   Platón and philosophy: report row counts per kind, esp. Spanish spelling noise, BEFORE
   going further. Log decisions here.

Progress (2026-10-16):
- [done] 1+2. `cover.py`: text cover (author, title, "Traducción de X") as PDF page 1,
  Word page 1 (Pandoc title block + raw OpenXML translator line and page break), EPUB
  cover image (rendered from that page). Translator found on the first 6 pages
  (Paddle blocks, then text layer): philosophy "Manuel Sacristán", Platón "M. Ángeles
  Durán y Francisco Lisi". `Metadata.translator`. md/html/txt unchanged (they already
  open with the title/author). Reflowed PDF: page numbers centred at the foot, = the
  PDF's own page numbers (cover is 1, unnumbered). `--no-cover` now covers PDF/Word too.
  Title is still metadata/file name (philosophy shows "philosophy"; use --title).
- [done] 3. `fixes.py` (`Review`): applies rows, flags, merges, statuses `applied` /
  `ambiguous` / `stale`; `convert --fixes PATH`; default `<stem>.fixes.tsv` next to the
  original PDF (CLI and kindle pass it, so OCR temp copies don't get it). Page = printed
  page label from the page marks. `add` value: `21d before pero`. Words written in a
  `replace` value are never flagged. Not covered: Gloss and Table text.
- [done] 5. Unit tests `tests/test_fixes.py`, `tests/test_cover.py`. 187 fast pass.
- 4. Italics: the block text carries no italics, so "skip italics" can't be done.
- TRIAL (Platón, `scratch/book_build.py ... txt --margin-refs --estimate-margin-refs`,
  rows counted with `scratch/fixes_counts.py`): spelling 4943 (!), chars 21, note-no-ref
  4, ref-no-note 6, margin-est 40, margin-missing 0 (estimates fill the gaps).
  Spelling is noise: pyspellchecker's Spanish list has 86k words and lacks most
  inflections ("normas", "sujetos", "explicamos"). A crude stemmer
  (`scratch/spell_stem.py`) leaves 2214, still mostly valid words (pudiésemos, componen,
  ignore). Real hits do exist: esla, ban (=han), deberlan, Atcnas, rla, and split words
  from hyphenation (atribui-mos, intro, dremos). chars: mostly transliterated Greek
  (thēin, phrónēsin) = noise in a Platón book; real: `$`, `pāg`, `sōphrosyñē`.
  Philosophy (`book_build.py ... 1-462 scratch/review_trial txt`): spelling 6065 (3126
  after stemming; 1328 capitalised, mostly bibliography names/German/French titles),
  chars 6 (all real: volūmenes, ūber, Būtzow, SCHŌNEBAUM, ВоHATEC, Germānicas),
  note-no-ref 5, ref-no-note 1.
- User chose a full-form dictionary. Now: LibreOffice Hunspell dictionaries (es_ES,
  en_US; licence notes alongside) in `src/pdf_worker/dictionaries/`, read by `spylls`
  (pure Python, 0.1 ms/word; replaces pyspellchecker in pyproject). Words of 5+ letters
  the English dictionary knows are excused (bibliography titles); shorter ones stay
  ("ban" for "han"). Re-trial: Platón spelling 1315 (was 4943); philosophy ~2100 (was
  6065; 2500 before the English filter, of which 412 English). What's left: real
  misreadings (becho, dcdicaban, Icyenda, Posiblc), missing accents (pudieramos,
  logico), fragments of words split at line ends (niciones, tamiento, apli), and
  names/German/French/Greek transliterations (best silenced with `* ignore` rows).
  Capitalised words are kept: they include real errors (CuaI, Fúlebo).
- User: spelling only in the body text. Now skipped: notes, small print, sections under
  a Bibliografía/Índice/Index/Referencias heading (until a heading of the same or higher
  level), and paragraphs that look like entries ("MAIGRON, L., ..."; or < 300 chars with
  a year and 3+ commas): philosophy's "BREVE BIBLIOGRAFIA" has subheadings of its own
  level. Measured with `scratch/body_spelling.py`: Platón 541 rows (notes had 708),
  philosophy 1303 (was ~2100); what's left in philosophy is mostly German/French/Latin
  quoted in the text, plus real errors (veemos, teniendolo, Jámás, presu).
- Dictionary fix: es_ES lists which pronouns each verb takes, so "basarlo", "evitarle"
  were flagged. `_knows` now also accepts infinitive/gerund + 1-2 enclitics when the bare
  verb is known (Spanish only). ("averiguemos" stays flagged: correct is "averigüemos".)
- Error analysis (`scratch/classify_spelling.py PDF RANGE [--margin-refs]`, from cached
  OCR; de/fr/it/la dicts in `scratch/dicts` from wooorm/dictionaries, analysis only).
  Buckets by priority: hyphen (joins with neighbour word), foreign, accent (one accent
  toggle), ocr1 (one edit), name (Capitalised), unknown. 20 random rows per bucket
  hand-checked (precision = share that are real errors):
  | bucket | philosophy rows | real | Platón rows | real |
  | hyphen | 21 | ~90% | 16 | ~100% |
  | accent | 47 | ~100% | 54 | ~85% |
  | ocr1 | 219 | ~65% | 221 | ~90% |
  | foreign | 635 | ~5% | 105 | ~20% |
  | name | 116 | ~5% | 51 | ~20% |
  | unknown | 241 | ~15% | 80 | ~55% |
  Estimated real errors: philosophy ~280 of 1279, Platón ~335 of 527.
  Seen: words split at paragraph/page starts (tieron, gún, cidad, dencia, mientos),
  old orthography (atribuído, solicitásteis), dictionary gaps (rehúye, Considerémoslo,
  capitación, inherencia). ocr1 suggestions often wrong (lan→la, should be tan).

## Spelling refinements (2026-10-16, branch `feature/spelling-refine`)
Steps 1-4 of the list below are done (commits bbfc11f, 9b6834d, 8e1ed08); step 5 below.
Blocked: nothing. Background job output files (outside the repo) can't be read, so the
scratch scripts write their reports into `scratch/`.
- 1. Foreign words: de/fr/it/la Hunspell dictionaries from wooorm/dictionaries copied to
  `src/pdf_worker/dictionaries/` with their licence files (de: GPL-2.0 OR GPL-3.0, fr:
  MPL-2.0, it: GPL-3.0, la: GPL-2.0; all allow redistributing the files with the
  licence). `FOREIGN_LANGUAGES = en, de, fr, it, la`; words of 5+ letters any of them
  knows aren't flagged. Loaded on first use (`Review.foreign`, cached_property): loading
  all four takes ~3 s, which every unit test paid before.
  Result (`classify_spelling.py`): philosophy 1279 -> 708 rows, Platón 527 -> 446.
- 2. Split words. Causes found by sampling the raw Paddle rows (`scratch/raw_breaks.py`,
  `raw_chars.py`, `built_around.py`):
  - Paddle writes most line-break hyphens with no space ("inmor-talidad"); the old
    `_BROKEN_WORD_RE` only handled "Pro- tarco".
  - Words broken across pages ("some-" + "tieron") were joined with the page mark in
    the middle ("some⟨mark⟩tieron"), and `Review` splits text at page marks, so both
    halves were checked as words. Same for a margin reference on the second half
    ("invo- ⟨108d⟩car").
  - Some breaks lost the hyphen ("por ciones", "año ranza", "Durante al" + "gún").
  Fixes: `paddle_book` puts the page mark (and a leading margin reference) before the
  whole word, and `_body_text` puts a margin reference before "invo-". `Review` joins
  with the dictionary (`_join_split`, before applying fixes): a hyphen pair when the
  joined word is known ("place-res" too, both halves being words); across a space only
  when the second part is a fragment (unknown, 2+ letters) and the joined word is known.
  Checked on all joins in both books (`scratch/hyphen_joins.py`): the hyphen rule also
  joins prefixes RAE writes joined (auto-impuestas, tras-fondo, ex-votos, a-moral: the
  last may be the author's own hyphen). Rejected after checking: joining across a space
  when the first part is unknown ("confies en" -> confiesen, should be "confíes en";
  "conclusion es"; "per la"), and joining old "acallar á" -> "acallará".
  "cosa-en-sí", "físico-químico", "Jean-Jacques" stay.
- 3. Review file: new column `type` (after `kind`, so the order is `id, page, kind,
  type, find, context, action, value, status`; old files read fine). Spelling types:
  `accent` (value pre-filled with the one-accent fix, action left empty), `ocr1: <word>?`
  (one edit or a common misreading such as rn/m: a guess only), `name`, `unknown`. The
  hyphen and foreign buckets went (steps 1-2). New rows are sorted: other kinds first,
  then spelling by type, page order within. The one-edit search uses plain dictionary
  lookups and runs only for flagged rows: 8 s for Platón, 24 s for philosophy (was ~10
  min in the classify script). Sample: accent fixes mostly right (aqui, incluias,
  necesitarias), some wrong (leno -> leño, should be lleno); ocr1 guesses often wrong.
- 4. `dictionaries/es.extra.txt` (capitación, considerémoslo, inherencia(s),
  rehúye(n)), and Spanish superlatives (correctísima, larguísimo, riquísimos) in `_knows`.
- Measured after 1-4 (`scratch/measure_review.py`, from the cached OCR, no margin
  estimates): Platón 409 spelling rows (accent 62, ocr1 215, name 52, unknown 80);
  philosophy 640 (accent 50, ocr1 218, name 126, unknown 246). Build time is the same
  with and without `Review` (500 vs 530 s for Platón).

### Step 5: the pipeline on new books (2026-10-16)
Eight public-domain Spanish scans from Internet Archive, each with a Project Gutenberg
text, plus `Timeo-Platón.pdf` from `test_pdfs/` (no reference) and the bad Platón scan
against `platon_dialogos_vi_good.pdf` (a Lectulandia ebook of the same Gredos volume).
Scans in `test_pdfs/<name>_<year>.pdf`, PG texts in `test_pdfs/refs/pg<id>.txt`,
15-page excerpts in `test_pdfs/excerpts/` (none committed).
How: `scratch/run_excerpts.py` cuts the excerpt and runs `convert --to txt --ocr force
--ocr-engine paddle` (210-350 s per 15 pages); `scratch/rebuild_excerpts.py` rebuilds
all from the Paddle cache with the current code into `scratch/excerpts_build/` (fresh
review files, `summary.txt`); `scratch/wer.py` / `wer_all.py` find the excerpt's span in
the reference from shared 4-word runs, compare body words only (note lines `[n] ...`
dropped) and also count leftover split words (`wer.txt`, `wer_<name>.diff`).
WER counts edition differences as errors: "accents off" ignores accents, which removes
the 19th-c. `á`/`ó` prepositions that PG modernised.

| book (IA id, pages) | kind of scan | WER | accents off | spelling rows/page | split words |
| Sombrero 1907 Holt (elsombrerodetre00alar, 41-55) | footnoted school ed., handwritten English glosses between the lines | 6.3% | 3.3% | 4.3 | 1 |
| La Barraca 1901 Sempere (labarracanovela00blas, 41-55) | clean; PG is a revised edition (whole phrases differ, checked on the scan) | 10.1% | 9.0% | 2.1 | 2 |
| Niebla 1914 (nieblanivola00unam, 41-55) | clean | 1.6% | 1.1% | 2.2 | 2 |
| Pepita Jiménez 1901 Fé (pepitajimnez1901vale, 41-55) | clean; PG is the 1874 ed. | 4.0% | 1.6% | 2.4 | 2 |
| Marianela 1888 (marianela00prez, 41-55) | clean; PG is the 1878 ed. | 4.7% | 2.5% | 5.7 | 3 |
| La Gaviota 1856 (lagaviotanovelao01caba, 61-75) | old print, old accents | 7.4% | 3.2% | 5.3 | 0 |
| Lazarillo 1900 L'Avenç (lavidadelazaril00tormgoog, 30-44) | Google scan, 1554 spelling, variant notes | 25.3% | 17.0% | 23.6 | 1 |
| Doña Perfecta 1897 Ginn (doaperfectanove01galdgoog, 60-74) | Google scan, same edition as PG | 3.6% | 1.4% | 3.7 | 0 |
| Platón bad (60-74, cached OCR) vs good ebook | bad scan | 4.7% | 4.4% | - | 1 |
| Timeo-Platón (241-255) | bilingual Greek/Spanish | - | - | 0.3 | - |

Spelling types (accent/ocr1/name/unknown): Sombrero 15/33/2/15, Barraca 8/10/2/11,
Niebla 4/17/4/8, Pepita 6/18/1/11, Marianela 25/37/8/15, Gaviota 35/30/3/11, Lazarillo
42/226/6/80, Perfecta 10/23/7/16.
Findings:
- OCR is good on clean scans: 1-2.5% with accents off where the edition matches.
  Lazarillo's 17% is the edition (1554 spelling: vn, dixo, cabeça; PG modernises), the
  OCR matches the page (checked on the scan).
- Old orthography floods the review file: Gaviota and Marianela's accent rows are
  mostly the edition's own accents (ponia, oian, vió, lábios), Lazarillo has 354 rows.
  This is the open question below.
- `¡` read as a letter: "jtú", "ivenga", "ijaque" (Niebla), ";Tendria", "iY" (Gaviota).
  `restore_question_marks` does this for `¿` only.
- Lazarillo: the edition's variant notes are printed run together in one line ("1. Bu.
  la — 2. Bu. de aqueste — 3. ..."): they are not split, so 116 ref-no-note rows.
- Timeo-Platón: a bilingual edition (Greek left page, Spanish right). Each page goes on
  from the last mid-sentence, so Greek and Spanish are joined into 7 paragraphs over 15
  pages; its endnote references give 62 ref-no-note rows. Stephanus numbers ([47d]) are
  printed in the text.
- Sombrero: handwritten interlinear glosses become words ("handsome", "especially the")
  and corrupt the words they cross; printed line numbers are dropped (9 glosses).
- Split words left after the fixes: 0-3 per 15 pages, mostly capitalised ("Au gusto")
  or a space join with a known second half ("fue re").
- Not checked: paragraph counts against the references (Pepita has 23 paragraphs in
  15 pages: letters with long paragraphs, plausible but unverified); headings were
  counted only (Sombrero 8, Perfecta 6 in 15 pages: short chapters).

### User decisions (2026-10-16) and what was done
- Old spellings are not flagged (commit 4d59f0e). An edition is old when its body has
  at least 5 "á"/"ó"/"é" as words or "vn"/"vna", and at least 2 per 1000 words. There,
  a spelling row is dropped when the word is one accent off a known word (ponia, vió)
  or known after modernising its letters (`_MODERN_LETTERS`: ç->z, ss->s, x->j, u
  between vowels->v, initial v+consonant->u, -ava->-aba, z+e/i->c, y->i, ff->f,
  sc+e/i->c, ct->t; also v->b, and "de" run into the next word: dellas). Modern books
  keep their accent rows (there they are misreadings). Niebla (1914) isn't detected as
  old. Spelling rows per 15 pages: Lazarillo 354 -> 128, Gaviota 79 -> 43, Marianela 85
  -> 59, Sombrero 65 -> 50, Pepita 36 -> 30, Barraca 31 -> 23, Perfecta 56 -> 46.
  Lazarillo's rest: real misreadings plus old forms the rules miss (fuyme, vuiera).
- `¡` read as i/j/l/; before an exclamation is put back like `¿`
  (`restore_question_marks` does both now). Niebla WER 1.6% -> 1.3%.
- Bilingual editions (Timeo-Platón) are not supported for now.
- Review files regenerated with the final code: `test_pdfs/philosophy.fixes.tsv`
  (1-462) and `test_pdfs/platon_dialogos_vi_bad.fixes.tsv` (1-293, --margin-refs
  --estimate-margin-refs), via `scratch/book_build.py`.

## NEXT SESSION — start here (written 2026-10-16, end of session)
State:
- PR #28 (`feature/spelling-refine`, everything above) was merged by the user on
  2026-10-16. Start new work on a new branch from main.
- The user may fill in some rows by hand first (action/value columns); the PLAN below
  takes over the rest. Review files:
  `test_pdfs/philosophy.fixes.tsv` (653 rows) and
  `test_pdfs/platon_dialogos_vi_bad.fixes.tsv` (482 rows). They are not in git
  (`test_pdfs/` is ignored): don't delete or overwrite them; back them up (copy to
  `scratch/`) before the first rebuild.
- Latest clean PDFs are from the morning of 2026-10-16, before this session's changes:
  `scratch/philo/book_1-462.pdf`, `scratch/platon_full/book_1-293.pdf`. Not rebuilt on
  purpose: one rebuild with the user's fixes instead.
- User decided (2026-10-16): forget for now the ocr1-guess ranking, Lazarillo's
  run-together variant notes, and the leftover split words ("Au gusto", "fue re").
  Bilingual editions not supported.
### PLAN: model-assisted review with a local review page (agreed 2026-10-16, option B)
Goal: a model (Groq, via the user's existing API code in another repo) proposes a
decision for each review row; the user accepts/edits/ignores them on a local HTML page
that shows the scan crop next to the proposal; a script merges the decisions into
`<stem>.fixes.tsv`. Proposals never go straight into the review file.

Token rules for this work (user asked: as few tokens as possible):
- Read only this section of PROGRESS.md (grep for "## NEXT SESSION", Read with offset).
- Never print a review file, packets or proposals. Scripts write details to
  `scratch/review_ai/` and print a summary of at most ~10 lines (counts only).
- Try every step on a sample of ~20 rows first, then the full run.
- No rebuilds or OCR: use the Paddle cache and the txt built this session
  (`scratch/review_books/book_1-462.txt` philosophy, `scratch/review_books_platon/
  book_1-293.txt` Platón).
- The per-row work is done by the Groq model; Claude writes and checks the scripts and
  spot-checks at most ~10 rows.
- Background jobs: their output file can't be read; scripts write to `scratch/`.

Steps:
0. New branch from main. The Groq code is in the user's `transcribe` repo (outside this
   repo: Claude may not read it, see the working rules). There:
   `text_correction/groq.py` holds the only HTTP call: `generate()` sends a chunk and
   waits out a 429 using `retry-after`; `api_key()` reads `GROQ_API_KEY` from `.env`.
   `text_correction/backends.py` `BACKENDS["groq"]` sets model, prompt, temperatures
   and chunk sizes (800/1,100 words). Tests fake it in `tests/test_correction.py`.
   State (2026-10-16): `scratch/groq_client.py` is in place (5.4 KB, copied by the
   user, not yet read). `GROQ_API_KEY` is in this repo's `.env` (gitignored; never print or read it into the
   conversation, the client reads it). Model: `GROQ_MODEL = "openai/gpt-oss-120b"`.
   gpt-oss-120b takes text only, no images: the model pass is text only (packet
   context, no crops sent); the crops are for the review page, where the user checks
   them. Read `scratch/groq_client.py` once; adapt only what's needed (prompt/JSON per
   row). No new dependency unless it needs one (then `.venv/bin/pip install` +
   pyproject `dev`).
1. Packets, `scratch/review_packets.py STEM` -> `scratch/review_ai/<stem>/packets.jsonl`
   + `crops/<id>.png`. Rows: kinds `spelling` and `chars` only (note and margin rows
   stay for the user: ~50 rows). Per row: id, page, kind, type, find, the pre-filled
   value, ~300 chars of context (find the row's context in the built txt), and a crop:
   page label -> PDF page via the Paddle cache's "number" blocks; the Paddle block whose
   text contains `find` gives the bbox; Tesseract on that block crop gives word boxes;
   cut the line holding the closest match (~600x60 px); if not found, the whole block.
2. Model pass, `scratch/review_model.py STEM [--sample N]` -> `proposals.jsonl`: batches
   of ~40 rows, fixed instructions (the actions and what they mean, from the fixes.py
   docstring; "propose the printed word, not a plausible one"), answer as JSON per row:
   id, action, value, confidence (high/medium/low), reason (one line). Model
   `openai/gpt-oss-120b`: text only, no crops sent. Without the scan it can't tell
   "Gual" from "cual": tell it to give low confidence when the context doesn't decide.
   Validate: action in the allowed set, replace changes something; invalid -> no
   proposal. Estimate for both books: ~150-200k input + ~40k output Groq tokens.
3. Test before trusting: if the user has already decided rows by hand, run the model on
   those blind and report agreement per type and confidence (`scratch/review_eval.py`).
4. Review page, `scratch/review_page.py STEM` -> `scratch/review_ai/<stem>/review.html`
   (local file, not published: it holds book pages; images by relative path). Per row:
   crop, context, current value, proposal + reason; buttons accept / ignore / edit;
   filters by type and confidence; keyboard shortcuts; the user's own existing
   decisions shown and kept. Choices saved in localStorage; "Export" downloads
   `decisions.tsv` (id, action, value). One-time build cost ~20-40k tokens.
5. Merge, `scratch/merge_decisions.py STEM decisions.tsv`: back up the review file to
   `scratch/review_ai/<stem>/` first; set action/value by id; report counts.
6. Then continue with the list below (rebuild with the fixes, analysis, reuse, final
   books). If the page works well, move the scripts into the package later.

Progress (2026-10-16, evening, branch `feature/review-model`):
- 0. `scratch/groq_client.py`: `config` import replaced by constants (model
  gpt-oss-120b, reasoning low, temperature 0.2, 8000 tokens/request, `.env` in repo).
- 1. `scratch/review_packets.py STEM [--sample N]`: done. Sample of 20: 16 line crops,
  1 block, 3 none (find not in any Paddle block, e.g. joined split words). Context from
  the built txt (falls back to the row's 60-char context). Reuses
  `mixed_script._tsv` for Tesseract word boxes (200 dpi).
- 2. `scratch/review_model.py STEM [--sample N]`: 25 rows/request (8000-token budget),
  resumable (appends to proposals.jsonl, skips done ids, skips rows the user decided).
  Sample 20: all valid, ~2.6k prompt + 1.3k output tokens; spot-check 10: 9 sensible,
  1 bad guess ("Cprk" -> "Cambridge"; printed is likely "Cork"). Added: prompt says
  the printed word shares most letters with `find`; a replace with similarity < 0.6
  to `find` is set to confidence low.
- 3. Skipped: no rows decided by hand yet in either file (`scratch/count_decided.py`).
  Run `review_eval.py` later only if the user decides rows first.
- 4. `scratch/review_page.py STEM` -> `scratch/review_ai/<stem>/review.html` (local).
  Keys: j/k move, a accept, i ignore, e edit (Enter = replace), c clear. Filters by
  kind+type group, confidence, undecided. localStorage `review:<stem>`; Export ->
  decisions.tsv.
- 5. `scratch/merge_decisions.py STEM decisions.tsv` (reuses `read_fixes`/
  `write_fixes`; backup first). Self-check `scratch/test_merge.py` passes.
- Backups of both review files: `scratch/review_ai/*.fixes.tsv` (before any run).
- Full run (both books, packets + model) via `scratch/review_run_all.py`, log in
  `scratch/review_ai/run.log`. Done, no failed batches (rate limit waits only):
  - philosophy 647 rows (crops: 595 line, 15 block, 37 none): replace 211 high /
    28 medium / 19 low; ignore 380 high / 3 medium; 6 invalid (no proposal).
  - Platón 432 rows (392 line, 5 block, 35 none): replace 239 high / 30 medium /
    29 low; ignore 121 high / 3 medium / 7 low; 3 invalid.
  - Spot-check Platón chars rows: Greek transliterations handled inconsistently
    (some ignored, some "loū" -> "loû"); a stray `$` proposed as ignore (should be
    removed: can't be a replace with an empty value). User checks these on the page.
- User: no checks in bibliographies. `fixes.py`: chars rows (odd letters, `$`) are no
  longer flagged under a Bibliografía/Índice heading or in entry-like paragraphs (spelling
  already skipped them); notes still get chars checks. Existing such rows in the review
  files go `stale` on the next build. Review pages: images now embedded (base64): the
  user's viewer didn't load the relative `crops/` paths.
- Split words ("def niciones", model says "fragment", ~23 rows): the page has a "find"
  box next to the value; widen it to "def niciones" and replace with "definiciones".
  decisions.tsv gets a 4th column `find`; merge sets the row's find (replace only).
  Test `test_replace_spans_a_split_word` confirms a two-word find applies.
- Pages built: `scratch/review_ai/philosophy/review.html`,
  `scratch/review_ai/platon_dialogos_vi_bad/review.html`. WAITING FOR THE USER to
  review and Export; then `merge_decisions.py STEM ~/Downloads/decisions.tsv` (path
  outside the repo: the user moves it into `scratch/review_ai/<stem>/` first).
  Pages now sort rows by kind, type, then the model's action (user request).

Done 2026-10-17 (user reviewed both pages):
- Merged: philosophy 556 decisions (180 replace, 376 ignore, 24 widened finds), Platón
  432 (287 replace, 145 ignore, 34 widened). Bibliography rows left undecided on
  purpose (they go stale). Backups: `scratch/review_ai/<stem>/<stem>.fixes.<time>.tsv`
  (before merge) and `<stem>.fixes.merged.tsv` (after).
- User's observations while reviewing, and what was done (measured on the decisions with
  `scratch/decision_patterns.py` and `scratch/rule_precision.py`, counts only):
  1. italics are mostly foreign words: no italic information in the OCR output (Paddle
     gives plain text), so not possible now; the foreign dictionaries cover most.
  2. ALL CAPS never flagged: done (step 0 below).
  3./4. b for h, c for e: Platón 13 + 25 replaces (philosophy ~0). New spelling type
     `swap`, value pre-filled like `accent`: b->h / c->e at one or two places gives a
     known word. On the decisions it matches the user's value 37 of 40 times.
  5. ¿/¡ read as i/l: ~10 rows, all with other errors in the same word; a rule
     ("i"/"l" + known word -> ¿word) matched 0 of 10: not added.
  6. spaces/hyphens inside words: 16 rows, already flagged and fixed by hand (widened
     find); `_join_split` already joins fragments. Not changed.
  7. joined words ("mezclade"): a split-into-two guess matched 3 of 22: not added.
  8. part of a correct word highlighted ("mezcl" in "mezclado"): the page marked the
     first substring match; now whole word first (`review_page.py`). Fragment rows from
     split words (context from the joined txt) go stale on rebuild.
- Rebuild 1 (outputs `scratch/fixed_philo/`, `scratch/fixed_platon/`): Platón 257
  replaces applied, 23 stale; philosophy 159 applied, 16 stale. Stale were mostly the
  user's widened two-word finds: a margin reference or a page mark sat between the
  halves (`scratch/stale_why.py`, `scratch/split_diag.py`: 8 of 11 Platón ones cross a
  page). Fixed in `fixes.py`: a multi-word find matches across margin refs, and across
  a page mark via `Review._across_pages` (whole block, before the per-page pass; row on
  either page); marks go before the new text. Tests in `test_replace_spans_a_split_word`.
  New rules on philosophy: 9 ALL CAPS + 1 name undecided rows went stale.
- Rebuild 2 (same outputs, with the fix): Platón 271 applied / 9 stale (6 of them: value
  already in the text; 3 to look at), philosophy 170 applied / 5 stale (all: value in the
  text). Ignores all applied. Still waiting: philosophy 77 undecided spelling rows
  (still flagged: not all bibliography), Platón 50 note/margin rows. New rows from the
  rebuild: philosophy 24, Platón 34 (incl. 1 `swap`).

Done 2026-10-19 (branch `feature/find-book-review`, 4 commits, not merged):
- Committed find-book/ebook-to-pdf and the bibliography fix.
- find-book: year weighs more (+25 exact, -2/year off; no year -15), Elejandría book pages
  read at search time (real formats; first 5 that fit), `--url` takes archive.org/details
  pages. Lisi's Timeo now ranks 1st.
- `pdf-worker review book.pdf` (src/pdf_worker/review.py, groq.py, review_page.html):
  replaces scratch review_packets/model/page/serve + merge_decisions. Folder
  `<stem>.review/` next to the PDF (crops, proposals.jsonl); server 127.0.0.1:8765, "Save
  decisions" merges into the TSV (backup in the folder). Context now from the Paddle block
  (scratch used the built txt). Tried on Platón: 11 open rows, all with suggestions.
  `test_pdfs/platon_dialogos_vi_bad.review/proposals.jsonl` copied from scratch/review_ai.
- Round 2 merged (philosophy 21, Platón 19) and both rebuilt. Platón: 13 of 16 replaces
  applied; stale: 437 'juiciocomún', 465 'mezclóde' (joined words), 508 'estre [74a] cha'
  (margin ref inside a word): the find doesn't match the blocks at apply time. Not fixed.
- Test book 7: Marianela (Galdós). Elejandría born-digital PDF -> EPUB fine (24 chapter
  files, 0 notes) but 262 spelling rows, all real words (enclitics "Mirábale", diminutives
  "patiecillo", old words): spelling flags on a born-digital text layer are noise. Fixed
  (user: yes): spelling only on Paddle text or mostly-scanned PDFs
  (`ocr_check.mostly_scanned`); Marianela now gets 0 rows. IA scan
  `scratch/find_book/test7/marianela.pdf` (1903, Google, 297 pp.): Paddle conversion
  started then stopped; user (2026-10-19): don't run it, the digital version is enough.
- Philosophy's 77 undecided spelling rows: 71 were in the bibliography (`scratch/where_rows.py`
  + `where_summary.py`). Cause: "BREVE BIBLIOGRAFIA" and its subheadings ("Obras generales",
  "Textos", "Estudios") are all h2, and a same-level heading ended the bibliography. Fix in
  `fixes.py` `_section`: same level ends it only at h1 or a chapter-like heading
  (`_CHAPTER_RE`, whole word: "Capítulos I-II" groups entries). Test
  `test_bibliography_subheadings_of_the_same_level_stay_in_it`. Rebuilt philosophy: 74 went
  stale, 4 still flagged, user's decisions unchanged. Not committed yet.
- Leftover review pages: `review_packets.py STEM --open` (undecided not stale, or stale
  replace whose value is not in the txt; context from `scratch/fixed_*` txt), model, page.
  philosophy 21 rows, Platón 19. Old pages kept as `review.20261017.html`. Backups:
  `<stem>.fixes.20261018-before-bib.tsv`. Waiting for the user: review, Export, merge.
- find-book experiment (Timeo, Lisi 1992): ranked an Elejandría copy (other translation,
  listed "epub", saved a PDF) first; the Gredos 1992 volume (Internet Archive) 4th, below
  candidates without a year. `--url` with an archive.org details page fails ("sent a web
  page"). Downloaded via the candidate (`scratch/fb_download.py 4`): same edition as
  `test_pdfs/platon_dialogos_vi_bad.pdf`, other scan (292 pages). Tesseract `ocr --mode
  redo` + `convert --margin-refs` -> `scratch/find_book/timeo_lisi.{pdf,txt}`: 0 margin refs
  (reference 728), 125 notes all note-no-ref, 292 chapter files in the PDF, 16.7% word
  differences vs the reviewed Paddle build (`scratch/fb_wer.py`). No EPUB of this translation
  in any source.

Next, when the user says the review files are done:
0. Fewer spelling rows (user decided 2026-10-16), in `fixes.py`, with tests, before
   the rebuild:
   - name rows: a capitalised unknown word that occurs 2+ times in the book with the
     same spelling is not flagged, unless it is one or two edits from a more frequent
     name (`Bohatcc` beside many `Bohatec`): then flag it, with that name as the hint.
     Count names over the whole book first (two passes or a pre-count), not per page.
   - a word in ALL CAPS is never a review row (spelling or chars).
   Count how many rows each rule removes in both books and report it.
   DONE 2026-10-17: `fixes.py` (`_is_name`, `_near_name`, `_distance`, `_swaps`;
   recurring names kept when an accent fix exists; near-name search only among names
   with the same first letter), tests `test_no_rows_for_all_caps_or_names_the_book_repeats`
   and the updated type-order test.
1. Back up both files, then rebuild both books from the Paddle cache with the fixes
   (`scratch/book_build.py PDF RANGE OUTDIR pdf epub txt`; Platón with
   `--margin-refs --estimate-margin-refs`; it uses `<stem>.fixes.tsv` next to the PDF).
   Report statuses (applied / ambiguous / stale) and anything that didn't apply.
2. Analyse the user's decisions (agreed with the user as the next step):
   - per spelling type: share replaced vs ignored (precision) -> hide or reorder types;
   - replace pairs, letter by letter: recurring misreadings -> candidate auto-fixes or
     better ocr1 guesses; test any auto-fix on the 8 reference excerpts (WER must drop,
     `scratch/rebuild_excerpts.py` + `wer_all.py`) before adopting it;
   - ignored words grouped (names, rare words, foreign, old forms);
   - attach/drop note rows: why references were missed.
3. Then decide with the user on reuse across books (discussed, not decided): a shared
   per-language list from whole-book `ignore` rows (words of 5+ letters only), and past
   `replace` rows offered as pre-filled suggestions (never applied automatically).
4. Produce the final EPUB/PDF of both books with the fixes; the user checks on device.
Later (user's choice): book profile for notes; Greek in Paddle books.

Done (2026-10-16), the list as it was:
1. Hide foreign words (user decided 2026-10-16): in `fixes.py`, a word the de/fr/it/la
   dictionary knows is not flagged (like the English rule; keep the 5+ letter minimum).
   Copy de/fr/it/la .aff/.dic from `scratch/dicts` (source: wooorm/dictionaries) into
   `src/pdf_worker/dictionaries/` with licence files; check each licence allows bundling
   first (if not: note under Blocked, skip). Accepted cost: ~5% of those rows were real
   errors (analiticamente, afin, mite). Note for later, not now: keep a foreign word
   flagged when the accent/one-edit check finds a Spanish word.
2. Words split by line breaks, fixed when the text is built (not as review rows):
   in-paragraph hyphen kept (`enciclo-pedistas`, `alre-dedor`) and words broken at a
   page/paragraph start (`tieron`, `gún`, `cidad`, `dencia`). Sample examples first
   (`scratch/classify_*.tsv`, bucket `hyphen`, plus `ocr1`/`unknown` rows that are
   fragments) to find where blocks are joined, then fix the root cause.
3. Review file: add the error type (hyphen/accent/ocr1/foreign/name/unknown, logic in
   `scratch/classify_spelling.py`) per spelling row, sort reliable types first;
   pre-fill `value` for accent rows (action left empty, user confirms); one-edit
   suggestions only as a hint. Speed: the one-edit search is slow (~10 min for
   philosophy); limit it or cache lookups.
4. Small word list for dictionary gaps (rehúye, inherencia, capitación,
   Considerémoslo, superlatives like correctísima).
5. Measure the pipeline on new books (user request, 2026-10-16). There are some pdfs in test_pdfs but also find Spanish scanned (about 10 or so)
   PDFs on the internet that are public domain or freely licensed, ideally ones with a
   trusted text version to compare against (e.g. an Internet Archive scan of a book that
   is also on Project Gutenberg or Biblioteca Virtual Miguel de Cervantes). Vary them:
   old print, footnotes, poor scans. Take ~10-20 pages from each (don't
   OCR whole books), run the pipeline, and measure: word error rate against the
   reference text, spelling rows per page and their type mix (`classify_spelling.py`),
   and structure problems (headings, notes, split words). Keep downloads in
   `test_pdfs/` and don't commit them. Write the results per book in this file.
Test books: `test_pdfs/philosophy.pdf 1-462`, `test_pdfs/platon_dialogos_vi_bad.pdf
1-293 --margin-refs`. Stale trial `.fixes.tsv` files in `test_pdfs/` can be deleted.

## Done

### Feature 1: PDF text extraction (2026-10-11)
- `pdf-worker extract-text <pdf> [-o out.txt] [--page-separator SEP]` streams the text layer
  page by page into a UTF-8 `.txt`, written atomically, and warns about pages with no text.
- Library choice: PyMuPDF (cleaner output than pypdf on the noisy OCR sample; licensed AGPL).
- Files: `pyproject.toml`, `src/pdf_worker/{cli,document,errors,text_extraction}.py`,
  `tests/{conftest,test_text_extraction,test_cli,test_integration_test_pdfs}.py`.
- Results: Kant, 206 pages, 681k chars, about 1s. Familia Romana, 332 pages, 557k chars,
  about 1s; pages 1, 2, 331 and 332 are image-only. Its text layer is poor OCR, and
  re-OCR would be a separate future feature.

### Repo setup for autonomous work (2026-10-11)
- Working rules added to `CLAUDE.md`. `scratch/` (gitignored) holds all temp files.
- pytest `tmp_path` redirected to `scratch/pytest` in `tests/conftest.py`.

### First commit and PR (2026-10-11)
- `test_pdfs/` and `.claude/settings.local.json` are gitignored: the PDFs are large and
  copyrighted, and the repo is public.
- Scaffolding is committed on `main`. Feature 1 is on `feature/text-extraction`.
- Once the user allowed pushing, both branches were pushed, PR #1 was opened and merged
  (https://github.com/fonsthefons/pdf-worker/pull/1), and local `main` was fast-forwarded.

### Feature 2: explicit footnotes in text extraction (2026-10-11)
- New `src/pdf_worker/footnotes.py`: an analysis pass (body font size, bracketed numbers)
  then per-page rendering. Output uses Markdown footnote syntax: page footnotes
  `[^p12-1]`, bracketed endnotes `[^31]`, notes continued onto the next page are
  re-emitted as `[^label]: (continued) ...`.
- `extract-text` marks notes by default (`--no-footnotes` opts out) and reports counts,
  plus warnings for unmatched references or notes.
- Samples: none of the three samples has classic bottom-of-page footnotes (checked with
  `scratch/scan_small_text.py`), so that path is covered by generated PDFs in
  `tests/test_footnotes.py`. The encyclical has 224 bracketed endnotes: all 224 linked.
  Kant and Familia Romana: 0 notes, and the output is byte-identical to the raw text.
- False positives found and fixed on Familia Romana: margin glosses and line numbers
  (the region must sit below all body text) and numbered exercises `[1]`–`[6]` (endnote
  numbers must occur ≤3 times, mostly mid-line).
- Cost: the analysis pass roughly doubles extraction time (still about 2s for 332 pages).
- Not handled yet: endnotes referenced by superscript numbers with a "Notes" chapter at the
  end; this needs per-chapter number matching.
- Files: `footnotes.py`, `text_extraction.py`, `cli.py`, `tests/conftest.py`
  (`make_layout_pdf` fixture), `tests/test_footnotes.py`,
  `tests/test_integration_test_pdfs.py`, `README.md`.

### OCR research and plan (2026-10-12)
- Plan written to `docs/ocr-plan.md`: Tesseract via OCRmyPDF as the default, an
  evaluation of PaddleOCR-VL-1.6 (MLX) for hard scans, and Apple Vision as an optional
  fast engine.
- Measured on the M1 at 300 dpi with `scratch/ocr_bakeoff.py`. Both engines get under 1%
  CER on clean pages. On the Familia Romana scan, both lose macrons; Tesseract keeps the
  margin column separate, while Vision interleaves it with the body.
- Installed: `brew install tesseract tesseract-lang` (system-wide, allowed by the current
  rules), plus `ocrmac` and `rapidfuzz` in `.venv`, now listed under the `ocr-eval` extra
  in `pyproject.toml`.

### Feature 3: convert to EPUB and Markdown (2026-10-12)
- `pdf-worker convert book.pdf [-o out.epub|out.md] [--to epub|md] [--title --author
  --language]`.
- Pipeline:
  1. `layout.py`: one analysis pass (body size, line spacing, heading sizes, running
     headers/footers, endnote candidates, a text sample for language guessing).
  2. `footnotes.layout_page`: body lines and notes.
  3. `structure.iter_blocks`: headings, paragraphs, notes, streamed.
  4. A writer: `epub.py` or `markdown_export.py`.
- EPUB: chapters are streamed into the zip; notes go to a temp file and become
  `notes.xhtml` (footnote asides linked both ways for Kindle pop-ups); nav plus NCX.
- Results: all three samples pass `epubcheck` with 0 messages. The encyclical has 224
  linked notes, 32 headings, language `es`. Kant: 43 headings, 908 paragraphs.
- Known rough spots:
  - Familia Romana (noisy OCR layer, line numbers and margin glosses) gives over 9,000
    short paragraphs; re-OCR is needed first.
  - The encyclical's on-page table of contents becomes headings and short paragraphs.
  - Images and tables are not carried over.
- Kindle check: validated with epubcheck. I couldn't test on a real device or Send to
  Kindle from here.
- Files: `layout.py`, `footnotes.py` (refactor), `structure.py`, `output.py`,
  `markdown_export.py`, `epub.py`, `convert.py`, `cli.py`, `tests/test_convert.py`,
  `tests/test_integration_test_pdfs.py`, `README.md`.

### Feature 4: OCR with Tesseract via OCRmyPDF (2026-10-12)
- Chosen engine: Tesseract via OCRmyPDF, the recommendation in `docs/ocr-plan.md`. It
  writes a PDF with a text layer, so the existing commands work on the result unchanged.
- New `src/pdf_worker/ocr.py` and `pdf-worker ocr in.pdf [-o out.pdf] [--lang lat+eng]
  [--mode skip|redo|force] [-j N]`. `extract-text` and `convert` also take
  `--ocr [MODE]` and `--ocr-lang`, which OCR into a temporary PDF next to the output and
  delete it afterwards.
- The language is guessed: from the text layer if there is one, otherwise from an
  English OCR of 2 middle pages. Guesses map to Tesseract codes (`es` to `spa`, `la` to
  `lat`). Missing Tesseract, missing OCRmyPDF and missing language models each give a
  clean `Error:` with an install hint.
- `ocrmypdf>=17.13` is in a new `ocr` extra. Ghostscript isn't needed with
  `output_type="pdf"`.
- Familia Romana, full book with `--mode redo`: language guessed as `lat`, and the
  image-only cover now has text. Tesseract reads long vowels as accents (`Màrcus`,
  `Iülia`, `nón`) where the old layer dropped them (`Marcus`, `Julia`). Margin glosses
  are cleaner (`-um` instead of `-urn`), with some junk from the pictures. `convert` on
  the result is still fragmented (459 headings, 9,725 paragraphs). The cause is the
  layout (line numbers, margin column), not the OCR.
- Tests: `tests/test_ocr.py` (12 tests, generated image-only PDFs, skipped when Tesseract
  is missing) and an integration test on Familia Romana pages 1 and 25.
- Files: `ocr.py`, `cli.py`, `convert.py` (`pdf_title`), `pyproject.toml`, `README.md`,
  `docs/ocr-plan.md`, `tests/test_ocr.py`, `tests/test_integration_test_pdfs.py`.

### Feature 5: Latin macrons in OCR (2026-10-12)
- Tesseract's `lat` model reads long vowels as accents (`Màrcus`, `Iülia`, `nón`), and
  sometimes as a doubled vowel (`Maàrcus`, `nàávis`).
- New `macrons.py` (`restore_macrons`) turns every grave/acute/circumflex/tilde/breve/
  diaeresis vowel into a macron vowel and collapses the doubled forms.
- New `ocr_latin_plugin.py` is an OCRmyPDF plugin that subclasses the Tesseract engine
  and rewrites the hOCR and text output before the text layer is built. It is loaded by
  module name, so the worker processes find it.
- On automatically when `lat` is an OCR language; `pdf-worker ocr --no-latin-macrons`
  turns it off. The report and CLI summary say when it was applied.
- Result on the full Familia Romana (`scratch/count_macrons.py`): 16,118 macron vowels,
  1 accent left. Tesseract still misses many long vowels entirely, so recall is uneven.
  In this book these words always carry a macron:

  | Word | Read with macron | Read plain |
  |---|---|---|
  | `Iūlia` | 167 | 13 |
  | `nōn` | 468 | 400 |
  | `Mārcus` | 124 | 280 |
- Tests: `tests/test_macrons.py` (11), 2 new tests in `tests/test_ocr.py`, and an
  integration check (`Iūlia` on Familia Romana p. 25).

### Feature 6: margin glosses and line numbers in convert (2026-10-12)
- New `margins.py` (`split_columns`) runs per page in `structure.py`:
  - It finds the body column from long lines (left edge from the most common x0, right
    edge from the 80th-percentile x1).
  - Lines entirely outside the column are margin lines. They only count as glosses if
    each side column is narrower than 60% of the body and holds at most half its text,
    so a two-column body isn't mistaken for glosses.
  - Bare numbers at the column edge are dropped, and line numbers glued onto a body
    line (`70 Puer…`, `…eum 55`) are stripped.
  - With margins found, the body is sorted top to bottom.
  - Same-row fragments are joined into one line (`merge_rows`, used on every page).
  - Lines with no letters or digits are dropped, except section breaks like `* * *`.
- New `Gloss` block, queued like footnotes, so it follows the paragraph in progress.
  Markdown writes it as a blockquote with `\` hard breaks; EPUB as `div.gloss`.
  `WriteStats.glosses` is new, and the CLI prints it.
- Paragraphs: the size-change test now compares a line with its block's mean size
  (threshold 8%, at least 0.6 pt), and wrapped lines keep the block's kind. This fixes
  OCR size jitter splitting paragraphs.
- Running headers: `running_key` normalises Roman numerals (`CAP. III`), and the margin
  zone grew from 8% to 10% of the page height.
- Results:

  | Sample | Before | After |
  |---|---|---|
  | Familia Romana, OCR'd with macrons | 459 headings, 9,659 paragraphs | 343 headings, 4,090 paragraphs, glosses separated |
  | Kant | — | Unchanged except one stray `.` paragraph dropped |
  | Encyclical | — | 224 notes; the web header's `ESPAÑOL` link became a gloss; the footer links joined onto one line |

  The Familia EPUB passes epubcheck.
- Tests: `tests/test_margins.py` (6) and an integration test (OCR plus convert of
  Familia pp. 25–26).

### OCR phase 2: PaddleOCR-VL-1.6 evaluation (2026-10-12)
- Results and decision are in `docs/ocr-plan.md` ("Phase 2 results").
- Installed:
  - `brew install python@3.12` (system-wide; PaddlePaddle has no 3.14 wheel).
  - `.venv-paddle/` (gitignored) with paddlepaddle 3.2.1 (CPU), paddleocr 3.7.0 and
    mlx-vlm 0.7.6.
  - The models (1.9 GB) are in `scratch/paddle-home` (HOME, HF_HOME and
    PADDLE_PDX_CACHE_HOME are redirected in `scratch/paddle_env.py`).
- Results on hand-transcribed Familia Romana pp. 9 and 25:

  | Engine | Long-vowel recall | Word recall |
  |---|---|---|
  | PaddleOCR-VL + `restore_macrons` | 94% | 97–98% |
  | Tesseract + macron fix | 44–50% | 81–82% |

  Speed is 12–24 s per page (rule: at most 10), so the speed rule fails. Kant CER is
  0.81% and 0.03%. Paddle also hallucinates now and then, swapped two paragraphs once,
  and dropped glosses on p. 25.
- Decision: Tesseract stays the default. Recommended next: integrate Paddle as an opt-in
  `--engine paddle` for hard scans (phase 3).
- Code change: `restore_macrons` also handles ring-above (`å`, which Paddle outputs),
  with a test.
- To re-run: start `.venv-paddle/bin/python scratch/paddle_server.py` (in the
  background), then `.venv-paddle/bin/python scratch/paddle_eval.py familia:25 ...`,
  then `.venv/bin/python scratch/paddle_truth.py`.

### Feature 7: chapter endnotes and real footnoted books (2026-10-13, PR #9)
- Samples (public domain, in `test_pdfs/`, gitignored):
  - Supreme Court Trump v. CASA (113 pages, 42 footnotes, a "Page Proof Pending
    Publication" watermark).
  - 9/11 Commission Report (585 pages, 1,742 endnotes in 13 chapter groups).
  - Gibbon, Decline and Fall vol. 1 (archive.org scan, unusable word-level OCR layer; I
    re-OCR'd it to `scratch/gibbon.ocr.pdf`).
- New `endnotes.py`:
  - Superscript number runs (restarting at 1) and numbered note lines (`12.` or
    `12.Text`) are grouped into sequences.
  - A sequence resumes after a numbered list inside a note.
  - Runs pair with groups by an LCS on counts, with groups after runs. Labels are
    `c<group>-<n>`.
  - `section_continues` tells whether a notes section goes on, so per-chapter
    subheadings inside it are dropped.
- `structure.py`:
  - Notes zone: a note's later paragraphs stay in the note (`PARAGRAPH_BREAK`, `\n\n`).
  - Subheadings in the zone are dropped. The zone ends after a group's last note at a
    heading or type change.
  - Writers: Markdown indents continuation paragraphs; EPUB writes one `<p>` each.
- Footnote detection fixes:
  - The region is found in vertical order (so a watermark or a stray box doesn't hide
    it), and watermark lines are skipped.
  - The region must sit under a column of body-size text; this kills Familia glosses
    and index pages.
  - Two-column notes are accepted and read column by column.
  - OCR jitter and specks are tolerated; printers' signature marks are skipped.
  - `*8`-style OCR markers are recognised.
  - Without superscript refs, a plain-text marker must be indented or ≤ 30 (this killed
    the `341 F. 2d` false note).
- Layout:
  - Watermarks: mid-page lines repeated on ≥ 50% of pages are dropped.
  - Small-type margin lines repeated on ≥ 4 pages are running heads ("NOTES TO
    CHAPTER 1").
  - Junk PDF titles like `201-635.job` are ignored.
- Results:

  | Sample | Before | After |
  |---|---|---|
  | Court opinion | 8 notes | 42/42 linked |
  | 9/11 report | 49 false notes | 1,742/1,742 refs linked (1 extra def), EPUB valid |
  | Gibbon after OCR | 34 pages with notes | 302 pages; 601 notes in EPUB, mostly unlinked because OCR garbles the markers |

  Familia still has 0 notes.
- Tests: `tests/test_endnotes.py` (5) and 3 new integration tests.

### Feature 8: EPUB links and Kindle page numbers (2026-10-13, PR #10)
- New `inline.py`: private-use-character markers in block text carry page starts
  (index plus printed label) and links (`u:<uri>` or `p:<page>:<y>`).
  `structure._page_links` reads PDF link annotations (URI, GOTO, NAMED);
  `_link_line` wraps the linked text of each line. `join_lines` keeps page marks
  through dehyphenation.
- Page labels (`layout._page_labels`): the PDF's page labels, else printed margin numbers
  with one consistent offset (≥ 25% of pages agree), else index + 1; pages before
  printed page 1 get i, ii, iii.
- EPUB:
  - Every page start becomes `<span epub:type="pagebreak" id="pgN" aria-label=...>`, and
    nav.xhtml gets a hidden `page-list` nav. The OPF declares
    `schema:accessibilityFeature printPageNumbers`.
  - Headings (`hN`) and paragraphs (`bN`) are anchors with their page and position.
  - Chapters are written to a work dir, and link placeholders (with the link's text)
    are resolved at the end: first a block near the target page whose start matches
    the link text (trailing page numbers removed), then the first block at or below the
    target y, then the page start.
  - Links never nest, and references inside links render as plain superscripts.
- Markdown: web links become `[text](<url>)`; page marks and internal links are dropped.
- Results:
  - Encyclical: all index links land on their sections. Before this, it had no links.
  - 9/11: 1,024 internal links; page list i–xviii then 1…, matching the print edition.
  - epubcheck: 0 messages on both.
- Not verified on a device: whether Send to Kindle turns the page-list into Kindle "real
  page numbers". The user should check.
- Tests: `tests/test_links_pages.py` (5) and integration checks on the encyclical and the
  9/11 report.

### Feature 9: pictures and cover (2026-10-13, PR #11)
- New `images.py`. Pictures are rendered from the page (clip, 120 dpi, JPEG quality 80),
  so codecs, masks and overlays don't matter:
  - Digital PDFs: each embedded image rect that is ≥ 1.5% of the page and < 80%
    (otherwise it's a scan or background) becomes a figure. Overlapping rects merge.
    Images placed on ≥ 30% of pages (`profile.repeated_images`) are logos and are
    skipped.
  - Scans (a full-page image): every text line's box is blanked in a 36 dpi grey
    render. Ink is anything ≥ 55 grey levels darker than the paper (90th
    percentile). Bands of inked rows ≥ 12% of the page tall and ≥ 25% wide are
    cropped.
  - Short text lines inside a picture (labels such as "insula") are dropped from the
    body.
- New `Image` block, queued like notes so it follows the paragraph before it. EPUB:
  `images/imgN.jpg` stored uncompressed, `div.figure`, manifest items. Cover: page 1 at
  1600 px tall, `cover-image` property, `<meta name="cover">`, a `cover.xhtml` first in
  the spine. Markdown: `<stem>_images/imgN.jpg` and `![](<...>)`.
- `convert --no-images / --no-cover`; `WriteStats.images`.
- Familia Romana (OCR'd): 58 pictures, all real illustrations on the first contact sheet
  (`scratch/contact_sheet.py`). A few include a strip of the gloss column. EPUB is 3 MB
  and valid.
- Not handled: vector drawings (charts, maps made of paths).
- Tests: `tests/test_images.py` (6).

### Feature 10: `pdf-worker kindle` (2026-10-13, PR #12)
- New `ocr_check.py` (`assess_text_layer`) samples 24 pages and measures:
  - the share with text;
  - the share that are full-page scans;
  - "jittery" lines, whose words differ in size by more than 25%;
  - suspect words (digits inside letters, stray symbols, `liBer`).
- Rules, tuned on all samples:
  - Text on fewer than 50% of pages: `skip`.
  - Scanned, with more than 20% jittery lines (archive.org's word-level layer is 0.30,
    Tesseract's ≤ 0.07): `redo`.
  - Scanned, with more than 1% suspect words (old Familia layer 1.3%, after re-OCR
    0.6%, digital ≤ 0.3%): `redo`.
  - Scanned with some text-less pages: `skip`.
  - Otherwise no OCR.
  - Results: Familia → redo, Gibbon → redo, all digital PDFs and the re-OCR'd files →
    none.
- New `kindle.py` (`make_kindle_book`): assess, then OCR into a temporary copy if
  needed (keeping the original title), then convert to EPUB. The CLI `kindle` command
  reports what it did and warns above the 50 MB e-mail limit.
- Tests: `tests/test_kindle.py` (5).
- Fix found on the full Gibbon run: the picture finder got only body lines, so
  footnote text (moved to notes) wasn't masked and every page "had" a picture. It now
  gets all page lines. Gibbon went from 300+ false pictures to 1 (the frontispiece);
  Familia still has 58. Gibbon end to end: auto redo OCR, 6 MB EPUB, epubcheck clean.

### Feature 11: `--engine paddle` (2026-10-13, PR #13)
- New `paddle_worker.py`: a script run by `.venv-paddle`'s Python, with no pdf_worker
  imports. It renders pages at 200 dpi, runs `PaddleOCRVL(vl_rec_backend=
  "mlx-vlm-server")`, and writes JSON lines with blocks (label, bbox, text).
- New `paddle_ocr.py`:
  - Starts `mlx_vlm.server` on a free port and waits for it (up to 15 min for the
    first model download), runs the worker, then stops the server.
  - Writes the blocks as an invisible text layer (render mode 3, Noto Sans from
    `pymupdf-fonts`), fitting each block's text into its box.
  - Wide blocks are rewrapped (Paddle keeps printed line breaks), aligned to one left
    edge, and start with two typed spaces, so they read as one paragraph each.
  - Missing glyphs fall back to their base letter; LaTeX wrappers are removed; macrons
    are restored when the output reads as Latin.
  - Redo/force first strips the old text with a full-page redaction that keeps
    images and drawings.
  - Caches: `PDF_WORKER_PADDLE_CACHE` (default `~/.cache/pdf-worker/paddle`). The
    subprocess also gets `HOME` set to it.
- `ocr.ocr_pdf(engine=...)`; CLI `--engine` / `--ocr-engine`, `--paddle-cache`; kindle
  `--engine`. New extra `paddle = [pymupdf-fonts]` (installed in `.venv`).
- Result on Familia pp. 9, 25 and 120 (redo): clean paragraphs with macrons (`Eurōpā`,
  `Āfricā`, `rīdet`, `Quīntus`) and glosses separated. The model's own errors remain
  (`Aemiliaam`, `nāo`, line numbers inside the text).
- For my runs: `--paddle-cache /Users/fons/Documents/programs/pdf-worker/scratch/paddle-home`
  (models already there).
- Tests: `tests/test_paddle_ocr.py`: 4 unit tests, plus 1 integration test that runs
  the real pipeline (about 15 s) when `.venv-paddle` exists.

### Feature 12: clean-ups (2026-10-13, PR #14)
- Headings:
  - `layout._cluster_sizes` merges sizes within 10% of each other (one level each,
    max 4), and `heading_level` takes the nearest level within that band.
  - Heading blocks of more than 3 lines or 160 characters become paragraphs; specks
    with fewer than 3 letters are dropped (chapter numbers kept).
  - A new paragraph starts where emphasis ends. `profile.emphasized(line)` means bold,
    or set wholly outside the body fonts (`body_fonts` = fonts setting 85% of the text);
    this catches Type3 display faces.
  - Results: Familia 343 → about 240 headings, mostly real. The encyclical 31 → 99:
    every section subheading is now a heading.
- Printed contents pages: a page where at least 5 lines and half of all lines are
  entries (title, leaders and/or spaces, page number) loses those entries and its side
  columns, unless the page has links. Familia's INDEX CAPITVLORVM is gone; the
  encyclical's linked index stays.
- Tables: `margins._join` now joins same-row pieces with a `CELL` marker
  (`inline.CELL`). The structure pass makes two or more consecutive multi-cell rows
  (±1 column) a `Table` block; a single row becomes a paragraph. EPUB writes
  `table.data`, Markdown a pipe table with the first row as header. `plain`/`pieces`
  turn CELL into a space elsewhere. Familia has 92 declension and verb tables; the 9/11
  report has 12 (flight timelines). Wrapped cells split tables (a limitation).
- Titles: "book.ocr.pdf" becomes "book"; underscores become spaces.
- Tests: `tests/test_cleanups.py` (4); the table test was updated; the integration test
  checks at least 90 encyclical headings.

### Feature 13: HTML, clean text, Word and reflowed PDF (2026-10-13, PR #15)
- `html_export.py`: builds the EPUB in a work dir and joins it into one HTML page:
  - the nav TOC becomes `nav.contents`, followed by the chapter bodies as
    `<section id="cNNN">` and then the notes;
  - `cNNN.xhtml#x` links become `#x`, and `epub:type`/`role` attributes are dropped;
  - pictures are embedded as data URIs, or saved to a folder (for the PDF).
- `text_export.py`: reflowed paragraphs, `[n]` references, a Notes section at the
  end, glosses indented, tables tab-separated. Default name `book.clean.txt`.
- `docx_export.py`: our Markdown, then Pandoc (`brew install pandoc`; a clean error if
  it's missing). Gives real Word footnotes and the title in the document properties.
- `pdf_export.py`: our HTML laid out by `pymupdf.Story.write_with_links` onto A5 pages
  with 42 pt margins, keeping internal links. Default name `book.reflowed.pdf`, and
  convert refuses to overwrite its input.
- Encyclical: all six formats convert in 3–8 s. The PDF has 163 pages, 4,660 links
  (2,343 internal) and is 2.2 MB; the docx has 224 footnotes.
- Tests: `tests/test_formats.py` (6) and one HTML/PDF pictures test.

### Feature 14: CI (2026-10-13, PR #16)
- GitHub Actions on ubuntu-latest, Python 3.12 and 3.14. It apt-installs tesseract-ocr
  (+lat, spa), pandoc and epubcheck, installs `.[dev,ocr,paddle]`, then runs ruff
  check, `ruff format --check` and `pytest -m "not integration"`.
- The first run caught a real bug: `KindleReport.ocr` shadowed the `ocr` module in its
  own annotation. Python 3.12 evaluates annotations eagerly (3.14 lazily, which is why
  it passed locally). Renamed to `ocr_report`. Both versions now pass.

### `pdf-worker help` (2026-10-13)
- `pdf-worker help`, or `pdf-worker` with no command, prints a cheat sheet: example
  commands with a one-line description each (`CHEAT_SHEET` in `cli.py`; keep it current
  when adding commands or options).
- The `convert` and `ocr` help texts now list all formats and both engines.
- (PR #19) The help ends with a "Files" section (`FILE_NOTES`): what the PDF path is,
  where output goes, quoting names with spaces, `-o`, two-dash options.
- Kindle check: cover and links work. Page numbers show as "Loc": Send to Kindle seems
  to drop the EPUB page-list. Likely fix is Calibre's KFX Output plugin plus USB; not
  done, the user hasn't asked for it.
- Tests: 2 new in `tests/test_cli.py`.

### Mixed-language books: Latin + Spanish, Greek passages (2026-10-13, PR #20)
- Macrons are restored only in paragraphs that read as Latin (`reads_as_latin` in
  `macrons.py`: Latin stopwords beat every other language's, from
  `convert.stopword_scores`). Before, `lat+spa` turned `canción` into `cancīōn`.
  Paragraphs too short to tell follow the page; Tesseract pages that can't tell count as
  Latin only if no other Latin-script language was asked for. Tesseract: per hOCR
  `ocr_par` and per blank-line paragraph of the text file (`ocr_latin_plugin.py`).
  Paddle: per block; on when any block reads as Latin.
- The language guess adds `grc` when the sample has ≥20 Greek letters. The scan probe
  now OCRs with `eng+grc` and samples 3 pages spread over the book (it was 2 adjacent
  middle pages, which in the sample book were all Spanish introduction and missed the Greek).
- Sample `test_pdfs/sample-text-spanish-ancient-greek.pdf` (XeTeX, born-digital): text
  layer extracts Greek fine. As a 300 dpi scan: `spa` alone gets 0 Greek words, `spa+grc`
  ~70% (misses are mostly words with footnote letters glued on). Guess: `["spa", "grc"]`.
- Not handled: the EPUB has one `lang` for the whole book. Scratch scripts:
  `scratch/greek_scan_trial.py`, `scratch/guess_full_scan.py`.
- Tests: `tests/test_ocr_latin_plugin.py` (2), new tests in `test_macrons.py`,
  `test_ocr.py` (2), integration `test_ocr_scanned_spanish_book_with_greek`.

### Greek word spaces, short Latin lines in mixed books (2026-10-13, stacked on PR #20)
- Greek spaces: in the sample PDF, MuPDF glued words after accented Greek vowels
  (`καὶἦλθεν`, `τοῦἸορδάνου`): the PDF has a word-sized gap but no space glyph.
  `layout.page_lines` now reads `rawdict` and inserts a space where the gap between two
  letters exceeds 0.15 em, within and across spans (`_with_text`). The `--no-footnotes`
  path uses `page_lines` too. 278 words un-glued in the sample; the Kant, encyclical,
  CASA, 9-11, Familia Romana and Gibbon PDFs are unchanged (one stray OCR `™` in Gibbon).
  Check script: `scratch/greek_spaces_check.py`.
- Short Latin lines: Tesseract's own hOCR `lang` tags proved useless (Spanish
  paragraphs tagged `lat`). Instead, `reads_as_latin` now (1) compares Latin only with the
  languages being OCR'd (`rivals`; "in" no longer counts as English in a `lat+spa`
  run), and (2) on a tie, a Latin-only ending (-um, -ae, -orum, -arum, -ibus) means
  Latin. Paddle's rivals are the languages with ≥5 stopword hits in the book.
  Known limit: Spanish words like `álbum`/`referéndum` alone on a line would read as Latin.
- Tests: `_with_text` unit test, `test_greek_words_are_not_glued_together` (integration),
  rival/ending tests in `test_macrons.py` and `test_ocr_latin_plugin.py`.

### Bad scans: Platón, Diálogos VI (2026-10-13)
- Samples: `test_pdfs/platon_dialogos_vi_bad.pdf` (293 pages, ABBYY FineReader layer,
  ~900 dpi bilevel scan, pencil underlining, Stephanus marks in the margins, page
  footnotes) and `platon_dialogos_vi_good.pdf` (calibre edition, notes at the end), used
  as ground truth. Scoring: bag-of-words recall/precision against the good text
  (`scratch/platon_eval.py` for bad pp. 19–20 vs good p13 + notes 1–6;
  `scratch/platon_eval2.py` for any passage, e.g. bad pp. 9–15).
- Findings: ABBYY's layer is better than Tesseract on clean pages (pp. 19–20 recall 0.92
  vs 0.89; PaddleOCR-VL also 0.92), so it is kept there. On underlined pages it is bad
  (pp. 9–15 recall 0.908).
- OCR changes:
  - New `underlines.py`: hand-drawn underlines are chains of thin blobs at one height
    (OpenCV connected components). `ocr_underline_plugin.py` (OCRmyPDF
    `filter_ocr_image`) scales the page to 300 dpi, binarizes it and erases them, only
    on pages that have them. Underlined pp. 9–15: recall 0.908 → 0.945.
  - The plugin is loaded only for underlined books (sample check, or `pages` given):
    merely decoding images in the hook changed Tesseract's output (Familia lost
    macrons).
  - `ocr_pdf(pages=...)` limits OCR to some pages. `assess_text_layer` returns `redo`
    with `pages` = the underlined scanned pages (36 in this book); `kindle` passes them.
  - Fixed: OCRmyPDF dropped the text of pages whose MediaBox doesn't start at (0, 0)
    (every other page of this book, `[330 0 660 518]`). `_zero_origin_copy` moves them
    first (pikepdf).
  - numpy + opencv-python-headless added to the `ocr` extra.
- Structure changes (all books):
  - `Line.bbox` now spans the inked spans only (`layout.ink_bbox`): ABBYY's space
    spans have sizes up to 35 pt, which moved line tops and broke paragraphs mid-sentence.
  - Soft hyphens (U+00AD) at line ends are joined (`join_lines`).
  - Short marks past the column edge after a gap (`11`, `b`, `<■`, `d`) are dropped
    (`margins._trim_edge_marks`, median right edge).
  - `_page_margins.left` is the leftmost edge shared by ≥ 20% of lines: in dialogue the
    most common edge was the speaker indent, so turns ran together.
  - Junk titles ending in `.tif`/`.jpg`/`.png` are ignored.
  - Scan pictures: black scanner edges (columns/rows in the outer 10% dark over 60% of
    the page) are blanked first; false pictures in this book 7 → 3.
- Result: `pdf-worker kindle` on the book: 36 underlined pages re-OCR'd, 2,679
  paragraphs, 154 notes, EPUB passes epubcheck.
- Not done / known limits:
  - Footnote references are not linked in this book: ABBYY reads superscripts as plain
    digits (`ventajoso5`, `Filebo* 4 * 6`) and some note markers as `J`. Notes are kept
    but unlinked, and some notes are missed (165 found; the book has more).
  - 3 false pictures remain (partial scanner smudges, pp. 137, 138, 140).
  - Tesseract on a single page swings ±4% with tiny image changes; judge on several pages.
- Tests: `tests/test_bad_scans.py` (8), 2 integration tests on the Platón PDF.
- Candidate next step: link footnote references in OCR layers that set them as plain
  digits glued to words, by matching against the note numbers found on the page.

### Word vote for scans (2026-10-13)
- User: "I as a human can read that text, so there must be something we can improve."
- Tried and measured (bag-of-words recall vs the good edition):
  - Apple Vision alone on pp. 19–20: 0.84 (worse than ABBYY 0.92, Tesseract 0.89).
  - Lexicon correction with Tesseract's own Spanish word list (dumped with
    `combine_tessdata` + `dawg2wordlist`): useless, the list contains `parce`, `jo`,
    `asi`, `cl` and lacks many verb forms.
  - Book-internal bigram noisy-channel model (`scratch/platon_spell2.py`): fixes
    `parce`, `Jo`, but also breaks real words; +0.1–1.5 pts depending on tuning. Dropped.
  - Two readings + language model (`scratch/platon_rover.py`): too weak to settle ties.
  - **Three-way word vote** (`scratch/platon_vote.py`): best and simplest. Kept.
- New `consensus.py`: each scanned page is re-read by Tesseract (CLI, 300 dpi,
  underlines erased) and Apple Vision (`ocrmac`); readings are aligned with the page's
  letter-run tokens (difflib); a word changes when both other readings agree on another
  word that is more common in the book (leave-one-out), and accents are only added.
  Pages that Tesseract already wrote (redone underlined pages) use the original
  (ABBYY) layer as the second voter instead.
- Fixes are stored per page as `/PdfWorkerFixes` (JSON: box, old, new) and applied in
  `layout.page_lines`, so sizes, fonts and positions (footnotes, headings) are kept.
- `kindle` runs it on scanned books after any OCR step and reports the count.
  `ocrmac` added to the `ocr` extra (macOS only); without it the step is skipped.
- Results on the Platón book: ~600 words fixed, 4 min for 293 pages (kindle total
  ~7 min). pp. 19–20: recall 0.924 → 0.936, precision 0.951 → 0.964. Underlined
  pp. 9–15: 0.945 → 0.952. Spot checks: the large majority of fixes are right; wrong
  ones cluster in foreign-language bibliography lines and one-letter words.
- Tests: `tests/test_consensus.py` (4).
- Next ideas: a fourth reader (PaddleOCR-VL, slow) would allow 3-of-4 votes; footnote
  reference linking is still open.

### Paddle fixes on test_familia (2026-10-14)
- `convert ... --ocr redo --ocr-engine paddle` failed now and then with MLX server 500
  "[broadcast_shapes] Shapes (8) and (2) cannot be broadcast": paddlex sends up to 200
  concurrent block requests and mlx_vlm.server's batching breaks on mixed crop sizes.
  Fix: `vl_rec_max_concurrency=1` in `paddle_worker.py`.
- Table blocks came back as raw HTML and went into the text layer; sometimes the cover's
  dog mosaic was read as a looping table ("Nīlus fluvius est..." ×15). `clean_text` now
  flattens tables and drops ones with <30% distinct words. Tests: 2 in
  `tests/test_paddle_ocr.py`.

### Paddle footnotes on test_platon_bad (2026-10-14)
- User: in `test_platon_bad.reflowed.pdf` a short paragraph came out smaller, showed a
  literal `^{1}`, and footnote 1 sat mid-text (between "redac-" and "ción").
- Cause (raw blocks for pp. 8–9 in `scratch/platon_paddle/pages.jsonl`): Paddle writes
  references as `$ ^{1} $`, labels notes `footnote` but drops most of their numbers, and
  every block was fitted at its own largest size, so tight short blocks went note-sized
  and notes were body-sized.
- Fix: `clean_text` turns `^{n}` into Unicode superscripts (and drops `<sup>`/`<sub>`);
  `layout._with_text` makes Unicode superscript digits their own SUPERSCRIPT spans (all
  books); `write_blocks` uses one body size per page (longest text block), writes
  footnotes at 0.8 of it and numbers unnumbered notes from the page's references;
  `_fit_text` shrinks in 4% steps and allows a line's leading below the box.
- Paragraphs also split at page breaks ("definitivamente | resuelto", "redac- | ción"):
  every text block got the paragraph indent. Now a block opening in lowercase doesn't.
- Full re-run (`convert --ocr redo --ocr-engine paddle`, output in
  `scratch/platon_paddle/`): 9 notes, all linked; both page-break joins right.
- Tests: `test_footnotes_are_numbered_small_and_referenced`,
  `test_clean_text_turns_latex_superscripts_into_references`. All tests pass.

### Footnotes at the foot of the page in reflowed PDFs (2026-10-14)
- User asked for each note under the page that refers to it, not at the end.
- `pdf_export.py`: notes leave the end section (`_split_notes`; refs lose their `href`,
  else Story raises on the missing target). The book is laid out repeatedly
  (`_typeset`, Story positions give each `r<n>` ref's page/rect) with room kept at each
  page's foot (`_room_needed`) until every page's notes fit; notes are drawn with
  `insert_htmlbox` under a short rule, links both ways added by hand (`_place_notes`).
- Oscillation seen on Platon p. 3 (ref 4 slipping back and forth): a ref too low for its
  note to fit under it now pushes its line to the next page. After 3 exact passes room
  only grows (guaranteed to settle); max 12 passes.
- Stay at the end: notes taller than 40% of the text frame, and notes no text refers to
  (Platon's `*` note). EPUB/HTML/MD unchanged.
- Tests: `test_reflowed_pdf_puts_footnotes_at_the_foot_of_their_page`,
  `test_a_reference_too_low_for_its_note_moves_to_the_next_page`. All 147 pass.
- Output: `scratch/platon_paddle/test_platon_bad.reflowed.pdf` (from `ocr.pdf`, a Paddle
  OCR of the scan, reusable to skip the slow OCR).

### Margin references (Stephanus) and running heads (2026-10-14)
- User tested `test_pdfs/test_platon_bad_2.pdf` (2 pages, Timeo 22a–23a). Asked: running
  heads "TIMEO"/"DIÁLOGOS" ended up as text; the margin "22", "b" ... "e", "23" should be
  kept as paragraph references, never mixed up with footnotes. User's choices: running
  title once as the opening heading, repeats dropped; labels in full ("22a", "22b");
  all formats (PDF margin; EPUB/HTML green bold inline; txt `[22b]`; md/docx bold `[22b]`).
- Running heads: `structure._running_heads` — small lines in the top 10% on one row with
  the page number (or "TIMEO 163" on one line), found per page so they work on 2-page
  books (the repeated-text rule needs 3+ pages). The right-hand page's head becomes a
  level-1 heading once, only if the book has no heading yet.
- Margin refs: new inline marker (`inline.margin_ref`, U+E009/U+E00A; `plain` strips it),
  placed at the start of the printed line. New `margin_refs.py`:
  - `next_label`: labels follow the sequence (a..e, then number+1); misread or
    unreadable marks take the next label; bare numbers on pages without letters (line
    numbers) are dropped (`structure._State._label_margin_refs`).
  - Layers that keep printed lines (ABBYY, Tesseract): `margins._trim_edge_marks` and the
    merged gutter numbers now keep the marks as markers instead of dropping them.
  - Paddle rewraps paragraphs and drops/garbles marks ("por c fuego" -> "por el juego"),
    so at OCR time `scan_page` finds ink blobs beside the column (Tesseract TSV gives the
    column and lines), reads each crop (x2, psm 7, whitelist `0-9a-e`), aligns the
    Tesseract words with Paddle's (difflib), removes what Paddle read of the mark, and
    stores the marks on the page (`/PdfWorkerMarginRefs`, box of the line's first word);
    `layout.page_lines` puts them into the text. Needs Tesseract; silently skipped
    without it.
  - PDF: the word after each ref carries its id; the label is drawn in the right margin
    (green Helvetica bold 7.5 pt). Story reports a span twice; the first can be on the
    line before, so the box with width is used.
- Result on test_platon_bad_2: 22a, 22b, 22c, 22d, 22e, 23a all on the right lines; Filebo
  (ABBYY, pp. 19-20) gives 11a–11d. Output:
  `scratch/platon2/test_platon_bad_2.reflowed.pdf`.
- Not done: standalone margin lines in Tesseract/ABBYY layers (a mark OCR'd as its own
  line, not glued onto a body line) are still dropped; margin refs inside footnotes.
- Tests: new `tests/test_margin_refs.py` (6); the glued-marks unit test and the Filebo
  integration test now expect the refs. All 153 pass, ruff clean.

## Paddle footnote numbering, margin-ref fixes (test_platon_bad_5, 2026-10-15)
- From the user's red highlights on `test_platon_bad_5.reflowed.pdf` (Paddle re-OCR).
- New `note_numbers.py`: `number_notes` numbers footnotes in sequence after the previous
  page's last note (a printed number wins only if 1 or expected..expected+2; a first note
  starting lowercase continues the previous page's note); `fix_refs` puts missing
  superscript refs into the text, from misread superscripts or from stray marks after a
  word in Tesseract's reading (filled only when places found == notes missing).
- `paddle_ocr.py`: `write_blocks` returns `(written, last_note)`, threaded page to page;
  margin-mark `aside_text` blocks skipped; narrow in-column text blocks (one-line
  speeches) written as body paragraphs at body size; `_fix_digit_words` takes Tesseract's
  all-letter reading for words like "FILE0", "S1.".
- `margin_refs.py`: unreadable crop falls back to Tesseract's own margin word (fixed 11);
  Paddle's inserted mark letters dropped ("y b pongo"); marks matched by first-char x0
  and y-centre (no mark on two overlapping lines).
- `images.py`: `_EDGE_SHARE` 0.6 → 0.3, so a partial book-edge shadow is blanked (fake
  picture at the bottom of p. 3 gone).
- Rejected: word vote (`consensus.vote_pdf`) on the Paddle layer (5 fixes, one wrong).
- Links ref ↔ note are valid; Preview doesn't move because the note is already visible.
- Scripts: `scratch/platon5_raw.py`, `platon5_replay.py`, `platon5_render.py`. Output:
  `scratch/platon5/test_platon_bad_5.reflowed.{txt,pdf,epub}`.
- Still Paddle misreads: "cuesta", "il El qué", "ol?ro", "declas", "Sốc.", "Pro- tarco".
- Tests: new `tests/test_note_numbers.py` (5), two new in `test_paddle_ocr.py`. 160 pass,
  ruff clean.

## Good-ePub comparison and direct-from-Paddle prototype (test_platon_bad_3, 2026-10-15)
- Full report: `scratch/platon3/REPORT.md`.
- `platon_dialogos_vi_good.pdf` = Titivillus ePub printed by calibre (notes at the end,
  numbered per part, transliterated Greek in italics). bad_3 pp. 6–36 = good pp. 6–23;
  printed p. 18 is missing from the test file.
- Scripts: `scratch/platon3_raw.py` (Paddle raw blocks + current pipeline),
  `platon3_score.py` (scores a .txt against the good PDF: words, paragraphs, refs,
  notes, margin refs), `platon3_direct.py` (prototype: book built from Paddle's labels,
  no text layer), `good_*.py` probes.
- Library: `paddle_ocr.prepare_blocks` split out of `write_blocks` (same behaviour);
  `number_notes`: a read "1" alone no longer restarts the count, an unnumbered first
  note continues the previous page's when the next note has the number due;
  `scan_page`: one margin mark per line (split marks gave double labels). New tests.
- Scores (current → prototype): word errors 2.3% → 1.8%, extra paragraph breaks 23 → 3,
  refs 53 → 52/57, notes mean similarity 0.83 → 0.87, margin refs 53/54 both.
- Not done: front matter/heading levels, italics, small caps, endnotes option in the
  real PDF writer; proposal in the report awaits approval. 160 tests pass, ruff clean.

## Paddle books built from Paddle's blocks (2026-10-15)
- User approved the proposal. New `paddle_book.py` (`iter_paddle_blocks`): Paddle's
  labels decide the structure; front matter (leading pages < 60 words) dropped; running
  heads/page numbers/footers dropped, a "header" low on the page kept as a small line
  (dramatis personae); paragraphs joined across pages; notes labelled per part
  (`c<part>-<n>`); margin refs, page marks (printed page numbers), pictures from
  Paddle's image boxes; speaker names normalised ("SÓC. — "); "Pro- tarco" joined.
- `paddle_ocr`: `paddle_pages` caches Paddle's rows per file (sha256 + model) in
  `cache_dir()/pages/*.jsonl`, resumes interrupted runs; `ocr_pdf_paddle` uses it;
  `text_settings` / `page_scanner` shared by the text-layer and book paths;
  `clean_text` keeps only the digits of a superscript like "^{2k}".
- `note_numbers.fix_refs`: a plain number equal to a due note ("número 27.") is that
  reference.
- `convert_pdf(..., notes_at="page"|"end", paddle_rows=...)`; CLI `convert --notes
  end|page`; `convert --ocr redo|force --ocr-engine paddle` takes the new path (`skip`
  keeps the text-layer path). README updated.
- Tests: `tests/test_paddle_book.py` (3), new cases in `test_note_numbers.py` and
  `test_paddle_ocr.py`; scorer moved to `tests/platon_score.py`; integration test
  `tests/test_paddle_book_platon.py` (needs the cached Paddle pages in
  scratch/paddle-home; seeded with `scratch/seed_cache.py`). 165 pass, ruff clean.
- Scores via the CLI (`scratch/platon3_cli.py`, output `scratch/platon3/book.*`): word
  errors 1.7%, extra paragraph breaks 4, refs 55/57, notes mean 0.87, margin 53/54.
- Still open: italics, small caps, centred dramatis personae, heading levels
  (Filebo > Introducción), Greek-alphabet font, Paddle misreads.

## Endnote back-arrow (2026-10-15)
- User asked for a back-link from endnotes to the text, like the good PDF's "<<"; chose
  "↩" for PDF and EPUB. The note number already linked back but didn't look like a link.
- `epub._write_note`: each note with a reference ends with
  `<a class="back" role="doc-backlink">↩</a>`. The PDF gets it via the HTML; MuPDF
  draws it with its NotoSansMath fallback (U+FE0E would show a box, so it isn't used).
  `pdf_export._split_notes` drops it from notes set at the page foot.
- Tests: `test_convert` (EPUB markup), `test_formats` (no arrow at the page foot; with
  `notes_at="end"` the arrow links to the reference's page). 166 pass, ruff clean.
- Platón book: 55 arrows for 56 notes, all linked (intro 8 has no reference).

## Search for missing note references (2026-10-15)
- User noticed the bad PDF's own (ABBYY) layer has intro note 8's "causa⁸" (size 8.8
  after 10.7) and asked for a bounded search for references whose note is on the page.
- New `missing_refs.py`: `missing_numbers` (page notes minus page refs); `restore`
  narrows to the words between the neighbouring refs and runs three tries, stopping
  at the first: `text_layer` (a smaller number after a word in the PDF's layer),
  `tesseract_try` (Tesseract on the stretch at 600 dpi: "causa8."/"causa 8."),
  `PaddleClips` (Paddle on a crop at 400 dpi; the MLX server starts at the first crop
  and stops at the end). A try counts only with exactly one candidate that matches
  exactly one ref-less Paddle word in the stretch.
- Wired into `paddle_book.iter_paddle_blocks(restored=...)`; `ConvertReport.restored_refs`;
  the CLI prints "note 8 reference restored from text layer, page 13".
- `note_numbers.add_ref` split out of `fix_refs`; `paddle_ocr._run_worker(dpi=)`.
- Platón: refs 56/57 (only intro 10 left; its page is missing), 56 arrows for 56 notes.
  Checked by hand: Tesseract and the Paddle crop both miss this "8" (faint, against a
  pen underline); the Paddle crop does read "placer⁹" on page 11.
- Tests: `tests/test_missing_refs.py` (6); integration refs threshold 54 -> 55. 172
  pass, ruff clean.
- Shortcut: Paddle crops are not cached (a rerun can differ); only the Paddle path
  searches, not `--ocr skip`'s text-layer path.

## Greek variants table, words lost as margin marks (test_platon_bad_4, 2026-10-15)
- bad_4: 25 pages, copyright page + Filebo intro (with note 10, "Nota al texto" and its
  table of Greek variants) + start of the dialogue. Run: `scratch/platon4_cli.py`,
  output `scratch/platon4/book.*`; check `scratch/platon4_check.py`.
- Notes: intro 1–10 and dialogue 1–16, every reference in place (note 10 included).
- Greek: Paddle labels the table "algorithm" and reads the polytonic Greek as Latin
  look-alikes ("τὰ δέοντα" -> "tà šèovta"). It stays inside that one block: the text
  around it is intact. Tesseract `spa+grc` on the crop (`scratch/platon4_tess.py`) reads
  the Greek well but garbles the Latin in it ("corchetes" -> "οογέπειες"). Not fixed yet;
  the table is also flattened to one paragraph (its line breaks are lost).
- Bug fixed (`margin_refs`): the table's indented lines set the column's right edge, so
  justified prose ending further right counted as margin. `mark_paddle_blocks` then
  deleted those words ("Platonis Opera," "en los casos", "volumen han", "a cabo por")
  and the ink became fake marks ([a], [b], [c], [2a], [1e]) that also threw off the
  dialogue's numbering ([2b] for 11a). Now a margin word both OCRs read alike is dropped
  only if it is mark-shaped, and a word with 3+ letters is body ink, not a mark.
  Result: words back, dialogue starts at [11a].
- Tests: `test_a_word_past_a_column_measured_too_narrow_stays`. 173 pass, ruff clean.

## Familia "better" scan: reader's marks removed (Step 1 of 2026-10-15 list)
- `test_familia_better_with_notes.pdf` (6 pages, same pages as test_familia_bad): the
  highlights/underlines were PDF annotations (Highlight, Underline, with popup notes);
  the scan itself has no handwriting (only dust specks). Stripped them
  (`scratch/familia_better_strip.py`) into `test_pdfs/test_familia_better.pdf`, deleted
  the original (user's choice).
- Its OCR layer is *not* better (`scratch/familia_layer_diff.py`): "est." -> "esto"
  everywhere (Spanish model), "ī" -> "I", "m" -> "rn", small-cap c -> "e", "littera" ->
  "linera"; no macrons in either layer. Per the user, Step 1 stops here.
- Library: every page render (`paddle_worker`, `consensus._page_image`, underline
  detection, OCR probe, figures/cover, missing-ref crops) now passes `annots=False`, and
  OCRmyPDF's source copy (`ocr._ocr_source_copy`, was `_zero_origin_copy`) drops markup
  annotations (`ocr.MARKUP_ANNOTS`; links stay). Test:
  `test_a_readers_marks_are_dropped_before_ocr`.

## Whole Platón book (Step 2 of 2026-10-15 list), branch feature/platon-full
- Progress for whole-book runs: `paddle_pages(on_page=)`, `convert_pdf(on_page=)`; the CLI
  prints "Step 1/2, OCR: 41% (120/293 pages), about 35 min left" (one rewritten line on
  a terminal, a line per 5% in a log), then "Step 2/2, building the book".
- Full Paddle OCR of the 293 pages is cached (`scratch/platon_full_ocr.py`, ~1 h with
  other work running). Builds from the cache: `scratch/platon_full.py FIRST-LAST [fmt..]`
  (output `scratch/platon_full/book_*.{txt,pdf,epub}`); scoring:
  `tests/platon_score.py book.txt --pages 6-175 [--show refs,mref,notes,para,words]`
  (any good-PDF page range now; parts/dialogues counted from restarts).
- Fixes found by cutting the book into 1-80, 81-160, then the whole:
  - Margin refs: `margin_refs.assign_labels` labels a dialogue's marks at once (dynamic
    programming: pencil blobs are junk, letters misread, labels skipped). The greedy
    `next_label` ran one ahead after a stray mark (99 wrong lines on pp. 1-80). Runs
    break at headings and at 4+ pages without marks; a run needs two page numbers read
    exactly (introductions' pencil and outline numbers label nothing).
  - Notes: a note broken off mid-sentence goes on at the next page's unnumbered first
    note when nothing there refers to the note due (`left_open`); "π" for "78"; a lost
    first reference still restarts the count (text and note both read "2" where 54 was
    due); printer's signatures ("160. — 18") are not notes; pages missing from the scan
    (printed 279 -> 282) reset the count from the page's first reference.
  - Garbling: "¿" read as i/l/ℓ/2 ("iY bien?") restored with the book's own vocabulary;
    margin marks read as words beside their label dropped; LaTeX commands unwrapped;
    "^{1267}" = ref 126 + "?"; made-up Vietnamese replaced by Tesseract's words of that
    box (`ScanWord.box`); Vietnamese letters in Spanish mapped back ("Sốc." -> "Sóc.");
    the Greek variants table (Paddle label "algorithm") re-read by `mixed_script`
    (Tesseract spa and grc, more confident word wins), one small line per table row.
- Whole book scores (good pp. 6-175): word errors 2.0%, refs 348/367 (6 are on the two
  pages missing from the scan), notes 355/367, margin refs 620/714 on the right line.

## philosophy.pdf, Copleston VI (Step 3 of 2026-10-15 list), branch feature/platon-full
- 462 pages, Spanish, Acrobat OCR layer (poor). Paddle OCR cached in the background
  (`scratch/paddle_cache_book.py`); builds of page ranges with `scratch/book_build.py PDF
  A-B scratch/philo [txt md pdf epub]`. No good edition: judged against page images
  (crops via `scratch/crop.py`) and with an exact reference/note link check on the
  Markdown output (`scratch/link_check.py`).
- No margin references are inserted anywhere (the label assignment needs two page
  numbers read exactly; this book has none).
- The "hand-made annotations" are pencil ticks (✓) at line ends in the right margin
  (e.g. p. 83). Paddle ignores them in the text; one became a margin note "！": margin
  blocks without a letter or digit are now dropped. No colour, no underlines found
  (`scratch/ink_pages.py`, `scratch/margin_ink.py`).
- Fixes: printed contents pages (Paddle label "content") dropped; note numbers printed
  "17." read; a read note number further ahead is kept when the text has that reference
  (notes 30-32 missed had pushed every later note 3-7 back); notes Paddle skipped (or
  whose page it saw no note on) recovered from Tesseract's lines; footer-labelled notes
  ("16. De l'esprit", "15. C.S.") relabelled; references glued after punctuation
  ("constricción”.5") in Paddle's text and in the PDF's layer; the printer's-signature
  filter narrowed (it had dropped notes like "31. 7."); a few made-up Chinese letters in
  a good block replaced by Tesseract's words.
- Link check: pp. 41-150 169 refs / 167 notes, 2 notes without their reference;
  pp. 151-290 227 / 225, 1 ref without a note, 2 notes without a reference;
  pp. 291-370 204 / 202 (before 1aa45be: "fórmula32" glued refs, two notes in one block
  split; not re-checked since).
- Later commits: 1aa45be (glued refs on a lowercase word, merged note blocks split).
  Platón regression after all of it (clean build): words 1.9%, refs 350/367, notes 358,
  margin 645/714 — unchanged or better.
- Scratch gotcha: `scratch/platon_full.py` no longer merges running-job work files (they
  were philosophy's and overwrote Platón pages). `scratch/book_build.py` still merges
  them with setdefault (fine when the running job is the same PDF).

## NIGHT PLAN (user, 2026-10-16) — START HERE, supersedes "Next steps" below
Be token-efficient: summaries only, at most 3-4 page images (step 2), nothing beyond these
steps. Reports go in `scratch/NIGHT_REPORT.md`, one short section per step, numbers only
(counts, time and token estimates); a short entry here too. Commit locally on
`feature/platon-full`, never push. Order: 1 -> 2 -> 5 -> 6 -> 3.
Checkpoints: after each step, mark it "[done]" here with its result line and commit, so a
session cut off by the token limit resumes at the first step not marked done (the user
restarts it with "continue from PROGRESS.md" after the limit resets). Long builds: start
them in the background and note the command here first.
FIRST ACTION of the session: CronList; if no such job exists, CronCreate a recurring
hourly job (off the :00/:30 marks, e.g. "17 * * * *") with the prompt "Night plan: if
any step in PROGRESS.md NIGHT PLAN is not marked [done] and no step is in progress in
this session, continue it from PROGRESS.md; otherwise do nothing." This resumes the work
after the 5-hour token window resets (the session must stay open). When all steps are
done: CronDelete the job and say so in the report.
1. [done] Result: 689 refs/683 notes (1 ref, 5 notes unmatched); 11 false `[193a]`-style
   labels, all in the bibliography; body garble: 1 lost Greek word, 2 odd letters
   (details in `scratch/NIGHT_REPORT.md`). Cron job e2a82415 created.
   Philosophy whole book (`scratch/philo/book_1-462.{md,txt}` already built): run
   `scratch/link_check.py` on the .md, `scratch/garble_scan.py` on the .txt, and check no
   `[NNa]` margin labels. Do NOT fix: report each error kind, how often it happens, and
   estimated time/tokens to fix.
2. [done] epubcheck clean; PDF 805 pages, 0 broken links, 11 margin labels (the
   bibliography ones); pp. 120, 500 look right. Build philosophy pdf + epub (`scratch/book_build.py test_pdfs/philosophy.pdf 1-462
   scratch/philo pdf epub`), epubcheck, `scratch/check_book_pdf.py`, look at 2-3 rendered
   pages. Report.
3. [done] Identical to the baseline below. All night steps done; cron job deleted.
   (run last) Re-score Platón: `scratch/platon_full.py 1-293`, then
   `tests/platon_score.py scratch/platon_full/book_1-293.txt --pages 6-175`. Baseline:
   words 1.9%, refs 350/367, notes 358, margin ok 645 / wrong 38 / missing 31 / extra 5.
   Report differences.
4. Book note-style profile: do NOT build; it stays in the TODO list below.
5. Margin refs estimated for missing marks (user's design): for labels missing between
   two found labels, count the words between those two found labels, split them evenly
   over the sections in between, place each estimate there (snapped to a line/word
   start). Skip labels missing at a dialogue's start/end (no second anchor). Optional,
   off by default (e.g. `convert --estimate-margin-refs`); estimated labels drawn PINK
   in every format that colours them (found ones stay green; txt/md need a marker, e.g.
   `[~23d]` — choose and document). First a dry run on Platón: how many of the 31
   missing get an estimate, and how many land within ±1 line of the good edition (the
   scorer). Build it unless fewer than half land within ~3 lines; then report only.
   [done] `margin_estimates.py`, `convert --estimate-margin-refs`, "[~23c]", pink in
   EPUB/HTML/PDF. Dry run: 40 estimates, 21 judgeable, 15 within 3 lines (7 within 1).
6. [done] `--notes none` (`drop_notes.py`, tests in test_endnotes.py); 180 fast tests pass.
   `convert --notes none`: drop notes (incl. an endnotes chapter) and strip reference
   markers ([12], ¹², [^c1-12]) in all formats; keep margin refs (11a...). Unit test.
   Uses the cached Paddle pages (no OCR rerun).

## Resume point (2026-10-15, session paused by the user)
- Branch `feature/platon-full` (on top of `feature/familia-better`), all committed,
  nothing pushed (user pushes). 174 unit tests pass, ruff clean.
- Philosophy OCR is complete: all 462 pages are in the Paddle cache
  (`scratch/paddle-home`). A whole-book build was started in the background at pause:
  `scratch/book_build.py test_pdfs/philosophy.pdf 1-462 scratch/philo md txt` ->
  `scratch/philo/book_1-462.{md,txt}` (may or may not have finished; rerun if missing).
- Next steps, in order:
  1. Philosophy whole book: `scratch/link_check.py scratch/philo/book_1-462.md`,
     `scratch/garble_scan.py scratch/philo/book_1-462.txt`, check no `[NNa]` margin
     labels; fix what shows up (sample page images with `scratch/crop.py PAGE Y0 Y1 DPI
     test_pdfs/philosophy.pdf`; raw Paddle blocks with `scratch/philo_raw.py`,
     `scratch/philo_find.py`, `scratch/philo_refs.py`).
  2. Build philosophy pdf + epub (`book_build.py ... pdf epub`), epubcheck, and
     `scratch/check_book_pdf.py` on the PDF; look at a couple of rendered pages.
  3. Re-check Platón after any fix (`scratch/platon_full.py 1-293 [txt pdf epub]`,
     `tests/platon_score.py book_1-293.txt --pages 6-175 [--show refs,mref]`).
  4. Then the user's requested improvement (asked 2026-10-15, to do after the
     iterations): the "Book profile for notes" in the TODO below — detect the note style
     from a 10-20 page sample, pass it to the build as a default (like `text_settings`),
     keep per-page fallbacks; re-run both books and compare scores.
  5. Final report to the user for Steps 2 and 3 (errors found, fixes, remaining issues:
     ~10% margin refs off, a few lost refs/notes, Paddle word misreads/accents,
     Critias pp. 280-281 missing from the scan).

## Blocked
- 2026-10-16: `gh pr merge 28 --merge` (feature/spelling-refine) denied by the auto-mode
  classifier (Merge Without Review); the user merged it. The repo has no CI workflow
  (no `.github/`), so PRs get no checks.
- 2026-10-15: `gh pr merge 23 --merge` denied by the auto-mode classifier (Merge Without
  Review); PRs #23 and #19 still open.
- 2026-10-15: committed 9e86cbf (footnote/margin-ref fixes). Denied: committing the
  code-review-graph tooling files and `git push origin feature/bad-scans-2`; nothing
  pushed or merged.
- 2026-10-13: `gh pr merge 20` was denied by the permission classifier; the user has to
  merge PR #20 (and the stacked PR) themselves or allow `gh pr merge`.
- (Earlier: Claude couldn't edit `.claude/settings.local.json` itself, so the user copied
  in the version from `scratch/settings.local.json` on 2026-10-11.)

## Resume here (keep this current; a new session should start from this)
- **The overnight list is complete: items 1–10 (PRs #9–#16).** Kindle check done
  (2026-10-13): cover and links work; page numbers don't survive Send to Kindle (see
  the `pdf-worker help` entry).
- No CI: the user asked (2026-10-13) to remove the GitHub Actions tests, and they were
  removed in PR #17. Don't add CI back; run tests locally.
- **Overnight task (user request 2026-10-12): do next steps 1–8, PR and merge each.**
  The user's answers:
  - Test books: download public-domain footnoted and endnoted books (archive.org,
    Gutenberg) into `test_pdfs/` (gitignored).
  - Output formats for item 7: docx, HTML, clean plain text, reflowed PDF (EPUB and
    Markdown exist already).
  - Paddle: `--engine paddle` auto-starts and stops the MLX server from `.venv-paddle`.
  - Printed contents pages: drop them (the EPUB has its own TOC).

  The items, with status:
  1. [x] Endnotes referenced by superscripts, with notes in a "Notes" section/chapter
     (PR #9, together with item 2).
  2. [x] Real footnoted books: downloaded the court opinion, the 9/11 report and the
     Gibbon scan, tuned detection on them, added integration tests.
  3. [x] Images and a cover in the EPUB (PR #11).
  4. [x] One-step `pdf-worker kindle`: auto-detect OCR need and mode, then EPUB (PR #12).
  5. [x] `--engine paddle` (opt-in) (PR #13).
  6. [x] Clean-ups: tables in EPUB, drop the printed TOC, fewer false headings, keep the
     title for OCR'd files (PR #14).
  7. [x] Formats: docx, html, txt, pdf (PR #15).
  8. [x] GitHub Actions CI (PR #16).
  9. [x] (PR #10) (added mid-task) Internal links: PDF link annotations (contents entries,
     cross-references) become working EPUB links to the target chapter or page. The
     user noticed the encyclical's index wasn't linked. A printed TOC whose entries
     resolve to links is kept as a linked list; one without links is dropped.
  10. [x] (PR #10) (added mid-task) Kindle page numbers instead of only "Loc": EPUB 3 page-list
     nav, `epub:type="pagebreak"` markers and an NCX pageList, using the printed page
     labels. These are fixed to the text, so they work at any font size, like store
     ebooks. Can't verify on a device: the user should check.
- User feedback: the EPUB footnotes "worked perfectly" on Kindle.
- Shipped: footnotes (PR #2), OCR plan (PR #3), EPUB/Markdown conversion (PR #4), OCR
  phase 1 (Tesseract, PR #5), Latin macrons (PR #6), and margin glosses and line numbers
  (PR #7).
- The PaddleOCR-VL evaluation (OCR phase 2) is done, on branch `feature/paddle-eval`
  (PR #8). Steps 1–3 of the 2026-10-12 request are complete.
- Kindle check (2026-10-12): the user reported that footnotes in the EPUB "worked
  perfectly" on their Kindle (the encyclical, 224 linked notes). Keep the current
  footnote markup (noteref links, `epub:type="footnote"` asides in `notes.xhtml`,
  backlinks).
- Candidate next steps:
  - OCR phase 3: `--engine paddle` (opt-in, slow, much better on diacritics).
  - Images in EPUB.
  - Superscript-referenced endnotes ("Notes" chapters).
  - Skip the on-page table of contents.
- epubcheck is installed via brew at `/opt/homebrew/bin/epubcheck`.
- Before resuming: `git status`, `git switch main`, `git pull --ff-only`.

## Next
User's feature list (2026-10-11). Ship each with a PR and merge it:
1. Footnotes stated explicitly in text extraction. Done (Feature 2).
2. OCR: research the best free tools, then write a plan. Plan done (`docs/ocr-plan.md`).
3. Conversion: EPUB (Kindle-friendly) and Markdown from the extracted text. Done
   (Feature 3).
4. (2026-10-12) "Choose the best [OCR] and implement it": Tesseract/OCRmyPDF. Done
   (Feature 4).
5. (2026-10-12) "Complete the next steps 1, 2 and 3": Latin macrons (PR #6), margin
   glosses and line numbers (PR #7), PaddleOCR-VL evaluation (PR #8). Done.

## Margin refs off by default, rebuilds (2026-10-16, user's answers)
- `convert --margin-refs` (off by default: only classical editions have them; ink in
  other books' margins made false labels, e.g. philosophy's bibliography "[193a]").
  `convert_pdf(margin_refs=)`, `iter_paddle_blocks(margin_refs=)` skips labelling, the
  text-layer path strips the markers. `--estimate-margin-refs` implies it. `kindle`
  keeps the default (off). Scratch: `platon_full.py ... [--estimate] [--notes-end]`
  (margin refs on), `book_build.py ... [--margin-refs] [--notes-end]`.
- Rebuilt with notes at the end (`--notes end` avoids the page-foot overlap below):
  Platón pdf+epub with estimates, philosophy pdf+epub without margin refs.
  Platón: epubcheck clean; PDF 293 pages, 1563 links, 0 broken, 688 margin labels
  (estimates pink, e.g. p. 27 "~21b"), 1 stray "$". Philosophy: epubcheck clean; PDF
  759 pages, 3260 links, 0 broken, 0 margin labels; p. 396 ("futilidad") no overlap.
  Seen on Platón p. 27: "ipodrias" for "¿podrías" (an "¿" misread not restored).

## TODO (user, 2026-10-15: later, low priority)
- Reflowed PDF, `--notes page`: notes can overlap the text (philosophy p. 446 under
  "futilidad"). MuPDF Story has no footnotes: `pdf_export` guesses each page's room for
  notes and lays the book out again, up to `_MAX_PASSES` (12); if it hasn't settled it
  draws the notes anyway. `check_book_pdf.py` doesn't test overlap. Options (user chose
  `--notes end` for now): (a) Typst writer: Markdown -> Pandoc (3.10 has a typst
  writer) -> `typst` (pip, into .venv); native footnotes, hyphenation by language,
  notes split across pages, widows/orphans, layout in seconds; margin refs inline first
  (~1-2 h), in the margin later; check Libertinus has polytonic Greek. (b) page-by-page
  layout in the current engine, LaTeX-style (~2 h). (c) quick patch: notes that don't fit
  after the last pass go to the end section (~30 min).
- Wrong letters from Paddle (user: note only, don't fix now): "volūmenes" (philosophy
  PDF p. 85), "brevę" (p. 571), macron for umlaut in German names ("Būtzow",
  "SCHŌNEBAUM"), Cyrillic "Во" in "ВоHATEC". Fix: map ū->ü/ú, ę->e, Cyrillic look-alikes
  by the word's language (~15 min).
- Notes without a reference (user: note only, don't fix now): philosophy c3-6, c6-5,
  c10-30, c11-71, c15-16 (e.g. PDF p. 804, "En sus últimos años Herder..."): the note was
  found but its superscript in the text was not. (A reference without a note, c9-2 p.
  285, is already shown as "no note found": fine.)
- Book profile for notes (user asked 2026-10-15 to keep this for later): after Paddle
  reads a sample of 10-20 pages (they are cached anyway), detect the book's note style
  once: number format (superscript / "17." / "1)"), restart per chapter or part,
  page-foot notes or endnotes, margin references present or not, printer's signatures
  at the foot, outer-margin side, reader's marks. Pass it to the book build like
  `text_settings` does for the language, as a default; keep the per-page fallbacks
  (books mix styles, e.g. Platón's introductions vs dialogues).
- Greek in Paddle books: Paddle reads polytonic Greek as Latin look-alikes
  ("τὰ δέοντα" -> "tà šèovta"); see test_platon_bad_4 p16, the "Nota al texto" variants
  table (Paddle label "algorithm"). Plan: re-read such blocks with Tesseract `spa+grc`
  (`scratch/platon4_tess.py` reads the Greek well, garbles the Latin), take Tesseract's
  words where they are Greek and Paddle's elsewhere, and keep the block's line breaks
  (now flattened to one paragraph).
- Same table in the EPUB (seen in iBooks): shows the garbled Latin-letter text. This is
  the same Paddle misreading, not an EPUB/font problem; the fix above covers both.

## TODO after #43/#44 (user, 2026-10-21: keep as the list; suggested order)
1. Regression check: the lossy note pairing (#44) runs on every book, only the Timeo was
   rebuilt. Re-score Platón against its baseline (words 1.9%, refs 350/367, notes 358,
   margin ok 645 / wrong 38 / missing 31 / extra 5) and rebuild philosophy + link check.
2. Timeo, small (~15-30 min each): title "Platón Time o"; "NOTAS A LA TRADUCCIÓN" not a
   heading; running head "INTRODUCCIÓN" left in the text; space before punctuation
   ("nacido ,"); p471 contents lines taken as footnotes; margin ref "[24_.e]" missed.
3. Timeo, bigger: ~170 notes without a reference (OCR garbled it: "Heracles73•" for 78,
   "todos'º5" for 105), maybe recover from the number sequence; notes whose number is
   garbled are folded into the note before; ~115 garbled Greek tokens.
4. From the TODO above: Paddle wrong letters (~15 min); `--notes page` overlap in the
   reflowed PDF (Typst ~1-2 h, or patch ~30 min); 5 philosophy notes without a found
   reference; book note-style profile and more `find_book` sources (user: later).
5. Housekeeping: `.claude/settings.json.bak` untracked, the user decides.
6. DONE 2026-10-22 (`document.TEXT_FLAGS`). Ligatures (user, 2026-10-22): typesetters join letter pairs into one glyph ("fi" →
   ﬁ U+FB01, "fl" → ﬂ), so "ﬁgura" is a different string from "figura" and the
   dictionary misses it. pdf-worker's own reflowed PDF has ~1,000 (its typesetter uses
   ligatures); source PDFs can too (Introducción a la Filosofía: 5; Kant, Gibbon: none).
   Fix in pdf-worker: one line at text extraction turning ligatures back into plain
   letters. The pipeline hands over pre-typesetting text, so only source PDFs need it.

## Reflowed PDF size (2026-10-21, branch feature/pdf-font-subset)
The Timeo's reflowed PDF was 39 MB: 611 embedded font objects (MuPDF Story embeds each
font whole, per use), 1 MB of images. `pdf_export` now calls `doc.subset_fonts()` and
saves with `garbage=4`: 4.5 MB, same text on all 519 pages, same 1610 links.

## Progress, notes at the end, Greek dropped (2026-10-21, branch feature/progress-greek)
User's choices: notes at the end by default; Greek pages dropped by their letters;
long Greek paragraphs dropped in bilingual books only, listed in the review file as
`ignore` and never sent to the AI review.
- Profile of a Timeo-Platón build (`--notes page`, 388 s): 12 layout passes 184 s +
  measuring the notes 77 s; spelling while building ~47 s, sorting the flagged words 33 s;
  re-reading garbled words 25 s; layout analysis 6 s.
- `--notes end` is the default (cli, `convert_pdf`, `write_pdf`): one layout pass.
- Progress: `convert_pdf(on_step=)`; the CLI passes `_progress` (now with a unit): "Step
  1/5, re-reading garbled words: 45% (510/1133 lines), under a minute left". Steps:
  re-reading (lines), layout (pages), building (pages), PDF layout (passes, pdf only),
  sorting flagged words. A rewritten line on a terminal, a line per 5% in a log.
- `tools/run_logged.py NAME CMD...` starts a long command detached, log in
  `scratch/logs/NAME.log` (the Bash tool's background mode keeps output in /private/tmp);
  `tools/wait_log.py LOG` waits for its end. Rule in CLAUDE.md.
- `bilingual.facing_pages`: a page of 40+ words with 60%+ Greek letters is a facing page,
  no neighbours needed (Timeo-Platón's split words left its Spanish pages at 0.16-0.24
  stopwords, under the 0.25 the old test needs: 42 Greek pages were kept).
- `bilingual.drop_greek` (bilingual books): paragraphs of 15+ words, 90%+ Greek letters,
  are left out (their page marks go to the next block); `Review.left_out` lists them as
  `greek-dropped` rows, action `ignore`, status `dropped`. At 60% it dropped a
  bibliography entry with a Greek title (Timeo-Platón p146, 0.8).
- Rebuilds: Timeo_by_Platón 71 s (749 notes, 104 facing pages, unchanged); Timeo-Platón
  103 s, was 327 s (104 facing pages, was 62; 0 paragraphs dropped). Pages still mostly
  Greek in its output: 3, the variants table of the "Nota al texto" (kept on purpose).

## Philosophy EPUB vs reference (2026-10-19)
User added `test_pdfs/philosophy_epub_good.epub`. Compared with `scratch/philo/book_1-462.epub`
via `scratch/epub_compare.py` (structure) and `scratch/epub_worddiff.py` (word counts).
- Size: ours 215k words / 60 docs vs 204k / 29. Extra is mostly the analytic index
  (véase +586, también +368, s./ss. +1500, Kant +325); the reference has no index.
- Italics: reference has 2750 `<i>`, ours none found (no `<i>/<em>` tags).
- Notes: reference 1419 `<sup>` (~700 notes, links both ways); ours 689 sup + 684 aside.
- Headings: ours has copyright lines as h1 ("© 1960...", "Impreso en España") and a body
  sentence as heading ("6. La actividad de Jacobi..."); no h3 subsections (ref has 81).
- Lost accents: Paris/París 164, Berlin/Berlín 52, Munich, categorico, teologia,
  conclusion, albedrio, Dificilmente, *-icamente (not checked against the PDF print).
- OCR typos: empiismo, empiriismo, constrición, núumenos, Königssberg, desarrolloos,
  contribuieron, incognosible, Florenceia, wollfiana, ecuídea, "éase" (lost V).
- Leftover hyphen splits: leza, ción, miento.
- Straight ' vs typographic ’.
Not fixed; nothing changed in src.

## virus-check (2026-10-19)
`pdf-worker virus-check [file|url] [--upload]`: VirusTotal v3 via urllib, key
`VIRUS_TOTAL_API_KEY` from env/.env (`groq.api_key` got a `variable` param). Files: SHA-256
lookup, upload only with --upload or a yes in interactive mode. URLs: VirusTotal's URL
report plus the served file's report. No target: asks file (macOS dialog) or URL. Exit 2
when flagged. Files: `src/pdf_worker/virus_check.py`, `cli.py`, `tests/test_virus_check.py`.
Live check on `philosophy_epub_good.epub`: clean (65 undetected).

## find_book: CCEL and Cervantes Virtual (2026-10-20, branch `feature/find-book-sources`)
User supplied `Recursos Electrónicos Acceso Libre.pdf` (repo root): 471 links, 307 answer
200 (`scratch/recursos_links.py`, results `scratch/recursos_links.tsv`). Probed the best
book sources (`scratch/probe_sources*.py`):
- Google Books: 429 without an API key; downloads often need a captcha. Not added.
- OAPEN: search works (same Atom as DOAB), pages and PDFs 403 to scripts. Not added (DOAB).
- Cervantes Virtual: Cloudflare blocks the site; its SPARQL catalogue
  (`data.cervantesvirtual.com/bvmc-lod/repositories/data`) works. Added `_cervantes`:
  title words (whole words, shortest titles first), page-only candidates (open in browser).
- CCEL: search runs in the browser; title index per letter works. Added `_ccel` + resolve
  from the book page (PDF/EPUB download verified live).
- OpenEdition, MDZ: search only in the browser, no API found. Not added.
`_get` takes an optional `accept` header. Tests: 2 new in `tests/test_find_book.py`.
Next from the list if wanted: Google Books (user key), Documenta Catholica Omnia.
(User 2026-10-20: keep this list for later.)

## Margin references on by themselves (2026-10-20)
- `convert --margin-refs` is now `--margin-refs/--no-margin-refs`, default auto: kept when
  `margin_refs.in_book` (marks or labels on >= 20% of pages). Measured with
  `scratch/margin_share.py`: Platón labels on 230/293 pages (78%, marks 86%); philosophy
  labels 11 on 4/462 pages (1%, marks 11%: ink). `scratch/margin_auto.py`: by default
  Platón keeps 688, philosophy 0. Text-layer path counts pages with stored marks.
- Philosophy PDF rebuilt on main (`scratch/philo_final/`, notes at the end): 754 pages,
  10443 internal links, 0 broken; all 4756 "[n]" marks linked
  (`scratch/pdf_index_marks.py`).
- Ratzinger EPUB in `test_pdfs/` is our own output (2026-10-19), not a reference; its
  rebuild matches it except italics/bold (phase 2). User: find a real reference book.
- Doña Perfecta: the scan is the 1897 printing, PG 15725 the later one with a vocabulary
  and fewer notes, so notes can't be scored against it.
- Second reference book: Lugones, *El imperio jesuítico* (1904). Scan from Commons
  (`test_pdfs/lugones_imperio_jesuitico_1904.pdf`, 370 pp., text layer on 333) and the
  proofread Wikisource export of that scan
  (`test_pdfs/refs/lugones_imperio_jesuitico_wikisource.epub`, from
  `ws-export.wmcloud.org/?format=epub-3&lang=es&page=El_imperio_jesuítico`). Text-layer
  route, footnotes. First score (`scratch/lugones/`): words 59698 vs 58629, notes 0 of
  84 found, 126 split words ("Paran á", "so bre"), 32 lost accents, 3533 words not in
  the reference.
- Skipped (user): book note-style profile.

## Margin references printed in the text (2026-10-20, branch `feature/bracketed-refs`)
- New scan `test_pdfs/Timeo_by_Platón.pdf` (35 MB): same book as `Timeo-Platón.pdf` (9 MB,
  ABBYY 2015, JBIG2 page images, text split "m anera p red om"). The new one has no page
  images: letters drawn by 31 MB of fonts made from the scan (ClearScan-style), clean
  text layer. References printed bold in the text: "[30c]"; OCR reads the old-style
  figures as letters ("[8oe]" 55x, "[I7b]" 12x; `scratch/bracket_refs.py`).
- `margin_refs.bracketed`: "[8oe]" -> margin reference "80e", taken as printed (after the
  sequence labelling, since endnotes cite them out of order). `DocumentProfile.bracketed_refs`
  (on >= 20% of pages) turns margin references on and line-end marks off (they were
  page numbers in the contents: "[93a]".."[94e]"). Timeo: 590 refs, 17b..92c, 0 review
  rows. Test in `tests/test_margin_refs.py`.
- Greek: the dialogue is facing pages, Greek on even pages 166-370 (103 pages). The text
  layer read the Greek as Latin look-alikes ("Aó'YT)aá am Ta"); convert puts each Greek
  page between the Spanish ones, cutting Spanish sentences. Tesseract `grc` on page 200
  (`scratch/ocr_pages.py ... grc force 200,201`) reads clean polytonic Greek, but the
  references as digits ("[30c]" -> "[406]"). Not fixed yet: waiting on the user.

## Bilingual editions: Spanish only, quoted Greek kept (2026-10-20, same branch)
- User chose: drop the Greek facing pages; keep Greek words quoted in the Spanish.
- `bilingual.py`: `facing_pages` (book-language stopword share < 0.15 between pages that
  aren't foreign, one of them >= 0.25, and alternating: a lone page is a table; at least
  10). Timeo: 104 pages (166-372 even); table page 81 kept. `iter_blocks(skip=)`.
- `mark_words`: tokens that look garbled (odd signs, digits or case flips inside; not
  "[I7d]", note numbers, addresses) are re-read per line with Tesseract grc and the book
  language (`mixed_script._tsv`, cached); Greek wins if >= 60% Greek letters, conf >= 60
  and >= the other; else the book language at conf >= 85. Stored in memory
  (`/PdfWorkerWords`), applied in `layout.page_lines`. Timeo: 990 words, 539 Greek words
  in the text ("(ἀλήθεια)", "(ὑποδοχή, πανδεχής, 49a)"); 115 garbled tokens left.
  Lugones (no Greek): 1135 words, all sampled right ("acci6n" -> "acción"); spelling
  rows 1087 -> 840.
- Timeo text now: 323 references (Spanish pages), Spanish runs on across dropped pages.
- Not done: ClearScan line boxes are irregular (heights 12-26 pt, overlapping), so
  paragraphs break mid-sentence ("causa,\n\npor cierto"); 6085 paragraphs. Next issue.

## Paragraphs in the Timeo (2026-10-20, branch `feature/clearscan-paragraphs`)
- Two causes (`scratch/baselines.py`, `scratch/para_rules.py`, `scratch/page_blocks.py`):
  1. ClearScan font Fd1485794 claims ascender 2.37 em, so lines using it got tops 11 pt
     too high. Baselines are regular (13.7-14.3). `Line.baseline` (most common span
     origin); paragraph gaps and `line_spacing` now measured on it. (A box clamp at
     1.2 em above the baseline was tried and dropped: it lost a footnote in an OCR'd
     scan, `test_scanned_book_footnotes_after_ocr`.)
  2. Body size is 9.8 (notes and introduction), the dialogue 11: `_page_margins` found
     no body-size line, gave left = 0, and every line counted as indented, so each
     was a paragraph. Now the page's own size stands in.
- Also "(8oc]" (bracket read as parenthesis) is a reference.
- Dialogue pages 201-350: one paragraph per line before, now 39-97 per 50 pages. Book
  total 5045: the rest are bibliography, endnotes and index entries (one per entry).
- Left: running head "INTRODUCCIÓN" kept as a paragraph; the introduction's footnotes
  aren't found as notes ("Cf. M. Baltes ..." is a paragraph).
- Merged (user, 2026-10-20): #39, then #42 retargeted to main (it carried #40 and #41,
  which had merged into their stacked bases / been closed).

## Font sizes in the Timeo (2026-10-20, branch `feature/font-sizes`)
- Reflowed PDF (`scratch/timeo/timeo.reflowed.pdf`) showed body lines in small print
  mid-paragraph. The file has 1039 fonts (one+ per page; others 7-25). The same 12 pt
  print reports 9.95 in one font, 7.90 in another on the same line
  (`scratch/span_sizes.py`); a third of the lines read as small type.
- Tried and dropped: per-font factors from fonts sharing lines (fonts shared by body
  and notes aren't scaled alike: notes came out body size); letter height from declared
  ascender/descender (depends on each font's glyphs: caps-only heading fonts came out
  7 pt, index lines with Greek 13 pt and became headings).
- Kept: `font_sizes.py`. Lines set with the same leading are one size: each line's
  leading = gap to its nearest baseline above/below in the column; book-wide table
  leading -> median size (per-page medians drifted 9.8-10.8 and broke paragraphs across
  pages); lone lines (headings) keep their own. Only for books with a font per page or
  more and mixed sizes on most mixed-font lines (`misreports`): only the new Timeo of
  the test books. Stored on the doc in memory, applied in `layout.page_lines`.
- Timeo PDF: body text reads as paragraphs across pages; 58 headings (real section
  titles found; leftovers are diagram labels on pp. 81, 427-445 and a few TOC lines).
- Still to do on the Timeo: note references are plain digits plus "•" ("inteligentes74•"),
  not linked to the endnotes; "[24_.e]" missed; title "Platón Time o"; "NOTAS A LA
  TRADUCCIÓN" not a heading.

## Note references in the Timeo (2026-10-20, branch `feature/glued-refs`, on #43)
- The redraw flattens printed superscripts: "inteligentes⁷⁴." is "inteligentes74•" on the
  baseline ("•" = the period), sometimes "diosa 66", some digits flagged superscript,
  one number split over two fonts ("7" "4"). The notes at the back hang their number in
  the margin as a line of its own ("33 " beside "Cf. supra"), with old-style figures
  misread (".¡. o" = 40, "l!IO" = 120).
- `glued_refs.py`: numbers glued to a word (or after "word ", or flagged superscript)
  that count up through the book (runs of 20+, steps up to 15, `endnotes.LOSSY_STEP`)
  are stored per page and written as superscript digits in `page_lines`; "•" after one
  becomes ".". `_with_text` merges adjacent superscript digit spans.
- `endnotes.sequences`: `max_step`/`resume_step`; a run resumes only over a shorter one;
  a second bare "1" replaces a lone "1". `match_chapter_notes(lossy=True)`: wide steps,
  groups of 20+, lying after their run's last reference (so page footnotes, which look
  the same, don't pair), items before it dropped.
- `layout.plain_note_start`: "235 Text", or a number hung beside its first line (same
  baseline within 0.3 size); the plain/lossy pairing is used when it links more refs.
  `footnotes.layout_page` drops the hung number line and strips only the note's own number.
- Timeo: 749 notes (was 13), 577 references linked; the introduction's footnotes are now
  found as page footnotes too. Paragraphs 4040 -> 2845 (notes were paragraphs).
- Left: ~170 notes without a reference (their reference garbled: "Heracles73•" for 78,
  "todos'º5" for 105); notes whose number is garbled beyond ".¡."/o/I are folded into
  the note before.
- Tests: `tests/test_glued_refs.py`; all 292 pass.

## Repo cleanup (2026-10-20, user's request)
- scratch/ emptied (1.4 GB of one-off scripts and old trial outputs, all rebuildable):
  kept `paddle-home` (Paddle cache used by integration tests), `tesseract-cache`, `tmp`,
  `pytest`, and `timeo/` (current reflowed PDF + review file).
- Reusable inspection scripts moved to `tools/` (`find_text.py`, `page_lines.py`,
  `render_clip.py`); listed in CLAUDE.md.
- Loose files in the repo root ("El Timeo (La Atlántida).epub", "Platon - Timeo.pdf",
  "Recursos Electrónicos Acceso Libre.pdf") moved to `test_pdfs/`.
- Left for the user: `.claude/settings.json.bak` (a settings backup, not ours to drop).

## Timeo step by step: test_timeo_1_bad.pdf (2026-10-21, uncommitted on feature/progress-greek)
- 2-page sample (Greek p168 + Spanish p169). Output: `scratch/timeo1/timeo1.reflowed.pdf`.
- Fixed: hanging indents (turn at the margin, other lines indented) made every line a
  paragraph (58 -> 33). `structure._hanging` detects them per page; `_starts_paragraph`
  then breaks at margin lines. Test: `test_hanging_indents_start_paragraphs_at_the_margin`.
- Fixed: a paragraph split at "los que quedamos": the leading table had 13.5 pt -> 7.7
  (scan jitter puts a few body lines 13.5 apart, and those few were in mis-scaled fonts).
  `font_sizes.leading_table` now takes each leading's median with the leadings a step
  either side. Test: `test_a_leading_of_few_lines_takes_the_size_of_the_leadings_beside_it`.
- Fixed: page margin split across two 3-pt buckets (turns at x 51.6-54.4) gave left=69,
  so the Greek page's last paragraph ran into the first Spanish turn. `_page_margins`
  counts each bucket with its neighbours.
- User: "drop greek paragraphs always, I don't care the amount". `drop_greek` now runs on
  every book, any length: a paragraph >= 0.9 Greek letters, or >= 0.15 with under 0.15
  of the book's stopwords (Greek read partly as Latin), or one with no Greek and no
  stopwords between two Greek ones. A bibliography entry with a Greek title goes too.
  Sample: the whole Greek page goes (25 rows `greek-dropped`).
- User: references with no note get one reading "no footnote content found".
  `footnotes._render_line` marks an unmatched superscript marker `[^pN-M]` (not after a
  word of 1-2 letters: exponents "m²"); `layout_page` adds the note. Excerpts (< 10
  pages): glued refs need a run of 2/page (min 4), from any number
  (`glued_refs._runs_from_anywhere`).
- User: notes 2-10 as printed. `glued_refs._missing`: for each run, the numbers it skips
  are looked for only where they must be (between the two found around them; before the
  first / after the last, to that page's top / foot), only that number, and only in a
  reference's shape (`_number_re`): glued to a word's end with misread digits ("'º" =
  10: ' ’ ‘ ´ ` | for 1, º ° for 0; a quote alone rejected), or apart but before
  punctuation ("tres . . . 2 ,"; "los 4 hombres" rejected). Stored as a 5-item box with
  the number; `apply_refs` writes it a digit a character. Unmatched references are
  labelled `oN-M`; `epub._number` shows the printed number for `c`/`o`/numeric labels,
  1-N only for page footnotes (`p`, often 1 again each page). Sample: notes 2-10.
- test_timeo_2_bad.pdf (13 pages: Greek/Spanish 168-177, notes 1-46). Output:
  `scratch/timeo2/timeo2.reflowed.pdf` (+ `.md`). References 2-36 all found; 33 paired
  with their notes (see Result).
  - User: the samples are parts of the book to test on; no excerpt-only path. One rule
    for any document: glued-ref runs and the lossy note pairing start at any number
    (`endnotes.runs_from_anywhere`; OCR loses note 1 as any other), and are trusted
    from `endnotes.lossy_min_run(pages)` = 2 a page, 4 to 20 (a whole book: 20 as
    before; "Page 1 .. Page 4" on 4 pages aren't refs). Lossy pairing: a run also fits
    a group that holds its numbers (last refs or notes may be lost).
  - User: don't rebuild the whole book as a check for now. Not done since this change.
  - User's clue: notes 17, 18, 19 found -> a reference 18 the text lacks is there:
    between the references found around it, one sign group glued to a word ("'3") is
    taken (`glued_refs._missing(noted=...)`, `_note_numbers`, `_misread_re`). Exact
    shapes are placed first, so misread ones search only between found neighbours.
  - Mirror: notes whose hung number is misread ("n" 11, "1+" 14) fill a group's gap
    when as many hung marks lie between its neighbours (`layout.hung_mark`,
    `endnotes._fill_gaps`).
  - Notes of the notes section no reference points to are left out
    (`convert._referenced_notes`; still listed as note-no-ref in the review file).
  - `bilingual._MIN_FACING` 10 -> 4: the excerpt's 5 Greek pages dropped.
  - `structure._running_heads`: a line is on the page number's row by baseline (the
    misreported fonts' tall boxes made the first text lines of pp. 173, 177 "heads").
  - A misread number starting the note's line ("3.¡. Así pues" for 34) is a mark too
    (`layout.NOTE_MARK_RE`); `footnotes.layout_page` strips it from the note.
  - Result: references 2-36 found, all 35 paired with their note. Left (user: not now):
    note lines out of order on the notes pages (MuPDF order:
    note 13 before 11, a note's lines swapped); note 1 has no number (shown as text).
- Samples compared (`scratch/compare_samples.py`): timeo1's 278 words and 12 paragraphs
  are timeo2's first ones; references 2-10 the same; only the notes' text differs
  (placeholder vs the real note).
- dilexit_nos.pdf (born digital, Chrome print of vatican.va, 69 pages): 227 references
  and 227 notes, all linked. Fixed: a [n] note whose first line ends short ("...2016):")
  lost its next line to the text (17 lines): `structure._add_line` keeps lines of the
  note's size in it. Left: the site header (top of p1, last in MuPDF order) comes out
  mid-text as a heading "La SANTA SEDE" + "FRANCISCO ENCÍCLICAS ESPAÑOL", and the footer
  (Copyright, FAQ, NOTAS LEGALES ...) at the end; "I." apart from its heading; italics
  (Rm, Jn) lost; "persona. [^3]" keeps a space.
- Italics in dilexit_nos: Chrome (Skia) wrote the text in 23 unnamed Type3 fonts, no
  italic flag; italic only in the glyph shapes. Idea parked (user: "not for now"): a
  `convert` route from HTML/URL (stdlib html.parser + urllib), main-text and note
  detection, starting with vatican.va.
- Misread bracketed Stephanus refs recovered before estimating
  (`margin_estimates.recover_margin_refs`, run in `convert` for `bracketed_refs` books):
  between two found labels with some missing (18d .. 19c), a bracket-like token
  ("b8e]", "[Iga]", "[˒oa]") whose sign-for-sign reading (OCR_DIGITS) is one sign off a
  missing label, same letter, takes it, in order. timeo2: 18e, 19a, 19b, 20a recovered;
  17e has no trace in the text (still missing). Test:
  `test_bracketed_references_misread_between_two_found_ones_are_recovered`.
- Space before punctuation ("Claro que sí , como") is in the OCR text layer itself.
  `tidy` now drops it before `, . ; : ) ? !` (French keeps it before `; : ? !`; a
  spaced ellipsis ". . ." stays). `tidy(blocks, language)`; test
  `test_a_space_before_punctuation_goes`. timeo2: none left.
- "propósito36• CRITIAS.-Es" ran on: on a page of long speeches (2 turns in 33 lines)
  the margin is the indent (x 63) and the page isn't hanging, so the turn at x 48 stuck
  out unnoticed. `_starts_paragraph` now breaks at an outdented line when: out by
  0.8-4 ems, the margin seen on >= 5 lines (`_Margins.support`), body size, starts
  with a capital/digit/quote/dash, and the line before ends a sentence or the line is
  a turn (`_TURN_RE`, "CRITIAS.-"). "•" counts as a full stop. Book-wide recurrence
  of the outdent position (user's option 4) left out until a full-book check shows
  stray breaks. timeo2: 37 -> 38 paragraphs, only CRITIAS. Test
  `test_a_line_left_of_the_margin_starts_a_turn`.
- One font, one size (user, 2026-10-21): the reflowed PDF is all Charis SIL. Notes
  11pt like the body (were 9pt); headings, cover in the body font (were sans), bigger
  and bold; margin labels (bold 7.5, green/pink) and page numbers (9) in Charis via
  `insert_htmlbox` (`_write_line`; pymupdf can't name Charis for `insert_text`). "↩"
  (not in Charis, fell back to Noto Sans Math) is "↑" in the PDF. EPUB/HTML: small
  print and glosses at body size. Speaker names read from small caps ("SócRATES")
  left as read (user). "SócRATES" was never a size change, only OCR casing.

### test_timeo_3_bad.pdf (38 pages, 2026-10-21)
- Notes 2-24 lost: a stray superscript "111" read on the 2nd notes page joined the
  reference run (101 -> 111), and notes before the run's last item were dropped.
  `endnotes._refs_end`: the run ends where the most of its numbers have their note
  after it. Test `test_a_stray_superscript_among_the_notes_does_not_end_the_references_there`.
- Glued refs misread further (`glued_refs`, a 3rd pass in a gap): signs read as
  digits only where one fits a missing number alone, with a real digit in it: "s" 5
  ("descritos6" -> descrito⁵⁶), "+" 4 ("9+"), 3/8 confused ("³0" -> 80, "3'" -> 81);
  "-" may follow a reference ("vejez38-", "usémoslo1º2-"). 44 ("libré4") and 57
  ("fulminados?") stay lost. Test `test_references_misread_further_are_found_where_only_they_fit`.
- Bracketed labels: `[22h]` (one sign off, letter too), `[2 5c]`/`[24_.e]` (spaces,
  stray marks dropped), `[23el` (closing bracket read "l", "1" after OCR_DIGITS).
  Left: 17e (not printed), 21a ("bua]"); 27d/28a/28b after the last found label.
- Note lines each a paragraph: notes read 5.8 pt but 9.3 apart, while the gap test
  scaled the body's spacing (12.1 at 10.1 pt) to 7. `DocumentProfile.size_spacing`:
  each frequent size's own median gap. timeo3 63 -> 52 paragraphs; timeo2 38 and
  dilexit 227 notes unchanged.
- Timeo_by_Platón_no_intro.pdf (261 pages, built by the user, 30 s for md). Against
  the old full-book build on printed pages 169-424: margin-missing 33 -> 17,
  note-no-ref 168 -> 59, ref-no-note 1 -> 2 (62, 506: not checked). Orphan references
  ("no footnote content found") were silently dropped numbers before (459 is simply
  missing from the old PDF). Two fixes, references matched 691 -> 744, orphans 81 -> 45:
  - Notes' numbers misread on the notes pages (".i,57", "H7", "4-54-", "lllll" for
    457, 447, 454, 122): at the page's number column (`layout._at_numbers`: the left
    edge, the median line a column further in) a first token of up to 6 signs with a
    digit is a mark (`LOOSE_NOTE_MARK_RE`; hung alone, up to 6 signs). Marks carry
    their reading; `endnotes._fill_gaps` fills by count, then by last digits (only
    when one missing number fits), then by count again. footnotes strips the mark.
  - References read past any reading ("mundo\"9•", "posible111º", "entonces1111",
    "concierto1112" for 119-122): `glued_refs._missing` counts glued signs (a digit
    among them) in a gap of at most 6 missing numbers; as many as missing: those, in
    order. A straight `"` may now precede a glued reference.
  - Tests: `test_misread_note_numbers_fill_by_their_last_digits_then_by_count`,
    `test_references_read_past_reading_are_counted_into_their_gap`,
    `test_a_note_number_misread_with_letters_is_a_mark_only_at_the_numbers`.
    timeo2 35/35, timeo3 99 (44, 57 lost), dilexit 227 notes: unchanged.
- "Note 331" (review row `note-no-ref 331 o168-1`): the running head "331" had its
  last digit flagged superscript, so a reference "1" got a stand-in note; the page
  number was dropped, the stand-in stayed. `_referenced_notes` now drops unreferenced
  `o…` notes too; review: an `o…` reference is `ref-no-note` (orphans were not counted
  before), an `o…` note never `note-no-ref`. no-intro: notes 789 -> 786; review now
  ref-no-note 46, note-no-ref 56 open (13 stale). Single-digit orphans left in the
  text (o38-1, o74-6, o204-8...) are likely stray superscripts, not references.
- Calibre comparison (user asked; /Applications/calibre.app/.../ebook-convert,
  defaults; scratch/calibre/, `compare_epubs.py`). no-intro Timeo, ours vs Calibre:
  paragraphs 1236 vs 7476 (one per printed line), words 60k vs 97k (Calibre keeps the
  104 Greek pages as OCR garbage: "Kal" 772, "µ" 3951; ours 0), note links 2365 vs 0,
  heads/page numbers left 17 vs 71, paragraphs cut mid-sentence 108 vs 4565. Calibre
  20 s, ours 30 s. Calibre keeps raw OCR ("posible111º", "[3ob", "abso lutamente").
- EPUB Stephanus labels easier to find on Kindle (user chose: brackets, full size,
  sans-serif): `[30b]` as text in the span (Kindle may drop styling), a space after it
  (padding is ignored), CSS sans-serif bold 0.95em, green kept. The PDF strips the
  brackets for its margin labels. Not yet checked on a Kindle.
- Remaining: note lines out of order on notes pages (MuPDF order, user: later);
  note 1 unnumbered so its text runs on after the last paragraph with "por Luc
  Brisson •" (running head of the notes pages); "TIMED" running head; speaker
  garbles "CRIT . .:.\_Escucha", "CRIT . ....:Considera".
- Seen, not fixed yet: running head "TIMED" kept; "[17a]" read "b7a]" (lost);
  note refs stay digits ("cuarto3": the notes are not in the sample); speaker names
  misread ("SOc.", "TrM."); "-" not turned into "—".
