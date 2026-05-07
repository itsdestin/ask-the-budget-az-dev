"""Phase 1b retrieval pipeline: BM25 (WS4) + dense (WS5) helpers.

Hybrid retrieval (RRF + Voyage rerank) lands in WS6 on top of these
two helpers; the public `retrieve(query, filters)` API surface is WS7.
"""

from retrieval.bm25 import bm25_query
from retrieval.dense import dense_query
from retrieval.types import RetrievalFilters, RetrievedChunk

__all__ = [
    "RetrievalFilters",
    "RetrievedChunk",
    "bm25_query",
    "dense_query",
]
