# Phase 0 Archive — Bake-Off Artifacts

Frozen-in-time outputs from the Phase 0 extractor bake-off. Preserved as the historical record of how the per-doc-type extractor decision was reached. Not used by Phase 1+ tooling.

| File / dir | What it is |
|---|---|
| `scoring-rubric.md` | The 5-dimension 0–3 scoring scale used to grade extractor output |
| `scoring-helper.md` | Auto-generated per-page scoring checklist (output of `scripts/phase-0-archive/score_helper.py`) |
| `scoring-pages.yaml` | The ~20 representative pages picked from the corpus for grading |
| `scout-shortlist.md` | Auto-generated page-shortlist that fed `scoring-pages.yaml` (output of `scripts/phase-0-archive/scout_pages.py`) |
| `scores-opendataloader.csv` | Filled-in OpenDataLoader scores |
| `scoring-helpers/` | PNG previews with bbox overlays for ODL output (one per scored page) |
| `scoring-helpers-mineru/` | Same, for MinerU output |

The bake-off pivoted mid-investigation when both extractors proved good at different things — see `docs/superpowers/investigations/2026-05-06-phase-0-findings.md` "What actually happened" + chunk-shape decision **D4** for the per-doc-type routing outcome.

## Companion archive

Bake-off scripts live at `scripts/phase-0-archive/`. They reference paths relative to the project root that no longer match the post-archive layout — running them as-is from project root will not work without either restoring the pre-archive layout or editing the path constants. Frozen as historical record.
