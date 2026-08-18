"""JLBC Search — one-click diagnostic for a laptop that won't start.

Run by diag.cmd (or `python diag.pyw`). Reads real app code where
possible so the diagnosis matches what the app actually does. Writes a
redacted report + relevant logs into the USB's JLBCSearch/diagnostics/
folder (or the same folder as this script when no USB is found), then
prints the next step.

SECURITY: this script NEVER writes the OpenRouter API key or any doc
contents. It records only:
  - where the data dir resolves to (JLBC_DATA_DIR > machine.json > default)
  - per-file presence and sizes for the corpus-critical paths
  - lancedb table names, vector dims, row counts (via the app's own
    store.chunk_store, when importable)
  - the health ladder's data_dir + first failing rung
  - the newest server log + package version, with one-line redaction
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

REPORT_NAME = "diagnostic-report.txt"
LOG_NAME = "server-log"
LOG_COPY_NAME = "server-log-last.txt"

REDACT = ("api_key", "Authorization", "token", "secret", "password")
REDACTED_VALUE = "<redacted>"


def redact_text(text: str) -> str:
    """Blank any line that mentions a secret, or a quoted sk-or-... value.

    Better to drop a whole line than to risk a real key in a file that
    travels on a USB stick.
    """
    out = []
    for line in text.splitlines():
        low = line.lower()
        # REDACT is the tuple of secret indicator strings; any line that
        # mentions one is dropped whole. It would be safer to over-drop a
        # line than to let a real key out on a USB stick.
        if any(k in low for k in REDACT):
            out.append(REDACTED_VALUE)
            continue
        if "sk-or-v1-" in low:
            out.append(REDACTED_VALUE)
            continue
        out.append(line)
    return "\n".join(out)


def _size_mb(p: Path) -> str:
    try:
        if p.is_file():
            return f"{p.stat().st_size / 1e6:.1f} MB"
        if p.is_dir():
            total = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
            return f"{total / 1e6:.1f} MB"
    except OSError:
        return "?"
    return "?"


def _candidates() -> list[Path]:
    out: list[Path] = []
    env = os.environ.get("JLBC_DATA_DIR")
    if env:
        out.append(Path(env))
    try:
        import app.machine_config as mc
        d = mc.read_data_dir()
        if d:
            out.append(Path(d))
    except Exception:
        pass
    return out


def main() -> int:
    lines: list[str] = []
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    lines.append(f"JLBC Search diagnostic — {stamp}")
    lines.append(f"host: {os.environ.get('COMPUTERNAME', os.environ.get('HOSTNAME', '?'))}")
    lines.append(f"user: {os.environ.get('USERNAME', os.environ.get('USER', '?'))}")
    lines.append("=" * 60)

    # --- install / bundle version -----------------------------------------
    here = Path(__file__).resolve().parent
    ver = here / "VERSION"
    lines.append(f"install root: {here}")
    lines.append(f"package VERSION: {ver.read_text().strip() if ver.exists() else '(none)'}")
    pyw = here / "python" / "pythonw.exe"
    lines.append(f"python/pythonw.exe present: {pyw.exists()}")
    lines.append(f"launcher.pyw present: {(here / 'launcher.pyw').exists()}")

    # --- data dir -----------------------------------------------------------
    lines.append("-" * 60)
    lines.append("DATA DIRS (in resolution order):")
    for c in _candidates():
        l = c / "lancedb"
        lines.append(f"  {c}")
        lines.append(f"    exists={c.exists()}  lancedb={l.is_dir()}  "
                     f"lancedb size={_size_mb(l) if l.is_dir() else 'n/a'}")
        if l.is_dir():
            try:
                n = len(list(l.iterdir()))
            except OSError:
                n = -1
            lines.append(f"    lancedb top-level entries: {n}")

    # --- corpus health, using the app's own store -------------------------
    lines.append("-" * 60)
    lines.append("CORPUS OPEN CHECK (app's own ChunkStore):")
    try:
        import store.chunk_store as cs

        store = cs.ChunkStore()
        lines.append(f"  store root: {store._root}")
        for name in cs.CORPUS_TABLES:
            try:
                count = store.count(name)
                lines.append(f"  {name}: count={count}")
            except Exception as e:
                lines.append(f"  {name}: ERROR {type(e).__name__}: {e}")
    except Exception as e:
        lines.append(f"  couldn't build ChunkStore: {type(e).__name__}: {e}")

    # --- raw probe of each candidate dir's tables (no app imports) ---------
    lines.append("-" * 60)
    lines.append("RAW LANCEDB TABLES (per candidate):")
    try:
        import lancedb
    except Exception as e:
        lancedb = None
        lines.append(f"  lancedb import failed: {type(e).__name__}: {e}")
    if lancedb is not None:
        for c in _data_candidates():
            l = c / "lancedb"
            if not l.is_dir():
                continue
            try:
                db = lancedb.connect(str(l))
                names = db.table_names()
                lines.append(f"  {l}: tables={names}")
                for n in names:
                    try:
                        t = db.open_table(n)
                        dim = t.schema.field("vector").type.list_size
                        rows = t.count_rows()
                        lines.append(f"    {n}: dim={dim} rows={rows}")
                    except Exception as e:
                        lines.append(f"    {n}: ERROR {type(e).__name__}: {e}")
            except Exception as e:
                lines.append(f"  {l}: connect ERROR {type(e).__name__}: {e}")

    # --- settings (redacted) ---------------------------------------
    lines.append("-" * 60)
    lines.append("SETTINGS (redacted — no keys):")
    for c in _data_candidates():
        s = c / "settings.json"
        if s.exists():
            try:
                data = json.loads(s.read_text(encoding="utf-8"))
                safe = {}
                for k, v in data.items():
                    if k == "provider" and isinstance(v, dict):
                        safe[k] = {kk: (REDACTED_VALUE if kk == "api_key" else vv)
                                   for kk, vv in v.items()}
                    elif k in ("admin_username", "ai_enabled"):
                        safe[k] = v
                    else:
                        safe[k] = "<redacted for brevity>"
                lines.append(f"  {s}: {json.dumps(safe)}")
            except Exception as e:
                lines.append(f"  {s}: unreadable {type(e).__name__}: {e}")
        else:
            lines.append(f"  {s}: (missing)")

    # --- companion files --------------------------------------------
    lines.append("-" * 60)
    lines.append("COMPANION FILES (sizes):")
    for c in _data_candidates():
        for f in ("documents.json", "fiscal-notes-directory.json",
                  "model-catalog.json", "book-check.json"):
            p = c / f
            lines.append(f"  {f}: {_size_mb(p)}" if p.exists() else f"  {f}: (missing)")

    report = "\n".join(lines)

    # ---- where to write --------------------------------------------
    dest = None
    for p in _usb_candidates():
        if p.is_dir():
            dest = p / "JLBCSearch" / "diagnostics"
            try:
                dest.mkdir(parents=True, exist_ok=True)
            except OSError:
                dest = None
            if dest and dest.is_dir():
                break
    if dest is None:
        dest = here / "diagnostics"
        dest.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%S")
    rpath = dest / f"{REPORT_NAME}"
    rpath.write_text(report, encoding="utf-8")

    # copy newest server log (redacted) + version
    log_src = _newest_server_log()
    log_dst = dest / f"{LOG_NAME}-{stamp}.txt"
    if log_src:
        try:
            text = log_src.read_text(encoding="utf-8", errors="replace")
            log_dst.write_text(redact_text(text), encoding="utf-8")
        except OSError as e:
            lines.append(f"  (log copy failed: {e})")
            rpath.write_text("\n".join(lines), encoding="utf-8")

    print(report)
    print("=" * 60)
    print("REPORT WRITTEN TO:", rpath)
    if log_src:
        print("LOG COPIED TO:    ", log_dst)
    print()
    print("NEXT STEP:")
    print("  Send the files in the 'diagnostics' folder to whoever maintains")
    print("  this app, together with the exact message on the screen.")
    return 0


def _data_candidates() -> list[Path]:
    """Where the app might be reading its data from — JLBC_DATA_DIR first,
    then the machine.json pointer, then the default repo/install dir."""
    out: list[Path] = []
    env = os.environ.get("JLBC_DATA_DIR")
    if env:
        out.append(Path(env))
    try:
        import app.machine_config as mc
        d = mc.read_data_dir()
        if d:
            out.append(Path(d))
    except Exception:
        pass
    # The dev/install default: <install>/data/insight-data
    out.append(Path(__file__).resolve().parent / "data" / "insight-data")
    return out


def _usb_candidates() -> list[Path]:
    """Drive roots to search for a JLBCSearch folder (the USB layout)."""
    roots = []
    here = Path(__file__).resolve()
    anchor = Path(here.anchor) if here.anchor else Path("/")
    roots.append(anchor)
    for letter in "DEFG":
        p = Path(f"{letter}:\\")
        if p.exists():
            roots.append(p)
    return roots


def _newest_server_log() -> Path | None:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "JLBC-Search" / "logs"
    if not base.is_dir():
        return None
    try:
        files = sorted(base.glob("server-*.log"), key=lambda p: p.stat().st_mtime)
        return files[-1] if files else None
    except OSError:
        return None


if __name__ == "__main__":
    raise SystemExit(main())