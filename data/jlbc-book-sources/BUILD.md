> **Vendored JLBC URL harvest — READ ONLY.** Snapshot date 2026-06-16,
> copied verbatim from `C:\Users\desti\JLBC Website Revamp\search-build\`
> (the website-revamp mockup's build directory). Do not edit these files by
> hand and do not treat them as live data — see this folder's README.md.

# Search index — build toolchain

This folder is the **offline build toolchain** for the site's self-contained semantic search. It is
*not* shipped; the runtime assets it produces live in `../assets/search/`.

➜ **For the as-built architecture, ranking logic, performance, and known issues, see
`../SEARCH-SYSTEM.md`.** This file is just the build/rebuild mechanics.

**After any rebuild, BUMP the `?v=N` cache-buster** in `../subpage-search_jlbc.html` (2 script tags)
and `../assets/search/search.js` (the `index-vec.json?v=N` fetch) — currently `v=34`. Otherwise
browsers serve the stale cached index. (Also bump it for renderer-only `search.js` changes, not just
index rebuilds — a returning visitor's cached `search.js` would otherwise keep the old behavior.)

**Whole-site single-file build (the shareable deliverable):** `node build-site-bundle.mjs` writes
`../JLBC-Website.html` (~5.6 MB) — the ENTIRE site (all 25 pages + working nav + search) inlined into ONE
double-clickable file via an iframe-srcdoc hash router (per-page style isolation; shared images +
`index-lite` + `search.js` stored once and injected by placeholder). Search is keyword-only there
(`about:srcdoc` ≠ http, so the model can't load); semantic search needs the page over http. Re-run it
after any change to a page, `search.js`, or `index-lite.js`. Details: `../SEARCH-SYSTEM.md` §7.

## What ships (in `../assets/search/`)
- `index-lite.js` — `window.JLBC_DOCS`, metadata for all documents (loads via `<script>`, works from file://).
- `index-vec.json` — int8 + base64 embedding vectors (fetched only for the HTTP semantic path).
- `models/Xenova/all-MiniLM-L6-v2/` — the vendored embedding model (~23 MB) + tokenizer.
- `vendor/transformers/` — transformers.js + its ONNX-Runtime WebAssembly files.
- `search.js` — the client-side search (classic script: semantic over HTTP, keyword on file://).

## Pipeline
1. **`extract-docs.mjs`** — parses every `../*.html`, pulls each real document link (title, description,
   real PDF URL, source-page category), enriches fiscal-note titles from bill numbers + subjects and
   meeting titles from the filename date code, tags each with factual topic-coverage keywords + a
   `scope` (`book` = whole report), and writes `corpus-all.json` (312 docs).
1b. **`parse-live-books.py`** — extracts the combined whole-report books (baseline books,
   appropriations reports, slideshows) from the LIVE `/prior-years/` archive page (`live-prior.html`),
   so the real, inconsistently-cased URLs are never guessed. Writes `live-books.json` (~165 books,
   **FY1984–2026**, `scope:'book'`). Recent years (FY2022–2026) the archive parse misses are pinned in
   the **`SUPP` list** (verified-200 URLs) so every FY2022–2027 report has BOTH a single-file and a
   linked-TOC variant — that uniformity is what makes the "Full report" chooser consistent. Requires
   `live-prior.html` (curl the live page) + `pip install pypdf`. (No PDF parsing here — it reads anchors
   from the HTML; pypdf is only needed by the other two Python builders.)
2. **`build-agency-pages.py`** — reads the JLBC agency-index PDFs in `idx/` and extracts each agency's real
   per-agency PDF link + name from the PDF link annotations. **Coverage: baseline FY2012–27, approps
   FY2005–26.** Modern years use `{YY}baseline/agencyindex.pdf` (baseline FY23–27) and `{YY}ar/agencyindex.pdf`
   (approps FY13–26). Older years use distinctly-named indexes that link to per-agency PDFs on the legacy
   `azleg.gov/jlbc` host (normalized to live `azjlbc.gov`, verified 200): baseline FY13–22 =
   `{YY}baseline/{YY}BaselineAgencyIndex.pdf` (FY22 = `FY2022BaselineAgencyIndex.pdf`), FY12 =
   `12book1/12BaselineAgencyIndex.pdf`; approps FY05–12 = `{YY}app/agencyindex.pdf`. The index-extractor is
   multi-page and a substring guard skips TOC/index self-links (`apprpttoc`, `…BaselineAgencyIndex`). Writes
   `agency-corpus.json` (~4,679 per-agency pages). Names resolve FY2027-baseline-first with
   first-good-name-wins (so a bad extraction in one year can't clobber a correct name from another).
   The agency file codes match ask-the-budget's agency IDs (`axs`=AHCCCS, `adc`=Corrections…),
   and search aliases are added: the 3-letter code itself (`adc`, `pio`), common acronyms
   (`ADOT`, `APH`, `ABOR`, `ASU`, `ICA`…), and topic words (`Medicaid` → AHCCCS). Distinctive
   codes/acronyms also get an exact-match `acro` bonus in `search.js` so "asu baseline" decisively
   picks ASU. Requires `pip install pypdf`.
2b. **`build-summary-sections.py`** — reads the baseline "links" PDFs + approps TOC PDFs in `idx2/`
   (`{YY}baselinelinks.pdf`, `{YY}ar/apprpttoc.pdf`), extracts the STATEWIDE SUMMARY sections — the
   generic document-level pages (`s<N>.pdf` summary, `bh<N>`/`bd<N>` budget highlights/detail, numbered
   revenue/technical sections) like "General Fund Summary by Agency", "General Appropriation Act
   Provisions", "Budget Stabilization Fund". These live ONLY in the linked TOCs (the per-agency builder
   deliberately skips them). Writes `summary-corpus.json` (~650, baseline FY12–27 + approps FY05–26,
   `scope:'summary'`). Pre-FY13 TOCs link to the dead legacy `azleg.gov/jlbc/` host — the builder
   rewrites it to the live `azjlbc.gov` (identical path, verified 200). Requires `pip install pypdf`.
3. **`build-index-all.mjs`** — embeds each doc's search text (site + books + summary + per-agency) with
   the local MiniLM model, int8-quantizes the vectors, and writes `index-lite.js` + `index-vec.json`.

## Rebuild after the site's documents change
```bash
cd search-build
UA="Mozilla/5.0"   # any browser UA
# 1. refresh source PDFs/pages (curl with --ssl-no-revoke on Windows)
curl -s --ssl-no-revoke -A "$UA" -L https://www.azjlbc.gov/prior-years/ -o live-prior.html
for y in 23 24 25 26 27; do curl -s --ssl-no-revoke -A "$UA" -L "https://www.azjlbc.gov/${y}baseline/agencyindex.pdf" -o "idx/${y}baseline.pdf"; done
for y in $(seq 13 26); do curl -s --ssl-no-revoke -A "$UA" -L "https://www.azjlbc.gov/${y}ar/agencyindex.pdf" -o "idx/${y}ar.pdf"; done
# older per-agency indexes (distinct legacy naming; per-agency PDFs resolve on azjlbc.gov via host rewrite)
for y in 13 14 15 16 17 18 19 20 21; do curl -s --ssl-no-revoke -A "$UA" -L "https://www.azjlbc.gov/${y}baseline/${y}BaselineAgencyIndex.pdf" -o "idx/${y}baseline.pdf"; done
curl -s --ssl-no-revoke -A "$UA" -L "https://www.azjlbc.gov/22baseline/FY2022BaselineAgencyIndex.pdf" -o "idx/22baseline.pdf"   # FY22 uses FY####… naming
curl -s --ssl-no-revoke -A "$UA" -L "https://www.azjlbc.gov/12book1/12BaselineAgencyIndex.pdf"        -o "idx/12baseline.pdf"   # FY12 baseline under /12book1/
for y in 05 06 07 08 09 10 11 12; do curl -s --ssl-no-revoke -A "$UA" -L "https://www.azjlbc.gov/${y}app/agencyindex.pdf" -o "idx/${y}app.pdf"; done
# baseline-links + approps-TOC PDFs for the SUMMARY sections (into idx2/). The authoritative URLs (with
# their inconsistent casing) live in the live /prior-years/ page — harvest them straight from there:
mkdir -p idx2
grep -oiE 'https://www.azjlbc.gov/[^"]*(BaselineLinks|apprpttoc)[^"]*\.pdf' live-prior.html | sort -u \
  | while read u; do fn=$(echo "$u" | sed -E 's#https://www.azjlbc.gov/##; s#/#__#g'); \
      curl -s --ssl-no-revoke -A "$UA" -L "$u" -o "idx2/$fn"; done
cp 27baselinelinks.pdf idx2/27baseline__27baselinelinks.pdf 2>/dev/null  # current year (not on /prior-years/ yet)
# 2. build
node extract-docs.mjs            # site docs -> corpus-all.json (year-enriches whole-book titles)
python parse-live-books.py       # combined books from live archive -> live-books.json
python build-summary-sections.py # statewide summary sections from idx2/*.pdf -> summary-corpus.json
python build-agency-pages.py     # per-agency pages from idx/*.pdf -> agency-corpus.json
node build-external-financials.mjs # external financial docs from manifest -> external-corpus.json
node build-index-all.mjs         # embed all five -> index-lite.js + index-vec.json (URL-deduped)
cp index-lite.js index-vec.json ../assets/search/
# 3. BUMP the cache-buster: change ?v=N in ../subpage-search_jlbc.html and ../assets/search/search.js
```
## Adding a new fiscal year / new documents

The corpus has **four** independent feeds; adding a year usually means touching three of them. Every URL
must be **verified 200 against the live site** — never guessed (casing/paths vary year to year).

**1. Per-agency pages** (`scope:'agency'`) — download the year's `agencyindex.pdf` into `idx/` and extend
the `SOURCES` ranges in `build-agency-pages.py`:
```bash
curl -s --ssl-no-revoke -A "$UA" -L "https://www.azjlbc.gov/<YY>baseline/agencyindex.pdf" -o "idx/<YY>baseline.pdf"   # baseline
curl -s --ssl-no-revoke -A "$UA" -L "https://www.azjlbc.gov/<YY>ar/agencyindex.pdf"       -o "idx/<YY>ar.pdf"         # approps
```
New agency? Add its 3-letter code + aliases to the `ALIAS` dict (and `NAME_OVERRIDE` if the link-rect
name extraction misses it). English-word codes go in `COMMON_CODE` so they stay non-decisive.

**2. Statewide summary sections** (`scope:'summary'`) — download the year's `…baselinelinks.pdf` /
`…ar/apprpttoc.pdf` into `idx2/` (the `grep | curl` loop below pulls everything the archive lists; add
the current year's links file by hand like the `cp` line does for FY27). No code change needed — the
builder globs `idx2/*.pdf`.

**3. Whole-report books** (`scope:'book'`) — older years auto-pick-up from `/prior-years/`. For the
**current / most-recent years** (not yet on the archive, or that the parse misses), add a `SUPP` entry in
`parse-live-books.py` for **both** formats so the "Full report" chooser stays uniform:
```python
("https://www.azjlbc.gov/<path>/<YY>baselinesinglefile.pdf", 20YY, "Baseline Book", "Single File"),
("https://www.azjlbc.gov/<path>/<YY>baselinelinks.pdf",      20YY, "Baseline Book", "with Links"),
("https://www.azjlbc.gov/<YY>ar/fy20YYapproprpt.pdf",        20YY, "Appropriations Report", ""),
("https://www.azjlbc.gov/<YY>ar/apprpttoc.pdf",              20YY, "Appropriations Report", "Table of Contents"),
```
The `sub` field drives `reportFormats()` detection in `search.js`: "Single File"/`approprpt`/`singlefile`
→ Single File; "with Links"/`links.pdf`/`apprpttoc`/"Table of Contents" → Linked TOC. Slideshow / exec
comparison / spreadsheet entries are fine to add but are treated as supplements (excluded from the
chooser). **Probe candidate URLs first** — e.g. `curl -sI --ssl-no-revoke <url> | head -1` — casing like
`25Baseline/` vs `22baseline/` and the rolling `/budget/...` location are real and inconsistent.

**4. Site documents** — only if the new year is also linked from the mockup HTML pages; `extract-docs.mjs`
re-parses `../*.html` automatically.

Then run the 5 build steps, copy, and **bump `?v=N`**. After rebuilding, sanity-check the year in a
browser (`bash run-search-demo.sh`, then "fy<YY> ahcccs", "<YY> appropriations report", and click "Full
report" on a grouped result to confirm both formats resolve).

**Index size note:** with the full archive the index is ~5,854 docs — `index-lite.js` ≈ 2.5 MB raw but
**≈ 250 KB gzipped**, which is what IIS sends (gzip/brotli on by default). `index-vec.json` (≈ 3.0 MB)
is fetched only in semantic mode, once, then browser-cached.
(The model + transformers vendor files only need to be copied once; they don't change.)

## External financial documents — AFR · Governor's budget · agency FY2027 submissions (5th feed — BUILT v=31)

**Status: BUILT.** Builder `build-external-financials.mjs` reads `../financial-docs-manifest.json` →
`external-corpus.json` (89 docs); `build-index-all.mjs` merges it as the 5th feed (corpus now ~5,854).
`search.js` gained three category boosts (`wantAFR` / `wantExecBudget` / `wantBudgetRequest`, +0.15 each,
parallel to the `wantBaseline`/`wantApprops` family synonyms) so the natural queries surface these. To
re-derive: `node build-external-financials.mjs && node build-index-all.mjs`, copy, bump `?v=N`.

A batch of **off-azjlbc.gov** financial documents folded into the corpus. Unlike the four feeds above
(all on `azjlbc.gov`), these come from GAO, OSPB/Governor, and ~90 individual agency websites. **The
authoritative, HTTP-verified link list is `../financial-docs-manifest.json` (+ the readable
`../FINANCIAL-DOCS-MANIFEST.md`).** Treat that manifest as the durable source of record — re-derive the
corpus from it, don't re-scrape from scratch.

Three groups (proposed field mapping):

| Group | Count | `category` | `doc_type` | `publisher` | `scope` | `fiscal_year` |
|-------|-------|-----------|-----------|-------------|---------|---------------|
| Annual Financial Reports (GAO) | 5 | `Annual Financial Report` | `Annual Financial Report` | `GAO` | `book` | 2021–2025 |
| Governor's Budget volumes (OSPB) | 6 | `Executive Budget` | `State Agency Detail` / `State Funds` | `Governor / OSPB` | `book` | 2025–2027 |
| Agency FY2027 budget submissions | 78 | `Agency Budget Request` | `Agency Budget Request` | per-agency | `agency` | 2027 |

The 78 agency submissions reuse the existing per-agency machinery: give each the agency's 3-letter code +
acronym aliases (same `ALIAS`/`acro`/`agtok` set `build-agency-pages.py` already builds) so "AHCCCS FY27
budget request" / "ADOT submission" resolve. Build good titles ("<Agency> FY2027 Budget Request") so the
year + agency-name signals fire. A new builder (e.g. `build-external-financials.mjs`) reading the manifest
is the clean way in; `build-index-all.mjs` dedupes by URL and embeds them with the rest.

### Fetch quirks (learned the hard way during the 2026-06-16 scrape — honor these or links break)

- **`.az.gov` Drupal hosts reject bare requests** (GAO, OSPB, and most agency sites WAF a plain UA → 403).
  Fetch with **full browser headers** AND the file's own origin as Referer:
  ```bash
  curl -s -L --ssl-no-revoke \
    -A "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36" \
    -H "Accept: text/html,application/pdf,*/*;q=0.8" -H "Accept-Language: en-US,en;q=0.9" \
    -e "https://<host>/" "<url>"
  ```
- **URL encoding is load-bearing — never re-encode.** The FY2021 AFR href is literally double-encoded
  (`…GRAYSCALE%2520AFR21%2520…`) and returns 200 as-is; the "fixed" single-encoded form 404s. Store and
  fetch URLs **exactly** as they appear in the manifest.
- **Dept of Homeland Security URL is tokenized** (`azdohs.gov/file/5282/download?token=…`) — the token
  expires. Don't persist it; re-fetch from `https://azdohs.gov/finance` at ingest time.
- **Criminal Justice Commission (DNN portal) 403s on a cold hotlink** — needs a session cookie primed by
  first GETting the landing page (`azcjc.gov/Programs/Finance/Budget-Strategic-Planning`) in the same
  curl jar, then the PDF.
- **Board of Pharmacy & RUCO are Google Drive files** (served `application/octet-stream`). Direct-download
  form: `https://drive.google.com/uc?export=download&id=<ID>` (IDs in the manifest notes).
- **Dept of Corrections appears twice** on the OSPB page (a direct submission + a "For JLBC" link to the
  *same* `FY 2027 Budget Request Update.pdf`) — the URL-dedup in `build-index-all.mjs` handles it; don't
  add it as two rows.
- **State Board of Tax Appeals** file is named `…_2026.pdf` but is the FY2027-cycle request — set
  `fiscal_year: 2027` deliberately, not from the filename.
- **9 agencies have no discoverable FY2027 doc** (listed in the manifest's `gaps`) — they simply hadn't
  posted FY2027 at scrape time (latest was FY2026) or hide it behind JS/Cloudflare. Re-check the manifest's
  `best_url` per agency on a later pass; don't guess filenames (every guess 404'd or soft-404'd).
- These are **big** PDFs (FY2027 State Agency Detail alone is 32 MB; the full set is ~600 MB). The index is
  **title/metadata-level** like the rest of the corpus — we link to the PDFs, we don't extract their text.
  Full-text would be the separate ask-the-budget-style content pipeline (see SEARCH-SYSTEM.md §6).

## Notes
- The model is downloaded once from a mirror and vendored locally — at runtime nothing touches the
  network (`allowRemoteModels=false`).
- `web/` is the earlier standalone proof-of-concept (18-doc demo). The real page is
  `../subpage-search_jlbc.html`.
- `node_modules/` and the model are large; this whole folder is dev-only and should be excluded from
  any distributable bundle.
