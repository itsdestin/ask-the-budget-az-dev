"""Tests for funds/slug.py — fund-name → slug derivation.

Plan §4.1 step 3 specifies the rules:
  - Lowercase, replace non-alphanumeric with `-`
  - Drop "fund" suffix when present
  - Collapse consecutive hyphens

Worked examples from the plan:
  "Aviation Fund" → 'aviation'
  "State Highway Fund" → 'state-highway'
  "Health Innovation Trust Fund" → 'health-innovation-trust'
"""
from __future__ import annotations

import pytest

from funds.slug import slugify_fund_name


# --- plan-documented worked examples ---------------------------------------


def test_slugify_aviation_fund():
    assert slugify_fund_name("Aviation Fund") == "aviation"


def test_slugify_state_highway_fund():
    assert slugify_fund_name("State Highway Fund") == "state-highway"


def test_slugify_health_innovation_trust_fund():
    assert slugify_fund_name("Health Innovation Trust Fund") == "health-innovation-trust"


# --- rule-by-rule coverage --------------------------------------------------


def test_slugify_lowercases_input():
    assert slugify_fund_name("AVIATION FUND") == "aviation"


def test_slugify_replaces_non_alphanumeric_with_hyphens():
    """Per plan: non-alphanumeric → '-'. Punctuation, spaces, slashes."""
    assert slugify_fund_name("ADOA - Capital Outlay") == "adoa-capital-outlay"
    assert slugify_fund_name("School Facilities/Capital Outlay") == "school-facilities-capital-outlay"
    # Leading 'Fund' is preserved (only the *trailing* fund suffix is stripped per plan §4.1).
    assert slugify_fund_name("Fund (Special)") == "fund-special"


def test_slugify_drops_fund_suffix():
    """`Fund` at end of name is informational — drop it."""
    assert slugify_fund_name("General Fund") == "general"
    assert slugify_fund_name("Aviation Fund") == "aviation"


def test_slugify_drops_only_trailing_fund_not_internal():
    """`Trust Fund Reserve` should keep `fund` because it's internal, not trailing."""
    assert slugify_fund_name("Trust Fund Reserve") == "trust-fund-reserve"


def test_slugify_handles_apostrophes_and_quotes():
    assert slugify_fund_name("Children's Health Fund") == "children-s-health"


def test_slugify_collapses_consecutive_hyphens():
    """Multiple non-alphanumerics in a row should collapse to one hyphen."""
    assert slugify_fund_name("ADOA  --  Reserve") == "adoa-reserve"


def test_slugify_strips_leading_and_trailing_hyphens():
    assert slugify_fund_name(" - General Fund - ") == "general"


def test_slugify_handles_alphanumerics():
    """Numbers in fund names are preserved."""
    assert slugify_fund_name("9-1-1 Emergency Fund") == "9-1-1-emergency"


def test_slugify_empty_input_returns_empty():
    assert slugify_fund_name("") == ""


def test_slugify_only_punctuation_returns_empty():
    """All-punctuation input should not produce a non-empty slug."""
    assert slugify_fund_name(" -- - ") == ""


def test_slugify_just_word_fund_returns_empty():
    """The bare word 'Fund' has nothing to slugify after stripping the suffix."""
    assert slugify_fund_name("Fund") == ""


def test_slugify_strips_outer_whitespace():
    assert slugify_fund_name("   General Fund   ") == "general"
