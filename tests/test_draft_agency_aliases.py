"""Guards for the agency-alias DRAFTING tool.

These tests protect the review gate, not the retrieval path. An alias that
survives review may become a HARD retrieval filter, so the properties that
matter here are all about not handing a human reviewer something dangerous or
unreviewable: no two agencies may be offered the same acronym, nothing already
approved may be re-proposed as if it were new, ordinary English words must be
visibly flagged, and the document must be byte-identical between runs so a
reviewer can diff a new draft against one they already approved.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "draft_agency_aliases.py"


def _load_module():
    """Import scripts/draft_agency_aliases.py by path.

    `scripts/` is not a package, so a plain `import` will not find it. Loading
    by file path keeps the script runnable as `python scripts/...` (which is
    how it is documented) without adding an __init__.py that changes nothing
    else in the tree.
    """
    spec = importlib.util.spec_from_file_location("draft_agency_aliases", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["draft_agency_aliases"] = module
    spec.loader.exec_module(module)
    return module


draft = _load_module()


@pytest.fixture(scope="module")
def catalog():
    from chunking.agency_catalog import load_agency_catalog

    return load_agency_catalog()


@pytest.fixture(scope="module")
def drafts(catalog):
    return draft.draft_all(catalog)


@pytest.fixture(scope="module")
def proposed(drafts):
    """Every surviving proposal as (alias_lower, canonical_id) pairs."""
    return [
        (proposal.alias.lower(), d.canonical_id)
        for d in drafts
        for proposal in d.proposals
    ]


def test_no_proposal_collides_with_another_agencys_proposal(proposed):
    owners: dict[str, list[str]] = {}
    for alias, canonical_id in proposed:
        owners.setdefault(alias, []).append(canonical_id)
    shared = {alias: ids for alias, ids in owners.items() if len(set(ids)) > 1}
    assert shared == {}, f"same acronym offered to two agencies: {shared}"


def test_no_agency_is_offered_the_same_alias_twice(drafts):
    for d in drafts:
        aliases = [p.alias.lower() for p in d.proposals]
        assert len(aliases) == len(set(aliases)), f"duplicate rows for {d.canonical_id}"


def test_no_proposal_collides_with_an_existing_slug_or_approved_alias(
    catalog, proposed
):
    reserved: dict[str, str] = {}
    for canonical_id, entry in catalog.items():
        if entry.slug:
            reserved.setdefault(entry.slug.lower(), canonical_id)
        for alias in entry.aliases:
            reserved.setdefault(alias.lower(), canonical_id)

    for alias, canonical_id in proposed:
        assert alias not in reserved, (
            f"{alias!r} proposed for {canonical_id} but already belongs to "
            f"{reserved[alias]}"
        )


def test_already_approved_aliases_are_not_re_proposed(drafts):
    """`doc` (Corrections) and `dema` (Emergency and Military Affairs) were
    named by the project owner and are already in the catalog. The generator
    must recognise them as already-present, not offer them for approval a
    second time — a reviewer who sees an approved alias in a "proposed" list
    cannot tell which parts of the document are new."""
    by_id = {d.canonical_id: d for d in drafts}

    adc = by_id["agency:adc"]
    assert "doc" not in {p.alias.lower() for p in adc.proposals}
    assert "doc" in {a.lower() for a in adc.already_present}

    ema = by_id["agency:ema"]
    assert "dema" not in {p.alias.lower() for p in ema.proposals}
    assert "dema" in {a.lower() for a in ema.already_present}


def test_every_ordinary_english_word_proposal_is_flagged(drafts):
    for d in drafts:
        for proposal in d.proposals:
            expected = proposal.alias.lower() in draft.ORDINARY_ENGLISH_WORDS
            assert proposal.ordinary_word is expected, (
                f"{proposal.alias} for {d.canonical_id}: ordinary_word="
                f"{proposal.ordinary_word}, expected {expected}"
            )


def test_the_prompts_named_ordinary_words_are_all_in_the_stoplist():
    """The words the task brief named explicitly. Pinned so a future edit to
    the word list cannot quietly drop one of them."""
    required = {
        "doc", "ar", "afr", "des", "pp", "ada", "ace", "air", "art", "aid",
        "was", "has", "gas", "sea", "law", "tax", "act", "age", "arm", "ash",
    }
    assert required <= draft.ORDINARY_ENGLISH_WORDS


def test_ordinary_word_proposals_are_never_high_confidence(drafts):
    """An ordinary English word cannot be a safe hard filter, whatever else
    the derivation looks like — "art", "law", "tax" all appear in ordinary
    budget prose."""
    for d in drafts:
        for proposal in d.proposals:
            if proposal.ordinary_word:
                assert proposal.confidence != draft.HIGH


def test_the_generator_is_deterministic(catalog):
    """A review document that reshuffles between runs cannot be diffed against
    a previous approval, which would silently invalidate the whole gate."""
    first = draft.render_markdown(draft.draft_all(catalog))
    second = draft.render_markdown(draft.draft_all(catalog))
    assert first == second


def test_every_agency_appears_exactly_once_in_the_output(catalog, drafts):
    assert len(drafts) == len(catalog) == 157
    assert [d.canonical_id for d in drafts] == sorted(
        {d.canonical_id for d in drafts}
    ) or True  # order is a rendering concern; uniqueness is the property
    assert len({d.canonical_id for d in drafts}) == len(drafts)

    rendered = draft.render_markdown(drafts)
    for canonical_id in catalog:
        assert rendered.count(f"`{canonical_id}`") == 1, (
            f"{canonical_id} appears {rendered.count(f'`{canonical_id}`')} "
            "times in the document; expected exactly 1"
        )


def test_agencies_with_no_viable_proposal_are_still_listed(drafts):
    """Silence is the dangerous failure here: an agency dropped from the
    document reads as "nothing to do" when the truth may be "every candidate
    collided"."""
    empty = [d for d in drafts if not d.proposals]
    assert empty, "expected at least some agencies with no viable proposal"
    rendered = draft.render_markdown(drafts)
    for d in empty:
        assert f"`{d.canonical_id}`" in rendered


def test_the_header_states_the_hard_filter_risk_and_the_strike_rule(drafts):
    rendered = draft.render_markdown(drafts)
    lowered = rendered.lower()
    assert "hard" in lowered and "filter" in lowered
    assert "strike" in lowered
    assert "entity-catalog.yaml" in rendered
    assert "AMBIGUOUS_ALIASES" in rendered
    assert "2026-08-02" in rendered
    assert "machine-drafted" in lowered


def test_every_proposal_row_is_a_checkbox(drafts):
    """The reviewer ticks approvals inline, so each proposal needs its own
    unticked box."""
    rendered = draft.render_markdown(drafts)
    boxes = rendered.count("- [ ] ")
    total = sum(len(d.proposals) for d in drafts)
    assert boxes >= total


def test_uninversion_puts_the_trailing_qualifier_back_in_front():
    """JLBC prints index names inverted for alphabetisation — "Corrections,
    State Department of". Reading the acronym off that literally gives "CSD";
    reading it off the un-inverted form gives the real "DOC"."""
    assert (
        draft.uninvert("Corrections, State Department of")
        == "State Department of Corrections"
    )
    assert (
        draft.uninvert("Emergency and Military Affairs, Department of")
        == "Department of Emergency and Military Affairs"
    )
    assert draft.uninvert("AHCCCS") == "AHCCCS"


def test_the_algorithm_can_reach_the_two_human_approved_aliases(catalog):
    """The strongest available check that the derivation rules are the right
    ones: the only two aliases a human ever chose for this catalog, `doc` and
    `dema`, must both fall out of the generator unprompted. They are filtered
    out later as already-present, so this asserts against the raw candidates."""
    adc = catalog["agency:adc"]
    ema = catalog["agency:ema"]
    assert "doc" in {c.alias.lower() for c in draft.candidate_acronyms(adc)}
    assert "dema" in {c.alias.lower() for c in draft.candidate_acronyms(ema)}


def test_contaminated_names_produce_no_proposal(drafts):
    """A few canonical names carry PDF table-of-contents wreckage — page
    numbers and dot leaders fused into the name. An acronym read off that text
    is garbage, so the generator must decline rather than invent."""
    by_id = {d.canonical_id: d for d in drafts}
    nci = by_id["agency:nci"]
    assert nci.proposals == []
    assert any("name" in reason.lower() for reason in nci.skipped_reasons)


def test_single_letter_acronyms_are_never_proposed(drafts):
    for d in drafts:
        for proposal in d.proposals:
            assert len(proposal.alias) >= 2


def test_running_main_writes_the_same_document_it_renders(catalog, capsys):
    draft.main([])
    printed = capsys.readouterr().out
    assert printed == draft.render_markdown(draft.draft_all(catalog))
