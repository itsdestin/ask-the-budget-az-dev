# Handoff: Plan 5 Session C — JLBC memo renderer (Task 21 now; 22–23 later)

You are working in `~/YouCoded/Projects/ask-the-budget-az-dev` (Linux, venv at
`.venv`).

## Read first

`docs/superpowers/plans/2026-08-01-standalone-plan-5-admin-packaging.md` —
Ground truth, then **Track 5 (Tasks 21–23)**.

## Do Task 21 now. Do NOT start Tasks 22–23 yet.

**Task 21** (the JLBC Staff-Memorandum renderer) needs nothing but the
committed reference document, so it is safe to build immediately:
`samples/raw-docx/jlbc-staff-memorandum-style-reference.docx` — the real FY 2027
Appropriations Report Round 1 instructions memo, vendored specifically so this
task has a fixture that survives a fresh clone.

**Tasks 22–23 (writing and shipping the handbook) must wait for Session A to
finish the admin screens.** Part 5 of the handbook describes those screens
button by button. Written against a plan rather than a running app, it will
name buttons that ended up called something else — and a handbook that is wrong
in its details teaches the reader not to trust the parts that are right.

## What Task 21 is

A reusable renderer, `scripts/jlbc_memo.py`, that turns a Markdown subset into
a Word document matching JLBC house style, plus `scripts/build_handbook.py`.

The measured style values are in the plan's Task 21 table — **implement those
numbers, do not eyeball the reference**. Two that look like mistakes and are
not: the body is **10.5 pt** even though the `Normal` style says 12 pt (every
body run overrides it), and section headings use the **built-in `Header`
paragraph style**. Matching house style means matching both.

Read expected values out of the committed reference docx in your tests where
practical, so a future JLBC style change is a fixture swap rather than a
rewrite.

**Step 5 is optional but worth doing:** repoint `harness/documents.py`'s
`_render_docx` at the new renderer so AI Mode's generated memos come out in
house style too, instead of Word defaults.

## ⚠ A BACKFILL IS RUNNING

App server on :9300, plus an orchestrator and maintainer. **Do not restart
them.** Do not touch `data/`, `~/backfill-scripts/`, `pyproject.toml`,
`uv.lock`, or the main `.venv/`. Do not run the eval or MinerU.

Your files (`scripts/`, `tests/`) are disjoint from the ingest path, which is
why this is safe to do now. Session A owns `app/`, `harness/`, `store/`,
`webapp/src/` — the one file you may touch there is `harness/documents.py`
(Step 5), and only if Session A is not mid-edit on it.

## Method

- Worktree: `git worktree add ~/atb-worktrees/plan5-c -b plan5-c origin/master`
- Test with `.venv/bin/python -m pytest tests/test_jlbc_memo.py -q`. Never
  `uv run` in a worktree.
- **Build the output and open it.** This is one of the few tasks where a green
  test is not sufficient evidence — it has to *look* like a JLBC memo.
- Merge `--no-ff`, push, remove the worktree.

## Report

What the renderer supports, test evidence, whether you did Step 5, and any
place the reference memo's styling could not be reproduced faithfully with
python-docx — Destin will want to know before the handbook is typeset into it.
