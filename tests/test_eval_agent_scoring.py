"""Key-fact matcher tests. Currency tolerance is the load-bearing part:
models restate $1,391,157,700 as '$1,391.2 million' or '$1.4 billion',
and an exact-string matcher would score every correct answer as wrong.
"""
from __future__ import annotations

from eval.agent_schema import KeyFact
from eval.agent_scoring import currency_values, fact_matches


def cf(v):
    return KeyFact(kind="currency", value=v)


def test_currency_exact_form():
    assert fact_matches(cf("$1,391,157,700"), "ADC received $1,391,157,700 from the General Fund.")


def test_currency_scale_words_and_suffixes_are_equivalent():
    assert fact_matches(cf("$1,234.5M"), "the total was 1234.5 million dollars")
    assert fact_matches(cf("$2.5 billion"), "roughly $2,500 million")


def test_currency_rounding_within_half_percent_matches():
    # 1,391.2M vs 1,391,157,700 differs by ~0.003% — a faithful rounding.
    assert fact_matches(cf("$1,391,157,700"), "about $1,391.2 million")


def test_currency_wrong_number_rejected():
    assert not fact_matches(cf("$1,391,157,700"), "ADC received $1,214,000,000.")


def test_currency_ignores_fiscal_years_as_numbers():
    # 'FY 2025' must not parse as the number 2025 matching a $2,025 fact
    # by accident of formatting-insensitive comparison at 0.5% tolerance.
    assert not fact_matches(cf("$2,032"), "In FY 2025 the fee was unchanged.")


def test_string_fact_case_insensitive():
    assert fact_matches(KeyFact(kind="string", value="Department of Corrections"),
                        "the department of corrections budget grew")


def test_regex_fact():
    assert fact_matches(KeyFact(kind="regex", value=r"70\.7\d?%"), "the rate is 70.70%")


def test_currency_values_parser():
    vals = currency_values("$1.5 billion and $300,000 and 12 million")
    assert 1.5e9 in vals and 300_000.0 in vals and 12e6 in vals
