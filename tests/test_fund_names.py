"""Tests for funds/names.py — the read-only fund-name lookup that
`harness/tools.py::_fund_names()` uses to attach catalog names to
`list_filter_values(field="fund")` output.

Mirrors `tests/test_agency_catalog.py`'s shape: `funds/names.py::id_to_name`
is the fund-side counterpart of `chunking/agency_catalog.py::id_to_name`.

Unlike the agency loader, this loader degrades to `{}` on its own (missing
file, malformed YAML, non-dict top level) rather than relying entirely on
the harness-side guard — see the module docstring in `funds/names.py` for
why. `harness/tools.py::_fund_names()` still wraps every call in its own
try/except, because it also has to tolerate failure shapes the loader
itself cannot produce (the module not existing at all, a callable that
raises, a return value of the wrong TYPE) — those are covered in
`tests/test_harness_tools.py`, not here.
"""
from __future__ import annotations

from funds.names import id_to_name


def test_loads_the_real_committed_catalog():
    names = id_to_name()
    # data/fund-catalog.yaml:33 — verified present at spec-review time.
    assert names["fund:ahcccs"] == "AHCCCS Fund"


def test_every_key_is_a_fund_canonical_id():
    names = id_to_name()
    assert len(names) >= 200  # the catalog's own _meta says 227
    assert all(k.startswith("fund:") for k in names)


def test_missing_file_degrades_to_empty_dict(tmp_path):
    assert id_to_name(tmp_path / "does-not-exist.yaml") == {}


def test_malformed_yaml_degrades_to_empty_dict(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("funds: [unterminated", encoding="utf-8")
    assert id_to_name(bad) == {}


def test_non_dict_top_level_degrades_to_empty_dict(tmp_path):
    not_a_dict = tmp_path / "list.yaml"
    not_a_dict.write_text("- one\n- two\n", encoding="utf-8")
    assert id_to_name(not_a_dict) == {}


def test_an_entry_with_no_canonical_id_is_skipped_not_crashed_on(tmp_path):
    """An entry a future harvest fails to key is unusable for lookup either
    way — skip it rather than raise, mirroring
    chunking/agency_catalog.py::_load_cached's same guard."""
    path = tmp_path / "partial.yaml"
    path.write_text(
        "funds:\n"
        "- canonical_name: No Id Fund\n"
        "- canonical_name: AHCCCS Fund\n"
        "  canonical_id: fund:ahcccs\n",
        encoding="utf-8",
    )
    assert id_to_name(path) == {"fund:ahcccs": "AHCCCS Fund"}
