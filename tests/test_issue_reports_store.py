"""One JSON file per report, the jobs/ pattern (spec E3): the directory is
the index, a corrupt file costs one visible row, never the list."""
import json

import pytest

import app.issue_reports as ir


@pytest.fixture(autouse=True)
def _reports_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(ir, "reports_dir", lambda: tmp_path / "issue-reports")


def test_create_and_list_newest_first():
    a = ir.create_report(submitted_by="asmith", description="search is empty")
    b = ir.create_report(submitted_by="bjones", description="pdf will not open")
    listed = ir.list_reports()
    assert [r["id"] for r in listed] == [b["id"], a["id"]]
    assert listed[0]["status"] == "unresolved"
    assert listed[0]["version"] == 1


def test_update_resolves_and_stamps():
    r = ir.create_report(submitted_by="asmith", description="x")
    out = ir.update_report(r["id"], status="resolved", admin_note="fixed", actor="destin")
    assert out["status"] == "resolved"
    assert out["resolved_by"] == "destin" and out["resolved_at"]
    assert ir.load_report(r["id"])["admin_note"] == "fixed"


def test_reopen_clears_the_resolution_stamp():
    r = ir.create_report(submitted_by="a", description="x")
    ir.update_report(r["id"], status="resolved", actor="destin")
    out = ir.update_report(r["id"], status="unresolved", actor="destin")
    assert out["resolved_by"] is None and out["resolved_at"] is None


def test_corrupt_file_is_a_visible_row_not_a_blank_list():
    ir.create_report(submitted_by="a", description="fine")
    bad = ir.reports_dir() / "9999-deadbeef.json"
    bad.write_text("{torn", encoding="utf-8")
    listed = ir.list_reports()
    assert any(r.get("unreadable") for r in listed)
    assert any(r.get("description") == "fine" for r in listed)


def test_missing_directory_is_genuinely_empty():
    # Nobody has filed anything yet: an empty list is the TRUE answer here,
    # and it must not be confused with the unreachable case below. The
    # `_reports_dir` fixture points reports_dir() at `tmp_path /
    # "issue-reports"` — tmp_path (the ROOT) exists, only the
    # issue-reports/ subfolder is missing, which is exactly the "genuinely
    # empty" half of the IMPORTANT 2 discrimination.
    assert ir.list_reports() == []


def test_a_vanished_share_is_reported_unreachable_not_empty(monkeypatch, tmp_path, capsys):
    # IMPORTANT 2 (review): store/config.py's `data_dir()` swallows a
    # failed mkdir on an unreachable share and returns the path anyway, so
    # os.listdir(<gone share>/issue-reports) raises the SAME
    # FileNotFoundError as "nobody has filed a report yet" — both screens
    # then confidently said "no reports". Simulate the vanished share: the
    # ROOT ("gone-share") itself was never created, unlike the fixture
    # above where only issue-reports/ is missing.
    monkeypatch.setattr(ir, "reports_dir", lambda: tmp_path / "gone-share" / "issue-reports")
    with pytest.raises(ir.ReportsUnavailable):
        ir.list_reports()
    assert "cannot read" in capsys.readouterr().err


def test_an_unreadable_directory_raises_instead_of_looking_empty(capsys):
    # THE DEFECT THIS GUARDS: an unreadable share used to return [], and the
    # screens then printed "No reports yet" / "You haven't filed a report
    # yet" — a confident claim about a folder nobody could read.
    import os

    directory = ir.reports_dir()
    directory.mkdir(parents=True)
    os.chmod(directory, 0)
    try:
        with pytest.raises(ir.ReportsUnavailable):
            ir.list_reports()
    finally:
        os.chmod(directory, 0o755)
    assert "cannot read" in capsys.readouterr().err


def test_update_unknown_id_returns_none():
    assert ir.update_report("nope", status="resolved", actor="d") is None


def test_transcript_is_embedded_verbatim():
    t = {"id": "c1", "title": "chat", "messages": [{"role": "user", "content": "hi"}]}
    r = ir.create_report(submitted_by="a", description="x", transcript=t)
    assert ir.load_report(r["id"])["transcript"] == t
