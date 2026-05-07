# PROMPT — Volume Ingest (Claude handoff)

This file is a handoff prompt for a fresh Claude session running on
Destin's desktop machine. The desktop has a beefier GPU than the
laptop where the rest of Phase 1b was built; you are picking up the
"Volume ingest" workstream so the laptop session doesn't have to grind
MinerU on its weaker hardware.

If you (Claude) just cloned this repo on the desktop, your task is
defined below. If you're the laptop session and you've ended up reading
this file, you're done with it — close it and pick up wherever you left
off in master.

---

## Context — what's already done

The laptop session shipped Phase 1b Workstreams 1, 2, and 3:

| Workstream | What it is | Status |
|---|---|---|
| WS1 | Postgres + pgvector + ParadeDB pg_search infrastructure (Docker compose, three SQL migrations, connection helper) | merged to master |
| WS2 | Chunk loader (`db/loader.py`) + post-load validation (`db/validate.py`) + 5-doc bulk loader (`scripts/load_slice.py`) | merged to master |
| WS3 | Voyage embedding pipeline (`db/embeddings.py`) + `scripts/embed_corpus.py` | merged to master |

The Phase 1a "validated slice" — 5 hand-picked documents, 161 chunks
total, JLBC + Legislature only — was loaded into the laptop's local
Postgres and embedded. That slice covers the original smoke-query
expectations but does **not** cover the full v1 dogfood corpus.

## Why the slice isn't enough — read decision D12 first

`docs/superpowers/decisions/2026-05-06-phase-1bc-architecture.md`
is the source of truth for v1 architecture decisions. Read **D1**
(vertical slice over horizontal slice) and **D12** (volume ingest
covers all four publishers) before doing anything.

D12 says v1 dogfood needs:

| Publisher | Doc set | Slice has? |
|---|---|---|
| **JLBC FY27 baseline** | 15 cross-cut s-PDFs + 110 per-agency PDFs | 2 of 15 cross-cuts only |
| **JLBC FY26 approps** | 28 cross-cut PDFs (bh*, bd*, page-keyed) | 2 of 28 only |
| **Legislature FY26** | SB 1735 GAA (DOCX) | yes — done |
| **Governor FY27** | State Agency Detail (636 pp) + Sources & Uses (919 pp) | **no** |
| **AGAO FY25 AFR** | 181 pp tagged PDF | **no** |
| **Primers** | writing draft + Gov glossary | not loaded |

> *"v1 wants all four publishers from the moment retrieval goes live,
> even if just one FY each. Without Gov SAD ingested, half the
> comparison value-prop doesn't work."* — decision D12

Your job is to close that gap. **Target: ~3000 chunks across all four
publishers.**

## The plan — read it

`docs/superpowers/plans/2026-05-06-phase-1b-storage-and-retrieval.md`
section **"Volume ingest (decoupled workstream)"** lays out four steps.
That is the plan you are executing. This file is a layer on top — local
desktop-specific guidance the plan doesn't carry.

## Step 0 — environment setup

```bash
# 1. Install dependencies
uv sync

# 2. Make sure Docker Desktop is installed and running.
# 3. Bring up Postgres + pgvector + pg_search:
cd db && docker compose up -d
docker compose ps  # confirm "(healthy)"

# 4. Configure environment
cp db/.env.example .env.local
# edit .env.local — set VOYAGE_API_KEY (sign up at https://dash.voyageai.com/api-keys
# if you don't have one). Add a payment method on the Voyage dashboard so the
# free-tier rate limits don't bottleneck a 3000-chunk embed run; the free
# token allowance still applies (200M tokens for voyage-3 series), so the
# actual dollar cost is $0.

# 5. Apply migrations (one-time)
set -a; source .env.local; set +a
psql "$DATABASE_URL" -f db/migrations/0001_initial_schema.sql
psql "$DATABASE_URL" -f db/migrations/0002_indexes.sql
psql "$DATABASE_URL" -f db/migrations/0003_seed_catalogs.sql

# 6. Sanity check — agencies + funds catalogs seeded
psql "$DATABASE_URL" -c "SELECT COUNT(*) FROM agencies"  # expect 157
psql "$DATABASE_URL" -c "SELECT COUNT(*) FROM funds"     # expect 227

# 7. Branch off master for this work
git fetch origin && git checkout master && git pull origin master
git worktree add ../ask-the-budget-az-worktrees/phase-1b-volume-ingest -b phase-1b-volume-ingest master
cd ../ask-the-budget-az-worktrees/phase-1b-volume-ingest

# 8. Run the existing test suite to confirm everything works
$env:DATABASE_URL = "postgresql://askbudget:askbudget-dev@127.0.0.1:5432/askbudget"
uv run pytest -q
# Expect: 311 passed (the 2 voyage-live tests skip without VOYAGE_API_KEY).
```

## Step 1 — extend the orchestrator (plan §"Volume ingest" Step 1)

`scripts/run_phase_1a_slice.py` hardcodes the 5 slice docs. Don't
modify it — it's the slice runner and stays as-is for laptop dev.

Create `scripts/run_volume_ingest.py` that drives doc enumeration from
`ingest/discovery.py` instead of a hardcoded list. Discovery already
has the helpers you need:

- `walk_baseline_links()` — enumerates JLBC FY27 baseline cross-cuts from `<YY>baselinelinks.pdf`
- `walk_approps_toc()` — enumerates JLBC FY26 approps cross-cuts from `<YY>ar/apprpttoc.pdf`
- `walk_agency_index()` — enumerates per-agency PDFs from `<YY>baseline/agencyindex.pdf`

For Gov SAD/S&U + AGAO AFR you'll add new pipelines (Step 2 below).

## Step 2 — add Gov SAD + AGAO AFR pipelines (plan §"Volume ingest" Step 2)

Per the spec, both are tagged PDFs that should run through the
**OpenDataLoader** extractor (Phase 0 stack decision: ODL for tagged
PDFs, MinerU for untagged JLBC PDFs). The wrapper is at
`scripts/run_opendataloader.py`.

- **Governor FY27 SAD**: `https://efs.az.gov/sites/default/files/...` (find URL in
  `data/discovery-cache.yaml` or via the AZ Gov OFM page).
- **Governor FY27 Sources & Uses**: same publisher, separate URL.
- **AGAO FY25 AFR**: `https://www.azauditor.gov/sites/default/files/...` (single
  document, 181 pp).

The chunker should accept ODL output via the existing dispatch in
`chunking/builder.py:chunk_doc`. Confirm `chunking/readers/odl_reader.py`
handles all the layout cases the new docs throw at it. If you find
real bugs in the chunker, fix them with regression tests — same
discipline the slice ingest used (see `data/chunks/MANIFEST.md`
"Bugs fixed in WS6").

## Step 3 — run end-to-end (plan §"Volume ingest" Step 3)

```bash
# Ingest, generate chunks
uv run python scripts/run_volume_ingest.py
# Expected: ~3000 chunks across data/chunks/<doc-id>.json files
# Wall time on a beefy GPU: 1-2 hours (most of it is MinerU on
# JLBC per-agency PDFs)

# Load chunks to DB. You'll need to extend scripts/load_slice.py to
# scripts/load_corpus.py — driven by a manifest (YAML or just-walk-the-
# chunks-dir-and-derive-DocumentMeta-from-the-first-chunk-of-each-file).
# DocumentMeta-from-chunks is fine; the only fields that don't survive
# the round-trip are title + source_blob_path + extractor_version, which
# can default to derivable strings.
uv run python scripts/load_corpus.py --validate

# (Optional, if you have a Voyage key)
uv run python scripts/embed_corpus.py --yes --reindex
# Expected: ~3000 chunks embedded, ~$0 (under free 200M tokens), ~10s
# wall time once Voyage rate limits are unlocked
```

If you don't have a Voyage key, skip the embed step. The laptop will
run it after pulling.

## Step 4 — verify (plan §"Volume ingest" Step 4)

```bash
uv run python -m db.validate
```

Expect all 9 checks PASS. The interesting one is `agency stamping rate
>= 0.85` — Phase 1a slice was 91.3%, full corpus may dip slightly
because per-agency PDFs have heavier narrative content. ≥ 85% is fine;
< 85% means the entity stamper is missing slugs and you should
investigate.

If validate fails:
- **`agency FK integrity` non-zero**: chunker emitted a slug not in
  `samples/entity-catalog.yaml`. Add the missing entry with proper
  canonical name + slug, regenerate `db/migrations/0003_seed_catalogs.sql`
  via `uv run python scripts/generate_seed_migration.py >
  db/migrations/0003_seed_catalogs.sql`, re-apply 0003. Same applies
  for `fund FK integrity` against `data/fund-catalog.yaml`.
- **`agency stamping rate < 0.85`**: investigate which doc / chunks are
  unstamped. Likely a chunker shape regression on the new ODL outputs.

## Commit policy

This is the same problem the laptop hit with the SB 1735 DOCX —
gitignored "regenerable data" was lost across checkouts. The laptop's
fix was to commit the DOCX. Same logic applies to volume-ingested
chunks.

Carve `data/chunks/` out of `.gitignore` so chunk JSONs persist:

```diff
-data/chunks/**
-!data/chunks/
-!data/chunks/MANIFEST.md
+# data/chunks/ chunk JSONs ARE committed (decision: persist across
+# machines so volume ingest doesn't have to re-run on every clone).
+# extractor-output and cached-pdfs stay gitignored — those are larger
+# and reproducible from public URLs anyway.
```

(Update `data/chunks/MANIFEST.md` with the volume corpus inventory
once ingest completes — keep the table format the slice version used.)

Things you commit:
- New code (`scripts/run_volume_ingest.py`, `scripts/load_corpus.py`,
  any extractor/chunker fixes you wrote)
- All chunk JSONs in `data/chunks/` (~28 MB total — under any
  practical Git size limit)
- Updated `data/chunks/MANIFEST.md`
- Updated `.gitignore`
- Updated `samples/entity-catalog.yaml` and `data/fund-catalog.yaml`
  if you added missing entries
- Regenerated `db/migrations/0003_seed_catalogs.sql` if catalogs grew

Things you DO NOT commit:
- `data/extractor-output/` — too large; reproducible from cached PDFs
- `data/cached-pdfs/` — reproducible from public URLs
- `data/audit/` — reproducible from chunks
- `.env.local` — secret material
- `db/data/` — Postgres bind-mount, machine-specific

## Branch + handoff

```bash
git add -A
git commit -m "feat(phase-1b/volume-ingest): full corpus across all four publishers

<your details>"
git push -u origin phase-1b-volume-ingest
```

Don't merge to master from the desktop. Push the branch; the laptop
session pulls, reviews the diff, and merges on its end.

## What "done" means for this handoff

- All four publishers represented in `chunks` table on a fresh
  desktop-side load (JLBC + Legislature + Governor + AGAO)
- Total chunks ≥ 2500 (target ~3000; not a hard floor)
- All 9 `db.validate` checks pass
- Branch `phase-1b-volume-ingest` pushed to remote
- (Optional but appreciated) Note in the PR body any oddities the new
  documents surfaced — ODL extractor quirks, missing catalog entries,
  multi-page tables that didn't reassemble, etc. The laptop will use
  these notes to write the WS8 eval set.

## Things NOT to do

- Don't change the schema (`db/migrations/`) — frozen as of WS1
- Don't change `db/loader.py:chunk_to_row` contract — WS4 retrieval
  depends on the row shape
- Don't merge to master from the desktop
- Don't run destructive git ops (`git reset --hard`, force push,
  branch delete) without explicit user confirmation
- Don't touch `.claude/`, `youcoded/`, or `~/.claude/` — those are
  Destin's YouCoded dev environment, separate from this project
- Don't put a payment method on Voyage if you're not going to use the
  free embedding step — add it only if/when you actually need to embed

## Pinging the laptop

If you hit a real ambiguity, push your work-in-progress to the feature
branch and DM the user. Useful messages:

- *"Step 2 ODL on Gov SAD threw an unhandled layout case (here's a
  sample). Should I extend the reader or skip Gov SAD for v1?"*
- *"Total chunk count is way under target (~1200 vs ~3000). Discovery
  walk only enumerated 18 docs, expected ~50. Bug in
  ingest/discovery.py or upstream TOC change?"*
- *"FK integrity fails on N agencies; here's the slug list. Add them
  to the catalog or are they false positives?"*

Don't speculate or paper over — the laptop session has spec context
the desktop session doesn't.
