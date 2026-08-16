"""Repair wrong titles in the two committed supplier files, from the corpus.

`data/jlbc-book-catalog.json` and `webapp/reference/assets/search/index-lite.js`
are both harvests of JLBC's own website index. The harvest is what produced
862 wrong titles across the corpus — e.g. `05app/bar.pdf` (the Board of
Barbers) recorded under the title of the row above it, "Agriculture, Arizona
Department of" — and that corpus-side defect has already been repaired
(identity-consistency work, 2026-08-16). But the two files above are
COMMITTED SNAPSHOTS of the original harvest, so they still carry the wrong
names, and a from-scratch re-ingest of any pre-2013 edition would re-import
them — `ingest/lance_writer.py` reads `build_title()` from the document's own
content first, but the book-discovery UI and the search page's "category ·
doc_type · FY" meta line both read straight from these two files today.

This script closes that loop: it re-derives every row's `title` from the
corpus's OWN repaired `documents.json`, joined by `source_url` — never by
row position, which is exactly the bug the harvest had. Every other field
(url, code, id, sub, category, doc_type, fiscal_year, kw, acro, scope,
agtok, …) is left untouched; only `title` is supplier data this script
trusts the corpus to correct.

The join is deliberately IDENTICAL to `app/search_provider.py::_info`'s
join — lowercased `source_url`, exact match, no fuzzy matching — so a title
that resolves correctly on the live search page resolves identically here.
A supplier row whose url isn't in the corpus (never ingested, or ingested
under a different source URL) keeps its existing title; the count of those
is reported so the gap is visible rather than silently accepted.

Run with the real corpus, e.g.:
  JLBC_DATA_DIR=/path/to/data/insight-data uv run python scripts/repair_supplier_titles.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Repo root on sys.path so `store` imports when this is run as a plain
# script (`python scripts/repair_supplier_titles.py`) rather than a module —
# same pattern as scripts/audit_chunks.py and scripts/build_fund_catalog.py.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from store import documents as store_documents  # noqa: E402
BOOK_CATALOG_PATH = ROOT / "data" / "jlbc-book-catalog.json"
INDEX_LITE_PATH = ROOT / "webapp" / "reference" / "assets" / "search" / "index-lite.js"

# Row-shaped supplier keys that carry {..., "title": ..., "url": ...} in the
# book catalog. `summary_sections` is the same shape as `per_agency` (both
# are the harvest's row records) and is exposed to exactly the same off-by-
# one risk, even though the known defect example is a per_agency row.
_BOOK_CATALOG_ROW_KEYS = ("per_agency", "summary_sections")


def _title_by_url() -> dict[str, str]:
    """lowercase source_url -> corpus title, straight from documents.json.

    Mirrors `app/search_provider.py::_info`'s join exactly: case-insensitive
    on `source_url`, first-and-only match (the live corpus was verified
    2026-08-16 to have zero duplicate source_urls, so "first wins" never
    actually has to choose between two documents). Entries with no url or
    no title are skipped — they cannot supply a title to anything.
    """
    docs = store_documents.load_documents()
    out: dict[str, str] = {}
    for meta in docs.values():
        url = meta.get("source_url")
        title = (meta.get("title") or "").strip()
        if url and title:
            out[url.lower()] = title
    return out


def _repair_rows(rows: list[dict], title_by_url: dict[str, str]) -> tuple[int, int]:
    """Mutate `title` in place on every row whose `url` matches the corpus.

    Returns (rows changed, rows with no corpus match). A row already
    carrying the correct title is not counted as "changed" — this makes the
    script's own report an honest measure of what it actually touched, not
    of how many rows it merely looked at.
    """
    changed = unmatched = 0
    for row in rows:
        url = row.get("url")
        corpus_title = title_by_url.get(url.lower()) if url else None
        if corpus_title is None:
            unmatched += 1
            continue
        if row.get("title") != corpus_title:
            row["title"] = corpus_title
            changed += 1
    return changed, unmatched


def repair_book_catalog(title_by_url: dict[str, str]) -> tuple[int, int]:
    catalog = json.loads(BOOK_CATALOG_PATH.read_text(encoding="utf-8"))
    changed = unmatched = 0
    for edition in catalog["editions"].values():
        for key in _BOOK_CATALOG_ROW_KEYS:
            c, u = _repair_rows(edition.get(key) or [], title_by_url)
            changed += c
            unmatched += u
    # WHY this exact json.dumps call (2026-08-16): it is byte-for-byte what
    # scripts/build_book_catalog.py uses to write this same committed file
    # (verified against that script's `main()`). Matching it keeps this
    # repair's diff limited to the ~900 changed title strings instead of
    # reformatting the whole 5,300-document file and making the real change
    # unreadable in review.
    BOOK_CATALOG_PATH.write_text(
        json.dumps(catalog, indent=1, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )
    return changed, unmatched


def repair_index_lite(title_by_url: dict[str, str]) -> tuple[int, int]:
    raw = INDEX_LITE_PATH.read_text(encoding="utf-8")
    # This file is NOT JSON — it is `window.JLBC_DOCS=[…];` on one line.
    # `app/search_provider.py::_load_mockup_index` parses it as
    # `raw.split("=", 1)[1].strip().rstrip(";")` then `json.loads`; the
    # prefix/partition split here must produce the same two halves or the
    # write-back below would silently stop matching that parse.
    prefix, sep, rest = raw.partition("=")
    if not sep:
        raise ValueError(f"{INDEX_LITE_PATH}: expected 'window.JLBC_DOCS=…', found no '='")
    payload = rest.strip().rstrip(";")
    entries = json.loads(payload)

    changed = unmatched = 0
    for entry in entries:
        url = entry.get("url")
        corpus_title = title_by_url.get(url.lower()) if url else None
        if corpus_title is None:
            unmatched += 1
            continue
        if entry.get("title") != corpus_title:
            entry["title"] = corpus_title
            changed += 1

    # Compact, no spaces after ','/':', matching the file as shipped (it is
    # loaded by the browser on every page view, so it was never pretty-
    # printed) and no trailing newline — the original file has none.
    new_payload = json.dumps(entries, ensure_ascii=False, separators=(",", ":"))
    INDEX_LITE_PATH.write_text(f"{prefix}={new_payload};", encoding="utf-8")
    return changed, unmatched


def main() -> int:
    title_by_url = _title_by_url()
    if not title_by_url:
        print(
            "jlbc-insight: documents.json has no usable (source_url, title) "
            "pairs — check JLBC_DATA_DIR. Nothing written.",
            file=sys.stderr,
        )
        return 1

    book_changed, book_unmatched = repair_book_catalog(title_by_url)
    index_changed, index_unmatched = repair_index_lite(title_by_url)

    print(
        f"{BOOK_CATALOG_PATH.relative_to(ROOT)}: {book_changed} titles "
        f"changed, {book_unmatched} rows with no corpus match (title left "
        "as-is)"
    )
    print(
        f"{INDEX_LITE_PATH.relative_to(ROOT)}: {index_changed} titles "
        f"changed, {index_unmatched} rows with no corpus match (title left "
        "as-is)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
