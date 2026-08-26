"""One documents.json reader (Plan 5 Task 19).

Four modules used to parse `<data_dir>/documents.json` with four caches:
`app/search_provider.py`, `app/routes/pdf.py`, `harness/tools.py` and
`ingest/lance_writer.py`. These specs pin the behaviours the survivors
had, because losing any one of them is invisible until a real corpus is
in front of a real user.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import pytest

from store import documents as docs_mod
from store.documents import (
    document_record,
    humanize_doc_id,
    load_documents,
    reset_documents_cache,
    title_for,
)


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    reset_documents_cache()
    yield tmp_path
    reset_documents_cache()


def _write(data_dir, payload):
    (data_dir / "documents.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Behaviour 1: the mtime cache, and that it actually re-reads
# ---------------------------------------------------------------------------


def test_missing_file_is_normal_and_reads_empty(data_dir):
    """A fresh install has no sidecar. Search must still work."""
    assert load_documents() == {}


def test_parses_and_caches(data_dir):
    """Proves the cache exists at all — a "cache" that re-parsed on every
    call would pass every other spec here while costing a share round-trip
    per search row.

    Rewriting the file with IDENTICAL mtime and size is the one case the
    stamp cannot see, so the stale value being served is the positive
    evidence. (It is also the cache's known limitation, which is why the
    stamp uses nanoseconds — a real rewrite always moves one of the two.)
    """
    path = data_dir / "documents.json"
    _write(data_dir, {"doc-a": {"title": "A"}})
    stamped = path.stat()

    assert load_documents()["doc-a"]["title"] == "A"

    _write(data_dir, {"doc-a": {"title": "B"}})  # same length
    os.utime(path, ns=(stamped.st_atime_ns, stamped.st_mtime_ns))
    assert path.stat().st_size == stamped.st_size

    assert load_documents()["doc-a"]["title"] == "A"


def test_a_deleted_sidecar_reads_empty_rather_than_serving_a_stale_cache(data_dir):
    """If the share drops out mid-session the honest answer is "I don't
    know", not the metadata from before it went away — a title is fine to
    lose, but `source_blob_path` would send the PDF route at a file the
    process can no longer reach."""
    _write(data_dir, {"doc-a": {"title": "A"}})
    assert load_documents()["doc-a"]["title"] == "A"

    (data_dir / "documents.json").unlink()

    assert load_documents() == {}


def test_rewriting_the_file_invalidates_the_cache(data_dir):
    """Plan 3's ingest rewrites this file whenever a document goes live,
    and the app is a long-lived process. Without this, every document
    ingested during a session keeps its humanized title until restart."""
    _write(data_dir, {"doc-a": {"title": "Before"}})
    assert load_documents()["doc-a"]["title"] == "Before"

    _write(data_dir, {"doc-a": {"title": "After"}})
    os.utime(data_dir / "documents.json", (2_000_000_000, 2_000_000_000))

    assert load_documents()["doc-a"]["title"] == "After"


def test_same_mtime_different_size_invalidates(data_dir):
    """Size is in the stamp too. A rewrite inside one filesystem mtime
    tick is exactly what a fast local ingest looks like."""
    path = data_dir / "documents.json"
    _write(data_dir, {"doc-a": {"title": "Before"}})
    stamped = path.stat()
    assert load_documents()["doc-a"]["title"] == "Before"

    _write(data_dir, {"doc-a": {"title": "A considerably longer title"}})
    os.utime(path, ns=(stamped.st_atime_ns, stamped.st_mtime_ns))

    assert load_documents()["doc-a"]["title"] == "A considerably longer title"


def test_repointing_the_data_dir_invalidates(data_dir, tmp_path, monkeypatch):
    """The stamp includes the PATH, so JLBC_DATA_DIR moving to a different
    corpus cannot serve the previous corpus's metadata."""
    _write(data_dir, {"doc-a": {"title": "First corpus"}})
    assert load_documents()["doc-a"]["title"] == "First corpus"

    other = tmp_path / "other"
    other.mkdir()
    _write(other, {"doc-a": {"title": "Second corpus"}})
    monkeypatch.setenv("JLBC_DATA_DIR", str(other))

    assert load_documents()["doc-a"]["title"] == "Second corpus"


# ---------------------------------------------------------------------------
# Behaviour 2: corrupt files — the read path degrades, the write path refuses
# ---------------------------------------------------------------------------


def test_corrupt_file_degrades_to_empty_on_the_read_path(data_dir, capsys):
    (data_dir / "documents.json").write_text("{not json", encoding="utf-8")

    assert load_documents() == {}
    # Silently returning {} would look like an empty corpus.
    assert "documents.json" in capsys.readouterr().err


def test_json_that_is_not_an_object_degrades_too(data_dir, capsys):
    _write(data_dir, ["a", "list", "not", "an", "object"])

    assert load_documents() == {}
    assert capsys.readouterr().err


def test_corrupt_file_RAISES_on_the_write_path(data_dir):
    """ingest/lance_writer.py read this file to merge one entry into it.
    Degrading to {} there would write a FRESH sidecar over the corrupt
    one and orphan every PDF in the viewer — the corrupt bytes are the
    only remaining record of where those files are.
    """
    (data_dir / "documents.json").write_text("{not json", encoding="utf-8")

    with pytest.raises(RuntimeError) as err:
        load_documents(strict=True)
    assert "documents.json" in str(err.value)


def test_strict_read_of_a_missing_file_is_still_empty(data_dir):
    """Absent is not corrupt. The very first ingest into a fresh data dir
    has no sidecar yet and must be allowed to create one."""
    assert load_documents(strict=True) == {}


def test_strict_never_serves_a_cached_copy_of_a_now_corrupt_file(data_dir):
    """The write path must re-validate. If a good read primed the cache
    and the file was then corrupted, returning the cached copy would let
    the writer overwrite the corruption it was supposed to refuse."""
    _write(data_dir, {"doc-a": {"title": "A"}})
    assert load_documents() == {"doc-a": {"title": "A"}}

    (data_dir / "documents.json").write_text("{not json", encoding="utf-8")
    os.utime(data_dir / "documents.json", (2_000_000_000, 2_000_000_000))

    with pytest.raises(RuntimeError):
        load_documents(strict=True)


# ---------------------------------------------------------------------------
# Behaviour 3: the doc-id humanizer
# ---------------------------------------------------------------------------


def test_humanizer_expands_fiscal_years_and_uppercases_acronyms():
    assert humanize_doc_id("jlbc-baseline-fy2027-ahcccs") == (
        "JLBC Baseline FY 2027 Ahcccs"
    )
    assert humanize_doc_id("agao-afr-fy2025") == "AGAO AFR FY 2025"


def test_humanizer_leaves_fy_lookalikes_alone():
    """'fy' followed by non-digits is a word, not a fiscal year."""
    assert humanize_doc_id("fyi-note") == "Fyi Note"


def test_title_falls_back_to_the_humanizer_when_the_doc_is_unknown(data_dir):
    assert title_for("jlbc-baseline-fy2027-axs") == "JLBC Baseline FY 2027 Axs"


def test_title_prefers_the_real_title(data_dir):
    _write(data_dir, {
        "jlbc-baseline-fy2027-axs": {
            "title": "FY 2027 Baseline — AHCCCS", "ingested_at": "2026-07-31",
        }
    })
    assert title_for("jlbc-baseline-fy2027-axs") == "FY 2027 Baseline — AHCCCS"


def test_blank_title_falls_back_rather_than_rendering_empty(data_dir):
    _write(data_dir, {"doc-a": {"title": "   ", "ingested_at": "2026-07-31"}})
    assert title_for("doc-a") == "Doc A"


# ---------------------------------------------------------------------------
# Behaviour 4: the ingested_at gate — OPTIONAL, and that is the point
# ---------------------------------------------------------------------------


def test_ingested_at_gate_rejects_migration_era_junk(data_dir):
    """app/search_provider.py's rule. The migration derived titles from
    doc_ids ("AGAO FY2025 fy2025"), which are WORSE than the humanizer.
    `ingested_at` is the discriminator: the migration never wrote it and
    every ingest-written entry has it."""
    _write(data_dir, {"agao-afr-fy2025": {"title": "AGAO FY2025 fy2025"}})

    assert title_for("agao-afr-fy2025", require_ingested=True) == (
        "AGAO AFR FY 2025"
    )


def test_the_gate_is_OFF_by_default(data_dir):
    """harness/tools.py did NOT apply the gate, and must not start.

    The 378 migration-era documents in the live corpus do not all have
    junk titles — "JLBC FY2025 — African-American Affairs, Arizona
    Commission of" is a real one. Gating unconditionally would replace
    that with "Jlbc Approps FY 2025 Aam" in AI Mode's answers, which is
    a regression on most of those documents. The gate is right for the
    search page (where the mockup index is the primary source and this
    is only a tiebreak) and wrong here.
    """
    _write(data_dir, {
        "jlbc-approps-fy2025-aam": {
            "title": "JLBC FY2025 — African-American Affairs, Arizona Commission of"
        }
    })

    assert title_for("jlbc-approps-fy2025-aam") == (
        "JLBC FY2025 — African-American Affairs, Arizona Commission of"
    )


def test_gate_lets_ingest_written_titles_through(data_dir):
    _write(data_dir, {
        "doc-a": {"title": "FY 2027 Baseline — Real", "ingested_at": "2026-07-31"}
    })
    assert title_for("doc-a", require_ingested=True) == "FY 2027 Baseline — Real"


# ---------------------------------------------------------------------------
# document_record
# ---------------------------------------------------------------------------


def test_document_record_returns_the_entry(data_dir):
    _write(data_dir, {"doc-a": {"title": "A", "source_format": "pdf"}})
    assert document_record("doc-a")["source_format"] == "pdf"


def test_document_record_is_none_for_unknown_docs(data_dir):
    _write(data_dir, {"doc-a": {"title": "A"}})
    assert document_record("nope") is None


def test_document_record_rejects_a_non_dict_entry(data_dir):
    """A hand-edited sidecar can put anything here. Callers index into
    the result, so a string would raise deep inside a route."""
    _write(data_dir, {"doc-a": "just a string"})
    assert document_record("doc-a") is None


# ---------------------------------------------------------------------------
# Concurrency — one process serves the whole office
# ---------------------------------------------------------------------------


def test_concurrent_readers_all_see_the_same_parse(data_dir):
    _write(data_dir, {f"doc-{i}": {"title": f"T{i}"} for i in range(50)})

    results: list[int] = []
    errors: list[BaseException] = []

    def read():
        try:
            results.append(len(load_documents()))
        except BaseException as exc:  # noqa: BLE001 - recorded, re-raised below
            errors.append(exc)

    threads = [threading.Thread(target=read) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert results == [50] * 16


def test_load_returns_a_copy_callers_cannot_corrupt(data_dir):
    """The cache is shared by every request in the process. A route that
    mutated its result would change what the next request sees."""
    _write(data_dir, {"doc-a": {"title": "A"}})

    first = load_documents()
    first["doc-b"] = {"title": "injected"}

    assert "doc-b" not in load_documents()


def test_mutating_a_record_does_not_corrupt_the_cache(data_dir):
    _write(data_dir, {"doc-a": {"title": "A"}})

    record = document_record("doc-a")
    record["title"] = "clobbered"

    assert document_record("doc-a")["title"] == "A"


def test_a_transient_read_error_is_retried_next_call(data_dir, monkeypatch):
    """A share blip during read_text cached {} under the GOOD file's stamp,
    so titles/links stayed blank until the next ingest changed the file."""
    _write(data_dir, {"d1": {"title": "Real title"}})
    real = Path.read_text
    calls = {"n": 0}

    def flaky(self, *a, **k):
        calls["n"] += 1
        if calls["n"] == 1 and self.name == "documents.json":
            raise PermissionError("sharing violation")
        return real(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", flaky)
    assert load_documents() == {}
    assert load_documents() == {"d1": {"title": "Real title"}}
