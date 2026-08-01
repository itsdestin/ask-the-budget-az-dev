# Corpus Source-Doc Recovery

> **2026-08-01 — read this first.** Plan 5 Track 4 deleted `db/` and
> `scripts/redownload_cached_pdfs.py` along with the rest of the Postgres
> architecture. **The one-command recovery flow this document used to
> describe no longer exists.** What survives is the acquisition trail
> below, which is still durable and still the thing that makes recovery
> possible; "Recovery flow" now describes the manual equivalent against
> `documents.json`. Everything phrased as "the DB" means that sidecar.

**The cache is ephemeral. The manifest, discovery cache, and the
`source_url` field in `documents.json` are durable. Treat them that way.**

This doc exists because the same failure mode has bitten the project
multiple times: a worktree gets cleaned up, its `data/cached-pdfs/`
goes with it, the DB rows still reference paths inside the now-gone
worktree, and recovery is an hours-long detective hunt for which URLs
were ingested.

## The acquisition trail (durable artifacts, all checked in)

| Artifact | Role |
|---|---|
| `data/cached-pdfs/manifest.yaml` | URL → sha256 + relative_path index. Every successful `DownloadCache.fetch()` writes here. Manual-acquisition entries (Cloudflare-protected origins) carry an `acquisition: "manual-browser-download …"` field. |
| `data/discovery-cache.yaml` | JLBC TOC walk results. URL list per (publisher, doc_type, fiscal_year) combo. Recreated from JLBC's TOC PDFs by `ingest.discovery.discover()`. |
| `samples/manifest.yaml` | Hand-curated entries for non-TOC docs (Phase 0 sample set, AGAO AFR, Governor's SAD, budget bills). URL + sha256 + local_path + acquired_on. |
| `documents.source_url` (field in `data/insight-data/documents.json`) | Per-doc URL. **Must always be populated** for any URL-fetchable doc. A null `source_url` = "we lost the trail." |
| `samples/raw-pdfs/agao-afr-fy25.pdf` | Checked into git (gitignore exception) because gao.az.gov is Cloudflare-protected — programmatic refetch is impossible, so the file itself is the source of truth. |

## What is NOT durable

- `data/cached-pdfs/<sha2>/<sha>.pdf` — gitignored, content-addressed.
  Always rebuildable from the manifest above.
- The on-disk presence of any worktree's cache directory.

## Recovery flow (manual — there is no script for this any more)

When you find yourself looking at a fresh checkout, an empty
`data/cached-pdfs/`, or `documents.json` entries whose
`source_blob_path` points at a directory that doesn't exist:

The corpus itself (`<data_dir>/lancedb` + `documents.json`) is
unaffected — **search keeps working**. What breaks is the PDF viewer,
because it streams the source file. So this is a repair job, not an
outage.

1. **Prefer copying the cache.** `data/cached-pdfs/` is content-addressed
   and machine-independent; copying it from a working machine or the
   shared drive is faster and far kinder to the state web servers than
   re-fetching ~7,400 PDFs one at a time. README.md → "Moving to a new
   device" covers it.
2. **If you must re-fetch**, drive `ingest.cache.DownloadCache.fetch()`
   over the URLs in `data/cached-pdfs/manifest.yaml` (and
   `data/discovery-cache.yaml` for anything the manifest missed). It is
   sha-keyed and idempotent, so it skips what is already present. Fetch
   politely and serially — these are state government web servers.
3. **Anything that still won't download** (Cloudflare / auth / 404) goes
   through "Manual acquisition" below.

**The deleted script did a third thing that no longer applies**: it
rewrote `source_blob_path` on every DB row. `documents.json` is written
by `ingest/lance_writer.py` with project-relative paths already, so
there is nothing to rewrite — an entry whose file is missing is a
missing *file*, not a wrong *path*.

## Manual acquisition (for Cloudflare-protected origins)

Some origins reject programmatic clients (gao.az.gov, ospb.az.gov,
azleg.gov in some configurations). The manual path:

1. Browse to the URL, save the file to your `Downloads/` folder.
2. Place into the cache:
   ```python
   from pathlib import Path
   import hashlib, shutil
   src = Path("C:/Users/<you>/Downloads/file.pdf")
   sha = hashlib.sha256(src.read_bytes()).hexdigest()
   dst = Path(f"data/cached-pdfs/{sha[:2]}/{sha}.pdf")
   dst.parent.mkdir(parents=True, exist_ok=True)
   shutil.copyfile(src, dst)
   print(sha, dst)
   ```
3. Add an entry to `data/cached-pdfs/manifest.yaml`:
   ```yaml
   "<source_url>":
     sha256: "<sha>"
     byte_size: <bytes>
     fetched_at: "<ISO8601 timestamp>"
     relative_path: "<sha[:2]>/<sha>.pdf"
     acquisition: "manual-browser-download (Cloudflare-protected origin)"
   ```
4. Make sure the doc's entry in `<data_dir>/documents.json` carries the
   same `source_url`. Re-ingesting the document through the upload page
   is the supported way to get there; hand-editing the sidecar works but
   is a last resort.

## What was wrong, what's fixed (2026-05-07)

> **2026-07-31 note:** references below to "the DB" describe the retired
> Postgres store; the live equivalent of every check here is the
> `data/insight-data/documents.json` sidecar (`source_url` /
> `source_blob_path` fields per doc), and the SQL snippets no longer run
> anywhere. The recovery *principles* (every doc re-fetchable; no
> out-of-tree paths) still hold.

- ✅ DB `source_url` is now populated for **381 of 382** documents.
  The one without a URL is the SB 1735 DOCX; its source path is
  `samples/raw-docx/budget-bill-sb1735-2025.docx` (checked in).
- ✅ All `documents.source_blob_path` values now use project-relative
  forms (`data/cached-pdfs/<sha2>/<sha>.pdf` or
  `samples/raw-pdfs/<file>.pdf` or `samples/raw-docx/<file>.docx`).
- ✅ `data/cached-pdfs/manifest.yaml` has 388 entries covering every
  doc the script could place in the cache, including the two
  manual-acquisition AFR / Governor's SAD PDFs.

## Verifying recovery posture (run before any corpus copy or worktree cleanup)

The two checks are unchanged; only the store they run against is. Both
read `<data_dir>/documents.json`:

```bash
python - <<'PY'
import json, os, pathlib
p = pathlib.Path(os.environ.get("JLBC_DATA_DIR", "data/insight-data")) / "documents.json"
docs = json.loads(p.read_text(encoding="utf-8"))
rows = docs.values() if isinstance(docs, dict) else docs

# Every URL-fetchable doc should have a source_url. Expected: 0.
no_url = [d for d in rows
          if d.get("source_format") == "pdf" and not d.get("source_url")]

# No doc should reference a path outside the project tree. Expected: 0.
absolute = [d for d in rows
            if (d.get("source_blob_path") or "").startswith(("/", "C:", "\\\\"))]

print(f"missing source_url: {len(no_url)}")
print(f"out-of-tree paths:  {len(absolute)}")
for d in (no_url + absolute)[:10]:
    print("  ", d.get("doc_id"), d.get("source_blob_path"))
PY
```

If either count is > 0, recovery posture is degraded and a fresh copy
will repeat the failure mode: those documents' PDFs cannot be re-fetched
from anything the repo knows about. Re-ingest them from their real
source before treating the corpus as canonical.
