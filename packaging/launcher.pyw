"""JLBC Search launcher (Plan 5, Task 16 — spec S8).

Run by a Start-Menu or Desktop shortcut as `python\\pythonw.exe launcher.pyw`.
`.pyw` + `pythonw.exe` means no console window ever appears.

Behaviour, in order:
  1. If running.json names a port that answers /health with OUR body, open a
     window at it and exit — whatever port that is, so a server that had to
     fall back is reused too. If that record is FRESH (started under 180 s
     ago) and its pid is alive, wait for it: that is a second click during a
     slow start, not a second server. A stale record is ignored — Windows
     recycles pids, so an old one can name a stranger.
  2. Otherwise take port 9300 if it is free. The BIND is the single-instance
     lock; a stranger holding 9300 costs one fallback port and nothing else.
  3. Start uvicorn *in this process* and record the port and pid.
  4. Wait up to 180 s for /health. On timeout, show a message box saying it
     is still starting and naming the log file; if the server CRASHED, say so
     instead and name the same file — never a traceback (nobody here can read
     one), and never "try again" for a fault that will just repeat.
  5. Open the UI as an ordinary browser tab: Chrome, else Edge, else whatever
     the default browser is. Deliberately NOT Chrome's --app mode — see
     open_window() for why that was reversed.
  6. Keep serving. Closing the browser window does not stop the server; that
     is deliberate (S8) and is what makes relaunch instant.

WHY plain Python and not a compiled .exe: a .exe needs a build toolchain
nobody at JLBC will have. This file is readable, editable, and debuggable by
the next person with nothing but Notepad.
"""
from __future__ import annotations

import ctypes
import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

INSTALL_DIR = Path(__file__).resolve().parent
APP_NAME = "JLBC Search"

# Per-machine state: the recorded port, the logs and MinerU's config. Kept out
# of the install directory so a reinstall (delete the program folder, unzip the
# new one) does not destroy the machine's own configuration.
STATE_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "JLBC-Search"
RUNNING_FILE = STATE_DIR / "running.json"
LOG_DIR = STATE_DIR / "logs"
MINERU_CONFIG = STATE_DIR / "mineru.json"

# Try this first (every document names it; bookmarks and restored tabs keep
# working across restarts). The BIND is the single-instance lock: if 9300 is
# held, the other holder is either us (poll it) or a stranger (fall back).
PREFERRED_PORT = 9300
# 180 s, not 60: a cold laptop imports ~36k files under Defender, then opens
# LanceDB over the share. At 60 s the box said "failed" while the non-daemon
# server thread finished starting a minute later — with no browser window.
HEALTH_TIMEOUT_S = 180


# ---------------------------------------------------------------------------
# Environment — this is what makes first run download nothing (S7)
# ---------------------------------------------------------------------------
def prepare_environment() -> None:
    """Point every library at the weights we shipped, and at nothing remote.

    Each of these was verified against the shipped source; see
    docs/superpowers/investigations/2026-08-01-bundle-size.md. Getting any of
    them wrong produces a bundle that works on a connected machine and fails,
    or silently degrades, on the offline one it was built for.
    """
    models = INSTALL_DIR / "models"

    # fastembed defaults its cache to %TEMP%, which Windows Storage Sense
    # eventually deletes — the models would vanish weeks after install.
    os.environ["FASTEMBED_CACHE_PATH"] = str(models / "fastembed")

    # Without this, fastembed calls model_info() and list_repo_tree() against
    # huggingface.co on EVERY model construction, even with a complete cache.
    # It is what turns a populated cache into an actually-offline start.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

    # MinerU: read weights from the bundle, never fetch.
    #
    # Written HERE, every start, from the real install dir — the installer's
    # rewrite step was silent (2>nul) and a moved folder stranded MinerU on a
    # stale absolute path. Lives in STATE_DIR so program files stay read-only.
    write_mineru_config(INSTALL_DIR, MINERU_CONFIG)
    os.environ["MINERU_MODEL_SOURCE"] = "local"
    os.environ["MINERU_TOOLS_CONFIG_JSON"] = str(MINERU_CONFIG)

    # tiktoken downloads cl100k_base on first use and FAILS SOFT to a
    # different chunk boundary if it cannot. The cache is pre-seeded.
    os.environ["TIKTOKEN_CACHE_DIR"] = str(models / "tiktoken")

    # opendataloader-pdf shells out to bare `java` (runner.py:24). Prepending
    # our own JRE means the office machines need no Java installed and nothing
    # already on the machine is affected.
    jre_bin = INSTALL_DIR / "jre" / "bin"
    if jre_bin.exists():
        os.environ["PATH"] = str(jre_bin) + os.pathsep + os.environ.get("PATH", "")
        os.environ.setdefault("JAVA_HOME", str(INSTALL_DIR / "jre"))

    # The app resolves its own source relative to this directory.
    if str(INSTALL_DIR) not in sys.path:
        sys.path.insert(0, str(INSTALL_DIR))
    sys.path.insert(0, str(INSTALL_DIR / "site-packages"))


def write_mineru_config(install_dir: Path, target: Path) -> None:
    # tmp + os.replace, exactly like record_port below. This file is shared
    # state: a MinerU child process reads it, and a plain write_text is
    # briefly a truncated file on disk. Rewriting it on EVERY start means
    # that window comes round every launch, so it has to be atomic.
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({
        "models-dir": {"pipeline": str(install_dir / "models" / "mineru"), "vlm": ""},
        "model-source": "local",
        "config_version": "1.3.2",
    }, indent=2)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, target)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def message_box(text: str, title: str = APP_NAME) -> None:
    """A dialog, not a traceback. 0x10 = MB_ICONERROR."""
    try:
        ctypes.windll.user32.MessageBoxW(None, text, title, 0x10)
    except Exception:
        # Not Windows (or no user32) — the launcher is Windows-only, but a
        # developer running it on Linux should still see the message.
        print(f"{title}: {text}", file=sys.stderr)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def try_bind(port: int) -> socket.socket | None:
    """A bound-but-not-listening socket on `port`, or None if it is held."""
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", port))
        return s
    except OSError:
        s.close()
        return None


def health_json(port: int, timeout: float = 1.5) -> dict | None:
    """/health's body if it is OURS ({"ok": true, ...}), else None."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=timeout) as r:
            if r.status != 200:
                return None
            body = json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None
    # `ok` alone is too common a shape; `provider` is ours (app/main.py /health).
    return body if isinstance(body, dict) and body.get("ok") is True and "provider" in body else None


def _pid_alive(pid: int) -> bool:
    """Is a process with this pid running? Windows: OpenProcess; else kill(0)."""
    if os.name == "nt":
        SYNCHRONIZE = 0x00100000
        h = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if not h:
            return False
        ctypes.windll.kernel32.CloseHandle(h)
        return True
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        # The process exists and belongs to another user — alive, not dead.
        # Reporting it dead would start a second server beside a live one.
        return True
    except OSError:
        return False


def recorded() -> dict | None:
    """{"port", "pid", "started_at"} from running.json, or None. A missing or
    corrupt file means 'no server', not a crash."""
    try:
        d = json.loads(RUNNING_FILE.read_text(encoding="utf-8"))
        return {"port": int(d["port"]), "pid": int(d["pid"]),
                "started_at": d.get("started_at")}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _sibling_worth_waiting_for(rec: dict) -> bool:
    """Is the recorded server plausibly still STARTING, so a second click
    should wait for it rather than start its own?

    WHY the age bound, and why `_pid_alive` alone is not enough: an unclean
    shutdown (a kill, a crash, a power cut) leaves running.json on disk with
    a pid nobody owns any more, and Windows RECYCLES pids — so the next click
    can find that pid alive, belonging to a total stranger, and poll it for
    the full three minutes with no window and no message. `started_at` is
    what separates the two: a server that has not answered /health within
    HEALTH_TIMEOUT_S of its own recorded start is not "still starting" by
    this launcher's own definition, so the record is stale whoever holds
    that pid now. A record with no stamp is pre-2026-08-25 and unjudgeable —
    treat it as stale; the cost is one extra server on a fallback port, and
    the cost of the other mistake is a three-minute silent hang.
    """
    started = rec.get("started_at")
    if not isinstance(started, str):
        return False
    try:
        age = (datetime.now() - datetime.fromisoformat(started)).total_seconds()
    except ValueError:
        return False
    return age < HEALTH_TIMEOUT_S


def record_port(port: int) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = RUNNING_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"port": port, "pid": os.getpid(),
                               "started_at": datetime.now().isoformat()}))
    os.replace(tmp, RUNNING_FILE)


def log_path_for_today() -> Path:
    """The log file this run writes to. One per day, appended."""
    return LOG_DIR / f"server-{datetime.now():%Y-%m-%d}.log"


# Set the moment stdout/stderr are redirected. NOT `log_path.exists()`: the
# log is one file per DAY, so a successful run at 9am makes that file exist
# for every later failure, and the exception line — the only detail a crash
# BEFORE redirection ever produces — would be suppressed exactly when it is
# the only evidence there is.
_LOGGED = False


# ---------------------------------------------------------------------------
# Opening the window
# ---------------------------------------------------------------------------
def _chrome_candidates() -> list[Path]:
    """JLBC machines vary; probe the three places Chrome and Edge actually land."""
    roots = [
        os.environ.get("PROGRAMFILES", r"C:\Program Files"),
        os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
        os.environ.get("LOCALAPPDATA", ""),
    ]
    rel = [
        r"Google\Chrome\Application\chrome.exe",
        r"Microsoft\Edge\Application\msedge.exe",
    ]
    out = []
    for root in roots:
        if not root:
            continue
        for r in rel:
            out.append(Path(root) / r)
    return out


def open_window(port: int) -> None:
    url = f"http://127.0.0.1:{port}"
    import subprocess

    for exe in _chrome_candidates():
        if exe.exists():
            try:
                # A NORMAL browser tab, deliberately — not Chrome's `--app` mode.
                #
                # S8 originally specified `--app=`, which strips the address bar
                # and tabs so the thing feels like a native application. Rejected
                # after the first real Windows run (2026-08-01): this is a
                # research tool used *alongside* a dozen other tabs, and app mode
                # makes it an island you have to alt-tab to. Passing the URL bare
                # also means a second launch lands as a tab in the Chrome window
                # the analyst already has open, next to their other work, instead
                # of spawning a separate window.
                subprocess.Popen([str(exe), url])
                return
            except OSError:
                continue
    try:
        os.startfile(url)  # type: ignore[attr-defined]  # Windows-only
    except Exception:
        import webbrowser
        webbrowser.open(url)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    try:
        return _main()
    except Exception as exc:  # noqa: BLE001 — a launcher must never die silently
        # §2.5: name the file, not the traceback. The exception text is added
        # ONLY when nothing was ever logged — if the log exists it already has
        # the detail, and a Python type name in a dialog is noise to a reader
        # who cannot act on it.
        log_path = log_path_for_today()
        text = (f"{APP_NAME} could not start.\n\n"
                f"Send this file to support:\n{log_path}")
        if not _LOGGED:
            text += f"\n\n{type(exc).__name__}: {exc}"
        message_box(text)
        return 1


def _main() -> int:
    global _LOGGED
    prepare_environment()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = log_path_for_today()

    # 1. Reuse a running instance before doing anything expensive (S8) —
    #    on WHATEVER port it recorded, so a fallback-port server is reused too.
    rec = recorded()
    if rec is not None:
        port, pid = rec["port"], rec["pid"]
        if health_json(port) is not None:
            open_window(port)
            return 0
        if _sibling_worth_waiting_for(rec) and _pid_alive(pid):
            # Our own sibling is mid-start (a second click). Wait for IT —
            # never for a stranger: a foreign process on the port has a
            # different pid, or no running.json at all.
            deadline = time.monotonic() + HEALTH_TIMEOUT_S
            while time.monotonic() < deadline and _pid_alive(pid):
                if health_json(port) is not None:
                    open_window(port)
                    return 0
                time.sleep(0.5)

    try:
        import uvicorn
        from app.main import create_app
    except Exception as exc:  # noqa: BLE001 — the user gets a sentence, the log gets the detail
        # Append: this is one file per DAY, and truncating it would destroy
        # the record of an earlier run on the same day.
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat()} startup import failed\n{exc!r}\n")
        message_box(
            f"{APP_NAME} could not start.\n\n"
            f"Send this file to support:\n{log_path}"
        )
        return 1

    # 2. Bind 9300 if free; a stranger holding it costs one free_port() call.
    sock = try_bind(PREFERRED_PORT)
    if sock is None:
        port = free_port()
        print(f"port {PREFERRED_PORT} is held by another program; using {port}",
              file=sys.stderr)
    else:
        sock.close()  # uvicorn re-binds it a few ms later
        port = PREFERRED_PORT
    record_port(port)

    # Log to a file: pythonw.exe has no console, so anything written to stdout
    # would go nowhere and the timeout message box would have nothing to name.
    log_file = open(log_path, "a", encoding="utf-8", buffering=1)
    sys.stdout = log_file
    sys.stderr = log_file
    _LOGGED = True
    print(f"\n=== {datetime.now().isoformat()} starting on port {port} ===")

    server_error: list[BaseException] = []

    def serve() -> None:
        try:
            uvicorn.run(create_app, factory=True, host="127.0.0.1", port=port,
                        log_level="info", access_log=False)
        except BaseException as exc:  # noqa: BLE001 — recorded, then surfaced as a sentence
            server_error.append(exc)
            import traceback
            traceback.print_exc()

    # The server runs on a non-daemon thread so the process outlives the
    # browser window (S8). The main thread only waits for health, opens the
    # window, and then parks.
    t = threading.Thread(target=serve, name="uvicorn", daemon=False)
    t.start()

    deadline = time.monotonic() + HEALTH_TIMEOUT_S
    while time.monotonic() < deadline:
        if server_error:
            # A crash is not slowness. The timeout box says "wait a minute,
            # then click the icon again" — for a crash that repeats the same
            # crash forever and never tells anyone to send the log. serve()
            # has already written the traceback to log_path.
            message_box(f"{APP_NAME} could not start.\n\n"
                        f"Send this file to support:\n{log_path}")
            return 1
        body = health_json(port)
        if body is not None:
            print(f"=== serving on {port}; search provider: {body.get('provider')} ===")
            open_window(port)
            t.join()
            return 0
        time.sleep(0.4)

    message_box(
        f"{APP_NAME} is still starting. Wait a minute, then click the icon again.\n\n"
        f"If it still won't open, send this file to support:\n{log_path}"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
