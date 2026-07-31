# What the bundle needs from the app — hand-off to Session A (Plan 5, Task 17)

**Date:** 2026-08-01
**From:** Session B (packaging, Track 3)
**To:** Session A (owns `app/`, `harness/`, `store/`, `webapp/src/`)
**Status:** open — none of this is built

Session B does not edit application code (parallel-execution contract). The bundle
is built and its file list is pinned by `tests/test_packaging_manifest.py`; these are
the four things it needs from the app side. They are ordered by consequence, not by
size.

Context for all four: the shape decision landed on **one bundle installed on all
~20 office PCs**, with whether a machine actually processes uploads being a setting
rather than a different download. See
`docs/superpowers/investigations/2026-08-01-bundle-size.md`.

---

## 1. An ingest-enabled switch, defaulting to OFF — and a warning when nobody is on

**This is the one that matters.** Everything else here is a papercut.

`launcher.pyw` starts the server with `uvicorn.run(create_app, factory=True)`, i.e.
`create_app()` with no arguments, which means the lifespan hook starts the ingest
worker (Ground truth 2). On twenty machines that is twenty workers competing for the
same queue. `IngestLock` is single-writer so nothing corrupts — but the machine that
wins is arbitrary, and it may be an analyst's laptop, which then spends six hours at
100% CPU on a Baseline Book while they try to work.

**Asked for:** a per-machine `ingest_enabled` flag, defaulting to **false**, that
`create_app()` consults before starting the worker. Per-machine, not per-install and
not in `settings.json` — `settings.json` lives on the share and is shared by every
machine, so it is the wrong home for "is *this* PC the one that does the work."
`%LOCALAPPDATA%\JLBC-Insight\machine.json` (Task 10's file) is the right home:

```json
{ "data_dir": "\\\\server\\share\\JLBC-Insight-Data", "ingest_enabled": false }
```

`create_app(ingest_worker=None)` already exists as the explicit opt-out; this is
about choosing that path from machine config rather than from a call site.

**And the other half, which is not optional:** defaulting to OFF re-creates the exact
silent failure the one-bundle decision was made to avoid — uploads queue on the share
and nothing ever drains them, with no error anywhere. The admin page must say so out
loud when the queue is non-empty and no machine has claimed the work. The queue
already records claims (`ingest/claim.py`, `ingest/jobs.py`), so "nothing has touched
the head of the queue in N minutes" is answerable without new plumbing.

Suggested wording, in the plain-English register the rest of the admin page uses:

> **Uploads are waiting and no computer is set to process them.** Open JLBC Insight
> on the computer that should do this work, go to Admin → Corpus, and turn on
> "Process uploads on this computer."

---

## 2. `/health` must answer 200 before the corpus is reachable

`launcher.pyw` polls `GET /health` for up to 60 seconds and, on timeout, shows a
message box naming the log file. It never opens a window.

That is the right behaviour for "the server is genuinely broken" and the **wrong**
behaviour for "the share is not mounted yet" — which is the single most likely
first-run condition on a laptop that is not on the office network. In that case the
user should see Task 12's repair screen, which is designed to explain it and fix it;
instead they would get a dialog telling them to email a log file to somebody.

**Asked for:** `/health` returns 200 whenever the process is serving, regardless of
the rungs below it. Ground truth 11 already says its `{ok, provider}` shape is fixed
and Plan 2's tests depend on it; this is asking that the *status code* be pinned too.
The detail belongs in `/api/health/detail` (Task 11), which the health gate reads.

If for some reason `/health` must go non-200 when the corpus is unreadable, tell me
and I will point the launcher at a different endpoint instead — but the launcher
needs *some* endpoint that means "the web server is up", separate from "everything is
well".

---

## 3. A supported way to write the data-dir, so `install.cmd` stops writing JSON by hand

`install.cmd` currently writes `%LOCALAPPDATA%\JLBC-Insight\machine.json` itself,
with a hand-rolled JSON literal, because the app is not running at install time. That
is a schema duplicated in a batch file, which will rot the first time
`app/machine_config.py` changes shape.

**Asked for:** a console-free entry point the installer can call:

```
python\python.exe -m app.machine_config --set-data-dir "\\server\share\JLBC-Insight-Data"
```

Exit 0 on success, non-zero with a one-line message on stderr otherwise. It should
run `validate_data_dir()` but **must not fail the install when validation fails** —
a network drive that is not connected during setup is normal, and refusing to record
the path would strand the user. Print the warning, record the path, exit 0.

The plan writes this as a `--data-dir` flag on `app/main.py`; a `machine_config`
entry point is a better fit because it does not start a server, but either works.
Once it exists I will replace the batch-file JSON write and delete this coupling from
`packaging/README.md`.

## 4. Two things I verified so you do not have to re-derive them

- **`DEFAULT_STATIC_DIR` works unchanged.** `app/main.py:119` resolves
  `<app's parent>/webapp/dist`, and the bundle mirrors the repo layout, so the SPA is
  found with no configuration.
- **The repo-default data dir correctly fails validation in the bundle.** With no
  `machine.json`, `store/config.data_dir()` falls back to `<install>/data` — which in
  the bundle is *not* empty (it carries `fund-catalog.yaml`, `jlbc-book-catalog.json`
  and friends). A validator that checked "is this directory non-empty" would wrongly
  accept it. Task 10's `validate_data_dir()` checks for a `lancedb/` subdirectory,
  which correctly rejects it and routes the user to the repair screen. Please keep
  that check as specified rather than loosening it.

---

## Not asked for, deliberately

- **Startup time.** Cold start loads two ONNX models. I have not measured it on
  Windows and it is not an app change; the launcher already waits 60 s and the
  quickstart tells the user to expect 20–40 s on first run.
- **A packaged-vs-dev flag.** Nothing in the app currently needs to know it is running
  from a bundle. Adding one would invite behaviour that only reproduces in the
  distributable, which is the hardest kind to debug from an office you cannot visit.
