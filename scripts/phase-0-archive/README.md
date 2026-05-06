# Phase 0 Archive — Bake-Off Scripts

Helpers used during the Phase 0 extractor bake-off. Frozen as historical record; not used by Phase 1+ tooling.

| Script | Purpose |
|---|---|
| `scout_pages.py` | Scanned the corpus and shortlisted ~20 candidate pages by archetype (multi-page table, restated AFR, footnote-heavy, etc.). Output: `samples/phase-0-archive/scout-shortlist.md`. |
| `score_helper.py` | Generated the per-page scoring checklist + auto-filled rubric scores. Output: `samples/phase-0-archive/{scoring-helper.md, scores-opendataloader.csv}`. |
| `render_score_previews.py` | Rendered PNG previews of OpenDataLoader output with bbox overlays. Output: `samples/phase-0-archive/scoring-helpers/`. |
| `render_mineru_previews.py` | Same, for MinerU output. Output: `samples/phase-0-archive/scoring-helpers-mineru/`. |

These scripts have hardcoded paths (e.g., `Path("samples/scoring-pages.yaml")`) referencing the pre-archive layout. They will not run as-is from the project root after archiving — restore the original paths or edit the constants if you need to re-run them.

The reusable Phase 1 scripts (`run_mineru.py`, `run_opendataloader.py`, `run_docx_ingest.py`, `build_agency_catalog.py`, `download_jlbc_indexes.py`, `sweep_entities.py`, `check_corpus_manifest.py`) remain at `scripts/`.
