"""Download JLBC agency-index PDFs for as many doc-years as are published.

JLBC's URL convention (verified for FY26 + FY27, presumed for prior years):

  https://www.azjlbc.gov/<YY>baseline/agencyindex.pdf   — Baseline Book
  https://www.azjlbc.gov/<YY>ar/agencyindex.pdf         — Appropriations Report

We try a wide range and skip 404s. The agency-index files are tiny (~150 KB
each) so the cost of being broad is low.

Output: samples/raw-pdfs/jlbc-{baseline,approps}-fy{YYYY}-agency-index.pdf

These feed scripts/build_agency_catalog.py which merges them into the canonical
catalog and tracks per-year slug stability.
"""

from __future__ import annotations

import sys
import time
import urllib.request
from pathlib import Path

OUT_DIR = Path("samples/raw-pdfs")

# Years to attempt. JLBC publishes baselines a year ahead of the FY they
# cover, so a "FY 2027 Baseline" exists in 27baseline/. Approps reports
# are similar (26ar/ covers FY 2026 enacted budget).
BASELINE_YEARS = list(range(15, 28))  # FY15 through FY27 (publishing-year suffix 15-27)
APPROPS_YEARS = list(range(15, 27))   # FY15 through FY26 (no FY27 approps yet)


def fy(yy: int) -> int:
    return 2000 + yy


def url_baseline(yy: int) -> str:
    return f"https://www.azjlbc.gov/{yy:02d}baseline/agencyindex.pdf"


def url_approps(yy: int) -> str:
    return f"https://www.azjlbc.gov/{yy:02d}ar/agencyindex.pdf"


def fetch(url: str, dest: Path) -> str:
    """Returns 'ok', 'skip-existing', '404', or 'err: <msg>'."""
    if dest.exists() and dest.stat().st_size > 1000:
        return "skip-existing"
    req = urllib.request.Request(url, headers={"User-Agent": "jlbc-search/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read()
            if not data.startswith(b"%PDF"):
                return "err: not-a-pdf"
            dest.write_bytes(data)
            return "ok"
    except urllib.error.HTTPError as e:
        return f"{e.code}"
    except Exception as e:
        return f"err: {e}"


def main(argv: list[str]) -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    plan: list[tuple[str, str, Path]] = []
    for yy in BASELINE_YEARS:
        plan.append((
            url_baseline(yy),
            "baseline",
            OUT_DIR / f"jlbc-baseline-fy{fy(yy)}-agency-index.pdf",
        ))
    for yy in APPROPS_YEARS:
        plan.append((
            url_approps(yy),
            "approps",
            OUT_DIR / f"jlbc-approps-fy{fy(yy)}-agency-index.pdf",
        ))

    print(f"attempting {len(plan)} downloads")
    ok = 0
    not_found = 0
    skipped = 0
    errors = 0
    for url, kind, dest in plan:
        result = fetch(url, dest)
        tag = result if len(result) <= 25 else result[:25] + "..."
        print(f"  {kind:8s} {dest.name:55s} {tag}")
        if result == "ok":
            ok += 1
        elif result == "skip-existing":
            skipped += 1
        elif result == "404":
            not_found += 1
        else:
            errors += 1
        time.sleep(0.2)  # be polite

    print()
    print(f"ok={ok} skipped={skipped} 404={not_found} errors={errors}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
