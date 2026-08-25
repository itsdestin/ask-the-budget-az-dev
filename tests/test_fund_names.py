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
    # The catalog holds 227 entries; the display-worthiness policy (see
    # below) withholds the 67 pollution/truncation names, leaving 160. A big
    # drop from this floor means either the catalog shrank or the policy
    # started eating real names — both worth a look.
    assert len(names) >= 150
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


# ---------------------------------------------------------------------------
# Display-worthiness — the 2026-08-22 audit (see the fund-names spec's
# post-ship audit section). The catalog's fund column is polluted: schedule
# Total/SUBTOTAL rows, agency names, budget-adjustment lines and mid-phrase
# truncations were parsed in as "funds". A name is served only when it reads
# as a complete fund name; everything else stays an honest raw id on screen.
# ---------------------------------------------------------------------------


def _write_catalog(tmp_path, names):
    path = tmp_path / "catalog.yaml"
    entries = "\n".join(
        f"- canonical_id: fund:x{i}\n  canonical_name: {n!r}"
        for i, n in enumerate(names)
    )
    path.write_text(f"funds:\n{entries}\n", encoding="utf-8")
    return path


def test_pollution_shaped_names_are_withheld(tmp_path):
    # One representative per measured pollution class: the 5,238-chunk
    # single-word truncation, a generic truncation, a schedule total row,
    # an agency name, an adjustment line, and a mid-phrase truncation.
    path = _write_catalog(
        tmp_path,
        [
            "Account",
            # "Block Grant" is NOT here: two words with a "grant" tail pass
            # the allowlist by design (TANF/WIA are real). That fragment is
            # removed from the catalog itself, hand-pinned in the
            # fund-identity repair, because no shape rule can tell it from
            # a real grant name.
            "Total - Secretary of State",
            "SUBTOTAL - Judiciary",
            "Department of Juvenile Corrections",
            "FY 2026 Unallocated Salary Adjustments",
            "Court Appointed Special Advocate and",
        ],
    )
    assert id_to_name(path) == {}


def test_complete_fund_names_are_served(tmp_path):
    path = _write_catalog(
        tmp_path,
        [
            "AHCCCS Fund",
            "Consumer Remediation Subaccount",
            "Highway Damage Recovery Account",
            "Arizona State Retirement System Administration Account",
        ],
    )
    assert len(id_to_name(path)) == 4


def test_the_real_catalog_withholds_the_measured_bad_names():
    names = id_to_name()
    # The three loudest measured defects: 5,238 / 1,299 / 25 chunks each.
    assert "fund:account" not in names
    assert "fund:block-grant" not in names
    assert "fund:total-secretary-of-state" not in names
    # And the legitimate names survive the policy.
    assert names["fund:ahcccs"] == "AHCCCS Fund"
    assert names["fund:consumer-remediation-subaccount"] == (
        "Consumer Remediation Subaccount"
    )


def test_a_grant_tail_is_a_complete_funding_source_name(tmp_path):
    # Federal block grants are real money analysts filter by; once the junk
    # "Block Grant" fragment is deleted from the catalog (fund-identity
    # repair, 2026-08-23) the tail word is safe to admit.
    path = _write_catalog(
        tmp_path,
        [
            "Federal Temporary Assistance for Needy Families Block Grant",
            "Workforce Investment Act Grant",
        ],
    )
    assert len(id_to_name(path)) == 2
