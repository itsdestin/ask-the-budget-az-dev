"""Spec T10: the book panel answers "what has JLBC published that we don't have?"

Measured before this change: 62 editions offered in the picker, **0** of them
usefully addable -- 38 ingestable and every one already in the corpus, 24 not
ingestable and offered anyway.

No test here touches the network. The prober is injected.
"""
import json

import pytest

from app.routes import books_missing as BM
from ingest.book_discovery import DiscoveryError


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    return tmp_path


def _documents(monkeypatch, urls):
    monkeypatch.setattr(
        BM, "load_documents", lambda: {f"d{i}": {"source_url": u} for i, u in enumerate(urls)}
    )


# --- reading the corpus's editions off source_url --------------------------


def test_all_four_url_conventions_are_recognised(data_dir, monkeypatch):
    """The failure this guards against is silent and expensive.

    Measured against the live corpus by mutating the regex: dropping `app`
    and `book1` takes approps from 22 editions to 14 and baseline from 16 to
    15. All NINE lost editions (approps FY2005-2012, baseline FY2012) are
    marked ingestable in the catalog, so each would be offered as "not in
    your corpus" when the corpus holds it -- nine books to add that are
    already here.
    """
    _documents(
        monkeypatch,
        [
            "https://www.azjlbc.gov/26ar/508.pdf",        # approps, modern
            "https://www.azjlbc.gov/12app/260.pdf",       # approps, pre-FY2013
            "https://www.azjlbc.gov/27baseline/353.pdf",  # baseline, modern
            "https://www.azjlbc.gov/12book1/353.pdf",     # baseline, FY2012 only
        ],
    )
    assert BM.corpus_editions() == {
        "approps": {2026, 2012},
        "baseline": {2027, 2012},
    }


def test_a_document_with_no_source_url_is_skipped(data_dir, monkeypatch):
    """5 of the 7,434 documents in the live corpus have no source_url."""
    monkeypatch.setattr(BM, "load_documents", lambda: {"d0": {}, "d1": {"source_url": None}})
    assert BM.corpus_editions() == {"approps": set(), "baseline": set()}


def test_fiscal_note_urls_are_not_mistaken_for_book_editions(data_dir, monkeypatch):
    _documents(monkeypatch, ["https://www.azjlbc.gov/fiscal/hb2001.pdf"])
    assert BM.corpus_editions() == {"approps": set(), "baseline": set()}


# --- what the check reports ------------------------------------------------


class _NeverPublished:
    """Every probe says the edition does not exist yet — the common case.

    `head_info` answers `(404, None)` — a REAL "no", the host is reachable
    and simply has nothing there. Required (not optional) once `check_missing`
    wraps its prober in `NetworkWatch`: `NetworkWatch.head()` calls
    `self.head_info(url)` on ITSELF, which then calls the wrapped prober's
    `head_info` — never its `head`. Without this method several EXISTING
    tests in this file (the ones that exercise the real probing ladder rather
    than monkeypatching `plan_edition`) would trip an `AttributeError` inside
    `NetworkWatch.head_info`'s own `except Exception:`, which miscounts a
    missing method on a TEST FAKE as "the network is unreachable" — the exact
    false-signal correction (c) exists to rule out.
    """

    def head(self, url):
        return False

    def head_info(self, url):
        return 404, None

    def get(self, url):
        raise AssertionError("check_missing must not download anything")


class _Exploding:
    """A prober that raises past its own `head`/`head_info` — a code BUG in
    the prober itself, not a quiet network failure. Kept distinct from the
    silent-failure fakes below: production's real `HttpProber` never raises
    (see `app/routes/books.py`), so this fixture is for the wide
    `except Exception` catch-all that stays in `check_missing` as a defensive
    backstop, not for proving the offline branch.
    """

    def head(self, url):
        raise OSError("network is down")

    def head_info(self, url):
        raise OSError("network is down")

    def get(self, url):
        raise OSError("network is down")


def test_an_edition_already_in_the_corpus_is_never_offered(data_dir, monkeypatch):
    _documents(monkeypatch, ["https://www.azjlbc.gov/26ar/508.pdf"])
    monkeypatch.setattr(
        BM,
        "list_editions",
        lambda: [
            {
                "family": "approps", "fiscal_year": 2026, "ingestable": True,
                "era_note": "", "document_count": 139,
            }
        ],
    )
    out = BM.check_missing(_NeverPublished())
    assert out["missing"] == []
    assert {"family": "approps", "fiscal_year": 2026} in out["present"]


def test_an_ingestable_edition_the_corpus_lacks_is_offered(data_dir, monkeypatch):
    _documents(monkeypatch, ["https://www.azjlbc.gov/26ar/508.pdf"])
    monkeypatch.setattr(
        BM,
        "list_editions",
        lambda: [
            {
                "family": "baseline", "fiscal_year": 2020, "ingestable": True,
                "era_note": "", "document_count": 131,
            }
        ],
    )
    out = BM.check_missing(_NeverPublished())
    assert out["missing"] == [
        {"family": "baseline", "fiscal_year": 2020, "document_count": 131, "source": "catalog"}
    ]


def test_a_NON_ingestable_edition_is_reported_but_never_as_missing(data_dir, monkeypatch):
    """Spec T10: shown greyed with its era_note, and Add is NOT offered.
    "FY 1984 was never published as per-agency PDFs" is a fact worth stating,
    but it is not something anybody can add.
    """
    _documents(monkeypatch, ["https://www.azjlbc.gov/26ar/508.pdf"])
    note = "Whole book only — JLBC did not publish per-agency pages before FY2005."
    monkeypatch.setattr(
        BM,
        "list_editions",
        lambda: [
            {
                "family": "approps", "fiscal_year": 1984, "ingestable": False,
                "era_note": note, "document_count": 1,
            }
        ],
    )
    out = BM.check_missing(_NeverPublished())
    assert out["missing"] == []
    assert out["unavailable"] == [
        {"family": "approps", "fiscal_year": 1984, "era_note": note}
    ]


def test_an_edition_published_since_the_catalog_snapshot_is_found_by_probing(
    data_dir, monkeypatch
):
    """The case the panel exists for. The FY2027 Appropriations Report is not
    in the 2026-06-16 catalog snapshot, and neither is anything JLBC
    publishes from now on.
    """
    _documents(monkeypatch, ["https://www.azjlbc.gov/26ar/508.pdf"])
    monkeypatch.setattr(BM, "list_editions", lambda: [])

    def _plan(family, fiscal_year, *, prober):
        if (family, fiscal_year) == ("approps", 2027):
            # A realistic plan, not a bare object(): an edition is only
            # offered when the probe found it at a YEAR-SPECIFIC url, and a
            # stub with no urls at all cannot exercise that. `_Plan` is
            # defined at the foot of this file, which is fine -- the name
            # resolves when the test runs, not when it is defined.
            return _Plan(
                agency_index="https://www.azjlbc.gov/27ar/agencyindex.pdf",
                linked_toc="https://www.azjlbc.gov/27ar/apprpttoc.pdf",
            )
        raise DiscoveryError("not published")

    monkeypatch.setattr(BM, "plan_edition", _plan)
    out = BM.check_missing(_NeverPublished())
    assert out["missing"] == [
        {"family": "approps", "fiscal_year": 2027, "document_count": None, "source": "probed"}
    ]


def test_an_unpublished_year_is_a_normal_answer_not_an_error(data_dir, monkeypatch):
    _documents(monkeypatch, ["https://www.azjlbc.gov/26ar/508.pdf"])
    monkeypatch.setattr(BM, "list_editions", lambda: [])
    monkeypatch.setattr(
        BM,
        "plan_edition",
        lambda *a, **k: (_ for _ in ()).throw(DiscoveryError("not published")),
    )
    out = BM.check_missing(_NeverPublished())
    assert out["missing"] == []
    assert out["online"] is True
    assert out["reason"] is None


# --- offline behaviour -----------------------------------------------------
#
# 🔴 THE OLD TEST HERE WAS THE RECORDED FALSE-PASSING SHAPE (design doc
# evidence section). It monkeypatched `plan_edition` to raise `OSError`
# directly — a shape production cannot produce, since `HttpProber.head`
# (app/routes/books.py) catches `requests.RequestException` and returns
# `False`, and never raises. It passed against code with NO working offline
# handling: `ingest/book_discovery.py::_first_live` catches every exception
# per rung and `plan_edition` raises `DiscoveryError` for both "not published"
# and "couldn't ask" — so a prober that merely returns False/(-, -) silently
# (never raising) drove the *live* codepath, and the old test never touched
# it. Replaced below by fakes that reproduce the real shape, driven through
# the REAL `plan_edition` ladder — nothing here monkeypatches it away.


class _SilentHost:
    """The PRODUCTION shape of a dead network: never raises, never answers.

    `app/routes/books.py::HttpProber.head` catches `requests.RequestException`
    and returns `False`; `HttpProber.head_info` catches it and returns
    `(None, None)`. Neither method EVER raises upward — that is exactly what
    makes the offline branch dead code without `NetworkWatch`: `_first_live`
    sees every rung answer `False` and `plan_edition` raises `DiscoveryError`,
    the identical signal it raises for "JLBC has not published this edition".
    """

    def head(self, url):
        return False

    def head_info(self, url):
        return None, None

    def get(self, url):
        raise AssertionError("check_missing must not download anything")


def test_offline_is_detected_via_the_production_shape(data_dir, monkeypatch):
    """The headline test (spec test-plan item 1). Reproduces production: a
    prober whose `head`/`head_info` returns False/(None, None) and never
    raises, driven through the REAL discovery ladder (no monkeypatched
    `plan_edition`) — this app is deliberately offline-capable and was
    verified cold-starting with WiFi disconnected, so a book panel reporting
    "everything is already here" on a dead network is a regression against
    that.
    """
    _documents(monkeypatch, ["https://www.azjlbc.gov/26ar/508.pdf"])
    monkeypatch.setattr(BM, "list_editions", lambda: [])
    (data_dir / BM.CACHE_FILENAME).write_text(
        json.dumps(
            {
                "checked_at": "2020-01-01T00:00:00+00:00",
                "online": True,
                "reason": None,
                "missing": [
                    {"family": "approps", "fiscal_year": 2027,
                     "document_count": None, "source": "probed"}
                ],
                "present": [],
                "unavailable": [],
            }
        ),
        encoding="utf-8",
    )

    out = BM.check_missing(_SilentHost())

    assert out["online"] is False
    assert "azjlbc.gov" in out["reason"]
    # The known gap survives — a network failure must not read as "nothing missing".
    assert out["missing"][0]["fiscal_year"] == 2027


def test_an_offline_check_with_no_prior_cache_writes_nothing(data_dir, monkeypatch):
    """Spec test-plan item 2, half A. With current (buggy) code `online`
    never flips False, so the check falsely believes the corpus is complete
    and writes THAT wrong, empty-gap payload to the cache — the exact
    poisoning defect this design fixes.
    """
    _documents(monkeypatch, ["https://www.azjlbc.gov/26ar/508.pdf"])
    monkeypatch.setattr(BM, "list_editions", lambda: [])

    BM.check_missing(_SilentHost())

    assert not (data_dir / BM.CACHE_FILENAME).exists()


def test_an_offline_check_leaves_an_existing_cache_byte_for_byte_untouched(
    data_dir, monkeypatch
):
    """Spec test-plan item 2, half B. A stale-but-good cache must survive an
    offline look unmodified — not merely "still readable", but the exact
    bytes, since a rewrite with a wrongly-empty gap is precisely what stayed
    wrong for the rest of the day in the recorded defect.
    """
    _documents(monkeypatch, ["https://www.azjlbc.gov/26ar/508.pdf"])
    monkeypatch.setattr(BM, "list_editions", lambda: [])
    cache_path = data_dir / BM.CACHE_FILENAME
    cache_path.write_text(
        json.dumps(
            {
                "checked_at": "2020-01-01T00:00:00+00:00",
                "online": True,
                "reason": None,
                "missing": [
                    {"family": "approps", "fiscal_year": 2027,
                     "document_count": None, "source": "probed"}
                ],
                "present": [],
                "unavailable": [],
            }
        ),
        encoding="utf-8",
    )
    before = cache_path.read_bytes()

    BM.check_missing(_SilentHost())

    assert cache_path.read_bytes() == before


def test_a_mixed_outage_flips_online_false_partway_and_caches_nothing(
    data_dir, monkeypatch
):
    """Spec test-plan item 4. One lookahead year is genuinely reachable (404
    everywhere — "not published", a normal answer); the NEXT year's rungs go
    silent. `online` must flip False partway through the loop, and the whole
    payload — including the first year's honest "not published" reading —
    must not be cached, since part of it went unmeasured.
    """
    _documents(monkeypatch, ["https://www.azjlbc.gov/26ar/508.pdf"])
    monkeypatch.setattr(BM, "list_editions", lambda: [])

    class _ReachableFor2027ThenSilent:
        """404 (a real, reachable "no") for every FY2027 candidate; silent
        for every FY2028 candidate. `{yy}` for 2027 is "27" and never
        appears in a 2028 URL (`{yy}` "28"), so the substring check cleanly
        separates the two years including the rolling `/budget/` rung.
        """

        def head_info(self, url):
            if "27" in url:
                return 404, None
            return None, None

        def head(self, url):
            status, _ = self.head_info(url)
            return status is not None and status < 400

    out = BM.check_missing(_ReachableFor2027ThenSilent())

    assert out["online"] is False
    assert "azjlbc.gov" in out["reason"]
    # FY2027 was read honestly as "not published" (never silently claimed
    # missing) before the outage was detected.
    assert all(m["fiscal_year"] != 2027 for m in out["missing"])
    assert not (data_dir / BM.CACHE_FILENAME).exists()


def test_a_partial_outage_that_recovers_still_skips_the_cache_write(
    data_dir, monkeypatch
):
    """The subtler half of spec design step 3: `online and watch.unreachable
    == 0`, not bare `online`. One single rung inside FY2027's ladder goes
    silent, but that year still receives plenty of real answers (so its OWN
    per-year check does not trip and `online` never flips False anywhere in
    the loop) — yet part of the picture genuinely went unmeasured, so the
    12-hour cache must still be skipped. `if online:` alone would write it.
    """
    _documents(monkeypatch, ["https://www.azjlbc.gov/26ar/508.pdf"])
    monkeypatch.setattr(BM, "list_editions", lambda: [])

    class _OneSilentRungOtherwiseFine:
        """Every candidate answers 404 (reachable) EXCEPT the one literal,
        non-year-parameterized rolling TOC rung
        (`https://www.azjlbc.gov/budget/apprpttoc.pdf`), which goes silent.
        That single rung is not enough to trip FY2027's own per-year check
        (plenty of other rungs in the same year answered for real), so
        `online` stays True end to end — but the outage still happened.
        """

        def head_info(self, url):
            if url == "https://www.azjlbc.gov/budget/apprpttoc.pdf":
                return None, None
            return 404, None

        def head(self, url):
            status, _ = self.head_info(url)
            return status is not None and status < 400

    out = BM.check_missing(_OneSilentRungOtherwiseFine())

    assert out["online"] is True
    assert not (data_dir / BM.CACHE_FILENAME).exists()


def test_a_fresh_answer_is_cached_and_reused_without_probing(data_dir, monkeypatch):
    _documents(monkeypatch, ["https://www.azjlbc.gov/26ar/508.pdf"])
    monkeypatch.setattr(BM, "list_editions", lambda: [])
    calls = []

    def _plan(family, fiscal_year, *, prober):
        calls.append((family, fiscal_year))
        raise DiscoveryError("not published")

    monkeypatch.setattr(BM, "plan_edition", _plan)

    BM.check_missing(_NeverPublished())
    first = len(calls)
    assert first > 0

    BM.check_missing(_NeverPublished())
    assert len(calls) == first, "a cached answer must not probe azjlbc.gov again"

    BM.check_missing(_NeverPublished(), refresh=True)
    assert len(calls) > first, "refresh=1 must actually look again"


def test_a_corrupt_cache_costs_a_round_trip_not_the_page(data_dir, monkeypatch):
    _documents(monkeypatch, ["https://www.azjlbc.gov/26ar/508.pdf"])
    monkeypatch.setattr(BM, "list_editions", lambda: [])
    monkeypatch.setattr(
        BM,
        "plan_edition",
        lambda *a, **k: (_ for _ in ()).throw(DiscoveryError("not published")),
    )
    (data_dir / BM.CACHE_FILENAME).write_text("null", encoding="utf-8")

    out = BM.check_missing(_NeverPublished())
    assert out["online"] is True


# --- the rolling directory (found by running it, 2026-08-13) ---------------


class _Plan:
    def __init__(self, agency_index=None, linked_toc=None, single_file=None):
        self.agency_index_url = agency_index
        self.linked_toc_url = linked_toc
        self.single_file_url = single_file


def test_an_edition_found_ONLY_in_the_rolling_folder_is_not_offered(
    data_dir, monkeypatch
):
    """🔴 Live defect, not a hypothetical.

    JLBC keeps a rolling `/budget/` directory that it repoints every cycle, and
    the probe ladders include it. On 2026-08-13 the live check offered "FY 2028
    Appropriations Report" on the strength of `/budget/apprpttoc.pdf` alone --
    a URL that at that moment held the FY 2027 book. FY2027 itself was found
    properly, on three year-specific /27ar/ URLs.

    Offering an edition that does not exist is exactly the noise T10 removes.
    """
    _documents(monkeypatch, ["https://www.azjlbc.gov/26ar/508.pdf"])
    monkeypatch.setattr(BM, "list_editions", lambda: [])
    monkeypatch.setattr(
        BM,
        "plan_edition",
        lambda family, fiscal_year, *, prober: _Plan(
            linked_toc="https://www.azjlbc.gov/budget/apprpttoc.pdf"
        ),
    )
    out = BM.check_missing(_NeverPublished())
    assert out["missing"] == []


def test_an_edition_with_a_year_specific_url_IS_offered(data_dir, monkeypatch):
    """The FY2027 Appropriations Report, as actually found live: three
    /27ar/ URLs, none of them rolling."""
    _documents(monkeypatch, ["https://www.azjlbc.gov/26ar/508.pdf"])
    monkeypatch.setattr(BM, "list_editions", lambda: [])

    def _plan(family, fiscal_year, *, prober):
        if (family, fiscal_year) != ("approps", 2027):
            raise DiscoveryError("not published")
        return _Plan(
            agency_index="https://www.azjlbc.gov/27ar/agencyindex.pdf",
            linked_toc="https://www.azjlbc.gov/27ar/apprpttoc.pdf",
            single_file="https://www.azjlbc.gov/27ar/fy2027approprpt.pdf",
        )

    monkeypatch.setattr(BM, "plan_edition", _plan)
    out = BM.check_missing(_NeverPublished())
    assert [(m["family"], m["fiscal_year"]) for m in out["missing"]] == [("approps", 2027)]


# --- ONE watch across the whole lookahead loop (correction a) --------------
#
# `check_missing` wraps its prober in ONE `NetworkWatch` for the whole
# lookahead loop, where `book_formats.py` builds a fresh one per edition.
# That is only safe because `NetworkWatch` deliberately does not memoise an
# UNREACHABLE result (retry is cheap) — but it DOES memoise a REAL answer,
# and JLBC's rolling `/budget/apprpttoc.pdf` approps-TOC rung is the one URL
# in the whole ladder that is IDENTICAL across fiscal years. A year that
# reuses it from cache contributes ZERO counter movement for that one rung.
# These tests pin that this can never be misread as "the network went down
# partway through" — the per-year rule is `unreachable_d and not
# answered_d`, so a rung contributing (0, 0) can never trip it on its own.


def test_a_cached_answer_produces_zero_counter_movement_on_reuse():
    """`NetworkWatch` unit-level: the exact mechanism correction (a) is about.
    A second `head_info` call for a URL already answered must move neither
    counter — that is what makes reusing it across fiscal years safe.
    """
    from app.routes.books import NetworkWatch

    class _Recorder:
        def __init__(self):
            self.calls = 0

        def head_info(self, url):
            self.calls += 1
            return 200, 999

    watch = NetworkWatch(_Recorder())
    watch.head_info("https://www.azjlbc.gov/budget/apprpttoc.pdf")
    before = (watch.answered, watch.unreachable)

    watch.head_info("https://www.azjlbc.gov/budget/apprpttoc.pdf")

    assert (watch.answered, watch.unreachable) == before
    assert watch._inner.calls == 1, "a cache hit must cost no real request"


def test_a_rolling_url_answered_in_one_year_and_reused_in_the_next_is_not_offline(
    data_dir, monkeypatch
):
    """End to end, via `check_missing`, through the REAL ladder. FY2027's
    approps TOC ladder finds the rolling `/budget/apprpttoc.pdf` rung live;
    FY2028 tries the identical URL and gets it back from `NetworkWatch`'s own
    cache with zero counter movement for that one rung — every OTHER FY2028
    rung is a genuinely fresh, reachable 404. The reused rung must not be
    misread as "offline"; it is inert, not a source of unreachability.
    """
    _documents(monkeypatch, ["https://www.azjlbc.gov/26ar/508.pdf"])
    monkeypatch.setattr(BM, "list_editions", lambda: [])

    rolling = "https://www.azjlbc.gov/budget/apprpttoc.pdf"

    class _RollingLiveEverythingElse404:
        def __init__(self):
            self.calls: list[str] = []

        def head_info(self, url):
            self.calls.append(url)
            if url == rolling:
                return 200, 12345
            return 404, None

        def head(self, url):
            status, _ = self.head_info(url)
            return status is not None and status < 400

    prober = _RollingLiveEverythingElse404()
    out = BM.check_missing(prober)

    assert out["online"] is True
    # The rolling rung was asked once for FY2027 and never asked again for
    # FY2028 — that second year's ladder answer came from the watch's own
    # cache, which is the whole property under test.
    assert prober.calls.count(rolling) == 1
