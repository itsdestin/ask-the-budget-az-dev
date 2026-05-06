"""Chunk builders.

Two builders consume `ExtractedDocument` and emit `Chunk` records:

- `table_chunk.build_table_chunk` — one whole logical table per chunk
  (chunk-shape D1, D6).
- `narrative_chunk.build_narrative_chunks` — paragraph-merge to a 512-token
  target / 1024-token max (chunk-shape D5).
"""
