"""harness/notices.py + the S13 runtime model fallback (Plan 5 Task 5).

Two halves of one feature. The notices file is the admin's "what went
wrong while I wasn't looking" feed; the fallback is the thing that most
often writes to it.

THE LOAD-BEARING ASSERTION is `test_model_fallback_does_not_rewrite_settings`.
S13 requires a retired model to degrade AI Mode to a different MODEL,
never to a dead feature — and the trap is where that gets recorded.
Writing the replacement back to settings.json would mean three office
machines hitting the same dead model stage three concurrent writes to one
file on an SMB share, and the last writer wins over whatever the admin
was editing at the time.
"""
from __future__ import annotations

import json

import httpx
import pytest

from harness.catalog import RECOMMENDATIONS
from harness.notices import (
    KIND_MODEL_FALLBACK,
    MAX_NOTICES,
    notices_path,
    read_notices,
    record_notice,
)
from harness.session import HarnessSession, reset_model_overrides
from harness.settings import ProviderConfig, Settings, TierConfig, settings_path, save_settings
from tests.test_harness_session import (
    FakeExecutor,
    FakeLedger,
    Provider,
    finish_chunk,
    sse,
    text_chunk,
    usage_chunk,
)

SYSTEM_PROMPT = "SYSTEM PROMPT (test stub)."
DEAD_MODEL = "vendor/retired-model"
FIRST_STANDARD_FALLBACK = next(
    r.id for r in RECOMMENDATIONS if r.tier_hint == "standard"
)


@pytest.fixture(autouse=True)
def _isolated_share(monkeypatch, tmp_path):
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    reset_model_overrides()
    yield
    reset_model_overrides()


# ---------------------------------------------------------------------------
# harness/notices.py
# ---------------------------------------------------------------------------


def test_a_notice_round_trips():
    record_notice(KIND_MODEL_FALLBACK, "the standard model was retired")
    rows = read_notices()
    assert len(rows) == 1
    assert rows[0]["kind"] == KIND_MODEL_FALLBACK
    assert rows[0]["message"] == "the standard model was retired"
    # Arizona-local ISO 8601 with the offset, same as the ledger — the two
    # feeds sit next to each other on the admin page and must not disagree
    # about what time it is.
    assert rows[0]["at"].endswith("-07:00")


def test_notices_come_back_oldest_first():
    for i in range(3):
        record_notice(KIND_MODEL_FALLBACK, f"notice {i}")
    assert [r["message"] for r in read_notices()] == ["notice 0", "notice 1", "notice 2"]


def test_reading_an_absent_file_is_not_an_error():
    # A fresh install has never recorded a notice. That is the good case.
    assert read_notices() == []


def test_since_filters_by_timestamp():
    record_notice(KIND_MODEL_FALLBACK, "old")
    first_at = read_notices()[0]["at"]
    record_notice(KIND_MODEL_FALLBACK, "new")
    assert [r["message"] for r in read_notices(since=first_at)] == ["new"]


def test_the_read_is_capped():
    for i in range(MAX_NOTICES + 25):
        record_notice(KIND_MODEL_FALLBACK, f"n{i}")
    rows = read_notices()
    assert len(rows) == MAX_NOTICES
    # The cap keeps the NEWEST rows — an admin glancing at the feed wants
    # what just broke, not what broke first.
    assert rows[-1]["message"] == f"n{MAX_NOTICES + 24}"


def test_one_corrupt_line_costs_only_itself():
    record_notice(KIND_MODEL_FALLBACK, "good one")
    with notices_path().open("ab") as f:
        f.write(b"{ not json\n")
        f.write(b'\xff\xfe not utf-8\n')
    record_notice(KIND_MODEL_FALLBACK, "good two")
    assert [r["message"] for r in read_notices()] == ["good one", "good two"]


def test_recording_never_raises_when_the_share_is_unwritable(monkeypatch, capsys):
    def boom(*_args, **_kwargs):
        raise OSError("share went away")

    monkeypatch.setattr("harness.notices._append_line", boom)
    # A notice is a courtesy message ABOUT a failure — it must never
    # become a second failure on a path already handling one.
    record_notice(KIND_MODEL_FALLBACK, "something broke")
    assert "couldn't record" in capsys.readouterr().err


def test_an_unknown_kind_is_still_recorded_and_flagged(capsys):
    record_notice("invented_kind", "hello")
    assert read_notices()[0]["kind"] == "invented_kind"
    assert "unknown notice kind" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# S13 runtime model fallback
# ---------------------------------------------------------------------------


def dead_model_response() -> httpx.Response:
    """What OpenRouter answers for a model it no longer routes to."""
    return httpx.Response(
        404,
        json={"error": {"message": f"No endpoints found for {DEAD_MODEL}.", "code": 404}},
    )


def working_response() -> httpx.Response:
    return sse(text_chunk("Here is the answer."), finish_chunk(), usage_chunk())


def build_session(provider: Provider, *, endpoint: str = "openrouter", **kwargs):
    settings = Settings(
        provider=ProviderConfig(
            api_key="sk-test",
            provider=endpoint,
            base_url="https://openrouter.ai/api/v1",
        ),
        tiers={"standard": TierConfig(model=DEAD_MODEL),
               "deep_research": TierConfig(model="vendor/deep")},
    )
    save_settings(settings)
    return HarnessSession(
        "c1",
        tier="standard",
        user="analyst1",
        settings=settings,
        executor=FakeExecutor(),
        transport=provider.transport(),
        system_prompt=SYSTEM_PROMPT,
        tools=[],
        check_limit=FakeLedger().check_limit,
        record_usage=lambda *a, **k: None,
        **kwargs,
    )


def _frames(session, text: str = "hello") -> list[dict]:
    return list(session.stream_turn(text))


def _turn_complete(frames: list[dict]) -> dict:
    return next(f for f in frames if f["type"] == "turn_complete")


def test_model_fallback_does_not_rewrite_settings():
    provider = Provider(dead_model_response, working_response)
    session = build_session(provider)
    before = settings_path().read_bytes()

    frames = _frames(session)

    # It answered — S13's requirement is a different model, not a dead
    # feature.
    assert _turn_complete(frames)["model"] == FIRST_STANDARD_FALLBACK
    assert any(f["type"] == "assistant_text_delta" for f in frames)
    # WHY: three office machines hitting the same dead model would
    # otherwise stage three concurrent writes to one settings.json on an
    # SMB share, and the last writer wins over whatever the admin was
    # editing at the time.
    assert settings_path().read_bytes() == before
    assert any(n["kind"] == KIND_MODEL_FALLBACK for n in read_notices())


def test_the_replacement_model_is_the_one_actually_requested():
    provider = Provider(dead_model_response, working_response)
    _frames(build_session(provider))
    assert [b["model"] for b in provider.bodies] == [DEAD_MODEL, FIRST_STANDARD_FALLBACK]


def test_the_notice_names_both_models():
    provider = Provider(dead_model_response, working_response)
    _frames(build_session(provider))
    message = read_notices()[0]["message"]
    assert DEAD_MODEL in message and FIRST_STANDARD_FALLBACK in message
    # The admin has to know this is temporary, or they will never go fix
    # the setting and will be baffled after the next restart.
    assert "restarted" in message


def test_the_override_persists_for_the_process():
    """The second turn must not re-discover the dead model.

    A fresh 404 per question wastes an analyst's time on a request already
    known to fail, once per question, all day.
    """
    provider = Provider(dead_model_response, working_response)
    session = build_session(provider)
    _frames(session)
    # An offset, NOT provider.bodies.clear(): Provider picks its scripted
    # response by len(bodies), so clearing would rewind the script and
    # replay the 404 — the test would then be measuring the fake.
    after_first_turn = len(provider.bodies)

    _frames(session, "second question")
    assert [b["model"] for b in provider.bodies[after_first_turn:]] == [
        FIRST_STANDARD_FALLBACK
    ]


def test_only_one_notice_per_distinct_transition():
    provider = Provider(dead_model_response, working_response)
    session = build_session(provider)
    _frames(session)
    _frames(session, "again")
    _frames(session, "and again")
    # Not three. A dead model fails on every turn; a notice per question
    # would bury every other notice in the feed by lunchtime.
    assert len([n for n in read_notices() if n["kind"] == KIND_MODEL_FALLBACK]) == 1


def test_a_custom_endpoint_surfaces_the_error_unchanged():
    """S15: there is no recommendation order for someone else's server.

    Substituting an OpenRouter model id would replace an honest error with
    a more confusing one from an endpoint that has never heard of it.
    """
    provider = Provider(dead_model_response)
    frames = _frames(build_session(provider, endpoint="custom"))
    error = next(f for f in frames if f["type"] == "_error")
    assert "No endpoints found" in error["message"]
    assert provider.call_count == 1
    assert read_notices() == []


def test_an_ordinary_provider_error_does_not_switch_models():
    """A 500 is the provider having a bad minute, not a retired model.

    Falling back here would silently answer from a model the admin did not
    choose, at a different price, because of a transient blip.
    """
    provider = Provider(lambda: httpx.Response(500, json={"error": {"message": "upstream boom"}}))
    session = build_session(provider, sleep=lambda _s: None)
    frames = _frames(session)
    assert any(f["type"] == "_error" for f in frames)
    assert {b["model"] for b in provider.bodies} == {DEAD_MODEL}
    assert read_notices() == []


def test_a_404_that_is_not_about_the_model_does_not_switch_models():
    # A hand-edited base_url pointing at a path that doesn't exist. Falling
    # back would hide the real problem behind a working-looking answer.
    provider = Provider(lambda: httpx.Response(404, json={"error": {"message": "Not Found"}}))
    frames = _frames(build_session(provider))
    assert any(f["type"] == "_error" for f in frames)
    assert {b["model"] for b in provider.bodies} == {DEAD_MODEL}
    assert read_notices() == []


def test_when_every_candidate_is_dead_the_error_surfaces():
    provider = Provider(dead_model_response)
    frames = _frames(build_session(provider))
    error = next(f for f in frames if f["type"] == "_error")
    assert "No endpoints found" in error["message"]
    # Every standard recommendation was tried once, plus the configured one.
    standard = [r.id for r in RECOMMENDATIONS if r.tier_hint == "standard"]
    assert {b["model"] for b in provider.bodies} == {DEAD_MODEL, *standard}


def test_a_fixed_setting_is_obeyed_without_a_restart():
    """An admin who picks a new model must not keep getting the fallback.

    The override is keyed on (tier, configured model), so a different
    configured id has no override entry and is used exactly as typed.
    """
    provider = Provider(dead_model_response, working_response)
    session = build_session(provider)
    _frames(session)

    fixed = Settings(
        provider=session.settings.provider,
        tiers={"standard": TierConfig(model="vendor/freshly-chosen"),
               "deep_research": TierConfig(model="vendor/deep")},
    )
    session.settings = fixed
    after_first_turn = len(provider.bodies)
    _frames(session, "after the fix")
    assert provider.bodies[after_first_turn]["model"] == "vendor/freshly-chosen"
