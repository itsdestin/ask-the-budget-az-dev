"""packaging/launcher.pyw — the pure parts, executed the way test_diag_tool.py
used to (a .pyw is not importable by spec)."""
from __future__ import annotations

import json
import re
import socket
from datetime import datetime, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "packaging" / "launcher.pyw"


@pytest.fixture
def launcher(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "la"))
    ns: dict = {"__name__": "launcher_under_test", "__file__": str(SRC)}
    exec(compile(SRC.read_text(encoding="utf-8"), str(SRC), "exec"), ns)
    return ns


def test_state_dir_is_the_parent_of_a_program_subfolder(launcher, tmp_path):
    assert launcher["STATE_DIR"] == tmp_path / "la" / "JLBC-Search"


def test_mineru_config_is_written_to_state_from_the_install_dir(launcher, tmp_path):
    target = tmp_path / "mineru.json"
    launcher["write_mineru_config"](Path("C:/x/program"), target)
    cfg = json.loads(target.read_text(encoding="utf-8"))
    assert cfg["models-dir"]["pipeline"] == str(Path("C:/x/program") / "models" / "mineru")
    assert cfg["model-source"] == "local"


def test_the_preferred_port_is_9300_and_a_held_port_is_reported(launcher):
    assert launcher["PREFERRED_PORT"] == 9300
    holder = socket.socket()
    holder.bind(("127.0.0.1", 0))
    port = holder.getsockname()[1]
    try:
        assert launcher["try_bind"](port) is None
    finally:
        holder.close()
    s = launcher["try_bind"](0)
    assert s is not None
    s.close()


def test_health_json_rejects_a_foreign_service(launcher, monkeypatch):
    import urllib.request

    class R:
        status = 200

        def read(self):
            return b"<html>not us</html>"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: R())
    assert launcher["health_json"](1) is None


def test_health_json_rejects_a_foreign_ok_true(launcher, monkeypatch):
    """Another local app answering {"ok": true} must not be mistaken for us."""
    import urllib.request

    class R:
        status = 200

        def read(self):
            return b'{"ok": true}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: R())
    assert launcher["health_json"](1) is None


def test_timeout_is_three_minutes(launcher):
    assert launcher["HEALTH_TIMEOUT_S"] == 180


# ---------------------------------------------------------------------------
# Which recorded server is worth waiting three minutes for
# ---------------------------------------------------------------------------
def test_a_stale_running_json_is_not_waited_on(launcher):
    """An unclean shutdown leaves running.json behind, and Windows recycles
    pids — so a live pid is NOT evidence that our own server is starting.
    Only a fresh `started_at` is."""
    worth = launcher["_sibling_worth_waiting_for"]
    hour_old = (datetime.now() - timedelta(hours=1)).isoformat()
    assert worth({"port": 9300, "pid": 4321, "started_at": hour_old}) is False


def test_a_server_that_started_seconds_ago_is_waited_on(launcher):
    worth = launcher["_sibling_worth_waiting_for"]
    fresh = (datetime.now() - timedelta(seconds=5)).isoformat()
    assert worth({"port": 9300, "pid": 4321, "started_at": fresh}) is True


def test_the_wait_outlives_the_message_that_invites_the_second_click(launcher):
    """The timeout box says "wait a minute, then click the icon again", so the
    click it invites lands AFTER 180 s. At a one-timeout bound that click would
    call the record stale and start a second server onto the held port. 200 s
    must still be waited on; twice the timeout is where it stops."""
    worth = launcher["_sibling_worth_waiting_for"]
    timeout = launcher["HEALTH_TIMEOUT_S"]
    just_after = (datetime.now() - timedelta(seconds=200)).isoformat()
    assert worth({"port": 9300, "pid": 4321, "started_at": just_after}) is True
    at_the_bound = (datetime.now() - timedelta(seconds=2 * timeout)).isoformat()
    assert worth({"port": 9300, "pid": 4321, "started_at": at_the_bound}) is False


def test_a_record_stamped_in_the_future_is_not_waited_on(launcher):
    """A clock change (or a machine whose time syncs after boot) gives a
    negative age, which is under any upper bound — it would wait for ever."""
    worth = launcher["_sibling_worth_waiting_for"]
    ahead = (datetime.now() + timedelta(hours=1)).isoformat()
    assert worth({"port": 9300, "pid": 4321, "started_at": ahead}) is False


def test_a_record_with_no_or_unreadable_timestamp_is_not_waited_on(launcher):
    worth = launcher["_sibling_worth_waiting_for"]
    assert worth({"port": 9300, "pid": 4321}) is False
    assert worth({"port": 9300, "pid": 4321, "started_at": None}) is False
    assert worth({"port": 9300, "pid": 4321, "started_at": "not a date"}) is False


def test_recorded_carries_the_start_time(launcher):
    """`started_at` is what the wait decision reads; recorded() must pass it on."""
    running = launcher["RUNNING_FILE"]
    running.parent.mkdir(parents=True, exist_ok=True)
    running.write_text(json.dumps({"port": 9301, "pid": 42, "started_at": "2026-08-25T09:00:00"}))
    assert launcher["recorded"]() == {"port": 9301, "pid": 42,
                                      "started_at": "2026-08-25T09:00:00"}


# ---------------------------------------------------------------------------
# Spec 2.5 wording — final copy, pinned so a later edit fails a test
# ---------------------------------------------------------------------------
LAUNCHER_SRC = SRC.read_text(encoding="utf-8")
INSTALLER_SRC = (REPO / "packaging" / "Install-JLBC-Search.cmd").read_text(encoding="utf-8")


def _as_rendered(src: str) -> str:
    """The launcher's source with the two things that split a message box's
    sentence removed: the `\\n` escapes, and the quote/f-quote join between
    adjacent string literals. What is left is what the box shows."""
    return " ".join(re.sub(r'"\s*f?"', "", src.replace("\\n", " ")).split())


# Counts, not just presence: "could not start" is written at THREE sites in
# the launcher (the top-level catch, the import failure, the crashed server).
# A presence test passes while two of the three say something else, and the
# reader who meets one of those sites meets only one.
@pytest.mark.parametrize("sentence,count", [
    ("is still starting. Wait a minute, then click the icon again.", 1),
    ("could not start. Send this file to support:", 3),
])
def test_the_launcher_keeps_its_final_wording(sentence, count):
    rendered = _as_rendered(LAUNCHER_SRC)
    assert rendered.count(sentence) == count, f"2.5 wording changed: {sentence!r}"


def test_the_retry_delete_only_fires_on_our_own_bundle():
    """Section 1.4: a folder that is not recognisably ours is never deleted.

    `rmdir /s /q` recurses and deletes every UNLOCKED file before failing, so
    a half-deleted install has lost launcher.pyw, VERSION and python.exe and
    kept only the locked ones — python\\pythonw.exe above all, since the
    shortcut runs pythonw. The retry therefore cannot be gated on any of the
    files that are always already gone. Its two gates are `OURS` (this run did
    the delete) and the embeddable-CPython fingerprint (pythonw.exe with no
    `Lib\\`, which no normal Python install can look like). Both must sit
    above the retry, or a stranger's folder gets deleted or ours never heals.
    """
    lines = [ln.strip() for ln in INSTALLER_SRC.splitlines()]
    ours = "if defined OURS goto :folder_retry"
    fingerprint = (r'if exist "%INSTALL_DIR%\python\pythonw.exe" '
                   r'if not exist "%INSTALL_DIR%\python\Lib\" goto :folder_retry')
    retry = r'rmdir /s /q "%INSTALL_DIR%" 2>nul'
    assert 'set "OURS=1"' in lines, "the guarded delete stopped recording that it ran"
    assert ours in lines, "the retry lost its same-run gate"
    assert fingerprint in lines, "the retry lost its embeddable-CPython fingerprint"
    assert lines.index(ours) < lines.index(retry)
    assert lines.index(fingerprint) < lines.index(retry)


def test_the_locked_file_checks_read_pythonw_not_python():
    """python.exe is not the running image and is not locked — it is deleted
    by the failed rmdir like everything else unlocked. A check on it reports
    "clear" over a folder that still holds python312.dll, and tar then fails
    with the message about copying the zip to the Desktop that this whole
    block exists to prevent."""
    block = INSTALLER_SRC[INSTALLER_SRC.index("--- replace the program folder"):
                          INSTALLER_SRC.index("\n:folder_clear\n")]
    assert block.count(r'"%INSTALL_DIR%\python\pythonw.exe"') == 3
    assert r'"%INSTALL_DIR%\python\python.exe"' not in block


@pytest.mark.parametrize("sentence", [
    "The install didn't finish. Run this installer again.",
    "JLBC Search is still open. Close it, then run this installer again.",
    "Couldn't clear the old program folder:",
])
def test_the_installer_keeps_its_final_wording(sentence):
    assert sentence in INSTALLER_SRC, f"§2.5 wording changed: {sentence!r}"
