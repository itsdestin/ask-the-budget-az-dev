"""Domain primer ingestion (Phase 1a Workstream 5).

Builds the system-prompt context blob the LLM (Phase 1c) loads on every
query: a Markdown rendering of the writing-draft DOCX + Gov glossary,
plus AFR Notes ingested as their own narrative chunks under doc_id
'agao-afr-fy25-notes'.

Public surface:
  - `primer.docx_to_md.render_docx_to_markdown` — DOCX run_docx_ingest
    output → Markdown (writing draft, T5.1)
  - `primer.glossary` — Gov glossary parser (T5.2)
  - `primer.notes_chunker` — AFR Notes chunker (T5.3)
"""
