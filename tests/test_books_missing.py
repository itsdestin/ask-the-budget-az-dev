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
    """Every probe says the edition does not exist yet — the common case."""

    def head(self, url):
        return False

    def get(self, url):
        raise AssertionError("check_missing must not download anything")


class _Exploding:
    def head(self, url):
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
            return object()
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


def test_a_network_failure_serves_the_last_good_answer_and_says_so(data_dir, monkeypatch):
    """This app is deliberately offline-capable and was verified cold-starting
    with WiFi disconnected. A book panel that hangs on a dead network, or that
    reports an empty gap as "everything is already here", would be a
    regression against that.
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

    def _boom(*a, **k):
        raise OSError("network is down")

    monkeypatch.setattr(BM, "plan_edition", _boom)
    out = BM.check_missing(_Exploding())

    assert out["online"] is False
    assert "azjlbc.gov" in out["reason"]
    # The known gap survives — a network failure must not read as "nothing missing".
    assert out["missing"][0]["fiscal_year"] == 2027


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
