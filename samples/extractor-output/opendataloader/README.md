# OpenDataLoader-PDF — Phase 0 setup notes

## Why this extractor

OpenDataLoader-PDF was selected as MinerU's bake-off opponent after
Docling proved unworkable on Destin's Windows machine:

- **`docling-parse` v5.3.x `std::bad_alloc`** — open regression
  ([docling-parse #227](https://github.com/docling-project/docling-parse/issues/227)),
  no fix as of May 2026.
- **OS-level hang from `ProcessPoolExecutor` × Windows Defender** —
  every spawn re-scanned ~110 MB of native DLLs; `docling --help` itself
  exceeded 60 s on a clean install.

Documented Docling workarounds (PyPdfium backend swap + manual Defender
exclusions) ship a downgraded extractor and don't address the
docling-parse regression. We pivoted instead.

## What we got

- Apache-2.0 license — fits the "no money" constraint.
- Pure JDK 11+ runtime; the Python package wraps a Java CLI. No PyTorch,
  no model downloads, no GPU.
- Bbox per element is the headline design feature — every output record
  carries `bounding box: [x0, y0, x1, y1]` in PDF user-space coordinates.
- XY-Cut++ reading-order algorithm specifically targets multi-column
  layouts (matters for AZ budget docs).
- Headline benchmark: 0.928 table accuracy vs Docling 0.882 (per the
  v2.4.1 release notes, April 30 2026).

## Install

```bash
uv add opendataloader-pdf
```

Resolved cleanly into the existing env. JDK 11+ requirement satisfied
by Microsoft OpenJDK 17 (`C:\Program Files\Microsoft\jdk-17.0.18.8-hotspot\`)
already on PATH.

## Smoke test (AFR FY25, page 1)

```bash
uv run python scripts/run_opendataloader.py \
  --pdf samples/raw-pdfs/agao-afr-fy25.pdf \
  --out samples/extractor-output/opendataloader/agao-afr-fy25 \
  --pages 1
```

**Wall-clock: ~10 seconds** (vs MinerU's 2m26s on the same page).

Output: 17 blocks across 3 element types (12 paragraph, 3 image, 2
heading). 100% of blocks carry a bbox; 14 of 17 carry font metadata; 2
of 2 headings carry both PDF-semantic level (`Doctitle`, `Subtitle`)
and a numeric `heading level`.

The synthesized Markdown reads cleanly — heading detection promotes
"Katie Hobbs" / "Elizabeth Alvarado-Thorson" to `# headers` from PDF
structure tags, and reading order is correct top-to-bottom on a
single-column governor's transmittal letter.

## Per-element fields observed

| Field | Always present? | Notes |
|---|---|---|
| `type` | yes | `paragraph` / `heading` / `image` (others possible on table-heavy pages — see Task 5) |
| `id` | yes | Stable element ID inside the document |
| `page number` | yes | 1-indexed (note: literal key has a space) |
| `bounding box` | yes | `[x0, y0, x1, y1]` in PDF user-space points |
| `content` | text-bearing only | Missing on images |
| `font` / `font size` | text-bearing only | |
| `text color` | text-bearing only | RGB triple as a stringified list |
| `heading level` | headings only | Numeric (1-6) |
| `level` | headings only | PDF structure-tag name (`Doctitle`, `H1`, etc.) |
| `source` | images only | Path to the extracted PNG/JPEG |

## Wrapper design

`scripts/run_opendataloader.py` mirrors `scripts/run_mineru.py`'s
per-page contract so downstream scoring (Task 5–9) can treat the two
extractors interchangeably:

- One `convert()` call per `run_opendataloader()` invocation — no
  per-range subprocess loop. The Java CLI accepts `pages="1,3,5-7"`
  natively.
- Output: `<out>/page-N.json` (with `extractor`, `source_pdf`, `page`,
  `blocks`) + `<out>/page-N.md` (synthesized from element `content`,
  with `# headers` for heading types).
- Image side-effects copied from the temp dir to `<out>/<stem>_images/`
  so `source` paths in JSON records still resolve.
- `--dry-run` flag for tests — same shape as MinerU's dry-run.

## Open questions deferred to Task 5

- How does table extraction look on JLBC budget grids? (Default
  `table_method` is border-based; `cluster` is also available.)
- How clean is reading order on the multi-column Baseline Book
  agency-detail pages?
- Do we hit any PDFs that need `use_struct_tree=True` or `--include-header-footer`?
