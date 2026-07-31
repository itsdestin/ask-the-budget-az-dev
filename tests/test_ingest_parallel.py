"""Tests for parallel ingest (`JLBC_INGEST_WORKERS`).

These are the safety proofs, not a feature demo. Five properties, in the
order they matter:

  1. **No double-run.** Concurrent workers never both take the same job, and
     never both take two jobs for the same document.
  2. **No lost jobs.** Every queued document reaches `live` exactly once.
  3. **Crash recovery.** A worker that dies mid-job releases its hold without
     a human, and a LIVE worker's job is never stolen out from under it.
  4. **Writes stay serialized.** The corpus lock is held during the write
     phase and NOT during extraction — otherwise parallelism buys nothing
     and the single-writer invariant is at risk.
  5. **N=1 is today.** The default path is unchanged in every observable way.

No models and no MinerU — a fake extractor and a fake 8-dim embedder, same
as tests/test_ingest_worker.py, so the whole thing runs in seconds.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from ingest.claim import JobClaim, claims_dir
from ingest.jobs import advance, load_job, new_job, save
from ingest.lock import LOCK_FILENAME, IngestLock, LockHeldError
from ingest.worker import (
    DEFAULT_WORKERS,
    MAX_WORKERS,
    WORKERS_ENV_VAR,
    IngestWorker,
    WorkerContext,
    configured_worker_count,
)
from store.chunk_store import ChunkStore
from tests.test_ingest_worker import PAGE_BLOCKS, FakeEmbedder


class SlowFakeExtractor:
    """Fake MinerU that takes measurable time and reports its own overlap.

    The delay is what makes concurrency observable at all: with an instant
    extractor, four workers would finish before the second one started and
    the test would pass for the wrong reason.
    """

    name = "mineru"

    def __init__(self, pages: int = 1, delay_s: float = 0.15) -> None:
        self.pages = pages
        self.delay_s = delay_s
        self._lock = threading.Lock()
        self.calls: list[str] = []          # doc_id per extraction
        self.live = 0
        self.max_live = 0
        self.lock_seen_while_extracting = False

    def get_version(self) -> str:
        return "fake-1.0"

    def extract(self, *, source_path: Path, output_dir: Path, pages) -> None:
        from store.config import data_dir

        with self._lock:
            self.live += 1
            self.max_live = max(self.max_live, self.live)
            self.calls.append(Path(output_dir).name)
        try:
            time.sleep(self.delay_s)
            # Only meaningful at ONE worker, where nobody else could be
            # holding it: proof that extraction itself never takes the lock.
            if (data_dir() / LOCK_FILENAME).exists():
                self.lock_seen_while_extracting = True
            output_dir.mkdir(parents=True, exist_ok=True)
            for page in range(1, self.pages + 1):
                (output_dir / f"page-{page}.json").write_text(
                    json.dumps({
                        "extractor": "mineru-fake",
                        "source_pdf": str(source_path),
                        "page": page,
                        "blocks": PAGE_BLOCKS,
                    }),
                    encoding="utf-8",
                )
        finally:
            with self._lock:
                self.live -= 1


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    # Snapshots zip the whole corpus per document; irrelevant here and slow.
    monkeypatch.setenv("JLBC_INGEST_SNAPSHOT", "off")
    return tmp_path


@pytest.fixture()
def extractor():
    return SlowFakeExtractor()


@pytest.fixture()
def ctx(data_dir, extractor):
    from chunking.entity_stamper import EntityStamper

    return WorkerContext(
        store=ChunkStore(root=data_dir, dim=8),
        embedder=FakeEmbedder(),
        stamper=EntityStamper.from_default_paths(fund_catalog_path=None),
        extractor=extractor,
    )


def _queue(data_dir, n: int, *, doc_id: str | None = None) -> list:
    """n queued jobs, each with its own document unless doc_id is forced."""
    source = data_dir / "uploads" / "ab" / f"{'ab' * 32}.pdf"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"%PDF-1.4\n")
    jobs = []
    for i in range(n):
        job = new_job(
            doc_id=doc_id or f"jlbc-baseline-fy2027-doc{i:02d}",
            title=f"doc {i}",
            corpus="budget",
            source_path=str(source.relative_to(data_dir)),
            source_sha256="ab" * 32,
            publisher="jlbc",
            doc_type="baseline-per-agency",
            fiscal_year=2027,
        )
        save(job)
        jobs.append(job)
        # job_ids embed a UTC second; a distinct created_at keeps "oldest
        # first" meaningful rather than an accident of hash ordering.
        time.sleep(0.002)
    return jobs


def _wait_for(predicate, timeout_s: float = 30.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            if predicate():
                return
        except Exception:
            pass
        time.sleep(0.02)
    raise AssertionError("condition not reached in time")


# --- 1 + 2: no double-run, no lost jobs -------------------------------------


def test_every_queued_document_runs_exactly_once_under_six_workers(
    data_dir, ctx, extractor
):
    """The headline safety property: 12 documents, 6 workers, 12 extractions.

    A 13th extraction means two workers took the same job — which on a real
    run means two MinerU processes writing the same extractor-output
    directory and two writers racing for the same LanceDB rows.
    """
    jobs = _queue(data_dir, 12)
    worker = IngestWorker(ctx=ctx, poll_interval_s=0.01, workers=6)
    worker.start()
    try:
        _wait_for(lambda: all(load_job(j.job_id).state == "live" for j in jobs))
    finally:
        worker.stop()

    assert len(extractor.calls) == 12, "a document was extracted twice"
    assert sorted(extractor.calls) == sorted(j.doc_id for j in jobs)
    assert len(set(extractor.calls)) == 12


def test_extraction_actually_overlaps(data_dir, ctx, extractor):
    """The point of the whole change. If this fails, N workers are running
    one-at-a-time and the feature is a no-op with extra risk."""
    _queue(data_dir, 8)
    worker = IngestWorker(ctx=ctx, poll_interval_s=0.01, workers=4)
    worker.start()
    try:
        _wait_for(lambda: len(extractor.calls) == 8)
    finally:
        worker.stop()
    assert extractor.max_live >= 2


def test_two_jobs_for_the_same_document_never_run_at_once(data_dir, ctx, extractor):
    """make_doc_id() is known to collide across report families (STATUS.md),
    so a bulk backfill really does queue two jobs for one doc_id. Serial
    ingest made that safe by accident; parallel ingest must do it on purpose —
    both jobs write the same rows and extract into the same directory."""
    jobs = _queue(data_dir, 4, doc_id="jlbc-approps-fy2026-508")
    worker = IngestWorker(ctx=ctx, poll_interval_s=0.01, workers=4)
    worker.start()
    try:
        _wait_for(lambda: all(load_job(j.job_id).state == "live" for j in jobs))
    finally:
        worker.stop()

    assert extractor.max_live == 1, "same-document jobs overlapped"
    assert len(extractor.calls) == 4  # all four ran, just never together


def test_claim_next_hands_one_job_to_exactly_one_thread(data_dir, ctx):
    """The claim step alone, hammered — no pipeline, no timing luck."""
    _queue(data_dir, 1)
    worker = IngestWorker(ctx=ctx, poll_interval_s=0.01, workers=8)

    winners = []
    guard = threading.Lock()
    barrier = threading.Barrier(16)

    def contend():
        barrier.wait()
        claimed = worker._claim_next()
        if claimed is not None:
            with guard:
                winners.append(claimed)

    threads = [threading.Thread(target=contend) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(winners) == 1
    winners[0][1].release()


# --- 3: crash recovery ------------------------------------------------------


def test_a_crashed_workers_job_is_reclaimed(data_dir, ctx, extractor):
    """A claim left behind by a dead machine must not park the document."""
    (job,) = _queue(data_dir, 1)
    stale = JobClaim(job.job_id, doc_id=job.doc_id, stale_after_s=1)
    assert stale.try_acquire()
    stale._stop.set()                       # stop beating: simulate the crash
    for path in stale.paths:                # rewrite with an old heartbeat
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["machine"] = "DEAD-PC"
        payload["heartbeat_at"] = time.time() - 9999
        path.write_text(json.dumps(payload), encoding="utf-8")

    worker = IngestWorker(ctx=ctx, poll_interval_s=0.01, workers=2)
    worker.start()
    try:
        _wait_for(lambda: load_job(job.job_id).state == "live")
    finally:
        worker.stop()


def test_a_live_workers_job_is_never_stolen(data_dir, ctx, extractor):
    """The mirror image, and the more dangerous direction: while a claim is
    beating, no other worker may touch that job."""
    (job,) = _queue(data_dir, 1)
    holder = JobClaim(job.job_id, doc_id=job.doc_id, heartbeat_interval_s=0.02)
    assert holder.try_acquire()

    worker = IngestWorker(ctx=ctx, poll_interval_s=0.01, workers=4)
    worker.start()
    try:
        time.sleep(1.0)
        assert load_job(job.job_id).state == "queued"
        assert extractor.calls == []
    finally:
        worker.stop()
        holder.release()


def test_the_claim_is_released_when_a_job_fails(data_dir, ctx):
    """A failed document must not leave its claim behind — the retry button
    would appear to do nothing for the whole stale window."""
    class Boom(SlowFakeExtractor):
        def extract(self, **kwargs):
            raise RuntimeError("mineru CLI failed")

    ctx.extractor = Boom()
    (job,) = _queue(data_dir, 1)
    worker = IngestWorker(ctx=ctx, poll_interval_s=0.01, workers=2)
    worker.start()
    try:
        _wait_for(lambda: load_job(job.job_id).state == "failed")
        _wait_for(lambda: list(claims_dir().glob("*.claim")) == [])
    finally:
        worker.stop()


def test_stopping_the_pool_leaves_no_claims_behind(data_dir, ctx, extractor):
    _queue(data_dir, 6)
    worker = IngestWorker(ctx=ctx, poll_interval_s=0.01, workers=3)
    worker.start()
    time.sleep(0.3)
    worker.stop(timeout_s=30)
    assert list(claims_dir().glob("*.claim")) == []


# --- 4: writes stay serialized ----------------------------------------------


def test_only_one_worker_writes_the_corpus_at_a_time(
    data_dir, ctx, extractor, monkeypatch
):
    """The single-writer invariant, under four workers.

    Also proves the lock is not over-held: while one worker is inside the
    write phase, others are still extracting. If that overlap were zero the
    pool would be serialized behind the lock and worth nothing.
    """
    import ingest.worker as worker_mod

    real_write_doc = worker_mod.write_doc
    state = {"live": 0, "max_live": 0, "writes": 0, "lock_missing": 0,
             "overlapped": False}
    guard = threading.Lock()

    def probing_write_doc(*args, **kwargs):
        with guard:
            state["live"] += 1
            state["max_live"] = max(state["max_live"], state["live"])
            state["writes"] += 1
            if not (data_dir / LOCK_FILENAME).exists():
                state["lock_missing"] += 1
        try:
            # Widen the window a racing writer would hit, and watch whether
            # anyone is extracting while we hold the corpus lock.
            for _ in range(10):
                time.sleep(0.01)
                if extractor.live > 0:
                    state["overlapped"] = True
            return real_write_doc(*args, **kwargs)
        finally:
            with guard:
                state["live"] -= 1

    monkeypatch.setattr(worker_mod, "write_doc", probing_write_doc)

    jobs = _queue(data_dir, 8)
    worker = IngestWorker(ctx=ctx, poll_interval_s=0.01, workers=4)
    worker.start()
    try:
        _wait_for(lambda: all(load_job(j.job_id).state == "live" for j in jobs))
    finally:
        worker.stop()

    assert state["writes"] == 8
    assert state["max_live"] == 1, "two workers wrote the corpus at once"
    assert state["lock_missing"] == 0, "a write happened without the corpus lock"
    assert state["overlapped"], \
        "nobody extracted while the corpus lock was held — the pool is serialized"


def test_extraction_never_holds_the_corpus_lock(data_dir, ctx, extractor,
                                                monkeypatch):
    """One worker, so a lockfile seen during extraction can only be ours.

    Holding the lock across extraction is the obvious wrong implementation of
    parallel ingest: it looks correct, passes every serialization test, and
    makes N workers exactly as slow as one.
    """
    monkeypatch.delenv(WORKERS_ENV_VAR, raising=False)
    jobs = _queue(data_dir, 3)
    worker = IngestWorker(ctx=ctx, poll_interval_s=0.01, workers=1)
    worker.start()
    try:
        _wait_for(lambda: all(load_job(j.job_id).state == "live" for j in jobs))
    finally:
        worker.stop()
    assert not extractor.lock_seen_while_extracting


def test_the_process_mutex_stops_a_sibling_thread_stealing_a_stale_lock(tmp_path):
    """A write that outruns the stale timeout must not be stolen by a thread
    in the SAME process. Cross-machine theft is the crash-recovery escape
    hatch; in-process theft is just two writers on one corpus."""
    holder = IngestLock(root=tmp_path, stale_after_s=0)   # instantly "stale"
    holder.acquire()
    try:
        with pytest.raises(LockHeldError):
            IngestLock(root=tmp_path, stale_after_s=0).acquire()
    finally:
        holder.release()


def test_a_waiting_writer_gets_the_lock_when_the_holder_finishes(tmp_path):
    holder = IngestLock(root=tmp_path)
    holder.acquire()

    got = threading.Event()

    def wait_for_it():
        with IngestLock(root=tmp_path, wait_s=10.0):
            got.set()

    thread = threading.Thread(target=wait_for_it)
    thread.start()
    time.sleep(0.2)
    assert not got.is_set(), "the waiter took the lock while it was held"
    holder.release()
    thread.join(timeout=10)
    assert got.is_set()


# --- 5: N=1 is exactly today ------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [None, "", "  ", "1", "0", "-4", "abc", "2.5", "true"],
)
def test_anything_that_is_not_a_number_above_one_means_one_worker(
    monkeypatch, value
):
    """Fails safe in every direction. A typo must not silently change the
    office install's behaviour."""
    if value is None:
        monkeypatch.delenv(WORKERS_ENV_VAR, raising=False)
    else:
        monkeypatch.setenv(WORKERS_ENV_VAR, value)
    assert configured_worker_count() == DEFAULT_WORKERS == 1


def test_a_requested_count_is_clamped_to_the_hardware(monkeypatch):
    """`JLBC_INGEST_WORKERS=64` typed on a 4-core office PC must not start 64
    MinerU processes on it."""
    monkeypatch.setenv(WORKERS_ENV_VAR, "64")
    monkeypatch.setattr("os.cpu_count", lambda: 4)
    assert configured_worker_count() == 1

    monkeypatch.setattr("os.cpu_count", lambda: 32)
    assert configured_worker_count() == MAX_WORKERS


def test_the_default_worker_runs_one_thread(data_dir, ctx, monkeypatch):
    monkeypatch.delenv(WORKERS_ENV_VAR, raising=False)
    worker = IngestWorker(ctx=ctx, poll_interval_s=0.01)
    assert worker.worker_count == 1
    worker.start()
    try:
        assert len(worker._threads) == 1
    finally:
        worker.stop()


def test_default_mode_processes_the_queue_oldest_first(data_dir, ctx, extractor,
                                                       monkeypatch):
    """Today's observable behaviour, unchanged: one at a time, in order."""
    monkeypatch.delenv(WORKERS_ENV_VAR, raising=False)
    jobs = _queue(data_dir, 5)
    worker = IngestWorker(ctx=ctx, poll_interval_s=0.01)
    worker.start()
    try:
        _wait_for(lambda: all(load_job(j.job_id).state == "live" for j in jobs))
    finally:
        worker.stop()
    assert extractor.calls == [j.doc_id for j in jobs]
    assert extractor.max_live == 1


def test_default_mode_still_fails_fast_when_another_machine_holds_the_lock(
    data_dir, ctx, monkeypatch
):
    """At one worker a held lock means ANOTHER MACHINE is writing, and the
    original behaviour — fail the job with a clear reason rather than block —
    is preserved deliberately."""
    monkeypatch.delenv(WORKERS_ENV_VAR, raising=False)
    (job,) = _queue(data_dir, 1)
    # A foreign, freshly-beating lock: not ours, not stale.
    (data_dir / LOCK_FILENAME).write_text(
        json.dumps({"machine": "OTHER-PC", "pid": 1, "user": "x",
                    "heartbeat_at": time.time()}),
        encoding="utf-8",
    )
    worker = IngestWorker(ctx=ctx, poll_interval_s=0.01)
    worker.start()
    try:
        _wait_for(lambda: load_job(job.job_id).state == "failed")
    finally:
        worker.stop()
    assert "held by" in load_job(job.job_id).error


def test_parallel_mode_is_announced_loudly_at_startup(data_dir, ctx, monkeypatch,
                                                      capsys):
    monkeypatch.setenv(WORKERS_ENV_VAR, "4")
    monkeypatch.setattr("os.cpu_count", lambda: 32)
    worker = IngestWorker(ctx=ctx, poll_interval_s=0.01)
    worker.start()
    worker.stop()
    err = capsys.readouterr().err
    assert "PARALLEL INGEST" in err
    assert "4 workers" in err
    assert WORKERS_ENV_VAR in err


def test_the_default_path_says_nothing_about_workers(data_dir, ctx, monkeypatch,
                                                     capsys):
    monkeypatch.delenv(WORKERS_ENV_VAR, raising=False)
    worker = IngestWorker(ctx=ctx, poll_interval_s=0.01)
    worker.start()
    worker.stop()
    assert WORKERS_ENV_VAR not in capsys.readouterr().err


def test_a_clamped_request_says_so(data_dir, ctx, monkeypatch, capsys):
    """Silently running 2-wide when the operator asked for 32 would have them
    mis-plan the night around a throughput that never happens."""
    monkeypatch.setenv(WORKERS_ENV_VAR, "32")
    monkeypatch.setattr("os.cpu_count", lambda: 8)
    worker = IngestWorker(ctx=ctx, poll_interval_s=0.01)
    worker.start()
    worker.stop()
    err = capsys.readouterr().err
    assert "clamped from 32" in err


# --- resume still works -----------------------------------------------------


def test_this_machines_unfinished_jobs_are_resumed_before_new_ones(
    data_dir, ctx, extractor
):
    """Resumable work has extractor output on the share already: finishing it
    costs minutes, starting a fresh document costs an hour."""
    old = _queue(data_dir, 1)[0]
    advance(old, "extracting")           # simulates a crash mid-extraction
    fresh = _queue(data_dir, 1)[0]

    worker = IngestWorker(ctx=ctx, poll_interval_s=0.01, workers=1)
    worker.start()
    try:
        _wait_for(lambda: load_job(fresh.job_id).state == "live")
    finally:
        worker.stop()
    assert load_job(old.job_id).state == "live"
    assert extractor.calls[0] == old.doc_id
