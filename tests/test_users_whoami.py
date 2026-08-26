# tests/test_users_whoami.py
"""users/whoami.py — the ONE answer to "who is this process running as",
and the ONE rule for "are these two usernames the same person" (spec U0).

The source-level guards at the bottom are the point of the file: four
independently-written folds WILL drift, and the three private
`_current_user()` copies that used to live in ingest/ are how a JLBC_USER
override applied to AI usage but not to the job record for the same person.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from users import whoami

ROOT = Path(__file__).resolve().parent.parent


def test_current_user_prefers_the_override(monkeypatch):
    monkeypatch.setenv("JLBC_USER", "analyst1")
    assert whoami.current_user() == "analyst1"


def test_current_user_falls_back_to_the_os(monkeypatch):
    monkeypatch.delenv("JLBC_USER", raising=False)
    monkeypatch.setattr(whoami.getpass, "getuser", lambda: "dmoss")
    assert whoami.current_user() == "dmoss"


def test_current_user_is_blank_when_the_os_cannot_say(monkeypatch):
    monkeypatch.delenv("JLBC_USER", raising=False)

    def boom():
        raise OSError("no USERNAME")

    monkeypatch.setattr(whoami.getpass, "getuser", boom)
    assert whoami.current_user() == ""


@pytest.mark.parametrize("a,b", [
    ("dmoss", "DMOSS"), ("Destin", "destin"), (" dmoss ", "dmoss"),
    ("İ", "i̇"),  # casefold, not lower: Python's lower() leaves these unequal
])
def test_same_person_folds_case_and_whitespace(a, b):
    assert whoami.same_person(a, b)


def test_same_person_never_matches_blank():
    # "" folds to "" — two unnameable users are NOT one person.
    assert not whoami.same_person("", "")
    assert not whoami.same_person("  ", "")


def test_different_people_are_different():
    assert not whoami.same_person("dmoss", "dmoss2")


def test_roster_key_is_identical_for_every_casing():
    assert whoami.roster_key("DMOSS") == whoami.roster_key("dmoss") == "dmoss"


def test_roster_key_sanitises_and_still_folds():
    # THE correction from review: the hash is of the FOLDED form, so the
    # backslash in a domain name does not give DOMAIN\dmoss and domain\dmoss
    # two files.
    a = whoami.roster_key("DOMAIN\\dmoss")
    b = whoami.roster_key("domain\\DMOSS")
    assert a == b
    assert a.startswith("domain-dmoss-")
    assert len(a) == len("domain-dmoss-") + 8


def test_roster_key_truncates_long_names_with_a_hash():
    key = whoami.roster_key("a" * 100)
    assert len(key) == 64 + 1 + 8
    assert key != whoami.roster_key("a" * 99)


def test_roster_key_of_blank_is_blank():
    assert whoami.roster_key("  ") == ""


def _shipped_python() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "*.py"], cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout.split()
    return [ROOT / p for p in out if not p.startswith(("tests/", "scripts/", "eval/", "packaging/"))]


def test_only_whoami_asks_the_os_who_is_running():
    """The resolver cannot grow a second copy. Found by review: jobs.py,
    claim.py and lock.py each carried a private one that ignored JLBC_USER."""
    offenders = [
        p for p in _shipped_python()
        if p != ROOT / "users" / "whoami.py" and "getpass.getuser(" in p.read_text(encoding="utf-8")
    ]
    assert offenders == [], f"call users.whoami.current_user() instead: {offenders}"


def test_only_two_places_fold_a_username():
    """U0 is one rule. harness/settings.py gets its own three-line copy
    because Invariant 7 forbids it importing users/ — and the copy is pinned
    to be the SAME expression, so the two cannot drift."""
    allowed = {ROOT / "users" / "whoami.py", ROOT / "harness" / "settings.py"}
    offenders = [
        p for p in _shipped_python()
        if p not in allowed and ".casefold(" in p.read_text(encoding="utf-8")
    ]
    assert offenders == [], f"use users.whoami.same_person()/fold(): {offenders}"
    settings_src = (ROOT / "harness" / "settings.py").read_text(encoding="utf-8")
    assert "return user.strip().casefold()" in settings_src
