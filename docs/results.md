# Drop-in experiment: results

Started 2026-11-15. Plan: `PROGRESS.md`, "Plan: drop-in-experiment". Shared facts and the
user's priorities: `docs/experiments/drop-in/README.md`. Nothing in `src/` was changed.

## Baseline

Today's pipeline, no paid model calls, run 2026-11-14/15.

| Run label | What was run | Seconds | Output |
|---|---|---|---|
| q-base | `tools/quality.py build`: the ten quality books against their references, marks followed where a book has them (philosophy, copleston, ratzinger, platon_bad) | 1,275 | `scratch/drop-in/q-base` |
| q-nomarks | the same with `--no-marks` | 1,253 | `scratch/drop-in/q-nomarks` |
| audit-base | `docs/experiments/drop-in/audit.py run` + `score`: 14 books dropped into an inbox (no AI, no marks, epub and pdf asked) | 15,640 | `scratch/drop-in/audit-base` |
| read (S9) | 120 pages read by a model against the page picture, 5 per book, both folders | - | `scratch/drop-in/audit-base/read.tsv`, `scratch/drop-in/results/S9.md` |

Counts made for the ranking: `docs/experiments/drop-in/rank_checks.py` (`headings`, `loops`,
`refs`).

### Quality set (reference editions)

Percentages: higher is better. Rates: per 10,000 reference words, lower is better.

| Book | Ref. words | matched | missing | extra | headings found | headings real | levels | breaks real | notes in body | leftovers |
|---|---|---|---|---|---|---|---|---|---|---|
| philosophy (marks) | 197,605 | 98.2% | 178.1 | 128.1 | 83.2% | 81.8% | 74.6% | 98.7% | 0.7 | 0.3 |
| copleston (marks) | 222,588 | 98.9% | 110.5 | 37.6 | 80.6% | 90.8% | 100.0% | 75.9% | 0.2 | 1.5 |
| ratzinger (marks) | 91,628 | 100.0% | 1.6 | 0.1 | 78.7% | 73.4% | 78.8% | 97.4% | 0.0 | 0.0 |
| lugones | 58,563 | 97.5% | 249.8 | 358.9 | - | - | - | 94.5% | 15.5 | 1.2 |
| platon_bad (marks) | 84,940 | 94.6% | 544.1 | 187.4 | 88.9% | 31.0% | 75.0% | 98.9% | 0.0 | 0.4 |
| dialogos | 86,104 | 97.8% | 217.8 | 93.8 | 100.0% | 43.3% | 53.8% | 98.9% | 156.7 | 2.1 |
| niebla | 57,225 | 95.0% | 504.7 | 552.7 | - | - | - | 77.2% | - | 2.3 |
| **working, q-base** | 798,653 | 97.9% | 210.9 | 138.1 | 82.0% | 76.4% | 84.0% | 88.9% | 19.7 | 1.0 |
| **working, q-nomarks** | 798,653 | 97.9% | 211.4 | 134.4 | 78.5% | 77.2% | 93.9% | 89.0% | 19.7 | 1.0 |
| pepita (held out) | 56,657 | 93.4% | 662.2 | 793.7 | - | - | - | 26.9% | - | 0.5 |
| marianela (held out) | 50,976 | 94.4% | 557.5 | 709.7 | - | - | - | 33.7% | - | 9.8 |
| gaviota (held out) | 42,994 | 85.6% | 1436.7 | 1320.0 | - | - | - | 70.7% | - | 0.7 |
| **held out** (same in both runs) | 150,627 | 91.5% | 847.9 | 915.5 | - | - | - | 38.2% | - | 3.7 |

Without marks, the four marked books: philosophy headings 78.8% found / 84.7% real / levels
87.5%, extra 106.9; copleston 79.5% / 85.3% / 100.0%; ratzinger 74.0% / 75.2% / 100.0%,
missing 2.4; platon_bad 77.8% / 25.9% / 52.4%, missing 548.9, extra 201.1. Words and notes in
the body are the same with and without marks; marks move headings only.
Headings test pages (both runs): working 189 real headings, 86.2% found, 90.9% real, levels
62.4%; held out 65, 80.0%, 77.3%, 52.1%.

### Headings: main and sub apart (user, 2026-11-15)

Main = what a contents table lists (parts, chapters, front and back matter); rule in
`rank_checks.py` (rough: by the title's first word and capitals). From `quality.json`.

| Run | Book | Reference headings | missed: main / sub | wrong: main / sub |
|---|---|---|---|---|
| q-base | philosophy | 155 | 3 / 23 | 13 / 17 |
| q-base | copleston | 134 | 7 / 19 | 6 / 5 |
| q-base | ratzinger | 89 | 7 / 12 | 1 / 24 |
| q-base | platon_bad | 9 | 1 / 0 | 4 / 16 |
| q-base | dialogos | 13 | 0 / 0 | 2 / 15 |
| q-base | **total** | 400 | 18 / 54 | 26 / 77 |
| q-nomarks | philosophy | 156 | 9 / 24 | 7 / 17 |
| q-nomarks | copleston | 132 | 8 / 19 | 18 / 8 |
| q-nomarks | ratzinger | 104 | 5 / 22 | 0 / 25 |
| q-nomarks | platon_bad | 9 | 2 / 0 | 5 / 15 |
| q-nomarks | dialogos | 13 | 0 / 0 | 2 / 15 |
| q-nomarks | **total** | 414 | 24 / 65 | 32 / 80 |

### Inbox audit (14 books, no reference)

| Book | Kind | State | Grade | Open rows | Seconds | Kept | Garble /10k | Note words in body | Body words in notes | Margin refs (gaps, back) | Contents links ok | Headings at one level |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Antropología Filosófica | scan, spreads | draft | C | 572 | 574 | 97% | 78 | 1,339 | 1,165 | 9 (5, 3) | 138/138 | h5 125 of 138 |
| De Anima | scan, spreads | failed (no PDF) | - | - | 2,844 | 97% | 173 | 6,255 | 99 | 174 (79, 65) | 106/106 | h5 100 of 106 |
| Filosofia del Hombre | scan, spreads | draft | C | 385 | 4,562 | 95% | 161 | 508 | 165 | 33 (7, 0) | 178/178 | h5 175 of 178 |
| Metafisica Alvira | scan | draft | B | 147 | 619 | 97% | 172 | 11,499 | 22 | 10 (4, 4) | 244/244 | h5 227 of 244 |
| Epistemología Verneaux | scan | draft | C | 826 | 701 | 98% | 227 | 857 | 0 | 0 | 101/101 | h4 90 of 101 |
| La Biblia en su entorno | born digital | draft | B | 523 | 845 | 100% | 106 | 1,664 | 2,169 | 0 | 463/463 | h4 402 of 463 |
| Historia de Filosofía Antigua T1 | scan | draft | B | 664 | 1,990 | 97% | 87 | 48,639 | 953 | 7 (1, 5) | 608/608 | h5 603 of 608 |
| Historia De La Filosofía T V | scan | draft | B | 554 | 2,019 | 98% | 113 | 12,051 | 12 | 0 | 790/790 | h5 783 of 790 |
| Timeo (no intro) | born digital | draft | D | 152 | 82 | 63% | 175 | 450 | 2,174 | 354 (17, 0) | 5/5 | - |
| platon_dialogos_vi_bad | scan | draft | B | 343 | 1,389 | 98% | 139 | 7,554 | 198 | 29 (12, 13) | 45/45 | h5 24 of 45 |
| Ratzinger (epub) | epub | finished | - | 0 | 3 | 100% | 37 | 0 | 0 | 0 | 121/121 | h3 108 of 121 |
| Copleston 4 (epub) | epub | finished | - | 0 | 10 | 100% | 26 | 0 | 0 | 0 | 155/155 | h3 126 of 155 |
| Prometeo (epub) | epub | finished | - | 0 | 1 | 99% | 27 | 0 | 0 | 0 | 7/7 | - |
| The Four Loves (epub) | epub | finished | - | 0 | 1 | 100% | 12 | 0 | 0 | 0 | 9/9 | - |

All columns (words in and out, unknown words, splits, notes lost, the source's outline, review
rows per kind): `scratch/drop-in/audit-base/audit.md`. Review rows over the ten PDFs: 4,890,
of them 4,223 spelling (86%).

### Reading (S9): marks summed over 5 pages a book

0 fine, 1 small, 2 a reader would be stopped; highest possible 10 per column.

| Set | Book | Body | Note mix | Margin | Headings | Notes lost (n) |
|---|---|---|---|---|---|---|
| audit-base | Filosofia del Hombre | 9 | 2 | 4 | 4 | 0 |
| audit-base | Antropología Filosófica | 8 | 2 | 0 | 4 | 3 (12) |
| audit-base | De Anima | 7 | 5 | 4 | 5 | 0 |
| audit-base | Timeo (no intro) | 7 | 1 | 4 | 1 | 2 (12) |
| audit-base | Epistemología Verneaux | 7 | 0 | 0 | 0 | 0 |
| audit-base | Historia de Filosofía Antigua T1 | 6 | 1 | 0 | 0 | 0 |
| audit-base | Historia De La Filosofía T V | 6 | 0 | 0 | 3 | 0 |
| audit-base | Metafisica Alvira | 5 | 0 | 0 | 1 | 0 |
| audit-base | platon_dialogos_vi_bad | 5 | 2 | 2 | 1 | 1 (1) |
| audit-base | La Biblia en su entorno | 2 | 2 | 0 | 0 | 0 |
| audit-base | Ratzinger (epub) | 0 | 0 | 0 | 2 | 0 |
| audit-base | Copleston 4 (epub) | 0 | 0 | 0 | 4 | 0 |
| audit-base | Prometeo (epub) | 0 | 0 | 0 | 0 | 0 |
| audit-base | The Four Loves (epub) | 0 | 0 | 0 | 0 | 0 |
| q-base | pepita | 9 | 0 | 0 | 0 | 0 |
| q-base | marianela | 7 | 2 | 0 | 1 | 0 |
| q-base | platon_bad (marks) | 6 | 0 | 1 | 0 | 0 |
| q-base | niebla | 6 | 1 | 0 | 0 | 0 |
| q-base | gaviota | 6 | 0 | 0 | 0 | 1 (1) |
| q-base | lugones | 5 | 0 | 0 | 3 | 0 |
| q-base | philosophy (marks) | 3 | 0 | 0 | 0 | 0 |
| q-base | copleston (marks) | 3 | 0 | 0 | 0 | 0 |
| q-base | ratzinger (marks) | 1 | 0 | 0 | 1 | 0 |
| q-base | dialogos | 0 | 1 | 2 | 0 | 2 (4) |

Pages a reader would be stopped on (body 2): 18 of the 50 PDF pages of audit-base, 0 of its
20 EPUB pages, 13 of the 48 judged pages of q-base. Five pages a book show kinds of error,
not rates.

### Where the reading overrules the counts

| Count | What it says | What the reading found | Weakness recorded |
|---|---|---|---|
| `kept`, `garble_10k` | Antropología 97% kept, garble 78: the best scan | 3 of its 5 pages stop the reader | a page woven line by line keeps every word: neither count sees order |
| grade | Antropología, Filosofia del Hombre and Epistemología all C; La Biblia B with 523 rows | Epistemología reads better than the other two; La Biblia is nearly clean (body 2 of 10) | the grade counts review rows, mostly spelling; it follows neither order nor notes |
| `note_in_body` | Alvira 11,499, Historia Antigua T1 48,639, Tomo V 12,051 words | no footnotes on their 15 pages; small-type paragraphs, boxes and captions, rightly in the body | the small-line rule calls small print a note; trust it only on De Anima (6,255), Antropología (1,339), platon (7,554) |
| `margin_refs` | De Anima 174, Filosofia del Hombre 33, Antropología 9, Alvira 10, Historia Antigua 7 | every one on the pages read is invented; the real Bekker numbers are plain words and not counted | counts what came out, not what is printed |
| `notes_lost` (EPUB) | Copleston 4 508, Prometeo 61, Ratzinger 10 | every call read has its note | the source's "[161]" calls are not matched |
| `garble_10k` (EPUB) | 12-37 per 10,000 | text identical to the source | names, verse numbers and italics count: a floor of about 12-37 that is not garble |
| `kept` (Timeo) | 63%, grade D | the Spanish pages are word for word; the 104 Greek facing pages are left out on purpose | pages left out by design count as lost |
| headings found / real | copleston misses 7 main headings; platon_bad 31.0% real, dialogos 43.3% | 5 of copleston's 7 are the reference's other wording ("PARTE I PLATÓN" for our "TERCERA PARTE Platón"); the "wrong" ones of platon_bad and dialogos are subheadings | one figure for main headings and subheadings; a title worded otherwise in the reference counts twice |
| `outline_found` | Copleston 4 97%, Historia Antigua T1 1% of 621 | Copleston 4's chapter names are body lines on 4 of 5 pages | a name turned into body text still matches; the 1% was not checked |
| contents links | 2,970 of 2,970 resolve | - | links never fail; says nothing on whether the entry is a chapter |

### Ranking of what fails

Order: the README's priorities (as the plan lists them: human step, text lost, garble, foreign
terms, notes and body mixed, margin references, headings, then lost notes and bibliography),
then books and words touched. Where reading and count disagree, the reading is used.

| # | Failure | Books and words | Numbers |
|---|---|---|---|
| 1 | A human step is asked for every PDF | 10 of 10 PDFs, 1,258,406 source words; both born-digital PDFs | 0 PDFs finished (9 drafts, De Anima failed with no PDF: "Typst failed: the document does not contain a bibliography"); 147-826 open rows a book, 4,166 in all; 86% of review rows are spelling. The 4 EPUBs finish untouched in 1-10 s |
| 2 | Scans of two-page spreads: the two pages woven line by line; words at the sheet's edges lost; margin references invented | 3 books (Antropología, De Anima, Filosofia del Hombre), 253,928 words | 4 of 15 pages read cannot be read at all, 3 more lose the first or last word of lines; body 9, 8 and 7 of 10; 174, 33 and 9 margin references came out, invented on every page read; the counts see nothing (kept 95-97%) |
| 3 | The model's reading puts a made-up loop in place of printed text, with no review row | the 2 books built from PaddleOCR-VL's reading (philosophy, platon_bad), 282,545 reference words | 2 loops, one in each, 0 in the other 8 books; platon_bad p249 loses 18 printed lines; platon_bad has the most missing words of the working books (544 per 10,000) |
| 4 | Old novels: sentences cut into a paragraph per printed line, running text put into tables | pepita, marianela, gaviota (150,627 reference words); niebla partly | paragraph breaks real 26.9%, 33.7%, 70.7% (working books 88.9%); 340 extra breaks, 848 missing and 916 extra words per 10,000; tables on 6 of 15 pages read, 8 of 15 marked 2 |
| 5 | Pictures and diagrams read as text | Historia Antigua T1, Tomo V, lugones (496,398 words) | 3 of 15 pages: a 25-line junk paragraph, a diagram in spaced letters, a made-up h1 "L RO 1" |
| 6 | Garbled words on poor pages (skewed, curved, underlined, badly printed) and slips on every scan | all 8 scans of the audit, niebla, lugones | garble 78-227 per 10,000 on scans (EPUB floor 12-37); 7 pages unreadable in 4 books; working books miss 211 words per 10,000 |
| 7 | Foreign terms: flagged though right in born-digital text; wrong in scans | La Biblia (flags); platon, De Anima, Historia Antigua T1, copleston (words) | La Biblia: 449 open spelling rows on a text read word for word; scans: every Greek word of platon p16, "logos" → "lagos", "in habitu" → "in nabitu" three times; copleston keeps Greek but drops its spaces. Letter for letter on every born-digital and EPUB page read |
| 8 | Note text in the body, body text in a note, calls that are not notes | in the body: De Anima, Antropología, platon by the inbox, dialogos, Timeo, lugones; in a note: Filosofia del Hombre, marianela; false calls: La Biblia, Historia Antigua T1, niebla | De Anima 6,255 words (3 of 5 pages), platon 7,554, Antropología 1,339, dialogos 156.7 per 10,000 (its endnotes one run-on body paragraph); La Biblia 58 false calls (edition numbers "⁴1993"). 0 on the 40 pages read from marked books and EPUBs; the four marked books score 0.0-0.7 with and without marks |
| 9 | Margin references lost or invented | lost: platon by the inbox, dialogos; invented: De Anima, Filosofia del Hombre (also in 2) | platon: 29 by the inbox against 701 on the quality route with marks and 688 without (p249: 4 of 4 gone); dialogos 0 in the book (p119: 6 of 6 gone); De Anima 174 invented from line numbers, its Bekker numbers left as plain words, line numbers inside words ("sobreis vivir"). Right: platon_bad 11 of 11, Timeo 6 of 6 |
| 10 | Main headings (parts, chapters) lost, turned into body text or split | philosophy, copleston (no marks), ratzinger, platon_bad, De Anima, Tomo V, lugones, Copleston 4 and Ratzinger EPUBs; flat levels on six scans | quality set: 18 main missed and 26 main wrong of 400 with marks, 24 and 32 of 414 without. Lost: De Anima "II. OBRAS", "CAPÍTULO SEGUNDO" (2 of 5 pages), philosophy's titles of parts III and IV, 4 part titles of ratzinger. In the body: Copleston 4's chapter names on 4 of 5 pages (27 chapters: contents show "CAPÍTULO XIII" without "SPINOZA.— IV"). Split: philosophy's chapters even with marks (number and name are two headings; 10 of the names count as wrong), copleston's without marks (18), Tomo V p28 (one title, four headings), lugones's title page. On six scans 2,013 of 2,064 headings are h5: the contents cannot tell a chapter from a subsection |
| 11 | Extra or wrong subheadings, heading levels (weighed lightly) | every book with headings | quality set: 54 sub missed and 77 sub wrong with marks, 65 and 80 without; the low "headings real" of platon_bad (31.0%) and dialogos (43.3%) is all of this kind (speaker lists, subheads of the introductions: 16 and 15); ratzinger 24 of 25 ("a).- ..."). Credit lines, a running head and an ad line made headings (4 pages); levels agree on 62.4% and 52.1% of test-page pairs |
| 12 | Notes lost (counted only) | Antropología, Timeo, dialogos, platon | Antropología 12 notes on 2 pages, Timeo 12 on 2, dialogos p6 three calls tied to other notes. The audit's `notes_lost` is not to be trusted (see above) |
| 13 | Bibliographies of scans garbled | De Anima p43, Alvira p225 | names in spaced letters, titles split; born-digital and EPUB bibliographies are right |

Contents links are not a failure: all 2,970 resolve.

What the baseline shows for headings, the two kinds apart. Main headings are mostly there but
often not whole: the usual error is a split (chapter number and chapter name as two headings)
or the name left in the body; an outright loss is rare (De Anima, two parts of philosophy,
ratzinger's part titles). Marks mend splits (copleston: 18 wrong main headings without, 6
with, 5 of them the reference's wording) but not philosophy's. Subheadings are where most of
the "missed" and "wrong" counts come from (131 of 175 with marks) and they are the light kind.

### Causes of the three worst

`tools/page_parts.py` on pages S9 read; no new pages.

1. **Human step.** Not a page matter: `src/pdf_worker/inbox.py:197-200` finishes a book only
   when its review file has no open row (the report's grade A allows 0.5 rows per 1,000
   words; no PDF is under 1.8). La Biblia's rows on the pages read: none on p47, p133, p262 (word for
   word); six on p402 and p414, all `ref-no-note` from edition numbers. So a clean
   born-digital book is held back by false alarms (449 spelling rows on names and foreign
   words, 58 false note calls). On scans the rows are real, but they are word rows: deciding
   them mends none of failures 2, 3 or 8.
2. **Spreads.** Filosofia del Hombre p91 and p34 (the inbox's work copy): the pipeline sees the
   sheet as one page with two running heads (10.4% and 10.8% down) and two page numbers (182,
   183); every line is whole, labelled `text`, in order within its printed page. The weave is
   made afterwards: body lines are ordered by height across the whole sheet (left 14.1%, right
   14.5%, left 16.2%, right 16.6%: the order of the output). No step that splits a sheet into
   its two pages was found. The lost words come from the margin-reference step, which the inbox
   turns on "when found": on p91 the last word of a right-page line is taken for a margin mark
   and an invented reference is put at the line's start ("anotar algunas de" → "[120a] Esto
   puede bastar ... anotar algunas"; "de la ra-" → "[120b] ... el plano de la"). On p34 the
   lines are whole in the pipeline's lines ("que la imaginación", "es irreal", "son anteriores")
   and their first word is gone in the output: the same step at the left edge (inferred, not
   traced in the code).
3. **Loop.** platon p249, original and work copy: the PDF's own text layer has the 18 lines
   right ("dentro causa muchas enfermedades inflamatorias ... se coagula tras verterse"). The
   loop is PaddleOCR-VL's: `tools/quality.py` builds platon_bad and philosophy from the model's
   reading, both have a loop (philosophy: "el poder de la confusión el poder de la confusión el
   poder de la decoración..."), with and without marks; the inbox run of the same PDF has the
   page word for word. Nothing compares the model's block with the text layer the PDF already
   has, and no review row is written. The same page shows the inbox route's margin loss: the
   letters sit at the line ends ("están 6", "encerrada c", "movimiento d", "san- e"); the
   output has neither the letters nor a reference.

Not looked for: why De Anima's PDF fails in Typst (an unescaped `@` read as a citation is the
likely cause; unchecked), why Filosofia del Hombre took 4,562 s.

## Comparison

Runs of 2026-11-15. The variants were measured on different books, so read each row against
the baseline rows of its own set. Words and notes in the body: per 10,000 reference words,
lower is better; for sets A and C the per-book rows of S5 and S7 weighted by reference words
(`scratch/drop-in/s8_weights.py`). Main headings: `rank_checks.py`'s rule. Flags: open
spelling rows settled against the reference (right: a wrong word corrected or a right word
un-flagged; wrong: a wrong word un-flagged or changed to another wrong word; harmed: a right
word changed). Full tables: `scratch/drop-in/results/S5.md`, `S6.md`, `S7.md`, `S10.md`.

Sets: **A** the four books with hand marks (philosophy, copleston, ratzinger, platon_bad;
596,761 reference words; margin references are platon_bad's, the only one of the four that
prints them). **B** the open spelling flags of philosophy, copleston, ratzinger,
lugones and niebla in q-base (1,551 flags, 920 aligned with the reference: 439 right words,
481 wrong). **C** the engines' three books (philosophy, copleston, ratzinger; 511,821 words).
**D** the three spread scans through the inbox (Antropología / De Anima / Filosofia del
Hombre; no reference, so the audit's counts and `split_spreads.py order`). Filosofia del
Hombre was cut and run again for its first 60 of 118 sheets only: its joins and garble are
like for like, its counts of note words and margin references are of fewer pages.

| Set | Run | Body words | Notes in the body | Margin references | Main headings missed / wrong | Flags right / wrong / harmed / left | Time | Cost |
|---|---|---|---|---|---|---|---|---|
| A | baseline, hand marks (q-base) | missing 177.9, extra 83.1 | 0.3 | 701 | 18 / 24 | - | 1,275 s, all ten books | the user's marking (not timed) |
| A | baseline, no marks (q-nomarks) | 178.6, 78.1 | 0.3 | 688 | 24 / 30 | - | 1,253 s, all ten books | none |
| A | auto-marks, rules | 193.1, 83.0 | 0.1 | 700 | 22 / 29 | - | marks 2.4 min, build 5.7 min | none |
| A | auto-marks, local model (qwen3.5-9b, LM Studio) | 193.7, 83.2 | 0.1 | 688 | 25 / 31 | - | marks 2.4 + 61 min, build 5.4 min | 80 pages asked, on this machine |
| A | auto-marks, cloud model (nemotron-3.5-super-vl, free) | 196.4, 84.3 | 0.4 | 705 | 23 / 28 | - | marks 2.4 + 17 min, build 5.0 min | 80 free requests (120 sent with re-runs) |
| B | today: every flag waits for the user | - | - | - | - | 0 / 0 / 0 / 920 | 0 s | the user's review |
| B | today's own `auto:` rows (274 aligned, apart from the 920) | - | - | - | - | 247 / 20 / 7 / 0 | 0 s | none |
| B | lists (Latin, German, French, English, Greek transliteration) | - | - | - | - | 14 / 21 / 0 / 885 | 15 s | none |
| B | sentences, nemotron-3.5-super-vl: philosophy + ratzinger (145 aligned) | - | - | - | - | 125 / 17 / 2 / 1 | 65 s | 2 free requests |
| B | sentences, same model: copleston (165 aligned) | - | - | - | - | 0 / 0 / 0 / 165: the answer came after 77 s, over the 60 s limit, so today's text was kept | 77 s | 1 free request |
| B | sentences: lugones, niebla | - | - | - | - | not run: 551 and 639 open flags, over the brief's limit of 300 | - | - |
| B | sentences, a second model | - | - | - | - | not run: inkling-2-small refused (403, region), nemotron-3-ultra down, gemma-4-31b rate-limited (429, three tries) | - | - |
| C | baseline, hand marks (q-base) | 117.1, 65.8 | 0.4 | - | 17 / 20 | - | in q-base's 1,275 s | - |
| C | baseline, no marks (q-nomarks) | 117.2, 57.6 | 0.4 | - | 22 / 25 | - | in q-nomarks's 1,253 s | none |
| C | Docling 2.150.1 (defaults) | 381.0, 383.1 | 354.8 | - | not counted; headings real 73.8-84.6% (q-base 73.4-90.8%) | - | 23.2 min | 1.9 GB venv shared with MinerU, 506 MB weights |
| C | MinerU 4.2.2 (tier basic) | 105.4, 1,020.4 | 365.0 | - | not counted; headings real 73.5-83.1% | - | 26.3 min | the same venv, 862 MB weights |
| D | baseline (audit-base) | joins found 91.5 / 93.1 / 70.4%; woven sheets 14 of 299; garble 78 / 173 / 161 | 1,339 / 6,255 / 508 words | 9 / 174 / 33, invented on every page read | De Anima: 6 of 8 outline titles | - | 574 / 2,844 / 4,562 s | none |
| D | spreads cut before the inbox | joins 92.7 / 95.0 / 96.4%; woven pages 1 of 562; garble 57 / 147 / 120 | 216 / 8,271 / 589 words | 2 / 134 / 1 | De Anima: 3 of 8 | - | 789 / 3,009 s (+37%, +6%); Filosofia 1,068 s for 60 of 118 sheets | none |

The human step: no variant changed a PDF's state. Only D went through the inbox, and its
books stayed draft, failed (Typst, as before) and draft; rows left to review fell from 403 to
231 on Antropología.

### Cost and time

No money was spent: local models and OpenRouter free models only.

| Variant | Jobs | Requests | Disk |
|---|---|---|---|
| Baseline | q-base 21 min, q-nomarks 21 min, the inbox audit of 14 books 261 min | 0 | - |
| Auto-marks | rules 8 min, local 69 min, cloud 24 min (marks + build of four books); 78 min more of superseded builds | cloud 120 sent, 80 in the final marks, 2 cut short; local 80 pages, 0 failed | - |
| Sentence checks | lists 15 s; sentences 65 s + 77 s late | 3 that answered; three other models gave nothing | - |
| Engines | Docling 23 min, MinerU 26 min for three books | 0 | 3.3 GB in `scratch/drop-in` |
| Spread cut | 88 min in all: detect 61 s for 20 PDFs, the three books 81 min | 0 | split PDFs 6-9% larger |

## Conclusion

Weighed by the README's priorities: body text first, then margin references, then main
headings, then notes. Nothing was adopted here; each line below names the plan to run.

### What to adopt, in this order

1. **Cut two-page spread scans into single pages before OCR.**
   `/plan-feature adopt cutting two-page spread scans into single pages before OCR`
   The only variant that turns unreadable body text into readable text, and it helps margin
   references too (priorities 1 and 2). Woven sheets 14 → 1; joins on Filosofia del Hombre
   70.4% → 96.4%; garble down on all three books (78 → 57, 173 → 147, 161 → 120); the six
   sheets a reader was stopped on all read now (body marks 12 → 6); invented margin
   references 9 → 2 on Antropología and 33 → 1 on Filosofia del Hombre (the 1 from its first
   60 sheets only).
   Cost: 6-37% more time, no model. No sheet of the 17 other books is cut. The plan must
   settle: the test (wider than high first; the rule as first briefed gave 40 false alarms on
   two-column pages), De Anima's main headings (6 of 8 outline titles found before, 3 after;
   not looked into), and page numbers that count half sheets.
2. **Finish born-digital PDFs without the word review.**
   `/plan-feature adopt finishing born-digital PDFs without the spelling review`
   The top failure (a human step for every PDF) has a no-model answer where the text is the
   PDF's own. On copleston and ratzinger 227 of 236 aligned flags are right words (96%); La
   Biblia has 449 open spelling rows on a text read word for word; the EPUBs already finish
   in 1-10 s. No text is changed, so priority 1 is not at risk. Read from the baseline and
   S6's truth, not run as a variant: the plan must measure it on La Biblia and Timeo, and
   decide the note rows that would still hold them (La Biblia 59, beside its 58 false calls
   from edition numbers; Timeo 102).
3. **Sentence checks by a free model for the flagged words of scans**, off by default until
   re-measured. `/plan-feature adopt sentence checks for flagged words of scans`
   125 right, 17 wrong, 2 harmed, 1 left of 145 flags, in 2 requests and 65 s. It harms a
   right word no more often than the pipeline's own `auto:` rows do (2 of 145 against 7 of
   274). Third because it is thinly measured: one model, one scan (philosophy) and one
   born-digital book; the books with most flags were not run (lugones 551, niebla 639; the
   audit's scans have 147-826 open rows each), and settling word rows mends none of the
   spread, loop or notes failures. The plan must change two things first: a sentence the
   model does not return keeps its flags (nearly all 17 wrong come from un-flagging those),
   and smaller batches (copleston's one request of 164 sentences answered after 77 s and
   everything was kept). A late or failed call keeps today's text, as tested.

### Not to adopt

- **Docling and MinerU.** Both put notes in the body: 354.8 and 365.0 per 10,000 words
  against 0.4, and leave 383 and 1,020 extra words against 66 (running heads, page numbers,
  note text). That is the priority-1 error on every book. MinerU misses fewer words (105.4
  against 117.1; copleston 71.5 against 110.5): the one figure where an engine beats the
  pipeline. Not tried: MinerU's VLM tiers, Docling with a Spanish OCR setting.
- **Marks made without the user, in any mode.** Rules mend 3 of the 54 main-heading errors
  (22 / 29 against 24 / 30; hand marks 18 / 24) and cost body words on scans: missing 208.0
  against 178.1 on philosophy, 580.7 against 548.9 on platon_bad, from the notes dropped when
  unsure (platon_bad without those marks: 544.3). They give nothing back there: notes in the
  body are 0.0-0.7 with no marks at all. The models add 17-61 minutes, miss more words than
  no marks on every book and gain no margin references (688 and 705 against 688); before the
  guards were added the local model put 25.7 notes per 10,000 words into platon_bad's body.
- **More word lists.** They un-flag misreads more often than foreign words: 21 wrong against
  14 right.

The finding under the marks result: with no marks at all the four books equal the
hand-marked ones on missing words (178.6 against 177.9), notes in the body (0.3 both) and
margin references (688 against 701). Marks buy main headings only. Marking is not what
stops a drop-in conversion.

### What stays manual

- **Marks, as an option, for a book whose contents table matters.** Hand marks are the only
  thing here that mends main headings (18 missed / 24 wrong against 24 / 30; copleston's
  split chapters 18 → 6). They are never needed for words, notes or margin references.
- **The look at a scan's doubtful pages.** After 1 and 3 a scan still has note rows
  (Antropología 311 after the cut) and the failures below that no variant touched.
- **Notes, by the user's rule:** a lost note is the lesser error and no variant mended note
  loss; nothing is proposed for it.

### Patches the numbers show could go

No run switched a single patch off: this is read from what the flags turned out to be (S6).
The dictionary and the Wikipedia counts live in ai-client's check; a glossary or an
encyclopaedia check was not found by name in this repo's `src/`, and ai-client was not read.

- **Dictionary and Wikipedia counts as the makers of spelling rows: go on born-digital text,
  stay on scans.** Born-digital: 96% of the flags are right words (above). Scans: 472 of 684
  aligned flags (69%) are wrong words (philosophy 57 of 74, lugones 207 of 332, niebla 208 of
  278), and they are what a sentence check works from.
- **Foreign-word lists: add no more; they are not where the flags are.** Foreign terms are 14
  of 920 flags (1.5%). Whether the lists ai-client already has could go was not measured.
- **Glossary, encyclopaedia and Wikipedia look-ups for rare right words** (names,
  derivations such as "culturizante", transliterations such as "daimón"): no case for them.
  On born-digital text 2 removes the question; the sentence check settled 125 of 145 flags
  right with no list at all (philosophy, a scan: 55 of 74; ratzinger: 70 of 71). The per-book
  glossary left for "measure later" needs no building.
- **Keep the `auto:` rows** (split words, learned corrections): 247 right, 20 wrong, 7
  harmed.
- **Greek: no evidence either way.** No mode edited a Greek-letter word, and the Greek truth
  set covers books outside these five.

### Still open: tested by no variant

In priority order; each needs its own measure before a plan.

- Priority 1: the model's made-up loop in place of printed text (failure 3; one in each of
  the two books built from PaddleOCR-VL's reading; the PDF's own text layer has the lines
  right). A guard that compares the two is the next thing to test:
  `/plan-feature guard the model's reading against the PDF's own text layer` once a count
  beyond `rank_checks.py loops` exists.
- Priority 1: old novels cut into a paragraph per line and put into tables (failure 4);
  pictures read as text (5); De Anima's notes in the body (8,271 words after the cut) and
  its PDF that fails in Typst.
- Priority 2: margin references by the inbox. platon keeps 29 where the quality route keeps
  688 without marks; De Anima still gets 134 invented from its line numbers while its Bekker
  numbers stay plain words; dialogos has none. Marks are not the answer (688 against 701).
  This is the highest priority nothing here answers.
- Priority 3: a chapter's number and name as two headings, and six scans with 2,013 of 2,064
  headings at h5. Only hand marks helped.

# Summarize prompt experiment (2026-11-23)

Question: does `summarize --detail full` (aim 30%) run long because of how the prompt words
"keep every idea", and does a rewritten prompt (B) or a key-ideas-first, two-request process
(C) do better, without forcing a length? Text: "Apuntes de Introducción a la filosofía 1",
section `I. > 1.` (6,400 words), `--detail full --keep-bold --lang es`, model pinned to
`nvidia/nemotron-3.5-super-vl:free`. Script: `docs/experiments/summarize-prompt/run.py`
(swaps `summarize.SYSTEM`, wraps the chat for C; nothing in `src/` changed). Outputs:
`scratch/summ_exp/out/`. Cost: free requests (B 1-2, C 3-4), about 1 min each.

Main ideas: 23, listed by hand from the original (León XIV's order of faith and humanity;
desire for good/beauty/truth; what is truly human; culture makes man more human; culture as
cultivation, paideia, Humanidades o barbarie; El Escorial's hierarchy of knowledge and the
liberal arts; Boethius; the human has to be won; Humanidades as philosophy's soil and science;
Trivium and Quadrivium, recovering reason; Gratry; Luther; rationalism and irrationalism,
Unamuno; Ortega's razón vital; Felipe VI; alétheia; then Plato, Aristotle, Sophocles, Aquinas,
Vitoria, Ortega and Heidegger on culture, John Paul II).

| Run | Prompt | Words | Share | Main ideas kept | Notes |
|---|---|---|---|---|---|
| A | today's SYSTEM | 4,270 | 67% | 23 / 23 | Faithful but quote-heavy: Luther, Gratry, Unamuno and Ortega quoted near whole |
| B | main ideas only; quote only a thesis; drop glosses, lists, supporting quotes | 5,664 | 88% | 23 / 23 | Failed: condensed the first ~650 words, then copied the rest of the text nearly word for word |
| C | B's prompt after a first request listing the key ideas (the skeleton) | 1,014 | 16% | 18 / 23 | Readable and short; the skeleton left out the whole reason block (Trivium/Quadrivium, Gratry, Luther, Unamuno, Ortega's razón vital) and put Felipe VI's line first as if the text began there |

Conclusions:
- No variant met the goal (main ideas kept and 25-40%). The prompt wording isn't the only
  cause: B, told plainly to drop supporting quotes, ran longer than A.
- B's copy is probably the `--keep-bold` follow-up ("write it again so that it also uses
  these phrases"): with many bold phrases, rewriting by copying the text is the easy answer.
  Not proven: the run keeps only the final answer.
- C's skeleton is the better shape (the length and order follow the argument), but the
  idea list decides what survives: a block made of quotations got no line, so it vanished.
- Next: run B and C again without `--keep-bold` (2 requests) to see whether the follow-up
  causes the copying, and give C's first request "one line per section of the argument,
  including what quoted authors argue". Then `/plan-feature` the winner.

## Round 2 (2026-11-23): without `--keep-bold`; C's skeleton covers every section

Same text and model, `run.py ... --no-bold`; C's first request now says "every section of
the argument gets at least one line, including a section made mostly of quotations".
Outputs: `scratch/summ_exp/out2/`.

| Run | Words | Share | Main ideas kept | Notes |
|---|---|---|---|---|
| B2 | 3,739 | 58% | 23 / 23 | Condenses well for the first two thirds (León XIV to El Escorial in ~450 words), then drifts: from Plato on (~1,300 words) it is a close paraphrase |
| C2 | 4,222 | 66% | 23 / 23 | The skeleton had 235 lines, nearly one per sentence: "at least one line per section" became "a line per sentence", and the summary followed it |

Conclusions:
- `--keep-bold` makes it worse (B 88% → 58%) but isn't the root cause: with no follow-up the
  model still stops condensing partway through a 6,400-word part.
- The skeleton follows its instruction too literally either way: too few lines (C, 16%,
  ideas lost) or one per sentence (C2, 66%). It doesn't fix the length on its own.
- The pattern in A, B and B2: the start of a long part is condensed to about 30%, the end
  is copied. The model condenses well over a short stretch, so the likely fix is smaller
  pieces (about 1,500 words, cut at paragraph ends, as `pieces` already does at the context
  limit), each summarized with B's prompt and joined without a merge request at
  `--detail full`.
- Next: D = B's prompt on ~1,500-word pieces, without and with `--keep-bold` (2 runs, about
  5 requests each).

## Round 3 (2026-11-23): pieces, a target in words, other models

Same text, B's prompt throughout. `D1500`: the part cut into ~1,500-word pieces at paragraph
ends (summarize's own `pieces`, with the context reported as 1,500 words), the pieces'
summaries joined without a merge request. `E`: B's prompt plus "Write about {target} words:
the original has {original}. Reach that length by saying each idea in fewer words, not by
leaving ideas out." (target = 30% of the request's text). `E1500`: both. Outputs:
`scratch/summ_exp/out3/`. Free models listed as up: nemotron-3.5-super-vl, nemotron-3-ultra,
gemma-4-31b-it. 37 free requests in all.

| Run | Model | Bold | Words | Share | Pieces (share each) |
|---|---|---|---|---|---|
| D1500 | super | no | 3,706 | 58% | 70, 59, 26, 70, 65 |
| D1500 | super | yes | 3,546 | 55% | 79, 69, 31, 44, 47 |
| E | super | no | 6,188 | 97% | (one request) |
| E1500 | super | no | 4,603 | 72% | 77, 83, 68, 74, 36 |
| B | ultra | no | 651 | 10% | (one request) |
| B | gemma | no | 5,870 | 92% | (one request) |
| E | ultra | no | 2,709 | 42% | (one request) |
| **E1500** | **ultra** | **no** | **2,390** | **37%** | 46, 32, 37, 30, 41 |
| E1500 (repeat) | ultra | no | 2,429 | 38% | 31, 30, 42, 52, 26 |
| E1500 | ultra | yes | 2,650 | 41% | 42, 29, 43, 50, 39 |

Conclusions:
- The model decides the length, not the prompt. nemotron-3.5-super-vl (summarize's first pick
  today) barely condenses whatever it is told (55-97%), and naming a word target made it
  longer. gemma copies (92%). nemotron-3-ultra condenses hard on its own (10%) and follows a
  target in words: 37-42% over three runs.
- Pieces help only a model that follows the target: ultra 42% → 37% (whole part → pieces).
- E1500 on ultra, read in full: all 23 main ideas, long quotations cut to their point, lists
  folded, real prose. Flaws: the seam between two pieces repeats Sophocles' ambivalence; each
  piece opens a little like a new text ("El texto explora…"); the first sentence credits the
  section's title (Felipe VI's words) to León XIV; "(en el Prometeo)" is outside knowledge.
- Meets the goal (main ideas, 25-40%) without bold; 41% with `--keep-bold`. No retry or cap was
  used, so nothing was cut to reach a length.
- Product change suggested: `/plan-feature adopt E1500 for summarize` (the target in words in
  the prompt, ~1,500-word pieces joined at `--detail full`, a model order that tries
  nemotron-3-ultra first, and the piece's place in the part given to each request so pieces
  don't open as new texts). Check it on a second book before changing the default model.
- Correction (round 4): the "gemma" row was answered by nemotron-super. A pinned model that
  fails twice (here: rate limits) falls back to the next one without a word
  (`ModelChat`/`pick_models`). The cache shows which model answered. The ultra rows were 5/5
  ultra.

## Round 4 (2026-11-23): the other free models, E1500

The same E1500 setup (B's prompt, target in words, ~1,500-word pieces, no merge) on every free
OpenRouter model of a usable size. The catalog has 12; `summarize` tries only the first 3
(`pick_models`). `run.py` now prints which models answered. Outputs: `scratch/summ_exp/out4/`.
About 50 free requests.

| Model | Bold | Words | Share | Pieces (share each) | Answered by | Time |
|---|---|---|---|---|---|---|
| **baidu/ernie-5.5-flash-preview** | no | 1,995 | **31%** | 30, 32, 30, 30, 31 | ernie 5/5 | 291 s |
| **baidu/ernie-5.5-flash-preview** | yes | 2,026 | **32%** | 30, 32, 32, 31, 30 | ernie 5/5 | 325 s |
| dots-studio/dots-3-note-preview | no | 2,079 | 32% | 31, 42, 17, 39, 31 | dots 5/5 | 60 s |
| inclusionai/ling-3.2-flash | no | 2,185 | 34% | 30, 29, 33, 36, 49 | ling 4, super 1 | 170 s |
| recursive/flint-v1.0 | no | 2,334 | 36% | 30, 28, 59, 29, 31 | flint 5/5 | 848 s |
| nemotron-3-ultra (round 3) | no | 2,390 | 37% | 46, 32, 37, 30, 41 | ultra 5/5 | 112 s |
| nvidia/nemotron-3.5-lightning | no | 3,425 | 54% | 28, 71, 57, 66, 30 | lightning 5/5 | 40 s |
| particle-ai/particle-1 | no | 4,564 | 71% | 80, 60, 72, 77, 57 | particle 5/5 | 65 s |
| google/gemma-4-31b-it | no | - | - | - | super 5/5 (rate-limited) | - |
| google/gemma-4-26b-a4b-it | no | - | - | - | super 5/5 (rate-limited) | - |

Not tried: liquid/lfm-3-1.7b (1.7B), nemotron-3-nano-omni (30B-A3B, reasoning). Gemma could not
be measured: both runs were rate-limited at once and fell back.

Conclusions:
- Ernie follows the target best by far: every piece at 30-32%, with and without bold. Read in
  full: 23/23 main ideas, tight prose, keeps the author apart from those quoted ("el autor
  interpreta", "según el autor"), no outside knowledge seen. It drops a few sub-points (Zeus's
  gift of justice in Plato; Aristotle's "without virtue the worst of animals"). Its only
  slowness was rate-limit waits.
- Two flaws are shared by ultra and ernie, so they belong to the setup, not the model:
  Sophocles is said twice where two pieces meet, and the section's title (Felipe VI's words)
  leaks into the text before the text reaches it. The "Part:" line gives the title as if it
  were content. Fix in the product: say what the title is, and tell a piece it continues the
  previous one.
- dots, ling and flint also land in the band, but less evenly (one piece at 17%, 49% or 59%),
  and flint is slow. lightning and particle barely condense, like super.
- For `/plan-feature`: E1500 with the model order ernie, ultra, dots, ling. ernie is a
  "preview" model that may be withdrawn, so keep ultra second. Report a fallback
  instead of hiding it.

## Round 5 (2026-11-23): adopted in `summarize`

E1500 is now the product: B's prompt with the target in words, ~1,500-word pieces (a piece is
told it continues the previous one and is shown its last paragraph), the title line marked as
headings, no merge at `full`. Models: ernie, then ultra only when ernie is gone from the free
list; a down ernie is waited for (30 s to 10 min, ~18.5 min in all). Measured with the real CLI
(`--fresh --to md`), outputs in `scratch/summ_adopt/`:

| Run | Section | Detail | Model | Words in | Words out | Share | Requests |
|---|---|---|---|---|---|---|---|
| a | Apuntes `I. > 1.` | full, bold | ernie | 6,400 | 2,011 | **31%** | 5 |
| b | Apuntes `I. > 1.` | normal, bold | ernie | 6,400 | 1,001 | **16%** | 7 |
| c | Apuntes `I. > 1.` | full, bold | ultra (`--model`) | 6,400 | 2,598 | 41% | 5 |
| d | Lecciones §137 | full, bold | ernie | 2,554 | 808 | **32%** | 2 |

All in the expected bands. (d): Lecciones' outline is flat, so its largest leaf (2,554 words, two
pieces) stood in for the planned 3,000-8,000-word one. No waits or fallbacks happened.
