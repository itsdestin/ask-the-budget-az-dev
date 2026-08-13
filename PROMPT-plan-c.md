# Plan C — the "Add a JLBC book" panel and the ingest queue

**Handoff for a fresh session. Written 2026-08-13, revised the same day after
review.** The revision matters: the spec's T13 carries one implementation
instruction that measurement contradicts, and following it literally ships a
queue that hides 13 of the 14 failures the decision exists to surface. That
correction is Task 0 below — read it before anything else.

You are implementing the last two decisions of the document-types /
resilient-processing design: **T10** (invert the "Add a JLBC book" panel) and
**T13** (the queue shows work, not history). Neither needs an OpenRouter key
and neither spends money.

---

## Start here

```bash
git fetch origin && git pull origin master
git worktree add -b plan-c ~/ask-the-budget-az-worktrees/plan-c master
ln -s /home/destin/YouCoded/Projects/ask-the-budget-az-dev/.venv ~/ask-the-budget-az-worktrees/plan-c/.venv
ln -s /home/destin/YouCoded/Projects/ask-the-budget-az-dev/webapp/node_modules \
      ~/ask-the-budget-az-worktrees/plan-c/webapp/node_modules
```

Read `CLAUDE.md` and `STATUS.md`, then spec sections **T10** and **T13** in
`docs/superpowers/specs/2026-08-11-document-types-and-resilient-processing-design.md`.
They carry the reasoning; this file carries only what the spec does not.

There is no plan yet. **Write one** (`superpowers:writing-plans` →
`docs/superpowers/plans/YYYY-MM-DD-plan-c-*.md`), then execute it. Plan B used
`superpowers:subagent-driven-development` and that worked well.

---

## 🔴 Task 0 — measure the queue, then bring Destin the choice

**Do this before writing the plan.** It takes ten minutes and it decides the
shape of half the work.

The spec's T13 says: *"Filter on the job file's mtime from the directory scan,
before parsing it."* **A job file's timestamp cannot tell you the job's
state** — that is inside the file — so a timestamp-first filter cannot find
the two categories T13 says must always be shown. Measured on the live data
dir on 2026-08-13:

| | count |
|---|---|
| job files on disk | 7,118 |
| `live` | 7,100 |
| **`failed`** | **14** |
| `cancelled` | 4 |
| **`failed` with a file older than 24 h** | **13 (all 12.6 days old)** |
| non-terminal with a file older than 24 h | 0 today — but see below |

A 24-hour timestamp window drops 13 of the 14 failures. The zero in the last
row is luck, not safety: ingest is default-OFF per machine, so an uploaded
document can legitimately sit `queued` for days with a stale timestamp while
the ingest PC is closed, and a timestamp filter would hide that too — someone
uploads a book, the row vanishes, and nothing anywhere says why.

Reproduce it yourself before deciding anything (adjust the path if your data
dir differs):

```bash
python3 - <<'EOF'
import json, time, collections
from pathlib import Path
d, now, DAY = Path("data/insight-data/jobs"), time.time(), 86400
states, stale = collections.Counter(), collections.Counter()
for p in d.glob("*.json"):
    try: st = json.loads(p.read_text()).get("state")
    except Exception: continue
    states[st] += 1
    if (now - p.stat().st_mtime) / DAY > 1: stale[st] += 1
print("all:", dict(states)); print("older than 24h:", dict(stale))
EOF
```

### The choice to put to Destin

Knowing a job's state cheaply requires one of these. **Options 2 and 3 change
how job files are written, which crosses the file boundary below — that is
exactly why this is a decision and not a guess.**

| | what it means | cost |
|---|---|---|
| **1. Read every file** | Keep today's behaviour; filter after parsing. Correct, and the payload shrinks even if the read count does not | 7,118 file opens per refresh over SMB stays |
| **2. Put the state in the filename** | `<job_id>.<state>.json`. One directory listing answers everything, zero file opens for rows you will not show | Touches `save()`/`advance()` and `load_job()`'s path building |
| **3. Move finished jobs to `jobs/done/`** | The main folder holds only work; history is one folder over and still readable in Notepad | Touches the write path at the `live` transition |

**Recommended: option 3, paired with the T13 simplification below.** It is the
only one that also fixes the callers in the next section, and it keeps the
"readable in Notepad" property that the whole one-file-per-job design exists
for.

### The T13 simplification worth putting to Destin at the same time

T13 as written has two interacting rules — an age window, plus an exception
that overrides the window for failures. Exceptions to a window are where bugs
live, and the exception is what the error above hinges on. The simpler rule:

> **The queue shows work: anything unfinished, plus anything failed. Nothing
> else. Plus one line — "7,100 documents finished — view all".**

Drop the 24-hour window. The spec itself gives the reason it is unnecessary:
*"successes age out because a finished document is visible in search."* If
that is true after a day it is true after a minute. The one moment a window
genuinely serves someone is the second a document finishes and its row would
vanish while they are watching it — and the **browser already knows what you
were watching**, so that is a small front-end touch, not a server rule with a
configurable window.

This is a change to T13 as written, so **it needs Destin's yes, not your
judgement.** If he says no, keep the window and note that it does not change
the storage question above.

---

## 🔴 The cost is in seven places, not one

The spec frames this as a page-payload problem — 3.02 MB per refresh. The same
all-7,118-files read happens in every one of these:

```
app/routes/jobs.py:27      the queue           ← T13's stated target
app/routes/admin.py:754    admin page
app/routes/admin.py:905    admin "Needs attention"
app/routes/upload.py:303   EVERY upload (duplicate check)
app/routes/books.py:118    EVERY book ingest (skip-existing check)
ingest/worker.py:1708      the worker's poll loop, picking the next job
ingest/jobs.py:305         resumable()
```

`ingest/worker.py:1708` is the one that matters most and is on nobody's radar:
**the background worker reads all 7,118 files every time it looks for the next
document to process.** Fixing only the listing route leaves five of seven
callers paying the full cost. Do not go and fix all seven — that is scope
creep — but let it inform the Task 0 choice, because option 2 or 3 fixes them
all for free where option 1 fixes none of them.

---

## What the two decisions are

**T10 — the book panel answers the wrong question.** Today it lists every
edition that exists with no indication of which you already have, so it reads
as noise (measured: 62 editions offered, 0 of them usefully addable). It
should answer *"what has JLBC published that we don't have?"* Non-ingestable
editions are shown greyed with their `era_note` and Add is NOT offered — "FY
1984 was never published as per-agency PDFs" is a fact worth stating. A
specific year can still be requested by hand. **This is a presentation
inversion, not a rewrite of discovery** — `ingest/book_discovery.py` is
catalog-first with a HEAD-verified probe ladder that once found the FY2027
Appropriations Report the harvest had recorded as unpublished, walking 139
documents with 0 unreachable. Do not re-engineer the ladder.

**T13 — the queue shows history instead of work.** See Task 0 above for the
one instruction not to take literally, and for the rule shape to confirm.
**Job files are NOT deleted** either way. They are the ingest audit trail —
what was added, by whom, when, and now which extraction methods were tried.
T13 changes what the queue *shows*, never what is *kept*, and the page keeps a
way to see everything so "where did my document go" has an answer better than
"trust me".

---

## Four things the spec does not cover and you must decide

1. **T10 needs the network the moment the panel opens.** This app is
   deliberately offline-capable — it was verified cold-starting with WiFi
   disconnected. Give the check a timeout and a cached last-good answer, and
   show *"Checked azjlbc.gov 3 hours ago — [Check again]"* rather than probing
   live on every open. JLBC publishes a couple of books a year; there is
   nothing to gain from asking every time, and an unreachable site must
   produce an honest sentence, not a spinner.

2. **The "139 documents" count in the spec's mockup costs more than a HEAD.**
   `_plan_by_probing` only climbs the URL ladders; the document count comes
   from `walk_edition`, which fetches and parses JLBC's index pages. Either
   accept the wait behind a visible "checking…" state, or leave the count off
   the first screen and fetch it on click.

3. **"The newest fiscal year we already have" has a known trap.** The obvious
   route is to read document IDs — and STATUS.md records that **21 documents
   carry the wrong family in their ID** (Baseline sections minted with an
   approps ID). `source_url` is the only independent evidence and 647/647
   parse from it. Get this wrong and the panel offers you a book you already
   have.

4. **Failures already have a second home.** The Admin page's "Needs attention"
   panel shows `failed AND held_out` jobs with a Dismiss button (which routes
   `failed → cancelled` — that is what "dismissed" means in T13; do not build
   a third verb). T13 puts failures on the Upload page too, which is right
   because Upload is not admin-gated. Decide deliberately whether the same
   failure appears in both places and say so in the plan.

**Also worth settling:** Plan B added `JobRecord.extraction_attempts` (one
entry per rung tried, with its coverage). Whether the Upload queue shows
attempts is open. Decide it explicitly rather than by accident.

---

## 🔴 File-ownership boundary — another session is live

A concurrent session is implementing **structural extraction quality**. It
owns:

```
ingest/coverage.py   ingest/worker.py   ingest/ladder.py
ingest/inspection.py   chunking/builder.py
```

Your surfaces:

```
T10:  app/routes/books.py   ingest/book_discovery.py
      webapp/src/pages/Upload.tsx  (the book panel)
T13:  app/routes/jobs.py    ingest/jobs.py
      webapp/src/pages/Upload.tsx  (the queue)
```

`ingest/jobs.py` is the genuine overlap — the other session added
`JobRecord.held_out` and `extraction_attempts` there. Stay out of `advance()`
and the state machine. **If Task 0 lands on option 2 or 3 you will need to
touch the write path, which is a coordination event, not a merge risk to
absorb quietly** — raise it with Destin and the other session before you
build it.

Both of you edit `webapp/src/pages/Upload.tsx` in different regions (book
panel + queue vs. the duplicate-upload response). **Rebase on master before
every task, not just at the start** — 75 commits from other sessions landed
during Plan B. If `ingest/jobs.py` has moved, read the diff before continuing.

---

## Baselines, gates and one lesson

Gates on master at handoff. **Re-run them and use YOUR numbers** — master moves
fast:

| gate | value at handoff |
|---|---|
| `uv run pytest -q` | 2798 passed, 5 skipped |
| `cd webapp && npx vitest run` | 859 passed |
| `cd webapp && npx tsc -b` | exit 0 |
| Layer 1 eval | recall@5 88.10% · @15 100% · @20 100% · refusal 60% |

The 5 skips are the documented ONNX/model-closure skips.

**The eval does not apply here.** It measures search quality and cannot see a
job-listing or panel change. Say so in the PR and move on. (If Task 0 lands on
a write-path change, that is still not a retrieval change — but say why in the
PR rather than skipping silently.)

**One lesson from Plan B worth repeating because it is not in `CLAUDE.md`:**
when you mutate a file to verify a test, restore it with a **targeted edit**.
Three agents on Plan B destroyed their own uncommitted work with
`git checkout <file>`. Everything else Plan B taught — plan code is a sketch
to run, not text to transcribe; check any comment justification you can check;
verify tests by mutation in place; jsdom applies no stylesheet; `tsc -b` is
the gate — is already in `CLAUDE.md` and in the project memory. Read it there.

---

## Definition of done

- A written plan under `docs/superpowers/plans/`, executed task by task with a
  review after each.
- All three gates green, with the numbers stated.
- **The before/after measurement stated**: file reads and response size for
  `GET /api/jobs`. The entire justification for T13 is a number; a change that
  does not report its own number has not been measured.
- **Destin has looked at both surfaces in a browser before merge.** Both of
  these changes are purely about what a page looks like, and this project's
  recurring failure is shipping visually-broken work under thousands of
  passing tests. A list of what was not verified is not a substitute here.
- `STATUS.md` updated — the single source of truth, and the only place status
  lives. Do not duplicate status into `CLAUDE.md`.
- Merged **and pushed** to `origin/master` (here "merge" means both), worktree
  and branch removed afterwards.

**Ask Destin before deciding anything the spec leaves open.** He is a
non-developer and relies on the WHY comments in the code to understand what it
does — record the *evidence* behind a choice, not just the choice.
