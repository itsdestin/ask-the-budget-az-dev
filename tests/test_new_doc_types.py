"""The two new types must be known EVERYWHERE, not just in the registry.

WHY a dedicated file: harness/tools.py's _DOC_TYPES has drifted from the
corpus before and the failure was SILENT -- a filtered search on a value the
corpus lacks returns zero chunks with no error, and the model concludes the
corpus does not cover it. The comment at that enum says to extend the system
prompt in the same change; test_the_system_prompt_mentions_the_new_type
enforces the half a reviewer would forget.
"""
from pathlib import Path

from ingest.dispatcher import EXTRACTOR_REGISTRY, MinerUExtractor, pick_extractor
from harness.tools import _DOC_TYPES, _PUBLISHERS

NEW = ("agency-submission", "budget-bill-summary")


def test_both_new_types_route_to_an_extractor():
    for key in NEW:
        assert (key, "pdf") in EXTRACTOR_REGISTRY
        assert isinstance(pick_extractor(key, "pdf"), MinerUExtractor)


def test_both_new_types_are_filterable_by_the_model():
    for key in NEW:
        assert key in _DOC_TYPES


def test_agency_is_a_publisher():
    assert "agency" in _PUBLISHERS


def test_the_doc_type_enum_matches_the_registry_exactly():
    """The enum and the registry are the two lists that must never drift."""
    from ingest import doc_types
    assert set(_DOC_TYPES) == {t.key for t in doc_types.all_types()}


def test_the_system_prompt_mentions_the_new_type():
    prompt = Path("harness/system-prompt.md").read_text(encoding="utf-8")
    assert "budget-bill-summary" in prompt
    assert "agency-submission" in prompt
