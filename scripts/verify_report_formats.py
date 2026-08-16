"""Re-check every whole-report URL in webapp/src/reportFamilies.ts.

    uv run python scripts/verify_report_formats.py [--full]

WHY THIS EXISTS. `REPORT_FORMATS` is what puts a link behind the "Full report"
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
import re
import sys
from pathlib import Path

import requests

# The same browser User-Agent `ingest/cache.py` sends, and for the same
# measured reason: azjlbc.gov's WAF rejects `python-requests` outright.
UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )
}

SOURCE = Path(__file__).resolve().parent.parent / "webapp" / "src" / "reportFamilies.ts"

# One row per curated edition, e.g.
#   "Baseline:2019": { singleFile: "https://…", linkedToc: "https://…" },
ROW = re.compile(
    r'"(?P<key>[^"]+:\d{4})":\s*\{\s*'
    r'singleFile:\s*(?P<single>"[^"]*"|null),\s*'
    r'linkedToc:\s*(?P<toc>"[^"]*"|null)'
)


def rows() -> list[tuple[str, str, str]]:
    """(edition key, format name, url) for every curated URL, in file order."""
    text = SOURCE.read_text(encoding="utf-8")
    out: list[tuple[str, str, str]] = []
    for m in ROW.finditer(text):
        for kind in ("single", "toc"):
            raw = m.group(kind)
            if raw != "null":
                out.append((m.group("key"), kind, raw.strip('"')))
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
        # A parse that finds nothing must FAIL, not report a clean sweep — the
        # regex is pinned to a formatting convention this file could be
        # reflowed out of, and "0 URLs, 0 problems" is the silent-success shape
        # this repo keeps getting bitten by.
        print(f"FAIL: parsed no URLs out of {SOURCE} — has the map's shape changed?")
        return 2

    print(f"{len(targets)} curated URLs in {SOURCE.name}\n")
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

    print(f"\n{len(targets) - bad} ok, {bad} failed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
