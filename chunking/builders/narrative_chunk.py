"""Narrative chunk builder.

Per chunk-shape D5: target ~512 tokens, hard max 1024. Paragraph-level
merge — never split mid-paragraph (entity boundaries inside a single
paragraph break retrieval signal).

Algorithm:
  1. Walk the document outline tree depth-first. For each node, gather the
     `Paragraph` blocks in its `body_blocks` list (skips `Table` and
     `Image` blocks — tables are handled by `table_chunk.build_table_chunk`).
  2. Within each section, greedily merge consecutive paragraphs into a
     buffer. Flush when the buffer's token count crosses the 512 target
     OR when the next paragraph would push the total past 1024.
  3. Each emitted chunk's text begins with the section path (section >
     subsection > ...) so the embedding signal carries the surrounding
     heading context.
  4. Any paragraph not reachable from the outline tree (typically: it
     precedes the FIRST heading anywhere in the document — the mineru/odl
     readers' `_build_outline` never attaches such a block to any
     `OutlineNode`, since its parse stack starts empty) is recovered from
     the raw page blocks and emitted as trailing chunks with an empty
     `section_path`, appended AFTER every outline-derived chunk and flushed
     at page boundaries (never token limits alone — see the WHY comment at
     the call site). See `_orphaned_paragraphs`.

Section path is the breadcrumb of outline-node texts from root to current
node, identical to what `ExtractedDocument.outline_path` would return for
content matched inside this section.
"""
from __future__ import annotations

import logging

from chunking.builders._tokens import count_tokens
from chunking.builders.table_chunk import DocMeta
from chunking.readers.types import (
    ExtractedDocument,
    Heading,
    OutlineNode,
    Paragraph,
)
from chunking.types import Chunk, ChunkProvenance, ProvenanceLine

log = logging.getLogger(__name__)

NARRATIVE_TARGET_TOKENS = 512
NARRATIVE_MAX_TOKENS = 1024


def build_narrative_chunks(
    doc: ExtractedDocument,
    doc_meta: DocMeta,
    *,
    start_index: int = 0,
) -> list[Chunk]:
    """Walk the document outline and emit narrative chunks.

    `start_index` lets the orchestrator interleave narrative + table chunks
    under one zero-padded sequence per doc.
    """
    chunks: list[Chunk] = []
    next_index = start_index

    def emit(
        text: str,
        *,
        section_path: list[str],
        first_para: Paragraph,
        member_paras: list[Paragraph],
    ) -> None:
        nonlocal next_index
        token_count = count_tokens(text)
        if token_count > NARRATIVE_MAX_TOKENS:
            log.warning(
                "narrative chunk exceeds %d tokens (%d) — chunk_id=%s, "
                "section_path=%s",
                NARRATIVE_MAX_TOKENS,
                token_count,
                f"{doc_meta.doc_id}-{next_index:04d}",
                section_path,
            )
        # WHY union, not first-paragraph bbox: the stored bbox is the strict
        # search region the PDF viewer highlights inside, and a merged chunk
        # cites values from ANY member paragraph. Measured 2026-08-18 on a
        # live run: 46/137 correctly linked figures sat outside the stored
        # (first-paragraph-only) bbox. Unioning same-page members makes the
        # region cover the chunk's own text. Other-page members contribute
        # NOTHING to the rectangle — a bbox is a region on ONE page and a
        # cross-page union would be a nonsense rectangle; the per-paragraph
        # `lines` below carry those pages for the locate endpoint.
        same_page = [
            p for p in member_paras if p.bbox and p.page == first_para.page
        ]
        if same_page:
            bbox = [
                min(p.bbox.x0 for p in same_page),
                min(p.bbox.y0 for p in same_page),
                max(p.bbox.x1 for p in same_page),
                max(p.bbox.y1 for p in same_page),
            ]
        elif first_para.bbox:
            bbox = [
                first_para.bbox.x0,
                first_para.bbox.y0,
                first_para.bbox.x1,
                first_para.bbox.y1,
            ]
        else:
            bbox = None
        # Per-paragraph locators for the locate endpoint (spec L1). Only
        # paragraphs carrying a bbox are useful as search regions; a line
        # without one would just re-state the chunk's page.
        lines = [
            ProvenanceLine(
                text=p.text,
                page=p.page,
                bbox=[p.bbox.x0, p.bbox.y0, p.bbox.x1, p.bbox.y1],
            )
            for p in member_paras
            if p.bbox
        ] or None
        chunks.append(
            Chunk(
                chunk_id=f"{doc_meta.doc_id}-{next_index:04d}",
                doc_id=doc_meta.doc_id,
                text=text,
                section_path=section_path,
                is_table=False,
                table_html=None,
                provenance=ChunkProvenance(
                    page=first_para.page,
                    bbox=bbox,
                    lines=lines,
                ),
                fiscal_year=doc_meta.fiscal_year,
                doc_type=doc_meta.doc_type,
                publisher=doc_meta.publisher,
                token_count=token_count,
            )
        )
        next_index += 1

    def visit(node: OutlineNode, ancestors: list[str]) -> None:
        section_path = ancestors + [node.text]
        # Body paragraphs in this node only (outline_path filtering)
        paragraphs = [b for b in node.body_blocks if isinstance(b, Paragraph)]
        if paragraphs:
            _flush_section_into_chunks(
                paragraphs=paragraphs,
                section_path=section_path,
                emit=emit,
            )
        for child in node.children:
            visit(child, section_path)

    for root in doc.outline:
        visit(root, [])

    # WHY: measured on 300 random per-agency PDFs, 5.1% of extracted prose
    # characters (56.7% of documents) are dropped here, silently — a
    # paragraph before the FIRST heading in the document is never attached
    # to any OutlineNode (see the readers' `_build_outline`), so the walk
    # above never sees it. On a JLBC agency page that's the AGENCY
    # DESCRIPTION paragraph; for a page with no heading at all (real corpus
    # example: jlbc-baseline-fy2022-hla) it is 100% of the page's narrative.
    # Recovered from doc.pages (the readers never remove blocks from Page
    # objects — only the outline tree omits them) and appended AFTER every
    # outline-derived chunk above, using the same running `next_index`, so
    # every chunk_id that existed before this fix keeps its exact index and
    # text — eval ground truth (eval/queries.yaml and friends) pins
    # chunk_ids, and the tool that used to re-bind stale ones was deleted
    # with nothing to replace it (CLAUDE.md "measurement discipline").
    orphans = _orphaned_paragraphs(doc)
    if orphans:
        _flush_section_into_chunks(
            paragraphs=orphans,
            # WHY empty, not ["preamble"]: there genuinely is no section —
            # the orphan bucket exists BECAUSE no heading claimed these
            # paragraphs. A synthetic "preamble" label is analyst-visible
            # (RetrieveView.tsx renders section_path as a breadcrumb) and is
            # fed into entity/fund resolution as a name candidate
            # (entity_stamper._resolve / _resolve_funds scan section_path).
            # For a document whose entire body is recovered this way (a
            # no-heading AFR), every chunk's breadcrumb would read
            # "preamble" — actively wrong, not just uninformative. `[]` is
            # the honest representation; both consumers already handle it
            # (RetrieveView checks `section_path.length > 0` before
            # rendering, table_chunk._build_text checks `if section_path:`
            # for the identical no-section case on the table side).
            section_path=[],
            emit=emit,
            # No "preamble" header line in the chunk TEXT either — mirrors
            # the DOCX precedent (_build_docx_chunks / _docx_section_text),
            # which never prefixes a heading line for its synthetic
            # no-heading section either. Doubly right here: the JLBC prose
            # already opens with its own explicit label ("AGENCY
            # DESCRIPTION — ..."), so a second synthetic one would just be
            # noise ahead of it in the embedding text.
            include_header=False,
            # WHY: an orphan bucket is unbounded by construction — for a
            # document whose reader finds NO heading at all (a real AFR
            # shape), it is the entire document, and the token targets
            # alone don't bound how many PAGES a chunk spans. Measured on
            # the live corpus: agao-afr-fy2023-0019 held 70 paragraphs
            # drawn from pages 2-175 in one chunk, stamped
            # provenance.page=2 (the first paragraph's page, per `emit`).
            # Invariant 1 requires every citation to resolve to an exact
            # PDF page + bbox; a citation into text physically on page 175
            # would send the viewer to page 2, the strict-bbox search would
            # find nothing there, and the analyst sees "couldn't pinpoint"
            # on a claim that is actually well-sourced. This does NOT apply
            # to the ordinary outline walk above — an outline section can
            # legitimately span pages (its heading is the true anchor for
            # the whole section) and that is unchanged here; only the
            # orphan bucket has no such anchor to justify spanning pages.
            flush_on_page_change=True,
        )

    return chunks


def _orphaned_paragraphs(doc: ExtractedDocument) -> list[Paragraph]:
    """Body paragraphs that are not reachable from any OutlineNode.

    Computed as a SET DIFFERENCE — every `Paragraph` across `doc.pages`,
    minus every `Paragraph` reachable via `body_blocks` from the outline
    tree, by object identity — rather than by re-deriving the readers'
    "before the first heading" stack invariant. An earlier version of this
    function re-derived that invariant (walk blocks in document order,
    collect Paragraphs until the first Heading) and was correct today, but
    it would DRIFT SILENTLY if a future reader ever seeded its outline
    stack differently (e.g. with a synthetic root node) — the orphan set
    would quietly go empty with no test failing, because nothing here would
    observe the tree actually built; it would only observe how this
    function assumes the tree gets built. A set difference cannot drift
    that way: it always answers "what's on the page that the actual
    outline doesn't claim", regardless of how the tree was constructed.
    Measured equivalent to the prior form on 306 real documents (every AFR
    and Governor budget included) before choosing this. `doc.pages` still
    holds every block regardless of outline membership (the readers only
    omit blocks from the tree, they never mutate `Page.blocks`), so nothing
    here needs either reader to change.
    """
    reachable_ids = {
        id(block)
        for node in _iter_outline_nodes(doc.outline)
        for block in node.body_blocks
        if isinstance(block, Paragraph)
    }
    return [
        block
        for page in doc.pages
        for block in page.blocks
        if isinstance(block, Paragraph) and id(block) not in reachable_ids
    ]


def _iter_outline_nodes(nodes: list[OutlineNode]):
    """Depth-first walk of every OutlineNode in the tree, root and child alike."""
    for node in nodes:
        yield node
        yield from _iter_outline_nodes(node.children)


def _flush_section_into_chunks(
    *,
    paragraphs: list[Paragraph],
    section_path: list[str],
    emit,
    include_header: bool = True,
    flush_on_page_change: bool = False,
) -> None:
    """Greedy paragraph-merge until target/max thresholds are crossed.

    `include_header=False` suppresses the " > ".join(section_path) line
    that otherwise opens every chunk's text — `section_path` itself is
    still passed through to `emit` untouched, so the Chunk's structural
    metadata is unaffected. Used for the synthetic preamble bucket only.

    `flush_on_page_change=True` adds a PAGE boundary as a third flush
    trigger, alongside (not instead of) the token target/max — see the WHY
    at the orphan call site in `build_narrative_chunks` for the measured
    corpus evidence. Used for the orphan bucket only; an ordinary
    heading-anchored section may legitimately span pages under its
    heading's anchor and is unaffected (this function's other caller never
    sets it).
    """
    section_header = " > ".join(section_path) if include_header else ""
    buffer_paragraphs: list[Paragraph] = []
    buffer_text_parts: list[str] = []
    buffer_tokens = count_tokens(section_header) if section_header else 0
    buffer_page: int | None = None

    def flush() -> None:
        nonlocal buffer_paragraphs, buffer_text_parts, buffer_tokens, buffer_page
        if not buffer_paragraphs:
            return
        text = section_header + "\n\n" + "\n\n".join(buffer_text_parts) if section_header else "\n\n".join(buffer_text_parts)
        emit(
            text,
            section_path=section_path,
            first_para=buffer_paragraphs[0],
            member_paras=list(buffer_paragraphs),
        )
        buffer_paragraphs = []
        buffer_text_parts = []
        buffer_tokens = count_tokens(section_header) if section_header else 0
        buffer_page = None

    for para in paragraphs:
        para_tokens = count_tokens(para.text)
        # If a single paragraph by itself exceeds the max, flush whatever's
        # buffered and emit the oversize paragraph alone — never split a
        # paragraph across chunks.
        if para_tokens > NARRATIVE_MAX_TOKENS:
            flush()
            emit(
                (section_header + "\n\n" + para.text) if section_header else para.text,
                section_path=section_path,
                first_para=para,
                member_paras=[para],
            )
            continue

        # Page-boundary flush BEFORE the token check: a chunk that crossed
        # a page must never absorb one more paragraph from a later page
        # just because there's still room under the token target. Checked
        # first so it wins outright — the token check below is then a
        # no-op on an already-empty buffer.
        if flush_on_page_change and buffer_paragraphs and para.page != buffer_page:
            flush()

        # If adding this paragraph would push the buffer past the target AND
        # the buffer already contains content, flush first.
        if buffer_paragraphs and buffer_tokens + para_tokens > NARRATIVE_TARGET_TOKENS:
            flush()

        if not buffer_paragraphs:
            buffer_page = para.page
        buffer_paragraphs.append(para)
        buffer_text_parts.append(para.text)
        buffer_tokens += para_tokens

    flush()
