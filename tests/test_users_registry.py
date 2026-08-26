"""One JSON file per person under <data_dir>/users/ (spec U1–U7).

Two properties carry the design and both are pinned below: a file is
written only by its own user's machine (nothing here takes another
person's username and writes it — there is no hide function), and a
second touch on the same day writes NOTHING (verified by mtime, because a
rewrite that changes no bytes is still a write on an SMB share).
"""
from __future__ import annotations

import json
import os
import stat
from datetime import datetime, timedelta

import pytest

from harness import ledger
from users import registry


@pytest.fixture(autouse=True)
def share(tmp_path, monkeypatch):
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    registry.reset_roster_cache()
    yield tmp_path
    registry.reset_roster_cache()


def _file(username: str):
    return registry.users_dir() / f"{registry.roster_key(username)}.json"


def test_first_touch_creates_the_row_with_the_windows_name():
    assert registry.touch("dmoss", windows_name="Danielle Moss") is True
    p = registry.read_person("dmoss")
    assert p is not None
    assert (p.username, p.display_name, p.name_source) == ("dmoss", "Danielle Moss", "windows")
    assert p.first_seen == p.last_seen
    raw = json.loads(_file("dmoss").read_text(encoding="utf-8"))
    assert raw["version"] == 1


def test_a_second_touch_the_same_day_writes_nothing():
    registry.touch("dmoss", windows_name="Danielle Moss")
    path = _file("dmoss")
    os.utime(path, (1_000_000, 1_000_000))
    assert registry.touch("dmoss", windows_name="Danielle Moss") is False
    assert path.stat().st_mtime == 1_000_000


def test_a_touch_on_a_new_day_updates_last_seen_only(monkeypatch):
    registry.touch("dmoss", windows_name="Danielle Moss")
    first = registry.read_person("dmoss")
    tomorrow = datetime.now(registry.ARIZONA_TZ) + timedelta(days=1)
    monkeypatch.setattr(registry, "_now", lambda: tomorrow)
    assert registry.touch("dmoss", windows_name="Danielle Moss") is True
    p = registry.read_person("dmoss")
    assert p.first_seen == first.first_seen
    assert p.last_seen[:10] == tomorrow.date().isoformat()


def test_the_day_bucket_is_arizona_local_like_the_ledger():
    # Anti-drift: the ledger shards on a fixed UTC-7; a roster that bucketed
    # on the host clock would write twice on the first UTC-hours of a day.
    assert registry.ARIZONA_TZ == ledger.ARIZONA_TZ


def test_a_changed_spelling_is_recorded_under_the_same_file():
    registry.touch("dmoss")
    assert registry.touch("DMOSS") is True
    assert registry.read_person("dmoss").username == "DMOSS"
    assert len(list(registry.users_dir().iterdir())) == 1


def test_a_typed_name_is_never_overwritten_by_windows(monkeypatch):
    registry.touch("dmoss", windows_name="JARRETTD")
    registry.set_typed_name("dmoss", "Danielle Moss")
    tomorrow = datetime.now(registry.ARIZONA_TZ) + timedelta(days=1)
    monkeypatch.setattr(registry, "_now", lambda: tomorrow)  # force a next-day touch
    assert registry.touch("dmoss", windows_name="JARRETTD") is True  # last_seen moved…
    p = registry.read_person("dmoss")  # …but the typed name did not
    assert (p.display_name, p.name_source) == ("Danielle Moss", "typed")


def test_a_blank_windows_read_does_not_erase_a_name(monkeypatch):
    registry.touch("dmoss", windows_name="Danielle Moss")
    tomorrow = datetime.now(registry.ARIZONA_TZ) + timedelta(days=1)
    monkeypatch.setattr(registry, "_now", lambda: tomorrow)
    registry.touch("dmoss", windows_name="")
    assert registry.read_person("dmoss").display_name == "Danielle Moss"


def test_a_local_typed_name_migrates_up_on_first_touch():
    registry.touch("dmoss", windows_name="JARRETTD", local_typed_name="Danielle Moss")
    p = registry.read_person("dmoss")
    assert (p.display_name, p.name_source) == ("Danielle Moss", "typed")


def test_clearing_a_typed_name_falls_back_to_windows_next_touch(monkeypatch):
    registry.touch("dmoss", windows_name="Danielle Moss")
    registry.set_typed_name("dmoss", "D. Moss")
    registry.set_typed_name("dmoss", "")
    p = registry.read_person("dmoss")
    assert p.name_source == ""
    tomorrow = datetime.now(registry.ARIZONA_TZ) + timedelta(days=1)
    monkeypatch.setattr(registry, "_now", lambda: tomorrow)
    registry.touch("dmoss", windows_name="Danielle Moss")
    assert registry.read_person("dmoss").name_source == "windows"


def test_typed_name_reads_only_a_typed_source():
    registry.touch("dmoss", windows_name="Danielle Moss")
    assert registry.typed_name("dmoss") == ""
    registry.set_typed_name("dmoss", "Danielle Moss")
    assert registry.typed_name("DMOSS") == "Danielle Moss"


def test_a_blank_username_is_never_written():
    assert registry.touch("") is False
    assert registry.touch("   ") is False
    assert not registry.users_dir().exists() or list(registry.users_dir().iterdir()) == []


def test_read_person_is_cached_on_the_file_stamp(monkeypatch):
    registry.touch("dmoss", windows_name="Danielle Moss")
    registry.read_person("dmoss")
    opened = []
    real = registry.Path.read_text
    monkeypatch.setattr(registry.Path, "read_text", lambda self, *a, **k: (opened.append(self), real(self, *a, **k))[1])
    registry.read_person("dmoss")
    assert opened == []  # same stamp → no read
    registry.set_typed_name("dmoss", "D. Moss")
    assert registry.read_person("dmoss").display_name == "D. Moss"  # new stamp → re-read


@pytest.mark.parametrize("body", ["null", "[]", "5", "{not json", ""])
def test_read_person_degrades_on_a_bad_file(body):
    registry.users_dir().mkdir(parents=True)
    _file("dmoss").write_text(body, encoding="utf-8")
    assert registry.read_person("dmoss") is None
    assert registry.typed_name("dmoss") == ""


def test_list_people_reports_torn_files_as_a_count_not_a_row():
    registry.touch("dmoss", windows_name="Danielle Moss")
    registry.touch("gpaulsen", windows_name="Geoff Paulsen")
    _file("bjw2").write_text("{torn", encoding="utf-8")
    people, unreadable = registry.list_people()
    assert sorted(p.username for p in people) == ["dmoss", "gpaulsen"]
    assert unreadable == 1


def test_list_people_is_empty_when_nobody_has_opened_the_app():
    assert registry.list_people() == ([], 0)


def test_list_people_raises_when_the_folder_cannot_be_read(share):
    d = registry.users_dir()
    d.mkdir(parents=True)
    d.chmod(0)
    try:
        with pytest.raises(registry.RosterUnavailable):
            registry.list_people()
    finally:
        d.chmod(stat.S_IRWXU)


def test_list_people_raises_when_the_share_itself_is_gone(share, monkeypatch):
    # data_dir() creates the root as a side effect, so the discriminator is
    # "root missing" — the way app/health.py and app/issue_reports.py do it.
    monkeypatch.setenv("JLBC_DATA_DIR", str(share / "vanished"))
    monkeypatch.setattr(registry, "users_dir", lambda: share / "vanished" / "users")
    with pytest.raises(registry.RosterUnavailable):
        registry.list_people()


def test_there_is_no_way_to_write_another_persons_file():
    # Structural (spec U1/U7): every writer takes the username it writes FOR.
    # There is no hide(), no unhide(), no write-by-key.
    assert not hasattr(registry, "hide")
    assert not hasattr(registry, "unhide")
    assert not hasattr(registry, "write_person")
