import json

import pytest

from store.report_formats import (
    EditionFormats,
    format_key,
    load,
    load_overlay,
    names_its_year,
    reset_cache,
    save_edition,
)


@pytest.fixture(autouse=True)
def _clean():
    reset_cache()
    yield
    reset_cache()


def _write(path, editions):
    path.write_text(json.dumps({"version": 1, "editions": editions}), encoding="utf-8")


def test_the_overlay_replaces_a_shipped_edition_wholesale(tmp_path):
    shipped = tmp_path / "shipped.json"
    overlay = tmp_path / "overlay.json"
    _write(shipped, {"Baseline:2027": {"single_file": "https://x/a.pdf", "linked_toc": "https://x/b.pdf"}})
    _write(overlay, {"Baseline:2027": {"single_file": "https://y/c.pdf", "linked_toc": None}})
    table, problems = load(shipped, overlay)
    assert table["Baseline:2027"] == EditionFormats("https://y/c.pdf", None)
    assert problems == []


def test_a_torn_overlay_row_costs_itself_not_the_file(tmp_path):
    shipped = tmp_path / "shipped.json"
    overlay = tmp_path / "overlay.json"
    _write(shipped, {"Baseline:2027": {"single_file": "https://x/a.pdf", "linked_toc": None}})
    _write(overlay, {
        "Nonsense Family:2027": {"single_file": "https://y/c.pdf", "linked_toc": None},
        "Baseline:2026": {"single_file": "https://y/d.pdf", "linked_toc": None},
    })
    table, problems = load(shipped, overlay)
    assert "Baseline:2026" in table          # the good row survived
    assert "Baseline:2027" in table          # the shipped table survived
    assert "Nonsense Family:2027" not in table
    assert len(problems) == 1 and "Nonsense Family:2027" in problems[0]


def test_the_reason_a_row_was_dropped_survives_a_second_load(tmp_path):
    # The second load is the one that comes off the mtime cache. A first version
    # cached only the rows, so the admin saw the explanation once and never
    # again while the row went on being dropped -- a warning that disappears is
    # worse than no warning, because the page then looks healthy.
    shipped = tmp_path / "shipped.json"
    overlay = tmp_path / "overlay.json"
    _write(shipped, {"Baseline:2027": {"single_file": "https://x/a.pdf", "linked_toc": None}})
    _write(overlay, {"Nonsense Family:2027": {"single_file": "https://y/c.pdf", "linked_toc": None}})
    assert load(shipped, overlay)[1] == load(shipped, overlay)[1] != []


def test_unreadable_overlay_json_leaves_the_shipped_table_serving(tmp_path):
    shipped = tmp_path / "shipped.json"
    overlay = tmp_path / "overlay.json"
    _write(shipped, {"Baseline:2027": {"single_file": "https://x/a.pdf", "linked_toc": None}})
    overlay.write_text("{ this is not json", encoding="utf-8")
    table, problems = load(shipped, overlay)
    assert table["Baseline:2027"].single_file == "https://x/a.pdf"
    assert problems and "could not be read" in problems[0]


def test_a_missing_overlay_is_silent(tmp_path):
    shipped = tmp_path / "shipped.json"
    _write(shipped, {"Baseline:2027": {"single_file": "https://x/a.pdf", "linked_toc": None}})
    table, problems = load(shipped, tmp_path / "absent.json")
    assert list(table) == ["Baseline:2027"]
    assert problems == []


def test_save_then_load_round_trips(tmp_path):
    overlay = tmp_path / "overlay.json"
    save_edition("Appropriations Report", 2028, "https://x/28.pdf", None, path=overlay)
    table, problems = load_overlay(overlay)
    assert table[format_key("Appropriations Report", 2028)] == EditionFormats("https://x/28.pdf", None)
    assert problems == []


def test_saving_an_edition_with_neither_format_is_refused(tmp_path):
    # Both-null is indistinguishable from having no entry, so the edition would
    # re-appear as unanswered forever and the admin could never settle it.
    #
    # (?i) because the message is written for the ADMIN'S SCREEN and therefore
    # starts with a capital; `pytest.raises(match=...)` is `re.search`, which is
    # case-sensitive. Asserting the lowercase form without the flag passes only
    # if the sentence is reworded into something that reads badly on the page.
    with pytest.raises(ValueError, match="(?i)at least one"):
        save_edition("Baseline", 2028, None, None, path=tmp_path / "overlay.json")


def test_saving_an_unknown_family_is_refused(tmp_path):
    with pytest.raises(ValueError, match="Unknown report family"):
        save_edition("Baselines", 2028, "https://x/a.pdf", None, path=tmp_path / "overlay.json")


def test_a_failed_save_raises_rather_than_degrading(tmp_path):
    # The read paths degrade on purpose; this one must not. An admin who
    # presses Approve and is told nothing has no way to learn it did not stick.
    unwritable = tmp_path / "nope"
    unwritable.write_text("i am a file, not a directory", encoding="utf-8")
    with pytest.raises(OSError):
        save_edition("Baseline", 2028, "https://x/a.pdf", None, path=unwritable / "overlay.json")


def test_saving_preserves_other_editions_already_in_the_overlay(tmp_path):
    overlay = tmp_path / "overlay.json"
    save_edition("Baseline", 2028, "https://x/28b.pdf", None, path=overlay)
    save_edition("Appropriations Report", 2028, "https://x/28a.pdf", None, path=overlay)
    table, _ = load_overlay(overlay)
    assert len(table) == 2


def test_a_corrupt_overlay_is_replaced_rather_than_blocking_every_future_save(tmp_path):
    overlay = tmp_path / "overlay.json"
    overlay.write_text("{ torn", encoding="utf-8")
    save_edition("Baseline", 2028, "https://x/a.pdf", None, path=overlay)
    table, _ = load_overlay(overlay)
    assert list(table) == ["Baseline:2028"]


@pytest.mark.parametrize(
    "url,year,expected",
    [
        ("https://www.azjlbc.gov/19AR/FY2019AppropRpt.pdf", 2019, True),
        ("https://www.azjlbc.gov/26baseline/26baselinesinglefile.pdf", 2026, True),
        ("https://www.azjlbc.gov/12book1/12BaselineSingleFile.pdf", 2012, True),
        ("https://www.azjlbc.gov/05app/apprpttoc.pdf", 2005, True),
        ("https://www.azjlbc.gov/budget/24baselinelinks.pdf", 2024, True),
        # The rolling directory: a live 200 that names no year at all. This is
        # the case the whole guard exists for.
        ("https://www.azjlbc.gov/budget/apprpttoc.pdf", 2028, False),
        # The realistic copy-paste slip: last year's report under this year's key.
        ("https://www.azjlbc.gov/19AR/FY2019AppropRpt.pdf", 2018, False),
        # 🔴 THE CASE A SUBSTRING TEST GETS WRONG, and the reason this function
        # compares whole digit runs. "20" sits inside "fy2019", so a substring
        # test answers True here and the FY2020 key accepts sixteen other
        # editions' reports. Measured on the real table 2026-08-16: 32 wrong
        # pairs accepted, all of them on :2020. Delete this row and the hole
        # comes back invisibly.
        ("https://www.azjlbc.gov/19AR/FY2019AppropRpt.pdf", 2020, False),
        ("https://www.azjlbc.gov/26ar/fy2026approprpt.pdf", 2020, False),
        # Same hole one digit along: "01" sits inside "2019".
        ("https://www.azjlbc.gov/19AR/FY2019AppropRpt.pdf", 2001, False),
    ],
)
def test_names_its_year(url, year, expected):
    assert names_its_year(url, year) is expected
