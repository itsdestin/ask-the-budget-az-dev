---
title: Publisher portals — canonical entry points for budget docs
date: 2026-05-07
status: complete
authors: Destin Moss, Claude
audience: future-Claude sessions picking up volume ingest, multi-year backfill, or new publishers
---

# Publisher portals

Catalogues the four publisher-side landing pages that every Phase 1+ ingest URL traces back to. Useful when JLBC reissues a TOC PDF, when a new fiscal-year drop lands, or when adding a new doc-type to `data/ingest-plan.yaml`.

The specific PDF URLs themselves live in `samples/manifest.yaml` (singletons, with SHA256 + page_count) and are TOC-walked from `data/cached-pdfs/manifest.yaml` for JLBC sub-docs. This doc just names the portals — the things to load in a browser when you need to find a new URL.

## Portals by publisher

| Publisher | Portal URL | Programmatic access? |
|---|---|---|
| **JLBC** (current FY) | https://www.azjlbc.gov/current-year/ | curl-friendly; TOC PDFs scrapable |
| **JLBC** (prior FYs) | https://www.azjlbc.gov/prior-years/ | curl-friendly; same shape per FY |
| **Governor / OSPB** | https://ospb.az.gov/governors-budget-requests | curl-friendly; PDF listing in raw HTML |
| **AGAO (General Accounting Office)** | https://gao.az.gov/financials/afr | **Cloudflare-protected**; programmatic clients hit `cf-mitigated: challenge` |
| **Legislature (bills)** | not portal-driven; primary sources arrive as DOCX uploads | n/a; commit to `samples/raw-docx/` |

## URL patterns

- **JLBC TOCs:** `https://www.azjlbc.gov/<YY>baselinelinks.pdf`, `https://www.azjlbc.gov/<YY>ar/apprpttoc.pdf`, `https://www.azjlbc.gov/<YY>baseline/agencyindex.pdf`. Walk via `ingest.discovery.walk_baseline_links / walk_approps_toc / walk_agency_index`.
- **JLBC sub-docs:** `https://www.azjlbc.gov/<YY>baseline/<slug>.pdf` (s-PDFs, per-agency), `https://www.azjlbc.gov/<YY>ar/<slug>.pdf` (bh/bd/page-keyed).
- **OSPB:** `https://ospb.az.gov/sites/default/files/<YYYY-MM>/<doc-name>-fy-<YYYY>.pdf`. The `<YYYY-MM>` prefix is the publication date, not the fiscal year. FY27 docs landed in `2026-01/`.
- **AGAO AFR:** `https://gao.az.gov/sites/default/files/<YYYY-MM>/AFR<YY>%20COMBINED%20with%20Transmittal%20Letter.pdf`. The `<YY>` is two-digit FY.

## AGAO Cloudflare workaround

Programmatic fetch (curl, PowerShell `Invoke-WebRequest`, Python `httpx` even with full browser headers) hits a Cloudflare bot challenge that returns 403 with `cf-mitigated: challenge`. The portal listing page (`/financials/afr`) is gated similarly.

Workaround: open the portal in a browser, right-click the AFR link, save the PDF locally to `samples/raw-pdfs/agao-afr-fy<YY>.pdf`, and add an entry to `samples/manifest.yaml` with the file's SHA256. The ingest plan's local-path branch picks it up from there.

`samples/manifest.yaml` already has FY25 declared with the right SHA; the FY24 and FY23 AFRs (URLs at `gao.az.gov/sites/default/files/2024-11/AFR24...pdf` and `2023-11/AFR23...pdf`) are not yet listed — add them when multi-year backfill (Phase 1.5) starts.

## Adding a new doc to the corpus

1. Find the URL via the appropriate portal above.
2. If JLBC and TOC-discoverable, no manifest entry needed — just add a target row to `data/ingest-plan.yaml` and `discover()` walks it.
3. If a singleton (Gov / AGAO / Legislature bill / JLBC singlefile), add an entry to `samples/manifest.yaml` (with `id`, `publisher`, `doc_type`, `fiscal_year`, `title`, `source_url`, `source_format`, `sha256`, `page_count`, `local_path`, `acquired_on`) AND add a target row to the plan with `local_path` pointing at where you'll save the file. Run `uv run python scripts/check_corpus_manifest.py` to verify the SHA matches.
4. For AGAO specifically: download via browser; programmatic clients won't work.
