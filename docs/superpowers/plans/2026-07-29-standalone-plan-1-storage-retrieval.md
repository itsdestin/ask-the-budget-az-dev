# Standalone Plan 1: Storage + Retrieval Foundation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Postgres/pgvector/ParadeDB with an embedded LanceDB store and replace Voyage embed/rerank with bundled local CPU models, migrating the existing 7,755-chunk corpus and passing the 34-query eval (spec gate G1).

**Architecture:** New `store/` package wraps LanceDB (one file-based DB holding chunk tables + native tantivy BM25 FTS). New `LocalEmbedder`/`LocalReranker` facades mirror the `VoyageEmbedder`/`rerank_chunks` contracts so `retrieval/pipeline.py` swaps backends without changing its public `RetrievalRequest`/`RetrievalResult` API. The FastAPI sidecar (`retrieval/api.py`) is ported so the existing web app + eval harness keep working throughout. A one-time migration script exports Postgres → embeds locally → writes LanceDB.

**Tech Stack:** Python 3.12, `lancedb` (embedded DB: vector + tantivy FTS), `fastembed` (ONNX CPU embeddings + cross-encoder rerank), `pyarrow`, existing FastAPI/pytest/uv toolchain.

**Spec:** `docs/superpowers/specs/2026-07-29-standalone-consolidation-design.md` (decisions S4, S5; gate G1). Work in a worktree per CLAUDE.md (`~/ask-the-budget-az-worktrees/plan1-storage-retrieval/`).

**What this plan does NOT touch:** ingest pipeline (still writes Postgres until Plan 3), MCP server, web UI, fiscal-note corpus (table schema supports it; population is Plan 3). Old Postgres-specific modules (`retrieval/bm25.py`, `retrieval/dense.py`, `db/`) stay in-tree, unused by the new path, until Plan 5 cleanup.

---

## File structure

| File | Responsibility |
|---|---|
| Create `store/__init__.py` | Re-export `ChunkStore`, `data_dir` |
| Create `store/config.py` | Resolve the shared-data directory (env override → dev default) |
| Create `store/schema.py` | PyArrow schema for chunk tables (parameterized by vector dim) |
| Create `store/chunk_store.py` | `ChunkStore`: connect/ensure tables, upsert, get-by-ids, vector search, FTS search, filter-expression builder |
| Create `retrieval/local_embedder.py` | `LocalEmbedder` facade over fastembed `TextEmbedding` (mirrors `VoyageEmbedder.embed_one/embed_batch`) |
| Create `retrieval/local_rerank.py` | `LocalReranker` facade over fastembed `TextCrossEncoder` (mirrors `rerank_chunks` contract) |
| Create `retrieval/search_lance.py` | `bm25_query_lance` + `dense_query_lance` returning `list[RetrievedChunk]` |
| Modify `retrieval/pipeline.py` | `retrieve()` rewired to LanceDB backend; drop psycopg/Voyage; public shapes unchanged |
| Modify `retrieval/api.py` | Sidecar uses `LocalEmbedder` + `ChunkStore` (retrieve + cite-validate chunk fetch + preflight) |
| Create `scripts/migrate_to_lancedb.py` | One-time Postgres → LanceDB migration with local re-embedding |
| Create `tests/test_store_config.py`, `tests/test_chunk_store.py`, `tests/test_local_embedder.py`, `tests/test_local_rerank.py`, `tests/test_search_lance.py` | New unit tests |
| Modify `tests/test_pipeline.py`, `tests/test_api.py` | Adapt mocks to the new backend seams |

Conventions used throughout:
- Table names: `budget_chunks` (this plan), `fiscal_note_chunks` (created empty, populated in Plan 3).
- Table columns use the exact key names `RetrievedChunk.from_row` already expects (`retrieval/types.py:80`), so LanceDB result dicts flow straight into the existing dataclass. `source_anchor` is stored as a JSON string (LanceDB has no dict column) and decoded in `search_lance.py`.
- Default local models: embeddings `BAAI/bge-small-en-v1.5` (384-dim), rerank `Xenova/ms-marco-MiniLM-L-6-v2`. Both are fastembed-supported ONNX models that run on CPU. Task 11 evaluates a second embedder candidate; the eval decides (G1).

---

### Task 1: Dependencies

**Files:**
- Modify: `pyproject.toml` (via `uv add`)

- [ ] **Step 1: Add packages**

Run: `uv add lancedb fastembed`
Expected: resolves and installs; `pyarrow` arrives as a lancedb dependency. If `uv` warns about torch/CUDA — fine, fastembed is ONNX-only, no torch.

- [ ] **Step 2: Smoke-import**

Run: `uv run python -c "import lancedb, fastembed, pyarrow; print(lancedb.__version__, fastembed.__version__)"`
Expected: two version strings, no error.

- [ ] **Step 3: Verify the chosen models are supported by the installed fastembed**

Run: `uv run python -c "from fastembed import TextEmbedding; names=[m['model'] for m in TextEmbedding.list_supported_models()]; print('BAAI/bge-small-en-v1.5' in names)"`
Run: `uv run python -c "from fastembed.rerank.cross_encoder import TextCrossEncoder; names=[m['model'] for m in TextCrossEncoder.list_supported_models()]; print('Xenova/ms-marco-MiniLM-L-6-v2' in names)"`
Expected: `True` and `True`. If either prints `False`, print the full list and pick the nearest equivalent (e.g. `BAAI/bge-small-en-v1.5` quantized variant, `BAAI/bge-reranker-base` for rerank), then use that name everywhere this plan says the model name — record the substitution in the commit message.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore(deps): add lancedb + fastembed for embedded storage / local models"
```

---

### Task 2: Data-directory config (`store/config.py`)

**Files:**
- Create: `store/__init__.py`
- Create: `store/config.py`
- Test: `tests/test_store_config.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_store_config.py
"""data_dir() resolution: env override wins; dev default otherwise."""
from pathlib import Path

from store.config import data_dir


def test_env_override_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path / "shared"))
    assert data_dir() == tmp_path / "shared"


def test_default_is_repo_local_dev_dir(monkeypatch):
    monkeypatch.delenv("JLBC_DATA_DIR", raising=False)
    d = data_dir()
    # Dev default lives inside the repo's data/ tree (gitignored).
    assert d.name == "insight-data"
    assert d.parent.name == "data"


def test_creates_directory(monkeypatch, tmp_path):
    target = tmp_path / "made" / "on" / "demand"
    monkeypatch.setenv("JLBC_DATA_DIR", str(target))
    assert data_dir().is_dir()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_store_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'store'`

- [ ] **Step 3: Implement**

```python
# store/__init__.py
from store.chunk_store import ChunkStore  # noqa: F401  (added Task 4)
from store.config import data_dir  # noqa: F401
```

For now (until Task 4 exists) create it with only the config export:

```python
# store/__init__.py
from store.config import data_dir  # noqa: F401
```

```python
# store/config.py
"""Shared-data directory resolution.

One env var controls where ALL shared state lives (LanceDB, pdfs,
settings, locks): JLBC_DATA_DIR. In production this points at the
office network share (e.g. \\\\JLBC-share\\...\\jlbc-insight-data).
On a dev machine it's unset and falls back to data/insight-data inside
the repo (gitignored), so tests and dev never touch a share.
"""
from __future__ import annotations

import os
from pathlib import Path

_ENV_VAR = "JLBC_DATA_DIR"


def data_dir() -> Path:
    """Resolve (and create if needed) the shared-data root directory."""
    raw = os.environ.get(_ENV_VAR)
    if raw:
        root = Path(raw)
    else:
        # WHY repo-relative: dev machines have no share; keeping the dev
        # corpus inside data/ (already gitignored) means zero setup.
        root = Path(__file__).resolve().parent.parent / "data" / "insight-data"
    root.mkdir(parents=True, exist_ok=True)
    return root
```

- [ ] **Step 4: Gitignore the dev data dir**

Check `.gitignore` already covers `data/` subpaths: it ignores `data/chunks/*` etc. Add an explicit line:

```
data/insight-data/
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_store_config.py -v`
Expected: 3 PASS

- [ ] **Step 6: Commit**

```bash
git add store/ tests/test_store_config.py .gitignore
git commit -m "feat(store): JLBC_DATA_DIR-based shared-data directory resolution"
```

---

### Task 3: Chunk table schema (`store/schema.py`)

**Files:**
- Create: `store/schema.py`
- Test: `tests/test_store_schema.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_store_schema.py
import pyarrow as pa

from store.schema import chunk_schema


def test_schema_fields_and_dim():
    s = chunk_schema(dim=384)
    names = s.names
    # Exact keys RetrievedChunk.from_row expects, plus the vector.
    for expected in [
        "chunk_id", "doc_id", "text", "section_path", "page", "bbox",
        "source_anchor", "agency_canonical_ids", "fund_canonical_id",
        "fund_mentions", "fiscal_year", "doc_type", "is_table",
        "table_html", "token_count", "publisher", "vector",
    ]:
        assert expected in names, expected
    vec = s.field("vector").type
    assert pa.types.is_fixed_size_list(vec) and vec.list_size == 384


def test_source_anchor_is_string_json():
    s = chunk_schema(dim=8)
    assert pa.types.is_string(s.field("source_anchor").type)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_store_schema.py -v`
Expected: FAIL — no module `store.schema`

- [ ] **Step 3: Implement**

```python
# store/schema.py
"""PyArrow schema for chunk tables (budget_chunks, fiscal_note_chunks).

Column names deliberately match the psycopg row keys that
RetrievedChunk.from_row (retrieval/types.py) already consumes, so a
LanceDB result dict flows straight into the existing dataclass.
source_anchor is a JSON string because LanceDB rows are Arrow-typed
(no free-form dict column); search_lance.py decodes it.
"""
from __future__ import annotations

import pyarrow as pa


def chunk_schema(*, dim: int) -> pa.Schema:
    return pa.schema(
        [
            pa.field("chunk_id", pa.string()),
            pa.field("doc_id", pa.string()),
            pa.field("text", pa.string()),
            pa.field("section_path", pa.list_(pa.string())),
            pa.field("page", pa.int32(), nullable=True),
            pa.field("bbox", pa.list_(pa.float32()), nullable=True),
            pa.field("source_anchor", pa.string(), nullable=True),  # JSON
            pa.field("agency_canonical_ids", pa.list_(pa.string())),
            pa.field("fund_canonical_id", pa.string(), nullable=True),
            pa.field("fund_mentions", pa.list_(pa.string())),
            pa.field("fiscal_year", pa.int32(), nullable=True),
            pa.field("doc_type", pa.string()),
            pa.field("is_table", pa.bool_()),
            pa.field("table_html", pa.string(), nullable=True),
            pa.field("token_count", pa.int32()),
            pa.field("publisher", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), dim)),
        ]
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_store_schema.py -v`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add store/schema.py tests/test_store_schema.py
git commit -m "feat(store): pyarrow chunk-table schema keyed to RetrievedChunk.from_row"
```

---

### Task 4: ChunkStore (`store/chunk_store.py`)

**Files:**
- Create: `store/chunk_store.py`
- Modify: `store/__init__.py`
- Test: `tests/test_chunk_store.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_chunk_store.py
"""ChunkStore against a real LanceDB in tmp_path — no models needed;
vectors are hand-made 8-dim floats."""
import pytest

from store.chunk_store import ChunkStore


def _row(cid: str, text: str, vec: list[float], **over):
    base = dict(
        chunk_id=cid, doc_id="doc-1", text=text, section_path=["A", "B"],
        page=3, bbox=[1.0, 2.0, 3.0, 4.0], source_anchor='{"p": 3}',
        agency_canonical_ids=["ahcccs"], fund_canonical_id=None,
        fund_mentions=[], fiscal_year=2026, doc_type="baseline-per-agency",
        is_table=False, table_html=None, token_count=42, publisher="jlbc",
        vector=vec,
    )
    base.update(over)
    return base


@pytest.fixture()
def store(tmp_path):
    s = ChunkStore(root=tmp_path, dim=8)
    s.upsert_chunks("budget_chunks", [
        _row("c1", "ahcccs provider rates increase", [1, 0, 0, 0, 0, 0, 0, 0]),
        _row("c2", "department of child safety caseworkers",
             [0, 1, 0, 0, 0, 0, 0, 0], fiscal_year=2025, publisher="agao"),
        _row("c3", "university operating budget", [0.9, 0.1, 0, 0, 0, 0, 0, 0]),
    ])
    s.build_fts_index("budget_chunks")
    return s


def test_get_by_ids_roundtrip(store):
    got = store.get_by_ids("budget_chunks", ["c2", "c1"])
    assert {r["chunk_id"] for r in got} == {"c1", "c2"}
    r1 = next(r for r in got if r["chunk_id"] == "c1")
    assert r1["text"] == "ahcccs provider rates increase"
    assert list(r1["agency_canonical_ids"]) == ["ahcccs"]


def test_vector_search_orders_by_cosine(store):
    hits = store.vector_search("budget_chunks", [1, 0, 0, 0, 0, 0, 0, 0], top_k=2)
    assert [h["chunk_id"] for h in hits] == ["c1", "c3"]
    assert hits[0]["_score"] > hits[1]["_score"]


def test_fts_search_finds_lexical_match(store):
    hits = store.fts_search("budget_chunks", "caseworkers", top_k=5)
    assert [h["chunk_id"] for h in hits] == ["c2"]
    assert hits[0]["_score"] > 0


def test_filters_apply_to_both_paths(store):
    where = store.filter_expr(fiscal_year=[2025], publisher=["agao"])
    v = store.vector_search("budget_chunks", [1, 0, 0, 0, 0, 0, 0, 0],
                            top_k=5, where=where)
    assert [h["chunk_id"] for h in v] == ["c2"]
    f = store.fts_search("budget_chunks", "ahcccs OR caseworkers",
                         top_k=5, where=where)
    assert [h["chunk_id"] for h in f] == ["c2"]


def test_agency_filter_uses_array_overlap(store):
    where = store.filter_expr(agency_canonical_id=["ahcccs", "dcs"])
    v = store.vector_search("budget_chunks", [0, 1, 0, 0, 0, 0, 0, 0],
                            top_k=5, where=where)
    # c1..c3 all stamp agency 'ahcccs' except none stamp 'dcs'; all match via overlap
    assert {h["chunk_id"] for h in v} == {"c1", "c2", "c3"}


def test_upsert_replaces_same_chunk_id(store):
    store.upsert_chunks("budget_chunks", [
        _row("c1", "REPLACED TEXT", [1, 0, 0, 0, 0, 0, 0, 0]),
    ])
    got = store.get_by_ids("budget_chunks", ["c1"])
    assert len(got) == 1 and got[0]["text"] == "REPLACED TEXT"


def test_empty_table_created_on_demand(tmp_path):
    s = ChunkStore(root=tmp_path, dim=8)
    assert s.count("fiscal_note_chunks") == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_chunk_store.py -v`
Expected: FAIL — no module `store.chunk_store`

- [ ] **Step 3: Implement**

```python
# store/chunk_store.py
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
import pyarrow as pa

from store.config import data_dir
from store.schema import chunk_schema

DEFAULT_DIM = 384  # BAAI/bge-small-en-v1.5
CORPUS_TABLES = ("budget_chunks", "fiscal_note_chunks")


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
        ids = ", ".join(f"'{r['chunk_id']}'" for r in rows)
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
        ids = ", ".join(f"'{c}'" for c in chunk_ids)
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
            r["_score"] = float(r.pop("_score", r.pop("score", 0.0)) or 0.0)
        return out

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
            rendered = ", ".join(
                str(v) if isinstance(v, (int, float)) else f"'{v}'" for v in vals
            )
            return f"{col} IN ({rendered})"

        def _overlap(col: str, vals: list[str]) -> str:
            rendered = ", ".join(f"'{v}'" for v in vals)
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
```

Update the package init:

```python
# store/__init__.py
from store.chunk_store import ChunkStore, DEFAULT_DIM  # noqa: F401
from store.config import data_dir  # noqa: F401
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_chunk_store.py -v`
Expected: 7 PASS. Two likely adjustment points, both fine to fix inline to match the installed lancedb version: (a) the FTS score key (`_score` vs `score`), (b) `.where(..., prefilter=True)` arg name. Check with `uv run python -c "import lancedb; help(lancedb.table.Table.search)"` if either assert trips.

- [ ] **Step 5: Commit**

```bash
git add store/ tests/test_chunk_store.py
git commit -m "feat(store): LanceDB ChunkStore — vector + BM25 FTS + filters + upsert"
```

---

### Task 5: LocalEmbedder (`retrieval/local_embedder.py`)

**Files:**
- Create: `retrieval/local_embedder.py`
- Test: `tests/test_local_embedder.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_local_embedder.py
"""Unit tests mock fastembed (no model download); one opt-in
integration test hits the real model."""
import numpy as np
import pytest

from retrieval.local_embedder import LocalEmbedder


class FakeModel:
    def __init__(self):
        self.calls = []

    def query_embed(self, texts):
        self.calls.append(("query", list(texts)))
        return iter([np.array([1.0, 0.0])])

    def passage_embed(self, texts):
        texts = list(texts)
        self.calls.append(("passage", texts))
        return iter([np.array([0.0, 1.0]) for _ in texts])


def test_embed_one_query_uses_query_path():
    fake = FakeModel()
    emb = LocalEmbedder(model=fake)
    vec = emb.embed_one("what is x", input_type="query")
    assert vec == [1.0, 0.0]
    assert fake.calls[0][0] == "query"


def test_embed_batch_documents_uses_passage_path():
    fake = FakeModel()
    emb = LocalEmbedder(model=fake)
    out = emb.embed_batch(["a", "b"], input_type="document")
    assert out == [[0.0, 1.0], [0.0, 1.0]]
    assert fake.calls[0] == ("passage", ["a", "b"])


@pytest.mark.slow
def test_real_model_dim():
    emb = LocalEmbedder()
    vec = emb.embed_one("arizona state budget", input_type="query")
    assert len(vec) == emb.dim == 384
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_local_embedder.py -v -m "not slow"`
Expected: FAIL — no module `retrieval.local_embedder`. (If pytest warns about the unknown `slow` marker, register it in `pyproject.toml` under `[tool.pytest.ini_options] markers = ["slow: downloads/loads real ONNX models"]`.)

- [ ] **Step 3: Implement**

```python
# retrieval/local_embedder.py
"""Local ONNX embedding facade (spec S4) — same shape as VoyageEmbedder
(db/embeddings.py) so retrieval code swaps without caring which is
behind it: embed_one(text, input_type=...) and
embed_batch(texts, input_type=...).

input_type mapping: fastembed's query_embed/passage_embed apply the
model-appropriate prefixes (bge models want a query instruction
prefix); "document" -> passage_embed, "query" -> query_embed.
"""
from __future__ import annotations

from typing import Any

DEFAULT_LOCAL_MODEL = "BAAI/bge-small-en-v1.5"
LOCAL_EMBEDDING_DIM = 384

INPUT_TYPE_DOCUMENT = "document"
INPUT_TYPE_QUERY = "query"


class LocalEmbedder:
    def __init__(
        self, *, model_name: str = DEFAULT_LOCAL_MODEL,
        dim: int = LOCAL_EMBEDDING_DIM, model: Any | None = None,
    ) -> None:
        self.model_name = model_name
        self.dim = dim
        if model is not None:
            self._model = model
        else:
            # Lazy import: keeps `import retrieval` cheap and lets tests
            # run without fastembed's model download.
            from fastembed import TextEmbedding

            self._model = TextEmbedding(model_name)

    def embed_one(self, text: str, *, input_type: str = INPUT_TYPE_DOCUMENT) -> list[float]:
        return self.embed_batch([text], input_type=input_type)[0]

    def embed_batch(
        self, texts: list[str], *, input_type: str = INPUT_TYPE_DOCUMENT,
    ) -> list[list[float]]:
        if not texts:
            return []
        if input_type == INPUT_TYPE_QUERY:
            it = self._model.query_embed(texts)
        else:
            it = self._model.passage_embed(texts)
        return [[float(x) for x in v] for v in it]
```

- [ ] **Step 4: Run unit tests**

Run: `uv run pytest tests/test_local_embedder.py -v -m "not slow"`
Expected: 2 PASS

- [ ] **Step 5: Run the slow test once (downloads the model, ~30MB)**

Run: `uv run pytest tests/test_local_embedder.py -v -m slow`
Expected: 1 PASS (first run downloads to the fastembed cache; note the cache dir printed — Plan 5 bundles it).

- [ ] **Step 6: Commit**

```bash
git add retrieval/local_embedder.py tests/test_local_embedder.py pyproject.toml
git commit -m "feat(retrieval): LocalEmbedder — fastembed ONNX facade mirroring VoyageEmbedder"
```

---

### Task 6: LocalReranker (`retrieval/local_rerank.py`)

**Files:**
- Create: `retrieval/local_rerank.py`
- Test: `tests/test_local_rerank.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_local_rerank.py
import pytest

from retrieval.local_rerank import LocalReranker
from retrieval.types import RetrievedChunk


def _chunk(cid: str, text: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=cid, doc_id="d", text=text, score=0.0, section_path=[],
        page=None, bbox=None, source_anchor=None, agency_canonical_ids=[],
        fund_canonical_id=None, fund_mentions=[], fiscal_year=None,
        doc_type="t", is_table=False, table_html=None, token_count=1,
        publisher="jlbc",
    )


class FakeCrossEncoder:
    def rerank(self, query, documents):
        # Score = position-reversed so ordering visibly changes.
        n = len(list(documents))
        return iter([0.1 * (i + 1) for i in range(n)])


def test_rerank_orders_by_score_and_truncates():
    rr = LocalReranker(model=FakeCrossEncoder())
    chunks = [_chunk("a", "one"), _chunk("b", "two"), _chunk("c", "three")]
    out = rr.rerank("q", chunks, top_k=2)
    # Fake scores: a=0.1, b=0.2, c=0.3 -> order c, b
    assert [c.chunk_id for c in out] == ["c", "b"]
    assert out[0].score == pytest.approx(0.3)


def test_empty_input_returns_empty():
    rr = LocalReranker(model=FakeCrossEncoder())
    assert rr.rerank("q", [], top_k=5) == []


@pytest.mark.slow
def test_real_model_prefers_relevant_text():
    rr = LocalReranker()
    chunks = [
        _chunk("bad", "recipe for banana bread with walnuts"),
        _chunk("good", "AHCCCS provider rate increases in the FY 2026 baseline"),
    ]
    out = rr.rerank("ahcccs provider rates", chunks, top_k=2)
    assert out[0].chunk_id == "good"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_local_rerank.py -v -m "not slow"`
Expected: FAIL — no module `retrieval.local_rerank`

- [ ] **Step 3: Implement**

```python
# retrieval/local_rerank.py
"""Local cross-encoder rerank (spec S4), replacing Voyage rerank-2.5.

Mirrors the rerank_chunks contract (retrieval/rerank.py): takes the
RRF-fused candidates, returns top_k RetrievedChunk re-scored by the
cross-encoder, descending. Score semantics change vs Voyage (raw
logits, roughly -10..10, NOT 0..1) — the refusal threshold is
re-calibrated in Task 12 and consumers must not assume 0..1.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any

from retrieval.types import RetrievedChunk

DEFAULT_LOCAL_RERANK_MODEL = "Xenova/ms-marco-MiniLM-L-6-v2"


class LocalReranker:
    def __init__(
        self, *, model_name: str = DEFAULT_LOCAL_RERANK_MODEL,
        model: Any | None = None,
    ) -> None:
        self.model_name = model_name
        if model is not None:
            self._model = model
        else:
            from fastembed.rerank.cross_encoder import TextCrossEncoder

            self._model = TextCrossEncoder(model_name)

    def rerank(
        self, query: str, chunks: list[RetrievedChunk], *, top_k: int,
    ) -> list[RetrievedChunk]:
        if not chunks:
            return []
        scores = list(self._model.rerank(query, [c.text for c in chunks]))
        rescored = [
            replace(c, score=float(s)) for c, s in zip(chunks, scores)
        ]
        rescored.sort(key=lambda c: (-c.score, c.chunk_id))
        return rescored[:top_k]
```

- [ ] **Step 4: Run unit tests, then the slow test once**

Run: `uv run pytest tests/test_local_rerank.py -v -m "not slow"`
Expected: 2 PASS
Run: `uv run pytest tests/test_local_rerank.py -v -m slow`
Expected: 1 PASS (downloads the cross-encoder once)

- [ ] **Step 5: Commit**

```bash
git add retrieval/local_rerank.py tests/test_local_rerank.py
git commit -m "feat(retrieval): LocalReranker — fastembed cross-encoder replacing Voyage rerank"
```

---

### Task 7: Lance search stage (`retrieval/search_lance.py`)

**Files:**
- Create: `retrieval/search_lance.py`
- Test: `tests/test_search_lance.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_search_lance.py
"""bm25_query_lance / dense_query_lance over a real tmp LanceDB.
Vectors are hand-made; no models involved."""
import pytest

from retrieval.search_lance import bm25_query_lance, dense_query_lance
from retrieval.types import RetrievalFilters
from store.chunk_store import ChunkStore


@pytest.fixture()
def store(tmp_path):
    s = ChunkStore(root=tmp_path, dim=4)
    s.upsert_chunks("budget_chunks", [
        dict(chunk_id="c1", doc_id="d1", text="ahcccs provider rates",
             section_path=["S"], page=1, bbox=None,
             source_anchor='{"page": 1}', agency_canonical_ids=["ahcccs"],
             fund_canonical_id=None, fund_mentions=[], fiscal_year=2026,
             doc_type="baseline-per-agency", is_table=False,
             table_html=None, token_count=5, publisher="jlbc",
             vector=[1, 0, 0, 0]),
        dict(chunk_id="c2", doc_id="d2", text="child safety caseworkers",
             section_path=[], page=2, bbox=[1, 2, 3, 4],
             source_anchor=None, agency_canonical_ids=["dcs"],
             fund_canonical_id=None, fund_mentions=["general-fund"],
             fiscal_year=2025, doc_type="afr", is_table=True,
             table_html="<table/>", token_count=7, publisher="agao",
             vector=[0, 1, 0, 0]),
    ])
    s.build_fts_index("budget_chunks")
    return s


def test_dense_returns_retrieved_chunks_with_decoded_anchor(store):
    hits = dense_query_lance(
        [1, 0, 0, 0], store=store, corpus="budget_chunks",
        top_k=1, filters=RetrievalFilters(),
    )
    c = hits[0]
    assert c.chunk_id == "c1"
    assert c.source_anchor == {"page": 1}       # JSON decoded
    assert c.publisher == "jlbc"


def test_bm25_respects_filters(store):
    hits = bm25_query_lance(
        "caseworkers OR ahcccs", store=store, corpus="budget_chunks",
        top_k=10, filters=RetrievalFilters(publisher=["agao"]),
    )
    assert [c.chunk_id for c in hits] == ["c2"]
    assert hits[0].is_table is True and hits[0].bbox == [1.0, 2.0, 3.0, 4.0]


def test_bm25_sanitizes_special_chars(store):
    # Apostrophes/specials crashed tantivy before (#47) — must not raise.
    hits = bm25_query_lance(
        "governor's office", store=store, corpus="budget_chunks",
        top_k=5, filters=RetrievalFilters(),
    )
    assert isinstance(hits, list)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_search_lance.py -v`
Expected: FAIL — no module `retrieval.search_lance`

- [ ] **Step 3: Implement**

```python
# retrieval/search_lance.py
"""LanceDB-backed lexical + dense retrieval stages.

Replaces retrieval/bm25.py (ParadeDB) and retrieval/dense.py
(pgvector). Returns list[RetrievedChunk] so rrf_fuse and the rerankers
work unchanged. Reuses the #47 sanitizer idea: tantivy chokes on
Lucene-ish specials, so strip them before querying.
"""
from __future__ import annotations

import json
import re
from typing import Any

from retrieval.types import RetrievalFilters, RetrievedChunk
from store.chunk_store import ChunkStore

# Strip characters tantivy treats as syntax (mirrors bm25.py's
# _sanitize_bm25_query fix for #47).
_SPECIALS = re.compile(r"""["'^~:(){}\[\]\\+\-!*?]""")


def _sanitize(query: str) -> str:
    return _SPECIALS.sub(" ", query).strip()


def _where(store: ChunkStore, filters: RetrievalFilters) -> str | None:
    if filters.is_empty():
        return None
    return store.filter_expr(
        fiscal_year=filters.fiscal_year,
        doc_type=filters.doc_type,
        publisher=filters.publisher,
        agency_canonical_id=filters.agency_canonical_id,
        fund_canonical_id=filters.fund_canonical_id,
        fund_mentions=filters.fund_mentions,
        is_table=filters.is_table,
    )


def row_to_chunk(row: dict[str, Any], score: float) -> RetrievedChunk:
    """LanceDB dict -> RetrievedChunk. source_anchor is JSON-encoded in
    the table (Arrow has no dict column); decode it here so downstream
    consumers see the same shape psycopg rows had."""
    row = dict(row)
    anchor = row.get("source_anchor")
    row["source_anchor"] = json.loads(anchor) if anchor else None
    return RetrievedChunk.from_row(row, score)


def bm25_query_lance(
    query: str, *, store: ChunkStore, corpus: str, top_k: int,
    filters: RetrievalFilters,
) -> list[RetrievedChunk]:
    q = _sanitize(query)
    if not q:
        return []
    rows = store.fts_search(corpus, q, top_k=top_k, where=_where(store, filters))
    return [row_to_chunk(r, r["_score"]) for r in rows]


def dense_query_lance(
    query_vector: list[float], *, store: ChunkStore, corpus: str,
    top_k: int, filters: RetrievalFilters,
) -> list[RetrievedChunk]:
    rows = store.vector_search(
        corpus, query_vector, top_k=top_k, where=_where(store, filters)
    )
    return [row_to_chunk(r, r["_score"]) for r in rows]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_search_lance.py -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add retrieval/search_lance.py tests/test_search_lance.py
git commit -m "feat(retrieval): LanceDB lexical+dense stages returning RetrievedChunk"
```

---

### Task 8: Rewire `retrieve()` (`retrieval/pipeline.py`)

**Files:**
- Modify: `retrieval/pipeline.py`
- Modify: `retrieval/__init__.py`
- Test: `tests/test_pipeline.py` (rewrite the backend seams; keep the behavioral tests)

- [ ] **Step 1: Update the pipeline tests first**

Open `tests/test_pipeline.py`. The existing tests monkeypatch `retrieval.pipeline.bm25_query` / `dense_query` / `rerank_chunks` and inject a mock embedder. Rewrite those seams to the new names — the behavioral assertions (empty-query short-circuit, RRF composition, counts, top_score) stay identical. The new seams to patch are `retrieval.pipeline.bm25_query_lance`, `retrieval.pipeline.dense_query_lance`, and the injected `reranker`/`embedder`/`store` parameters. Add one new test:

```python
def test_default_corpus_is_budget(monkeypatch):
    seen = {}

    def fake_bm25(query, *, store, corpus, top_k, filters):
        seen["corpus"] = corpus
        return []

    monkeypatch.setattr("retrieval.pipeline.bm25_query_lance", fake_bm25)
    monkeypatch.setattr(
        "retrieval.pipeline.dense_query_lance",
        lambda v, *, store, corpus, top_k, filters: [],
    )
    from retrieval.pipeline import RetrievalRequest, retrieve

    class FakeEmb:
        def embed_one(self, text, *, input_type="query"):
            return [0.0]

    retrieve(RetrievalRequest(query="x"), store=object(), embedder=FakeEmb())
    assert seen["corpus"] == "budget_chunks"
```

- [ ] **Step 2: Run to verify the rewritten tests fail**

Run: `uv run pytest tests/test_pipeline.py -v`
Expected: FAIL — `retrieve()` doesn't accept `store=`, lance stage names don't exist in `retrieval.pipeline`.

- [ ] **Step 3: Rewire the pipeline**

In `retrieval/pipeline.py`:

Replace the imports `import psycopg`, `from db.embeddings import VoyageEmbedder`, `from retrieval.bm25 import bm25_query`, `from retrieval.dense import dense_query`, `from retrieval.rerank import rerank_chunks` with:

```python
from retrieval.local_embedder import LocalEmbedder
from retrieval.local_rerank import LocalReranker
from retrieval.search_lance import bm25_query_lance, dense_query_lance
from store.chunk_store import ChunkStore
```

Add module-level lazy singletons (constructing the ONNX models per-call would reload weights every query):

```python
_default_store: ChunkStore | None = None
_default_embedder: LocalEmbedder | None = None
_default_reranker: LocalReranker | None = None


def _defaults() -> tuple[ChunkStore, LocalEmbedder, LocalReranker]:
    global _default_store, _default_embedder, _default_reranker
    if _default_store is None:
        _default_store = ChunkStore()
    if _default_embedder is None:
        _default_embedder = LocalEmbedder()
    if _default_reranker is None:
        _default_reranker = LocalReranker()
    return _default_store, _default_embedder, _default_reranker
```

Add `corpus: str = "budget_chunks"` as a field on `RetrievalRequest` (after `top_k`), and replace `retrieve()`'s signature + body:

```python
def retrieve(
    req: RetrievalRequest,
    *,
    store: ChunkStore | None = None,
    embedder: LocalEmbedder | None = None,
    reranker: LocalReranker | None = None,
    bm25_top_k: int = BM25_TOP_K,
    dense_top_k: int = DENSE_TOP_K,
    fused_top_k: int = FUSED_TOP_K,
    rrf_k: int = 60,
    bm25_weight: float = 1.0,
    dense_weight: float = 1.0,
) -> RetrievalResult:
    """Hybrid retrieval over the embedded LanceDB store.

    Stages: LanceDB FTS (BM25/tantivy) + local-ONNX dense -> RRF ->
    local cross-encoder rerank. Same public shapes as the Postgres/
    Voyage version; `conn`/`rerank_client` params are gone (no server,
    no external APIs). Score semantics: reranker scores are raw
    cross-encoder logits (not 0..1) — refusal thresholds are
    calibrated against this distribution, not Voyage's.
    """
    if not req.query.strip():
        return RetrievalResult()

    if store is None or embedder is None or reranker is None:
        d_store, d_emb, d_rr = _defaults()
        store = store or d_store
        embedder = embedder or d_emb
        reranker = reranker or d_rr

    filters = req.to_filters()

    bm25_hits = bm25_query_lance(
        req.query, store=store, corpus=req.corpus,
        top_k=bm25_top_k, filters=filters,
    )
    qvec = embedder.embed_one(req.query, input_type="query")
    dense_hits = dense_query_lance(
        qvec, store=store, corpus=req.corpus,
        top_k=dense_top_k, filters=filters,
    )

    fused = rrf_fuse(
        [
            RankedList(chunks=bm25_hits, weight=bm25_weight),
            RankedList(chunks=dense_hits, weight=dense_weight),
        ],
        k=rrf_k,
        top_k=fused_top_k,
    )
    if not fused:
        return RetrievalResult(
            bm25_count=len(bm25_hits),
            dense_count=len(dense_hits),
            fused_count=0,
        )

    reranked = reranker.rerank(req.query, fused, top_k=req.top_k)
    return RetrievalResult(
        chunks=reranked,
        top_score=reranked[0].score if reranked else 0.0,
        reranker_scores=[c.score for c in reranked],
        bm25_count=len(bm25_hits),
        dense_count=len(dense_hits),
        fused_count=len(fused),
    )
```

Update `retrieval/__init__.py`: remove the `from retrieval.bm25 import bm25_query`, `from retrieval.dense import dense_query`, and `from retrieval.rerank import ...` re-exports (those modules are now legacy, not part of the public API); export `bm25_query_lance`, `dense_query_lance`, `LocalEmbedder`, `LocalReranker` instead, and drop the removed names from `__all__`.

- [ ] **Step 4: Run pipeline tests + full non-slow suite**

Run: `uv run pytest tests/test_pipeline.py -v`
Expected: PASS
Run: `uv run pytest tests/ -m "not slow" -q`
Expected: `tests/test_bm25.py`, `tests/test_dense.py`, `tests/test_rerank.py`, `tests/test_retrieval_sql.py` may fail at import if they import removed re-exports from `retrieval` — change their imports to the concrete legacy modules (`from retrieval.bm25 import ...`), and if they require a live Postgres they should already skip without `DATABASE_URL`. Fix imports only; do not delete legacy tests in this plan.

- [ ] **Step 5: Commit**

```bash
git add retrieval/pipeline.py retrieval/__init__.py tests/test_pipeline.py tests/test_bm25.py tests/test_dense.py tests/test_rerank.py tests/test_retrieval_sql.py
git commit -m "feat(retrieval): retrieve() now runs on LanceDB + local models (public shapes unchanged)"
```

---

### Task 9: Port the sidecar (`retrieval/api.py`)

**Files:**
- Modify: `retrieval/api.py`
- Test: `tests/test_api.py` (adapt fixtures)

- [ ] **Step 1: Update tests**

`tests/test_api.py` injects fake embedders/DB. Adapt its fixtures the same way as Task 8: patch `retrieval.api` seams to the new store/embedder objects. Specifically:
- Wherever a test monkeypatches Voyage or `DATABASE_URL` preflight, switch to `JLBC_DATA_DIR` pointing at a tmp LanceDB populated with `ChunkStore` (reuse the `_row` helper pattern from `tests/test_chunk_store.py`).
- The `/cite/validate` tests keep their behavior assertions (quote-in-text, span sanity, duplicate-quote rejection) — only the chunk-fetch seam changes.

- [ ] **Step 2: Run to verify failures**

Run: `uv run pytest tests/test_api.py -v`
Expected: FAIL — api.py still imports psycopg/Voyage.

- [ ] **Step 3: Port api.py**

In `retrieval/api.py`:
1. Replace the `VoyageEmbedder` import/usage: `_get_embedder()` returns a module-cached `LocalEmbedder()`.
2. Replace every chunk-fetch SQL (`WHERE chunk_id = ANY(%s)` in `/cite/validate`, `/cite/validate_batch`, `GET /docs/{doc_id}`) with `ChunkStore.get_by_ids("budget_chunks", ids)` / a `where`-filtered query via a module-cached `ChunkStore()`.
3. `lifespan` preflight: drop `VOYAGE_API_KEY` and `DATABASE_URL` checks; new checks are (a) `data_dir()` resolvable/writable, (b) `ChunkStore().count("budget_chunks") > 0`, exiting with the same clear stderr style on failure. Keep the warmup query (it now warms ONNX model load instead of TLS handshakes — same >15s cold-start motivation; note the uncommitted warmup change already in the working tree — fold it in).
4. `/list_values` reads distinct values from LanceDB (`tbl.search().select(["agency_canonical_ids", "doc_id"])...to_list()` then aggregate in Python — the corpus is small; no SQL GROUP BY needed).

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_api.py -v`
Expected: PASS (55 tests or adjusted count)

- [ ] **Step 5: Commit**

```bash
git add retrieval/api.py tests/test_api.py
git commit -m "feat(api): sidecar runs on LanceDB + local models — no Postgres/Voyage"
```

---

### Task 10: Migration script (`scripts/migrate_to_lancedb.py`)

**Files:**
- Create: `scripts/migrate_to_lancedb.py`
- Test: `tests/test_migrate_rows.py` (pure transform only)

- [ ] **Step 1: Write the failing test for the row transform**

```python
# tests/test_migrate_rows.py
from scripts.migrate_to_lancedb import pg_row_to_lance


def test_pg_row_to_lance_maps_and_encodes():
    row = dict(
        chunk_id="c1", doc_id="d1", text="hello", section_path=["A"],
        page=4, bbox=[1, 2, 3, 4], source_anchor={"page": 4},
        agency_canonical_ids=["ahcccs"], fund_canonical_id=None,
        fund_mentions=[], fiscal_year=2026, doc_type="afr",
        is_table=False, table_html=None, token_count=9, publisher="agao",
    )
    out = pg_row_to_lance(row, vector=[0.1, 0.2])
    assert out["source_anchor"] == '{"page": 4}'
    assert out["vector"] == [0.1, 0.2]
    assert out["publisher"] == "agao"


def test_none_anchor_stays_none():
    row = dict(
        chunk_id="c1", doc_id="d1", text="t", section_path=[],
        page=None, bbox=None, source_anchor=None, agency_canonical_ids=[],
        fund_canonical_id=None, fund_mentions=[], fiscal_year=None,
        doc_type="afr", is_table=False, table_html=None, token_count=1,
        publisher="jlbc",
    )
    assert pg_row_to_lance(row, vector=[0.0])["source_anchor"] is None
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_migrate_rows.py -v`
Expected: FAIL — script doesn't exist.

- [ ] **Step 3: Implement the script**

```python
# scripts/migrate_to_lancedb.py
"""One-time Postgres -> LanceDB migration (spec S5, gate G2 input).

Reads every chunk (+ documents.publisher via JOIN) from the Phase-1b
Postgres, re-embeds text with LocalEmbedder (passage mode), and writes
the budget_chunks LanceDB table, then builds the FTS index.

chunk_ids are preserved verbatim, so eval/queries.yaml ground truth
stays valid with no refresh_chunk_ids pass.

Usage:  uv run python scripts/migrate_to_lancedb.py [--batch 128]
Env:    DATABASE_URL (source), JLBC_DATA_DIR (dest; default dev dir)
Runtime: ~7,755 chunks on an i5 CPU ≈ 10–20 min (embedding-bound).
Re-runnable: upsert semantics; safe to interrupt and restart.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any

import psycopg
from psycopg.rows import dict_row

from retrieval.local_embedder import LocalEmbedder
from store.chunk_store import ChunkStore

SELECT_SQL = """
    SELECT c.chunk_id, c.doc_id, c.text, c.section_path, c.page, c.bbox,
           c.source_anchor, c.agency_canonical_ids, c.fund_canonical_id,
           c.fund_mentions, c.fiscal_year, c.doc_type, c.is_table,
           c.table_html, c.token_count, d.publisher
    FROM chunks c
    JOIN documents d ON d.doc_id = c.doc_id
    ORDER BY c.chunk_id
"""


def pg_row_to_lance(row: dict[str, Any], *, vector: list[float]) -> dict[str, Any]:
    anchor = row.get("source_anchor")
    return {
        **{k: row.get(k) for k in (
            "chunk_id", "doc_id", "text", "page", "fund_canonical_id",
            "fiscal_year", "doc_type", "table_html", "token_count",
            "publisher",
        )},
        "section_path": list(row.get("section_path") or []),
        "bbox": [float(x) for x in row["bbox"]] if row.get("bbox") else None,
        "source_anchor": json.dumps(anchor) if anchor is not None else None,
        "agency_canonical_ids": list(row.get("agency_canonical_ids") or []),
        "fund_mentions": list(row.get("fund_mentions") or []),
        "is_table": bool(row.get("is_table")),
        "vector": vector,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, default=128)
    args = ap.parse_args()

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL not set — source Postgres required.", file=sys.stderr)
        return 1

    embedder = LocalEmbedder()
    store = ChunkStore(dim=embedder.dim)

    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        rows = conn.execute(SELECT_SQL).fetchall()
    print(f"source chunks: {len(rows)}")

    t0 = time.time()
    for i in range(0, len(rows), args.batch):
        batch = rows[i : i + args.batch]
        vecs = embedder.embed_batch(
            [r["text"] for r in batch], input_type="document"
        )
        store.upsert_chunks(
            "budget_chunks",
            [pg_row_to_lance(r, vector=v) for r, v in zip(batch, vecs)],
        )
        done = i + len(batch)
        rate = done / max(time.time() - t0, 1e-9)
        print(f"  {done}/{len(rows)}  ({rate:.0f} chunks/s)", flush=True)

    store.build_fts_index("budget_chunks")

    n = store.count("budget_chunks")
    print(f"lancedb budget_chunks rows: {n}")
    if n != len(rows):
        print("COUNT MISMATCH — do not proceed to eval.", file=sys.stderr)
        return 2
    print("migration OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the transform tests**

Run: `uv run pytest tests/test_migrate_rows.py -v`
Expected: 2 PASS. If the real `chunks` table's column names differ from `SELECT_SQL` (check with `uv run python -c "..."` against `db/` schema files or `psql \d chunks`), fix SELECT_SQL to match — the transform contract stays the same.

- [ ] **Step 5: Run the real migration (needs Docker Postgres up on the dev machine)**

Run: `docker compose up -d` (existing dev DB), then `uv run python scripts/migrate_to_lancedb.py`
Expected: progress lines, final `lancedb budget_chunks rows: 7755` (or current corpus count) and `migration OK`.

- [ ] **Step 6: Spot-check citation fidelity (gate G2 evidence)**

Run: `uv run python -c "
from store.chunk_store import ChunkStore
s = ChunkStore()
rows = s.get_by_ids('budget_chunks', [r['chunk_id'] for r in s._table('budget_chunks').search().limit(3).to_list()])
for r in rows: print(r['chunk_id'], r['page'], r['bbox'], r['text'][:60])
"`
Expected: three rows with page/bbox/text intact.

- [ ] **Step 7: Commit**

```bash
git add scripts/migrate_to_lancedb.py tests/test_migrate_rows.py
git commit -m "feat(migration): one-time Postgres -> LanceDB corpus migration with local embeddings"
```

---

### Task 11: Eval gate G1

**Files:**
- Modify: `eval/run_eval.py` only if it constructs Voyage-specific objects (check first — it calls `retrieve(req)` at module level, which now defaults to the local stack, so likely zero changes)
- Create: `eval/results/<UTC-ISO>-<sha>.{json,md}` (generated)

- [ ] **Step 1: Run the eval against the migrated LanceDB corpus**

Run: `uv run python -m eval.run_eval`
Expected: completes in a few minutes (ONNX warm-up + 34 queries); writes results files with recall@5 / recall@20 / latency and a delta-vs-previous section (the delta will compare against the Voyage baseline: recall@5 86%, recall@20 100%).

- [ ] **Step 2: Judge against gate G1**

- recall@5 ≥ 0.80 and recall@20 ≥ 0.95 → **pass**, continue to Step 4.
- Below that → Step 3.

- [ ] **Step 3 (only if G1 missed): try the second candidate embedder**

Change `DEFAULT_LOCAL_MODEL` in `retrieval/local_embedder.py` to `"snowflake/snowflake-arctic-embed-m"` (dim 768 — update `LOCAL_EMBEDDING_DIM`, and pass `dim=768` consistently; the `ChunkStore` table must be rebuilt: delete `<data_dir>/lancedb` and re-run Task 10 Step 5). Re-run the eval. If BOTH candidates land recall@5 < 0.70, STOP — spec says revisit decision S4 with the user before writing more code.

- [ ] **Step 4: Commit the results**

```bash
git add eval/results/
git commit -m "eval: G1 baseline on LanceDB + local models — recall@5 <fill actual>, recall@20 <fill actual>"
```

(Fill the actual numbers into the commit message — they're the audit trail for S4.)

---

### Task 12: Refusal-threshold recalibration

**Files:**
- Modify: `mcp-server/system-prompt.md` (threshold value + score-semantics note)
- Create: `eval/results/` calibration output (generated)

- [ ] **Step 1: Run the calibration sweep**

Run: `uv run python -m eval.calibrate_refusal`
Expected: sweep output with a recommended threshold. Cross-encoder logits are NOT 0..1 — expect a recommendation in raw-logit space (could be negative). If the script assumes a 0..1 grid, widen its sweep range to the observed min/max of `reranker_scores` in the Task 11 results JSON (small code change inside `eval/calibrate_refusal.py`; keep its recommendation logic untouched).

- [ ] **Step 2: Update the system prompt threshold**

In `mcp-server/system-prompt.md`, find the refusal threshold (currently `0.65`, Voyage-calibrated) and replace with the recommended value plus one sentence noting the scale change ("cross-encoder logit, typically −10..10; recalibrated 2026-07-29 for the local reranker"). This file is rewritten wholesale in Plan 4, but the dev app still reads it until then — keeping it correct keeps dogfooding honest.

- [ ] **Step 3: Run the eval once more to confirm no regression from any calibrate-script edits**

Run: `uv run python -m eval.run_eval`
Expected: same recall numbers as Task 11.

- [ ] **Step 4: Commit**

```bash
git add eval/ mcp-server/system-prompt.md
git commit -m "eval: recalibrate refusal threshold for local cross-encoder score scale"
```

---

### Task 13: STATUS.md + merge

**Files:**
- Modify: `STATUS.md`

- [ ] **Step 1: Update STATUS.md**

Add a "Standalone consolidation (Plan 1) — shipped" entry: LanceDB store live at `store/`, local models default, migration done, G1 numbers, refusal threshold change, pointer to the spec + this plan. Update the "What must travel for a fresh device" section: the corpus now travels as `<data_dir>/lancedb` (copyable folder), Postgres/Docker no longer needed for retrieval (still needed for ingest until Plan 3).

- [ ] **Step 2: Full suite**

Run: `bash setup.sh --verify`
Expected: pytest green (including new store/retrieval tests); the 2 vitest suites unaffected.

- [ ] **Step 3: Commit, merge, push**

```bash
git add STATUS.md
git commit -m "docs(STATUS): Plan 1 shipped — LanceDB + local-model retrieval foundation"
```

Then follow superpowers:finishing-a-development-branch (merge `--no-ff` to master, push, remove worktree).

---

## Self-review notes

- **Spec coverage (this plan's slice):** S4 (Tasks 5, 6, 11), S5 (Tasks 3, 4, 7), S6 read-side (ChunkStore docstring; write-lock is Plan 3), G1 (Task 11), G2 evidence starts (Task 10 Step 6). Corpus param for S9 added to `RetrievalRequest` (Task 8) so Plans 2–4 don't need to touch the pipeline signature again.
- **Known uncertainty, called out where it bites:** exact fastembed/lancedb API details (FTS score key, `prefilter` arg, model names) are verified by Task 1 Step 3 and Task 4 Step 4 rather than assumed silently.
- **Legacy code:** `retrieval/bm25.py`, `retrieval/dense.py`, `retrieval/rerank.py`, `db/` stay in-tree unused (ingest still needs `db/` until Plan 3); removal is Plan 5.
