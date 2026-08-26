"""The Windows Browse-for-Folder dialog, driven from the server (spec §2.5).

A web page cannot learn a folder's real address; the server runs on the same
PC and can. Everything here is faked — the suite must never open a dialog."""
from __future__ import annotations

import os
import subprocess

import pytest

from app import folder_picker


def test_unsupported_off_windows(monkeypatch):
    monkeypatch.setattr(os, "name", "posix")
    assert folder_picker.supported() is False


def test_supported_on_windows(monkeypatch):
    monkeypatch.setattr(os, "name", "nt")
    assert folder_picker.supported() is True


def _fake_run(stdout: str, returncode: int = 0):
    def run(cmd, **kw):
        assert cmd[0] == "powershell" and "-STA" in cmd
        assert kw.get("encoding") == "utf-8"
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr="")
    return run


def test_pick_returns_the_chosen_path(monkeypatch):
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(subprocess, "run", _fake_run("\\\\bcpool\\JLBCSearch\r\n"))
    assert folder_picker.pick_folder() == "\\\\bcpool\\JLBCSearch"


def test_cancel_returns_none(monkeypatch):
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(subprocess, "run", _fake_run(""))
    assert folder_picker.pick_folder() is None


def test_a_second_dialog_is_refused_while_one_is_open(monkeypatch):
    import threading

    monkeypatch.setattr(os, "name", "nt")
    started, release = threading.Event(), threading.Event()

    def slow(cmd, **kw):
        started.set()
        release.wait(5)
        return subprocess.CompletedProcess(cmd, 0, stdout="C:\\x", stderr="")

    monkeypatch.setattr(subprocess, "run", slow)
    t = threading.Thread(target=folder_picker.pick_folder)
    t.start()
    started.wait(5)
    with pytest.raises(folder_picker.PickerBusy):
        folder_picker.pick_folder()
    release.set()
    t.join(5)


def test_pick_off_windows_returns_none_without_running_anything(monkeypatch):
    monkeypatch.setattr(os, "name", "posix")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("ran")))
    assert folder_picker.pick_folder() is None
