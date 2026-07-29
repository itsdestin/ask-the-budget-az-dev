"""Embedded LanceDB chunk store.

One LanceDB database directory (under <data_dir>/lancedb) holds one
table per corpus. Vector search (cosine) and FTS/BM25 (tantivy) both
live here, replacing pgvector + ParadeDB. All methods return plain
dicts with a `_score` key added by search paths; retrieval code adapts
them to RetrievedChunk (see retrieval/search_lance.py).

Concurrency model (spec S6): any number of reader processes; writers
are externally serialized by the ingest lock (Plan 3). This class does
NOT itself lock.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import lancedb

from store.config import data_dir
from store.schema import chunk_schema

DEFAULT_DIM = 384  # BAAI/bge-small-en-v1.5
CORPUS_TABLES = ("budget_chunks", "fiscal_note_chunks")

# WHY: LanceDB search results carry the relevance/distance column under
# different names depending on query type and version (vector ->
# _distance, FTS -> _score, hybrid/reranked -> _relevance_score). We
# probe in order rather than hardcoding one key.
_FTS_SCORE_KEYS = ("_score", "score", "_relevance_score")


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

    # -- tables ---------------------------------------------------------
    def _table(self, name: str):
        if name not in self._db.table_names():
            self._db.create_table(name, schema=chunk_schema(dim=self._dim))
        return self._db.open_table(name)

    def count(self, name: str) -> int:
        # NOTE: like every method here, this goes through _table() and so
        # CREATES the table (empty) if it does not exist yet. That is
        # deliberate — callers can count/search a fresh corpus before any
        # ingest has run and get 0 rather than an exception.
        return self._table(name).count_rows()

    # -- writes ---------------------------------------------------------
    def upsert_chunks(self, name: str, rows: Iterable[dict[str, Any]]) -> None:
        rows = list(rows)
        if not rows:
            return
        tbl = self._table(name)
        # WHY delete-then-add instead of merge_insert: rows are full
        # replacements keyed by chunk_id, and delete+add keeps us off
        # version-sensitive merge APIs. Wrapped by the external ingest
        # lock, so no interleaving writers.
        ids = ", ".join(_sql_str(r["chunk_id"]) for r in rows)
        tbl.delete(f"chunk_id IN ({ids})")
        tbl.add(rows)

    def build_fts_index(self, name: str) -> None:
        # Tantivy-backed BM25 index over chunk text. replace=True makes
        # rebuild-after-append idempotent.
        self._table(name).create_fts_index("text", replace=True)

    # -- reads ----------------------------------------------------------
    def get_by_ids(self, name: str, chunk_ids: list[str]) -> list[dict[str, Any]]:
        if not chunk_ids:
            return []
        ids = ", ".join(_sql_str(c) for c in chunk_ids)
        return (
            self._table(name)
            .search()
            .where(f"chunk_id IN ({ids})")
            .limit(len(chunk_ids))
            .to_list()
        )

    def vector_search(
        self, name: str, vector: list[float], *, top_k: int,
        where: str | None = None,
    ) -> list[dict[str, Any]]:
        q = (
            self._table(name)
            .search(vector, vector_column_name="vector")
            .metric("cosine")
            .limit(top_k)
        )
        if where:
            q = q.where(where, prefilter=True)
        out = q.to_list()
        # LanceDB returns _distance (cosine distance); expose similarity.
        for r in out:
            r["_score"] = 1.0 - float(r.pop("_distance", 1.0))
        return out

    def fts_search(
        self, name: str, query: str, *, top_k: int, where: str | None = None,
    ) -> list[dict[str, Any]]:
        q = self._table(name).search(query, query_type="fts").limit(top_k)
        if where:
            q = q.where(where, prefilter=True)
        out = q.to_list()
        for r in out:
            r["_score"] = self._pop_fts_score(r)
        return out

    @staticmethod
    def _pop_fts_score(row: dict[str, Any]) -> float:
        """Pull the BM25 relevance value out of a raw FTS result row.

        WHY a helper: the column name varies across LanceDB versions and
        query paths, and a naive `r.pop("_score", r.pop("score", 0.0))`
        would evaluate the fallback eagerly and drop the real value.
        """
        for key in _FTS_SCORE_KEYS:
            if key in row:
                value = row.pop(key)
                return float(value) if value is not None else 0.0
        return 0.0

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
        """
        parts: list[str] = []

        def _in(col: str, vals: list) -> str:
            # WHY the bool check comes first: bool is a subclass of int in
            # Python, so `isinstance(True, int)` is True and a bare numeric
            # branch would render it as the invalid SQL literal `True`.
            rendered = ", ".join(
                str(v) if isinstance(v, (int, float)) and not isinstance(v, bool)
                else _sql_str(v)
                for v in vals
            )
            return f"{col} IN ({rendered})"

        def _overlap(col: str, vals: list[str]) -> str:
            rendered = ", ".join(_sql_str(v) for v in vals)
            return f"array_has_any({col}, [{rendered}])"

        if fiscal_year:
            parts.append(_in("fiscal_year", fiscal_year))
        if doc_type:
            parts.append(_in("doc_type", doc_type))
        if publisher:
            parts.append(_in("publisher", publisher))
        if agency_canonical_id:
            parts.append(_overlap("agency_canonical_ids", agency_canonical_id))
        if fund_canonical_id:
            parts.append(_in("fund_canonical_id", fund_canonical_id))
        if fund_mentions:
            parts.append(_overlap("fund_mentions", fund_mentions))
        if is_table is not None:
            parts.append(f"is_table = {'true' if is_table else 'false'}")
        return " AND ".join(parts) if parts else None
