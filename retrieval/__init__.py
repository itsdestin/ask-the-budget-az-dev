"""Retrieval pipeline (LanceDB + local ONNX models).

Hybrid retrieval composing:
- Lexical: LanceDB FTS/BM25 over chunk.text (`bm25_query_lance`)
- Dense: LanceDB cosine ANN over local embeddings (`dense_query_lance`)
- RRF: rank-based fusion of the two legs
- Rerank: local cross-encoder (`LocalReranker`)
- `retrieve()`: top-level orchestrator returning RetrievalResult

The legacy Postgres/Voyage stages (`retrieval.bm25`, `retrieval.dense`,
`retrieval.rerank`) are no longer re-exported here — they are dead code
kept only for their tests until the cutover is finished. Import them
from their concrete modules if you need them.
"""

from retrieval.local_embedder import LocalEmbedder
from retrieval.local_rerank import LocalReranker
from retrieval.pipeline import (
    BM25_TOP_K,
    DEFAULT_CORPUS,
    DEFAULT_PIPELINE_TOP_K,
    DENSE_TOP_K,
    FUSED_TOP_K,
    RetrievalRequest,
    RetrievalResult,
    retrieve,
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
]
