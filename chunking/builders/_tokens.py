"""Token counting helper.

Uses tiktoken's cl100k_base when available (matches GPT-4-class encodings,
which is what Phase 1b's embeddings will use in practice). Falls back to
a 4-chars-per-token heuristic for English text — close enough for chunk
size budgeting.

Cached per-process so we don't rebuild the encoder on every call.
"""
from __future__ import annotations

from functools import lru_cache


@lru_cache(maxsize=1)
def _try_tiktoken():
    try:
        import tiktoken
        return tiktoken.get_encoding("cl100k_base")
    except Exception:
        return None


def count_tokens(text: str) -> int:
    """Approximate GPT-4-class token count for `text`."""
    if not text:
        return 0
    enc = _try_tiktoken()
    if enc is not None:
        return len(enc.encode(text))
    # Fallback heuristic: ~4 chars/token for English.
    return max(1, len(text) // 4)
