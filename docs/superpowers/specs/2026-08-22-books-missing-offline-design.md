# Books-missing offline detection — design

**Date:** 2026-08-22 · **Status:** DRAFT, not built · **Scope:** `app/routes/` only

## Problem (STATUS provenance)

STATUS.md, "Whole-report links" § known limits: *"`app/routes/books_missing.py` has
the identical dead-offline-branch hole found in item 2 above — its 'Add a JLBC book'
panel will report an empty gap it never measured when the network is down. Out of
scope here; it deserves its own fix."*

With WiFi off, `GET /api/books/missing` reports `online: true` and an empty probed
gap. The Upload page's book card then says **"Every edition through FY 2027 is
here."** — a confident wrong answer manufactured by a network failure, on an app
verified to cold-start offline. Worse, that answer is **written into the 12-hour
cache**, so it stays wrong for the rest of the day after the network comes back.

## Evidence

- `app/routes/books.py:65-78` — `HttpProber.head` catches `requests.RequestException`
  and returns `False`. It never raises.
- `ingest/book_discovery.py:249-258` — `_first_live` catches every exception per rung
  and continues; `:235-240` — when no rung answers, `_plan_by_probing` raises
  `DiscoveryError`, the **same** signal as "JLBC has not published this edition".
- `app/routes/books_missing.py:236-240` — `except DiscoveryError: continue` treats
  that as "not published"; `:241-247` — the `except Exception` offline branch is
  therefore **dead code** for the real prober (nothing on the network path raises
  through to it). `:287-288` — the poisoned payload is cached (`online` stayed true).
- The fixed sibling: `app/routes/book_formats.py:111-165` (`_NetworkWatch`) counts
  `head_info`'s `(None, None)` "host never answered" apart from `(404, None)` "host
  said no"; `:239-263` runs the offline test AFTER the confirm requests and never
  writes the cache on an outage. This is the house pattern.
- The existing offline test, `tests/test_books_missing.py:195-229`, monkeypatches
  `plan_edition` to raise `OSError` — a shape production cannot produce. It passes
  against code with no working offline handling, the exact failure STATUS records
  for book_formats' original offline test.
- **Webapp needs no change — verified.** `webapp/src/pages/upload/BookFamilyPanel.tsx:227`
  gates the "Every edition through FY X is here." sentence on `check.online`, and
  `:249-257` already renders `reason` when `online` is false. The server contract
  (`online` / `reason` / cached answer) is unchanged by this design.

## Design (smallest correct change)

Adopt the `_NetworkWatch` mechanism. The serving/caching contract in
`check_missing` is already right (`books_missing.py:265-272` serves the last good
answer with the plain-English reason; `:287-288` skips the cache write when
offline) — **only the signal feeding `online` is broken.** So the fix is upstream
detection, not a new contract.

1. **Hoist `_NetworkWatch` out of `book_formats.py` into `app/routes/books.py`** as
   `NetworkWatch`, byte-identical behavior, next to the `HttpProber` it decorates.
   `book_formats.py` imports it from there. No circularity: `books.py` imports
   neither sibling (its imports are `ingest.*` + `app.routes.upload`), while both
   siblings already import from `books.py`. (The "two files, two helper sets"
   comment at `book_formats.py:49-53` is about the **stateful cache helpers**
   hardwired to a filename; the watch is a stateless per-request decorator, and two
   drifting copies of "was that a real no?" is the disagreement shape STATUS warns
   about.) A local copy in `books_missing.py` is the fallback if the hoist proves
   noisy — see open questions.
2. **`check_missing` wraps its prober once** and evaluates the counters **per
   lookahead year, after each `plan_edition` call** (i.e. after the confirm
   requests — the order that was the whole book_formats fix, `book_formats.py:239`).
   Snapshot the counters before the call; if that year produced `unreachable > 0`
   **and** `answered == 0`, the year was never measured: set `online = False`, keep
   the existing reason sentence, `break`. A genuine `DiscoveryError` with answered
   rungs stays what it is today — "not published, a normal answer".
3. **Never cache a payload any part of which went unmeasured:** the write condition
   becomes `online and watch.unreachable == 0` (partial mid-check outages return
   their answer but are not remembered — same rule as `book_formats.py:268-280`).
4. The **never-answered signal is observed entirely inside the watch**, via
   `head_info` — no change to `ingest/book_discovery.py`. `_first_live` calls
   `prober.head(url)`; the watch's `head` answers out of its own `head_info` and
   records which kind of "no" it was. `plan_edition` being catalog-first is safe
   here: a catalog hit makes zero network calls, contributes zero to both counters,
   and correctly never trips the offline rule.

SKETCH — to be run and corrected, not transcribed (per the repo's plan-code rule):

```python
watch = NetworkWatch(prober)                     # once, before the lookahead loop
...
before = (watch.answered, watch.unreachable)
try:
    plan = plan_edition(family, year, prober=watch)
    ...
except DiscoveryError:
    plan = None                                  # fall through to the year check
answered_d = watch.answered - before[0]
unreachable_d = watch.unreachable - before[1]
if unreachable_d and not answered_d:
    online, reason = False, "Couldn't reach azjlbc.gov to check for new editions. ..."
    break
if plan is None or not _has_year_specific_url(plan):
    continue
...
if online and not watch.unreachable:
    _write_cache(payload)
```

The `except Exception` branch at `:241` stays (a prober bug must still degrade, not
500) but stops being the load-bearing offline path.

## Exact files to change

- `app/routes/books.py` — `_NetworkWatch` moves here as `NetworkWatch` (verbatim).
- `app/routes/book_formats.py` — delete the local class; import from `books`.
- `app/routes/books_missing.py` — wrap the prober; per-year counter check; cache
  write condition; reason wording unchanged.
- `tests/test_books_missing.py` — replace the naive offline test and extend the
  fakes (below). `tests/test_book_formats_route.py` should pass unedited.

**Nothing under `ingest/`, `chunking/`, `retrieval/`, `citation/` or the prompt**
— by CLAUDE.md's rule, no eval run is required or meaningful for this change.

## Test plan (no real network anywhere — the suite convention already forbids it)

1. **Offline test in the PRODUCTION shape.** A fake prober whose `head_info`
   returns `(None, None)` and whose `head` returns `False` — never raising
   requests exceptions upward — driven through the REAL `plan_edition` ladder (no
   monkeypatching it away). Assert `online: false`, the reason names azjlbc.gov,
   and the cached gap survives. Verify it fails against today's code first.
2. **Cache-not-poisoned.** Same fake, no pre-existing cache: assert
   `book-check.json` is not written; then with a fresh cache present, assert its
   bytes are unchanged after an offline check.
3. **Online path unchanged.** `_NeverPublished` gains
   `head_info → (404, None)`; every existing green test stays green with identical
   payloads (a 404-for-everything host is "answered", never "offline").
4. **Mixed case.** A fake that answers 404 for one year's rungs then `(None, None)`
   for the next: first year reads not-published, `online` flips false, nothing
   cached.
5. Mutation checks: drop the per-year rule (offline test reds); revert the cache
   condition to bare `if online` (test 4 reds); delete the watch wrap (tests 1–2
   red, 3 green).

Fakes must implement `head_info` — the watch consults it, and an `AttributeError`
would be miscounted as unreachable. State this in the test file.

## UX consequences (plain English)

**Before, WiFi off:** the Upload page's Baseline/Appropriations cards say "Every
edition through FY 2027 is here." — and keep saying it for up to 12 hours after
the WiFi returns, because the wrong answer was remembered. **After:** the cards
show the existing red note — "Couldn't reach azjlbc.gov to check for new editions
(…). Showing what we knew last time." — over the last good list, and the moment
the network is back the next check is live. No new screens, no new copy: the
webapp already renders this state; it has just never been reachable in production.
Nothing else on the page changes; add/preview of a named edition still works the
way it does today.

## Risks + what NOT to do

- **Do not narrow `DiscoveryError` handling or make the ladder raise on network
  errors** — that changes `ingest/` (eval-rerun rule) and breaks `walk_edition`'s
  tolerate-a-404 design.
- **Do not merge the two caches or cache helpers** — `book_formats.py:49-53`
  records why that reports an empty gap it never measured.
- **Do not test the offline path by making the prober raise** — that is the
  recorded false-passing shape this spec exists to retire.
- Hoisting risk: the watch must move verbatim; `test_book_formats_route.py` is the
  guard that its behavior did not drift.
- A rolling-`/budget/` hit while half-offline still counts as "answered"; the
  existing `_has_year_specific_url` guard (`books_missing.py:106-118`) already
  refuses to offer on its strength — unchanged here.

## Open questions

1. Hoist vs. local copy: recommended hoist touches `book_formats.py`; if review
   prefers zero risk to the shipped panel, a private copy in `books_missing.py`
   with a cross-file drift-guard test is acceptable.
2. Should an offline check with **no cache at all** (fresh install, WiFi off) still
   list catalog-derived missing editions with `online: false`? Current code says
   yes (step 1 needs no network); this spec keeps that, but it has never been
   looked at in a browser.
