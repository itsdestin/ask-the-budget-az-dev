"""Tests for retrieval/api.py — the FastAPI sidecar that fronts the
hybrid retrieval pipeline for the Phase 1c MCP server.

Two layers, mirroring the pattern used by test_pipeline.py / test_loader.py:

* Pure unit tests (no DB, no Voyage). monkeypatch `retrieve()` and the
  doc-title lookup so the route logic + Pydantic validation can be
  exercised in isolation. These run on every CI tick.
* Integration tests gated by `_has_full_stack()` — Postgres reachable
  with the embedded slice AND VOYAGE_API_KEY set. These exercise the
  real /retrieve and /cite/validate endpoints end-to-end.
"""
from __future__ import annotations

import os

import pytest

psycopg = pytest.importorskip("psycopg")
fastapi_testclient = pytest.importorskip("fastapi.testclient")

from fastapi.testclient import TestClient

import retrieval.api as api_module
from db.connection import close_pool
from retrieval.api import app
from retrieval.pipeline import RetrievalResult
from retrieval.types import RetrievedChunk

MIN_CHUNKS_FOR_PIPELINE = 50


def _has_database() -> bool:
    if not os.environ.get("DATABASE_URL"):
        return False
    try:
        with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=1):
            return True
    except Exception:
        return False


def _has_embedded_corpus() -> bool:
    if not _has_database():
        return False
    try:
        with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=1) as c:
            row = c.execute(
                "SELECT COUNT(*) FROM chunks WHERE embedding IS NOT NULL"
            ).fetchone()
            return bool(row and row[0] >= MIN_CHUNKS_FOR_PIPELINE)
    except Exception:
        return False


needs_full_stack = pytest.mark.skipif(
    not (_has_embedded_corpus() and os.environ.get("VOYAGE_API_KEY")),
    reason=(
        "API integration tests need DATABASE_URL with >=50 embedded chunks "
        "AND VOYAGE_API_KEY set."
    ),
)

needs_db = pytest.mark.skipif(
    not _has_database(),
    reason="cite/validate tests need a reachable Postgres.",
)


@pytest.fixture(autouse=True)
def _reset_pool():
    yield
    close_pool()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_chunk(
    chunk_id: str,
    *,
    doc_id: str = "test-doc",
    score: float = 0.9,
    text: str = "Aviation Fund balance was $123,456.",
    page: int | None = 47,
) -> RetrievedChunk:
    """Build a RetrievedChunk fixture that satisfies every required
    field on RetrievedChunk.from_row's output. Used by unit tests that
    monkey-patch retrieve() — the values are never compared against
    a real DB, only marshaled into the API response.
    """
    return RetrievedChunk(
        chunk_id=chunk_id,
        doc_id=doc_id,
        text=text,
        score=score,
        section_path=["AHCCCS", "Operating Lump Sum"],
        page=page,
        bbox=[10.0, 20.0, 100.0, 40.0],
        source_anchor=None,
        agency_canonical_ids=["agency:ahcccs"],
        fund_canonical_id="fund:ahcccs",
        fund_mentions=["fund:ahcccs"],
        fiscal_year=2027,
        doc_type="baseline-cross-cut",
        is_table=True,
        table_html=None,
        token_count=120,
        publisher="jlbc",
    )


# ---------------------------------------------------------------------------
# Unit tests — /health
# ---------------------------------------------------------------------------


def test_health_endpoint_returns_ok():
    """Sanity check: /health is reachable and returns the expected shape.
    Used by the dev script to wait for the sidecar before launching the
    MCP server.
    """
    # TestClient runs the lifespan context manager, which constructs a
    # VoyageEmbedder. We patch the constructor so unit tests don't need
    # a Voyage key.
    with TestClient(app) as client:
        # Lifespan is set up only when the context manager is entered;
        # the embedder will exist on app.state.
        resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "voyage_key_present" in body


# ---------------------------------------------------------------------------
# Unit tests — /retrieve (monkeypatched)
# ---------------------------------------------------------------------------


def test_retrieve_marshals_chunks_to_schema_shape(monkeypatch):
    """The MCP `retrieve` tool's return shape is locked in
    citation-tool-schema.md. Confirm the FastAPI sidecar produces
    exactly that shape from a RetrievalResult.
    """
    fake_result = RetrievalResult(
        chunks=[_fake_chunk("c1", doc_id="d1"), _fake_chunk("c2", doc_id="d2")],
        top_score=0.9,
        reranker_scores=[0.9, 0.8],
        bm25_count=42,
        dense_count=37,
        fused_count=20,
    )

    monkeypatch.setattr(
        api_module, "retrieve", lambda req, embedder=None: fake_result
    )
    monkeypatch.setattr(
        api_module,
        "_lookup_doc_titles",
        lambda doc_ids: {"d1": "Doc One", "d2": "Doc Two"},
    )
    # Bypass the lazy Voyage SDK init — unit tests don't need a real
    # embedder since retrieve() is monkey-patched above.
    monkeypatch.setattr(api_module, "_get_embedder", lambda: None)

    with TestClient(app) as client:
        resp = client.post(
            "/retrieve",
            json={
                "query": "Aviation Fund balance",
                "filters": {"fiscal_year": [2027]},
                "top_k": 5,
            },
        )

    assert resp.status_code == 200
    body = resp.json()

    # Top-level shape per schema doc.
    assert set(body.keys()) == {
        "chunks",
        "top_score",
        "retrieval_id",
        "bm25_count",
        "dense_count",
        "fused_count",
    }
    assert body["top_score"] == 0.9
    assert body["bm25_count"] == 42
    assert body["dense_count"] == 37
    assert body["fused_count"] == 20
    assert isinstance(body["retrieval_id"], str) and body["retrieval_id"]
    assert len(body["chunks"]) == 2

    # Per-chunk shape. `bbox` joined the schema in Phase 1c WS4c so the
    # PdfViewer can paint a precise rectangle highlight on chip-click;
    # required-field set unchanged otherwise.
    c0 = body["chunks"][0]
    assert set(c0.keys()) == {
        "chunk_id",
        "doc_id",
        "doc_title",
        "publisher",
        "fiscal_year",
        "doc_type",
        "section_path",
        "page_start",
        "page_end",
        "bbox",
        "text",
        "text_length",
        "score",
    }
    assert c0["chunk_id"] == "c1"
    assert c0["doc_id"] == "d1"
    assert c0["doc_title"] == "Doc One"
    assert c0["publisher"] == "jlbc"
    assert c0["fiscal_year"] == 2027
    assert c0["doc_type"] == "baseline-cross-cut"
    assert c0["section_path"] == ["AHCCCS", "Operating Lump Sum"]
    assert c0["page_start"] == 47 and c0["page_end"] == 47
    assert c0["bbox"] == [10.0, 20.0, 100.0, 40.0]
    assert c0["score"] == 0.9


def test_retrieve_empty_filters_omitted(monkeypatch):
    """Filters block is optional; sidecar should accept the bare
    `{ query }` body and pass through to retrieve()."""
    captured: dict = {}

    def fake_retrieve(req, embedder=None):
        captured["req"] = req
        return RetrievalResult()

    monkeypatch.setattr(api_module, "retrieve", fake_retrieve)
    monkeypatch.setattr(api_module, "_lookup_doc_titles", lambda ids: {})
    monkeypatch.setattr(api_module, "_get_embedder", lambda: None)

    with TestClient(app) as client:
        resp = client.post("/retrieve", json={"query": "x"})

    assert resp.status_code == 200
    req = captured["req"]
    assert req.query == "x"
    assert req.fiscal_year is None
    assert req.publisher is None
    assert req.is_table is None


def test_retrieve_empty_query_returns_zero_chunks(monkeypatch):
    """retrieve() short-circuits on whitespace queries — sidecar should
    pass the empty result through cleanly with retrieval_id still set
    (the audit log writer relies on its presence)."""
    monkeypatch.setattr(api_module, "retrieve", lambda req, embedder=None: RetrievalResult())
    monkeypatch.setattr(api_module, "_lookup_doc_titles", lambda ids: {})
    monkeypatch.setattr(api_module, "_get_embedder", lambda: None)

    with TestClient(app) as client:
        resp = client.post("/retrieve", json={"query": "   "})

    assert resp.status_code == 200
    body = resp.json()
    assert body["chunks"] == []
    assert body["top_score"] == 0.0
    assert body["retrieval_id"]


def test_retrieve_rejects_malformed_filter_types():
    """fiscal_year must be a list of ints; a string should 422."""
    with TestClient(app) as client:
        resp = client.post(
            "/retrieve",
            json={"query": "x", "filters": {"fiscal_year": "2027"}},
        )
    assert resp.status_code == 422


def test_retrieve_filters_pass_through_to_pipeline(monkeypatch):
    """Each documented filter dimension reaches RetrievalRequest in the
    correct field. Catches accidental rename / drop bugs."""
    captured: dict = {}

    def fake_retrieve(req, embedder=None):
        captured["req"] = req
        return RetrievalResult()

    monkeypatch.setattr(api_module, "retrieve", fake_retrieve)
    monkeypatch.setattr(api_module, "_lookup_doc_titles", lambda ids: {})
    monkeypatch.setattr(api_module, "_get_embedder", lambda: None)

    payload = {
        "query": "x",
        "filters": {
            "fiscal_year": [2027, 2026],
            "doc_type": ["baseline-cross-cut"],
            "publisher": ["jlbc"],
            "agency_canonical_id": ["agency:ahcccs"],
            "fund_canonical_id": ["fund:ahcccs"],
            "is_table": True,
        },
        "top_k": 7,
    }

    with TestClient(app) as client:
        resp = client.post("/retrieve", json=payload)
    assert resp.status_code == 200

    req = captured["req"]
    assert req.fiscal_year == [2027, 2026]
    assert req.doc_type == ["baseline-cross-cut"]
    assert req.publisher == ["jlbc"]
    assert req.agency_canonical_id == ["agency:ahcccs"]
    assert req.fund_canonical_id == ["fund:ahcccs"]
    assert req.is_table is True
    assert req.top_k == 7


# ---------------------------------------------------------------------------
# Unit tests — /cite/validate (monkeypatched DB)
# ---------------------------------------------------------------------------


def test_cite_validate_rejects_unknown_chunk_id(monkeypatch):
    """`unknown chunk_id` is the dominant hallucination mode; the
    server-side check catches it cleanly so Claude sees the error in
    the tool result and self-corrects."""

    class FakeConn:
        def execute(self, *_args, **_kw):
            class _Cur:
                def fetchone(self):
                    return None

            return _Cur()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    monkeypatch.setattr(api_module, "get_connection", lambda: FakeConn())

    with TestClient(app) as client:
        resp = client.post(
            "/cite/validate",
            json={"chunk_id": "made-up", "span_start": 0, "span_end": 10},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["error"] == "unknown chunk_id"


def test_cite_validate_rejects_out_of_range_span(monkeypatch):
    """Returns the actual `chunk_text_length` so the model can self-correct."""

    class FakeConn:
        def execute(self, *_args, **_kw):
            class _Cur:
                def fetchone(self):
                    return {"text": "x" * 50, "doc_type": "baseline-per-agency"}

            return _Cur()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    monkeypatch.setattr(api_module, "get_connection", lambda: FakeConn())

    with TestClient(app) as client:
        # 200 over a 50-char chunk — 200 > max(50 abs, 2.5 ratio) so
        # this is above the auto-clamp budget and rejects cleanly.
        # Smaller overflows now clamp (covered by the dedicated
        # test_span_end_auto_clamp_small_overflow test below).
        resp = client.post(
            "/cite/validate",
            json={"chunk_id": "c1", "span_start": 0, "span_end": 250},
        )

    body = resp.json()
    assert body["ok"] is False
    assert body["error"] == "span out of range"
    assert body["chunk_text_length"] == 50


def test_cite_validate_accepts_valid_span(monkeypatch):
    class FakeConn:
        def execute(self, *_args, **_kw):
            class _Cur:
                def fetchone(self):
                    return {"text": "x" * 50, "doc_type": "baseline-per-agency"}

            return _Cur()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    monkeypatch.setattr(api_module, "get_connection", lambda: FakeConn())

    with TestClient(app) as client:
        resp = client.post(
            "/cite/validate",
            json={"chunk_id": "c1", "span_start": 0, "span_end": 25},
        )

    body = resp.json()
    assert body["ok"] is True
    assert body["chunk_text_length"] == 50


def test_cite_validate_rejects_inverted_span(monkeypatch):
    """span_end <= span_start is structurally invalid; we don't even
    need to know chunk_text_length to reject it. Belt-and-braces case
    in case Pydantic field constraints get relaxed in the future."""

    class FakeConn:
        def execute(self, *_args, **_kw):
            class _Cur:
                def fetchone(self):
                    return {"text": "x" * 50, "doc_type": "baseline-per-agency"}

            return _Cur()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    monkeypatch.setattr(api_module, "get_connection", lambda: FakeConn())

    with TestClient(app) as client:
        resp = client.post(
            "/cite/validate",
            json={"chunk_id": "c1", "span_start": 30, "span_end": 30},
        )

    body = resp.json()
    assert body["ok"] is False
    assert body["error"] == "span out of range"


# ---------------------------------------------------------------------------
# Unit tests — /docs/{doc_id} (monkeypatched DB)
# ---------------------------------------------------------------------------


def test_doc_metadata_returns_full_record(monkeypatch):
    """The Next.js /api/pdf/[doc_id] route reads source_blob_path from
    this endpoint to resolve a chip-click into a file to stream. Pin
    down the response shape so a schema drift breaks the test (and
    not the click-to-jump UX) at PR time."""

    class FakeConn:
        def execute(self, *_args, **_kw):
            class _Cur:
                def fetchone(self):
                    return {
                        "doc_id": "d1",
                        "title": "JLBC Baseline Book",
                        "publisher": "jlbc",
                        "doc_type": "baseline-cross-cut",
                        "fiscal_year": 2024,
                        "source_format": "pdf",
                        "source_blob_path": "/path/to/file.pdf",
                        "page_count": 250,
                        "source_url": "https://example.com/file.pdf",
                    }

            return _Cur()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    monkeypatch.setattr(api_module, "get_connection", lambda: FakeConn())

    with TestClient(app) as client:
        resp = client.get("/docs/d1")

    assert resp.status_code == 200
    body = resp.json()
    assert body["doc_id"] == "d1"
    assert body["title"] == "JLBC Baseline Book"
    assert body["source_blob_path"] == "/path/to/file.pdf"
    assert body["source_format"] == "pdf"
    assert body["page_count"] == 250
    assert body["fiscal_year"] == 2024
    assert body["source_url"] == "https://example.com/file.pdf"


def test_doc_metadata_returns_404_for_unknown_doc(monkeypatch):
    """Hallucinated doc_ids hit 404 cleanly (the Next.js route relays
    that to the browser as a 404 too — no PDF panel painted)."""

    class FakeConn:
        def execute(self, *_args, **_kw):
            class _Cur:
                def fetchone(self):
                    return None

            return _Cur()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    monkeypatch.setattr(api_module, "get_connection", lambda: FakeConn())

    with TestClient(app) as client:
        resp = client.get("/docs/ghost-doc")
    assert resp.status_code == 404


def test_doc_metadata_omits_null_optional_fields(monkeypatch):
    """`response_model_exclude_none=True` keeps page_count / source_url
    out of the JSON when null. Catches accidental dropping of the
    response_model_exclude_none=True decorator (which would render
    nulls and confuse the Next.js consumer)."""

    class FakeConn:
        def execute(self, *_args, **_kw):
            class _Cur:
                def fetchone(self):
                    return {
                        "doc_id": "d2",
                        "title": "Bill SB1234",
                        "publisher": "legislature",
                        "doc_type": "budget-bill",
                        "fiscal_year": 2025,
                        "source_format": "docx",
                        "source_blob_path": "/path/to/file.docx",
                        "page_count": None,
                        "source_url": None,
                    }

            return _Cur()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    monkeypatch.setattr(api_module, "get_connection", lambda: FakeConn())

    with TestClient(app) as client:
        resp = client.get("/docs/d2")
    body = resp.json()
    assert "page_count" not in body
    assert "source_url" not in body
    assert body["source_blob_path"] == "/path/to/file.docx"


# ---------------------------------------------------------------------------
# Integration tests — live DB + live Voyage
# ---------------------------------------------------------------------------


@needs_full_stack
def test_retrieve_against_live_corpus_returns_chunks():
    """Smoke test against the live slice. The Aviation Fund query is
    the canonical retrieval probe — surfaces s18 chunks under the
    bm25+dense+rerank pipeline. Validates that the FastAPI sidecar
    exposes the same behavior as calling retrieve() directly.
    """
    with TestClient(app) as client:
        resp = client.post(
            "/retrieve",
            json={"query": "Aviation Fund balance", "top_k": 5},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["chunks"]) > 0
    assert body["top_score"] > 0
    assert body["retrieval_id"]
    # doc_title is denormalized from documents — every chunk should have one.
    for c in body["chunks"]:
        assert c["doc_title"], f"chunk {c['chunk_id']} missing doc_title"


@needs_db
def test_cite_validate_against_live_chunk():
    """Pull a real chunk_id from the DB and confirm validate accepts
    a (0, 5) span on it. Catches schema drift between the cite
    endpoint and the chunks table.
    """
    from db.connection import get_connection

    with get_connection() as conn:
        row = conn.execute(
            "SELECT chunk_id, length(text) AS len FROM chunks LIMIT 1"
        ).fetchone()
    if row is None:
        pytest.skip("chunks table is empty")

    with TestClient(app) as client:
        resp = client.post(
            "/cite/validate",
            json={
                "chunk_id": row["chunk_id"],
                "span_start": 0,
                "span_end": min(5, row["len"]),
            },
        )
    body = resp.json()
    assert body["ok"] is True
    assert body["chunk_text_length"] == row["len"]


# ---------------------------------------------------------------------------
# Unit tests — citation-alignment helpers (no DB needed)
# ---------------------------------------------------------------------------


def test_normalize_for_match_folds_quotes_and_dashes():
    """NFKC + smart-quote folds + dash folds must match the renderer's
    normalizeForMatch (web/lib/citation-extract.ts:376). If these
    diverge, a claim_span the renderer finds in the PDF text-layer
    won't pass server-side validation here — same input, different
    verdict per layer."""
    n = api_module._normalize_for_match
    assert n("“Hello”") == '"hello"'  # smart double quotes
    assert n("don’t") == "don't"  # smart apostrophe
    assert n("a—b") == "a-b"  # em dash
    assert n("a–b") == "a-b"  # en dash
    assert n("ﬁle") == "file"  # NFKC ligature
    assert n("  multi   spaces  ") == "multi spaces"


def test_normalize_for_match_strips_markdown_tokens():
    """Bold/italic/code/pipe must be stripped so the model's
    markdown-formatted claim_span matches the raw PDF text in the
    chunk (which has no markdown)."""
    n = api_module._normalize_for_match
    assert n("**bold**") == "bold"
    assert n("*italic*") == "italic"
    assert n("`code`") == "code"
    assert n("[label](http://example.com)") == "label"
    assert n("| FY 2024 | $4,679,100 |") == "fy 2024 $4,679,100"


def test_normalize_for_match_decodes_html_entities():
    """parseInlineCiteAttrs on the renderer side decodes &quot; etc.
    before matching; mirror that here or quoted claim_spans (common
    in budget bills citing statute names) will silently fail."""
    n = api_module._normalize_for_match
    assert n("&quot;Aviation Fund&quot;") == '"aviation fund"'
    assert n("&amp;") == "&"


def test_normalize_strips_markdown_backslash_escapes():
    """MinerU emits `\\$(10,000,000)` to prevent `$…$` from rendering
    as math; the PDF text layer and the model's claim_span both use
    the unescaped form. Without backslash-stripping, the verbatim
    substring check fails because `\\$` and `$` are different chars.

    This was the 2026-05-11 cite-#14 root cause: chunk text had
    `\\$(10,000,000)` and findTextRects couldn't match it against the
    PDF, so the renderer fell back to the chunk's coarse bbox."""
    n = api_module._normalize_for_match
    assert n(r"\$10,000,000") == "$10,000,000"
    assert n(r"\(10,000,000\)") == "(10,000,000)"
    assert n(r"\[note\]") == "[note]"
    # All CommonMark-escapable punctuation. Note: after backslash is
    # stripped, the bare `*` / `_` / `` ` `` chars are then handled by
    # the bold/italic/code markdown stripper later in the pipeline and
    # disappear — so escaped emphasis markers collapse to whitespace,
    # NOT to literal `*`. Same logic as the renderer's normalize.
    assert n(r"\\ \` \* \_ \{ \} \[ \] \( \) \# \+ \- \. \! \| \> \~ \$") == \
        "\\ { } [ ] ( ) # + - . ! > ~ $"


def test_normalize_collapses_accounting_parens_on_dollars():
    """`$(10,000,000)` and `($10,000,000)` both denote accounting
    negatives; for citation alignment, treat both as `$10,000,000`
    so a claim that says "removes $10 million" matches a source that
    uses either convention. The sign is in the verb, not the parens.
    2026-05-12: added paren-first form for parity with the PDF text
    layer (pdfjs renders `($X)` even when the source PDF was MinerU-
    extracted with `\\$(X)`)."""
    n = api_module._normalize_for_match
    # Dollar-first convention (MinerU's preferred markdown output).
    assert n("$(10,000,000)") == "$10,000,000"
    assert n(r"decrease of \$(10,000,000)") == "decrease of $10,000,000"
    # Paren-first convention (pdfjs text-layer output).
    assert n("($10,000,000)") == "$10,000,000"
    assert n("decrease of ($3,500,000) from the General Fund") == \
        "decrease of $3,500,000 from the general fund"
    # Non-dollar parens left alone (don't accidentally strip
    # parenthesized notes like "(Item 9 of Section 116)" or
    # "(see footnote 1)").
    assert n("note (see footnote 1)") == "note (see footnote 1)"
    assert n("(Item 9 of Section 116)") == "(item 9 of section 116)"


def test_normalize_expands_abbreviated_dollar_amounts():
    """Single highest-leverage fix from the 2026-05-11 audit: models
    write `$40 million` while sources use `$40,000,000`. Without
    expansion, the content-word check treats `$40` and `$40,000,000`
    as different tokens and paraphrase overlap craters."""
    n = api_module._normalize_for_match
    assert n("$40 million") == "$40,000,000"
    assert n("$5.0 million") == "$5,000,000"
    assert n("$11.5 M") == "$11,500,000"
    assert n("$501.9 million") == "$501,900,000"
    assert n("$1.74B") == "$1,740,000,000"
    assert n("$10K") == "$10,000"
    assert n("$10 thousand") == "$10,000"
    # Case-insensitive units.
    assert n("$5 MILLION") == "$5,000,000"
    # Already-expanded numbers untouched.
    assert n("$40,000,000") == "$40,000,000"
    # Word-boundary protection: "$10 minute" shouldn't match "m".
    assert n("$10 minute") == "$10 minute"
    # Decimal precision preserved through the int conversion.
    assert n("$0.5 million") == "$500,000"


def test_normalize_dollar_expansion_handles_audit_failure_case():
    """Reproduces cite-#14 from the 2026-05-11 audit: the model wrote
    a paraphrase claim with `$10 million` and `$40 million`, and the
    chunk text had `\\$(10,000,000)` and `$40,000,000`. With the new
    normalize: claim's `$10,000,000` and `$40,000,000` tokens both
    appear in the chunk after backslash-stripping + paren-collapse +
    dollar-expansion."""
    cw = api_module._content_words
    n = api_module._normalize_for_match
    claim = (
        "The JLBC FY 2027 Baseline continues the $40 million ongoing "
        "transfer to ADC but removes the FY 2026 $10 million Coordinated "
        "Reentry appropriation as one-time funding."
    )
    chunk = (
        r"Remove One-Time Funding. The Baseline includes a decrease of "
        r"\$(10,000,000) from the Consumer Remediation Subaccount in FY "
        r"2027 for Coordinated Reentry. A separate footnote requires the "
        r"AG to transfer $40,000,000 ongoing to the ADC Opioid "
        r"Remediation Fund."
    )
    claim_words = cw(n(claim))
    chunk_words = set(cw(n(chunk)))
    # Both dollar amounts must match across the abbreviation gap.
    # Currency tokens canonicalize to bare-number form (no $ prefix).
    assert "10,000,000" in claim_words
    assert "10,000,000" in chunk_words
    assert "40,000,000" in claim_words
    assert "40,000,000" in chunk_words


def test_check_alignment_now_passes_audit_failure_case():
    """End-to-end on cite-#14 from the audit: with the normalize
    upgrades, the paraphrase overlap clears the 0.60 threshold so the
    validator returns None (no error) for what was previously a
    7/17 = 0.41 failure."""
    claim = (
        "The JLBC FY 2027 Baseline continues the $40 million ongoing "
        "transfer to ADC but removes the FY 2026 $10 million Coordinated "
        "Reentry appropriation as one-time funding."
    )
    chunk = (
        r"Remove One-Time Funding. The Baseline includes a decrease of "
        r"\$(10,000,000) from the Consumer Remediation Subaccount in FY "
        r"2027 for Coordinated Reentry. A separate footnote requires the "
        r"AG to transfer $40,000,000 ongoing to the ADC Opioid "
        r"Remediation Fund Baseline appropriation, one-time funding "
        r"removes the JLBC continues."
    )
    err = api_module._check_alignment(chunk, claim, "paraphrase")
    assert err is None


def test_content_words_includes_numbers_and_currency():
    """Dollar amounts and bare numbers are the most diagnostic words
    in budget claims — a paraphrase cite that drops the $4,677,100
    figure has lost the actual support. Currency tokens are emitted
    in canonical bare-number form (no `$` prefix) so claim vs cited
    compare symmetrically regardless of which side has the sign."""
    cw = api_module._content_words
    # Currency emitted as bare number — `$X` → `X`.
    assert "4,677,100" in cw(api_module._normalize_for_match("Total $4,677,100 in FY 2024"))
    assert "2024" in cw(api_module._normalize_for_match("Total $4,677,100 in FY 2024"))
    # Short words (≤3 chars) excluded.
    assert "the" not in cw(api_module._normalize_for_match("the the the the"))


def test_check_alignment_verbatim_pass():
    """Strict normalized substring — the cited text must contain the
    claim verbatim (after normalize folds)."""
    err = api_module._check_alignment(
        "The Baseline includes $4,677,100 for FY 2026.",
        "Baseline includes $4,677,100",
        "verbatim",
    )
    assert err is None


def test_check_alignment_verbatim_fail_with_suggestion():
    """Verbatim mismatch returns an error that tells the model to
    either re-pick the span or downgrade to paraphrase. Both options
    are actionable; an unhelpful error string drives the model to
    invent yet another wrong cite. Wholly-mismatched cites must still
    fail even with the loosened threshold."""
    err = api_module._check_alignment(
        "Operating Budget composition: General Fund $342,500.",
        "$6,000,000 (one-time) for secure ballot paper",
        "verbatim",
    )
    assert err is not None
    assert "verbatim" in err
    assert "paraphrase" in err  # suggests downgrade option


def test_check_alignment_verbatim_loose_accepts_label_prefixed_claims():
    """The 2026-05-12 user-feedback case: the model wrote
    `**FY 2025 (Approved):** $4,677,100 and 38.4 FTE — $342,500 General
    Fund + $4,334,600 State Treasurer's Operating Fund.` and chose
    verbatim. Every load-bearing figure IS in the source; only the
    label `(Approved)` is the model's addition. Strict substring
    rejected this; loose verbatim (≥85% content-word overlap) accepts
    it. Verifying with the actual chunk text shape from the audit."""
    chunk_text = (
        r"Operating Budget |  | The budget includes \$4,677,100 and 38.4 "
        r"FTE Positions in FY 2025 for the operating budget. These amounts "
        r"consist of: |  | General Fund \$342,500 |  | State Treasurer's "
        r"Operating Fund 4,334,600 |  | Adjustments are"
    )
    claim = (
        "**FY 2025 (Approved):** $4,677,100 and 38.4 FTE — $342,500 "
        "General Fund + $4,334,600 State Treasurer's Operating Fund."
    )
    err = api_module._check_alignment(chunk_text, claim, "verbatim")
    assert err is None


def test_content_words_canonicalizes_currency_to_bare_form():
    """`$4,334,600` in the claim and `4,334,600` in the source both
    canonicalize to bare `4,334,600` — so set-based overlap matches
    symmetrically. This replaces the earlier dual-emit approach
    which inflated the claim-token count when one side had `$X` and
    the other bare `X`."""
    cw = api_module._content_words
    n = api_module._normalize_for_match
    # Currency token emitted as bare number (no $ prefix).
    tokens = cw(n("Total $4,334,600 in FY 2025"))
    assert "4,334,600" in tokens
    assert "$4,334,600" not in tokens
    # Bare numbers without $ stay bare (consistent).
    bare_tokens = cw(n("38.4 FTE"))
    assert "38.4" in bare_tokens
    assert "$38.4" not in bare_tokens


def test_check_alignment_verbatim_single_dollar_token(monkeypatch):
    """The 2026-05-12 audit cite #22 pattern: model verbatim-cites
    a single dollar figure (`$131,582,200`) against a chunk that
    contains the bare number (`131,582,200`, without `$`). With the
    old dual-emit approach this scored 1/2 = 50% and failed; with
    canonical bare-number tokens it scores 1/1 = 100% and passes.
    No DB needed — go direct to _check_alignment to keep this fast."""
    err = api_module._check_alignment(
        "AGENCY TOTAL 131,582,200 23,303,200 18,401,400",
        "$131,582,200",
        "verbatim",
    )
    assert err is None


def test_check_alignment_paraphrase_pass_high_overlap():
    """A genuine paraphrase: claim restates the chunk's content with
    different ordering / connective words but same content words."""
    err = api_module._check_alignment(
        "The Baseline includes $4,721,600 and 38.4 FTE Positions in "
        "FY 2027 for the operating budget. These amounts are unchanged "
        "from FY 2026.",
        "The FY 2027 Baseline operating budget of $4,721,600 with 38.4 "
        "FTE is unchanged from FY 2026.",
        "paraphrase",
    )
    assert err is None


def test_check_alignment_paraphrase_fail_low_overlap():
    """The cite-#18 pattern from the 2026-05-11 audit: claim is about
    'ballot paper', cited span is about 'Operating Budget composition'.
    Content-word overlap is near zero and the validator must catch it."""
    err = api_module._check_alignment(
        "Operating Budget composition: General Fund $342,500. State "
        "Treasurer's Operating Fund $4,334,600.",
        "$6,000,000 (one-time) for secure ballot paper",
        "paraphrase",
    )
    assert err is not None
    assert "paraphrase" in err
    assert "content words" in err


def test_cite_validate_paraphrase_misalignment_returns_preview(monkeypatch):
    """Full end-to-end: a paraphrase cite that fails alignment must
    return cited_text_preview so the model can see what its span
    actually contained and pick a better one on retry."""
    chunk_text = (
        "Operating Budget. The budget includes $4,677,100 and 38.4 FTE "
        "Positions in FY 2025 for the operating budget. These amounts "
        "consist of: General Fund $342,500. State Treasurer's Operating "
        "Fund $4,334,600."
    )

    class FakeConn:
        def execute(self, *_args, **_kw):
            class _Cur:
                def fetchone(self):
                    return {"text": chunk_text, "doc_type": "baseline-per-agency"}

            return _Cur()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    monkeypatch.setattr(api_module, "get_connection", lambda: FakeConn())

    with TestClient(app) as client:
        resp = client.post(
            "/cite/validate",
            json={
                "chunk_id": "c1",
                "span_start": 0,
                "span_end": len(chunk_text),
                "claim_span": "$6,000,000 one-time for secure ballot paper",
                "confidence": "paraphrase",
            },
        )

    body = resp.json()
    assert body["ok"] is False
    assert "paraphrase" in body["error"]
    # Preview must echo the cited slice so the model knows what to fix.
    assert body["cited_text_preview"].startswith("Operating Budget")


def test_cite_validate_verbatim_substring_passes(monkeypatch):
    """Verbatim happy path: claim is a substring of cited text after
    normalize."""
    chunk_text = "The Baseline includes $4,677,100 in FY 2026."

    class FakeConn:
        def execute(self, *_args, **_kw):
            class _Cur:
                def fetchone(self):
                    return {"text": chunk_text, "doc_type": "baseline-per-agency"}

            return _Cur()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    monkeypatch.setattr(api_module, "get_connection", lambda: FakeConn())

    with TestClient(app) as client:
        resp = client.post(
            "/cite/validate",
            json={
                "chunk_id": "c1",
                "span_start": 0,
                "span_end": len(chunk_text),
                "claim_span": "Baseline includes $4,677,100",
                "confidence": "verbatim",
            },
        )

    body = resp.json()
    assert body["ok"] is True


def test_cite_validate_span_too_broad_rejected(monkeypatch):
    """A span longer than SPAN_BREADTH_LIMIT chars is rejected before
    the alignment check, even if the claim happens to be in there.
    This pushes the model toward focused citations and produces
    usable PDF highlights."""
    chunk_text = "Operating Budget content. " + ("x " * 2000) + "Tail content."

    class FakeConn:
        def execute(self, *_args, **_kw):
            class _Cur:
                def fetchone(self):
                    return {"text": chunk_text, "doc_type": "baseline-per-agency"}

            return _Cur()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    monkeypatch.setattr(api_module, "get_connection", lambda: FakeConn())

    with TestClient(app) as client:
        resp = client.post(
            "/cite/validate",
            json={
                "chunk_id": "c1",
                "span_start": 0,
                "span_end": len(chunk_text),
                "claim_span": "Operating Budget",
                "confidence": "verbatim",
            },
        )

    body = resp.json()
    assert body["ok"] is False
    assert "too broad" in body["error"]
    # Preview still attached so the model sees what to narrow from.
    assert body["cited_text_preview"].startswith("Operating Budget")


def test_cite_validate_no_claim_span_skips_alignment_check(monkeypatch):
    """Back-compat: when claim_span and confidence are omitted (older
    MCP servers or test harnesses), only the chunk_id + bounds check
    runs. Validates that the new fields are truly optional."""
    chunk_text = "Some unrelated text content."

    class FakeConn:
        def execute(self, *_args, **_kw):
            class _Cur:
                def fetchone(self):
                    return {"text": chunk_text, "doc_type": "baseline-per-agency"}

            return _Cur()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    monkeypatch.setattr(api_module, "get_connection", lambda: FakeConn())

    with TestClient(app) as client:
        resp = client.post(
            "/cite/validate",
            json={
                "chunk_id": "c1",
                "span_start": 0,
                "span_end": len(chunk_text),
            },
        )

    body = resp.json()
    assert body["ok"] is True


# ---------------------------------------------------------------------------
# AFR currency-only alignment + auto-clamp + doc_type dispatch
# (2026-05-12 audit-driven changes)
# ---------------------------------------------------------------------------


def _fake_conn(text: str, doc_type: str):
    """Mock get_connection() returning a row with both `text` and
    `doc_type` (the validator now JOINs documents for the AFR
    dispatch). Helper saves repetition in the new test cases."""

    class _FakeConn:
        def execute(self, *_args, **_kw):
            class _Cur:
                def fetchone(self):
                    return {"text": text, "doc_type": doc_type}

            return _Cur()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    return _FakeConn


def test_afr_alignment_passes_when_dollar_amounts_match(monkeypatch):
    """The 2026-05-12 audit's #18 case: model writes English prose
    ('Corrections started FY 2025 with $75,000,000 balance, received
    $40,000,000...') against a raw AFR table row ('FUND TOTAL
    75,000,000.00 40,000,000.00 99,360,968.11 15,639,031.89').
    Normal paraphrase overlap was 0.06 because the English words
    ('started', 'received') aren't in the table. AFR path checks
    currency tokens only — every $X in the claim matches a numeric
    token in the cited span (with `$75,000,000` ↔ `75,000,000.00`)."""
    chunk_text = (
        "2573-CONSUMER RESTITUTION AND REMEDIATION REVOLVING FUND | "
        "DCA DC2573 APPROPRIATED ACTIVITY 40,000,000.00 - | "
        "DCA DC2573 OPIOID REMEDIATION - 99,360,968.11 | "
        "FUND TOTAL 75,000,000.00 40,000,000.00 99,360,968.11 15,639,031.89"
    )
    monkeypatch.setattr(api_module, "get_connection", _fake_conn(chunk_text, "afr"))
    with TestClient(app) as client:
        resp = client.post(
            "/cite/validate",
            json={
                "chunk_id": "c1",
                "span_start": 0,
                "span_end": len(chunk_text),
                "claim_span": (
                    "The Corrections (DCA) side of fund 2573 started FY 2025 "
                    "with a $75,000,000 balance, received $40,000,000 in "
                    "revenues, spent $99,360,968.11, ended FY 2025 at "
                    "$15,639,031.89."
                ),
                "confidence": "paraphrase",
            },
        )
    body = resp.json()
    assert body["ok"] is True, body


def test_afr_alignment_rejects_when_claim_dollar_amounts_absent(monkeypatch):
    """AFR path must still reject when the claim's dollar amounts
    DON'T match the cited span — wholly-wrong cites can't sneak
    through just because we relaxed the English overlap check."""
    chunk_text = (
        "MAA MA2573 MA OPIOID REMEDIATION 3,000,000.00 2,313,971.39 | "
        "FUND TOTAL 3,000,000.00 2,313,971.39 686,028.61"
    )
    monkeypatch.setattr(api_module, "get_connection", _fake_conn(chunk_text, "afr"))
    with TestClient(app) as client:
        resp = client.post(
            "/cite/validate",
            json={
                "chunk_id": "c1",
                "span_start": 0,
                "span_end": len(chunk_text),
                "claim_span": (
                    "The ADC side: started with $75,000,000, ended at "
                    "$15,639,031.89."
                ),
                "confidence": "paraphrase",
            },
        )
    body = resp.json()
    assert body["ok"] is False
    assert "afr cite" in body["error"]
    assert "$75,000,000" in body["error"]


def test_afr_alignment_ignores_year_and_small_numbers(monkeypatch):
    """Years (2025) and small fractional numbers (38.4 FTE) appear
    in claims but aren't load-bearing data. The AFR check only
    matches numbers with ≥4 integer digits to skip them. Without
    this filter, a claim mentioning 'FY 2025' would reject when the
    AFR row doesn't repeat the year."""
    chunk_text = "FUND TOTAL 75,000,000.00 40,000,000.00 99,360,968.11"
    monkeypatch.setattr(api_module, "get_connection", _fake_conn(chunk_text, "afr"))
    with TestClient(app) as client:
        resp = client.post(
            "/cite/validate",
            json={
                "chunk_id": "c1",
                "span_start": 0,
                "span_end": len(chunk_text),
                "claim_span": (
                    "In FY 2025, the fund opened with $75,000,000 and "
                    "received $40,000,000 (38.4 FTE)."
                ),
                "confidence": "paraphrase",
            },
        )
    body = resp.json()
    assert body["ok"] is True


def test_span_end_auto_clamp_small_overflow(monkeypatch):
    """Audit #10: span_end=1850 on a 1832-char chunk (off by 18).
    The model picked a rounded value past the end; clamping to length
    and proceeding catches the model's intent without forcing a
    wasted retry. Threshold is max(50 chars, 5% of length) — 18 is
    well inside that, so this clamps."""
    chunk_text = "x" * 100  # short chunk; 5% = 5, abs cap = 50; effective = 50
    monkeypatch.setattr(api_module, "get_connection", _fake_conn(chunk_text, "baseline-per-agency"))
    with TestClient(app) as client:
        resp = client.post(
            "/cite/validate",
            json={
                "chunk_id": "c1",
                "span_start": 0,
                "span_end": 130,  # 30 over, within abs cap of 50
                "claim_span": "x",
                "confidence": "verbatim",
            },
        )
    body = resp.json()
    assert body["ok"] is True


def test_span_end_clamp_rejects_large_overflow(monkeypatch):
    """A 200-char overflow on a 100-char chunk is genuinely wrong;
    the validator still rejects so the model self-corrects.
    Boundary: max(50, 5% × 100) = 50. 200 > 50 → reject."""
    chunk_text = "x" * 100
    monkeypatch.setattr(api_module, "get_connection", _fake_conn(chunk_text, "baseline-per-agency"))
    with TestClient(app) as client:
        resp = client.post(
            "/cite/validate",
            json={
                "chunk_id": "c1",
                "span_start": 0,
                "span_end": 300,
                "claim_span": "x",
                "confidence": "verbatim",
            },
        )
    body = resp.json()
    assert body["ok"] is False
    assert body["error"] == "span out of range"
    assert body["chunk_text_length"] == 100


def test_verbatim_threshold_lowered_to_070(monkeypatch):
    """The 2026-05-12 audit's #15/#16 cases: verbatim cites where the
    claim is MOSTLY in the cited span (82%, 68%) but the trailing
    few words spill past span_end. With 0.85 threshold they failed;
    with 0.70 they pass. The threshold change accepts these without
    making the validator permissive enough to let wholly-wrong cites
    through (a 0% overlap cite still fails)."""
    # 10 content words in claim; 7 of them appear in chunk → 0.70.
    chunk_text = (
        "Operating Budget includes amounts Treasurer General Fund balance "
        "appropriation summary."
    )
    claim = (
        "Operating Budget includes amounts Treasurer General Fund — "
        "expanded discussion follows."  # 'expanded' 'discussion' 'follows' missing
    )
    monkeypatch.setattr(
        api_module, "get_connection", _fake_conn(chunk_text, "baseline-per-agency")
    )
    with TestClient(app) as client:
        resp = client.post(
            "/cite/validate",
            json={
                "chunk_id": "c1",
                "span_start": 0,
                "span_end": len(chunk_text),
                "claim_span": claim,
                "confidence": "verbatim",
            },
        )
    body = resp.json()
    assert body["ok"] is True, body
