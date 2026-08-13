"""The office alias overlay file (spec E1/E5).

Same posture as settings.json: reads degrade, writes raise, a rewrite on
the share is picked up by the (path, mtime, size) stamp.
"""
import json

from store.office_aliases import (
    OfficeAlias,
    OfficeAliases,
    load_office_aliases,
    reset_office_aliases_cache,
    save_office_aliases,
)


def _sample() -> OfficeAliases:
    return OfficeAliases(
        added=(
            OfficeAlias("dor", "agency:rev", "destin", "2026-08-12T17:00:00Z"),
        ),
        disabled=frozenset({"colleges"}),
    )


def test_round_trip(tmp_path):
    path = tmp_path / "office-aliases.json"
    save_office_aliases(_sample(), path=path)
    reset_office_aliases_cache()
    loaded = load_office_aliases(path=path)
    assert loaded == _sample()


def test_missing_file_is_empty(tmp_path):
    reset_office_aliases_cache()
    loaded = load_office_aliases(path=tmp_path / "nope.json")
    assert loaded == OfficeAliases()


def test_corrupt_file_degrades_to_empty_and_says_why(tmp_path, capsys):
    path = tmp_path / "office-aliases.json"
    path.write_text("{not json", encoding="utf-8")
    reset_office_aliases_cache()
    assert load_office_aliases(path=path) == OfficeAliases()
    assert "office-aliases" in capsys.readouterr().err


def test_non_object_json_degrades_not_raises(tmp_path):
    # The chat-history review's defect 8, guarded here from day one: null,
    # [] and 5 all parse fine and then explode on .get. They are bad DATA.
    for junk in ("null", "[]", "5"):
        path = tmp_path / "office-aliases.json"
        path.write_text(junk, encoding="utf-8")
        reset_office_aliases_cache()
        assert load_office_aliases(path=path) == OfficeAliases()


def test_rewrite_on_disk_is_picked_up_without_reset(tmp_path):
    path = tmp_path / "office-aliases.json"
    save_office_aliases(OfficeAliases(), path=path)
    reset_office_aliases_cache()
    assert load_office_aliases(path=path) == OfficeAliases()
    # Another machine writes the file. Force a different mtime stamp.
    import os
    save_office_aliases(_sample(), path=path)
    os.utime(path, ns=(1, 1))
    os.utime(path)  # now() again — size changed, so the stamp differs anyway
    assert load_office_aliases(path=path) == _sample()


def test_added_by_agency_groups_and_lowercases():
    aliases = OfficeAliases(
        added=(
            OfficeAlias("DOR", "agency:rev", "", ""),
            OfficeAlias("rev-dept", "agency:rev", "", ""),
            OfficeAlias("ade", "agency:ade", "", ""),
        )
    )
    assert aliases.added_by_agency() == {
        "agency:rev": ("dor", "rev-dept"),
        "agency:ade": ("ade",),
    }
