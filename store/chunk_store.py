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

from pathlib import Path
from typing import Any, Iterable

import lancedb
from lancedb.index import FTS

from store.config import data_dir
from store.schema import chunk_schema

DEFAULT_DIM = 384  # BAAI/bge-small-en-v1.5
CORPUS_TABLES = ("budget_chunks", "fiscal_note_chunks")

def _sql_str(value: str) -> str:
    """Render a Python string as a SQL string literal, safely quoted.

    WHY this exists: LanceDB filters are SQL *strings* — there is no
    parameter binding like psycopg's `%s`. The Postgres code this
    replaces passed values as params, so a fund name containing an
    apostrophe was harmless. Interpolating it raw here would produce a
    DataFusion parse error (or worse, injected predicate), so we escape
    by doubling single quotes, which is what SQL specifies.
    """
    return "'" + str(value).replace("'", "''") + "'"


class ChunkStore:
    def __init__(self, *, root: Path | None = None, dim: int = DEFAULT_DIM):
        self._root = (root or data_dir()) / "lancedb"
        self._root.mkdir(parents=True, exist_ok=True)
        self._dim = dim
        self._db = lancedb.connect(str(self._root))
        # WHY cache handles: table_names() + open_table() measured ~5.7ms per
        # call locally versus ~1.9ms for a cached handle, and each is a
        # separate round trip on the SMB share — which every query pays 1-3
        # times over. See _open() for the staleness guard that makes it safe.
        self._handles: dict[str, Any] = {}
        # Every column except the 384-float vector, which no consumer reads
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

    def optimize(self, name: str) -> None:
        """Compact data files and rebuild indices.

        Worth calling after a bulk load: a many-batch migration leaves one
        data file per batch (61 after the Task 10 backfill), which measurably
        slows queries until compacted.
        """
        tbl = self._open(name)
        if tbl is not None:
            tbl.optimize()

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
        ids = ", ".join(_sql_str(cid) for cid in deduped)
        tbl.delete(f"chunk_id IN ({ids})")
        tbl.add(list(deduped.values()))

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
        ids = ", ".join(_sql_str(c) for c in chunk_ids)
        return (
            tbl.search()
            .where(f"chunk_id IN ({ids})")
            .select(self._columns)
            .limit(len(chunk_ids))
            .to_list()
        )

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
            # fails, so the one thing to avoid is routing bools to _sql_str.)
            rendered = ", ".join(
                str(v) if isinstance(v, (int, float)) else _sql_str(v) for v in vals
            )
            return f"{col} IN ({rendered})"

        def _overlap(col: str, vals: list[str]) -> str:
            rendered = ", ".join(_sql_str(v) for v in vals)
            return f"array_has_any({col}, [{rendered}])"

        for col, vals, builder in (
            ("fiscal_year", fiscal_year, _in),
            ("doc_type", doc_type, _in),
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
