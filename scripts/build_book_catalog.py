"""Build data/jlbc-book-catalog.json from the vendored URL harvest.

⚠ **If you re-run this and commit the result, re-run
`scripts/repair_supplier_titles.py` immediately afterwards.**

This script reproduces the harvest's titles faithfully, and **the harvest's
titles are wrong for 430 rows**. It scraped JLBC's index page and, where a
row had no link text, picked up the *previous* row's label: `05app/bar.pdf`
is the Board of Barbers and the harvest records it as *"Agriculture, Arizona
Department of"*. That name then became the document's title in the corpus
and the name shown beside a citation — provenance naming the wrong source.

The committed catalog therefore has titles from TWO layers: this builder,
then `repair_supplier_titles.py`, which overwrites them from the corpus's
own content-derived `documents.json`. `test_the_builder_reproduces_the_
committed_catalog` excludes `title` for exactly that reason and still checks
every other field, so a hand-edited URL fails it as before. The regression
guard for the defect itself is `test_no_edition_has_two_agencies_sharing_a_
title` — the harvest's signature is two rows in one edition carrying one
title, and that test fails if this builder's output is committed unrepaired.

The catalog answers one question the ingest UI has to answer before it can
offer anything: *which JLBC books exist, and where do their pieces live?*

WHY a catalog rather than deriving URLs on demand — this is the design
decision the whole "Add a JLBC book" feature turns on, and it was reached by
auditing the website mockup's own harvest:

  * There are ~6 different URL naming eras across FY1984–FY2027
    (`/FY1997AppropRpt.pdf`, `/05app/`, `/12book1/`, `/25Baseline/`,
    `/budget/`, …). No single pattern generates them.
  * Per-agency filenames are NOT derivable. The agency roster shifts every
    year, codes are irregular (`axs`, `sba`, `doa-cfs`), and casing is
    inconsistent *within* a single edition.
  * The mockup's own build rule is "never guess URLs — verify 200 or don't
    ship". A guessed URL that 404s isn't a small bug here: it's a queued job
    that fails overnight on somebody else's machine.

So the harvest — a real crawl that verified every URL — becomes the source
of truth, and probing (ingest/book_discovery.py) is reserved for editions
published AFTER the snapshot.

Run:  uv run python scripts/build_book_catalog.py
Out:  data/jlbc-book-catalog.json (generated, committed)
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "data" / "jlbc-book-sources"
OUT = ROOT / "data" / "jlbc-book-catalog.json"

# --- pinned expectations ----------------------------------------------------
# The harvest is a frozen snapshot, so these are facts, not estimates. They
# are asserted at build time: if a future re-harvest changes them, the build
# fails loudly instead of silently shipping a catalog with editions missing.
EXPECTED_EDITIONS = {"approps": 41, "baseline": 21}

# Ranges where an edition has per-agency/section children worth ingesting.
# Older books exist only as one giant scanned PDF with no child pages.
CHILDREN_FROM = {"approps": 2005, "baseline": 2012}
# Ranges where BOTH a linked-TOC and a single-file format exist.
BOTH_FORMATS_FROM = {"approps": 2011, "baseline": 2012}

KNOWN_GAPS = [
    "FY2000 and FY2001 Appropriations Reports are absent from azjlbc.gov "
    "(the harvest found books for every other year FY1984-FY2026).",
    "FY2027 Appropriations Report is expected but was not published at "
    "harvest time (2026-06-16); ingest/book_discovery.py's probe ladder "
    "picks it up once it appears.",
]

# --- host normalization -----------------------------------------------------
# Two dead legacy hosts serve byte-identical paths under azjlbc.gov. Three
# records in the harvest still carry the second one; both are rewritten here
# so no dead host can reach a download.
DEAD_HOSTS = (
    ("http://www.azleg.gov/jlbc/", "https://www.azjlbc.gov/"),
    ("https://www.azleg.gov/jlbc/", "https://www.azjlbc.gov/"),
    ("http://www.azleg.state.az.us/jlbc/", "https://www.azjlbc.gov/"),
    ("https://www.azleg.state.az.us/jlbc/", "https://www.azjlbc.gov/"),
)

# Supplements are not the report. Ported verbatim from the mockup's
# search.js::isSupplement.
IS_SUPPLEMENT = re.compile(
    r"slide|comparison|spreadsheet|presentation|revenue estimate|forecast|\(summary\)",
    re.I,
)
IS_LINKED = re.compile(
    r"(with links|individual links|table of contents|apprpttoc|links\.pdf)", re.I
)
IS_SINGLE = re.compile(r"(single ?file|approprpt)", re.I)

# The 9 agency-index PDFs that leaked into summary-corpus.json as fake
# "sections". They ARE the per-agency index — useful as index-URL evidence,
# wrong as content.
AGENCY_INDEX_TITLE = re.compile(r"INDIVIDUAL AGENCY INDEX", re.I)
AGENCY_INDEX_URL = re.compile(r"agencyindex|agency_index", re.I)


def normalize_url(url: str) -> str:
    """Rewrite dead hosts. Never re-encodes — one AFR URL only works
    double-encoded, and 'cleaning' it would break it."""
    for dead, live in DEAD_HOSTS:
        if url.lower().startswith(dead.lower()):
            return live + url[len(dead):]
    return url


def family_of(record: dict) -> str:
    doc_type = (record.get("doc_type") or "").lower()
    return "baseline" if "baseline" in doc_type else "approps"


def edition_key(family: str, year: int) -> str:
    return f"{family}-fy{year}"


def _load(name: str) -> list[dict]:
    return json.loads((SOURCES / name).read_text(encoding="utf-8"))


def build_catalog() -> dict[str, Any]:
    books = _load("live-books.json")
    agencies = _load("agency-corpus.json")
    summaries = _load("summary-corpus.json")
    toc_urls = _toc_urls()

    editions: dict[str, dict[str, Any]] = {}

    def edition(family: str, year: int) -> dict[str, Any]:
        key = edition_key(family, year)
        if key not in editions:
            editions[key] = {
                "family": family,
                "fiscal_year": year,
                "single_file_url": None,
                "linked_toc_url": None,
                "agency_index_url": None,
                "per_agency": [],
                "summary_sections": [],
                "ingestable": False,
                # True when this edition's whole-book URLs live under the
                # ROLLING /budget/ directory, which JLBC repurposes each
                # cycle. The URLs are real and verified — they just stop
                # pointing at THIS edition once the next one publishes, so
                # discovery has to re-check rather than trust them blindly.
                "rolling": False,
                "era_note": "",
            }
        return editions[key]

    # --- whole books -> the two "open the full report" formats ---------------
    # WHY the scope filter: live-books.json also carries page-keyed sections
    # (`10app/544.pdf`), indexes (`04app/index.pdf`) and one-off analyses
    # (`FY09budgetshortfall.pdf`). Without it the loose fallback below happily
    # offers one of those as "the full FY 2010 Appropriations Report". The
    # mockup's own reportFormats() filters `scope === 'book'` first.
    whole_books = [b for b in books if (b.get("scope") or "") == "book"]

    for record in whole_books:
        family, year = family_of(record), record["fiscal_year"]
        entry = edition(family, year)
        url = normalize_url(record["url"])
        blob = f"{record.get('title', '')} {url}"
        if IS_SUPPLEMENT.search(blob):
            continue
        if IS_LINKED.search(blob):
            entry["linked_toc_url"] = entry["linked_toc_url"] or url
        elif IS_SINGLE.search(blob):
            entry["single_file_url"] = entry["single_file_url"] or url

    # Approps' "single file" is often titled just "FY YYYY Appropriations
    # Report" with no format word at all, so the mockup falls back to "the
    # first non-supplement, non-TOC book". That fallback is too loose to ship
    # as an ingest target: applied to the raw harvest it names
    # `09optionsdoc/FY09budgetshortfall.pdf` as the FY 2009 Appropriations
    # Report, `10app/544.pdf` as the FY 2010 one, and `04app/index.pdf` as
    # FY 2004's. Those are a different analysis, a page-keyed section, and an
    # index. `_is_credible_single_file` rejects them, which is why "both
    # formats" starts at FY2011 for approps rather than FY2004.
    for record in whole_books:
        family, year = family_of(record), record["fiscal_year"]
        entry = edition(family, year)
        if entry["single_file_url"]:
            continue
        url = normalize_url(record["url"])
        blob = f"{record.get('title', '')} {url}"
        if IS_SUPPLEMENT.search(blob) or re.search(r"links|toc", blob, re.I):
            continue
        if _is_credible_single_file(url, entry["linked_toc_url"]):
            entry["single_file_url"] = url

    # Editions still need an entry even when only non-book records mention
    # them, so the catalog's year coverage doesn't silently shrink.
    for record in books:
        edition(family_of(record), record["fiscal_year"])

    # --- linked-TOC URLs from the authoritative list ------------------------
    # These are the 37 TOC URLs the harvest verified, plus the idx2 filenames
    # that encode the same mapping. They win over the title-regex guess above.
    for url in toc_urls:
        family, year = _classify_toc(url)
        if family and year:
            edition(family, year)["linked_toc_url"] = url

    # --- per-agency children ------------------------------------------------
    for record in agencies:
        family, year = family_of(record), record["fiscal_year"]
        edition(family, year)["per_agency"].append({
            "code": record.get("agency") or _code_from_id(record["id"]),
            "url": normalize_url(record["url"]),
            "title": record.get("title") or "",
        })

    # --- summary sections + the agency-index evidence hiding among them -----
    for record in summaries:
        family, year = family_of(record), record["fiscal_year"]
        entry = edition(family, year)
        url = normalize_url(record["url"])
        title = record.get("title") or ""
        if AGENCY_INDEX_TITLE.search(title) or AGENCY_INDEX_URL.search(url):
            # Evidence, not content: this is where the edition's per-agency
            # index lives, which is what walk_edition needs to find children
            # for an edition the harvest didn't cover.
            entry["agency_index_url"] = entry["agency_index_url"] or url
            continue
        entry["summary_sections"].append({
            "name": Path(url).stem.lower(),
            "url": url,
            "title": title,
        })

    _dedupe_and_sort(editions)
    _stamp_ingestable(editions)
    _validate(editions)

    return {
        "snapshot_date": "2026-06-16",
        "source": "data/jlbc-book-sources (vendored mockup harvest)",
        "known_gaps": KNOWN_GAPS,
        "children_from": CHILDREN_FROM,
        "both_formats_from": BOTH_FORMATS_FROM,
        "editions": dict(sorted(editions.items())),
    }


# --- helpers ----------------------------------------------------------------


def _toc_urls() -> list[str]:
    """The verified TOC URLs, from both sources the harvest recorded them in.

    `toc-urls.txt` is the explicit list; the `idx2/` filenames encode the same
    URLs with `__` standing in for `/`. Reading both is belt-and-braces — they
    agree today, and a disagreement would mean the harvest is inconsistent.
    """
    urls = {
        u.strip() for u in (SOURCES / "toc-urls.txt").read_text().splitlines()
        if u.strip()
    }
    for line in (SOURCES / "idx-manifest.txt").read_text().splitlines():
        line = line.strip()
        if line.startswith("idx2/"):
            urls.add("https://www.azjlbc.gov/" + line[len("idx2/"):].replace("__", "/"))
    return sorted(normalize_url(u) for u in urls)


def _classify_toc(url: str) -> tuple[str | None, int | None]:
    """Read (family, fiscal year) out of a TOC URL's directory.

    Deliberately returns (None, None) for `/budget/*`: that directory is a
    ROLLING location JLBC repurposes each year, so `/budget/apprpttoc.pdf`
    carries no year and would silently attach to the wrong edition. Discovery
    handles those with an explicit guard instead.
    """
    path = url.split("azjlbc.gov/", 1)[-1].lower()
    if path.startswith("budget/"):
        return None, None
    directory = path.split("/", 1)[0]
    two_digit = re.match(r"^(\d{2})(app|ar|baseline|book\d*)$", directory)
    if two_digit:
        year = 2000 + int(two_digit.group(1))
        family = "baseline" if "baseline" in directory or "book" in directory else "approps"
        return family, year
    return None, None


def _is_credible_single_file(url: str, linked_toc_url: str | None) -> bool:
    """Could this URL plausibly BE the whole report?

    Three rejections, each from a real mis-classification in the harvest:
      * `index.pdf` — an index of the report, not the report.
      * an all-digits stem (`544.pdf`) — JLBC's page-keyed section files.
      * a directory the edition doesn't otherwise use — `09optionsdoc/` next
        to a TOC in `09app/` is a different publication that happens to carry
        the same fiscal year.
    """
    stem = Path(url).stem.lower()
    if stem == "index" or stem.isdigit():
        return False
    if linked_toc_url:
        directory = url.rsplit("/", 1)[0].lower()
        if directory != linked_toc_url.rsplit("/", 1)[0].lower():
            return False
    return True


def _code_from_id(record_id: str) -> str:
    """`ag-13baseline-sba` -> `sba`."""
    parts = record_id.split("-", 2)
    return parts[2] if len(parts) > 2 else record_id


def _dedupe_and_sort(editions: dict[str, dict]) -> None:
    """Collapse case-only URL duplicates. IIS is case-insensitive and the
    harvest reflects that — `.../AXS.pdf` and `.../axs.pdf` are one file, and
    ingesting both would double-count the document."""
    for entry in editions.values():
        for field, key in (("per_agency", "code"), ("summary_sections", "name")):
            seen: dict[str, dict] = {}
            for item in entry[field]:
                seen.setdefault(item["url"].lower(), item)
            entry[field] = sorted(seen.values(), key=lambda d: (d[key], d["url"]))


def _stamp_ingestable(editions: dict[str, dict]) -> None:
    for entry in editions.values():
        family, year = entry["family"], entry["fiscal_year"]
        has_children = bool(entry["per_agency"] or entry["summary_sections"])
        entry["ingestable"] = has_children
        entry["rolling"] = any(
            "/budget/" in (url or "").lower()
            for url in (entry["single_file_url"], entry["linked_toc_url"])
        )
        entry["era_note"] = _era_note(family, year, has_children)
        if entry["rolling"]:
            entry["era_note"] += (
                " Published under the rolling /budget/ directory, which JLBC "
                "repurposes each cycle — verify before re-fetching."
            )


def _era_note(family: str, year: int, has_children: bool) -> str:
    if has_children:
        if year >= BOTH_FORMATS_FROM[family]:
            return "Per-agency pages and summary sections; both full-report formats."
        return "Per-agency pages and summary sections; one full-report format."
    return (
        f"Whole book only — JLBC did not publish per-agency pages for "
        f"{family} editions before FY{CHILDREN_FROM[family]}."
    )


def _validate(editions: dict[str, dict]) -> None:
    counts: dict[str, int] = defaultdict(int)
    for entry in editions.values():
        counts[entry["family"]] += 1
    for family, expected in EXPECTED_EDITIONS.items():
        if counts[family] != expected:
            raise SystemExit(
                f"Expected {expected} {family} editions, found {counts[family]}. "
                "The vendored harvest changed — re-pin EXPECTED_EDITIONS only "
                "after confirming the new count is correct."
            )
    for key, entry in editions.items():
        for item in entry["per_agency"] + entry["summary_sections"]:
            if "azleg" in item["url"].lower():
                raise SystemExit(f"{key} still points at a dead host: {item['url']}")


def main() -> int:
    catalog = build_catalog()
    OUT.write_text(
        json.dumps(catalog, indent=1, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )
    editions = catalog["editions"]
    ingestable = sum(1 for e in editions.values() if e["ingestable"])
    print(
        f"{len(editions)} editions ({ingestable} ingestable) -> {OUT}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
