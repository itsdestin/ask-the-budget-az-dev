"""JLBC Insight launcher (Plan 5, Task 16 — spec S8).

Run by a Start-Menu or Desktop shortcut as `python\\pythonw.exe launcher.pyw`.
`.pyw` + `pythonw.exe` means no console window ever appears.

Behaviour, in order:
  1. If a server is already answering on the recorded port, just open a window
     at it and exit. Double-clicking the shortcut twice gives you two windows
     and one server (S8).
  2. Otherwise bind a free port, start uvicorn *in this process*, and record it.
  3. Wait for the server to answer /health. On timeout, show a message box
     naming the log file — never a traceback (nobody here can read one).
  4. Open the UI: Chrome in --app mode, else Edge in --app mode, else the
     default browser.
  5. Keep serving. Closing the browser window does not stop the server; that
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
APP_NAME = "JLBC Insight"

# Per-machine state: the recorded port and the logs. Kept out of the install
# directory so a reinstall (delete the folder, unzip the new one) does not
# destroy the machine's own configuration.
STATE_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "JLBC-Insight"
RUNNING_FILE = STATE_DIR / "running.json"
LOG_DIR = STATE_DIR / "logs"

HEALTH_TIMEOUT_S = 60


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
    os.environ["MINERU_MODEL_SOURCE"] = "local"
    os.environ["MINERU_TOOLS_CONFIG_JSON"] = str(models / "mineru.json")

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


def health_ok(port: int, timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=timeout) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def recorded_port() -> int | None:
    try:
        return int(json.loads(RUNNING_FILE.read_text())["port"])
    except (OSError, ValueError, KeyError, TypeError):
        # A missing or corrupt running.json means "no server", not a crash.
        return None


def record_port(port: int) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = RUNNING_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"port": port, "pid": os.getpid(),
                               "started_at": datetime.now().isoformat()}))
    os.replace(tmp, RUNNING_FILE)


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
                # --app strips the address bar and tabs: it looks like an
                # application window rather than a web page, which is the whole
                # point of S8's "native feel with zero Electron".
                subprocess.Popen([str(exe), f"--app={url}"])
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
    # Reuse a running instance before doing anything expensive (S8).
    existing = recorded_port()
    if existing and health_ok(existing):
        open_window(existing)
        return 0

    prepare_environment()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"server-{datetime.now():%Y-%m-%d}.log"

    try:
        import uvicorn
        from app.main import create_app
    except Exception as exc:  # noqa: BLE001 — the user gets a sentence, the log gets the detail
        log_path.write_text(f"{datetime.now().isoformat()} startup import failed\n{exc!r}\n")
        message_box(
            f"{APP_NAME} could not start.\n\n"
            f"Details were written to:\n{log_path}\n\n"
            f"Send that file to whoever supports this app."
        )
        return 1

    port = free_port()
    record_port(port)

    # Log to a file: pythonw.exe has no console, so anything written to stdout
    # would go nowhere and the timeout message box would have nothing to name.
    log_file = open(log_path, "a", encoding="utf-8", buffering=1)
    sys.stdout = log_file
    sys.stderr = log_file
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
            break
        if health_ok(port):
            open_window(port)
            t.join()
            return 0
        time.sleep(0.4)

    message_box(
        f"{APP_NAME} did not finish starting.\n\n"
        f"The log file is:\n{log_path}\n\n"
        f"Send that file to whoever supports this app."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
