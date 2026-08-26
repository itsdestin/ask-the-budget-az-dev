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
import sys
import threading
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable, Sequence

from scripts.run_mineru import (
    _block_page,
    _contiguous_ranges,
    _read_mineru_output,
    write_range_pages,
)

ProgressCallback = Callable[[int, int], None]

# (doc_id, state) for the batch path, where state is one of "done",
# "failed" or "cancelled". Documents, not pages — one CLI invocation covers
# the whole batch, so there is no honest per-page counter to report.
DocumentCallback = Callable[[str, str], None]

# Two hours per document. Generous on purpose: a 210-page book at 3 min/page
# is well past this, so the worker passes its own per-range budget; this
# default only catches an obviously-wedged run.
DEFAULT_TIMEOUT_S = 7200

# Batch budget = one model load + a per-document allowance. A batch of 20
# is 20 documents of work inside ONE process, so reusing DEFAULT_TIMEOUT_S
# would kill perfectly healthy batches; and a flat "very large" number would
# let a wedged batch of 2 hold the queue for half a day. Both numbers are
# deliberately loose — this catches a hung run, it does not pace a real one.
BATCH_STARTUP_TIMEOUT_S = 1800
BATCH_TIMEOUT_PER_DOC_S = 1800

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

# One pdfium call at a time inside this process. Same shape, and the same
# reason, as `_EMBED_MUTEX` in ingest/worker.py: one shared native library,
# several worker threads, and no thread-safety guarantee from the library.
#
# THIS LOCK IS REQUIRED FOR CORRECTNESS, NOT PERFORMANCE. Do not delete it
# because it guards a call that takes a millisecond. **pypdfium2 is not
# thread-safe** — pdfium keeps global state, and concurrent use corrupts it,
# so a PERFECTLY VALID PDF comes back as
# `PdfiumError: Failed to load document (PDFium: Data format error)`.
#
# Measured 2026-08-02, same 80 real PDFs, same process:
#   serial probe of 80 files ................ 0 failures
#   4 threads over the same 80 files ........ 60, then 80, then 80 failures
#
# And it is not theoretical: at `JLBC_INGEST_WORKERS=4` this cost the live
# backfill **224 valid documents**, all failed inside one six-minute window
# with that identical message, every one of them a file that opens fine and
# had been byte-final on disk for two days.
#
# It is held only around the open -> page-count -> close sequence, which is
# milliseconds, and never across staging or any other I/O — so it does not
# pace the batch. Retrying instead of locking would paper over a data race
# and still fail under load; dropping the probe reinstates the whole-batch
# abort it was written for. Neither is a fix.
_PDFIUM_MUTEX = threading.Lock()


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


def batch_timeout_s(count: int) -> int:
    """Time budget for a batch of `count` documents.

    Scales with the batch because the whole point of batching is that ONE
    invocation now carries N documents' worth of work.
    """
    return BATCH_STARTUP_TIMEOUT_S + BATCH_TIMEOUT_PER_DOC_S * max(count, 1)


def resolve_mineru_exe() -> list[str]:
    """The command prefix that runs MinerU, as an argv list.

    Four rungs, in order:
      1. `JLBC_MINERU_EXE` — what the packaged install pins (spec S7). A
         stale value raises rather than falling through, because silently
         running a *different* mineru than the install bundled is how you
         get "works on my machine" bugs nobody can debug on a locked-down PC.
      2. `mineru` on PATH.
      3. The `mineru` module, run with the current interpreter — the
         Windows bundle's shape (see below).
      4. `uv run mineru` — dev machines, where it lives in the project venv.
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

    # The Windows bundle (packaging/build_bundle.py) ships the `mineru`
    # PACKAGE but no `mineru.exe` — the embeddable interpreter has no
    # Scripts/ dir and the POSIX console scripts uv lays down are Linux
    # shebangs. `mineru.cli.client:main` is what the console script wraps
    # (mineru-3.1.6.dist-info/entry_points.txt), so run the module with the
    # interpreter we are already inside. Under the launcher that is
    # pythonw.exe, which also means: no console window. Found 2026-08-25 —
    # before this rung the bundle fell through to `uv run mineru`.
    import importlib.util

    if importlib.util.find_spec("mineru") is not None:
        return [sys.executable, "-m", "mineru.cli.client"]
    return ["uv", "run", "mineru"]


class MineruRunner:
    """Runs MinerU over a page list, with progress, cancel, and timeout.

    One instance per job. `cancel()` is safe to call from another thread —
    it's the only cross-thread entry point, which is why it's a plain flag
    plus a process handle rather than anything more elaborate.
    """

    def __init__(
        self,
        exe: Sequence[str] | Path | None = None,
        *,
        method: str = "auto",
    ) -> None:
        if exe is None:
            self._exe = resolve_mineru_exe()
        elif isinstance(exe, Path):
            self._exe = [str(exe)]
        else:
            self._exe = list(exe)
        # MinerU's `-m` flag. Per-instance, not per-call -- fine for the
        # per-document path (the ladder in ingest/ladder.py picks a rung
        # BEFORE extraction starts, so the worker builds one runner per
        # attempt), but NOT solved for the batch path: `run_batch()` takes
        # up to 40 documents and ingest/worker.py builds exactly ONE runner
        # for the whole batch (see the `MineruRunner()` construction ahead
        # of the `run_batch(items, ...)` call), so one `-m` value covers
        # every document in it. A mixed-rung batch either OCRs documents
        # that didn't need it (hours of wasted work) or fails to OCR the one
        # that did -- grouping a batch to be homogeneous by rung before it
        # reaches this class is the CALLER's job, not something enforced
        # here. "auto" is BEHAVIOURALLY equivalent to today's command line,
        # not textually identical to it -- every call site below now passes
        # `-m auto` explicitly where it previously omitted `-m` and relied
        # on the installed CLI's own default (`mineru --help` documents
        # `-m, --method [auto|txt|ocr]`, defaulting to auto), so every
        # existing caller's RESULT is unaffected even though the literal
        # argv is not.
        self._method = method
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

    def run_batch(
        self,
        items: Sequence[tuple[str, Path, Path]],
        *,
        timeout_s: float | None = None,
        on_document: DocumentCallback | None = None,
    ) -> dict[str, str | None]:
        """Extract several WHOLE documents in one MinerU invocation.

        `items` is `(doc_id, pdf_path, out_dir)` per document. Returns
        `{doc_id: None}` on success or `{doc_id: "reason"}` on failure — one
        entry per input, always.

        WHY this exists: a MinerU invocation costs ~38 s for a small
        document and ~33 s of that is loading models. `mineru -p <directory>`
        is MinerU's own batch mode and loads them ONCE for the whole folder,
        measured 2.85x on only four documents.

        WHY the types are this plain: the ingest worker codes against this
        without importing anything new from this module, so a change here
        cannot silently break it. Tuples in, plain dict out, deliberately.

        Failures are per-document, not per-batch: MinerU finishes the rest of
        the folder when one file fails and merely exits non-zero, so a
        non-zero exit is recorded against the documents that produced no
        output and NOT against their 19 healthy batch-mates.

        That tolerance has ONE exception, and it is why every candidate is
        probed before it is staged: a PDF MinerU cannot even open fails in
        its input preflight, before extraction starts, and takes the whole
        invocation down with it. `_unreadable_pdf_reason` keeps those files
        out of the batch so they fail alone.

        Cancel and timeout are the two batch-level exits — they kill the one
        child, so nothing unfinished can be salvaged. Both notify every
        unfinished document and then raise, matching `run()`.

        This path is for whole small documents only. A long book keeps the
        per-range `run()` path: its resume granularity is the page range, and
        batching ranges would multiply the state space for no gain.
        """
        results: dict[str, str | None] = {}
        if not items:
            return results
        _check_batch_doc_ids(items)
        self._raise_if_cancelled()

        budget = timeout_s if timeout_s is not None else batch_timeout_s(len(items))

        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            stage = tmp_path / "in"
            stage.mkdir()
            mineru_out = tmp_path / "out"
            mineru_out.mkdir()

            runnable: list[tuple[str, Path, Path]] = []
            for doc_id, pdf, out_dir in items:
                # Probe BEFORE staging: an unreadable PDF that reaches the
                # staging directory takes the whole batch down with it. See
                # `_unreadable_pdf_reason` for the measurement.
                unreadable = _unreadable_pdf_reason(pdf)
                if unreadable is not None:
                    results[doc_id] = unreadable
                    if on_document:
                        on_document(doc_id, "failed")
                    continue
                try:
                    # Stage under doc_id, NEVER the original filename: MinerU
                    # names its output by input stem, and 508.pdf exists in
                    # both the FY2026 Baseline and the FY2026 Approps. Staging
                    # by filename would hand one agency's budget text to
                    # another — plausible, cited, and wrong.
                    _stage_pdf(pdf, stage / f"{doc_id}.pdf")
                except OSError as exc:
                    # One unreadable path must not stop its batch-mates.
                    results[doc_id] = f"could not stage {pdf}: {exc}"
                    if on_document:
                        on_document(doc_id, "failed")
                else:
                    runnable.append((doc_id, pdf, out_dir))

            if not runnable:
                return results

            cmd = [
                *self._exe,
                "-p", str(stage),       # a DIRECTORY — MinerU's batch mode
                "-o", str(mineru_out),
                "-b", "pipeline",       # CPU-only backend, as per document
                "-m", self._method,
            ]
            api_url = resolve_api_url()
            if api_url:
                cmd += ["--api-url", api_url]

            cli_error: str | None = None
            try:
                # on_page=None: page counters from a batch run belong to
                # whichever document MinerU is on, which we cannot attribute.
                self._stream(cmd, timeout_s=budget, on_page=None)
            except MineruCancelled:
                _notify(runnable, "cancelled", on_document)
                raise
            except MineruTimeout:
                _notify(runnable, "failed", on_document)
                raise
            except RuntimeError as exc:
                # Not fatal on its own — see the per-document note above.
                cli_error = str(exc)

            for doc_id, pdf, out_dir in runnable:
                reason = self._demux_one(
                    doc_id=doc_id, pdf=pdf, out=out_dir,
                    mineru_out=mineru_out, cli_error=cli_error,
                )
                results[doc_id] = reason
                if on_document:
                    on_document(doc_id, "done" if reason is None else "failed")

        return results

    # --- internals ----------------------------------------------------------

    def _demux_one(
        self,
        *,
        doc_id: str,
        pdf: Path,
        out: Path,
        mineru_out: Path,
        cli_error: str | None,
    ) -> str | None:
        """Turn one document's share of a batch run into the per-page files.

        Returns None on success or a human-readable reason on failure.
        """
        try:
            content_list, _markdown = _read_mineru_output(mineru_out, doc_id)
        except (RuntimeError, ValueError) as exc:
            # No output for this document. If the CLI also reported an error,
            # that tail is the more useful reason to show.
            return cli_error or str(exc)

        pages = sorted(
            {p for p in (_block_page(b) for b in content_list) if p is not None}
        )
        if not pages:
            # An extraction that "succeeded" with nothing in it is the FY2024
            # AFR shape. Refusing it here means the worker sees a failure with
            # a reason instead of a document that reaches `live` and empty.
            reason = f"mineru produced no page content for {doc_id}"
            return f"{reason}: {cli_error}" if cli_error else reason

        # start=1 because batch mode extracts the WHOLE document, so MinerU's
        # in-range renumbering is already the absolute page number. Ask for
        # every page up to the last one with content, so a genuinely blank
        # page still gets its (empty) page file, exactly as `run()` does.
        end = pages[-1]
        # mkdir only now: an existing output directory is the worker's
        # "extraction already done" signal, so a failure must never leave one.
        out.mkdir(parents=True, exist_ok=True)
        write_range_pages(
            content_list,
            out=out,
            # The ORIGINAL pdf, not the staged copy — the copy dies with the
            # temp directory, and this path is recorded as provenance.
            pdf=pdf,
            start=1,
            end=end,
            pages=list(range(1, end + 1)),
        )
        return None

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
                "-m", self._method,
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
        # A console-subsystem child spawned from pythonw.exe gets its own
        # console window — a black box on the analyst's desktop for the length
        # of the extraction, and closing it kills the job. The bundle runs
        # MinerU via pythonw (see resolve_mineru_exe) so this is belt-and-
        # braces for a dev running the server from python.exe; it does NOT
        # reach OpenDataLoader's Java child, whose runner hardcodes its own
        # Popen (spec §W).
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=self.child_env(),
            creationflags=flags,
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


def _check_batch_doc_ids(items: Sequence[tuple[str, Path, Path]]) -> None:
    """Refuse a batch whose doc_ids can't each be one staged filename.

    Two items sharing a doc_id would stage over each other and one document
    would vanish with no error; a doc_id carrying a path separator would
    write outside the batch directory entirely. Both are caller bugs, so
    they fail loudly here rather than producing quietly wrong output.
    """
    seen: set[str] = set()
    for doc_id, _pdf, _out in items:
        if not doc_id or doc_id in {".", ".."} or "/" in doc_id or "\\" in doc_id:
            raise ValueError(
                f"doc_id {doc_id!r} is not usable as a filename; a batch "
                "stages every PDF under its doc_id"
            )
        if doc_id in seen:
            raise ValueError(f"doc_id {doc_id!r} appears twice in one batch")
        seen.add(doc_id)


def _unreadable_pdf_reason(pdf: Path) -> str | None:
    """None if this file is a PDF MinerU can open; else why it isn't.

    WHY this exists — measured 2026-08-01: **one truncated PDF aborted an
    entire batch.** MinerU collects and probes every input in the folder
    BEFORE it extracts anything, and one file it cannot open raises out of
    that preflight and exits the whole invocation with `rc=1` and zero
    output — for all 20 documents. It costs only ~3.3 s, because nothing was
    extracted yet, but at `JLBC_INGEST_BATCH=40` it marks 40 documents
    failed on account of one bad file. Excluding the bad file here means it
    fails alone and its batch-mates run.

    This is not hypothetical: the backfill fetches ~3,500 PDFs over the
    network from azjlbc.gov, which has already served us a genuinely empty
    PDF and 404 HTML bodies saved under a `.pdf` name. A poison pill is
    expected.

    WHY pdfium, and NOT `ingest.dispatcher._pdf_page_count` — this is the
    crux, and reusing that helper is the obvious "simplification" that
    would silently bring the bug back. `_pdf_page_count` uses PyMuPDF, and
    **PyMuPDF is more tolerant than pdfium**. Measured on the same files:
    a real PDF cut to 90% of its bytes is opened happily by PyMuPDF, which
    reports all 6 pages, and REJECTED by pdfium; an HTML 404 body renamed
    `.pdf` reads to PyMuPDF as a 1-page document and is likewise rejected
    by pdfium. MinerU's own preflight uses pdfium, so pdfium is the only
    library whose answer predicts what MinerU will do. A PyMuPDF check
    would wave through the exact file that kills the batch.

    Deliberately narrow: `PdfiumError` (a `RuntimeError` subclass, raised
    for truncated / empty / not-actually-a-PDF input) and `OSError` (the
    file is missing, unreadable, or the share dropped mid-read). Anything
    else propagates — a bug in our own code must not be filed away as
    "unreadable PDF" and blamed on the publisher.

    WHY the whole body is under `_PDFIUM_MUTEX`: `run_batch` runs on a worker
    thread, and at `JLBC_INGEST_WORKERS=4` four of them probe at once. pdfium
    is not thread-safe and concurrent use rejects VALID files — see the
    measurements on `_PDFIUM_MUTEX`. The lock spans open -> count -> close,
    not just the constructor, because it is concurrent *use* that corrupts
    pdfium's state, not only concurrent construction.
    """
    # Lazy, matching `ingest.dispatcher._pdf_page_count`: importing
    # pypdfium2 loads a native library, and only the batch path needs it.
    # It is already installed — MinerU depends on it. Outside the mutex on
    # purpose: CPython already serializes module imports, and holding our
    # lock through a native-library load would stall every other worker on
    # the very first probe.
    import pypdfium2

    with _PDFIUM_MUTEX:
        doc = None
        try:
            doc = pypdfium2.PdfDocument(str(pdf))
            # Read the page count, which is what MinerU's preflight actually
            # asks for. Opening is where a poison pill fails today, but a file
            # that opens and then cannot be counted is just as fatal there.
            len(doc)
        except (pypdfium2.PdfiumError, OSError) as exc:
            return f"unreadable PDF {pdf}: {exc}"
        finally:
            if doc is not None:
                doc.close()
    return None


def _stage_pdf(src: Path, dest: Path) -> None:
    """Put one PDF into the batch directory under its staged name.

    Hardlink when the filesystem allows it — MinerU only reads the file, and
    a book edition's worth of PDFs is real bytes to copy. Falls back to a
    copy across devices, which is the normal case when the corpus is on the
    share and the temp directory is on local disk.
    """
    try:
        os.link(src, dest)
    except OSError:
        shutil.copy2(src, dest)


def _notify(
    items: Sequence[tuple[str, Path, Path]],
    state: str,
    on_document: DocumentCallback | None,
) -> None:
    if not on_document:
        return
    for doc_id, _pdf, _out in items:
        on_document(doc_id, state)


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
