"""harness/ledger.breakdown() — all users' rows grouped for the admin page
(Plan 5 Task 2).

`month_total` answers "what has THIS user spent"; the admin page needs
"what has the whole office spent, split by user / model / tier". The
properties pinned here are the ones that would otherwise fail silently:
an unknown-cost row must not read as $0, a pre-S22 row with no
`cached_tokens` key must read as 0 rather than as corrupt, and one
undecodable byte must not take out the whole month (Ground truth 8 —
`UnicodeDecodeError` is a `ValueError`, not an `OSError`).
"""
from __future__ import annotations

import json

import pytest

from harness.ledger import breakdown, month_total
from store.config import data_dir


@pytest.fixture(autouse=True)
def _isolated_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    yield


def _write_rows(shard: str, rows: list[dict]) -> None:
    path = data_dir() / "usage" / f"usage-{shard}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8",
    )


ROWS = [
    {"user": "a", "tier": "standard", "model": "m1", "tokens_in": 10,
     "tokens_out": 5, "cost_usd": 0.10, "cached_tokens": 8},
    {"user": "a", "tier": "standard", "model": "m1", "tokens_in": 10,
     "tokens_out": 5, "cost_usd": None},          # custom endpoint (S15)
    {"user": "b", "tier": "deep_research", "model": "m2", "tokens_in": 1,
     "tokens_out": 1, "cost_usd": 0.20},          # no cached_tokens key (pre-S22)
]


def test_breakdown_excludes_unknown_cost_from_dollars():
    _write_rows("2026-07", ROWS)
    by_user = {g.key: g for g in breakdown("2026-07", by="user")}
    assert by_user["a"].cost_usd == 0.10
    assert by_user["a"].rows_with_unknown_cost == 1
    assert by_user["a"].cached_tokens == 8
    assert by_user["b"].cached_tokens == 0   # absent key reads as 0, not corrupt


def test_breakdown_counts_every_row_including_unknown_cost():
    _write_rows("2026-07", ROWS)
    by_user = {g.key: g for g in breakdown("2026-07", by="user")}
    # `rows` is the honest call count; `rows_with_unknown_cost` is the subset
    # whose dollars are missing. The admin page renders both, so a user with
    # two calls and one price must not read as having made one call.
    assert by_user["a"].rows == 2
    assert by_user["a"].tokens_in == 20
    assert by_user["a"].tokens_out == 10


def test_breakdown_groups_by_model_and_tier():
    _write_rows("2026-07", ROWS)
    by_model = {g.key: g for g in breakdown("2026-07", by="model")}
    assert set(by_model) == {"m1", "m2"}
    assert by_model["m1"].rows == 2

    by_tier = {g.key: g for g in breakdown("2026-07", by="tier")}
    assert set(by_tier) == {"standard", "deep_research"}
    assert by_tier["deep_research"].cost_usd == 0.20


def test_breakdown_is_sorted_by_cost_descending():
    _write_rows("2026-07", ROWS)
    keys = [g.key for g in breakdown("2026-07", by="user")]
    # b spent $0.20, a spent $0.10 — the admin opens this page to find out
    # who is spending the most, so the biggest number goes first.
    assert keys == ["b", "a"]


def test_breakdown_survives_one_undecodable_byte():
    """Ground truth 8: one mis-encoded byte once crashed the spend gate.

    The readable rows must still come back — a corrupt line costs its own
    row, not the month.
    """
    path = data_dir() / "usage" / "usage-2026-07.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    good = json.dumps(ROWS[0]).encode("utf-8")
    other = json.dumps(ROWS[2]).encode("utf-8")
    path.write_bytes(good + b"\n" + b'{"user": "\xff\xfe bad"}' + b"\n" + other + b"\n")

    by_user = {g.key: g for g in breakdown("2026-07", by="user")}
    assert set(by_user) == {"a", "b"}
    assert by_user["a"].cost_usd == 0.10


def test_breakdown_of_a_month_with_no_rows_is_empty():
    # A new month, or a month before the app was installed. Not an error.
    assert breakdown("2019-01", by="user") == []


def test_breakdown_rejects_an_unknown_grouping_key():
    _write_rows("2026-07", ROWS)
    with pytest.raises(ValueError):
        breakdown("2026-07", by="model_name")


def test_breakdown_dollars_agree_with_month_total():
    """The two readers must never disagree about one user's spend.

    They round through the same helper for exactly this reason: an admin
    page that shows $0.31 next to a Settings page that shows $0.30 for the
    same person destroys confidence in both numbers.
    """
    rows = [
        {"user": "a", "tier": "standard", "model": "m1", "tokens_in": 1,
         "tokens_out": 1, "cost_usd": 0.1, "cached_tokens": 0},
        {"user": "a", "tier": "standard", "model": "m1", "tokens_in": 1,
         "tokens_out": 1, "cost_usd": 0.7, "cached_tokens": 0},
    ]
    from datetime import datetime

    _write_rows("2026-07", rows)
    group = {g.key: g for g in breakdown("2026-07", by="user")}["a"]
    total = month_total("a", now=datetime(2026, 7, 15, 12, 0))
    # 0.1 + 0.7 is 0.7999999999999999 in IEEE 754; both sides must land on 0.8.
    assert group.cost_usd == total.cost_usd == 0.8


def test_breakdown_treats_a_missing_field_as_its_own_group():
    """A row with no `model` key must not vanish from a per-model view.

    Dropping it would understate the office total on one tab and not the
    others — three breakdowns of the same month that don't add up to the
    same number is exactly the kind of thing that makes an admin stop
    trusting the page.
    """
    _write_rows("2026-07", [
        {"user": "a", "tier": "standard", "tokens_in": 1, "tokens_out": 1,
         "cost_usd": 0.05},
    ])
    by_model = {g.key: g for g in breakdown("2026-07", by="model")}
    assert sum(g.cost_usd for g in by_model.values()) == 0.05
