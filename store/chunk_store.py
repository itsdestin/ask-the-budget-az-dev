"""Embedded LanceDB chunk store.

One LanceDB database directory (under <data_dir>/lancedb) holds one
table per corpus. Vector search (cosine) and full-text search (BM25
scoring over a native Lance inverted index) both live here, replacing
pgvector + ParadeDB. All methods return plain dicts with a `_score` key
added by search paths; retrieval code adapts them to RetrievedChunk
(see retrieval/search_lance.py).

Concurrency model (spec S6): any number of reader processes; writers
are externally serialized by the ingest lock (Plan 3). This class does
NOT itself lock. Readers never create or mutate tables — only the write
paths (upsert_chunks / build_fts_index / optimize / ensure_tables) do —
so a read-only process on the office share never writes to it.
"""
from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path
from typing import Any, Iterable

import lancedb
from lancedb.index import FTS

from store.config import data_dir
from store.schema import chunk_schema

# Must stay in lockstep with retrieval.local_embedder.DEFAULT_LOCAL_MODEL /
# LOCAL_EMBEDDING_DIM: retrieval/pipeline.py builds its singleton as a bare
# ChunkStore(), so if this drifts from the model's real width, _check_dim
# refuses to open the table the migration just wrote.
DEFAULT_DIM = 768  # snowflake/snowflake-arctic-embed-m
CORPUS_TABLES = ("budget_chunks", "fiscal_note_chunks")

# How long a superseded LanceDB version survives before `optimize()` prunes
# it. See `ChunkStore.optimize` for why this is not LanceDB's 7-day default.
#
# WHY 10 MINUTES — the number is a balance between two concrete things, not a
# round guess:
#
#  * It must not be 0. ~20 office machines read this corpus off a share.
#    `_open()` calls `checkout_latest()` and then runs a query, so a reader
#    holds a specific version for the DURATION OF ONE QUERY — a few seconds
#    here. Ten minutes is two orders of magnitude of headroom over that, and
#    also absorbs the modest clock skew you get between office PCs, which
#    matters because the prune compares version timestamps against the
#    pruning machine's clock.
#  * It must not be long. The bug being fixed is a bulk run at ~945 docs/hr
#    where every version is minutes old, so any window measured in hours
#    reclaims nothing while it matters most. Ten minutes bounds the garbage
#    to roughly 150 documents' worth at that rate instead of all of it.
#
# Version history is NOT this app's recovery mechanism — `store/backup.py`'s
# S17 snapshots are — so nothing is being given up by pruning aggressively.
DEFAULT_RETENTION_MINUTES = 10
_RETENTION_ENV_VAR = "JLBC_LANCE_RETENTION_MINUTES"


def version_retention() -> timedelta:
    """Retention window for superseded versions, from the environment.

    `0` is honoured — it is the right answer for a supervised bulk backfill
    on a machine nobody else is reading, and it is unambiguous. Anything
    that is not a non-negative integer (a typo, a blank, a float) falls back
    to the default and does NOT read as zero: silently pruning every version
    because somebody fat-fingered a shell variable is how a reader on
    another machine gets its dataset yanked mid-query.
    """
    raw = (os.environ.get(_RETENTION_ENV_VAR) or "").strip()
    if raw.isdigit():
        return timedelta(minutes=int(raw))
    return timedelta(minutes=DEFAULT_RETENTION_MINUTES)


def sql_str(value: str) -> str:
    """Render a Python string as a SQL string literal, safely quoted.

    WHY this exists: LanceDB filters are SQL *strings* — there is no
    parameter binding like psycopg's `%s`. The Postgres code this
    replaces passed values as params, so a fund name containing an
    apostrophe was harmless. Interpolating it raw here would produce a
    DataFusion parse error (or worse, injected predicate), so we escape
    by doubling single quotes, which is what SQL specifies.

    Public (not `_sql_str`) because callers OUTSIDE this module build
    `where=` strings for scan() too — retrieval/api.py's /docs endpoint
    filters on a client-supplied doc_id. One escaper, used everywhere,
    beats a second copy in the sidecar.
    """
    return "'" + str(value).replace("'", "''") + "'"


class ChunkStore:
    def __init__(self, *, root: Path | None = None, dim: int = DEFAULT_DIM,
                 create: bool = True):
        self._root = (root or data_dir()) / "lancedb"
        if create:
            self._root.mkdir(parents=True, exist_ok=True)
        elif not self._root.is_dir():
            # WHY not connect anyway: lancedb.connect() creates a missing
            # local directory itself. A PROBE must never do that — spec
            # principle 3 (2026-08-25); the health ladder, the startup
            # provider probe and validate_data_dir all pass create=False.
            raise FileNotFoundError(f"no lancedb folder at {self._root}")
        self._dim = dim
        self._db = lancedb.connect(str(self._root))
        # WHY cache handles: table_names() + open_table() measured ~5.7ms per
        # call locally versus ~1.9ms for a cached handle, and each is a
        # separate round trip on the SMB share — which every query pays 1-3
        # times over. See _open() for the staleness guard that makes it safe.
        self._handles: dict[str, Any] = {}
        # Every column except the vector, which no consumer reads
        # back — projecting it away keeps result payloads small.
        self._columns = [f.name for f in chunk_schema(dim=dim) if f.name != "vector"]

    # -- tables ---------------------------------------------------------
    @staticmethod
    def _validate_name(name: str) -> None:
        if name not in CORPUS_TABLES:
            raise ValueError(
                f"Unknown corpus table {name!r}. "
                f"Valid names are: {', '.join(CORPUS_TABLES)}."
            )

    def _check_dim(self, name: str, tbl: Any) -> None:
        """Guard against opening a table built with a different embedding model."""
        actual = tbl.schema.field("vector").type.list_size
        if actual != self._dim:
            raise ValueError(
                f"Table {name!r} stores {actual}-dimensional vectors, but this "
                f"ChunkStore was opened with dim={self._dim}. This usually means "
                "the embedding model changed. Re-ingest the corpus into a fresh "
                "data directory, or open the store with the matching dim."
            )

    def _open(self, name: str) -> Any | None:
        """Return an up-to-date handle for `name`, or None if it doesn't exist.

        Read path — never creates. Returning None (rather than creating an
        empty table) keeps readers off the write path entirely, and means a
        typo'd name can't silently materialize a table; _validate_name
        catches the typo before we get here.
        """
        self._validate_name(name)
        tbl = self._handles.get(name)
        if tbl is not None:
            # WHY checkout_latest on every access: a cached handle is pinned
            # to the version it was opened at, so it would never see rows
            # another process appended (verified — count stays 0 after an
            # external add). It mutates in place and returns None.
            tbl.checkout_latest()
            return tbl
        if name not in self._db.table_names():
            return None
        tbl = self._db.open_table(name)
        self._check_dim(name, tbl)
        self._handles[name] = tbl
        return tbl

    def _open_or_create(self, name: str) -> Any:
        """Write path — creates the table with our schema if it's missing."""
        tbl = self._open(name)
        if tbl is None:
            self._db.create_table(name, schema=chunk_schema(dim=self._dim))
            tbl = self._db.open_table(name)
            self._handles[name] = tbl
        return tbl

    def ensure_tables(self) -> None:
        """Create every corpus table up front (used by ingest / migration)."""
        for name in CORPUS_TABLES:
            self._open_or_create(name)

    def count(self, name: str) -> int:
        tbl = self._open(name)
        return 0 if tbl is None else tbl.count_rows()

    def optimize(self, name: str, *, retention: timedelta | None = None) -> None:
        """Compact data files, rebuild indices, and PRUNE dead versions.

        Worth calling after a bulk load: a many-batch migration leaves one
        data file per batch (61 after the Task 10 backfill), which measurably
        slows queries until compacted.

        `retention` is what fixes the measured 5.1-GB-holding-18k-chunks
        problem. LanceDB keeps every superseded version until a prune
        removes it, and every write in this app is delete-then-add, so a
        re-ingested document leaves its whole previous self behind. The
        prune is already part of `optimize()` — but its `cleanup_older_than`
        DEFAULTS TO SEVEN DAYS, so on a bulk run where every version is
        minutes old it prunes exactly nothing while returning successfully.
        That is why nobody caught it by reading the call site.

        `delete_unverified` is deliberately left False. It would also remove
        files from apparently-in-progress transactions, and LanceDB's own
        docs warn that is only safe when no other process is touching the
        dataset — which is not something a shared office drive can promise.
        """
        tbl = self._open(name)
        if tbl is not None:
            tbl.optimize(
                cleanup_older_than=(
                    version_retention() if retention is None else retention
                )
            )

    # -- writes ---------------------------------------------------------
    def upsert_chunks(self, name: str, rows: Iterable[dict[str, Any]]) -> None:
        # WHY dedupe within the batch: the delete below removes each chunk_id
        # once, so two rows sharing a chunk_id in one call would both survive
        # the add and duplicate the chunk. Last one wins.
        deduped = {r["chunk_id"]: r for r in rows}
        if not deduped:
            return
        tbl = self._open_or_create(name)
        # WHY delete-then-add instead of merge_insert: rows are full
        # replacements keyed by chunk_id, and delete+add keeps us off
        # version-sensitive merge APIs. Wrapped by the external ingest
        # lock, so no interleaving writers.
        #
        # CAUTION: the delete and the add are two separate commits, so this
        # is NOT atomic — an interruption between them leaves those chunk_ids
        # deleted. Acceptable for the re-runnable migration script, but
        # Plan 3's ingest must not inherit that assumption blindly.
        ids = ", ".join(sql_str(cid) for cid in deduped)
        tbl.delete(f"chunk_id IN ({ids})")
        tbl.add(list(deduped.values()))

    def delete_doc(self, name: str, doc_id: str) -> None:
        """Remove every chunk of one document.

        WHY ingest needs this: re-ingesting a document must REPLACE it, and
        the new run's chunk_ids don't necessarily match the old run's (a
        different MinerU version can split pages differently). Keying the
        replacement on chunk_id — what upsert_chunks does — would leave the
        stale chunks behind as orphans. Deleting by doc_id first is what
        makes re-ingest idempotent.

        No-op when the table doesn't exist yet: `_open` is the read path, so
        deleting from a fresh corpus doesn't materialize an empty table.
        """
        tbl = self._open(name)
        if tbl is None:
            return
        tbl.delete(f"doc_id = {sql_str(doc_id)}")

    def build_fts_index(self, name: str) -> None:
        # BM25 full-text index over chunk text. In lancedb 0.36 this builds a
        # NATIVE Lance inverted index (use_tantivy=False is the default),
        # which is what lets it live inside the table on the share and
        # support prefiltered search. replace=True keeps rebuild-after-append
        # idempotent.
        #
        # WHY the bare "text" positional: when config= is supplied,
        # create_index's first parameter IS the column name, even though it
        # is still named `metric` for legacy-API back-compat.
        self._open_or_create(name).create_index("text", config=FTS(), replace=True)

    # -- reads ----------------------------------------------------------
    def get_by_ids(self, name: str, chunk_ids: list[str]) -> list[dict[str, Any]]:
        tbl = self._open(name)
        if tbl is None or not chunk_ids:
            return []
        ids = ", ".join(sql_str(c) for c in chunk_ids)
        return (
            tbl.search()
            .where(f"chunk_id IN ({ids})")
            .select(self._columns)
            .limit(len(chunk_ids))
            .to_list()
        )

    def scan(
        self, name: str, columns: list[str], *, where: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Unranked projection scan: every matching row, listed columns only.

        WHY it exists: the sidecar has two endpoints that aren't searches at
        all — `/list_values` (which canonical_ids exist, with counts) and
        `/docs/{doc_id}` (metadata for one document). Both were SQL
        `GROUP BY` / `WHERE` queries against Postgres. On Lance the cheapest
        equivalent is to project the handful of needed columns and aggregate
        in Python: the whole 7,755-row budget corpus scans in ~60ms with 6
        columns, which is well inside an HTTP request budget.

        `where` is a DataFusion SQL predicate — build string literals with
        sql_str() so a value containing an apostrophe can't break (or
        rewrite) the expression.

        `limit` caps the rows returned. Pass it when the caller only needs a
        sample — /docs reads document-level columns that every chunk of a
        document repeats, so limit=1 is a full answer and skips dragging
        1,395 identical rows out of the Governor's-budget document.

        WHY limit=None still passes an explicit limit: LanceDB query
        builders apply a default row limit (10 for vector search). A plain
        scan returns everything on lancedb 0.36, but relying on that would
        SILENTLY truncate a full scan if the default ever started applying
        here — a truncated /list_values looks like a small corpus, not like
        a bug. Passing the row count removes the question (and is skipped
        entirely, saving a count_rows round trip, when a limit is given).
        """
        tbl = self._open(name)
        if tbl is None:
            return []
        q = (
            tbl.search()
            .select(columns)
            .limit(tbl.count_rows() if limit is None else limit)
        )
        if where:
            q = q.where(where)
        return q.to_list()

    def vector_search(
        self, name: str, vector: list[float], *, top_k: int,
        where: str | None = None,
    ) -> list[dict[str, Any]]:
        tbl = self._open(name)
        if tbl is None:
            return []
        q = (
            tbl.search(vector, vector_column_name="vector")
            .metric("cosine")
            # _distance is named explicitly: with a projection set, LanceDB
            # warns that a future version will stop auto-including it.
            .select(self._columns + ["_distance"])
            .limit(top_k)
        )
        if where:
            q = q.where(where, prefilter=True)
        out = q.to_list()
        # LanceDB returns cosine *distance*; expose similarity instead.
        for r in out:
            r["_score"] = 1.0 - self._pop_required(r, "_distance")
        return out

    def fts_search(
        self, name: str, query: str, *, top_k: int, where: str | None = None,
    ) -> list[dict[str, Any]]:
        tbl = self._open(name)
        if tbl is None:
            return []
        q = (
            tbl.search(query, query_type="fts")
            .select(self._columns + ["_score"])
            .limit(top_k)
        )
        if where:
            q = q.where(where, prefilter=True)
        out = q.to_list()
        # WHY no alias-probing here: .select() above names _score explicitly,
        # so if LanceDB ever renames the FTS relevance column the query fails
        # loudly at the select — a fallback key could never be reached.
        for r in out:
            r["_score"] = self._pop_required(r, "_score")
        return out

    @staticmethod
    def _pop_required(row: dict[str, Any], key: str) -> float:
        """Pop a score/distance column that MUST be present.

        WHY strict: defaulting a missing key to a constant would silently
        score every hit identically, quietly destroying ranking (and the RRF
        fusion downstream) if LanceDB ever renamed the column.
        """
        if key not in row:
            raise RuntimeError(
                f"LanceDB result is missing the {key!r} column, so hits cannot "
                f"be ranked. Columns present: {sorted(row)}. This usually means "
                "the installed lancedb version renamed it."
            )
        value = row.pop(key)
        return float(value) if value is not None else 0.0

    # -- filters --------------------------------------------------------
    @staticmethod
    def filter_expr(
        *, fiscal_year: list[int] | None = None,
        doc_type: list[str] | None = None,
        doc_id: list[str] | None = None,
        publisher: list[str] | None = None,
        agency_canonical_id: list[str] | None = None,
        fund_canonical_id: list[str] | None = None,
        fund_mentions: list[str] | None = None,
        is_table: bool | None = None,
    ) -> str | None:
        """Build a LanceDB (DataFusion SQL) WHERE expression.

        Same AND-of-OR semantics as RetrievalFilters. Agency + fund
        mentions use array overlap (array_has_any), mirroring the old
        Postgres array-overlap behavior (decision D2).

        None entries inside a filter list are dropped: rendering them as the
        literal 'None' matched nothing at all, silently emptying the result
        set. An all-None list therefore means "no filter on this dimension".
        """
        parts: list[str] = []

        def _in(col: str, vals: list) -> str:
            # Numbers render bare; everything else is a quoted string literal.
            # No bool special-case is needed: is_table is the only boolean
            # column and it has its own scalar branch below, so vals here is
            # only ever ints or strings. (Even a stray bool would be fine —
            # DataFusion accepts a bare `True`; it is the *quoted* 'True' that
            # fails, so the one thing to avoid is routing bools to sql_str.)
            rendered = ", ".join(
                str(v) if isinstance(v, (int, float)) else sql_str(v) for v in vals
            )
            return f"{col} IN ({rendered})"

        def _overlap(col: str, vals: list[str]) -> str:
            rendered = ", ".join(sql_str(v) for v in vals)
            return f"array_has_any({col}, [{rendered}])"

        for col, vals, builder in (
            ("fiscal_year", fiscal_year, _in),
            ("doc_type", doc_type, _in),
            # Scalar string column like doc_type, so ANY-of, not overlap
            # (spec N4 — the by=doc_id spread axis).
            ("doc_id", doc_id, _in),
            ("publisher", publisher, _in),
            ("agency_canonical_ids", agency_canonical_id, _overlap),
            ("fund_canonical_id", fund_canonical_id, _in),
            ("fund_mentions", fund_mentions, _overlap),
        ):
            cleaned = [v for v in (vals or []) if v is not None]
            if cleaned:
                parts.append(builder(col, cleaned))

        if is_table is not None:
            parts.append(f"is_table = {'true' if is_table else 'false'}")
        return " AND ".join(parts) if parts else None
