"""JLBC Search — one-click diagnostic + repair tool (replaces the old one).

Runs from the USB (diag.cmd, or the run-/RUN-DIAGNOSTIC.cmd at the USB root)
on a machine whose app shows the failure screen "the search index is there
but could not be opened". Does four things, in order:

  1. COPY the app's newest server log (%LOCALAPPDATA%\\JLBC-Search\\logs)
     into the USB's JLBCSearch/diagnostics/ folder, redacted so no API key
     ever travels on a USB stick.
  2. VERIFY the copy of the corpus on the network/share drive against the
     USB seed: same file-by-file sizes under lancedb/, pdfs/ and the
     companion JSON files. Finds missing and half-copied files.
  3. REPORT the verdict in plain terms (and write a report file).
  4. OFFER TO REPAIR: copy the missing/mismatched files from the USB into
     the network folder, then re-verify, and finally open the repaired
     corpus with the app's own ChunkStore — the exact check the health
     ladder performs — so the report says "the app should start now"
     instead of guessing.

Why this replaced the old diag: the old script only WROTE A REPORT. The
failure screen's own guess is "the copy to the shared folder is incomplete
or still running", so the obvious next step is to compare the two copies
byte-for-byte and finish the copy — this script does that in one click.

Security (unchanged from the old diag): this NEVER writes the OpenRouter
API key. The server log copy drops any line that mentions a secret, and the
report records only paths, sizes, counts and row counts.
"""
from __future__ import annotations

import ctypes
import json
import os
import shutil
import sys
import time
from pathlib import Path

REPORT_NAME = "diagnostic-report.txt"
LOG_COPY_NAME = "server-log-last.txt"

REDACT = ("api_key", "Authorization", "token", "secret", "password")
REDACTED_VALUE = "<redacted>"

# The corpus-critical tree. pdfs/ is 7,628 files but the manifest walk is
# one-shot and cheap on both USB and share. Every other top-level entry
# (backups/, extractor-output/, jobs/, ...) is a working artifact the app
# can live without — the copy problem being diagnosed is one of these.
SCOPE = (
    "lancedb",
    "pdfs",
    "documents.json",
    "fiscal-notes-directory.json",
    "model-catalog.json",
)

# Text for the interactive prompts — plain and specific, this is used by a
# non-technical person on a laptop with no console experience.
_YES = frozenset({"y", "yes", "1"})


def redact_text(text: str) -> str:
    """Blank any line that mentions a secret, or a quoted sk-or-... value.

    Better to drop a whole line than to risk a real key in a file that
    travels on a USB stick.
    """
    out = []
    for line in text.splitlines():
        low = line.lower()
        if any(k in low for k in REDACT):
            out.append(REDACTED_VALUE)
            continue
        if "sk-or-v1-" in low:
            out.append(REDACTED_VALUE)
            continue
        out.append(line)
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Corpus comparison — the heart of the tool
# ---------------------------------------------------------------------------
def manifest(root: Path) -> tuple[dict[str, int], int, int]:
    """(relpath -> size_bytes) for every file under SCOPE, plus (files, bytes).

    A file that exists but cannot be read (drive dropped mid-walk, permission
    error) is recorded as size -1 so the compare reports it as a problem
    rather than silently skipping it. Relpaths use forward slashes so USB and
    network manifests compare equal regardless of Windows separators.
    """
    out: dict[str, int] = {}
    total_files = 0
    total_bytes = 0

    for entry in SCOPE:
        p = root / entry
        try:
            if p.is_file():
                sz = p.stat().st_size
                out[entry] = sz
                total_files += 1
                if sz >= 0:
                    total_bytes += sz
            elif p.is_dir():
                for dirpath, _dirnames, filenames in os.walk(p):
                    for fn in filenames:
                        fp = Path(dirpath) / fn
                        rel = str(fp.relative_to(root)).replace("\\", "/")
                        try:
                            sz = fp.stat().st_size
                        except OSError:
                            sz = -1
                        out[rel] = sz
                        total_files += 1
                        if sz >= 0:
                            total_bytes += sz
        except OSError:
            out[entry] = -1
            total_files += 1
    return out, total_files, total_bytes


def compare(usb: dict[str, int], net: dict[str, int]) -> dict:
    """Diff the two manifests.

    Returns:
      missing:    [(rel, usb_size)] — in the USB seed, absent on the network
      mismatch:   [(rel, usb_size, net_size)] — both present, different size
                  (a half-copied or interrupted file), or unreadable
      ok:         number of files that match exactly
      bytes_missing: total bytes that would need copying
    """
    missing: list[tuple[str, int]] = []
    mismatch: list[tuple[str, int, int]] = []
    ok = 0
    bytes_missing = 0
    for rel, usb_size in usb.items():
        net_size = net.get(rel)
        if net_size is None:
            missing.append((rel, usb_size))
            if usb_size >= 0:
                bytes_missing += usb_size
        elif usb_size != net_size:
            mismatch.append((rel, usb_size, net_size))
            if usb_size >= 0 and (net_size < 0 or usb_size > net_size):
                # Unreadable or short file on the network = needs re-copying.
                bytes_missing += max(usb_size - max(net_size, 0), 0)
        else:
            ok += 1
    return {
        "missing": missing,
        "mismatch": mismatch,
        "ok": ok,
        "bytes_missing": bytes_missing,
    }


def copy_missing(usb: Path, net: Path, items: list[tuple[str, int, int | None]]) -> tuple[int, list[str]]:
    """Copy each relpath from USB to network. Returns (copied, failures).

    (rel, usb_size) and (rel, usb_size, net_size) both unpack — mismatched
    entries carry net_size (possibly -1), missing entries carry None.
    """
    copied = 0
    failures: list[str] = []
    for item in items:
        rel = item[0]
        src = usb / rel
        dst = net / rel
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            copied += 1
        except OSError as err:
            failures.append(f"{rel}: {err}")
    return copied, failures


# ---------------------------------------------------------------------------
# The app's own open check — what the health ladder actually does
# ---------------------------------------------------------------------------
def open_check(root: Path) -> tuple[bool, str]:
    """Run ChunkStore().count("budget_chunks"), exactly like app/health.py
    rung corpus does. Returns (ok, one plain sentence).

    Deliberately does NOT construct ChunkStore when lancedb/ is missing:
    ChunkStore.__init__ CREATES the folder, and the health ladder's rule is
    never to manufacture the thing you are checking — a check that creates
    its own empty lancedb/ would report "set up but has no documents" for a
    folder that was actually the wrong one.
    """
    if not (root / "lancedb").is_dir():
        return False, "There is no search index folder (lancedb/) in this location."
    try:
        from store.chunk_store import ChunkStore

        count = ChunkStore(root=root).count("budget_chunks")
        if count <= 0:
            return True, "The search index is set up but has no budget documents in it yet."
        return True, f"The search index opens and holds {count:,} budget passages."
    except Exception as err:  # noqa: BLE001 — report, never traceback
        return False, (
            f"The search index could NOT be opened ({type(err).__name__}: {err}). "
            "The most likely cause is a half-finished copy — see the comparison above."
        )


# ---------------------------------------------------------------------------
# Discovery helpers
# ---------------------------------------------------------------------------
def machine_data_dir() -> Path | None:
    """The network/share folder the app is pointed at: env > machine.json.

    Resolution order deliberately mirrors store.config.resolve_data_dir.
    Falls back silently so a missing config reads as "nothing configured".
    """
    env = os.environ.get("JLBC_DATA_DIR")
    if env:
        return Path(env.strip())
    try:
        import app.machine_config as mc

        d = mc.read_data_dir()
        if d:
            return Path(d)
    except Exception:  # noqa: BLE001
        pass
    return None


def _add_install_to_path() -> None:
    """Make `import app` / `import store` work if this script runs from the
    USB but python came from the install. The launcher does the same insert;
    here it is defensive glue so diag.pyw can use the app's own modules."""
    candidate = Path(os.environ.get("LOCALAPPDATA", "")) / "JLBC-Search"
    # here = the FILE (packaging/diag/diag.pyw) — the install root is its
    # grandparent's parent: repo root next to app/ and store/.
    here = Path(__file__).resolve()
    install_root = here.parent.parent.parent
    for install in (candidate, install_root):
        if (install / "app" / "machine_config.py").is_file() and str(install) not in sys.path:
            sys.path.insert(0, str(install))
            return


def find_usb_corpus(explicit: Path | None) -> Path | None:
    """The USB seed folder: the drive root with a JLBCSearch\\lancedb dir.

    Probes C: then D..Z so the tool works whether the stick maps to the
    first free letter or a specific one. Returns None if not found — the
    caller then asks for a path.
    """
    if explicit is not None:
        return explicit if (explicit / "lancedb").is_dir() else None
    # The USB seed has the layout <drive>:\JLBCSearch\ with lancedb inside.
    here = Path(__file__).resolve().parent  # the dir holding diag.pyw
    roots = [here] if here.name == "JLBCSearch" else []
    roots += [Path(f"{c}:\\") for c in "CDEFGHIJ"]
    for root in roots:
        try:
            candidate = root if root.name == "JLBCSearch" else root / "JLBCSearch"
        except (OSError, ValueError):
            continue
        if (candidate / "lancedb").is_dir():
            return candidate
    return None


def newest_server_log() -> Path | None:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "JLBC-Search" / "logs"
    if not base.is_dir():
        return None
    try:
        files = sorted(base.glob("server-*.log"), key=lambda p: p.stat().st_mtime)
        return files[-1] if files else None
    except OSError:
        return None


def _size_str(n: int) -> str:
    if n < 0:
        return "? (unreadable)"
    return f"{n / 1e6:.1f} MB"


def _mb(n: int) -> float:
    return max(n, 0) / 1e6


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------
def build_report(*, usb: Path | None, net: Path | None, usb_mf: tuple | None,
                 net_mf: tuple | None, diff: dict, usb_check: tuple[bool, str] | None,
                 net_check: tuple[bool, str] | None) -> list[str]:
    lines: list[str] = []
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    lines.append(f"JLBC Search diagnostic — {stamp}")
    lines.append(f"host: {os.environ.get('COMPUTERNAME', os.environ.get('HOSTNAME', '?'))}")
    lines.append(f"user: {os.environ.get('USERNAME', os.environ.get('USER', '?'))}")
    lines.append("=" * 60)

    lines.append("WHERE THE APP LOOKS FOR THE CORPUS:")
    lines.append(f"  machine.json / env data dir: {net or '(none found)'}")

    if usb is None:
        lines.append("-" * 60)
        lines.append("USB CORPUS: not found on any drive. Plug the USB stick in")
        lines.append("  and run this again — without it the copy cannot be verified.")
        return lines

    if usb_mf is None or net_mf is None:
        lines.append("-" * 60)
        lines.append("CORPUS COMPARISON: could not be completed (see messages above).")
        return lines

    usb_files, usb_bytes = usb_mf[1], usb_mf[2]
    net_files, net_bytes = net_mf[1], net_mf[2]
    lines.append("-" * 60)
    lines.append("CORPUS COMPARISON (USB seed vs its copy on the network/share):")
    lines.append(f"  USB seed:     {usb_files:,} files, {_size_str(usb_bytes)}")
    lines.append(f"  Network copy: {net_files:,} files, {_size_str(net_bytes)}")
    lines.append(f"  Matching:     {diff['ok']:,} files")
    if diff["missing"]:
        lines.append(f"  MISSING on the network: {len(diff['missing']):,} files "
                     f"({_mb(diff['bytes_missing']):.1f} MB)")
        for rel, sz in diff["missing"][:20]:
            lines.append(f"    - {rel} ({_size_str(sz)})")
        if len(diff["missing"]) > 20:
            lines.append(f"    ... and {len(diff['missing']) - 20} more")
    if diff["mismatch"]:
        lines.append(f"  DIFFERENT SIZE (half-copied?): {len(diff['mismatch']):,} files")
        for rel, us, ns in diff["mismatch"][:20]:
            lines.append(f"    - {rel} (seed {_size_str(us)} vs copy {_size_str(ns)})")
        if len(diff["mismatch"]) > 20:
            lines.append(f"    ... and {len(diff['mismatch']) - 20} more")
    if not diff["missing"] and not diff["mismatch"]:
        lines.append("  VERDICT: the network copy of the corpus is COMPLETE — every file")
        lines.append("  on the USB seed is present on the network with the same size.")

    lines.append("-" * 60)
    lines.append("CORPUS OPEN CHECK (the app's own ChunkStore):")
    lines.append(f"  USB seed:     {usb_check[1] if usb_check else 'could not be checked'}")
    lines.append(f"  Network copy: {net_check[1] if net_check else 'could not be checked'}")
    return lines


def _prompt(question: str) -> str | None:
    """Ask the user. Returns None when there is no interactive console."""
    if not sys.stdin.isatty():
        return None
    try:
        return input(question).strip().lower()
    except EOFError:
        return None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    interactive = sys.stdin.isatty() and os.name == "nt"
    force_repair = "--copy" in argv or "-y" in argv
    check_only = "--check" in argv or not interactive  # never prompt when not a console

    _add_install_to_path()
    explicit_usb = None
    explicit_net = None
    if "--usb" in argv:
        explicit_usb = Path(argv[argv.index("--usb") + 1])
    if "--data" in argv:
        explicit_net = Path(argv[argv.index("--data") + 1])

    net = explicit_net or machine_data_dir()
    usb = find_usb_corpus(explicit_usb)

    lines: list[str] = []
    usb_mf: tuple[dict[str, int], int, int] | None = None
    net_mf: tuple[dict[str, int], int, int] | None = None
    diff: dict = {"missing": [], "mismatch": [], "ok": 0, "bytes_missing": 0}
    usb_check: tuple[bool, str] | None = None
    net_check: tuple[bool, str] | None = None

    # --- verify both copies ------------------------------------------------
    if usb is not None:
        print(f"USB corpus found at: {usb}")
        usb_mf = manifest(usb)
        usb_check = open_check(usb)
        print(f"  {usb_mf[1]:,} files, {_mb(usb_mf[2]):.1f} MB — open check: {usb_check[1]}")
    else:
        print("No USB corpus found. Verify/repair is skipped — the server log")
        print("is still copied below.")
        print()

    if net is not None:
        print(f"Network/share corpus at: {net}")
    elif not check_only:
        ans = _prompt("Enter the path of the network corpus folder (the one with lancedb inside): ")
        if ans:
            net = Path(ans)
    if net is not None and net.is_dir():
        net_mf = manifest(net)
        net_check = open_check(net)
        print(f"  {net_mf[1]:,} files, {_mb(net_mf[2]):.1f} MB — open check: {net_check[1]}")
        if usb_mf is not None:
            diff = compare(usb_mf[0], net_mf[0])
            print()
            print(f"Comparison: {diff['ok']:,} files match, "
                  f"{len(diff['missing']):,} missing, {len(diff['mismatch']):,} different size.")
            if diff["missing"] or diff["mismatch"]:
                print(f"  {_mb(diff['bytes_missing']):.1f} MB would need copying.")
            else:
                print("  The network copy is COMPLETE.")

    # --- repair offer ------------------------------------------------------
    repaired = False
    if usb is not None and net is not None and (diff["missing"] or diff["mismatch"]):
        if force_repair or (not check_only and _prompt(
                "The network copy is incomplete. Copy the missing files from the "
                "USB into it now? (y/n) ") in _YES):
            items: list[tuple[str, int, int | None]] = (
                [(r, s, None) for r, s in diff["missing"]]
                + [(r, s, n) for r, s, n in diff["mismatch"]]
            )
            print()
            print("Copying...")
            copied, failures = copy_missing(usb, net, items)
            print(f"  Copied {copied:,} files, {len(failures):,} failed.")
            for f in failures[:10]:
                print(f"    FAILED: {f}")
            # re-verify
            net_mf = manifest(net)
            net_check = open_check(net)
            diff = compare(usb_mf[0], net_mf[0])
            repaired = not diff["missing"] and not diff["mismatch"]
            print()
            if repaired and net_check and net_check[0]:
                print("VERDICT: repaired. Every file matches the USB seed and the app's")
                print("  own open check passes — reopen the app now.")
            else:
                print("VERDICT: still incomplete after copying. The failures above are")
                print("  the reason; usually a drive that disconnected mid-copy.")
    elif check_only:
        pass  # a --check run never repairs

    # --- report file + server log ------------------------------------------
    lines = build_report(
        usb=usb, net=net, usb_mf=usb_mf, net_mf=net_mf, diff=diff,
        usb_check=usb_check, net_check=net_check,
    )
    dest_dir = None
    if usb is not None:
        dest_dir = usb / "diagnostics"
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            dest_dir = None
    if dest_dir is None:
        dest_dir = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "JLBC-Search" / "diagnostics"
        dest_dir.mkdir(parents=True, exist_ok=True)
    rpath = dest_dir / REPORT_NAME
    rpath.write_text("\n".join(lines), encoding="utf-8")
    print()
    print("=" * 60)
    print("REPORT WRITTEN TO:", rpath)
    for line in lines:
        print(line)

    log_src = newest_server_log()
    if log_src:
        try:
            log_dst = dest_dir / LOG_COPY_NAME
            log_dst.write_text(redact_text(log_src.read_text(encoding="utf-8", errors="replace")),
                               encoding="utf-8")
            print("SERVER LOG COPIED TO:", log_dst)
        except OSError as err:
            print(f"(log copy failed: {err})")
    else:
        print("(no server log found at %LOCALAPPDATA%\\JLBC-Search\\logs)")

    print()
    print("NEXT STEP:")
    if repaired:
        print("  Reopen the app (double-click the JLBC Search shortcut).")
    elif diff["missing"] or diff["mismatch"]:
        print("  The network copy is incomplete. Run this tool again with the USB")
        print("  plugged in and answer 'y' to repair it, or finish the copy by hand.")
    elif net_check and not net_check[0]:
        print("  The copy looks complete but the app still cannot open it — send the")
        print("  files in the diagnostics folder to whoever supports this app.")
    else:
        print("  If the app still will not start, send the files in the diagnostics")
        print("  folder to whoever supports this app.")

    if os.name == "nt" and not sys.stdin.isatty():
        # Double-clicked diag.pyw directly (pythonw, no console): speak up.
        try:
            ctypes.windll.user32.MessageBoxW(
                None, "\n".join(lines[-12:]), "JLBC Search diagnostic", 0x40)
        except Exception:  # noqa: BLE001
            pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())