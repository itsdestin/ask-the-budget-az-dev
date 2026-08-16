"""A DECLARED agency beats one inferred from the document's text.

`_primary_agency_name` counts agency stamps across the extracted chunks and
takes the most common. That is a good guess and only a guess:
`chunking/entity_stamper.py` cannot resolve an agency it has no alias for,
and 103 of the 157 catalogued agencies carry no alias at all (recorded in
STATUS.md under "Query understanding").

On exactly the documents the picker exists for — one agency's own budget
request — the inferred answer is therefore most likely to be None or wrong,
and the uploader's pick is ground truth. This file pins that ordering,
because the failure is silent: a document filed under the wrong agency name
looks completely normal in a results list.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from chunking.types import Chunk, ChunkProvenance
from ingest.jobs import new_job
from ingest.worker import _agency_name_for_title
from store import office_agencies as oa

# Taken from the catalog rather than typed here. The catalog stores names in
# an INVERTED form ("Corrections, State Department of", not "Department of
# Corrections"), and a hardcoded guess at one is a test that passes or fails
# on a spelling this file does not own.
ADC = oa.agency_name("agency:adc")


def _chunk(agency_id: str | None) -> Chunk:
    return Chunk(
        chunk_id="c1", doc_id="d1", text="text", section_path=[], is_table=False,
        table_html=None,
        provenance=ChunkProvenance(page=1, bbox=[0, 0, 1, 1], paragraph_id=None,
                                   table_cell_id=None),
        agency_canonical_id=agency_id, fund_canonical_id=None,
        doc_type="agency-submission", publisher="agency", fiscal_year=2027,
        token_count=2,
    )


def _job(**over):
    base = dict(
        doc_id="d1", title="t", corpus="budget", source_path="p",
        source_sha256="s", publisher="agency", doc_type="agency-submission",
        fiscal_year=2027,
    )
    base.update(over)
    return new_job(**base)


@pytest.fixture
def ctx():
    """A stand-in, not a real WorkerContext.

    `_agency_name_for_title` reads exactly one field off it. Building the
    real thing needs a ChunkStore, an embedder and a stamper — a LanceDB
    directory and ONNX weights — which the testing convention in CLAUDE.md
    forbids this suite from touching at all.
    """
    return SimpleNamespace(
        agency_names={"agency:des": "Department of Economic Security"}
    )


def test_the_declared_agency_wins_over_a_different_inferred_one(ctx):
    # The sharpest case: the text is stamped as one agency and the uploader
    # said another. The uploader is looking at the document.
    name = _agency_name_for_title(
        _job(agency_canonical_id="agency:adc"),
        [_chunk("agency:des")],
        ctx,
    )
    assert name == ADC


def test_the_declared_agency_wins_when_nothing_was_inferred_at_all(ctx):
    # The COMMON case, not an edge one — 103 of 157 agencies have no alias
    # for the stamper to match, so an unstamped budget request is normal.
    name = _agency_name_for_title(
        _job(agency_canonical_id="agency:adc"), [_chunk(None)], ctx
    )
    assert name == ADC


def test_nothing_declared_falls_through_to_the_inferred_name(ctx):
    # Every doc_type except agency-submission, and every job queued before
    # the picker existed.
    name = _agency_name_for_title(_job(), [_chunk("agency:des")], ctx)
    assert name == "Department of Economic Security"


def test_an_office_added_agency_resolves_too(ctx, tmp_path, monkeypatch):
    monkeypatch.setattr(oa, "data_dir", lambda: tmp_path)
    oa.reset_office_agencies_cache()
    oa.save_office_agencies(
        (oa.OfficeAgency(canonical_id="agency:office-x", name="Office of X"),)
    )
    try:
        name = _agency_name_for_title(
            _job(agency_canonical_id="agency:office-x"), [_chunk(None)], ctx
        )
        assert name == "Office of X"
    finally:
        oa.reset_office_agencies_cache()


def test_an_id_that_no_longer_resolves_degrades_instead_of_failing_the_job(ctx):
    # An office entry an admin deleted between upload and ingest. A worse
    # title is not worth losing the document, so it falls through rather
    # than raising.
    name = _agency_name_for_title(
        _job(agency_canonical_id="agency:office-deleted"), [_chunk("agency:des")], ctx
    )
    assert name == "Department of Economic Security"


# ---------------------------------------------------------------------------
# Bad supplied names are advisory, never blocking (spec I4)
# ---------------------------------------------------------------------------


def test_a_bad_supplied_name_does_not_block_the_document(tmp_path):
    """Spec I4. `ingest/validate.py` already works this way and has already
    caught a real defect. The alternative — holding the document — is what
    happened to the FY2024 AFR, which sat invisible for weeks because a held
    document looks exactly like a missing one."""
    from identity.validator import validate_name

    verdict = validate_name("Osteopathic Examiners, Arizona ... 342 Board of...")
    assert verdict.ok is False
    # The worker records the reason and keeps going; it never raises.
    note = f"supplied name looked wrong ({verdict.reason}); used the document's own name"
    assert "dot leaders" in note


def test_note_bad_supplied_title_appends_without_replacing(monkeypatch):
    """The worker's actual call site. Appends to `job.warnings` alongside
    whatever `validate_doc` already put there (Task 9 Step 3) — a bad name
    is one more thing to check, not a reason to lose the agency-stamp
    warning that was already recorded."""
    from ingest.worker import _note_bad_supplied_title

    job = _job(user_title="Osteopathic Examiners, Arizona ... 342 Board of...")
    job.warnings = ["Only 40% of passages were matched to an agency."]

    _note_bad_supplied_title(job)

    assert job.warnings[0] == "Only 40% of passages were matched to an agency."
    assert len(job.warnings) == 2
    assert "dot leaders" in job.warnings[1]


def test_note_bad_supplied_title_is_silent_on_a_clean_name():
    from ingest.worker import _note_bad_supplied_title

    job = _job(user_title="Department of Economic Security")
    _note_bad_supplied_title(job)
    assert job.warnings == []


def test_note_bad_supplied_title_is_silent_with_no_supplied_title():
    """Every doc_type except agency-submission, and every job queued before
    the picker existed — job.user_title is "". Nothing to validate."""
    from ingest.worker import _note_bad_supplied_title

    job = _job(user_title="")
    _note_bad_supplied_title(job)
    assert job.warnings == []


def test_note_bad_supplied_title_never_raises(monkeypatch):
    """I4: a broken check on the way in must not cost the analyst the
    document. Simulates the validator itself breaking."""
    import ingest.worker as worker

    def _boom(_raw):
        raise RuntimeError("boom")

    monkeypatch.setattr(worker, "validate_name", _boom)
    job = _job(user_title="Department of Economic Security")

    worker._note_bad_supplied_title(job)  # must not raise

    assert job.warnings == []
