# Progress

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
- The user runs `git push` and `gh pr create/merge` themselves, per the no-push rule.

## Blocked
- None. (Claude couldn't edit `.claude/settings.local.json` itself, so the user copied in the
  version from `scratch/settings.local.json` on 2026-10-11.)

## Next
- Not yet decided.
