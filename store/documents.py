"""The one reader for `<data_dir>/documents.json` (Plan 5 Task 19).

`documents.json` is the per-document metadata sidecar written by
`ingest/lance_writer.py` — title, publisher, doc_type, fiscal_year,
source_format, source_blob_path, source_url, page_count. It is what
lets the PDF viewer find a file and what gives a search row a readable
name. `store/config.py` owns its PATH and its WRITER; this module owns
reading it.

Before this, four modules parsed it with four caches: `harness/tools.py`,
`app/search_provider.py`, `app/routes/pdf.py` (which at least borrowed
the harness's) and `ingest/lance_writer.py`. They had already drifted in
three ways, and each divergence is preserved here deliberately rather
than averaged away:

* **mtime resolution.** One stamped `st_mtime` (float seconds), the other
  `st_mtime_ns`. Nanoseconds wins: a rewrite inside one filesystem tick
  is exactly what a fast local ingest looks like, and the float version
  would serve stale titles with no symptom.
* **corrupt-file policy.** The read paths degrade to `{}` so search keeps
  working; the WRITE path raises, because it does a read-modify-write and
  degrading there would overwrite the corrupt file with a fresh one,
  orphaning every PDF in the viewer. `strict=` selects.
* **the `ingested_at` title gate.** `app/search_provider.py` applied it;
  `harness/tools.py` did not. It stays OPTIONAL — see `title_for`.
"""
from __future__ import annotations

import json
import sys
import threading
from copy import deepcopy
from typing import Any

from store import config

# WHY resolved through the module rather than `from store.config import
# documents_path`: a module-level binding is captured at import time, so a
# test that monkeypatches `store.config.documents_path` would have no effect
# here — the reader would keep pointing at the real data dir while the test
# believed it was reading a tmp file. Two existing suites patch exactly that
# name.
def documents_path():
    return config.documents_path()

# Slug parts that are acronyms, not words — `.capitalize()` renders them
# "Jlbc" / "Afr". This tuple used to exist in three files, kept
# "character-identical" by hand so no two layers showed a different title
# for the same document. Now there is one.
_SLUG_ACRONYMS = ("jlbc", "agao", "afr", "sad")

_lock = threading.Lock()
_cache: dict[str, dict[str, Any]] = {}
# (path, mtime_ns, size) of the file the cache was built from. All three
# matter: mtime+size catch a rewrite, and the path catches JLBC_DATA_DIR
# being repointed at a different corpus mid-process.
_stamp: tuple[str, int, int] | None = None


def sidecar_stamp() -> tuple[str, int, int] | None:
    """(path, mtime_ns, size) of documents.json, or None if unreachable.

    Exposed because `app/search_provider.py` caches a *derived* structure —
    the sidecar joined by URL to the vendored mockup index — and needs to
    know when to rebuild that join. It must use the SAME staleness rule as
    the loader, or the two caches drift and the page shows titles from one
    generation of the file with links from another.
    """
    try:
        st = documents_path().stat()
    except OSError:
        return None
    return (str(documents_path()), st.st_mtime_ns, st.st_size)


def reset_documents_cache() -> None:
    """Force the next read to re-stat and re-parse.

    Test-only in normal operation, but also the escape hatch if a caller
    ever needs to be certain it is not looking at a cached parse.
    """
    global _cache, _stamp
    with _lock:
        _cache, _stamp = {}, None


def load_documents(*, strict: bool = False) -> dict[str, dict[str, Any]]:
    """Parsed `documents.json`, cached until the file changes on disk.

    Returns a DEEP COPY. The cache is shared by every request in a process
    that serves the whole office, so a caller that mutated its result would
    change what the next request sees.

    That copy is not free — the live corpus is 3,527 records — so anything
    that just needs to LOOK something up should use `document_record`,
    `title_for` or `titles_for`, which read the cache in place and copy at
    most one record. Copying the whole map per title lookup is quadratic
    over a result page.

    `strict=False` (the read path) degrades a missing OR unparseable file
    to `{}` and says why on stderr — a search with generated titles beats
    a search that 500s.

    `strict=True` (the write path — `ingest/lance_writer.py`) raises
    `RuntimeError` on an unparseable file, and re-validates rather than
    trusting the cache. A missing file is still `{}`, because the very
    first ingest into a fresh data dir legitimately creates one; the
    distinction is absent-vs-corrupt, not first-run-vs-later.
    """
    return deepcopy(_load_cached(strict=strict))


def _load_cached(*, strict: bool = False) -> dict[str, dict[str, Any]]:
    """The cached parse itself — NOT copied. Internal; never hand this out.

    Every public accessor either copies what it returns or returns an
    immutable value derived from it.
    """
    global _cache, _stamp
    path = documents_path()
    try:
        st = path.stat()
        stamp: tuple[str, int, int] | None = (str(path), st.st_mtime_ns, st.st_size)
    except OSError:
        stamp = None  # absent, or the share is unreachable

    with _lock:
        if stamp is None:
            _cache, _stamp = {}, None
            return {}
        # WHY strict skips the cache-hit shortcut: a good read can prime the
        # cache and the file can be corrupted afterwards. Serving the cached
        # copy would let the writer merge into it and overwrite the very
        # corruption strict= exists to refuse.
        if stamp == _stamp and not strict:
            return _cache
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict):
                raise ValueError(
                    "expected a JSON object of doc_id -> metadata, got "
                    f"{type(loaded).__name__}"
                )
        except OSError as err:
            if strict:
                # Do NOT cache the failure — the next attempt must re-read.
                # WHY this differs from the ValueError branch below: an
                # OSError here is a sharing violation, a dropped share or a
                # permission problem — the file is very probably FINE, so
                # telling the reader to restore it from a snapshot is wrong
                # advice that risks discarding a good sidecar.
                raise RuntimeError(
                    f"{path} could not be read ({err}). Retry the write; if "
                    "it keeps failing, check the share."
                ) from err
            # A share blip, a sharing violation, a half-replaced file: keep
            # whatever was cached and FORGET the stamp, so the next call
            # re-reads. Caching {} under the good stamp (the pre-2026-08-25
            # behaviour) blanked every title until the next ingest.
            print(
                f"store.documents: could not read {path} ({err}) — will retry.",
                file=sys.stderr,
            )
            _stamp = None
            return _cache
        except ValueError as err:
            if strict:
                raise RuntimeError(
                    f"{path} is not valid JSON ({err}). Restore it from a "
                    "corpus snapshot before ingesting — writing a fresh one "
                    "over it would orphan every PDF in the viewer."
                ) from err
            print(
                f"store.documents: ignoring {path} ({err}) — document titles "
                "fall back to doc_id slugs and source links are unavailable. "
                "Restore it from a corpus snapshot.",
                file=sys.stderr,
            )
            loaded = {}
        _cache, _stamp = loaded, stamp
        return loaded


def document_record(doc_id: str) -> dict[str, Any] | None:
    """One document's metadata, or None if it isn't in the sidecar.

    Non-dict entries read as None. A hand-edited sidecar can hold
    anything, and callers index into this result — a bare string would
    raise deep inside a route rather than at the lookup.

    Copies the ONE record, not the whole map: callers do mutate what they
    get back, but copying 3,527 records to hand back one is the difference
    between a lookup and a scan.
    """
    record = _load_cached().get(doc_id)
    return deepcopy(record) if isinstance(record, dict) else None


def humanize_doc_id(doc_id: str) -> str:
    """FALLBACK title: 'jlbc-baseline-fy2027-axs' -> 'JLBC Baseline FY 2027 Axs'.

    Only good enough to be recognisable. A real ingest title
    ("FY 2027 Baseline — Industrial Commission of Arizona") is derived
    from the document's CONTENT and is much better, which is why the
    sidecar wins whenever it knows the document.
    """
    out: list[str] = []
    for part in doc_id.split("-"):
        if part.startswith("fy") and part[2:].isdigit():
            out.append(f"FY {part[2:]}")
        elif part in _SLUG_ACRONYMS:
            out.append(part.upper())
        else:
            out.append(part.capitalize())
    return " ".join(out)


def sidecar_title(
    meta: dict[str, Any] | None, *, require_ingested: bool = False
) -> str | None:
    """The sidecar's own title for one entry, or None to fall back.

    `require_ingested=True` reproduces `app/search_provider.py`'s gate:
    trust the title only for documents Plan 3's ingest wrote. The
    migration derived titles from doc_ids, and its worst output ("AGAO
    FY2025 fy2025") is worse than the humanizer. `ingested_at` is the
    discriminator — the migration's field set never carried it, and every
    ingest-written entry has it.
    """
    if not isinstance(meta, dict):
        return None
    if require_ingested and not meta.get("ingested_at"):
        return None
    return (meta.get("title") or "").strip() or None


def title_for(doc_id: str, *, require_ingested: bool = False) -> str:
    """Display title for a doc_id — sidecar title, else the humanizer.

    **`require_ingested` defaults to False, and that asymmetry is
    deliberate.** The gate is right on the search page, where the vendored
    mockup index is the primary title source and this is only the tiebreak
    for the handful of documents the index never covered. It is WRONG
    everywhere the sidecar is the only source — the live corpus holds 378
    migration-era entries and most of their titles are fine ("JLBC FY2025
    — African-American Affairs, Arizona Commission of"). Gating those
    would replace a real agency name with "Jlbc Approps FY 2025 Aam" in AI
    Mode's answers, where an ugly title shows up in the ANSWER, not just
    in a list.
    """
    return (
        sidecar_title(
            _load_cached().get(doc_id), require_ingested=require_ingested
        )
        or humanize_doc_id(doc_id)
    )


def titles_for(doc_ids, *, require_ingested: bool = False) -> dict[str, str]:
    """`title_for` over many ids with ONE sidecar read.

    The per-id helper would re-`deepcopy` the whole map for each of ~20
    search results; this reads once.
    """
    docs = _load_cached()
    return {
        doc_id: (
            sidecar_title(docs.get(doc_id), require_ingested=require_ingested)
            or humanize_doc_id(doc_id)
        )
        for doc_id in doc_ids
    }
