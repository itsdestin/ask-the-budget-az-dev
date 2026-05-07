"""Phase 1b retrieval pipeline.

Hybrid retrieval pipeline composing the WS4–WS6 components:
- BM25 (WS4): ParadeDB pg_search over chunk.text
- Dense (WS5): pgvector cosine ANN over Voyage embeddings
- RRF (WS6): rank-based fusion of BM25 + dense
- Rerank (WS6): Voyage rerank-2.5 cross-encoder
- `retrieve()` (WS6): top-level orchestrator returning RetrievalResult

WS7 is the thin public re-export — already covered here.
"""

from retrieval.bm25 import bm25_query
from retrieval.dense import dense_query
from retrieval.pipeline import (
    BM25_TOP_K,
    DEFAULT_PIPELINE_TOP_K,
    DENSE_TOP_K,
    FUSED_TOP_K,
    RetrievalRequest,
    RetrievalResult,
    retrieve,
)
from retrieval.rerank import DEFAULT_RERANK_MODEL, rerank_chunks
from retrieval.rrf import DEFAULT_K, RankedList, rrf_fuse
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
    "bm25_query",
    "dense_query",
    "rrf_fuse",
    "rerank_chunks",
    # Helper types
    "RankedList",
    # Tuning constants
    "BM25_TOP_K",
    "DENSE_TOP_K",
    "FUSED_TOP_K",
    "DEFAULT_PIPELINE_TOP_K",
    "DEFAULT_K",
    "DEFAULT_RERANK_MODEL",
]
