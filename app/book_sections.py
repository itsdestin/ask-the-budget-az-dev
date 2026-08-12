"""Re-export shim. The family rule moved to `store/book_family.py` (spec
2026-08-12 N1) so `harness/corpus_map.py` can use it without importing
`app/`. This module stays because app- and webapp-facing code imports it by
this path (`app/search_provider.py`, `app/routes/corpus.py`); the docstring
history — including WHY the rule reads source_url and not doc_id — lives at
the new home.
"""
from __future__ import annotations

from store.book_family import section_of

__all__ = ["section_of"]
