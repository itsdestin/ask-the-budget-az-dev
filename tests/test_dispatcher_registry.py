"""The registry repoint must not change one byte of routing.

A differently-extracted document produces different chunk text, different
chunk_ids, and broken eval ground truth. This file is the guard, and it is
written to pass against the PRE-refactor dispatcher first.
"""
from ingest.dispatcher import (
    EXTRACTOR_REGISTRY,
    MinerUExtractor,
    OpenDataLoaderExtractor,
    PythonDocxExtractor,
    pick_extractor,
)

# The shipped table, transcribed by hand from ingest/dispatcher.py on
# 2026-08-11. Hand-transcribed ON PURPOSE: deriving it from the module under
# test would make this assert that a thing equals itself.
SHIPPED = {
    ("afr", "pdf"): OpenDataLoaderExtractor,
    ("governors-budget", "pdf"): OpenDataLoaderExtractor,
    ("baseline-book", "pdf"): MinerUExtractor,
    ("approps-report", "pdf"): MinerUExtractor,
    ("baseline-per-agency", "pdf"): MinerUExtractor,
    ("approps-per-agency", "pdf"): MinerUExtractor,
    ("s-pdf", "pdf"): MinerUExtractor,
    ("bh-pdf", "pdf"): MinerUExtractor,
    ("bd-pdf", "pdf"): MinerUExtractor,
    ("topic-pdf", "pdf"): MinerUExtractor,
    ("detailed-list-pdf", "pdf"): MinerUExtractor,
    ("budget-bill", "docx"): PythonDocxExtractor,
    ("fiscal-note", "pdf"): MinerUExtractor,
    ("agency-submission", "pdf"): MinerUExtractor,
    ("budget-bill-summary", "pdf"): MinerUExtractor,
}


def test_the_registry_is_exactly_the_shipped_table():
    assert EXTRACTOR_REGISTRY == SHIPPED


def test_every_shipped_pair_resolves_to_the_same_extractor_instance_type():
    for (doc_type, fmt), cls in SHIPPED.items():
        assert isinstance(pick_extractor(doc_type, fmt), cls)


def test_unknown_pairs_still_raise():
    import pytest
    # A budget-bill PDF is the canonical caller bug: the Word file is the
    # whole point of that type.
    with pytest.raises(ValueError):
        pick_extractor("budget-bill", "pdf")
    with pytest.raises(ValueError):
        pick_extractor("not-a-type", "pdf")
