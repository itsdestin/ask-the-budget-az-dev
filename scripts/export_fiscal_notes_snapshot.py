"""One-time export: vendored mockup session cache -> JSON snapshot.

The fiscal notes PAGE ships in Plan 2 backed by this frozen snapshot;
Plan 3 replaces the data source with the live corpus + refresh scraper.

WHY the parse logic is COPIED and not imported: the vendored generator
`webapp/reference/fiscal-notes-build/build.py` does all of its parsing in
module-level top-level code (no `main()`, no `if __name__ == "__main__"`
guard), and its last two lines WRITE `webapp/reference/subpage-fiscal-notes.html`.
`import build` would therefore rewrite a read-only vendored file as a side
effect. So the 3 parse pieces below (PAIR, spaced, the per-file row loop)
plus the display helpers (ch, ordinal, leg_session) are transcribed verbatim
from build.py lines 15-46 — behavior is identical, only the output format
changes. build.py itself is the citation for these regexes.

Run:  uv run python scripts/export_fiscal_notes_snapshot.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REFERENCE = Path("webapp/reference/fiscal-notes-build")
OUT = Path("app/data/fiscal-notes-snapshot.json")

# --- copied verbatim from build.py (lines 15-19) -----------------------------
# Matches an azjlbc.gov fiscal-notes table row: the bill-number cell's closing
# anchor, then the adjacent title cell's link. re.S so the title can wrap lines.
PAIR = re.compile(
    r'>([A-Z]{2,4}\s?\d+)</a></div>\s*<div class="divTableCell"[^>]*>\s*'
    r'<a href="([^"]+)"[^>]*?>(.*?)</a>', re.S)


def spaced(no: str) -> str:
    """Normalize "HB2015"/"HB 2015" to a single canonical "HB 2015"."""
    m = re.match(r'([A-Z]+)\s?(\d+)', no)
    return m.group(1) + ' ' + m.group(2)


def chamber_of(bill_number: str) -> str:
    """build.py's `ch()`: chamber is the bill prefix's first letter.

    HB/HCR/HCM/HR -> H, SB/SCR/SCM/SR -> S. Arizona has no other prefixes,
    so the first character is sufficient.
    """
    return 'H' if bill_number[0].upper() == 'H' else 'S'


def ordinal(n: int) -> str:
    """copied from build.py: 57 -> "57th", 1 -> "1st"."""
    suf = 'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')
    return str(n) + suf


def leg_session(y: int) -> str:
    """copied from build.py's `leg_session()` — the label the mockup page shows.

    AZ: odd year = 1st Regular Session, even year = 2nd Regular Session;
    the 57th Legislature covers 2025-2026, which anchors the arithmetic.
    """
    if y % 2 == 1:
        leg = 44 + (y - 1999) // 2
        sess = '1st Reg. Session'
    else:
        leg = 44 + (y - 2000) // 2
        sess = '2nd Reg. Session'
    return '%s Legislature, %s (%d)' % (ordinal(leg), sess, y)


def parse_session_html(html: str) -> list[dict]:
    """copied from build.py's per-file loop (lines 25-32).

    Two behaviors that MUST be preserved, because the export total depends on
    them (2126 bills across 28 sessions, ~37-135 per session):
      1. Rows whose link is not under `/fiscal/` are skipped — that filter is
         what restricts the list to bills that actually have a fiscal note.
      2. Duplicate (bill number, href) pairs are dropped; the cached JLBC
         pages repeat some rows.

    Note this dedupes on the PAIR (number, href), not the number alone, so a
    bill with both an original and a revised note keeps both rows (e.g. 2025
    SB 1010 -> SB1010.DOCX.pdf and SB1010R.DOCX.pdf). `bill_number` is
    therefore NOT unique within a session — 93 such extra rows corpus-wide.
    """
    rows: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for no, href, desc in PAIR.findall(html):
        if '/fiscal/' not in href:
            continue
        no = no.strip()
        desc = re.sub(r'\s+', ' ', desc).strip()   # collapse HTML whitespace
        key = (no, href)
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "bill_number": spaced(no),
            "title": desc,
            # &amp; -> & so the PDF link is usable as a real URL
            "fiscal_note_url": href.replace('&amp;', '&'),
        })
    return rows


def numkey(no: str) -> tuple[int, str]:
    """copied from build.py: sort "HB 2015" by its numeric part, not as text."""
    return (int(re.search(r'\d+', no).group()), no)


def main() -> None:
    sessions = []
    for f in sorted(REFERENCE.glob("live/*.html")):
        year = int(f.stem[:4])
        # errors="replace" mirrors build.py's read. (All 28 currently-cached
        # pages do decode as strict UTF-8; this only keeps the two readers
        # byte-for-byte equivalent.)
        bills = parse_session_html(f.read_text(encoding="utf-8", errors="replace"))
        if not bills:
            continue   # build.py's `if rows:` — skip sessions with no fiscal notes
        # Default order matches the mockup page: bill number ascending.
        bills.sort(key=lambda b: numkey(b["bill_number"]))
        sessions.append({
            "year": year,
            "name": leg_session(year),
            "bills": [
                {"bill_number": b["bill_number"], "title": b["title"],
                 "chamber": chamber_of(b["bill_number"]),
                 "fiscal_note_url": b["fiscal_note_url"]}
                for b in bills
            ],
        })
    # Newest session first — the mockup page lists sessions in reverse order.
    sessions.sort(key=lambda s: s["year"], reverse=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"sessions": sessions}, indent=1), encoding="utf-8")
    # ASCII-only print: the Windows console default codepage mangles an em dash.
    print(f"wrote {OUT} - {sum(len(s['bills']) for s in sessions)} bills "
          f"across {len(sessions)} sessions")


if __name__ == "__main__":
    main()
