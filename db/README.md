> **RETIRED** — Postgres left every runtime path (Plans 1 + 3 of the
> standalone consolidation). Migration-era record only; this directory is
> scheduled for deletion in Plan 5.

# db/ — Phase 1b Postgres infrastructure

Local Postgres 16 + pgvector + ParadeDB pg_search for the Ask the Budget AZ retrieval stack. **Phase 1b WS1–WS7 shipped on slice (2026-05-07)** — schema is stable, the slice corpus is loaded and embedded, retrieval is callable end-to-end via `retrieval.retrieve(...)`. Volume ingest (corpus expansion to all four publishers) runs separately — see [`PROMPT-volume-ingest.md`](../PROMPT-volume-ingest.md).

## Quick start

```bash
# 1. Copy + populate env (one-time)
cp db/.env.example .env.local
# edit .env.local if you want a non-default password

# 2. Bring stack up
cd db && docker compose up -d
docker compose ps     # confirm "healthy"

# 3. Apply migrations
set -a; source ../.env.local; set +a
psql "$DATABASE_URL" -f migrations/0001_initial_schema.sql
psql "$DATABASE_URL" -f migrations/0002_indexes.sql
psql "$DATABASE_URL" -f migrations/0003_seed_catalogs.sql

# 4. Verify
psql "$DATABASE_URL" -c "SELECT extname, extversion FROM pg_extension ORDER BY extname;"
psql "$DATABASE_URL" -c "SELECT COUNT(*) FROM agencies;"   # ~157
psql "$DATABASE_URL" -c "SELECT COUNT(*) FROM funds;"      # ~227
```

## Teardown / reset

```bash
cd db && docker compose down -v       # also wipes ./data/
```

`-v` removes the bind-mounted Postgres data dir (`db/data/`). Without it, the container restarts with the prior schema state.

## Migration files

Migrations are plain SQL, applied in order. No `alembic` for v1 — schema is small enough that hand-written `.sql` files are clearer than an ORM-coupled migration tool, and we have no running production DB to migrate.

| File | Contents |
|---|---|
| `migrations/0001_initial_schema.sql` | Extensions + tables (`documents`, `agencies`, `funds`, `chunks`, `conversations`, `messages`, `queries`, `eval_runs`) |
| `migrations/0002_indexes.sql` | HNSW vector, BM25, GIN array, btree filter indexes |
| `migrations/0003_seed_catalogs.sql` | `agencies` + `funds` rows from `samples/entity-catalog.yaml` and `data/fund-catalog.yaml` |

To regenerate `0003` after a catalog YAML change:

```bash
uv run python scripts/generate_seed_migration.py > db/migrations/0003_seed_catalogs.sql
```

## Connection from Python

```python
from db.connection import get_connection

with get_connection() as conn:
    rows = conn.execute("SELECT canonical_name FROM agencies LIMIT 5").fetchall()
    for r in rows:
        print(r["canonical_name"])
```

`get_connection()` returns a pooled `psycopg.Connection` with the `vector` type registered (via `pgvector.psycopg.register_vector`). The pool is module-level — created on first use, holds 5 connections, hands one out per `with` block.

## Why ParadeDB image (not plain Postgres)

ParadeDB's `paradedb/paradedb` image is plain Postgres 16 with `pgvector` and `pg_search` pre-installed. The alternative — building extensions from source in a custom Dockerfile — would fight the `pg_search` Rust toolchain dance every time we bumped Postgres minor versions. Pinning to `paradedb/paradedb:0.18.4-pg16` gives us reproducible builds without managing the extension build chain ourselves.

The image is otherwise vanilla; nothing ParadeDB-specific is required for production deployments — Phase 4 can switch to a managed Postgres + extension pair without code changes.

(Actual pinned tag is `paradedb/paradedb:0.23.4-pg16`, set in `db/docker-compose.yml`. The image label was bumped from the originally-planned 0.18.4 because that tag never existed on Docker Hub.)
