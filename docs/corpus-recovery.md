# Corpus Source-Doc Recovery

**The cache is ephemeral. The manifest, discovery cache, and DB
`source_url` column are durable. Treat them that way.**

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
| `documents.source_url` (DB column) | Per-row URL. **Must always be populated** for any URL-fetchable doc. A null `source_url` = "we lost the trail." |
| `samples/raw-pdfs/agao-afr-fy25.pdf` | Checked into git (gitignore exception) because gao.az.gov is Cloudflare-protected — programmatic refetch is impossible, so the file itself is the source of truth. |

## What is NOT durable

- `data/cached-pdfs/<sha2>/<sha>.pdf` — gitignored, content-addressed.
  Always rebuildable from the manifest above.
- The on-disk presence of any worktree's cache directory.

## Recovery flow (one command)

When you find yourself looking at a fresh checkout, an empty
`data/cached-pdfs/`, or a DB whose `source_blob_path` values point at
a directory that doesn't exist, run:

```bash
DATABASE_URL=postgresql://askbudget:askbudget-dev@127.0.0.1:5432/askbudget \
  python -m scripts.redownload_cached_pdfs
```

What it does, in three phases:

1. **Discovery walk** — calls `ingest.discovery.discover()` for every
   `(publisher, doc_type, fiscal_year)` combo currently in the DB.
   Walks JLBC TOC PDFs, populates `data/discovery-cache.yaml`.
2. **Download** — walks every URL in the discovery cache, hands it to
   `DownloadCache.fetch()`. Sha-keyed, idempotent. Skips already-cached
   URLs.
3. **DB rewrite** — for every `documents` row, extracts the sha256
   from the existing `source_blob_path` basename, points the row at
   `data/cached-pdfs/<sha2>/<sha>.pdf` (project-relative), and
   backfills `source_url` from the cache manifest.

Reports:
- `not-in-cache` rows — sha exists in DB but no file shows up locally
  after the download pass. These are docs whose source URL fails to
  download (Cloudflare / requires auth / 404). Hand-acquire and place
  via the "Manual acquisition" path below.
- `sha-missing` rows — `source_blob_path` doesn't end in
  `<64-hex>.pdf`. These need a different recovery path because we
  don't know the expected hash.

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
4. Re-run `redownload_cached_pdfs.py --no-fetch` to backfill the DB
   `source_url` for that doc.

## What was wrong, what's fixed (2026-05-07)

- ✅ DB `source_url` is now populated for **381 of 382** documents.
  The one without a URL is the SB 1735 DOCX; its source path is
  `samples/raw-docx/budget-bill-sb1735-2025.docx` (checked in).
- ✅ All `documents.source_blob_path` values now use project-relative
  forms (`data/cached-pdfs/<sha2>/<sha>.pdf` or
  `samples/raw-pdfs/<file>.pdf` or `samples/raw-docx/<file>.docx`).
- ✅ `data/cached-pdfs/manifest.yaml` has 388 entries covering every
  doc the script could place in the cache, including the two
  manual-acquisition AFR / Governor's SAD PDFs.

## Verifying recovery posture (run before any DB dump or worktree cleanup)

```sql
-- Every URL-fetchable row should have a source_url.
SELECT COUNT(*) FROM documents
WHERE source_format = 'pdf' AND (source_url IS NULL OR source_url = '');
-- Expected: 0.

-- No row should reference a path outside the project tree.
SELECT doc_id, source_blob_path FROM documents
WHERE source_blob_path LIKE 'C:%' OR source_blob_path LIKE '/%';
-- Expected: 0 rows.
```

If either query returns > 0, recovery posture is degraded and a fresh
dump will repeat the failure mode. Run `redownload_cached_pdfs.py`
to repair before snapshotting.
