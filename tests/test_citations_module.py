"""Tests for retrieval/citations.py — the corpus-aware cite validator.

This module is the code path that enforces Core Invariant 2 ("citations
are verified, not just emitted"), so it is tested directly rather than
only through the HTTP sidecar that used to own it. Two consumers now
share it:

* `retrieval/api.py`'s `/cite/validate` + `/cite/validate_batch` (the
  legacy Phase-1c sidecar on port 9200, retired in Plan 5).
* Plan 4's in-process tool loop (`harness/`), which calls the functions
  directly and may target either corpus.

The `corpus` parameter is the only new degree of freedom versus the
behavior these tests were ported from (`tests/test_api.py`), so the
fiscal-note cases below are the genuinely new coverage; everything else
pins behavior that must NOT have changed in the move.

Storage is real: a LanceDB in tmp_path, injected through the `store=`
seam. No ONNX models are involved — cite validation never embeds
anything, it only reads chunk text.
"""
from __future__ import annotations

import pytest

from retrieval.citations import (
    CiteValidateBody,
    SPAN_BREADTH_LIMIT,
    fetch_chunk_texts,
    validate_cite,
    validate_cite_against_text,
    validate_cites,
)
from retrieval.pipeline import DEFAULT_CORPUS, reset_default_collaborators
from store.chunk_store import ChunkStore

# Small dim keeps the tmp tables cheap. Only the tests that go through the
# process-wide singleton (which builds a bare `ChunkStore()`) need the real
# 768 width — see `default_store_corpus`.
DIM = 8


def _vec(seed: int, dim: int = DIM) -> list[float]:
    v = [0.0] * dim
    v[seed % dim] = 1.0
    return v


def _row(chunk_id: str, text: str, *, seed: int = 0, dim: int = DIM, **over) -> dict:
    """A complete chunk row for the LanceDB schema (mirrors the `_row`
    helpers in tests/test_chunk_store.py and tests/test_api.py)."""
    row = dict(
        chunk_id=chunk_id,
        doc_id="jlbc-baseline-fy2027-axs",
        text=text,
        section_path=["AHCCCS", "Operating Lump Sum"],
        page=47,
        bbox=[10.0, 20.0, 100.0, 40.0],
        source_anchor='{"page": 47}',
        agency_canonical_ids=["agency:axs"],
        fund_canonical_id="fund:ahcccs",
        fund_mentions=["fund:ahcccs"],
        fiscal_year=2027,
        doc_type="baseline-per-agency",
        is_table=True,
        table_html=None,
        token_count=120,
        publisher="jlbc",
        vector=_vec(seed, dim),
    )
    row.update(over)
    return row


@pytest.fixture()
def store(tmp_path):
    """A two-corpus tmp store. Both tables carry a chunk whose text differs,
    so a test can prove which table a read actually went to."""
    s = ChunkStore(root=tmp_path, dim=DIM)
    s.upsert_chunks("budget_chunks", [
        _row("b1", "The Baseline includes $4,677,100 and 38.4 FTE Positions."),
        _row("b2", "Department of Child Safety caseworker funding.", seed=1),
    ])
    s.upsert_chunks("fiscal_note_chunks", [
        _row(
            "fn1",
            "HB 2001 would increase General Fund costs by $2,500,000 annually.",
            seed=2,
        ),
        # Deliberately shares a chunk_id with a budget chunk: proves the
        # corpus argument selects the table rather than the store searching
        # everywhere and taking whatever it finds first.
        _row("b1", "FISCAL NOTE TEXT, NOT THE BUDGET CHUNK.", seed=3),
    ])
    return s


@pytest.fixture()
def default_store_corpus(tmp_path, monkeypatch):
    """Point the process-wide pipeline singleton at a tmp corpus.

    Covers the `store=None` default path (what harness/tools.py will use):
    the singleton is built as a bare `ChunkStore()`, so this table has to be
    768-wide or `_check_dim` refuses to open it.
    """
    real_dim = 768
    s = ChunkStore(root=tmp_path, dim=real_dim)
    s.upsert_chunks("budget_chunks", [
        _row("d1", "Aviation Fund balance was $123,456 at year end.",
             dim=real_dim),
    ])
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    reset_default_collaborators()
    yield
    reset_default_collaborators()


# ---------------------------------------------------------------------------
# fetch_chunk_texts — the bulk read, now corpus-aware
# ---------------------------------------------------------------------------


def test_fetch_chunk_texts_returns_text_and_doc_type(store):
    got = fetch_chunk_texts(["b1", "b2"], store=store)
    assert set(got) == {"b1", "b2"}
    assert got["b1"] == (
        "The Baseline includes $4,677,100 and 38.4 FTE Positions.",
        "baseline-per-agency",
    )


def test_fetch_chunk_texts_omits_missing_ids(store):
    """Missing rows are absent from the mapping, not None-valued — the
    caller decides how to render `unknown chunk_id`."""
    got = fetch_chunk_texts(["b1", "nope-not-here"], store=store)
    assert set(got) == {"b1"}


def test_fetch_chunk_texts_empty_input_skips_the_store(store):
    """No ids means no network hop on the office share."""
    calls: list[list[str]] = []

    class Counting:
        def get_by_ids(self, corpus, ids):
            calls.append(list(ids))
            return []

    assert fetch_chunk_texts([], store=Counting()) == {}
    assert calls == []


def test_fetch_chunk_texts_dedups_to_one_row_per_unique_id(store):
    """The optimization the batch path depends on: five cites against one
    chunk must ask the store for ONE id, not five."""
    calls: list[list[str]] = []
    real = store

    class Counting:
        def get_by_ids(self, corpus, ids):
            calls.append(sorted(ids))
            return real.get_by_ids(corpus, ids)

    got = fetch_chunk_texts(["b1"] * 5 + ["b2"], store=Counting())
    assert set(got) == {"b1", "b2"}
    assert calls == [["b1", "b2"]], calls


def test_fetch_chunk_texts_reads_the_fiscal_note_corpus(store):
    """The whole point of Task 2: the same reader serves a second corpus."""
    got = fetch_chunk_texts(["fn1"], corpus="fiscal_note_chunks", store=store)
    assert got["fn1"][0].startswith("HB 2001 would increase General Fund")


def test_fetch_chunk_texts_corpus_selects_the_table_for_a_shared_id(store):
    """`b1` exists in BOTH tables with different text. Whichever corpus is
    named is the one that answers — a cite validated against the fiscal-note
    corpus must never be checked against budget text."""
    budget = fetch_chunk_texts(["b1"], corpus="budget_chunks", store=store)
    notes = fetch_chunk_texts(["b1"], corpus="fiscal_note_chunks", store=store)
    assert budget["b1"][0].startswith("The Baseline includes")
    assert notes["b1"][0] == "FISCAL NOTE TEXT, NOT THE BUDGET CHUNK."


def test_fetch_chunk_texts_defaults_to_the_budget_corpus(store):
    """Default must stay `budget_chunks` — every pre-Plan-4 caller relies
    on it and passes no corpus."""
    calls: list[str] = []
    real = store

    class Counting:
        def get_by_ids(self, corpus, ids):
            calls.append(corpus)
            return real.get_by_ids(corpus, ids)

    fetch_chunk_texts(["b1"], store=Counting())
    assert calls == [DEFAULT_CORPUS] == ["budget_chunks"]


def test_fetch_chunk_texts_raises_on_an_unknown_corpus_name(store):
    """A typo'd corpus must raise, not return {} — silently answering
    "no such chunk" for every citation would look like a corpus problem
    instead of a caller bug."""
    with pytest.raises(ValueError, match="Unknown corpus table"):
        fetch_chunk_texts(["b1"], corpus="budget_chunkz", store=store)


def test_fetch_chunk_texts_checks_the_corpus_name_before_the_empty_guard(store):
    """Regression: the `no chunk_ids -> return {}` short-circuit used to
    return before anything touched the store, so the store's own name
    check never ran and a typo'd corpus passed silently. The name is a
    caller-supplied constant — it is wrong or right regardless of how
    many citations came with it."""
    with pytest.raises(ValueError, match="Unknown corpus table"):
        fetch_chunk_texts([], corpus="budget_chunkz", store=store)


def test_validate_cites_checks_the_corpus_name_on_an_empty_batch(store):
    """Same regression one layer up, and the sharper case: a zero-citation
    batch is a DOCUMENTED normal path (the model may hand over none), so
    without an explicit check the expected-empty case and the typo case
    are indistinguishable. harness/tools.py picks the corpus per call,
    which is exactly who this protects."""
    with pytest.raises(ValueError, match="Unknown corpus table"):
        validate_cites([], corpus="budget_chunkz", store=store)


def test_validate_cite_raises_on_an_unknown_corpus_name(store):
    """The single-cite wrapper inherits the same guarantee."""
    with pytest.raises(ValueError, match="Unknown corpus table"):
        validate_cite(
            CiteValidateBody(chunk_id="b1", quote="x"),
            corpus="budget_chunkz",
            store=store,
        )


def test_empty_input_still_returns_empty_for_a_VALID_corpus(store):
    """The guard only rejects bad names — a legitimately-empty call must
    still be a cheap no-op that never reads the store."""
    calls: list[str] = []

    class Counting:
        def get_by_ids(self, corpus, ids):
            calls.append(corpus)
            return []

    assert fetch_chunk_texts([], corpus="fiscal_note_chunks", store=Counting()) == {}
    assert validate_cites([], corpus="fiscal_note_chunks", store=Counting()) == []
    assert calls == []


def test_validate_cite_reports_unknown_chunk_when_the_table_is_absent(tmp_path):
    """Valid corpus name, table never created (fiscal_note_chunks before
    Plan 3's ingest has run): reads return nothing, so every cite comes
    back as `unknown chunk_id`. Honest, and it does NOT create the table
    — readers must stay off the write path on the office share."""
    empty = ChunkStore(root=tmp_path, dim=DIM)
    out = validate_cite(
        CiteValidateBody(chunk_id="fn1", quote="anything"),
        corpus="fiscal_note_chunks",
        store=empty,
    )
    assert out.ok is False
    assert out.error == "unknown chunk_id"


def test_validate_cite_reports_unknown_chunk_when_the_table_is_empty(tmp_path):
    """The realistic near-term state of `fiscal_note_chunks`: the schema
    exists but nothing has been ingested. That takes a DIFFERENT branch
    inside ChunkStore._open than the never-created case above (a real
    table handle, zero matching rows), and `unknown chunk_id` is a
    model-facing contract string, so pin both branches."""
    created = ChunkStore(root=tmp_path, dim=DIM)
    created.ensure_tables()
    assert created.count("fiscal_note_chunks") == 0

    out = validate_cite(
        CiteValidateBody(chunk_id="fn1", quote="anything"),
        corpus="fiscal_note_chunks",
        store=created,
    )
    assert out.ok is False
    assert out.error == "unknown chunk_id"


def test_fetch_chunk_texts_uses_the_pipeline_singleton_when_no_store_passed(
    default_store_corpus,
):
    """`store=None` is the shape harness/tools.py will call — it must reach
    the same process-wide store the retrieval path already opened."""
    got = fetch_chunk_texts(["d1"])
    assert got["d1"][0].startswith("Aviation Fund balance")


# ---------------------------------------------------------------------------
# validate_cite — fetch + validate for a single citation
# ---------------------------------------------------------------------------


def test_validate_cite_unknown_chunk_id(store):
    """Exact error string: the model and the web UI both key off it."""
    out = validate_cite(
        CiteValidateBody(chunk_id="does-not-exist", quote="x"), store=store
    )
    assert out.ok is False
    assert out.error == "unknown chunk_id"


def test_validate_cite_resolves_quote_to_offsets(store):
    text = "The Baseline includes $4,677,100 and 38.4 FTE Positions."
    out = validate_cite(
        CiteValidateBody(chunk_id="b1", quote="$4,677,100"), store=store
    )
    assert out.ok is True, out
    assert out.resolved_span_start == text.index("$4,677,100")
    assert out.resolved_span_end == text.index("$4,677,100") + len("$4,677,100")
    assert out.chunk_text_length == len(text)


def test_validate_cite_quote_not_found(store):
    out = validate_cite(
        CiteValidateBody(chunk_id="b1", quote="definitely-not-here-XYZ"),
        store=store,
    )
    assert out.ok is False
    assert "quote not found in chunk.text" in out.error


def test_validate_cite_requires_offsets_or_quote(store):
    out = validate_cite(CiteValidateBody(chunk_id="b1"), store=store)
    assert out.ok is False
    assert "requires either (span_start, span_end) OR" in out.error


def test_validate_cite_rejects_duplicate_quote_with_positions(store):
    """Ambiguous quotes used to silently bind to the first occurrence, which
    is how a PDF highlight landed on the wrong dollar amount."""
    text = "Item A: $5,000,000 in FY 2025. Item B: $5,000,000 in FY 2026."
    out = validate_cite_against_text(
        CiteValidateBody(chunk_id="x", quote="$5,000,000"), text, None
    )
    assert out.ok is False
    assert "quote appears multiple times in chunk.text" in out.error
    assert "positions:" in out.error
    assert "…" not in out.error  # only two occurrences — no truncation marker


def test_validate_cite_duplicate_quote_caps_positions_at_3(store):
    out = validate_cite_against_text(
        CiteValidateBody(chunk_id="x", quote="$X"),
        "$X here $X there $X again $X once more $X last",
        None,
    )
    assert out.ok is False
    err = out.error
    assert "…" in err
    inside = err.split("(", 1)[1].split(")", 1)[0]
    # Three positions joined by ", " (2 commas) plus the ", …" tail = 3.
    assert inside.count(",") == 3, inside


def test_validate_cite_offsets_win_when_both_passed(store):
    """Back-compat disposition rule: explicit offsets beat `quote`, and the
    quote is not even scanned for (this one would fail if it were)."""
    out = validate_cite(
        CiteValidateBody(
            chunk_id="b1",
            span_start=0,
            span_end=12,
            quote="not-in-the-chunk-XYZ",
        ),
        store=store,
    )
    assert out.ok is True, out


# ---------------------------------------------------------------------------
# Span sanity — pure paths, exercised through validate_cite_against_text
# ---------------------------------------------------------------------------


def test_validate_cite_against_text_needs_no_store():
    """The pure core: callers that already hold the chunk text (the batch
    fan-out) validate without touching storage at all."""
    out = validate_cite_against_text(
        CiteValidateBody(chunk_id="whatever", span_start=0, span_end=5),
        "hello world",
        None,
    )
    assert out.ok is True
    assert out.chunk_text_length == 11


@pytest.mark.parametrize(
    "span_start,span_end",
    [(-1, 5), (10, 10), (10, 4)],
    ids=["negative-start", "empty-range", "inverted-range"],
)
def test_validate_cite_rejects_bad_ranges(span_start, span_end):
    out = validate_cite_against_text(
        CiteValidateBody(
            chunk_id="x", span_start=span_start, span_end=span_end
        ),
        "x" * 100,
        None,
    )
    assert out.ok is False
    assert out.error == "span out of range"


def test_validate_cite_auto_clamps_small_span_end_overflow():
    """max(50 chars, 5% of length); 30 over a 100-char chunk clamps."""
    out = validate_cite_against_text(
        CiteValidateBody(chunk_id="x", span_start=0, span_end=130),
        "x" * 100,
        None,
    )
    assert out.ok is True
    assert out.resolved_span_end == 100


def test_validate_cite_rejects_large_span_end_overflow():
    out = validate_cite_against_text(
        CiteValidateBody(chunk_id="x", span_start=0, span_end=300),
        "x" * 100,
        None,
    )
    assert out.ok is False
    assert out.error == "span out of range"
    assert out.chunk_text_length == 100


def test_validate_cite_rejects_span_too_broad():
    text = "Operating Budget content. " + ("x " * 2000) + "Tail content."
    out = validate_cite_against_text(
        CiteValidateBody(chunk_id="x", span_start=0, span_end=len(text)),
        text,
        None,
    )
    assert out.ok is False
    assert "too broad" in out.error
    assert str(SPAN_BREADTH_LIMIT) in out.error
    # Preview still attached so the model can see what to narrow from.
    assert out.cited_text_preview.startswith("Operating Budget")


def test_validate_cite_soft_truncates_claim_span_over_500():
    """Rejecting a long claim_span outright wasted a whole model turn; the
    UI's chip-attachment substring search still works on the truncated form."""
    out = validate_cite_against_text(
        CiteValidateBody(
            chunk_id="x", span_start=0, span_end=5, claim_span="x" * 750
        ),
        "hello world",
        None,
    )
    assert out.ok is True
    assert out.truncated is True


def test_validate_cite_does_not_flag_a_short_claim_span_as_truncated():
    out = validate_cite_against_text(
        CiteValidateBody(
            chunk_id="x", span_start=0, span_end=5, claim_span="short claim"
        ),
        "hello world",
        None,
    )
    assert out.ok is True
    assert out.truncated is None


def test_validate_cite_does_not_run_a_word_overlap_alignment_check():
    """Regression guard. The content-word-overlap heuristic was retired
    2026-05-20 (~40% false rejections on faithful-but-differently-worded
    claims) and must not creep back in: a claim sharing no vocabulary with
    the cited span still validates. Real faithfulness checking is WS3's job,
    not a string comparison's."""
    out = validate_cite_against_text(
        CiteValidateBody(
            chunk_id="x",
            span_start=0,
            span_end=40,
            claim_span="$6,000,000 one-time for secure ballot paper",
            confidence="verbatim",
        ),
        "Operating Budget composition: General Fund $342,500.",
        None,
    )
    assert out.ok is True, out


def test_validate_cite_ignores_doc_type():
    """`doc_type` is carried for a future faithfulness verifier but must not
    change any verdict today — including for AFR chunks, whose dollar-amount
    alignment check went out with the rest of the heuristics."""
    body = CiteValidateBody(
        chunk_id="x",
        span_start=0,
        span_end=30,
        claim_span="started with $75,000,000",
        confidence="paraphrase",
    )
    text = "FUND TOTAL 3,000,000.00 2,313,971.39 686,028.61"
    assert validate_cite_against_text(body, text, "afr").ok is True
    assert validate_cite_against_text(body, text, None).ok is True


# ---------------------------------------------------------------------------
# validate_cites — the batch fan-out
# ---------------------------------------------------------------------------


def test_validate_cites_empty_input_returns_empty_list(store):
    assert validate_cites([], store=store) == []


def test_validate_cites_preserves_order_and_isolates_failures(store):
    out = validate_cites(
        [
            CiteValidateBody(chunk_id="b1", quote="$4,677,100"),
            CiteValidateBody(chunk_id="missing-id", quote="x"),
            CiteValidateBody(chunk_id="b2", quote="caseworker"),
            CiteValidateBody(chunk_id="b1", quote="not-in-this-chunk-XYZ"),
        ],
        store=store,
    )
    assert [c.ok for c in out] == [True, False, True, False]
    assert out[1].error == "unknown chunk_id"
    assert "quote not found" in out[3].error


def test_validate_cites_makes_one_store_read_for_repeated_chunk_ids(store):
    """The batch endpoint exists to collapse N reads into 1 — each read is a
    network round trip on the office share. Guard the optimization."""
    calls: list[list[str]] = []
    real = store

    class Counting:
        def get_by_ids(self, corpus, ids):
            calls.append(list(ids))
            return real.get_by_ids(corpus, ids)

    out = validate_cites(
        [CiteValidateBody(chunk_id="b1", span_start=0, span_end=10)] * 5,
        store=Counting(),
    )
    assert [c.ok for c in out] == [True] * 5
    assert calls == [["b1"]], calls


def test_validate_cites_reads_the_fiscal_note_corpus(store):
    out = validate_cites(
        [CiteValidateBody(chunk_id="fn1", quote="$2,500,000")],
        corpus="fiscal_note_chunks",
        store=store,
    )
    assert out[0].ok is True, out[0]


def test_validate_cite_against_a_fiscal_note_chunk(store):
    """End-to-end single-cite path on the second corpus — what Plan 3's
    fiscal-note answers will run through."""
    note_text = "HB 2001 would increase General Fund costs by $2,500,000 annually."
    out = validate_cite(
        CiteValidateBody(chunk_id="fn1", quote="General Fund costs"),
        corpus="fiscal_note_chunks",
        store=store,
    )
    assert out.ok is True, out
    assert out.resolved_span_start == note_text.index("General Fund costs")
    assert out.chunk_text_length == len(note_text)


def test_validate_cite_budget_corpus_cannot_see_a_fiscal_note_chunk(store):
    """Corpus isolation, stated as a failure: a fiscal-note chunk_id is
    simply unknown to the budget corpus."""
    out = validate_cite(
        CiteValidateBody(chunk_id="fn1", quote="General Fund costs"),
        store=store,
    )
    assert out.ok is False
    assert out.error == "unknown chunk_id"
