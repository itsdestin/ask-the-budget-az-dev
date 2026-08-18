"""Pydantic models for the Phase 1a chunk schema.

Mirrors spec §6 SQL schema. Lives in Python until Phase 1b serializes to
Postgres. `embedding` is intentionally absent — it lands in Phase 1b.

Provenance is polymorphic per chunk-shape D3:
- PDF chunks carry (page, bbox)
- DOCX chunks carry (paragraph_id [, table_cell_id])

The CHECK constraint from spec §6 — provenance must include either a page or a
paragraph_id — is enforced in `ChunkProvenance` via a model-level validator so
the rule rides with the type, not just the database.
"""
from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, model_validator


@dataclass
class DocMeta:
    """The minimum doc-level metadata each chunk needs.

    Mirrors the public fields on `Chunk` that aren't derivable from the
    document body itself. `doc_id` is what the dispatcher's `make_doc_id`
    produced for this document.

    `extractor` / `source_format` are used by the orchestrator to dispatch
    to the right reader. `source_url` is consumed by the entity stamper
    (JLBC URL → per-agency slug).

    Lives here rather than next to the table builder because every chunk
    builder and now the ingest writer take one — it's doc-level input to the
    whole chunking stage, not a table concern.
    """

    doc_id: str
    publisher: str
    doc_type: str
    fiscal_year: int
    extractor: str = ""  # 'mineru' | 'opendataloader' | 'python-docx'
    source_format: str = ""  # 'pdf' | 'docx'
    source_url: str | None = None


class ProvenanceLine(BaseModel):
    """One member paragraph's locator inside a merged narrative chunk.

    WHY this exists: a narrative chunk merges several paragraphs, but the
    stored `bbox`/`page` used to describe only the FIRST one — measured on a
    live AI-Mode run (2026-08-18, 137 linked figures), 46/137 correctly
    linked citations fell outside the stored bbox and 7 sat on a different
    page, because the cited value was in paragraph 2+. The strict-bbox
    viewer search then cannot see the chunk's own text. `lines` carries the
    per-paragraph (text, page, bbox) tuples the locate endpoint
    (`GET /api/chunks/{id}/locate`) resolves a cited value against, so the
    highlight is the value's own span without re-ingesting anything.

    `text` is the paragraph's own text (a substring of the chunk text by
    construction), so matching a cited slice to a line needs no
    normalization — only whitespace-collapsed containment.
    """

    model_config = ConfigDict(extra="forbid")

    text: str
    page: int
    bbox: list[float]


class ChunkProvenance(BaseModel):
    """Where this chunk came from in its source document.

    Exactly one of `page` (PDF) or `paragraph_id` (DOCX) must be present;
    `bbox` and `table_cell_id` are sub-locators that only make sense alongside
    their parent locator.
    """

    model_config = ConfigDict(extra="forbid")

    page: int | None = None
    bbox: list[float] | None = None
    paragraph_id: str | None = None
    table_cell_id: str | None = None
    # Per-paragraph locators for merged narrative chunks (see ProvenanceLine).
    # None everywhere it has never been written — table chunks and old rows
    # simply lack it, and the locate endpoint falls back to page+bbox+scan.
    lines: list[ProvenanceLine] | None = None

    @model_validator(mode="after")
    def _at_least_one_provenance(self) -> "ChunkProvenance":
        # spec §6 CHECK constraint: must locate the chunk in some source frame
        if self.page is None and self.paragraph_id is None:
            raise ValueError(
                "ChunkProvenance requires page or paragraph_id (spec §6 CHECK)"
            )
        return self


class Chunk(BaseModel):
    """One indexable unit of a budget document.

    Field order mirrors spec §6 columns. `extra='forbid'` makes typos noisy
    rather than silently dropped — Phase 1b's storage layer assumes the shape
    here is exhaustive for what's persisted in 1a.
    """

    model_config = ConfigDict(extra="forbid")

    chunk_id: str
    doc_id: str
    text: str
    section_path: list[str]
    is_table: bool = False
    table_html: str | None = None
    provenance: ChunkProvenance
    agency_canonical_id: str | None = None
    fund_canonical_id: str | None = None
    fiscal_year: int
    doc_type: str
    publisher: str
    token_count: int
    # Observability for entity-stamper hops (chunk-shape D7). Empty when no
    # alias was applied during canonical-id resolution. Not persisted to
    # Postgres in spec §6 — sidecar metadata for audit/debugging.
    alias_chain: list[str] = Field(default_factory=list)
    fund_mentions: list[str] = Field(default_factory=list)
