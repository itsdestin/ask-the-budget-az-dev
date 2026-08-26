"""Windows/SMB refuse to replace or delete a file another handle has open.
One helper, two callers' worth of retries (2026-08-25)."""
from __future__ import annotations

import os

import pytest

from store.fs import replace_with_retry, unlink_with_retry


def test_replace_retries_a_sharing_violation(tmp_path, monkeypatch):
    tmp, target = tmp_path / "a.tmp", tmp_path / "a.json"
    tmp.write_text("new", encoding="utf-8")
    target.write_text("old", encoding="utf-8")
    real = os.replace
    left = {"n": 2}

    def flaky(src, dst):
        if left["n"]:
            left["n"] -= 1
            raise PermissionError(5, "sharing violation")
        real(src, dst)

    monkeypatch.setattr(os, "replace", flaky)
    replace_with_retry(tmp, target, budget_s=1.0)
    assert target.read_text(encoding="utf-8") == "new"
    assert not tmp.exists()


def test_replace_gives_up_and_cleans_the_tmp(tmp_path, monkeypatch):
    tmp, target = tmp_path / "a.tmp", tmp_path / "a.json"
    tmp.write_text("new", encoding="utf-8")
    monkeypatch.setattr(os, "replace", lambda s, d: (_ for _ in ()).throw(PermissionError(5, "x")))
    with pytest.raises(PermissionError):
        replace_with_retry(tmp, target, budget_s=0.05)
    assert not tmp.exists()


def test_replace_does_not_retry_a_real_error(tmp_path, monkeypatch):
    tmp, target = tmp_path / "a.tmp", tmp_path / "a.json"
    tmp.write_text("new", encoding="utf-8")
    calls = []

    def boom(s, d):
        calls.append(1)
        raise FileNotFoundError(2, "gone")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(FileNotFoundError):
        replace_with_retry(tmp, target, budget_s=1.0)
    assert len(calls) == 1


def test_unlink_retries_then_reports(tmp_path, monkeypatch):
    p = tmp_path / "x"
    p.write_text("", encoding="utf-8")
    real = os.unlink
    left = {"n": 1}

    def flaky(path, *a, **k):
        if left["n"]:
            left["n"] -= 1
            raise PermissionError(32, "in use")
        real(path)

    monkeypatch.setattr(os, "unlink", flaky)
    assert unlink_with_retry(p, budget_s=1.0) is True
    assert not p.exists()
