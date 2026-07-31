"""MinerU wrapper for the background ingest queue.

`scripts/run_mineru.py` is the batch-era wrapper: one blocking
`subprocess.run` per contiguous page range, no timeout, no progress, no way
to stop it. That's fine for a script someone watches; it's wrong for a GUI
queue where a 210-page Baseline book runs overnight on an office i5 at
roughly 1–3 minutes per page and a colleague may well want to cancel it.

This wrapper adds the four things the queue needs, and reuses everything
else — `_contiguous_ranges`, `_read_mineru_output`, and the page-reindex /
table-rendering logic in `write_range_pages` — verbatim from the script,
because that logic already absorbed two real extraction bugs.

  1. **Resolved executable.** The packaged install (spec S7) sets
     `JLBC_MINERU_EXE`; dev machines fall back to `uv run mineru`.
  2. **Progress.** stdout is streamed and per-page log lines become
     `on_progress(pages_done, pages_total)` callbacks the job journal turns
     into "page 34/210".
  3. **Cancel.** Cooperative — checked between ranges and while streaming —
     and it kills the child rather than waiting out a 3-minute page.
  4. **Timeout.** A wedged MinerU must not hold the queue forever.

Resume granularity is the contiguous range, matching the one-CLI-invocation
boundary: `run()` returns the ranges it completed, and the job journal
replays that list on restart so a reboot re-extracts at most one range.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable, Sequence

from scripts.run_mineru import (
    _contiguous_ranges,
    _read_mineru_output,
    write_range_pages,
)

ProgressCallback = Callable[[int, int], None]

# Two hours per document. Generous on purpose: a 210-page book at 3 min/page
# is well past this, so the worker passes its own per-range budget; this
# default only catches an obviously-wedged run.
DEFAULT_TIMEOUT_S = 7200

EXE_ENV = "JLBC_MINERU_EXE"
MODELS_ENV = "JLBC_MINERU_MODELS"

# Point every extraction at an ALREADY-RUNNING `mineru.cli.fast_api` instead of
# letting each invocation start its own throwaway one.
#
# WHY this matters more than it looks: a `mineru` invocation was measured at
# ~38 s for a 2-page document, of which ~33 s is loading models — paid fresh
# every single time. Worse, each concurrent worker holds its own copy of those
# models in RAM, which is what actually capped parallel ingest (40 GB used /
# 12 GB free at 12 workers, while half the CPU sat idle). Pointing all workers
# at one warm server removes both: measured 38 s -> 8 s per document, with one
# set of models in memory instead of N.
#
# Output is unaffected — the same CLI does the same work, it just doesn't
# rebuild the world first. Verified byte-identical (block counts, text and
# bboxes) against the spawn-per-document path before this was wired up.
#
# Unset (the default, and the office install) = today's behavior exactly:
# every invocation starts its own temporary service.
API_URL_ENV = "JLBC_MINERU_API_URL"

# How long to give a killed child before giving up on reaping it. Short —
# we already asked it to die.
_KILL_GRACE_S = 5


class MineruCancelled(RuntimeError):
    """The caller cancelled this extraction."""


class MineruTimeout(RuntimeError):
    """MinerU exceeded its time budget and was killed."""


def resolve_api_url() -> str | None:
    """A shared mineru-api base URL, or None to spawn one per invocation.

    Whitespace-only is treated as unset so an empty variable in a launcher
    script cannot produce a `--api-url ` with nothing after it.
    """
    raw = os.environ.get(API_URL_ENV, "").strip()
    return raw or None


def resolve_mineru_exe() -> list[str]:
    """The command prefix that runs MinerU, as an argv list.

    Three rungs, in order:
      1. `JLBC_MINERU_EXE` — what the packaged install pins (spec S7). A
         stale value raises rather than falling through, because silently
         running a *different* mineru than the install bundled is how you
         get "works on my machine" bugs nobody can debug on a locked-down PC.
      2. `mineru` on PATH.
      3. `uv run mineru` — dev machines, where it lives in the project venv.
    """
    pinned = os.environ.get(EXE_ENV)
    if pinned:
        path = Path(pinned)
        if not path.exists():
            raise FileNotFoundError(
                f"{EXE_ENV} points at {pinned}, which does not exist. "
                "Fix or unset it."
            )
        return [str(path)]

    found = shutil.which("mineru")
    if found:
        return [found]
    return ["uv", "run", "mineru"]


class MineruRunner:
    """Runs MinerU over a page list, with progress, cancel, and timeout.

    One instance per job. `cancel()` is safe to call from another thread —
    it's the only cross-thread entry point, which is why it's a plain flag
    plus a process handle rather than anything more elaborate.
    """

    def __init__(self, exe: Sequence[str] | Path | None = None) -> None:
        if exe is None:
            self._exe = resolve_mineru_exe()
        elif isinstance(exe, Path):
            self._exe = [str(exe)]
        else:
            self._exe = list(exe)
        self._cancelled = threading.Event()
        self._proc: subprocess.Popen | None = None
        self._proc_lock = threading.Lock()
        self.last_process_returncode: int | None = None

    # --- control ------------------------------------------------------------

    def cancel(self) -> None:
        """Ask the run to stop. Kills a live child immediately."""
        self._cancelled.set()
        with self._proc_lock:
            proc = self._proc
        if proc is not None and proc.poll() is None:
            _kill(proc)

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    def child_env(self) -> dict[str, str]:
        """Environment for the MinerU child process.

        When `JLBC_MINERU_MODELS` names a bundled weights directory (the
        packaged install), pin MinerU to local weights so first run
        downloads nothing — spec S7's offline-first requirement, and on a
        locked-down JLBC PC an outbound model fetch is likely to be blocked
        anyway. Without it, leave the environment alone: a dev machine's
        existing HuggingFace cache is what makes MinerU work there at all.
        """
        env = dict(os.environ)
        models = env.get(MODELS_ENV)
        if not models:
            return env
        env["MINERU_MODEL_SOURCE"] = "local"
        config = Path(models) / "mineru.json"
        if config.is_file():
            env["MINERU_TOOLS_CONFIG_JSON"] = str(config)
        return env

    # --- running ------------------------------------------------------------

    def run(
        self,
        *,
        pdf: Path,
        out: Path,
        pages: list[int],
        on_progress: ProgressCallback | None = None,
        timeout_s: int = DEFAULT_TIMEOUT_S,
        completed_ranges: Sequence[Sequence[int]] | None = None,
    ) -> list[list[int]]:
        """Extract `pages` of `pdf` into `out`, one CLI call per range.

        Returns the ranges completed in THIS call plus the ones handed in as
        already done, in `[[start, end], ...]` form — the shape the job
        journal persists for crash-resume.

        `on_progress(done, total)` counts pages of the whole request, not of
        the current range: the UI shows "page 34/210" against the book, and
        a counter that restarted at each range would look like a bug.
        """
        out.mkdir(parents=True, exist_ok=True)
        done_ranges = [list(r) for r in (completed_ranges or [])]
        already_done = {p for start, end in done_ranges for p in range(start, end + 1)}

        total = len(pages)
        done = len(already_done & set(pages))
        if on_progress and done:
            on_progress(done, total)

        for start, end in _contiguous_ranges(pages):
            self._raise_if_cancelled()
            if [start, end] in done_ranges:
                continue

            span = [p for p in pages if start <= p <= end]
            base_done = done
            self._run_range(
                pdf=pdf, out=out, pages=pages, start=start, end=end,
                timeout_s=timeout_s,
                on_page=(
                    (lambda n: on_progress(min(base_done + n, total), total))
                    if on_progress
                    else None
                ),
            )
            done = base_done + len(span)
            done_ranges.append([start, end])
            if on_progress:
                on_progress(done, total)

        return done_ranges

    # --- internals ----------------------------------------------------------

    def _run_range(
        self,
        *,
        pdf: Path,
        out: Path,
        pages: list[int],
        start: int,
        end: int,
        timeout_s: int,
        on_page: Callable[[int], None] | None,
    ) -> None:
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            cmd = [
                *self._exe,
                "-p", str(pdf),
                "-o", str(tmp_path),
                "-s", str(start - 1),   # CLI is 0-indexed, inclusive
                "-e", str(end - 1),
                "-b", "pipeline",       # CPU-only backend; the default may want a GPU
            ]
            api_url = resolve_api_url()
            if api_url:
                cmd += ["--api-url", api_url]
            self._stream(cmd, timeout_s=timeout_s, on_page=on_page)
            # Read inside the TemporaryDirectory — MinerU writes into it.
            content_list, _markdown = _read_mineru_output(tmp_path, pdf.stem)

        write_range_pages(
            content_list, out=out, pdf=pdf, start=start, end=end, pages=pages
        )

    def _stream(
        self,
        cmd: list[str],
        *,
        timeout_s: int,
        on_page: Callable[[int], None] | None,
    ) -> None:
        """Run one CLI invocation to completion, streaming its output."""
        # stderr folded into stdout: MinerU writes its progress to one and its
        # errors to the other depending on version, and we want both in order.
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=self.child_env(),
        )
        with self._proc_lock:
            self._proc = proc

        # An explicit flag, not `timer.is_alive()`: the timer thread stays alive
        # for as long as its kill takes, so inferring "did it fire?" from
        # liveness races and reports a timeout as a generic CLI failure.
        expired = threading.Event()

        def on_timeout() -> None:
            expired.set()
            _kill(proc)

        timer = threading.Timer(timeout_s, on_timeout)
        timer.start()
        tail: list[str] = []
        pages_seen = 0
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                line = line.rstrip()
                # Bounded tail: MinerU logs hundreds of lines on SUCCESS, and
                # only the end is useful when it fails.
                tail.append(line)
                del tail[:-40]
                if self._cancelled.is_set():
                    _kill(proc)
                    break
                pages_seen = _pages_done(line, pages_seen)
                if on_page and pages_seen:
                    on_page(pages_seen)
            proc.wait(timeout=_KILL_GRACE_S)
        except subprocess.TimeoutExpired:
            _kill(proc)
        finally:
            timer.cancel()
            self.last_process_returncode = proc.returncode
            with self._proc_lock:
                self._proc = None

        self._raise_if_cancelled()
        if expired.is_set():
            raise MineruTimeout(
                f"mineru exceeded its {timeout_s}s budget and was stopped. "
                "Large books can legitimately take hours — raise the timeout "
                "if this document is genuinely that big."
            )
        if proc.returncode != 0:
            raise RuntimeError(
                "mineru CLI failed:\n" + "\n".join(tail[-30:])
            )

    def _raise_if_cancelled(self) -> None:
        if self._cancelled.is_set():
            raise MineruCancelled("extraction cancelled")


def _kill(proc: subprocess.Popen) -> None:
    """Stop a child and reap it. Tolerates an already-dead process."""
    try:
        proc.kill()
    except OSError:
        return
    try:
        proc.wait(timeout=_KILL_GRACE_S)
    except subprocess.TimeoutExpired:
        pass


def _pages_done(line: str, current: int) -> int:
    """Read a page counter out of one MinerU log line.

    MinerU has no documented machine-readable progress, so this reads its
    human progress lines ("Processing pages: 12/34", tqdm's "12/34"). It is
    deliberately advisory: the caller emits an exact count at the end of
    every range, so a missed or mis-parsed line costs a smoother progress
    bar, never correctness. Monotonic so a stray smaller number can't make
    the bar run backwards.
    """
    for token in line.replace(",", " ").split():
        if "/" not in token:
            continue
        left, _, right = token.partition("/")
        if left.isdigit() and right.isdigit() and int(right) > 0:
            value = int(left)
            if current < value <= int(right):
                return value
    return current
