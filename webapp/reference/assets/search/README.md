# Vendored mockup search engine (reference only — never served)

Vendored 2026-07-29 at Destin's direction: the mockup's in-browser search
logic is useful input to the real retrieval stack's later tuning, and it
would otherwise die with the mockup folder.

- `search.js` (37KB) — the whole engine. Worth reading for:
  - **Report families** (`familyOf`): a Baseline/Appropriations annual report
    is published as MANY docs (whole-book variants + one page per agency +
    summary sections); the engine collapses them into one logical report for
    both filter counts and result grouping.
  - **Curated filter buckets** (`bucketOf`, `BUCKET_ORDER`): fixed 8-bucket
    taxonomy instead of ~26 raw doc_type chips; report buckets count
    distinct annual reports, not sub-pages; the headline doc count is the
    sum of the chips so the numbers always reconcile.
  - **Ranking**: query embedded in-browser, cosine blended with a keyword
    signal; keyword-only fallback when the model can't load.
  - **Canonical full-report formats**: the lookup that powers the
    "Linked Table of Contents vs Single File PDF" chooser modal.
- `index-lite.js` (2.6MB) — `window.JLBC_DOCS`: metadata for every site
  document (id, url, title, category, doc_type, fiscal_year, publisher,
  keywords, agency tokens). This is the URL map a future task will join
  against the app corpus's doc_ids to power the book-vs-agency-page
  chooser inside this app.

Deliberately NOT vendored: `index-vec.json` (3MB int8 embeddings),
`models/` (23MB), `vendor/` (44MB) — artifacts of the mockup's specific
embedding model, reproducible and not reusable logic.
