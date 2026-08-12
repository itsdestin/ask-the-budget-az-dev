"""Retrieval pipeline (LanceDB + local ONNX models).

Hybrid retrieval composing:
- Lexical: LanceDB FTS/BM25 over chunk.text (`bm25_query_lance`)
- Dense: LanceDB cosine ANN over local embeddings (`dense_query_lance`)
- RRF: rank-based fusion of the two legs
- Rerank: local cross-encoder (`LocalReranker`)
- `retrieve()`: top-level orchestrator returning RetrievalResult

The legacy Postgres/Voyage stages (`retrieval.bm25`, `retrieval.dense`,
`retrieval.rerank`, `retrieval.sql`) and the FastAPI sidecar
(`retrieval.api`) were DELETED in Plan 5 Track 4. `retrieval.citations`
is live — the AI Mode harness calls it in-process for every citation.
"""

from retrieval.local_embedder import LocalEmbedder
from retrieval.local_rerank import LocalReranker
from retrieval.pipeline import (
    BM25_TOP_K,
    DEFAULT_CORPUS,
    DEFAULT_PIPELINE_TOP_K,
    DENSE_TOP_K,
    FUSED_TOP_K,
    NO_RESULTS_TOP_SCORE,
    RetrievalRequest,
    RetrievalResult,
    SpreadSpec,
    reset_default_collaborators,
    retrieve,
    retrieve_spread,
)
from retrieval.rrf import DEFAULT_K, RankedList, rrf_fuse
from retrieval.search_lance import bm25_query_lance, dense_query_lance
from retrieval.types import RetrievalFilters, RetrievedChunk

__all__ = [
    # Core public types
    "RetrievalFilters",
    "RetrievalRequest",
    "RetrievalResult",
    "RetrievedChunk",
    # Top-level pipeline
    "retrieve",
    # Spec N4/N5 — structured multi-group search, opt-in alongside retrieve()
    "retrieve_spread",
    "SpreadSpec",
    "reset_default_collaborators",
    # Stage helpers (callable directly when you want one stage only)
    "bm25_query_lance",
    "dense_query_lance",
    "rrf_fuse",
    # Local models
    "LocalEmbedder",
    "LocalReranker",
    # Helper types
    "RankedList",
    # Tuning constants
    "BM25_TOP_K",
    "DENSE_TOP_K",
    "FUSED_TOP_K",
    "DEFAULT_PIPELINE_TOP_K",
    "DEFAULT_CORPUS",
    "DEFAULT_K",
    "NO_RESULTS_TOP_SCORE",
]
