"""Reconciliation tests.

A computed total that renders like a sourced figure is the kind of thing
that erodes trust in a whole table. Reconciliation is what lets a derived
number say what it was computed FROM, mechanically, so the model cannot
pass arithmetic off as provenance.
"""
from __future__ import annotations

from citation.figures import Figure
from citation.reconcile import Derivation, reconcile


def f(value, scale=1):
    return Figure(text=str(value), start=0, end=1, value=value, scale=scale)


def test_sum_of_two():
    d = reconcile(f(300.0), [f(100.0), f(200.0)])
    assert d == Derivation(operation="sum", inputs=[0, 1])


def test_sum_of_three():
    d = reconcile(f(600.0), [f(100.0), f(200.0), f(300.0)])
    assert d is not None and d.operation == "sum"
    assert sorted(d.inputs) == [0, 1, 2]


def test_difference():
    d = reconcile(f(376.2), [f(1000.0), f(623.8)])
    assert d is not None and d.operation == "difference"
    assert sorted(d.inputs) == [0, 1]


def test_percent_change():
    # 1,038 is 3.8% above 1,000.
    d = reconcile(f(3.8), [f(1000.0), f(1038.0)])
    assert d is not None and d.operation == "percent_change"


def test_unrelated_number_is_not_reconciled():
    assert reconcile(f(999999.0), [f(100.0), f(200.0)]) is None


def test_rounding_tolerated():
    # "$1.06 billion" restating 1,058,400,000.
    d = reconcile(f(1.06, scale=1_000_000_000), [f(1058400000.0)])
    assert d is not None and d.operation == "sum" and d.inputs == [0]


def test_no_linked_figures_means_no_derivation():
    assert reconcile(f(300.0), []) is None


def test_a_zero_valued_input_does_not_crash_percent_change():
    # A linked figure of 0 is a legal budget line (an unfunded program).
    # Dividing by it must be guarded, not raise into the turn.
    assert reconcile(f(50.0), [f(0.0), f(123.0)]) is None
