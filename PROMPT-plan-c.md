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

## 🔴 Task 0 — reproduce the measurement before you write the plan

**Do this first.** It takes ten minutes, and the decision recorded at the end
of this section rests on it. The storage shape is already chosen — you are
confirming the evidence, not re-opening the choice.

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

### ✅ DECIDED 2026-08-13 by Destin — finished jobs move to `jobs/done/`

Three options were put to him; this is the one he chose, and it is not open
for a fresh session to re-litigate:

| | what it means | why not |
|---|---|---|
| 1. Read every file | Filter after parsing. Correct, shrinks the payload only | 7,118 file opens per refresh over SMB stays, and it fixes none of the six other callers |
| 2. State in the filename `<job_id>.<state>.json` | One directory listing answers everything | Same speed win, but `load_job()` can no longer build a path from an id alone, and every rename is a state change in two places at once |
| **3. Move finished jobs to `jobs/done/` ← CHOSEN** | The main folder holds only work; history is one folder over | — |

**Why 3 over 2:** it keeps the property the whole one-file-per-job design
exists for — *"a colleague, or a future maintainer with no code access, can
read the queue in Notepad"* (`ingest/jobs.py` module docstring). A folder
called `done` says what it holds. A filename suffix does not.

**This makes the 24-hour window moot, so T13's rule simplifies to:**

> **The queue shows work: anything unfinished, plus anything failed. Nothing
> else. Plus one line — "7,100 documents finished — view all".**

Once finished jobs live in another folder they simply do not appear, so an age
window is machinery with nothing left to do — and an age window with an
exception clause is precisely what produced the defect measured above. One
rule with no exception cannot reproduce it. Destin has accepted this.

### What choice 3 actually commits you to — think this through in the plan

These are the consequences, not optional extras. Work them into the plan
rather than discovering them one at a time:

- **`failed` stays in the main folder.** That is the entire point. Only `live`
  and `cancelled` move. Retry (`failed → queued`) needs no move because it
  never left; **dismiss is `failed → cancelled`, which moves it** — that is
  exactly T13's "until it is retried, cancelled or dismissed", and it falls
  out of the design instead of needing a rule.
- **`load_all()` splits in two, and each of the seven callers must be told
  which one it wants.** Roughly: the worker's `_candidates()`, the upload
  duplicate check and the book skip-existing check want **active only**; the
  admin panels want **active only** (they are looking for failures); the "view
  all" link is the one caller that wants **both**. Getting one of these wrong
  is a silent correctness bug, not a performance bug — a duplicate check that
  stops seeing history starts re-ingesting documents. **Read each caller and
  justify its choice in a WHY comment.**
- **`load_job(job_id)` must look in both folders** — a job id from a URL may
  name an archived job.
- **The move needs `_replace_with_retry`'s treatment**, not a bare
  `os.rename`. Windows and SMB refuse to move a file another machine has open,
  and the queue page polls these files from other PCs. Same reasoning as the
  comment already on that function.
- **The failure mode must be benign.** If the move fails, the job file stays
  put as `live` and shows up in the queue until something sweeps it. That is
  the right way round — a stray finished row is noise; a lost job file is the
  audit trail gone.
- **7,100 existing files need moving once.** Decide deliberately whether that
  is a startup sweep, an admin button, or a one-off script, and whether it
  takes the ingest lock. It runs against the live office share.
- **Nothing is deleted, ever.** Unchanged from the spec.
- **One front-end touch:** a row now disappears the instant it finishes, which
  is abrupt for the person who just uploaded it and is watching. The browser
  knows what it was watching — keep those rows visible for the rest of the
  session. This is the only thing the 24-hour window was ever really doing.

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
document to process.** That is why the storage choice went the way it did —
moving finished jobs out of the folder fixes every one of these at once, where
a filter in the listing route fixes none of them.

**Every one of these seven callers must be visited**, not to be rewritten, but
to be told which of the two loaders it wants (see the consequences list
above). Leaving one on the wrong loader is a silent correctness bug. This is
the largest single risk in Plan C — treat it as its own task with its own
review, and state each caller's choice and its reason in the plan.

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

**T13 — the queue shows history instead of work.** Read Task 0 above before
the spec: it carries the one spec instruction not to take literally, the
measurement that disproves it, and the storage decision Destin has already
made. **Job files are NOT deleted** either way. They are the ingest audit trail —
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
`JobRecord.held_out` and `extraction_attempts` there. **The decision above
means you WILL touch its write path** (the move on reaching a terminal state)
and you will change `load_all()`'s shape, which `ingest/worker.py` calls —
a file the other session owns.

**That is a coordination event, not a merge risk to absorb quietly.** Before
you build it: tell the other session what `load_all()` is becoming, agree who
edits `ingest/worker.py:_candidates`, and prefer *adding* `load_active()`
alongside a `load_all()` that keeps working over changing `load_all()` under
them. Still stay out of `advance()`'s transition rules and the state machine
itself — the move is a consequence of a transition, not a new transition.

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
