# Vendored JLBC URL harvest — READ ONLY

**Snapshot date: 2026-06-16.** Copied verbatim from
`C:\Users\desti\JLBC Website Revamp\search-build\` (the website-revamp
mockup's build directory). Do not edit these files by hand and do not treat
them as live data.

## Why they're here

`scripts/build_book_catalog.py` turns them into `data/jlbc-book-catalog.json`,
the verified edition catalog that drives "Add a JLBC book". They are vendored
for the same reason `webapp/reference/` is: the mockup lives outside this
repo, on one machine, with no guarantee of surviving a reinstall — and this
harvest is not cheaply reproducible. It represents a crawl of azjlbc.gov that
verified every URL returned 200, across ~6 different URL naming eras spanning
FY1984–FY2027.

That verification is the whole value. The mockup's own build rule is **"never
guess URLs — verify 200 or don't ship"**, and per-agency filenames are not
derivable: the agency roster shifts year to year, casing is inconsistent
*within* a single edition, and two dead legacy hosts appear inside older PDFs.
A catalog built from a live crawl is the only honest source for which
editions exist and where their children live.

## What each file is

| File | What it holds |
|---|---|
| `live-books.json` | Whole-book URLs (single file / linked TOC / slideshow supplements), one record per book PDF |
| `agency-corpus.json` | Every per-agency child PDF, id-prefixed `ag-{directory}-{agencycode}` — this is the child roster AND the directory prefix per edition |
| `summary-corpus.json` | Statewide summary sections (`s{N}`, `bd{N}`, `bh{N}`, capital outlay, …) |
| `toc-urls.txt` | The 37 authoritative linked-TOC URLs |
| `sum-status.txt` | Liveness proof (HTTP status) for all harvested summary URLs |
| `idx-manifest.txt` | Generated here: the filenames under the mockup's `idx/` and `idx2/` directories. The `idx2/` names encode each edition's TOC URL — every `__` is a `/`. The PDFs themselves (~9 MB) are deliberately NOT vendored |
| `BUILD.md` | The mockup's own build notes — the citation for how this harvest was produced |

## What is NOT here

The harvested PDFs. `ingest/book_discovery.py` re-fetches what it needs at
ingest time; storing 9 MB of index PDFs to avoid a handful of HTTP requests
would be a bad trade.
