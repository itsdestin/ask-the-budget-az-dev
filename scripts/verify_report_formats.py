"""Re-check every whole-report URL the app actually serves.

    uv run python scripts/verify_report_formats.py [--full]

WHAT IT READS, AND WHY THAT CHANGED. Until 2026-08-16 this script parsed a
`REPORT_FORMATS` constant out of `webapp/src/reportFamilies.ts` with a regex.
That constant is gone: the table is now `data/report-formats.json` merged with
the administrator's approvals at `<data_dir>/report-formats.json`, and this
script reads the MERGED result through `store.report_formats.load`. That
matters — an edition approved on the Admin page is exactly the kind that has
never been checked by anyone but the person who approved it, so a verifier
blind to the overlay would report a clean sweep over only the rows that
shipped. Any row the overlay could not read is printed before the check rather
than silently skipped.

WHY THIS EXISTS. This table is what puts a link behind the "Full report"
button on the Budget Documents page. A wrong or dead URL there is a false
provenance claim (Invariant 1), and nothing else in the repo would notice: the
webapp suite runs in jsdom with no network, and the ingest side's own edition
catalog (`data/jlbc-book-catalog.json`) is deliberately tolerant of a 404
because it feeds a probe ladder. So the only check that means anything is
fetching the file and looking at it, which is exactly what this does.

WHY IT IS A SCRIPT AND NOT A TEST. It needs the public internet and downloads
~1.5 GB in `--full` mode. A test that reaches azjlbc.gov would fail on a
disconnected office machine and on every fresh clone, which is worse than no
test at all.

EVERY MODE RE-RUNS THE YEAR RULE FIRST, offline and free — see
`year_mismatches`. Reachability is not the dangerous failure; a live report for
the wrong fiscal year is, and it is the one an HTTP 200 cannot see.

Default mode checks reachability and type only (HEAD, cheap, ~40 requests).
`--full` downloads each PDF and reads its first pages, printing the page count
and opening text so a human can confirm the file is the report it claims to
be. Note that three Baseline single files (FY2017-FY2019) are scans with NO
text layer — an empty `head:` for those is expected and is not a failure; they
were verified by rendering their cover pages to images on 2026-08-16.
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

import requests

# Importable because this script runs from the repo root under `uv run`, the
# same way scripts/build_book_catalog.py is imported by ingest/book_discovery.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from store.report_formats import (  # noqa: E402  (after the path insert)
    YEARLESS_BY_DESIGN,
    load,
    names_its_year,
)

# The same browser User-Agent `ingest/cache.py` sends, and for the same
# measured reason: azjlbc.gov's WAF rejects `python-requests` outright.
UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )
}

SOURCE = "the shipped table plus the administrator's approvals"


def rows() -> list[tuple[str, str, str]]:
    """(edition key, format name, url) for every curated URL, sorted by key.

    Reads the MERGED table, so this checks what the app actually serves rather
    than only what shipped in the bundle. Problems with the administrator's
    file are printed rather than swallowed: a row this script cannot read is a
    row it also cannot check, and reporting "all ok" over a table that quietly
    lost entries is the silent-success shape this repo keeps getting bitten by.
    """
    table, problems = load()
    for problem in problems:
        print(f"note: {problem}")
    out: list[tuple[str, str, str]] = []
    for key, formats in sorted(table.items()):
        for kind, url in (("single", formats.single_file), ("toc", formats.linked_toc)):
            if url:
                out.append((key, kind, url))
    return out


def year_mismatches(targets: list[tuple[str, str, str]]) -> list[tuple[str, str, str]]:
    """Every row whose address does not name the fiscal year it is filed under.

    🔴 THE ONE DEFECT A `200 OK` CANNOT DETECT. A copied row with the year in
    the key bumped and the URL left alone gives a live, downloadable, WRONG
    report behind a button labelled "Full report" — a false provenance claim
    (Invariant 1). `tests/test_report_formats_data.py` runs this rule over the
    COMMITTED file, but it cannot see the administrator's approvals, which are
    a file on a shared drive that no test on any machine reads. Before this,
    an approved wrong-year link was warned about once on the save screen and
    then never re-checked by anything, ever.

    It runs BEFORE the network check and needs no network at all, so it still
    reports on a disconnected machine — which is when a verifier is most likely
    to be run and least likely to finish.

    `YEARLESS_BY_DESIGN` is honoured: exactly one published address carries no
    year (JLBC put the FY2023 Appropriations Report in the undated /budget/
    directory) and it is verified by download.
    """
    out = []
    for key, kind, url in targets:
        year = key.rpartition(":")[2]
        if not year.isdigit() or url in YEARLESS_BY_DESIGN:
            continue
        if not names_its_year(url, int(year)):
            out.append((key, kind, url))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--full",
        action="store_true",
        help="download each PDF and read its first pages (slow, ~1.5 GB)",
    )
    args = ap.parse_args()

    targets = rows()
    if not targets:
        # A read that finds nothing must FAIL, not report a clean sweep. The
        # committed table can no longer be reflowed out of a regex's shape, but
        # it can still go missing — it is a data file, and `load()` degrades to
        # an empty table rather than raising, by design. "0 URLs, 0 problems"
        # is the silent-success shape this repo keeps getting bitten by.
        print(f"FAIL: read no URLs out of {SOURCE} — is data/report-formats.json there?")
        return 2

    print(f"{len(targets)} curated URLs in {SOURCE}\n")

    wrong_year = year_mismatches(targets)
    if wrong_year:
        print(f"{len(wrong_year)} address(es) do NOT name the year they are filed under:")
        for key, kind, url in wrong_year:
            print(f"WRONG-YEAR {key:32s} {kind:6s} {url}")
        print(
            "  Each of those would download a real report for a DIFFERENT year "
            "behind that edition's Full report button.\n"
        )
    else:
        print("every address names its own fiscal year\n")

    bad = 0
    for key, kind, url in targets:
        try:
            if args.full:
                r = requests.get(url, headers=UA, timeout=300)
            else:
                r = requests.head(url, headers=UA, timeout=60, allow_redirects=True)
            ctype = r.headers.get("content-type", "")
            ok = r.status_code == 200 and "pdf" in ctype.lower()
            detail = f"{r.status_code} {ctype}"
            if ok and args.full:
                import fitz  # imported here so the cheap mode needs no PDF library

                doc = fitz.open(stream=io.BytesIO(r.content), filetype="pdf")
                head = " ".join(
                    " ".join(doc[i].get_text().split())
                    for i in range(min(2, doc.page_count))
                )[:90]
                detail = f"{doc.page_count}pp {len(r.content) / 1e6:.1f}MB head: {head!r}"
                doc.close()
        except Exception as exc:  # noqa: BLE001 - any failure is a finding
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        bad += not ok
        print(f"{'ok  ' if ok else 'FAIL'} {key:32s} {kind:6s} {detail}")
        if not ok:
            print(f"       {url}")

    print(
        f"\n{len(targets) - bad} ok, {bad} failed, "
        f"{len(wrong_year)} wrong-year"
    )
    # A wrong-year row fails the run exactly as a dead one does. It is the more
    # dangerous of the two: a dead link is visibly broken to the analyst, while
    # a wrong-year link downloads cleanly and reads as authoritative.
    return 1 if (bad or wrong_year) else 0


if __name__ == "__main__":
    sys.exit(main())
