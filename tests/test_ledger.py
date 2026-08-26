"""harness/ledger.py — S19 usage ledger + per-user monthly spend limits
(Plan 4 Task 5).

Covers: month-sharded JSONL append + read, None-cost handling (custom
endpoint / corrupt rows), corrupt-line resilience, the Arizona-fixed-
offset timezone decision at a month-boundary edge, `check_limit`'s
allowed/warn/blocked resolution (exemptions, no-limit, a configured
`0` limit, the 80% warn boundary, the exact blocked message text), and
concurrent-writer safety. All tests point JLBC_DATA_DIR at tmp_path via
monkeypatch (store/config.py convention — see tests/test_store_config.py
and tests/test_harness_settings.py) so nothing here ever touches a real
share.
"""
from __future__ import annotations

import json
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest

from harness.constants import WARN_THRESHOLD_RATIO
from harness.ledger import (
    ARIZONA_TZ,
    LimitStatus,
    MonthUsage,
    _load_msvcrt,
    check_limit,
    month_total,
    record_usage,
)
from harness.settings import ProviderConfig, Settings
from store.config import data_dir


@pytest.fixture(autouse=True)
def _isolated_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    yield


def _shard_path(shard: str):
    return data_dir() / "usage" / f"usage-{shard}.jsonl"


# ---------------------------------------------------------------------------
# record_usage
# ---------------------------------------------------------------------------


def test_record_usage_appends_one_json_line_to_month_shard():
    when = datetime(2026, 7, 15, 12, 0)
    record_usage("analyst1", "standard", "qwen/qwen3-max", 100, 200, 0.05, now=when)
    path = _shard_path("2026-07")
    assert path.exists()
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["user"] == "analyst1"
    assert row["tier"] == "standard"
    assert row["model"] == "qwen/qwen3-max"
    assert row["tokens_in"] == 100
    assert row["tokens_out"] == 200
    assert row["cost_usd"] == 0.05
    assert row["timestamp"].startswith("2026-07-15T12:00:00")


def test_record_usage_two_calls_append_two_lines():
    when = datetime(2026, 7, 15, 12, 0)
    record_usage("analyst1", "standard", "m", 1, 1, 0.01, now=when)
    record_usage("analyst1", "standard", "m", 2, 2, 0.02, now=when)
    lines = _shard_path("2026-07").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2


def test_record_usage_cost_none_still_writes_a_row():
    when = datetime(2026, 7, 15, 12, 0)
    record_usage("analyst1", "standard", "llama-3.1-70b", 10, 20, None, now=when)
    row = json.loads(_shard_path("2026-07").read_text(encoding="utf-8").splitlines()[0])
    assert row["cost_usd"] is None
    assert row["tokens_in"] == 10


def test_record_usage_no_leftover_tmp_files():
    when = datetime(2026, 7, 15, 12, 0)
    record_usage("analyst1", "standard", "m", 1, 1, 0.01, now=when)
    names = {p.name for p in (data_dir() / "usage").iterdir()}
    assert names == {"usage-2026-07.jsonl"}


# ---------------------------------------------------------------------------
# month_total
# ---------------------------------------------------------------------------


def test_month_total_no_rows_returns_zeroed_usage():
    usage = month_total("nobody", now=datetime(2026, 7, 15))
    assert usage == MonthUsage(
        cost_usd=0.0, tokens_in=0, tokens_out=0, rows=0, rows_with_unknown_cost=0
    )


def test_month_total_sums_cost_and_tokens_for_the_named_user_only():
    when = datetime(2026, 7, 1)
    record_usage("analyst1", "standard", "m", 100, 200, 0.10, now=when)
    record_usage("analyst1", "standard", "m", 50, 60, 0.20, now=when)
    record_usage("analyst2", "standard", "m", 999, 999, 5.00, now=when)

    usage = month_total("analyst1", now=when)
    assert usage.cost_usd == pytest.approx(0.30)
    assert usage.tokens_in == 150
    assert usage.tokens_out == 260
    assert usage.rows == 2
    assert usage.rows_with_unknown_cost == 0


def test_month_total_excludes_none_cost_from_dollar_total_but_keeps_tokens():
    when = datetime(2026, 7, 1)
    record_usage("analyst1", "standard", "m", 100, 200, 0.10, now=when)
    record_usage("analyst1", "custom-tier", "custom-model", 40, 40, None, now=when)

    usage = month_total("analyst1", now=when)
    assert usage.cost_usd == pytest.approx(0.10)  # the None row contributes $0, not counted
    assert usage.tokens_in == 140  # but tokens from BOTH rows are kept
    assert usage.tokens_out == 240
    assert usage.rows == 2
    assert usage.rows_with_unknown_cost == 1


def test_month_total_sums_across_differently_cased_spellings_of_one_person():
    # U0: the ledger keeps writing whatever spelling the OS handed it that
    # day (`dmoss` one day, `DMOSS` the next), so the same person's rows can
    # be split across two exact keys. Found by the 2026-08-26 final review:
    # `month_total` used to match by exact username, so the People panel's
    # (folded) total and the cap's (exact) total could disagree.
    when = datetime(2026, 7, 1)
    record_usage("dmoss", "standard", "m", 100, 100, 10.0, now=when)
    record_usage("DMOSS", "standard", "m", 40, 40, 4.2, now=when)

    assert month_total("dmoss", now=when).cost_usd == pytest.approx(14.2)
    assert month_total("DMOSS", now=when).cost_usd == pytest.approx(14.2)
    assert month_total("dmoss", now=when).rows == 2


def test_check_limit_blocks_at_the_summed_total_across_spellings():
    when = datetime(2026, 7, 1)
    record_usage("dmoss", "standard", "m", 1, 1, 60.0, now=when)
    record_usage("DMOSS", "standard", "m", 1, 1, 45.0, now=when)  # 105 total, cap 100
    settings = _settings(default_monthly_limit_usd=100.0)

    # Neither spelling's OWN rows reach the cap (60 and 45 are both under
    # 100) — only the fold-summed total does, which is the property this
    # guards: the cap must not be checkable by asking under a different
    # spelling than the one that pushed the total over.
    assert check_limit("dmoss", settings, now=when).status == "blocked"
    assert check_limit("DMOSS", settings, now=when).status == "blocked"


def test_month_total_blank_user_never_folds_onto_a_named_row():
    # Mirrors users.whoami.same_person: "" is not a fold-match for anyone,
    # including another blank row recorded under a different spelling of
    # nothing (there isn't one — "" is already folded).
    when = datetime(2026, 7, 1)
    record_usage("dmoss", "standard", "m", 1, 1, 5.0, now=when)
    record_usage("", "standard", "m", 1, 1, 2.0, now=when)

    assert month_total("", now=when).cost_usd == pytest.approx(2.0)
    assert month_total("dmoss", now=when).cost_usd == pytest.approx(5.0)


def test_month_sharding_two_months_do_not_mix():
    record_usage("analyst1", "standard", "m", 10, 10, 1.0, now=datetime(2026, 6, 30, 23, 0))
    record_usage("analyst1", "standard", "m", 10, 10, 2.0, now=datetime(2026, 7, 1, 0, 30))

    june = month_total("analyst1", now=datetime(2026, 6, 15))
    july = month_total("analyst1", now=datetime(2026, 7, 15))
    assert june.cost_usd == pytest.approx(1.0)
    assert june.rows == 1
    assert july.cost_usd == pytest.approx(2.0)
    assert july.rows == 1


def test_default_now_is_current_month_when_not_pinned():
    # No `now=` — must use "today" so a fresh call lands in the shard
    # month_total(default) also reads, proving the clock isn't hardcoded
    # to any fixture value.
    record_usage("analyst1", "standard", "m", 1, 1, 0.01)
    usage = month_total("analyst1")
    assert usage.rows == 1


# ---------------------------------------------------------------------------
# Timezone: Arizona fixed offset, not UTC, not host-local
# ---------------------------------------------------------------------------


def test_naive_now_is_treated_as_arizona_local():
    # 11pm Arizona time on the 31st must land in that month's shard, not
    # spill to the next calendar day/month the way a UTC interpretation
    # of the same wall-clock numbers might.
    record_usage("analyst1", "standard", "m", 1, 1, 0.01, now=datetime(2026, 7, 31, 23, 0))
    assert month_total("analyst1", now=datetime(2026, 7, 31)).rows == 1
    assert month_total("analyst1", now=datetime(2026, 8, 1)).rows == 0


def test_utc_aware_now_converts_to_arizona_before_sharding():
    # 2026-08-01 02:00 UTC is 2026-07-31 19:00 Arizona (UTC-7, no DST) —
    # must land in the JULY shard, proving month_shard is computed from
    # Arizona time, not from whatever tzinfo the caller happened to pass.
    utc_now = datetime(2026, 8, 1, 2, 0, tzinfo=timezone.utc)
    record_usage("analyst1", "standard", "m", 1, 1, 0.01, now=utc_now)
    assert _shard_path("2026-07").exists()
    assert not _shard_path("2026-08").exists()
    assert month_total("analyst1", now=datetime(2026, 7, 31)).rows == 1


def test_arizona_tz_is_fixed_utc_minus_7_no_dst():
    assert ARIZONA_TZ.utcoffset(None).total_seconds() == -7 * 3600


# ---------------------------------------------------------------------------
# Corrupt-line resilience
# ---------------------------------------------------------------------------


def test_corrupt_line_is_skipped_not_fatal(capsys):
    when = datetime(2026, 7, 1)
    record_usage("analyst1", "standard", "m", 10, 10, 1.0, now=when)
    path = _shard_path("2026-07")
    with path.open("a", encoding="utf-8") as f:
        f.write("{not valid json at all\n")
    record_usage("analyst1", "standard", "m", 20, 20, 2.0, now=when)

    usage = month_total("analyst1", now=when)  # must not raise
    assert usage.rows == 2
    assert usage.cost_usd == pytest.approx(3.0)
    err = capsys.readouterr().err
    assert "corrupt" in err.lower()


def test_non_object_json_line_is_skipped_not_fatal():
    when = datetime(2026, 7, 1)
    path = _shard_path("2026-07")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write("[1, 2, 3]\n")
    record_usage("analyst1", "standard", "m", 5, 5, 0.5, now=when)

    usage = month_total("analyst1", now=when)  # must not raise
    assert usage.rows == 1


def test_blank_lines_are_ignored():
    when = datetime(2026, 7, 1)
    path = _shard_path("2026-07")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n\n", encoding="utf-8")
    record_usage("analyst1", "standard", "m", 5, 5, 0.5, now=when)
    assert month_total("analyst1", now=when).rows == 1


# ---------------------------------------------------------------------------
# Concurrent-writer safety
# ---------------------------------------------------------------------------


def test_concurrent_appends_do_not_corrupt_the_ledger():
    when = datetime(2026, 7, 1)
    n = 25
    errors = []

    def _write(i):
        try:
            record_usage("analyst1", "standard", "m", i, i, float(i), now=when)
        except Exception as exc:  # pragma: no cover - failure path
            errors.append(exc)

    threads = [threading.Thread(target=_write, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    lines = _shard_path("2026-07").read_text(encoding="utf-8").splitlines()
    assert len(lines) == n
    # Every line must be independently well-formed — proves writes never
    # interleaved into a single garbled line.
    parsed = [json.loads(line) for line in lines]
    assert {row["tokens_in"] for row in parsed} == set(range(n))


# ---------------------------------------------------------------------------
# check_limit
# ---------------------------------------------------------------------------


def _settings(**kwargs) -> Settings:
    return Settings(
        provider=ProviderConfig(api_key="sk-or-x", provider="openrouter"),
        admin_username=kwargs.pop("admin_username", "destin"),
        **kwargs,
    )


def test_check_limit_allowed_when_no_default_no_override():
    settings = _settings()
    status = check_limit("analyst1", settings, now=datetime(2026, 7, 1))
    assert status.status == "allowed"
    assert status.message is None
    assert status.reason == "no limit"
    assert status.limit_usd is None


def test_check_limit_allowed_well_under_threshold():
    when = datetime(2026, 7, 1)
    record_usage("analyst1", "standard", "m", 1, 1, 10.0, now=when)
    settings = _settings(default_monthly_limit_usd=100.0)
    status = check_limit("analyst1", settings, now=when)
    assert status.status == "allowed"
    assert status.message is None
    assert status.reason is None
    assert status.limit_usd == 100.0
    assert status.month_usd == pytest.approx(10.0)


def test_check_limit_79_percent_is_allowed():
    when = datetime(2026, 7, 1)
    record_usage("analyst1", "standard", "m", 1, 1, 79.0, now=when)
    settings = _settings(default_monthly_limit_usd=100.0)
    status = check_limit("analyst1", settings, now=when)
    assert status.status == "allowed"


def test_check_limit_80_percent_is_warn():
    when = datetime(2026, 7, 1)
    record_usage("analyst1", "standard", "m", 1, 1, 80.0, now=when)
    settings = _settings(default_monthly_limit_usd=100.0)
    status = check_limit("analyst1", settings, now=when)
    assert status.status == "warn"
    assert status.message is not None
    assert "$80.00" in status.message
    assert "$100.00" in status.message


def test_check_limit_warn_ratio_matches_named_constant():
    # Pin exactly at the constant, not a hardcoded 0.8, so a future
    # recalibration of WARN_THRESHOLD_RATIO doesn't quietly desync the
    # test from the code it's checking.
    limit = 250.0
    when = datetime(2026, 7, 1)
    record_usage(
        "analyst1", "standard", "m", 1, 1, limit * WARN_THRESHOLD_RATIO, now=when
    )
    settings = _settings(default_monthly_limit_usd=limit)
    status = check_limit("analyst1", settings, now=when)
    assert status.status == "warn"


def test_check_limit_100_percent_is_blocked():
    when = datetime(2026, 7, 1)
    record_usage("analyst1", "standard", "m", 1, 1, 100.0, now=when)
    settings = _settings(default_monthly_limit_usd=100.0)
    status = check_limit("analyst1", settings, now=when)
    assert status.status == "blocked"


def test_check_limit_over_100_percent_is_blocked():
    when = datetime(2026, 7, 1)
    record_usage("analyst1", "standard", "m", 1, 1, 150.0, now=when)
    settings = _settings(default_monthly_limit_usd=100.0)
    status = check_limit("analyst1", settings, now=when)
    assert status.status == "blocked"


def test_check_limit_blocked_message_exact_text():
    when = datetime(2026, 7, 1)
    record_usage("analyst1", "standard", "m", 1, 1, 100.0, now=when)
    settings = _settings(default_monthly_limit_usd=25.0, admin_username="destin")
    status = check_limit("analyst1", settings, now=when)
    assert status.status == "blocked"
    assert status.message == (
        "You've reached your monthly AI usage limit ($25.00) "
        "— ask destin to raise it."
    )


def test_check_limit_blocked_message_empty_admin_username_reads_as_sentence():
    when = datetime(2026, 7, 1)
    record_usage("analyst1", "standard", "m", 1, 1, 100.0, now=when)
    settings = _settings(default_monthly_limit_usd=25.0, admin_username="")
    status = check_limit("analyst1", settings, now=when)
    assert status.message == (
        "You've reached your monthly AI usage limit ($25.00) "
        "— ask your admin to raise it."
    )
    assert "ask  to raise it" not in status.message  # no double-space blank


def test_check_limit_exempt_user_always_allowed_even_far_over_limit():
    when = datetime(2026, 7, 1)
    record_usage("director", "standard", "m", 1, 1, 10_000.0, now=when)
    settings = _settings(default_monthly_limit_usd=10.0, exempt_users=("director",))
    status = check_limit("director", settings, now=when)
    assert status.status == "allowed"
    assert status.message is None
    assert status.reason == "exempt"


def test_check_limit_zero_limit_blocks_outright_with_no_usage_at_all():
    # An admin typing 0 means "this user may spend nothing" — must block
    # even with $0 spent so far, distinguishing it from None ("unlimited").
    settings = _settings(user_limits={"analyst1": 0.0})
    status = check_limit("analyst1", settings, now=datetime(2026, 7, 1))
    assert status.status == "blocked"
    assert status.message is not None


def test_check_limit_zero_vs_none_limit_are_different_outcomes():
    when = datetime(2026, 7, 1)
    none_limit = _settings()
    zero_limit = _settings(default_monthly_limit_usd=0.0)
    assert check_limit("analyst1", none_limit, now=when).status == "allowed"
    assert check_limit("analyst1", zero_limit, now=when).status == "blocked"


def test_check_limit_custom_provider_limits_inactive():
    when = datetime(2026, 7, 1)
    record_usage("analyst1", "standard", "m", 1, 1, None, now=when)
    settings = Settings(
        provider=ProviderConfig(
            base_url="https://gateway.example.gov/v1",
            api_key="internal",
            provider="custom",
        ),
        default_monthly_limit_usd=10.0,
    )
    status = check_limit("analyst1", settings, now=when)
    assert status.status == "allowed"
    assert status.reason == "custom endpoint"
    assert status.limit_usd is None
    assert status.month_usd is None


def test_check_limit_custom_provider_overrides_even_a_would_be_blocked_user():
    when = datetime(2026, 7, 1)
    record_usage("analyst1", "standard", "m", 1, 1, None, now=when)
    settings = Settings(
        provider=ProviderConfig(provider="custom", api_key="internal"),
        default_monthly_limit_usd=1.0,  # would block on a real (non-custom) provider
    )
    status = check_limit("analyst1", settings, now=when)
    assert status.status == "allowed"


def test_check_limit_returns_limit_status_dataclass():
    status = check_limit("analyst1", _settings(), now=datetime(2026, 7, 1))
    assert isinstance(status, LimitStatus)


# ---------------------------------------------------------------------------
# Fix-review round 2
# ---------------------------------------------------------------------------
# Five gaps found by an independent quality review of the first pass:
#   1. CRITICAL — a mis-encoded byte in a shard file crashed month_total
#      (UnicodeDecodeError, a ValueError subclass, wasn't caught).
#   2. The read-failure fallback failed open silently, conflating "no
#      file yet" with "share unreadable" — the latter needs a log line.
#   3. record_usage's failure contract (raises, doesn't swallow) was
#      undocumented and untested.
#   4. Summed cost_usd wasn't rounded, so a total that DISPLAYS as the
#      limit could compare as narrowly under it.
#   5. msvcrt=None degraded cross-process locking silently.


def test_month_total_survives_a_mis_encoded_utf8_byte_in_a_line():
    """The critical regression: a torn write (or a hand-edited row) can
    leave one line with an invalid UTF-8 byte sequence. That must not
    crash month_total for the whole file — it must be skipped exactly
    like a malformed-JSON line, and every OTHER row must still count.
    """
    when = datetime(2026, 7, 1)
    record_usage("analyst1", "standard", "m", 10, 10, 1.0, now=when)
    path = _shard_path("2026-07")
    with path.open("ab") as f:
        f.write(b"\xff\xfe not valid utf-8 at all\n")
    record_usage("analyst1", "standard", "m", 20, 20, 2.0, now=when)

    usage = month_total("analyst1", now=when)  # must not raise
    assert usage.rows == 2
    assert usage.cost_usd == pytest.approx(3.0)


def test_check_limit_survives_a_mis_encoded_utf8_byte_in_a_line():
    """Same defect, exercised through the actual gate (check_limit),
    which is what the review flagged as the real-world blast radius —
    exempt and no-limit users still read the file to populate
    `month_usd`, so they were exposed too, not just ratio-checked users.
    """
    when = datetime(2026, 7, 1)
    path = _shard_path("2026-07")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xff\xfe garbage\n")
    settings = _settings(exempt_users=("analyst1",))
    status = check_limit("analyst1", settings, now=when)  # must not raise
    assert status.status == "allowed"


def test_mis_encoded_line_is_logged_to_stderr(capsys):
    when = datetime(2026, 7, 1)
    path = _shard_path("2026-07")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xff\xfe garbage\n")
    month_total("analyst1", now=when)
    err = capsys.readouterr().err
    assert "utf-8" in err.lower() or "decode" in err.lower()


def test_month_total_missing_shard_file_is_silent_not_an_error(capsys):
    # "No usage yet" (the overwhelmingly common case — new month, new
    # hire) must NOT print a warning; only a genuine read failure should.
    usage = month_total("nobody", now=datetime(2026, 7, 1))
    assert usage.rows == 0
    assert capsys.readouterr().err == ""


def test_month_total_unreadable_shard_fails_open_but_logs_to_stderr(
    monkeypatch, capsys
):
    """A degraded/unreachable share must not lock every analyst out —
    fail-open matches S19's "search is never affected" spirit for an
    infrastructure blip — but unlike a missing file, this MUST be logged:
    a silent false-"allowed" on a paid-key spend gate is a blind spot an
    admin needs a signal for.
    """
    when = datetime(2026, 7, 1)
    record_usage("analyst1", "standard", "m", 1, 1, 5.0, now=when)
    path = _shard_path("2026-07")
    real_read_bytes = Path.read_bytes

    def _boom(self, *args, **kwargs):
        if self == path:
            raise PermissionError(13, "Permission denied")
        return real_read_bytes(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", _boom)

    usage = month_total("analyst1", now=when)  # must not raise
    assert usage.rows == 0
    assert usage.cost_usd == 0.0
    err = capsys.readouterr().err
    assert "unreadable" in err.lower() or "permission" in err.lower()


def test_check_limit_fails_open_but_logs_when_share_is_unreadable(
    monkeypatch, capsys
):
    when = datetime(2026, 7, 1)
    # This usage would normally BLOCK the user outright.
    record_usage("analyst1", "standard", "m", 1, 1, 100.0, now=when)
    settings = _settings(default_monthly_limit_usd=100.0)
    path = _shard_path("2026-07")
    real_read_bytes = Path.read_bytes

    def _boom(self, *args, **kwargs):
        if self == path:
            raise PermissionError(13, "Permission denied")
        return real_read_bytes(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", _boom)

    status = check_limit("analyst1", settings, now=when)
    assert status.status == "allowed"  # fails open, deliberately
    err = capsys.readouterr().err
    assert "unreadable" in err.lower() or "permission" in err.lower()


def test_record_usage_propagates_write_failures_rather_than_swallowing(
    monkeypatch,
):
    def _boom(*args, **kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr("harness.ledger._append_line", _boom)
    with pytest.raises(OSError):
        record_usage("analyst1", "standard", "m", 1, 1, 0.01, now=datetime(2026, 7, 1))


def test_month_total_rounds_cost_to_cents_once():
    when = datetime(2026, 7, 1)
    record_usage("analyst1", "standard", "m", 1, 1, 0.1, now=when)
    record_usage("analyst1", "standard", "m", 1, 1, 0.1, now=when)
    record_usage("analyst1", "standard", "m", 1, 1, 0.1, now=when)
    usage = month_total("analyst1", now=when)
    # Exact equality, not approx — proves the total was rounded rather
    # than left as raw-float-summation residue (0.30000000000000004).
    assert usage.cost_usd == 0.3


def test_check_limit_ratio_uses_the_same_rounded_total_the_message_shows():
    """Regression for review point 4: 0.1 + 0.7 sums to
    0.7999999999999999 in raw float — narrowly UNDER a 0.8 limit, so an
    unrounded comparison would report "warn" (ratio just under 1.0)
    while the displayed total rounds to $0.80, the full limit. Rounding
    ONCE, before both the comparison and the message, keeps the two from
    disagreeing.
    """
    when = datetime(2026, 7, 1)
    record_usage("analyst1", "standard", "m", 1, 1, 0.1, now=when)
    record_usage("analyst1", "standard", "m", 1, 1, 0.7, now=when)
    settings = _settings(default_monthly_limit_usd=0.8)

    status = check_limit("analyst1", settings, now=when)
    assert status.month_usd == 0.8
    assert status.status == "blocked"
    assert "$0.80" in status.message


# ---------------------------------------------------------------------------
# msvcrt degradation is logged, not silent
# ---------------------------------------------------------------------------


def test_msvcrt_unavailable_logs_to_stderr_and_returns_none(monkeypatch, capsys):
    # sys.modules[name] = None is the documented way to force `import
    # name` to raise ImportError, without needing a non-Windows machine
    # or a full module reload to exercise the degrade path.
    monkeypatch.setitem(sys.modules, "msvcrt", None)
    result = _load_msvcrt()
    assert result is None
    err = capsys.readouterr().err
    assert "msvcrt" in err.lower()
