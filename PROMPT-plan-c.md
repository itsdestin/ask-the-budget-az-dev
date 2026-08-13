# Plan C — the "Add a JLBC book" panel and the ingest queue

**Handoff for a fresh session. Written 2026-08-13, immediately after Plan B merged.**

You are implementing the last two decisions of the document-types /
resilient-processing design: **T10** (invert the "Add a JLBC book" panel) and
**T13** (the queue shows work, not history). Both are specified, both are
self-contained, and neither needs an OpenRouter key or spends money.

---

## Start here

```bash
git fetch origin && git pull origin master
git worktree add -b plan-c ~/ask-the-budget-az-worktrees/plan-c master
ln -s /home/destin/YouCoded/Projects/ask-the-budget-az-dev/.venv ~/ask-the-budget-az-worktrees/plan-c/.venv
ln -s /home/destin/YouCoded/Projects/ask-the-budget-az-dev/webapp/node_modules \
      ~/ask-the-budget-az-worktrees/plan-c/webapp/node_modules
```

Read `CLAUDE.md` and `STATUS.md` first — `STATUS.md` is the single source of
truth for what is shipped. Then read the two spec decisions:

**`docs/superpowers/specs/2026-08-11-document-types-and-resilient-processing-design.md`**
— sections **T10** and **T13**. They are short, complete, and carry the
reasoning. Do not work from this file's summary; work from the spec.

There is no plan yet. **Write one** (`superpowers:writing-plans` →
`docs/superpowers/plans/YYYY-MM-DD-plan-c-*.md`), then execute it. Plan B was
executed with `superpowers:subagent-driven-development` and that worked well.

---

## What the two decisions are, in one paragraph each

**T10 — the book panel answers the wrong question.** Today it lists every
edition that exists, with no indication of which ones you already have, so it
reads as noise. It should answer *"what has JLBC published that we don't
have?"*: find the newest fiscal year in the corpus per family, probe
azjlbc.gov beyond it, and surface only what is missing, with an Add button.
Editions already present are marked or omitted. **Non-ingestable editions are
shown greyed with their `era_note` and Add is NOT offered** — "FY 1984 was
never published as per-agency PDFs" is a fact worth stating. A specific year
can still be requested by hand.

**T13 — the queue shows history instead of work.** `GET /api/jobs` should
return every non-terminal job, terminal jobs finished within a window
(default 24 h), and **every `failed` job regardless of age**, until it is
retried, cancelled or dismissed. That last clause is the one rule not to
relax — this project has repeatedly been bitten by work that fails with
nobody told, and a failure that ages off the screen after a day is a failure
nobody will ever see. Successes age out because a finished document is
visible in search.

**Two implementation constraints the spec is explicit about:**
- **Filter on the job file's mtime from the directory scan, BEFORE parsing
  it.** The current cost is ~7,116 file reads and the office reads this off an
  SMB share. Deciding from the directory entry means parsing only the handful
  that qualify.
- **Job files are NOT deleted.** They are the ingest audit trail — what was
  added, by whom, when, and now which extraction methods were tried. T13
  changes what the queue *shows*, never what is *kept*. The page keeps a way
  to see everything, so "where did my document go" has an answer better than
  "trust me".

---

## Current state, and your baselines

Plan B merged at `cb94195`. Gates on master **right now** — re-run them before
you start and use YOUR numbers, not these, since master moves fast (it took 75
commits from other sessions during Plan B):

| gate | value at handoff |
|---|---|
| `uv run pytest -q` | **2798 passed, 5 skipped** |
| `cd webapp && npx vitest run` | **859 passed** |
| `cd webapp && npx tsc -b` | **exit 0** |
| Layer 1 eval | recall@5 88.10% · @15 100% · @20 100% · refusal 60% |

The 5 skips are documented ONNX/model-closure skips and are expected.

**You almost certainly do not need to run the eval.** It is required after
changes to `retrieval/`, `ingest/`, `chunking/`, `citation/` or
`harness/system-prompt.md`. T13 touches `ingest/jobs.py`, so if you change
anything there beyond the listing filter, run it — otherwise a note in the PR
saying why it does not apply is enough. It needs `JLBC_DATA_DIR`.

---

## 🔴 File-ownership boundary — another session is live

A concurrent session is designing **structural extraction quality** (ranking
extractors on structure rather than volume). When it moves to implementation
it will own:

```
ingest/coverage.py       ingest/worker.py       ingest/ladder.py
ingest/inspection.py     chunking/builder.py
```

**Plan C should not need any of those.** Your surfaces are:

```
T10:  app/routes/books.py   ingest/book_discovery.py
      webapp/src/pages/Upload.tsx  (the book panel)
T13:  app/routes/jobs.py    ingest/jobs.py (the LISTING path only)
      webapp/src/pages/Upload.tsx  (the queue)
```

`ingest/jobs.py` is the one genuine overlap risk — the other session added
`JobRecord.held_out` and `extraction_attempts` there. **Touch only the listing
/ filtering path; do not restructure `JobRecord`, `advance()`, or the state
machine.** If you find you need to, stop and coordinate rather than merging
over it.

Both of you will edit `webapp/src/pages/Upload.tsx`, but in different regions
(book panel + queue vs. the duplicate-upload response). Merge conflicts there
are likely and small. Sync with master often.

---

## Hard-won lessons from Plan B — these will save you real time

Plan B ran 8 tasks with a review after each. Every one of these cost somebody
an hour:

1. **The plan's prose is reliable; the plan's example code is not.** Three
   separate tasks found the plan's code blocks wrong while its reasoning was
   right — including a loop that would have discarded healthy extractions in
   production. **Treat any code block in a plan as a sketch to run and
   correct, never text to transcribe.**

2. **Check any comment justification you can cheaply check.** FOUR WHY
   comments on Plan B asserted things that measurement contradicted. One
   claimed "a budget bill is mostly tables"; the committed sample bill is
   279,819 paragraph characters against 176 table characters. If a
   justification is checkable, check it — and if it turns out false, say so
   rather than committing a comment that argues against its own evidence.

3. **Verify tests by mutation, not by reading.** This project has shipped
   five tests that passed whether or not the feature worked. Break the exact
   line a test targets, watch it go red, restore it. Reviewers on Plan B found
   guards that were correct, load-bearing, and green whether or not they
   existed.

4. **Mutate the file IN PLACE.** `uv run pytest` re-resolves the real package
   regardless of `PYTHONPATH`, so mutating a scratch copy under `/tmp` gives a
   false green — a reviewer got 9/9 "passing" against a module it had
   deliberately broken. And restore with a targeted edit: **three agents on
   Plan B destroyed their own uncommitted work with `git checkout <file>`.**

5. **jsdom applies no stylesheet.** A green vitest run says nothing about
   layout, clipping or paint order. Both of Plan B's predecessor defects
   shipped under ~3,000 passing tests. Say plainly in your report what has not
   been seen in a browser.

6. **`tsc -b` is stricter than `tsc --noEmit`** and rejects unused imports the
   dev check allows. It is the gate that matters.

---

## Two things worth knowing about the surfaces you're touching

**The book panel already works and is not broken** — `ingest/book_discovery.py`
is catalog-first (zero network on a hit) with a HEAD-verified probe ladder,
and a live dry run once found the FY2027 Appropriations Report that the
harvest had recorded as expected-but-unpublished, walking 139 documents with 0
unreachable. T10 is a **presentation** inversion, not a rewrite of discovery.
Do not re-engineer the ladder.

**The queue now carries extraction attempts.** Plan B added
`JobRecord.extraction_attempts` (one entry per rung tried, with its coverage)
and `JobRecord.held_out`. A held-out document already surfaces on the Admin
page under "Held out of search". Decide deliberately whether the Upload queue
should show attempts too — Plan B left that open, and it is a reasonable thing
for T13 to settle, but it is your call to make explicitly rather than by
accident.

---

## Definition of done

- A written plan under `docs/superpowers/plans/`, executed task by task with a
  review after each.
- All three gates green, with the numbers stated.
- `STATUS.md` updated — it is the single source of truth, and the only place
  status lives. Do not duplicate status into `CLAUDE.md`.
- Merged **and pushed** to `origin/master` (in this project "merge" means
  both), worktree and branch removed afterwards.
- An honest list of what has NOT been verified in a browser.

**Ask Destin before deciding anything the spec leaves open.** He is a
non-developer and relies on the WHY comments in the code to understand what it
does — record the *evidence* behind a choice, not just the choice.
