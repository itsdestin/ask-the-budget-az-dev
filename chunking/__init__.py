"""Phase 1a chunking layer.

Reads extractor output (ODL JSON / MinerU JSON / python-docx output) and emits
uniform `Chunk` rows. See spec §6 for the schema this layer produces and the
plan at docs/superpowers/plans/2026-05-06-phase-1a-ingestion-and-chunking.md
for the workstream breakdown.
"""

from chunking.types import Chunk, ChunkProvenance

__all__ = ["Chunk", "ChunkProvenance"]
