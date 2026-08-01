# Handoff: Plan 5 Track 4 — Cleanup (Tasks 18–20 + two orphaned items)

You are working in `~/YouCoded/Projects/ask-the-budget-az-dev` (Linux, venv at
`.venv`).

## Read first

`docs/superpowers/plans/2026-08-01-standalone-plan-5-admin-packaging.md` — the
**Ground truth** block, then **Track 4 (Tasks 18–20)**. Then `STATUS.md` for
current state (it is the single source of truth; the phase plans are historical
and were never updated as features shipped).

## Context: what already landed

Tracks 1, 2 and 3 of Plan 5 all shipped on 2026-07-31. Admin page, Settings,
health ladder, S18 repair screen, break-glass admin recovery, and a **working
Windows bundle verified with an offline cold start**. Plan 5 is 17 of 27 tasks
done; you are doing 18–20.

**The Z13 backfill is finished.** The corpus is ~22.5k budget chunks + 13.3k
fiscal-note chunks across ~3,400 documents. The ingest path is no longer live,
so unlike every handoff before this one **you may restart the app server** —
just say so in your report when you do.

---

## Task 18 — Delete the retired architecture

`web/` (936K), `mcp-server/` (288K), `db/` (112K) and four dead `retrieval/`
modules are still in-tree. This is not tidiness: **`setup.sh` currently runs
`npm ci`, a TypeScript build, and 277 vitest specs across two directories Plan 4
retired.** Anyone who clones this repo — including the G3 cold-start tester —
installs and runs code that does nothing. Deleting it is part of making the
handoff honest.

### The dependency graph, already verified for you (AST, not grep)

I ran an AST import scan on 2026-07-31. **These 14 files are the complete set
that actually imports the deletion targets** — every one is itself being deleted
or is a test of a deleted module, except `eval/synthesize_queries.py`:

| File | imports |
|---|---|
| `eval/refresh_chunk_ids.py` | `db` |
| `eval/synthesize_queries.py` | `db` ← **PORT THIS, don't delete** |
| `retrieval/bm25.py` | `db` |
| `retrieval/dense.py` | `db` |
| `scripts/embed_corpus.py` | `db` |
| `scripts/load_slice.py` | `db` |
| `scripts/redownload_cached_pdfs.py` | `db` |
| `tests/test_api.py` | `retrieval.api` |
| `tests/test_bm25.py` | `db`, `retrieval.bm25` |
| `tests/test_connection.py` | `db` |
| `tests/test_dense.py` | `db`, `retrieval.dense` |
| `tests/test_embeddings.py` | `db` |
| `tests/test_loader.py` | `db` |
| `tests/test_rerank.py` | `retrieval.rerank` |

**⚠ A plain `grep -rl` gives a WRONG, scarier answer.** It also flags
`retrieval/citations.py` (which is **LIVE** — the harness calls it for every
citation) and `packaging/build_bundle.py` (Session B's new code). Both are
**comments/docstrings mentioning the retired modules, not imports.** Do not
"fix" either of them, and do not conclude the deletion is unsafe because grep
said so. `retrieval/__init__.py` already deliberately does not re-export the
dead modules.

### What to do

- [ ] **Port `eval/synthesize_queries.py` FIRST**, in its own commit: swap
      `db.connection.get_connection` for `store.chunk_store.ChunkStore`. Keep it
      because eval-set expansion is a live need (Phase 3, and the fiscal-note
      eval still has no ground truth). Everything else on the `db` list is
      Postgres-era tooling that has no meaning against LanceDB.
- [ ] **Commit A — the Node trees:** delete `web/` and `mcp-server/`, and remove
      their `npm ci` / build / test steps from `setup.sh` (lines ~89–100 and
      ~171–180, plus the header comment at line ~7).
- [ ] **Commit B — the Postgres trees:** delete `db/`, `eval/refresh_chunk_ids.py`,
      `scripts/embed_corpus.py`, `scripts/load_slice.py`,
      `scripts/redownload_cached_pdfs.py`, and `tests/test_connection.py`,
      `tests/test_embeddings.py`, `tests/test_loader.py`.
- [ ] **Commit C — the dead retrieval modules:** delete `retrieval/api.py`,
      `retrieval/bm25.py`, `retrieval/dense.py`, `retrieval/rerank.py` and
      `tests/test_api.py`, `tests/test_bm25.py`, `tests/test_dense.py`,
      `tests/test_rerank.py`.
- [ ] **Commit D — the stale operator docs** STATUS flags: `eval/README.md` and
      `eval/calibrate_refusal.py` still tell operators to edit
      `mcp-server/system-prompt.md`; the refusal threshold lives in
      `harness/constants.py` (`REFUSAL_THRESHOLD = 1.9`). Also sweep `README.md`
      and `CLAUDE.md`'s workspace-layout table for references to the deleted
      trees.
- [ ] **Verify from a FRESH CLONE**, not your working tree — the whole point is
      what the next person gets:
      ```
      git clone <this repo> /tmp/clonecheck && cd /tmp/clonecheck
      bash setup.sh --verify > /tmp/verify.log 2>&1; echo $?
      ```
      **Capture the exit code directly.** Piping into `tail` returns `tail`'s
      status and hides a failure. Note: `.env.local` must not exist during the
      run — there is a known pre-existing test-isolation defect where dotenv
      leaks `DATABASE_URL` and un-skips Postgres suites mid-run.

---

## Task 19 — One `documents.json` reader + live corpus counts

Four modules parse `documents.json` with four separate caches:
`app/search_provider.py`, `app/routes/pdf.py`, `harness/tools.py`,
`ingest/lance_writer.py`.

- [ ] Create `store/documents.py` as the single loader. **Preserve all three
      behaviours** the current readers have, with a test each: mtime-cached
      re-read; the `ingested_at` gate that makes migration-era junk titles lose
      to the doc-id humanizer; and the humanizer fallback itself.
- [ ] Repoint all four callers.
- [ ] Add `GET /api/corpus/counts` → `{documents, budget_chunks, fiscal_note_chunks}`
      and restore a true corpus size to the webapp footer. It states no number
      today because any hardcoded one is falsified the first time somebody
      uploads.

---

## Task 20 — The remaining ingest defects

I verified on 2026-07-31 that **none of these have landed.** Details and
evidence are in STATUS's "Known follow-ups". One per commit.

- [ ] **Dead LanceDB versions — do this one first.** `optimize()` never drops
      superseded versions. The backfill's maintainer script reclaimed **9.5 GB
      in two passes today** — but that script lives on the Z13 and will not
      exist in the office, so the app itself never cleans up. Pass
      `cleanup_older_than` / expose `cleanup_old_versions` in the write phase.
      Test: write, delete, re-write, assert on-disk bytes fall after cleanup.
- [ ] **`DownloadCache` concurrency.** Per-instance tmp path (it is shared
      across instances today) plus a lock around the manifest write. A corrupted
      manifest parses as an **empty** cache, which would re-download ~7,400 PDFs
      from state web servers one at a time. Test with concurrent writers.
- [ ] **`IngestLock` auto-heartbeat.** `_write` heartbeats before `write_doc`
      but not during it, and `build_fts_index` + `optimize` will exceed the 120s
      stale window as the corpus grows — so a live writer's lock can be
      legitimately stolen by another machine. Add a background heartbeat thread
      for the lock's lifetime. Test: hold the lock through a simulated 200s
      write, assert a second acquirer never steals it.
- [ ] **Per-batch snapshots.** `JLBC_INGEST_SNAPSHOT=off` exists for supervised
      backfills because the per-document S17 snapshot is O(n²). The right shape
      is one snapshot per batch (per book edition / per note session) — the
      protection without the quadratic cost.

**Run the eval afterwards** (CLAUDE.md rule — any change to `ingest/` re-runs
it): `uv run python -m eval.run_eval`, and commit the
`eval/results/<...>.{json,md}` files alongside the code.

---

## Two orphaned items — pick these up, nobody else did

Session B (packaging) handed these to Session A, and Session A merged without
them. I checked: `ingest_enabled` exists nowhere in the codebase. Both are small
and both are handoff-blocking. Details:
`docs/superpowers/investigations/2026-08-01-bundle-app-requirements.md`.

- [ ] **A per-machine `ingest_enabled` flag, defaulting to OFF.** The packaging
      decision was **one bundle on all ~20 office PCs**. Without this, all 20
      start an ingest worker against the one shared corpus. It belongs in
      `app/machine_config.py` (Task 10's per-machine config, already shipped),
      not in the shared `settings.json` — it is a property of the machine, not
      of the office.
- [ ] **A visible admin warning when jobs are queued and nothing is draining
      them.** Without it, "off by default" recreates the exact silent pile-up
      that the one-bundle decision was made to avoid: uploads queue forever, no
      error anywhere. Surface it on the admin page's corpus/queue panel.
- [ ] While you are there: `packaging/install.cmd` writes `machine.json` by
      hand and should call `app/machine_config.py` now that Task 10 has landed.

---

## Method

- Worktree: `git worktree add ~/atb-worktrees/plan5-track4 -b plan5-track4 origin/master`
- Test with `.venv/bin/python -m pytest ...` directly. Do **not** run `uv sync`
  or `uv run` inside a worktree — it provisions a second multi-GB venv and
  fights for the uv cache. (`uv run python -m eval.run_eval` from the MAIN
  checkout is fine and is what the eval rule means.)
- TDD where there is behaviour to test; Task 18 is deletion, so the test is the
  fresh-clone `setup.sh --verify`.
- WHY comments on non-obvious decisions — CLAUDE.md rule; Destin is
  non-technical and relies on them.
- Merge `--no-ff` to master, push, remove the worktree.
- Update `STATUS.md`: mark Track 4 shipped, and **delete the follow-up entries
  you actually fixed** rather than leaving them to be re-discovered.

## Report

What was deleted and the fresh-clone verify exit code; what you ported and why;
test evidence for each Task 20 defect; the eval delta; confirmation that the two
orphaned items are done; and anything you found that belongs on the Plan 5 or
Plan 6 list rather than being silently fixed.
