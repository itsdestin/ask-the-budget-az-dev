#!/usr/bin/env python3
"""Pre-fetch every source PDF the S20 backfill will need into the DownloadCache.

WHY this exists
---------------
The S20 historical backfill runs MinerU over thousands of JLBC book pages and
fiscal notes. MinerU takes 1-3 minutes PER PAGE, so a backfill is a multi-day
grind — and every one of those days is a day where a network hiccup, a moved
URL, or an azjlbc.gov redesign can stall the run mid-flight. Downloading the
bytes FIRST turns two failure modes into one:

  * the ingest run never waits on (or fails from) the network, and
  * dead/moved URLs surface NOW, days before anyone is depending on them.

This script downloads ONLY. It never touches the LanceDB corpus, never enqueues
an ingest job, and never starts the app.

What it fetches
---------------
1. ``data/jlbc-book-catalog.json`` — the 38 editions flagged ``ingestable``
   (S20 scope: baselines FY2012-2027, approps FY2005-2026). For each: every
   ``per_agency[]`` and ``summary_sections[]`` URL, plus the edition's
   ``agency_index_url`` / ``linked_toc_url`` (small, and useful for verifying
   the per-agency list is still complete).

   Deliberately NOT fetched: ``single_file_url`` on the non-ingestable pre-2005
   editions. Those are whole-book PDFs outside S20 scope; pulling them would
   add hundreds of MB nobody has scheduled to ingest.

2. ``app/data/fiscal-notes-snapshot.json`` — every bill's ``fiscal_note_url``
   (azleg.gov).

Politeness
----------
These are Arizona state government web servers and the run is ~7,500 requests.
Concurrency is capped, a global rate limiter spaces request STARTS apart, the
User-Agent identifies the project, and 429/5xx responses get exponential
backoff. If the server starts refusing sustained (consecutive 429s or connection
refusals), the run ABORTS with a clear message rather than hammering through —
a partial cache is fine, a blocked IP is not.

Resumability
------------
Every URL already in the cache is skipped via ``DownloadCache.has()``, so a
re-run after an abort/Ctrl-C costs one manifest read and picks up where it left
off. The manifest is flushed periodically and on every exit path.

Usage
-----
    uv run python -m scripts.prefetch_corpus_pdfs --all
    uv run python scripts/prefetch_corpus_pdfs.py --books --limit 50
    uv run python scripts/prefetch_corpus_pdfs.py --fiscal-notes --dry-run
"""

from __future__ import annotations

import argparse
import json
import random
import signal
import sys
import threading
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ingest.cache import DownloadCache  # noqa: E402

BOOK_CATALOG = REPO_ROOT / "data" / "jlbc-book-catalog.json"
FISCAL_NOTES_SNAPSHOT = REPO_ROOT / "app" / "data" / "fiscal-notes-snapshot.json"
CACHE_ROOT = REPO_ROOT / "data" / "cached-pdfs"
FAILURES_PATH = REPO_ROOT / "data" / "prefetch-failures.json"

USER_AGENT = (
    "jlbc-search/1.0 (JLBC budget-document research tool; "
    "one-time content prefetch; contact: destinj101@gmail.com)"
)

# Consecutive rejections (429 / connection refused) before we conclude the
# server is pushing back and stop. Not a per-URL count — a single flaky file
# shouldn't end the run, but a wall of them means we are the problem.
ABORT_AFTER_CONSECUTIVE_REJECTIONS = 12

REQUEST_TIMEOUT = 90
MAX_ATTEMPTS = 4
PROGRESS_EVERY = 50
MANIFEST_FLUSH_EVERY = 25


class ServerPushbackError(RuntimeError):
    """Raised when the origin is sustainedly refusing us — abort the run."""


class NotAPdfError(RuntimeError):
    """Body did not start with %PDF — almost always an HTML error page.

    Caching that under a .pdf name would poison the backfill: MinerU would be
    handed a 404 page and produce chunks of navigation text. Better to record
    it as a failure now.
    """


# --------------------------------------------------------------------------
# Work list
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class WorkItem:
    url: str
    group: str  # edition key, or "fiscal-notes/<session year>"
    kind: str  # per_agency | summary_section | agency_index | linked_toc | fiscal_note
    label: str


def book_work_items() -> list[WorkItem]:
    catalog = json.loads(BOOK_CATALOG.read_text(encoding="utf-8"))
    items: list[WorkItem] = []
    for key, edition in sorted(catalog["editions"].items()):
        # S20 scope is exactly the ingestable flag; non-ingestable editions are
        # whole-book-only pre-2005 records nobody is backfilling.
        if not edition.get("ingestable"):
            continue
        for field_name, kind in (
            ("agency_index_url", "agency_index"),
            ("linked_toc_url", "linked_toc"),
        ):
            url = edition.get(field_name)
            if url:
                items.append(WorkItem(url, key, kind, field_name))
        for entry in edition.get("per_agency") or []:
            items.append(
                WorkItem(
                    entry["url"], key, "per_agency", entry.get("code") or entry["url"]
                )
            )
        for entry in edition.get("summary_sections") or []:
            items.append(
                WorkItem(
                    entry["url"],
                    key,
                    "summary_section",
                    entry.get("name") or entry["url"],
                )
            )
    return items


def fiscal_note_work_items() -> list[WorkItem]:
    snapshot = json.loads(FISCAL_NOTES_SNAPSHOT.read_text(encoding="utf-8"))
    items: list[WorkItem] = []
    for session in snapshot["sessions"]:
        group = f"fiscal-notes/{session.get('year')}"
        for bill in session.get("bills") or []:
            url = bill.get("fiscal_note_url")
            if url:
                items.append(
                    WorkItem(url, group, "fiscal_note", bill.get("bill_number") or url)
                )
    return items


def dedupe(items: list[WorkItem]) -> tuple[list[WorkItem], dict[str, list[WorkItem]]]:
    """First occurrence wins; the full membership map is kept for reporting.

    A handful of fiscal notes are shared across bills (same note URL, two bill
    numbers), so per-group coverage has to count memberships, not downloads.
    """
    seen: dict[str, WorkItem] = {}
    memberships: dict[str, list[WorkItem]] = defaultdict(list)
    for item in items:
        memberships[item.url].append(item)
        seen.setdefault(item.url, item)
    return list(seen.values()), memberships


# --------------------------------------------------------------------------
# Polite fetching
# --------------------------------------------------------------------------


class RateLimiter:
    """Global floor on the interval between request STARTS, across threads."""

    def __init__(self, min_interval: float) -> None:
        self._min_interval = min_interval
        self._lock = threading.Lock()
        self._next_at = 0.0

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            wait = max(0.0, self._next_at - now)
            self._next_at = max(now, self._next_at) + self._min_interval
        if wait > 0:
            time.sleep(wait)


class PoliteFetcher:
    """requests-backed fetcher with backoff, rate limiting and a circuit breaker.

    URLs are passed through byte-for-byte. ``requests`` preserves existing
    percent-escapes (its requote_uri leaves %25 alone), which matters because at
    least one JLBC URL only resolves when double-encoded — re-encoding it would
    silently 404.
    """

    def __init__(self, limiter: RateLimiter, verbose: bool = False) -> None:
        import requests

        self._requests = requests
        self._limiter = limiter
        self._verbose = verbose
        self._local = threading.local()
        self._lock = threading.Lock()
        self._consecutive_rejections = 0

    def _session(self) -> Any:
        session = getattr(self._local, "session", None)
        if session is None:
            session = self._requests.Session()
            session.headers.update(
                {"User-Agent": USER_AGENT, "Accept": "application/pdf,*/*"}
            )
            self._local.session = session
        return session

    def _note_outcome(self, rejected: bool) -> None:
        with self._lock:
            if rejected:
                self._consecutive_rejections += 1
                hit_limit = (
                    self._consecutive_rejections >= ABORT_AFTER_CONSECUTIVE_REJECTIONS
                )
            else:
                self._consecutive_rejections = 0
                hit_limit = False
        if hit_limit:
            raise ServerPushbackError(
                f"{ABORT_AFTER_CONSECUTIVE_REJECTIONS} consecutive rate-limit / "
                "connection failures — the origin is refusing us. Aborting rather "
                "than hammering a state government server. Re-run later; the cache "
                "is resumable."
            )

    def __call__(self, url: str) -> bytes:
        last_error: Exception | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            self._limiter.acquire()
            try:
                response = self._session().get(
                    url, timeout=REQUEST_TIMEOUT, allow_redirects=True
                )
            except self._requests.exceptions.RequestException as exc:
                last_error = exc
                # Connection-level failures count toward the circuit breaker:
                # a refused connection is the other way a server says "stop".
                self._note_outcome(rejected=True)
                if attempt == MAX_ATTEMPTS:
                    raise
                self._backoff(attempt, None)
                continue

            status = response.status_code
            if status == 429 or status >= 500:
                last_error = RuntimeError(f"HTTP {status}")
                self._note_outcome(rejected=True)
                if attempt == MAX_ATTEMPTS:
                    raise RuntimeError(f"HTTP {status} after {MAX_ATTEMPTS} attempts")
                self._backoff(attempt, response)
                continue

            if status >= 400:
                # 404/403 are real, permanent answers about this URL — not
                # pushback. Don't retry, don't trip the breaker.
                self._note_outcome(rejected=False)
                raise RuntimeError(f"HTTP {status}")

            self._note_outcome(rejected=False)
            body = response.content
            if not body.startswith(b"%PDF"):
                raise NotAPdfError(
                    f"body is not a PDF (first bytes {body[:16]!r}, "
                    f"{len(body)} bytes, content-type "
                    f"{response.headers.get('Content-Type', '?')})"
                )
            return body

        raise last_error or RuntimeError("unreachable")

    def _backoff(self, attempt: int, response: Any) -> None:
        delay = min(60.0, 2.0**attempt) + random.uniform(0, 1.0)
        if response is not None:
            retry_after = response.headers.get("Retry-After")
            if retry_after and retry_after.isdigit():
                delay = max(delay, min(120.0, float(retry_after)))
        if self._verbose:
            print(f"  backoff {delay:.1f}s (attempt {attempt})", file=sys.stderr)
        time.sleep(delay)


# --------------------------------------------------------------------------
# Cache with batched manifest writes
# --------------------------------------------------------------------------


class BatchedDownloadCache(DownloadCache):
    """DownloadCache that defers manifest writes to a periodic flush.

    The base class rewrites the whole YAML manifest after EVERY download. At 386
    entries that's free; at 7,900 it is quadratic — the manifest grows past a
    megabyte and gets serialized thousands of times, costing more wall-clock
    than the downloads. Deferring keeps the on-disk format byte-identical while
    making the run linear. Every exit path flushes, so an abort loses at most
    MANIFEST_FLUSH_EVERY entries' worth of bookkeeping (the FILES are already on
    disk; a lost entry just means one re-download next run).
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._defer = False
        super().__init__(*args, **kwargs)

    def _save_manifest(self) -> None:
        if self._defer:
            return
        super()._save_manifest()

    def begin_batch(self) -> None:
        self._defer = True

    def flush(self) -> None:
        was = self._defer
        self._defer = False
        try:
            super()._save_manifest()
        finally:
            self._defer = was


# --------------------------------------------------------------------------
# Run
# --------------------------------------------------------------------------


@dataclass
class RunStats:
    attempted: int = 0
    downloaded: int = 0
    skipped: int = 0
    failed: int = 0
    bytes_added: int = 0
    failures: list[dict[str, Any]] = field(default_factory=list)
    downloaded_urls: list[str] = field(default_factory=list)


def run(
    items: list[WorkItem],
    *,
    cache: BatchedDownloadCache,
    fetcher: PoliteFetcher,
    concurrency: int,
    stats: RunStats,
    stop_event: threading.Event,
) -> None:
    from concurrent.futures import ThreadPoolExecutor

    cache_lock = threading.Lock()
    counter_lock = threading.Lock()
    started = time.monotonic()
    processed = 0
    since_flush = 0

    def record_progress() -> None:
        nonlocal processed, since_flush
        processed += 1
        since_flush += 1
        if since_flush >= MANIFEST_FLUSH_EVERY:
            since_flush = 0
            with cache_lock:
                cache.flush()
        if processed % PROGRESS_EVERY == 0:
            elapsed = time.monotonic() - started
            rate = processed / elapsed if elapsed else 0.0
            remaining = len(items) - processed
            eta = remaining / rate if rate else 0.0
            print(
                f"[{processed}/{len(items)}] "
                f"{stats.downloaded} new, {stats.skipped} cached, "
                f"{stats.failed} failed, "
                f"{stats.bytes_added / 1e6:.0f} MB, "
                f"{rate:.1f} files/s, ETA {eta / 60:.0f} min",
                flush=True,
            )

    def work(item: WorkItem) -> None:
        if stop_event.is_set():
            return
        try:
            # has() is a manifest lookup + stat — cheap, and the whole reason a
            # re-run after an abort costs seconds instead of hours.
            with cache_lock:
                already = cache.has(item.url)
            if already:
                with counter_lock:
                    stats.skipped += 1
                    record_progress()
                return

            body = fetcher(item.url)
            with cache_lock:
                path = cache_store(cache, item.url, body)
            with counter_lock:
                stats.downloaded += 1
                stats.bytes_added += len(body)
                stats.downloaded_urls.append(item.url)
                record_progress()
            del path
        except ServerPushbackError as exc:
            stop_event.set()
            with counter_lock:
                stats.failures.append(
                    {
                        "url": item.url,
                        "group": item.group,
                        "kind": item.kind,
                        "label": item.label,
                        "error": str(exc),
                        "error_type": "ServerPushback",
                    }
                )
                stats.failed += 1
            print(f"\nABORTING: {exc}\n", file=sys.stderr, flush=True)
        except Exception as exc:  # noqa: BLE001 - every failure is data
            with counter_lock:
                stats.failed += 1
                stats.failures.append(
                    {
                        "url": item.url,
                        "group": item.group,
                        "kind": item.kind,
                        "label": item.label,
                        "host": urlsplit(item.url).netloc,
                        "error": str(exc),
                        "error_type": type(exc).__name__,
                    }
                )
                record_progress()

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        list(pool.map(work, items))

    stats.attempted = processed
    cache.flush()


def cache_store(cache: BatchedDownloadCache, url: str, body: bytes) -> Path:
    """Write already-fetched bytes through DownloadCache's own code path.

    We fetch in worker threads (for concurrency) but must not let the cache's
    single-shot fetcher run the request again — so the bytes are handed back via
    a one-shot fetcher closure. The layout, manifest entry shape and sha naming
    stay entirely the base class's business.
    """
    original = cache._fetcher  # noqa: SLF001
    cache._fetcher = lambda _url: body  # noqa: SLF001
    try:
        return cache.fetch(url)
    finally:
        cache._fetcher = original  # noqa: SLF001


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------


def verify_pdf_magic(cache: DownloadCache, urls: list[str], sample: int) -> tuple[int, list[str]]:
    """Spot-check cached files really start with %PDF."""
    checked = urls if sample <= 0 or sample >= len(urls) else random.sample(urls, sample)
    bad: list[str] = []
    for url in checked:
        entry = cache._entries.get(url)  # noqa: SLF001
        if not entry:
            continue
        path = cache.root / entry["relative_path"]
        try:
            with path.open("rb") as handle:
                if handle.read(4) != b"%PDF":
                    bad.append(url)
        except OSError:
            bad.append(url)
    return len(checked), bad


def coverage_table(
    memberships: dict[str, list[WorkItem]], cache: DownloadCache
) -> list[tuple[str, int, int]]:
    per_group_total: Counter[str] = Counter()
    per_group_have: Counter[str] = Counter()
    for url, members in memberships.items():
        have = cache.has(url)
        for member in members:
            per_group_total[member.group] += 1
            if have:
                per_group_have[member.group] += 1
    return [
        (group, per_group_have[group], total)
        for group, total in sorted(per_group_total.items())
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--books", action="store_true", help="fetch JLBC book PDFs")
    parser.add_argument(
        "--fiscal-notes", action="store_true", help="fetch fiscal-note PDFs"
    )
    parser.add_argument("--all", action="store_true", help="both sources")
    parser.add_argument("--limit", type=int, default=0, help="cap URLs (0 = no cap)")
    parser.add_argument("--dry-run", action="store_true", help="plan only, no network")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument(
        "--min-interval",
        type=float,
        default=0.15,
        help="minimum seconds between request starts, globally (politeness floor)",
    )
    parser.add_argument("--verify-sample", type=int, default=200)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    do_books = args.books or args.all
    do_notes = args.fiscal_notes or args.all
    if not (do_books or do_notes):
        parser.error("pick at least one of --books / --fiscal-notes / --all")
    if args.concurrency < 1 or args.concurrency > 6:
        parser.error("--concurrency must be between 1 and 6 (politeness cap)")

    raw: list[WorkItem] = []
    if do_books:
        raw += book_work_items()
    if do_notes:
        raw += fiscal_note_work_items()
    items, memberships = dedupe(raw)
    if args.limit:
        items = items[: args.limit]

    cache = BatchedDownloadCache(CACHE_ROOT)
    cache.begin_batch()

    already = sum(1 for item in items if cache.has(item.url))
    print(
        f"work list: {len(raw)} references -> {len(items)} unique URLs "
        f"({already} already cached, {len(items) - already} to fetch)",
        flush=True,
    )
    by_host = Counter(urlsplit(i.url).netloc for i in items)
    print(f"hosts: {dict(by_host)}", flush=True)

    if args.dry_run:
        for group, have, total in coverage_table(memberships, cache):
            print(f"  {group:24s} {have}/{total}")
        return 0

    stats = RunStats()
    stop_event = threading.Event()
    limiter = RateLimiter(args.min_interval)
    fetcher = PoliteFetcher(limiter, verbose=args.verbose)

    def handle_sigint(_sig: int, _frame: Any) -> None:
        print("\ninterrupted — finishing in-flight requests, flushing manifest",
              file=sys.stderr, flush=True)
        stop_event.set()

    signal.signal(signal.SIGINT, handle_sigint)

    started = time.time()
    try:
        run(
            items,
            cache=cache,
            fetcher=fetcher,
            concurrency=args.concurrency,
            stats=stats,
            stop_event=stop_event,
        )
    finally:
        cache.flush()
    elapsed = time.time() - started

    checked, bad = verify_pdf_magic(cache, stats.downloaded_urls, args.verify_sample)

    FAILURES_PATH.write_text(
        json.dumps(
            {
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "attempted": stats.attempted,
                "downloaded": stats.downloaded,
                "skipped_already_cached": stats.skipped,
                "failed": stats.failed,
                "failures": sorted(stats.failures, key=lambda f: f["url"]),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print("\n" + "=" * 68)
    print(f"attempted            {stats.attempted}")
    print(f"newly downloaded     {stats.downloaded}")
    print(f"already cached       {stats.skipped}")
    print(f"failed               {stats.failed}")
    print(f"bytes added          {stats.bytes_added / 1e6:.1f} MB")
    print(f"elapsed              {elapsed / 60:.1f} min")
    print(f"pdf magic-byte check {checked} sampled, {len(bad)} not PDFs")
    for url in bad[:10]:
        print(f"  NOT A PDF: {url}")

    if stats.failures:
        grouped: Counter[tuple[str, str]] = Counter(
            (f.get("host", "?"), f["error"][:60]) for f in stats.failures
        )
        print("\nfailures by host + error:")
        for (host, error), count in grouped.most_common():
            print(f"  {count:5d}  {host}  {error}")
        print(f"\nfull list: {FAILURES_PATH}")

    print("\nper-group coverage (cached/expected):")
    for group, have, total in coverage_table(memberships, cache):
        flag = "" if have == total else "  <-- INCOMPLETE"
        print(f"  {group:24s} {have}/{total}{flag}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
