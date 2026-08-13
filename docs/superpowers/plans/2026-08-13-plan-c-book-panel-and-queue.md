# Plan C — the "Add a JLBC book" panel and the ingest queue

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development`
> (recommended) or `superpowers:executing-plans` to implement this plan
> task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the "Add a JLBC book" panel answer *"what has JLBC published
that we don't have?"* (spec T10), and make the ingest queue show outstanding
work rather than 7,100 rows of history (spec T13).

**Architecture:** T13 is a **storage** change, not a filter: jobs that reach
`live` or `cancelled` move to a `<data_dir>/jobs/done/` subdirectory, so the
main jobs folder comes to hold exactly the set the queue should show —
everything unfinished, plus everything `failed`. `failed` never moves, which
is what makes "every failed job, regardless of age" a property of where the
file lives instead of a rule something has to remember to apply. T10 is a
**presentation** inversion over the existing catalog-first discovery: derive
which book editions the corpus already holds from `source_url`, probe
azjlbc.gov just beyond that, cache the answer, and offer only what is
missing.

**Tech Stack:** Python 3.12 / FastAPI / pytest (backend), React 18 + Vite +
vitest (webapp). No new dependencies.

---

## Global Constraints

Copied from `CLAUDE.md`, the spec, and the Plan C handoff. Every task's
requirements implicitly include these.

- **Job files are NEVER deleted.** They are the ingest audit trail. This work
  changes what the queue *shows* and *where a file lives*, never what is kept.
- **`failed` jobs stay in `<data_dir>/jobs/` forever**, until retried
  (`failed → queued`) or dismissed (`failed → cancelled`). This is spec T13's
  one rule not to relax.
- **Do not touch `advance()`'s transition rules or the state machine.** The
  move is a consequence of a transition, not a new transition.
- **`load_all()` keeps its name and its meaning** (every job, both folders).
  New behaviour arrives as `load_active()`. A peer session was told this;
  changing `load_all()`'s meaning underneath it breaks that agreement.
- **Annotate every non-trivial edit with a WHY comment** recording the
  *evidence* that drove the choice — Destin is a non-developer and reads these
  to understand the code. A justification you can cheaply check, you must
  check before writing it.
- **Never write "verified", "validated", "healthy" or "good"** about a
  document's extraction. Say only what was measured.
- **Assert behaviour, not mechanism.** Verify each new test by mutation:
  break the exact line it targets *in place*, watch it go red, restore it with
  a **targeted edit** — never `git checkout <file>`, which has destroyed three
  agents' uncommitted work on this project.
- **`tsc -b` is the gate**, not `tsc --noEmit`.
- **jsdom applies no stylesheet.** A green vitest run says nothing about
  layout. Record what has not been seen in a browser.
- Baselines on this branch at start: **2824 pytest / 5 skipped · 913 vitest ·
  `tsc -b` exit 0**. The 5 skips are the documented ONNX/model-closure skips.

---

## Measured facts this plan is built on

Re-derived on 2026-08-13 against the live data dir and `documents.json`. Do
not take them on trust — Task 1 Step 1 re-runs the first one.

| fact | value |
|---|---|
| job files in `<data_dir>/jobs/` | 7,118 |
| `live` / `failed` / `cancelled` | 7,100 / 14 / 4 |
| `failed` with a file older than 24 h | **13 of 14** |
| non-terminal jobs | 0 today |
| documents in `documents.json` | 7,434 |
| documents with no `source_url` | 5 |
| newest edition in corpus | approps **FY2026**, baseline **FY2027** |

**The four azjlbc URL directory patterns**, counted across the whole corpus —
a two-pattern regex would silently miss 1,581 documents and under-report the
newest edition:

| pattern | family | example | docs |
|---|---|---|---|
| `{yy}ar` | approps | `/26ar/508.pdf` | FY2013–2026 |
| `{yy}app` | approps | `/12app/260.pdf` | FY2005–2012 |
| `{yy}baseline` | baseline | `/27baseline/353.pdf` | FY2013–2027 |
| `{yy}book1` | baseline | `/12book1/353.pdf` | FY2012 only |

`12book1/353.pdf` is titled *"CAPITAL OUTLAY ESTIMATES — FY 2012 Baseline"*
and `12app/260.pdf` *"Capital Outlay — FY 2012 Appropriations Report"*, which
is how the last two rows were confirmed rather than guessed.

---

## File structure

**Create**

| file | responsibility |
|---|---|
| `ingest/archive.py` | Where a job file lives, and the one-time sweep. Kept out of `jobs.py` so the peer session's `jobs.py` edits and this plan's edits touch different files wherever possible |
| `app/routes/books_missing.py` | The T10 "what's missing" check + its on-disk cache |
| `webapp/src/pages/upload/QueuePanel.tsx` | The queue, extracted from `Upload.tsx` |
| `webapp/src/pages/upload/BookPanel.tsx` | The book panel, extracted from `Upload.tsx` |
| `tests/test_job_archive.py` | Task 1 + 2 guards |
| `tests/test_job_loaders.py` | Task 3 guards — the seven callers |
| `tests/test_books_missing.py` | Task 6 guards |
| `webapp/src/pages/upload/QueuePanel.test.tsx` | Task 5 guards |
| `webapp/src/pages/upload/BookPanel.test.tsx` | Task 7 guards |

**Modify**

| file | change |
|---|---|
| `ingest/jobs.py` | `save()` routes by state; `load_active()`; `load_all()` spans both folders; `load_job()` searches both; `resumable()` uses `load_active()` |
| `app/routes/jobs.py` | `GET /api/jobs` returns active work + a finished count; `?all=1` returns everything |
| `app/routes/admin.py` | two callers pointed at `load_active()`; `last_live` sourced from the archive |
| `app/routes/upload.py` | one caller pointed at `load_active()` |
| `app/routes/books.py` | one caller pointed at `load_active()`; mount the missing-editions route |
| `ingest/worker.py` | **one line** — `_candidates()` uses `load_active()` |
| `app/main.py` | lifespan runs the one-time archive sweep |
| `webapp/src/pages/Upload.tsx` | render the two extracted panels |
| `webapp/src/api.ts` | types + fetchers for the new shapes |
| `STATUS.md` | the record |

**Extracting the two panels out of `Upload.tsx` is deliberate.** A peer
session also edits that file, and the handoff predicts conflicts there; two
new files plus a thin parent conflict far less than one file two sessions both
rewrite. It also gets each panel under its own test file.

---

## Task 1: Job files move to `jobs/done/` when they finish

**Files:**
- Create: `ingest/archive.py`
- Modify: `ingest/jobs.py` (`save`, `load_job`, `load_all`, `resumable`, + new `load_active`)
- Test: `tests/test_job_archive.py`

**Interfaces:**
- Consumes: nothing.
- Produces, all importable from `ingest.jobs`:
  - `ARCHIVED_STATES: frozenset[str]` — `{"live", "cancelled"}`
  - `archive_dir() -> Path` — `<data_dir>/jobs/done`, created on demand
  - `load_active() -> list[JobRecord]` — main folder only, newest first
  - `load_all() -> list[JobRecord]` — both folders, deduped, newest first
  - `archived_count() -> int` — a directory listing; opens no files
  - `newest_archived_live() -> JobRecord | None`
  - `save(job) -> Path`, `load_job(job_id) -> JobRecord | None` — same
    signatures as today, new behaviour

- [ ] **Step 1: Re-run the measurement this plan rests on**

Do not skip this. It is the evidence for the whole design, and the plan is a
hypothesis until you have your own number.

```bash
cd ~/ask-the-budget-az-worktrees/plan-c
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

Expected, within a few of these: `all: {'live': 7100, 'failed': 14,
'cancelled': 4}` and `older than 24h: {'live': 7100, 'failed': 13, ...}`.
**If `failed` older than 24 h is not the large majority of `failed`, stop and
tell Destin** — the design's justification has changed.

- [ ] **Step 2: Write the failing tests**

Create `tests/test_job_archive.py`. Every test uses a tmp data dir; nothing
here may touch the real corpus.

```python
"""Where a job file lives, and what that buys.

Spec T13 as amended 2026-08-13: the queue shows work, not history. Rather
than filter a 7,118-file directory on every poll, a job that reaches a
terminal SUCCESS state moves out of the way, so the main folder comes to
hold exactly what the queue shows. `failed` deliberately never moves.
"""
import json
import os
from pathlib import Path

import pytest

from ingest import jobs as J


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    # store.config.data_dir() caches nothing today, but jobs_dir() creates
    # directories as a side effect, so make the fixture explicit about which
    # tree it is building.
    (tmp_path / "jobs").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _job(**over):
    base = dict(
        doc_id="doc-1", title="T", corpus="budget", source_path="/x.pdf",
        source_sha256="abc", publisher="jlbc", doc_type="jlbc-approps-per-agency",
        fiscal_year=2026,
    )
    base.update(over)
    return J.new_job(**base)


def test_a_queued_job_lives_in_the_main_folder(data_dir):
    job = _job()
    path = J.save(job)
    assert path.parent == J.jobs_dir()
    assert path.parent.name == "jobs"


def test_reaching_live_moves_the_file_into_done(data_dir):
    job = _job()
    main = J.save(job)
    assert main.exists()

    for state in ("extracting", "chunking", "embedding", "writing", "live"):
        J.advance(job, state)

    assert not main.exists(), "the main-folder copy must not be left behind"
    assert (J.archive_dir() / f"{job.job_id}.json").exists()


def test_a_failed_job_NEVER_moves(data_dir):
    """The one rule spec T13 says not to relax.

    A failure that ages out of the folder the queue reads is a failure
    nobody will ever see. Measured 2026-08-13: 13 of the 14 failures in the
    live data dir are 12.6 days old, so any age-based scheme hides them.
    """
    job = _job()
    J.save(job)
    J.advance(job, "extracting")
    J.advance(job, "failed", error="boom")

    assert (J.jobs_dir() / f"{job.job_id}.json").exists()
    assert not (J.archive_dir() / f"{job.job_id}.json").exists()
    assert job.job_id in {j.job_id for j in J.load_active()}


def test_dismissing_a_failure_moves_it(data_dir):
    """Dismiss is `failed -> cancelled` (app/routes/jobs.py::cancel_job).

    T13 says a failure shows "until it is retried, cancelled or dismissed".
    Because `cancelled` is an archived state, that clause falls out of where
    the file lives rather than needing a rule to enforce it.
    """
    job = _job()
    J.save(job)
    J.advance(job, "failed", error="boom")
    J.advance(job, "cancelled")

    assert not (J.jobs_dir() / f"{job.job_id}.json").exists()
    assert (J.archive_dir() / f"{job.job_id}.json").exists()
    assert job.job_id not in {j.job_id for j in J.load_active()}


def test_retrying_a_failure_keeps_it_in_the_main_folder(data_dir):
    job = _job()
    J.save(job)
    J.advance(job, "failed", error="boom")
    J.advance(job, "queued")

    assert (J.jobs_dir() / f"{job.job_id}.json").exists()
    assert job.job_id in {j.job_id for j in J.load_active()}


def test_load_active_excludes_archived_and_load_all_includes_it(data_dir):
    done = _job(doc_id="done")
    J.save(done)
    for state in ("extracting", "chunking", "embedding", "writing", "live"):
        J.advance(done, state)
    waiting = _job(doc_id="waiting")
    J.save(waiting)

    assert {j.job_id for j in J.load_active()} == {waiting.job_id}
    assert {j.job_id for j in J.load_all()} == {waiting.job_id, done.job_id}


def test_load_job_finds_an_archived_job(data_dir):
    job = _job()
    J.save(job)
    for state in ("extracting", "chunking", "embedding", "writing", "live"):
        J.advance(job, state)
    found = J.load_job(job.job_id)
    assert found is not None and found.state == "live"


def test_a_job_in_BOTH_folders_is_returned_once(data_dir):
    """A crash between "write the new copy" and "remove the old" leaves a
    twin. That ordering is deliberate — the other order can lose the file —
    so the readers must tolerate the duplicate it can produce.
    """
    job = _job()
    J.save(job)
    stale_twin = J.jobs_dir() / f"{job.job_id}.json"
    for state in ("extracting", "chunking", "embedding", "writing", "live"):
        J.advance(job, state)
    stale_twin.write_text(json.dumps(job.to_json()), encoding="utf-8")

    ids = [j.job_id for j in J.load_all()]
    assert ids.count(job.job_id) == 1


def test_archived_count_opens_no_files(data_dir, monkeypatch):
    """The finished count feeds a line on a page that polls. Reading 7,100
    files to render one number is what this whole change exists to stop.
    """
    for i in range(3):
        job = _job(doc_id=f"d{i}")
        J.save(job)
        for state in ("extracting", "chunking", "embedding", "writing", "live"):
            J.advance(job, state)

    real_open = Path.read_text
    calls = []
    monkeypatch.setattr(
        Path, "read_text",
        lambda self, *a, **k: (calls.append(self), real_open(self, *a, **k))[1],
    )
    assert J.archived_count() == 3
    assert calls == [], f"archived_count opened {len(calls)} files"


def test_newest_archived_live_skips_cancelled(data_dir):
    """`last_ingest_at` on the admin health panel means "when did a document
    last finish successfully", so a dismissed failure must not answer it.
    """
    old = _job(doc_id="old")
    J.save(old)
    for state in ("extracting", "chunking", "embedding", "writing", "live"):
        J.advance(old, state)
    os.utime(J.archive_dir() / f"{old.job_id}.json", (1_000_000, 1_000_000))

    junk = _job(doc_id="junk")
    J.save(junk)
    J.advance(junk, "cancelled")

    newest = J.newest_archived_live()
    assert newest is not None and newest.doc_id == "old"
```

- [ ] **Step 3: Run them and watch them fail**

```bash
cd ~/ask-the-budget-az-worktrees/plan-c && uv run pytest tests/test_job_archive.py -q
```

Expected: failures — `AttributeError: module 'ingest.jobs' has no attribute
'archive_dir'` and friends.

- [ ] **Step 4: Write `ingest/archive.py`**

```python
"""Which folder a job file belongs in, and the one-time sweep that gets
7,100 existing files there.

Spec T13, as amended 2026-08-13. The queue must show outstanding work and
every failure regardless of age. Doing that as a FILTER means reading every
job file on every poll — measured at 7,118 files / 3.02 MB per refresh,
over an SMB share, on a page that polls. Doing it as a LOCATION means the
main folder already IS the answer and the readers get cheaper for free.

Why a subdirectory rather than encoding the state in the filename: this
queue is a directory of small JSON files specifically so that "a colleague
(or a future maintainer with no code access) can read the queue in Notepad"
(see ingest/jobs.py's module docstring). A folder named `done` says what it
holds. A filename suffix does not. Destin chose this shape on 2026-08-13.

Nothing here deletes anything, ever.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

# States whose files move out of the main folder. `failed` is deliberately
# NOT here and must never be added: spec T13 requires every failure to stay
# visible regardless of age, and 13 of the 14 failures in the live data dir
# on 2026-08-13 were 12.6 days old, so anything age-based hides them.
ARCHIVED_STATES = frozenset({"live", "cancelled"})

ARCHIVE_DIRNAME = "done"


def dir_for_state(main: Path, state: str) -> Path:
    return (main / ARCHIVE_DIRNAME) if state in ARCHIVED_STATES else main


def unlink_with_retry(path: Path, *, attempts: int = 20) -> bool:
    """Remove a file another machine may have open. Never raises.

    Same hazard as ingest/jobs.py::_replace_with_retry: Windows and SMB
    refuse to touch a file while another handle is open, and the queue page
    polls these files from other PCs every couple of seconds. Returns
    whether the file is gone.

    A failure here is benign BY DESIGN. The new copy is already written, so
    the worst case is the same job appearing in both folders — which the
    readers dedupe — rather than a job file lost. That is why the caller
    writes first and removes second, and never the other way round.
    """
    for attempt in range(attempts):
        try:
            path.unlink(missing_ok=True)
            return True
        except PermissionError:
            if attempt == attempts - 1:
                return False
            time.sleep(0.02)
        except OSError:
            return False
    return False


def sweep(main: Path, *, read, limit: int | None = None) -> int:
    """Move already-finished job files into `done/`. Idempotent.

    Runs once at startup. The first run on the office share has ~7,100 files
    to move; every later run reads only what is left in the main folder,
    which by then is outstanding work plus failures — tens of files.

    `read` is injected (`ingest.jobs._read`) rather than imported to keep
    this module free of a circular import back into jobs.py.

    Two machines sweeping at once is safe and expected: os.replace to the
    same destination is last-writer-wins on identical bytes, and a file
    another machine already moved simply is not there any more.
    """
    archive = main / ARCHIVE_DIRNAME
    archive.mkdir(parents=True, exist_ok=True)
    moved = 0
    for path in sorted(main.glob("*.json")):
        if limit is not None and moved >= limit:
            break
        job = read(path)
        if job is None or job.state not in ARCHIVED_STATES:
            continue
        try:
            os.replace(path, archive / path.name)
            moved += 1
        except FileNotFoundError:
            continue          # another machine got there first
        except OSError:
            continue          # locked right now; the next sweep gets it
    return moved
```

- [ ] **Step 5: Wire it into `ingest/jobs.py`**

Add the import near the top, beside the existing `from store.config import
data_dir`:

```python
from ingest.archive import (
    ARCHIVE_DIRNAME,
    ARCHIVED_STATES,
    dir_for_state,
    unlink_with_retry,
)
```

Add below `jobs_dir()`:

```python
def archive_dir() -> Path:
    """Where finished jobs live. Inside `jobs/`, so one folder holds the
    whole audit trail and a person looking for "the queue" finds both.

    Nested rather than a sibling because `jobs_dir().glob("*.json")` does
    not descend — the main-folder listing is naturally unaffected by
    however many files pile up in here.
    """
    path = jobs_dir() / ARCHIVE_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path
```

Replace the body of `save()` (keep its existing docstring and the WHY
comment about pid+tid, both still true) so the destination follows the
state, and the stale twin is removed **after** the new copy is safely
written:

```python
def save(job: JobRecord) -> Path:
    ...existing docstring...
    main = jobs_dir()
    target = dir_for_state(main, job.state)
    if target is not main:
        target.mkdir(parents=True, exist_ok=True)
    path = target / f"{job.job_id}.json"
    # ...existing pid+tid WHY comment, unchanged...
    tmp = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.json.tmp")
    tmp.write_text(json.dumps(job.to_json(), indent=2), encoding="utf-8")
    _replace_with_retry(tmp, path)
    # A job only ever moves ONE way — into `done/` — because the only
    # transitions into an archived state come from the main folder and
    # nothing ever leaves `live` or `cancelled`. So this is the only twin
    # that can exist, and it is removed only after the new copy landed:
    # a crash here costs a duplicate the readers dedupe, where the other
    # order would cost the file.
    if target is not main:
        unlink_with_retry(main / f"{job.job_id}.json")
    return path
```

Replace the three readers:

```python
def load_job(job_id: str) -> JobRecord | None:
    """Outstanding work first, then the archive — a job id from a URL
    (`/api/jobs/{id}/retry`) may name either."""
    name = f"{_validated_job_id(job_id)}.json"
    return _read(jobs_dir() / name) or _read(archive_dir() / name)


def load_active() -> list[JobRecord]:
    """Outstanding work and every failure, newest first.

    The main folder holds exactly {non-terminal} ∪ {failed} — see
    ingest/archive.py — so this needs no state filter of its own, and
    cannot drift out of step with one.
    """
    return _sorted(_read_dir(jobs_dir()))


def load_all() -> list[JobRecord]:
    """Every job ever, newest first — outstanding work plus the archive.

    Deliberately unchanged in MEANING. Callers that want only outstanding
    work ask for `load_active()`; this stays the honest "everything", which
    is what the audit trail and the queue's "view all" need.

    Unreadable files are skipped rather than raised: one corrupt job must
    not blank the queue page for everyone.
    """
    by_id = {j.job_id: j for j in _read_dir(jobs_dir())}
    # The archive wins a tie: a job present in both folders crashed between
    # the write and the unlink, so the archived copy is the later write.
    by_id.update({j.job_id: j for j in _read_dir(archive_dir())})
    return _sorted(by_id.values())


def archived_count() -> int:
    """How many jobs have finished. A directory listing — opens no files.

    Rendering this number by reading 7,100 job files is precisely what
    spec T13 exists to stop, so it must stay a listing.
    """
    try:
        return sum(1 for _ in archive_dir().glob("*.json"))
    except OSError:
        return 0


# How many archived files to open looking for the newest successful ingest.
# The archive is written newest-last, so in practice the answer is the first
# entry; the cap is what stops a pathological archive (a long run of
# dismissed failures) turning one admin panel into a full scan.
_NEWEST_LIVE_SCAN_CAP = 50


def newest_archived_live() -> JobRecord | None:
    """The most recently finished successful ingest, or None.

    Feeds `last_ingest_at` on the admin health panel. Sorted by file mtime
    rather than by `updated_at` because mtime is available from the
    directory entry, so the common case opens exactly one file.
    `cancelled` jobs are skipped — a dismissed failure is not an ingest.
    """
    try:
        entries = sorted(
            archive_dir().glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return None
    for path in entries[:_NEWEST_LIVE_SCAN_CAP]:
        job = _read(path)
        if job is not None and job.state == "live":
            return job
    return None


def _read_dir(path: Path) -> list[JobRecord]:
    try:
        return [j for j in (_read(p) for p in path.glob("*.json")) if j is not None]
    except OSError:
        return []


def _sorted(jobs) -> list[JobRecord]:
    return sorted(jobs, key=lambda j: (j.created_at, j.job_id), reverse=True)
```

And point `resumable()` at the cheaper loader — its filter already excludes
every archived state, so this is equivalent by construction:

```python
    live = [
        j for j in load_active()          # was load_all()
        if j.machine == me and j.state not in TERMINAL_STATES and j.state != "queued"
    ]
```

- [ ] **Step 6: Run the tests**

```bash
cd ~/ask-the-budget-az-worktrees/plan-c && uv run pytest tests/test_job_archive.py -q
```

Expected: 10 passed.

- [ ] **Step 7: Verify the guards by mutation, in place**

For each, break the named line **in the real file**, run, confirm RED,
then restore with a targeted edit (never `git checkout`):

| mutation | must turn RED |
|---|---|
| add `"failed"` to `ARCHIVED_STATES` | `test_a_failed_job_NEVER_moves` |
| in `save()`, drop the `unlink_with_retry` call | `test_reaching_live_moves_the_file_into_done` |
| in `load_all()`, use a list instead of the dict | `test_a_job_in_BOTH_folders_is_returned_once` |
| in `newest_archived_live()`, drop the `state == "live"` check | `test_newest_archived_live_skips_cancelled` |
| in `archived_count()`, read each file | `test_archived_count_opens_no_files` |

- [ ] **Step 8: Run the whole suite**

```bash
cd ~/ask-the-budget-az-worktrees/plan-c && uv run pytest -q 2>&1 | tail -5
```

Expected: **2824 + 10 = 2834 passed, 5 skipped**, or a clear list of
existing tests that assert the old single-folder layout. Fix those by
updating what they assert, not by weakening the new behaviour — and read
each one to check it was not passing vacuously before.

- [ ] **Step 9: Commit**

```bash
git add ingest/archive.py ingest/jobs.py tests/test_job_archive.py
git commit -m "feat(T13): finished jobs move to jobs/done/, failures never do"
```

---

## Task 2: Sweep the 7,100 files already on disk

**Files:**
- Modify: `app/main.py` (the existing `_lifespan` handler)
- Test: `tests/test_job_archive.py` (append)

**Interfaces:**
- Consumes: `ingest.archive.sweep`, `ingest.jobs.jobs_dir`, `ingest.jobs._read`.
- Produces: `ingest.jobs.sweep_archive() -> int`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_job_archive.py`)

```python
def test_sweep_moves_existing_finished_files_and_leaves_the_rest(data_dir):
    """The 7,100 files already on disk when this ships.

    Without this, every one of them stays in the main folder forever and the
    change accomplishes nothing on the machine that matters.
    """
    finished, failed, waiting = _job(doc_id="a"), _job(doc_id="b"), _job(doc_id="c")
    for job, state in ((finished, "live"), (failed, "failed")):
        job.state = state           # write it straight into the OLD layout
    for job in (finished, failed, waiting):
        path = J.jobs_dir() / f"{job.job_id}.json"
        path.write_text(json.dumps(job.to_json()), encoding="utf-8")

    assert J.sweep_archive() == 1
    assert (J.archive_dir() / f"{finished.job_id}.json").exists()
    assert (J.jobs_dir() / f"{failed.job_id}.json").exists()
    assert (J.jobs_dir() / f"{waiting.job_id}.json").exists()


def test_sweep_is_idempotent(data_dir):
    job = _job()
    job.state = "live"
    (J.jobs_dir() / f"{job.job_id}.json").write_text(
        json.dumps(job.to_json()), encoding="utf-8")
    assert J.sweep_archive() == 1
    assert J.sweep_archive() == 0
    assert len(J.load_all()) == 1


def test_sweep_survives_a_corrupt_file(data_dir):
    (J.jobs_dir() / "20260101T000000Z-deadbeef.json").write_text("{ not json",
                                                                 encoding="utf-8")
    job = _job()
    job.state = "live"
    (J.jobs_dir() / f"{job.job_id}.json").write_text(
        json.dumps(job.to_json()), encoding="utf-8")
    assert J.sweep_archive() == 1
```

- [ ] **Step 2: Run and watch fail**

```bash
uv run pytest tests/test_job_archive.py -q -k sweep
```
Expected: `AttributeError: ... has no attribute 'sweep_archive'`.

- [ ] **Step 3: Add `sweep_archive()` to `ingest/jobs.py`**

```python
def sweep_archive(*, limit: int | None = None) -> int:
    """Move already-finished job files into `done/`. Returns how many moved.

    Called once per process from the app's lifespan handler. The first run
    against the office share has ~7,100 files to move and takes seconds;
    afterwards the main folder holds only outstanding work and failures, so
    it is a listing of tens of files.
    """
    return _sweep(jobs_dir(), read=_read, limit=limit)
```

with `from ingest.archive import sweep as _sweep` added to the existing
import block.

- [ ] **Step 4: Run**

```bash
uv run pytest tests/test_job_archive.py -q
```
Expected: 13 passed.

- [ ] **Step 5: Call it from the lifespan handler**

In `app/main.py::_lifespan`, beside the existing `ingest.worker.ensure_started`
call, in its own `try`:

```python
    # WHY here and not in create_app(): building an app object (which every
    # route test does) must not touch the share or move files — only SERVING
    # should. Same reasoning as the ingest worker beside it, which was moved
    # here for exactly this after it was found starting threads in tests.
    #
    # WHY a thread: the first sweep on the office share moves ~7,100 files,
    # and the launcher opens a browser tab the moment the port answers. A
    # few seconds of blocked startup reads as "the app is broken".
    #
    # A failure is logged and swallowed: an unsweepable jobs folder means the
    # queue shows some finished rows it need not, which is untidy, not broken.
    try:
        threading.Thread(
            target=_sweep_archive_quietly, name="jlbc-archive-sweep", daemon=True
        ).start()
    except Exception as exc:  # noqa: BLE001
        print(f"[jlbc] could not start the job-archive sweep: {exc}", file=sys.stderr)
```

and beside it:

```python
def _sweep_archive_quietly() -> None:
    try:
        from ingest.jobs import sweep_archive

        moved = sweep_archive()
        if moved:
            print(f"[jlbc] moved {moved} finished job files into jobs/done/",
                  file=sys.stderr)
    except Exception as exc:  # noqa: BLE001
        print(f"[jlbc] job-archive sweep failed: {exc}", file=sys.stderr)
```

Check the existing imports at the top of `app/main.py` for `threading` and
`sys` and add whichever is missing.

- [ ] **Step 6: Prove it against a COPY of the real jobs folder**

Never against the live one.

```bash
cd ~/ask-the-budget-az-worktrees/plan-c
rm -rf /tmp/sweep-probe && mkdir -p /tmp/sweep-probe
cp -r ~/YouCoded/Projects/ask-the-budget-az-dev/data/insight-data/jobs /tmp/sweep-probe/
JLBC_DATA_DIR=/tmp/sweep-probe uv run python -c "
import time; from ingest.jobs import sweep_archive, load_active, load_all, archived_count
t=time.time(); moved=sweep_archive(); el=time.time()-t
print(f'moved {moved} in {el:.1f}s')
print('active now:', len(load_active()), '| archived:', archived_count(), '| all:', len(load_all()))
print('states left in the main folder:', sorted({j.state for j in load_active()}))
"
```

Expected, and **write the real numbers into the commit message**: ~7,104
moved, **active ≈ 14**, archived ≈ 7,104, all ≈ 7,118, and the states left
are `['failed']` (plus any non-terminal). If anything other than `failed`
and non-terminal states remains, stop — `ARCHIVED_STATES` is wrong.

- [ ] **Step 7: Commit**

```bash
git add ingest/jobs.py app/main.py tests/test_job_archive.py
git commit -m "feat(T13): one-time sweep moves existing finished jobs into done/"
```

---

## Task 3: Point all seven `load_all()` callers at the right loader

**This is the highest-risk task in the plan.** Four callers are equivalent by
construction, two are a judgement call, and one is a genuine behaviour change
that a naive swap gets wrong. A duplicate check left on the wrong loader
starts silently re-ingesting documents — a correctness bug wearing a
performance change's clothes.

**Files:**
- Modify: `ingest/worker.py:1708`, `app/routes/upload.py:303`,
  `app/routes/books.py:118`, `app/routes/admin.py:754`, `app/routes/admin.py:905`
- Test: `tests/test_job_loaders.py`

**Interfaces:**
- Consumes: `load_active`, `load_all`, `newest_archived_live` from Task 1.
- Produces: nothing new.

**The decision table. Put this in the commit message.**

| caller | today's filter | loader | why |
|---|---|---|---|
| `ingest/worker.py::_candidates` | `state == "queued"` | `load_active` | `queued` is never archived, so equivalent by construction. This is the poll loop — it read all 7,118 files every pass |
| `app/routes/upload.py` dedupe | `state not in TERMINAL_STATES` | `load_active` | Archived jobs are all terminal, so equivalent by construction. **The `documents.json` check above it is what catches finished documents — this loop only ever meant "already queued"** |
| `app/routes/books.py` pending | `state not in TERMINAL_STATES` | `load_active` | Same construction as above |
| `ingest/jobs.py::resumable` | non-terminal, this machine | `load_active` | Done in Task 1 |
| `app/routes/admin.py::get_attention` | `failed and held_out` | `load_active` | `failed` never leaves the main folder — that is the whole design |
| `app/routes/admin.py::_queue_summary` counts | queued / running / failed | `load_active` | None of the three counts an archived state |
| `app/routes/admin.py::_queue_summary` `last_live` | newest `live` job | **`newest_archived_live()`** | ⚠ **NOT `load_active`.** Every `live` job is archived, so `load_active` returns `None` forever and the admin panel would report "no ingest has ever finished" |

- [ ] **Step 1: Write the failing tests**

Create `tests/test_job_loaders.py`.

```python
"""Each `load_all()` caller asks for the set it actually means.

Spec T13 moved finished jobs to `jobs/done/`. Every caller then had to be
re-read and re-pointed. Four are equivalent by construction (their filters
already excluded every archived state); `last_ingest_at` is the one that
genuinely changes, and a naive swap breaks it silently — which is why it
has a test of its own.
"""
import json

import pytest

from ingest import jobs as J


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    (tmp_path / "jobs").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _finished(doc_id, sha, url=None):
    job = J.new_job(
        doc_id=doc_id, title="T", corpus="budget", source_path="/x.pdf",
        source_sha256=sha, publisher="jlbc", doc_type="jlbc-approps-per-agency",
        fiscal_year=2026, source_url=url,
    )
    J.save(job)
    for state in ("extracting", "chunking", "embedding", "writing", "live"):
        J.advance(job, state)
    return job


def test_the_admin_panel_still_reports_the_last_finished_ingest(data_dir):
    """The regression a naive load_active() swap would have shipped.

    Every `live` job is archived, so a summary built only from the main
    folder reports `last_ingest_at: None` forever — the admin health panel
    saying nothing has ever been ingested on a corpus of 7,434 documents.
    """
    from app.routes.admin import _queue_summary

    job = _finished("d1", "sha1")
    summary, last_live = _queue_summary()
    assert last_live == job.updated_at
    assert summary["queued"] == 0 and summary["failed"] == 0


def test_the_queue_summary_still_counts_failures(data_dir):
    from app.routes.admin import _queue_summary

    job = J.new_job(
        doc_id="d", title="T", corpus="budget", source_path="/x.pdf",
        source_sha256="s", publisher="jlbc", doc_type="jlbc-approps-per-agency",
        fiscal_year=2026,
    )
    J.save(job)
    J.advance(job, "failed", error="boom")
    summary, _ = _queue_summary()
    assert summary["failed"] == 1


def test_a_finished_upload_is_still_recognised_as_a_duplicate(data_dir, monkeypatch):
    """The correctness trap in this task.

    The job loop only ever meant "already queued" — `documents.json` is what
    catches an already-INGESTED file. This pins that the two together still
    refuse a re-upload once the job has been archived.
    """
    from app.routes import upload as U

    _finished("doc-x", "sha-dup")
    monkeypatch.setattr(
        U, "_documents",
        lambda: {"doc-x": {"source_sha256": "sha-dup", "ingested_at": "2026-08-13"}},
    )
    assert U._duplicate_of("sha-dup") is not None


def test_book_ingest_still_skips_a_url_that_is_merely_QUEUED(data_dir):
    """The book route's `pending` set means "queued but not yet in
    documents.json". An archived job's URL is in documents.json, so it is
    the other check's job — but a still-queued one is only knowable here.
    """
    job = J.new_job(
        doc_id="d", title="T", corpus="budget", source_path="/x.pdf",
        source_sha256="s", publisher="jlbc", doc_type="jlbc-approps-per-agency",
        fiscal_year=2026, source_url="https://www.azjlbc.gov/27ar/508.pdf",
    )
    J.save(job)
    pending = {j.source_url for j in J.load_active()
               if j.state not in J.TERMINAL_STATES and j.source_url}
    assert "https://www.azjlbc.gov/27ar/508.pdf" in pending


def test_the_worker_still_finds_queued_work_and_ignores_the_archive(data_dir):
    _finished("done", "s1")
    waiting = J.new_job(
        doc_id="waiting", title="T", corpus="budget", source_path="/x.pdf",
        source_sha256="s2", publisher="jlbc", doc_type="jlbc-approps-per-agency",
        fiscal_year=2026,
    )
    J.save(waiting)
    queued = [j for j in reversed(J.load_active()) if j.state == "queued"]
    assert [j.doc_id for j in queued] == ["waiting"]
```

- [ ] **Step 2: Run and watch `test_the_admin_panel_...` fail for the RIGHT reason**

```bash
uv run pytest tests/test_job_loaders.py -q
```

Before any edit, these should mostly PASS (the code still reads both folders
via `load_all`). **That is expected and is the point** — they are here to
catch the *swap*, not the current state. Confirm the file is green now, then
make the edits below and confirm it is still green. If
`test_the_admin_panel_still_reports_the_last_finished_ingest` fails at this
point, Task 1 broke something.

- [ ] **Step 3: The four equivalent-by-construction swaps**

`ingest/worker.py:1708` — one line, and the only edit in a file the peer
session owns:

```python
        # load_active(), not load_all(): `queued` is never an archived state,
        # so this is the same set — but load_all() reads the whole 7,118-file
        # archive on every poll of this loop. Spec T13.
        queued = [j for j in reversed(load_active()) if j.state == "queued"]
```

`app/routes/upload.py:303`:

```python
    # load_active(): every archived job is terminal, so the `state not in
    # TERMINAL_STATES` filter below already excluded all of them — same set,
    # without reading the archive. An already-INGESTED file is caught by the
    # documents.json loop above, not by this one.
    for job in load_active():
```

`app/routes/books.py:118`:

```python
    pending = {
        # load_active(): same set as load_all() under this filter, since
        # every archived job is terminal. A URL that has finished is in
        # `known` (documents.json) above.
        job.source_url for job in load_active()
        if job.state not in TERMINAL_STATES and job.source_url
    }
```

Update each file's `from ingest.jobs import ...` line accordingly.

- [ ] **Step 4: The two admin callers, including the one that changes**

In `app/routes/admin.py::get_attention` (~line 905), swap the import and
call to `load_active`, with:

```python
        # load_active(): `failed` never leaves the main folder — that is
        # exactly what spec T13's storage shape guarantees — so this panel
        # sees every held-back document without reading the archive.
        from ingest.jobs import load_active

        jobs = load_active()
```

In `app/routes/admin.py::_queue_summary` (~line 750), the counts move to
`load_active()` and `last_live` gets its own source:

```python
    summary = {"queued": 0, "running": 0, "failed": 0}
    try:
        from ingest.jobs import load_active, newest_archived_live

        jobs = load_active()
    except Exception:  # noqa: BLE001 — unreadable jobs dir
        return summary, None

    for job in jobs:
        if job.state == "queued":
            summary["queued"] += 1
        elif job.state == "failed":
            summary["failed"] += 1
        elif job.state not in _TERMINAL_JOB_STATES:
            summary["running"] += 1

    # NOT from `jobs` above. Every `live` job is archived by spec T13, so a
    # summary built from the main folder alone would report "nothing has ever
    # finished" on a corpus of 7,434 documents — which is what this panel
    # exists to reassure an admin about. `newest_archived_live()` reads the
    # archive's newest entries by mtime and opens one file in the common case.
    try:
        newest = newest_archived_live()
    except Exception:  # noqa: BLE001
        newest = None
    return summary, (newest.updated_at if newest else None)
```

- [ ] **Step 5: Run the loader tests, then the whole suite**

```bash
uv run pytest tests/test_job_loaders.py -q
uv run pytest -q 2>&1 | tail -5
```
Expected: 5 passed, then **2839 passed, 5 skipped**.

- [ ] **Step 6: Verify by mutation, in place**

| mutation | must turn RED |
|---|---|
| `_queue_summary` returns `None` for `last_live` | `test_the_admin_panel_still_reports_the_last_finished_ingest` |
| `get_attention` uses `load_all()` | nothing — and that is CORRECT (it is a performance change, not a behaviour one). Note it rather than inventing a test |
| `upload.py` drops the `documents.json` loop | `test_a_finished_upload_is_still_recognised_as_a_duplicate` |

- [ ] **Step 7: Commit** — put the decision table in the message.

```bash
git add ingest/worker.py app/routes/upload.py app/routes/books.py \
        app/routes/admin.py tests/test_job_loaders.py
git commit -m "feat(T13): each job loader asks for the set it means"
```

---

## Task 4: `GET /api/jobs` returns work, plus a count of what finished

**Files:**
- Modify: `app/routes/jobs.py`
- Test: `tests/test_jobs_route.py` (create if absent; check first with
  `ls tests/ | grep -i job`)

**Interfaces:**
- Consumes: `load_active`, `load_all`, `archived_count`.
- Produces the API contract Task 5 renders:
  ```
  GET /api/jobs        -> {"jobs": [JobView...], "finished_count": int, "showing": "active"}
  GET /api/jobs?all=1  -> {"jobs": [JobView...], "finished_count": int, "showing": "all"}
  ```
  `JobView` itself is unchanged — the frozen contract in
  `JobRecord.view()` is not touched.

- [ ] **Step 1: Write the failing tests**

```python
def test_the_queue_returns_work_not_history(tmp_path, monkeypatch):
    """Spec T13. Measured before this change: 7,118 jobs / 3.02 MB per poll,
    of which 14 needed attention.
    """
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    # ...create one live job and one failed job via ingest.jobs...
    client = TestClient(create_app())
    body = client.get("/api/jobs").json()
    assert [j["state"] for j in body["jobs"]] == ["failed"]
    assert body["finished_count"] == 1
    assert body["showing"] == "active"


def test_all_1_returns_everything(tmp_path, monkeypatch):
    ...
    body = client.get("/api/jobs?all=1").json()
    assert {j["state"] for j in body["jobs"]} == {"failed", "live"}
    assert body["showing"] == "all"


def test_a_failed_job_of_any_age_is_still_returned(tmp_path, monkeypatch):
    """The one rule not to relax. Backdate the file 30 days and check."""
    ...
    os.utime(path, (time.time() - 30 * 86400,) * 2)
    assert [j["state"] for j in client.get("/api/jobs").json()["jobs"]] == ["failed"]
```

Write these out fully against the fixtures already used by the neighbouring
route tests — copy their `create_app()` + `TestClient` setup rather than
inventing a second style.

- [ ] **Step 2: Run, watch fail** (`finished_count` missing → `KeyError`).

- [ ] **Step 3: Implement**

```python
@router.get("/api/jobs")
def list_jobs(all: bool = False):
    """Outstanding work by default; everything on request.

    Spec T13: the queue shows work, not history. The default set is whatever
    is in the main jobs folder — every unfinished job plus every failure,
    regardless of age — because finished jobs have moved to `jobs/done/`.
    There is no age window and no state filter here on purpose: an age
    window with an exception clause is what the amendment to T13 removed,
    after measuring that a 24-hour window hid 13 of 14 live failures.

    `finished_count` is a directory listing, not 7,100 file reads, and is
    what lets the page offer "view all" without pretending the archive is
    not there.
    """
    jobs = load_all() if all else load_active()
    return {
        "jobs": [job.view() for job in jobs],
        "finished_count": archived_count(),
        "showing": "all" if all else "active",
    }
```

- [ ] **Step 4: Run the tests.** Expected: 3 passed.

- [ ] **Step 5: Mutation check** — make `list_jobs` always call `load_all()`;
`test_the_queue_returns_work_not_history` must go RED.

- [ ] **Step 6: Measure the real payload.** This is a required number.

```bash
cd ~/ask-the-budget-az-worktrees/plan-c
JLBC_DATA_DIR=/tmp/sweep-probe uv run python -c "
import json
from fastapi.testclient import TestClient
from app.main import create_app
c = TestClient(create_app(ingest_worker=None))
for url in ('/api/jobs', '/api/jobs?all=1'):
    r = c.get(url)
    print(f'{url:20} {len(r.content)/1e6:.3f} MB  rows={len(r.json()[\"jobs\"])}')
"
```

Expected direction: `/api/jobs` **far** below the 3.02 MB baseline (tens of
rows), `?all=1` roughly at it. **Record both numbers in the commit message
and in STATUS.md** — the entire justification for T13 is a number, and a
change that does not report its own number has not been measured.

- [ ] **Step 7: Commit.**

---

## Task 5: The queue shows work

**Files:**
- Create: `webapp/src/pages/upload/QueuePanel.tsx`, `.test.tsx`
- Modify: `webapp/src/pages/Upload.tsx`, `webapp/src/api.ts`

**Interfaces:**
- Consumes: the Task 4 contract.
- Produces: `<QueuePanel />`, self-contained (does its own polling).

**Behaviour:**
1. Renders the rows `/api/jobs` returns — no client-side age filter. The
   server decides; a second filter here is a second place to get it wrong.
2. **Rows this browser watched finish stay visible for the session.** A row
   vanishing the instant a document succeeds is abrupt for the person who
   just uploaded it and is watching — this is the only thing the deleted
   24-hour window was really doing. Hold the ids seen in a non-terminal
   state in a `useRef<Set<string>>`, keep rendering them from the last
   response that carried them, and let them go on reload.
3. **The finished line:** `7,104 documents finished — view all`, where "view
   all" re-fetches with `?all=1` and the panel says it is showing everything.
   Never invent the number client-side.
4. **When there is no work and nothing has failed, render nothing but that
   line.** `NeedsAttention.tsx` sets the house rule directly: a box on screen
   every day teaches people to scroll past it. Do not add "0 jobs running".

- [ ] **Step 1: Write the failing specs** in `QueuePanel.test.tsx`:
  `renders a failed job of any age`, `does not render finished jobs`,
  `keeps a row that finished while we were watching`,
  `"view all" refetches with all=1 and says so`,
  `renders only the finished line when there is no work`.
  Mock `fetch`; follow the existing `Upload.test.tsx` mocking style.
- [ ] **Step 2: Run, watch fail.**
- [ ] **Step 3: Write `QueuePanel.tsx`**, moving the queue JSX out of
  `Upload.tsx` unchanged where possible so the diff shows intent.
- [ ] **Step 4: Add the `api.ts` types** — `JobsResponse { jobs: JobView[];
  finished_count: number; showing: "active" | "all" }`.
- [ ] **Step 5: Render it from `Upload.tsx`.**
- [ ] **Step 6:** `npx vitest run` and `npx tsc -b`. Expected: 913 + ~5
  passing, tsc exit 0.
- [ ] **Step 7: Mutation check** — delete the watched-ids `useRef` logic;
  `keeps a row that finished while we were watching` must go RED.
- [ ] **Step 8: Commit.**

---

## Task 6: Which book editions are missing

**Files:**
- Create: `app/routes/books_missing.py`, `tests/test_books_missing.py`
- Modify: `app/main.py` (mount the router)

**Interfaces:**
- Produces:
  ```
  GET /api/books/missing[?refresh=1] -> {
    checked_at: str | null,          # ISO, when the network check last ran
    online: bool,                    # did the last check reach azjlbc.gov
    reason: str | null,              # why not, in plain English
    missing:     [{family, fiscal_year, document_count: int | null, source: "catalog"|"probed"}],
    present:     [{family, fiscal_year}],
    unavailable: [{family, fiscal_year, era_note}],
  }
  ```
- Also produces `corpus_editions() -> dict[str, set[int]]`, importable for
  tests and reused by Task 7's copy.

**The URL→edition map, from the measured table at the top of this plan.**
Four patterns, not two:

```python
# JLBC has used four directory conventions for its books. Counted across the
# whole live corpus on 2026-08-13: {yy}ar 1,782 docs (FY2013-2026), {yy}app
# 1,294 (FY2005-2012), {yy}baseline 1,866 (FY2013-2027), {yy}book1 141
# (FY2012 only). A two-pattern regex misses 1,435 documents and reports the
# newest approps edition as FY2013 instead of FY2026 — which would offer
# Destin thirteen books he already has.
#
# Confirmed by title, not by guess: 12book1/353.pdf is "CAPITAL OUTLAY
# ESTIMATES - FY 2012 Baseline" and 12app/260.pdf is "Capital Outlay - FY
# 2012 Appropriations Report".
_EDITION_DIR = re.compile(r"azjlbc\.gov/(\d{2})(ar|app|baseline|book1)/", re.I)
_FAMILY_OF = {"ar": "approps", "app": "approps",
              "baseline": "baseline", "book1": "baseline"}
```

Read `source_url` from `store.documents` (the one documents.json reader —
do not add a second) and never from the doc_id: 21 documents in this corpus
carry a family in their id that contradicts their own title, and `source_url`
is the only independent evidence (STATUS.md, Budget Documents section).

**The check:**
1. `corpus_editions()` → `{"approps": {2005..2026}, "baseline": {2012..2027}}`.
2. For each family, `plan_edition(family, newest + 1)` and `+ 2`. Catalog-first,
   so a hit costs nothing; a miss climbs the HEAD ladder. `DiscoveryError`
   means "not published yet" — a normal answer, not an error.
3. Plus any catalog edition marked `ingestable` whose year is not in the
   corpus.
4. Catalog editions marked not `ingestable` go in `unavailable` with their
   `era_note`, and **carry no Add** (spec T10).

**Cache:** write the whole response to `<data_dir>/book-check.json` with
`checked_at`. Serve it without touching the network unless `?refresh=1` or it
is older than 12 h. A network failure serves the last good answer with
`online: false` and a reason — this app is offline-capable and was verified
cold-starting with WiFi off; a book panel that hangs on a dead network is a
regression against that.

- [ ] **Step 1: Write the failing tests** — `corpus_editions` parses all four
  patterns (use real URLs from the table); `12book1` reads as baseline FY2012;
  a probed year that raises `DiscoveryError` is absent from `missing` rather
  than being an error; a non-ingestable catalog edition appears in
  `unavailable` and never in `missing`; a probe exception yields
  `online: false` with the cached body intact. Inject a fake prober; **no test
  may touch the network.**
- [ ] **Step 2: Run, watch fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run.**
- [ ] **Step 5: Check it against the real corpus** (read-only, one network
  round):
  ```bash
  JLBC_DATA_DIR=~/YouCoded/Projects/ask-the-budget-az-dev/data/insight-data \
    uv run python -c "
from app.routes.books_missing import corpus_editions
e = corpus_editions()
print({k: (min(v), max(v), len(v)) for k, v in e.items()})"
  ```
  Expected: `approps (2005, 2026, 22)`, `baseline (2012, 2027, 16)`.
  **If either newest year is below 2026/2027, the regex is wrong** — that is
  the whole failure mode this task is guarding against.
- [ ] **Step 6: Mutation check** — drop `app|book1` from the regex; the
  four-pattern test must go RED.
- [ ] **Step 7: Commit.**

---

## Task 7: The book panel offers only what is missing

**Files:**
- Create: `webapp/src/pages/upload/BookPanel.tsx`, `.test.tsx`
- Modify: `webapp/src/pages/Upload.tsx`, `webapp/src/api.ts`

Renders the spec's shape:

```
Add a JLBC book
Checking azjlbc.gov for editions you don't have…

  FY 2027 Appropriations Report — not in your corpus        [ Add ]

Everything else JLBC publishes is already here.
Need an older edition?  [ Choose a specific year ]
```

**Three properties this must have** (spec T10, verbatim):
- Editions already in the corpus are **marked as such, or omitted**.
- Non-ingestable editions are **not selectable** — greyed, with their
  `era_note` shown, and no Add button.
- A specific year can still be requested by hand, reaching the probe ladder.

Plus, from the check above: show `checked_at` as "Checked 3 hours ago —
[Check again]", and when `online` is false say so in the server's own words
rather than spinning.

- [ ] **Step 1: Write the failing specs** — a missing edition renders an Add
  button; an edition in `present` renders no Add; an `unavailable` edition
  renders its `era_note` and **no Add** (assert the button is absent, not
  merely disabled); "everything else is already here" appears when `missing`
  is empty; `online: false` renders the reason and not a spinner.
- [ ] **Step 2: Run, watch fail.**
- [ ] **Step 3: Implement**, moving the existing picker's specific-year path
  into the "Choose a specific year" control rather than rewriting it.
- [ ] **Step 4:** `npx vitest run`, `npx tsc -b`.
- [ ] **Step 5: Mutation check** — render Add for `unavailable` rows; that
  spec must go RED.
- [ ] **Step 6: Commit.**

---

## Task 8: Gates, the browser pass, and the record

- [ ] **Step 1: Sync with master and re-run everything.**

```bash
cd ~/ask-the-budget-az-worktrees/plan-c
git fetch origin && git rebase origin/master
uv run pytest -q 2>&1 | tail -3
cd webapp && npx vitest run 2>&1 | tail -4 && npx tsc -b; echo "tsc: $?"
```
Expected: pytest ≥ 2839 / 5 skipped, vitest ≥ 918, tsc 0. **State the real
numbers.**

- [ ] **Step 2: No eval, and say why in the PR.** Nothing under `retrieval/`,
  `chunking/`, `citation/` or `harness/system-prompt.md` is touched. `ingest/`
  is touched, but only where a job file lives and which loader a caller
  uses — the eval calls `retrieve()` and cannot observe any of it. Do not run
  it and do not skip the sentence.

- [ ] **Step 3: The browser pass. Destin does this before merge.** Build and
  run:
  ```bash
  cd webapp && npm run build && cd ..
  JLBC_DATA_DIR=~/YouCoded/Projects/ask-the-budget-az-dev/data/insight-data \
    uv run uvicorn app.main:create_app --factory --port 9301
  ```
  ⚠ `uvicorn` runs without `--reload`; **Python changes need a restart** —
  only the SPA picks up a rebuild. Several rounds of testing on the citation
  work measured a stale build this way.

  Checklist to walk with him:
  1. Upload page: the queue shows a handful of rows, not thousands, and the
     finished line states the real number.
  2. "View all" shows everything and says it is showing everything.
  3. A failed row is present and is 12 days old.
  4. Upload something small; watch its row survive the moment it turns live.
  5. The book panel offers **FY 2027 Appropriations Report** and nothing that
     is already in the corpus.
  6. A non-ingestable edition shows its `era_note` and has no Add button.
  7. Turn WiFi off, reload: the panel says it could not reach azjlbc.gov and
     shows the cached answer — it does not hang.

- [ ] **Step 4: Update `STATUS.md`** with a Plan C section: both measurements
  (payload before/after, sweep count and duration), the seven-caller decision
  table, what the mutation checks proved, and — honestly — everything not seen
  in a browser. Do not duplicate any of it into `CLAUDE.md`.

- [ ] **Step 5: Merge and push.** In this project "merge" means both.

```bash
git checkout master && git pull origin master
git merge --no-ff plan-c && git push origin master
git worktree remove ~/ask-the-budget-az-worktrees/plan-c && git branch -d plan-c
```

---

## Self-review notes

- **Spec coverage.** T10 → Tasks 6, 7 (all three required properties are
  named as assertions). T13 → Tasks 1–5: non-terminal jobs (Task 1
  `load_active`), failures regardless of age (Tasks 1, 4 tests), the dropped
  window (Task 4 — no age code exists anywhere, which is the point), job
  files never deleted (Task 1 `unlink` only ever follows a successful write;
  Task 2 only moves), and "a way to see everything" (Task 4 `?all=1`, Task 5's
  link).
- **The plan's code is a sketch.** Three tasks on Plan B found the plan's
  example code wrong while its reasoning was right. Run every block and
  correct it; the prose is the contract, the code is a draft.
- **Known gap, deliberate:** Tasks 5 and 7 give behaviour and spec names but
  not full component source, because both must be written against the
  `Upload.tsx` that exists at execution time — a peer session is editing it.
  Read the file first; do not transcribe a component from this plan.
