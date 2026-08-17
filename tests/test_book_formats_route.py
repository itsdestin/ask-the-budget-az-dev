"""The pending-edition scan and the admin's approve/correct/check routes.

Spec R3 (which editions are unanswered), R5 (candidates come from the existing
discovery ladder), R6 (a year mismatch is flagged, never refused), R9 (the card
states a real status and a real size), R10 (reads degrade, writes raise).

No test here touches the network or LanceDB: the prober is injected through
`app.state.book_prober` and the app is built with `StubSearchProvider()` and
`ingest_worker=None`.
"""
import json

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.search_provider import StubSearchProvider


class FakeProber:
    """Stands in for HttpProber. Records what was asked."""

    def __init__(self, live: set[str] | None = None, size: int = 47_000_000):
        self.live = live or set()
        self.size = size
        self.asked: list[str] = []

    def head(self, url: str) -> bool:
        # Part of the prober protocol `ingest/book_discovery.py` expects. The
        # scan reaches it only through `head_info` (see `_NetworkWatch`), and
        # this fake keeps the two consistent ON PURPOSE: the real HttpProber
        # answers both from one request, so a fake in which they disagree would
        # test a state that cannot exist.
        self.asked.append(url)
        return url in self.live

    def head_info(self, url: str) -> tuple[int | None, int | None]:
        self.asked.append(url)
        if url in self.live:
            return 200, self.size
        # 404, not an exception: the host answered, it just said no. The scan
        # has to tell that apart from an unreachable host.
        return 404, None

    def get(self, url: str):
        raise AssertionError("the pending scan must never download a book")


def _client(tmp_path, monkeypatch, *, documents, overlay=None, prober=None):
    import app.routes.book_formats as bf
    import app.routes.books_missing as bm
    import store.report_formats as rf
    from harness.settings import reset_settings_cache

    # An isolated share. Without it `data_dir()` resolves to the developer's own
    # 14 GB corpus and `load_settings()` reads its real settings.json, whose
    # `admin_username` would 403 this whole file.
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    reset_settings_cache()

    # 🔴 Patch the name in `books_missing`, NOT `store.documents`.
    # `books_missing.py` does `from store.documents import load_documents`, so
    # the function is already bound into that module's namespace and patching
    # the source module has no effect — the test would silently run against the
    # real 7,566-document corpus and pass or fail for reasons unrelated to it.
    # The same rule applies to everything `book_formats.py` imports by name:
    # patch `bf.save_edition`, never `rf.save_edition`.
    monkeypatch.setattr(bm, "load_documents", lambda: documents)
    monkeypatch.setattr(rf, "overlay_path", lambda: overlay or (tmp_path / "absent.json"))
    monkeypatch.setattr(bf, "_cache_path", lambda: tmp_path / "probe.json")
    rf.reset_cache()
    app = create_app(provider=StubSearchProvider(), ingest_worker=None)
    app.state.book_prober = prober or FakeProber()
    return TestClient(app)


def test_an_edition_the_table_answers_is_not_pending(tmp_path, monkeypatch):
    # FY2026 approps is in the committed table, so holding it must produce no
    # card. On a healthy corpus this is EVERY edition, which is why the panel
    # is empty by default.
    docs = {"d1": {"source_url": "https://www.azjlbc.gov/26ar/axs.pdf"}}
    body = _client(tmp_path, monkeypatch, documents=docs).get("/api/admin/book-formats").json()
    assert body["pending"] == []


def test_an_edition_with_no_entry_becomes_pending_with_its_candidates(tmp_path, monkeypatch):
    docs = {"d1": {"source_url": "https://www.azjlbc.gov/28ar/axs.pdf"}}
    prober = FakeProber(live={
        "https://www.azjlbc.gov/28ar/fy2028approprpt.pdf",
        "https://www.azjlbc.gov/28ar/apprpttoc.pdf",
    })
    body = _client(tmp_path, monkeypatch, documents=docs, prober=prober).get(
        "/api/admin/book-formats"
    ).json()
    row = next(p for p in body["pending"] if p["fiscal_year"] == 2028)
    assert row["family"] == "Appropriations Report"
    single = row["candidates"]["single_file"]
    assert single["url"].endswith("28ar/fy2028approprpt.pdf")
    assert single["names_its_year"] is True
    # R9: the card claims the address responded and how big it is, so both must
    # come off a real request rather than being assumed from the ladder.
    assert single["status"] == 200
    assert single["bytes"] == 47_000_000


def test_a_catalogued_candidate_that_does_not_respond_is_shown_as_not_responding(
    tmp_path, monkeypatch
):
    """🔴 The case that makes the confirm request load-bearing, not decorative.

    It has to use CATALOGUED editions, and finding that out corrected the first
    draft of this test. `plan_edition` is catalog-first: for an edition
    `data/jlbc-book-catalog.json` names, it returns that file's URLs having made
    ZERO network calls — and STATUS.md records that catalog as built to feed a
    ladder that TOLERATES a 404, so it carries addresses nobody ever fetched
    (`budget/fy2027approprpt.pdf` is a live 404 sitting in it today). That is
    where an offered-but-dead link really comes from.

    A PROBED edition cannot produce this shape, because the ladder rung and the
    confirm are now one and the same request — which is the point, not a gap.

    Real fixtures: FY2003 and FY2004 Appropriations Reports are both in the
    committed catalog and in neither the shipped link table nor each other's
    format, so this test breaks if either file changes underneath it.
    """
    docs = {
        "d1": {"source_url": "https://www.azjlbc.gov/03app/260.pdf"},
        "d2": {"source_url": "https://www.azjlbc.gov/04app/260.pdf"},
    }
    prober = FakeProber(live={"https://www.azjlbc.gov/04recbk/recbktoc.pdf"})
    body = _client(tmp_path, monkeypatch, documents=docs, prober=prober).get(
        "/api/admin/book-formats"
    ).json()

    dead = next(p for p in body["pending"] if p["fiscal_year"] == 2003)
    single = dead["candidates"]["single_file"]
    assert single["url"].endswith("03app/Appendix.pdf")   # offered by the catalog
    assert single["status"] == 404 and single["bytes"] is None

    alive = next(p for p in body["pending"] if p["fiscal_year"] == 2004)
    assert alive["candidates"]["linked_toc"]["status"] == 200
    assert alive["candidates"]["linked_toc"]["bytes"] == 47_000_000


def test_a_candidate_from_the_rolling_directory_is_flagged_not_dropped(tmp_path, monkeypatch):
    # /budget/apprpttoc.pdf has no year in it and JLBC republishes it every
    # cycle — verified 2026-08-16 that it currently serves the FY2023 book. It
    # must reach the admin WITH a warning, because it is sometimes the right
    # answer (FY2023's own table of contents genuinely lives there).
    docs = {"d1": {"source_url": "https://www.azjlbc.gov/28ar/axs.pdf"}}
    prober = FakeProber(live={"https://www.azjlbc.gov/budget/apprpttoc.pdf"})
    body = _client(tmp_path, monkeypatch, documents=docs, prober=prober).get(
        "/api/admin/book-formats"
    ).json()
    row = next(p for p in body["pending"] if p["fiscal_year"] == 2028)
    assert row["candidates"]["linked_toc"]["url"].endswith("budget/apprpttoc.pdf")
    assert row["candidates"]["linked_toc"]["names_its_year"] is False


def test_an_unreachable_network_says_so_instead_of_reporting_nothing_pending(tmp_path, monkeypatch):
    # A panel that renders "nothing to add" because the WiFi is off is a
    # confident wrong answer. This app cold-starts offline by design.
    class Dead:
        """A host that never answers.

        BOTH methods fail, which is what a dead network really looks like — the
        first draft of this test defined only `head`, so the scan tripped over
        an `AttributeError` on `head_info` instead of on the network, and would
        have gone on passing if the offline branch were deleted and replaced by
        any other error path.
        """

        def head(self, url):
            raise OSError("no route to host")

        def head_info(self, url):
            raise OSError("no route to host")

    docs = {"d1": {"source_url": "https://www.azjlbc.gov/28ar/axs.pdf"}}
    body = _client(tmp_path, monkeypatch, documents=docs, prober=Dead()).get(
        "/api/admin/book-formats"
    ).json()
    assert body["online"] is False
    assert "azjlbc.gov" in body["reason"]
    # The edition is pending whether or not the network is up — that fact comes
    # from the link table, not from azjlbc.gov — so it must still be listed.
    assert [p["fiscal_year"] for p in body["pending"]] == [2028]


def test_an_unreachable_host_is_not_mistaken_for_an_unpublished_edition(tmp_path, monkeypatch):
    """The real prober never raises, so a raising fake would not prove this.

    `HttpProber.head_info` returns `(None, None)` on a `RequestException` and
    `HttpProber.head` returns `False`; `_first_live` then swallows the lot and
    `plan_edition` raises `DiscoveryError` — the same signal it raises for "JLBC
    never published this". This fake reproduces the PRODUCTION shape rather than
    an exception, which is the shape that would really reach an office machine
    with the network down.
    """
    class Silent:
        def head(self, url):
            return False

        def head_info(self, url):
            return None, None

    docs = {"d1": {"source_url": "https://www.azjlbc.gov/28ar/axs.pdf"}}
    body = _client(tmp_path, monkeypatch, documents=docs, prober=Silent()).get(
        "/api/admin/book-formats"
    ).json()
    assert body["online"] is False


def test_an_edition_jlbc_never_published_is_pending_without_claiming_we_are_offline(
    tmp_path, monkeypatch
):
    """The other side of the discrimination above, and it must not be lost.

    A host that answers 404 to everything IS reachable. Reporting that as
    offline would put a network warning on the admin's page every time an
    edition simply has no whole-report file — which is the normal state for
    Appropriations Reports before FY2011.
    """
    docs = {"d1": {"source_url": "https://www.azjlbc.gov/28ar/axs.pdf"}}
    body = _client(tmp_path, monkeypatch, documents=docs, prober=FakeProber()).get(
        "/api/admin/book-formats"
    ).json()
    assert body["online"] is True
    row = next(p for p in body["pending"] if p["fiscal_year"] == 2028)
    assert row["candidates"] == {"single_file": None, "linked_toc": None}


def test_the_probe_answer_is_cached_so_opening_the_page_twice_costs_one_look(tmp_path, monkeypatch):
    docs = {"d1": {"source_url": "https://www.azjlbc.gov/28ar/axs.pdf"}}
    prober = FakeProber(live={"https://www.azjlbc.gov/28ar/apprpttoc.pdf"})
    client = _client(tmp_path, monkeypatch, documents=docs, prober=prober)
    client.get("/api/admin/book-formats")
    first = len(prober.asked)
    assert first > 0
    client.get("/api/admin/book-formats")
    assert len(prober.asked) == first


def test_refresh_looks_again_even_when_the_cache_is_fresh(tmp_path, monkeypatch):
    # The admin's escape hatch: JLBC publishes a book an hour after the last
    # look, and nobody should have to wait twelve hours to see it offered.
    docs = {"d1": {"source_url": "https://www.azjlbc.gov/28ar/axs.pdf"}}
    prober = FakeProber(live={"https://www.azjlbc.gov/28ar/apprpttoc.pdf"})
    client = _client(tmp_path, monkeypatch, documents=docs, prober=prober)
    client.get("/api/admin/book-formats")
    first = len(prober.asked)
    client.get("/api/admin/book-formats?refresh=true")
    assert len(prober.asked) > first


def test_a_healthy_corpus_asks_the_network_nothing(tmp_path, monkeypatch):
    # The scan is free by construction: it reads documents.json and the merged
    # table, both already cached. Only a PENDING edition costs a request, and
    # on a healthy corpus there are none.
    docs = {"d1": {"source_url": "https://www.azjlbc.gov/26ar/axs.pdf"}}
    prober = FakeProber()
    _client(tmp_path, monkeypatch, documents=docs, prober=prober).get("/api/admin/book-formats")
    assert prober.asked == []


def test_a_newly_ingested_edition_appears_at_once(tmp_path, monkeypatch):
    # 🔴 The reason the cache holds PROBE RESULTS and not the whole answer. A
    # cached payload would keep reporting the old pending list for its full TTL,
    # so an analyst who ingests a book sees an admin page saying nothing is
    # waiting — for up to twelve hours, with nothing on screen explaining why.
    # Noticing the book costs no network, so nothing justifies delaying it.
    import app.routes.books_missing as bm

    docs = {"d1": {"source_url": "https://www.azjlbc.gov/26ar/axs.pdf"}}
    client = _client(tmp_path, monkeypatch, documents=docs)
    assert client.get("/api/admin/book-formats").json()["pending"] == []
    docs["d2"] = {"source_url": "https://www.azjlbc.gov/28ar/axs.pdf"}
    monkeypatch.setattr(bm, "load_documents", lambda: docs)
    body = client.get("/api/admin/book-formats").json()
    assert [p["fiscal_year"] for p in body["pending"]] == [2028]


def test_overlay_problems_reach_the_admin(tmp_path, monkeypatch):
    # The ungated corpus route deliberately drops these; this is where they go.
    overlay = tmp_path / "report-formats.json"
    overlay.write_text(json.dumps({"version": 1, "editions": {"Bogus:2028": {}}}), encoding="utf-8")
    docs = {"d1": {"source_url": "https://www.azjlbc.gov/26ar/axs.pdf"}}
    body = _client(tmp_path, monkeypatch, documents=docs, overlay=overlay).get(
        "/api/admin/book-formats"
    ).json()
    assert body["problems"] and "Bogus:2028" in body["problems"][0]


def test_the_route_is_admin_gated(tmp_path, monkeypatch):
    # The gate is app/identity.py: JLBC_USER vs settings.admin_username, and it
    # is OPEN TO EVERYONE until the admin seat is claimed — so a test that
    # forgets save_settings() passes whether or not the route is gated.
    # Verbatim shape from tests/test_admin_tuning_routes.py.
    from harness.settings import Settings, reset_settings_cache, save_settings

    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("JLBC_USER", "analyst1")
    reset_settings_cache()
    save_settings(Settings(admin_username="Destin"))
    reset_settings_cache()
    try:
        client = TestClient(create_app(provider=StubSearchProvider(), ingest_worker=None))
        assert client.get("/api/admin/book-formats").status_code == 403
        assert client.put("/api/admin/book-formats", json={
            "family": "Baseline", "fiscal_year": 2028,
            "single_file": "https://x/a.pdf", "linked_toc": None,
        }).status_code == 403
        assert client.post("/api/admin/book-formats/check", json={
            "url": "https://x/a.pdf", "fiscal_year": 2028,
        }).status_code == 403
    finally:
        reset_settings_cache()


# --- writing ---------------------------------------------------------------


def test_approving_an_edition_writes_it_and_clears_it_from_pending(tmp_path, monkeypatch):
    overlay = tmp_path / "report-formats.json"
    docs = {"d1": {"source_url": "https://www.azjlbc.gov/28ar/axs.pdf"}}
    client = _client(tmp_path, monkeypatch, documents=docs, overlay=overlay)
    r = client.put("/api/admin/book-formats", json={
        "family": "Appropriations Report", "fiscal_year": 2028,
        "single_file": "https://www.azjlbc.gov/28ar/fy2028approprpt.pdf",
        "linked_toc": "https://www.azjlbc.gov/28ar/apprpttoc.pdf",
    })
    assert r.status_code == 200
    # No ?refresh — the list must be right on an ordinary load, or an admin who
    # presses Approve watches the card sit there and presses it again.
    body = client.get("/api/admin/book-formats").json()
    assert all(p["fiscal_year"] != 2028 for p in body["pending"])


def test_an_already_approved_edition_can_be_corrected(tmp_path, monkeypatch):
    # Approving a wrong link must be recoverable from the app. Without this the
    # only repair is hand-editing JSON on the share — the thing this feature
    # exists to abolish — and the spec's concurrency risk row is unfounded.
    overlay = tmp_path / "report-formats.json"
    docs = {"d1": {"source_url": "https://www.azjlbc.gov/26ar/axs.pdf"}}
    client = _client(tmp_path, monkeypatch, documents=docs, overlay=overlay)
    for url in ("https://www.azjlbc.gov/26ar/wrong.pdf",
                "https://www.azjlbc.gov/26ar/fy2026approprpt.pdf"):
        assert client.put("/api/admin/book-formats", json={
            "family": "Appropriations Report", "fiscal_year": 2026,
            "single_file": url, "linked_toc": None,
        }).status_code == 200
    row = next(
        a for a in client.get("/api/admin/book-formats").json()["approved"]
        if a["fiscal_year"] == 2026 and a["family"] == "Appropriations Report"
    )
    assert row["single_file"].endswith("fy2026approprpt.pdf")
    # R1: the entry REPLACES its shipped row wholesale. The committed table
    # gives FY2026 a linked TOC; this correction did not, so it must be gone
    # rather than surviving from underneath.
    assert row["linked_toc"] is None


def test_marking_one_format_as_never_published_is_accepted(tmp_path, monkeypatch):
    # Appropriations Reports before FY2011 genuinely have no single file. The
    # row must then link straight to the table of contents with no chooser.
    overlay = tmp_path / "report-formats.json"
    docs = {"d1": {"source_url": "https://www.azjlbc.gov/28ar/axs.pdf"}}
    client = _client(tmp_path, monkeypatch, documents=docs, overlay=overlay)
    r = client.put("/api/admin/book-formats", json={
        "family": "Appropriations Report", "fiscal_year": 2028,
        "single_file": None,
        "linked_toc": "https://www.azjlbc.gov/28ar/apprpttoc.pdf",
    })
    assert r.status_code == 200
    saved = json.loads(overlay.read_text(encoding="utf-8"))
    assert saved["editions"]["Appropriations Report:2028"]["single_file"] is None


def test_marking_BOTH_formats_as_never_published_is_refused_in_plain_english(tmp_path, monkeypatch):
    overlay = tmp_path / "report-formats.json"
    docs = {"d1": {"source_url": "https://www.azjlbc.gov/28ar/axs.pdf"}}
    client = _client(tmp_path, monkeypatch, documents=docs, overlay=overlay)
    r = client.put("/api/admin/book-formats", json={
        "family": "Appropriations Report", "fiscal_year": 2028,
        "single_file": None, "linked_toc": None,
    })
    assert r.status_code == 400
    assert "at least one" in r.json()["detail"].lower()


def test_an_unknown_family_is_refused(tmp_path, monkeypatch):
    docs = {"d1": {"source_url": "https://www.azjlbc.gov/28ar/axs.pdf"}}
    client = _client(tmp_path, monkeypatch, documents=docs)
    r = client.put("/api/admin/book-formats", json={
        "family": "Baselines", "fiscal_year": 2028,
        "single_file": "https://x/a.pdf", "linked_toc": None,
    })
    assert r.status_code == 400
    # The store's own sentence, verbatim — one wording per refusal for the whole
    # office. Rewriting it here would give the same refusal two voices.
    assert "Baselines" in r.json()["detail"]


def test_a_failed_save_reaches_the_caller_rather_than_reporting_success(tmp_path, monkeypatch):
    # The read paths degrade on purpose. This one must not: an admin told
    # nothing has no way to learn the approval did not stick.
    #
    # 🔴 Patch `book_formats`, NOT `store.report_formats`. The route does
    # `from store.report_formats import save_edition`, so the name is already
    # bound into the route module and patching the source module changes
    # nothing — the real save would succeed, the route would return 200, and
    # this test would fail for a reason that has nothing to do with what it
    # asserts. Same trap `_client` documents for `load_documents`.
    import app.routes.book_formats as bf

    def boom(*a, **k):
        raise OSError("the share went away")

    docs = {"d1": {"source_url": "https://www.azjlbc.gov/28ar/axs.pdf"}}
    client = _client(tmp_path, monkeypatch, documents=docs)
    monkeypatch.setattr(bf, "save_edition", boom)
    with pytest.raises(OSError):
        client.put("/api/admin/book-formats", json={
            "family": "Appropriations Report", "fiscal_year": 2028,
            "single_file": "https://x/a.pdf", "linked_toc": None,
        })


# --- checking a typed address ----------------------------------------------


def test_checking_a_typed_url_reports_its_year_and_size(tmp_path, monkeypatch):
    docs = {"d1": {"source_url": "https://www.azjlbc.gov/28ar/axs.pdf"}}
    prober = FakeProber(live={"https://www.azjlbc.gov/19AR/FY2019AppropRpt.pdf"})
    client = _client(tmp_path, monkeypatch, documents=docs, prober=prober)
    r = client.post("/api/admin/book-formats/check", json={
        "url": "https://www.azjlbc.gov/19AR/FY2019AppropRpt.pdf", "fiscal_year": 2028,
    })
    # Flagged, not refused (R6) — the admin may be correcting a genuinely
    # year-less address, and one such address really exists.
    assert r.status_code == 200
    assert r.json()["names_its_year"] is False
    assert r.json()["ok"] is True
    assert r.json()["bytes"] == 47_000_000


def test_a_typed_url_that_does_not_respond_says_so(tmp_path, monkeypatch):
    docs = {"d1": {"source_url": "https://www.azjlbc.gov/28ar/axs.pdf"}}
    client = _client(tmp_path, monkeypatch, documents=docs, prober=FakeProber())
    r = client.post("/api/admin/book-formats/check", json={
        "url": "https://www.azjlbc.gov/28ar/nope.pdf", "fiscal_year": 2028,
    }).json()
    assert r["ok"] is False and r["status"] == 404
    assert r["reason"]


def test_a_typed_url_on_a_dead_network_reports_the_network_not_a_404(tmp_path, monkeypatch):
    # "That address answered 404" and "we could not reach anything" send the
    # admin to two different places. Collapsing them would have them editing a
    # correct URL while the WiFi is off.
    class Dead:
        def head(self, url):
            raise OSError("no route to host")

        def head_info(self, url):
            raise OSError("no route to host")

    docs = {"d1": {"source_url": "https://www.azjlbc.gov/26ar/axs.pdf"}}
    client = _client(tmp_path, monkeypatch, documents=docs, prober=Dead())
    r = client.post("/api/admin/book-formats/check", json={
        "url": "https://www.azjlbc.gov/28ar/x.pdf", "fiscal_year": 2028,
    }).json()
    assert r["ok"] is False
    assert r["status"] is None
    assert "didn't respond" in r["reason"]


# --- HttpProber.head_info --------------------------------------------------


def test_head_info_prefers_the_range_total_over_a_one_byte_content_length():
    """The 405 fallback asks for one byte, so Content-Length lies about size.

    A card reporting a 47 MB Appropriations Report as "1 byte" would fire
    exactly the "this is visibly the wrong file" alarm R9 reserves for real
    trouble — every time IIS refuses a HEAD.
    """
    from app.routes.books import _content_size

    assert _content_size({"Content-Range": "bytes 0-0/49312768", "Content-Length": "1"}) == 49_312_768
    assert _content_size({"Content-Length": "49312768"}) == 49_312_768
    # An unknown size must read as unknown, never as zero.
    assert _content_size({}) is None
    assert _content_size({"Content-Length": "chunked"}) is None


def test_head_falls_back_to_a_ranged_get_only_on_405(monkeypatch):
    """Pins the behaviour a refactor into `head_info` would have quietly changed.

    `head()` must NOT fetch a body on a 404. One book edition performs ~130 of
    these checks against files that are megabytes each, so widening the fallback
    to `>= 400` would download a whole missing report to learn it is missing.
    Nothing else in tests/ drives this path.
    """
    import requests

    from app.routes.books import HttpProber

    calls: list[str] = []

    class Reply:
        def __init__(self, status):
            self.status_code = status
            self.headers = {}

        def close(self):
            pass

    def fake_head(url, **kw):
        calls.append("head")
        return Reply(404 if "missing" in url else 405)

    def fake_get(url, **kw):
        calls.append("get")
        assert kw.get("headers", {}).get("Range") == "bytes=0-0", (
            "the fallback must ask for one byte, not a whole book"
        )
        return Reply(200)

    monkeypatch.setattr(requests, "head", fake_head)
    monkeypatch.setattr(requests, "get", fake_get)

    assert HttpProber().head("https://x/missing.pdf") is False
    assert calls == ["head"]

    calls.clear()
    assert HttpProber().head("https://x/iis.pdf") is True
    assert calls == ["head", "get"]
