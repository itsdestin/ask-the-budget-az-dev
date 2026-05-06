"""Scout candidate pages for the Phase 0 extractor bake-off (Task 4).

Heuristically flags pages in the 6 PDFs that look like good candidates
for each archetype defined in the Phase 0 plan. Output is a Markdown
shortlist for the user to review and confirm into samples/scoring-pages.yaml.

NOT a deliverable — a one-shot scouting helper. Heuristics are
intentionally simple (no NLP, no layout inference); they're meant to
narrow ~3,500 pages down to a few dozen plausible candidates per
archetype, NOT to pick the final 20.

Run from the worktree root:
  uv run python scripts/scout_pages.py > samples/scout-shortlist.md
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

from pypdf import PdfReader


# pypdf takes ~6.5 minutes on the full 3,472-page corpus. Cache per-page
# stats to disk so heuristic iteration doesn't re-pay that cost.
CACHE_PATH = Path("/tmp/scout-cache.json")


CORPUS = [
    ("jlbc-baseline-fy27", "samples/raw-pdfs/jlbc-baseline-fy27.pdf"),
    ("jlbc-baseline-fy23", "samples/raw-pdfs/jlbc-baseline-fy23.pdf"),
    ("jlbc-approps-fy26", "samples/raw-pdfs/jlbc-approps-fy26.pdf"),
    ("agao-afr-fy25", "samples/raw-pdfs/agao-afr-fy25.pdf"),
    ("governors-state-agency-detail-fy27", "samples/raw-pdfs/governors-state-agency-detail-fy27.pdf"),
    ("governors-sources-and-uses-fy27", "samples/raw-pdfs/governors-sources-and-uses-fy27.pdf"),
]


# Programs likely to surface cross-doc-name drift between Baseline Book
# and Governor's Budget. Picked manually from AZ budget context.
CROSS_DOC_TARGETS = [
    "AHCCCS",
    "DEPARTMENT OF CHILD SAFETY",
    "DEPARTMENT OF CORRECTIONS",
    "DEPARTMENT OF ECONOMIC SECURITY",
    "DEPARTMENT OF EDUCATION",
    "DEPARTMENT OF HEALTH SERVICES",
    "ARIZONA BOARD OF REGENTS",
]


# Heuristic regexes. Compiled once.
RE_NUMERIC_TOKEN = re.compile(r"\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b|\$\s?\d+(?:,\d{3})*(?:\.\d+)?\b")
RE_FOOTNOTE_PAREN = re.compile(r"\(\d{1,2}\)")
RE_FOOTNOTE_LETTER = re.compile(r"\([a-z]\)")
RE_FOOTNOTE_STAR = re.compile(r"\*+|†+|‡+")
RE_RESTATED = re.compile(r"\bas restated\b|\brestated\b", re.IGNORECASE)
# AFR FY25 uses "prior year" rather than "restated" — modern AGAO phrasing for
# the same restatement archetype. Probe in this corpus found 0 hits for
# "restated" but 4 hits for "prior year" on fund-balance schedule pages.
RE_PRIOR_YEAR = re.compile(r"\bprior year\b|\bprior period\b|\bpreviously\s+reported\b", re.IGNORECASE)
RE_MISSION = re.compile(r"\bMission\s+Statement\b|\bProgram Description\b|\bAgency Description\b", re.IGNORECASE)
RE_FY_HEADER = re.compile(r"FY\s*20\d\d", re.IGNORECASE)
RE_LINE_ITEM = re.compile(r"\bSPECIAL LINE ITEMS?\b|\bOPERATING LUMP SUM\b", re.IGNORECASE)
RE_FUND_BAL = re.compile(r"\bfund balance\b|\bnet position\b|\bfinancial statement\b", re.IGNORECASE)


@dataclass
class PageStats:
    doc_id: str
    page: int  # 1-indexed
    char_count: int
    numeric_tokens: int
    footnote_markers: int
    has_restated: bool
    has_prior_year: bool
    has_mission: bool
    fy_header_count: int
    line_item_marker: bool
    fund_balance_marker: bool
    text: str  # kept for cross-doc-name search


def page_stats(doc_id: str, page_num: int, text: str) -> PageStats:
    fn = (
        len(RE_FOOTNOTE_PAREN.findall(text))
        + len(RE_FOOTNOTE_LETTER.findall(text))
        + len(RE_FOOTNOTE_STAR.findall(text))
    )
    return PageStats(
        doc_id=doc_id,
        page=page_num,
        char_count=len(text),
        numeric_tokens=len(RE_NUMERIC_TOKEN.findall(text)),
        footnote_markers=fn,
        has_restated=bool(RE_RESTATED.search(text)),
        has_prior_year=bool(RE_PRIOR_YEAR.search(text)),
        has_mission=bool(RE_MISSION.search(text)),
        fy_header_count=len(RE_FY_HEADER.findall(text)),
        line_item_marker=bool(RE_LINE_ITEM.search(text)),
        fund_balance_marker=bool(RE_FUND_BAL.search(text)),
        text=text,
    )


def extract_corpus() -> dict[str, list[PageStats]]:
    """Read all 6 PDFs and produce per-page stats.

    Disk-cached at CACHE_PATH because pypdf takes ~6.5 minutes on the
    full corpus. Delete the cache file to re-extract.
    """
    if CACHE_PATH.exists():
        print(f"Loading cached stats from {CACHE_PATH}...", file=sys.stderr, flush=True)
        raw = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        # Re-derive PageStats from cached `text` rather than reading the
        # cached fields directly — adding a new boolean flag (e.g. when
        # iterating heuristics) would otherwise need a full pypdf re-run.
        return {
            doc_id: [page_stats(doc_id, p["page"], p["text"]) for p in pages]
            for doc_id, pages in raw.items()
        }
    out: dict[str, list[PageStats]] = {}
    for doc_id, path in CORPUS:
        print(f"Reading {doc_id}...", file=sys.stderr, flush=True)
        reader = PdfReader(path)
        pages: list[PageStats] = []
        for i, page in enumerate(reader.pages):
            try:
                text = page.extract_text() or ""
            except Exception as e:
                text = ""
                print(f"  page {i+1} extract_text() failed: {e}", file=sys.stderr)
            pages.append(page_stats(doc_id, i + 1, text))
        out[doc_id] = pages
    CACHE_PATH.write_text(
        json.dumps({doc_id: [asdict(p) for p in pages] for doc_id, pages in out.items()}),
        encoding="utf-8",
    )
    print(f"Wrote stats cache to {CACHE_PATH}", file=sys.stderr, flush=True)
    return out


# ---------- archetype scorers ----------


def find_multi_page_tables(corpus: dict[str, list[PageStats]]) -> list[dict]:
    """Pages that LOOK like the last (or middle) page of a 5+ page numeric
    table. Heuristic: window of 5 consecutive pages, each with >= 25
    numeric tokens AND each carrying an FY-style header. We return the
    LAST page of each window — that's the page Task 5/7/8 will score for
    multi-page-reassembly. (Per the rubric: dimension applies to the
    last page of a multi-page table, not all pages of one.)
    """
    candidates: list[dict] = []
    # Multi-page tables are concentrated in JLBC Approps and Governor's docs.
    for doc_id in (
        "jlbc-approps-fy26",
        "governors-state-agency-detail-fy27",
        "governors-sources-and-uses-fy27",
    ):
        pages = corpus[doc_id]
        n = len(pages)
        WINDOW = 5
        for last in range(WINDOW, n + 1):
            window = pages[last - WINDOW : last]
            if all(p.numeric_tokens >= 25 and p.fy_header_count >= 1 for p in window):
                # Score = total numeric density over the window.
                score = sum(p.numeric_tokens for p in window)
                candidates.append(
                    {
                        "doc_id": doc_id,
                        "page": last,
                        "why": (
                            f"Last page of a {WINDOW}-page run where every page has "
                            f"≥25 numeric tokens and an FY header (window total: {score} numbers)"
                        ),
                        "score": score,
                    }
                )
    # Dedup overlapping windows: keep the highest-scoring within ±5 pages.
    candidates.sort(key=lambda c: c["score"], reverse=True)
    chosen: list[dict] = []
    seen_ranges: list[tuple[str, int]] = []
    for c in candidates:
        too_close = any(
            doc == c["doc_id"] and abs(p - c["page"]) <= 6 for doc, p in seen_ranges
        )
        if not too_close:
            chosen.append(c)
            seen_ranges.append((c["doc_id"], c["page"]))
        if len(chosen) >= 8:
            break
    return chosen


def find_restated_afr(corpus: dict[str, list[PageStats]]) -> list[dict]:
    """Pages in AFR that signal restated/prior-year financial figures.

    AFR FY25 doesn't use the word "restated" anywhere — modern AGAO style
    phrases the same archetype as "prior year" comparisons on fund-balance
    schedules. Probe found 4 such pages (126, 128, 163, 177). Both
    phrasings are accepted as equivalents for the rubric's
    "restated AFR" archetype.
    """
    out: list[dict] = []
    for p in corpus["agao-afr-fy25"]:
        if not (p.has_restated or p.has_prior_year):
            continue
        marker_label = "restated" if p.has_restated else "prior year"
        out.append(
            {
                "doc_id": p.doc_id,
                "page": p.page,
                "why": (
                    f"Contains '{marker_label}' marker; "
                    f"{p.numeric_tokens} numeric tokens; "
                    f"{'fund-balance/financial-statement language' if p.fund_balance_marker else 'no fund-balance markers'}"
                ),
                "score": p.numeric_tokens + (50 if p.fund_balance_marker else 0),
            }
        )
    out.sort(key=lambda c: c["score"], reverse=True)
    return out[:6]


def find_multi_column_narrative(corpus: dict[str, list[PageStats]]) -> list[dict]:
    """Baseline Book agency-detail pages with Mission Statement / Program
    Description headings. Both FY27 and FY23 in scope so we can pick
    pages that demonstrate cross-year Baseline Book layout.
    """
    out: list[dict] = []
    for doc_id in ("jlbc-baseline-fy27", "jlbc-baseline-fy23"):
        for p in corpus[doc_id]:
            if p.has_mission and p.char_count >= 1500:
                out.append(
                    {
                        "doc_id": doc_id,
                        "page": p.page,
                        "why": (
                            f"Has Mission/Program-Description heading; "
                            f"{p.char_count} chars (prose-heavy); "
                            f"{p.numeric_tokens} numeric tokens"
                            + (" (mixes prose with inline table)" if p.numeric_tokens >= 8 else "")
                        ),
                        "score": p.char_count + (1000 if p.numeric_tokens >= 8 else 0),
                    }
                )
    out.sort(key=lambda c: c["score"], reverse=True)
    return out[:6]


def find_footnote_heavy(corpus: dict[str, list[PageStats]]) -> list[dict]:
    """Pages with lots of footnote markers. Approps and Governor's tend
    to carry numbered footnotes on appropriations schedules.
    """
    out: list[dict] = []
    for doc_id in (
        "jlbc-approps-fy26",
        "governors-state-agency-detail-fy27",
        "agao-afr-fy25",
    ):
        for p in corpus[doc_id]:
            if p.footnote_markers >= 4:
                out.append(
                    {
                        "doc_id": doc_id,
                        "page": p.page,
                        "why": (
                            f"{p.footnote_markers} footnote markers "
                            f"(parens like (1), letter (a), or stars); "
                            f"{p.numeric_tokens} numeric tokens "
                            + ("- looks like a schedule" if p.numeric_tokens >= 15 else "- looks like prose")
                        ),
                        "score": p.footnote_markers * 10 + p.numeric_tokens,
                    }
                )
    out.sort(key=lambda c: c["score"], reverse=True)
    return out[:6]


def find_cross_doc_name(corpus: dict[str, list[PageStats]]) -> list[dict]:
    """Pages where a CROSS_DOC_TARGETS entity appears prominently.

    Filters out TOC/index pages: a single page that mentions 3+ different
    target entities is almost always an index, not a substantive page
    about any one of them. (Probed empirically: page 6 of governors-
    state-agency-detail-fy27 hits 5 of our 7 targets — clearly a TOC.)

    Returns up to 8 pages, ideally matched pairs across docs, but we
    just flag candidates and let the user pair them.
    """
    # First identify TOC pages — pages that mention 3+ targets are noise.
    toc_pages: set[tuple[str, int]] = set()
    for doc_id in (
        "jlbc-baseline-fy27",
        "jlbc-baseline-fy23",
        "governors-state-agency-detail-fy27",
    ):
        for p in corpus[doc_id]:
            distinct_targets = sum(
                1 for t in CROSS_DOC_TARGETS
                if re.search(rf"\b{re.escape(t)}\b", p.text)
            )
            if distinct_targets >= 3:
                toc_pages.add((doc_id, p.page))

    out: list[dict] = []
    for target in CROSS_DOC_TARGETS:
        per_target: list[dict] = []
        for doc_id in (
            "jlbc-baseline-fy27",
            "jlbc-baseline-fy23",
            "governors-state-agency-detail-fy27",
        ):
            for p in corpus[doc_id]:
                if (doc_id, p.page) in toc_pages:
                    continue
                occurrences = sum(1 for _ in re.finditer(rf"\b{re.escape(target)}\b", p.text))
                # Require at least 2 occurrences on a content-rich page —
                # one mention is too weak a signal that the page is ABOUT
                # the entity (could be a parenthetical / cross-reference).
                if occurrences >= 2 and p.char_count > 1500:
                    per_target.append(
                        {
                            "doc_id": doc_id,
                            "page": p.page,
                            "why": f"'{target}' appears {occurrences}× on a content-rich page ({p.char_count} chars)",
                            "score": occurrences * 100 + p.char_count // 100,
                            "_target": target,
                        }
                    )
        per_target.sort(key=lambda c: c["score"], reverse=True)
        seen_doc_target: set[tuple[str, str]] = set()
        for c in per_target:
            key = (c["doc_id"], c["_target"])
            if key in seen_doc_target:
                continue
            seen_doc_target.add(key)
            out.append(c)
    out.sort(key=lambda c: (c["_target"], c["doc_id"], c["page"]))
    return out[:10]


def find_misc(corpus: dict[str, list[PageStats]]) -> list[dict]:
    """Variety pages — different doc types / page styles to surface
    failure modes the other archetypes miss.
    """
    out: list[dict] = []

    # AFR prose page — likely Notes-to-Financial-Statements section.
    # AFR FY25 has no MD&A section (probed empirically), so we use the
    # longest prose-heavy AFR page that's NOT a fund-balance schedule.
    afr_notes_candidates = [
        p for p in corpus["agao-afr-fy25"]
        if p.char_count >= 2500 and p.numeric_tokens <= 15
    ]
    afr_notes_candidates.sort(key=lambda p: p.char_count, reverse=True)
    for p in afr_notes_candidates[:1]:
        out.append(
            {
                "doc_id": "agao-afr-fy25",
                "page": p.page,
                "why": (
                    f"AFR prose page (likely Notes-to-Financial-Statements section); "
                    f"{p.char_count} chars, {p.numeric_tokens} numbers — "
                    f"tests narrative/disclosure handling vs. all-table pages"
                ),
                "score": p.char_count,
            }
        )

    # Sources and Uses summary table — high numeric density near start.
    for p in corpus["governors-sources-and-uses-fy27"][:30]:
        if p.numeric_tokens >= 30:
            out.append(
                {
                    "doc_id": "governors-sources-and-uses-fy27",
                    "page": p.page,
                    "why": f"Early Sources-and-Uses summary table ({p.numeric_tokens} numbers, page near start)",
                    "score": p.numeric_tokens,
                }
            )
            break

    # Baseline FY23 agency overview (paired-year drift candidate).
    for p in corpus["jlbc-baseline-fy23"]:
        if p.has_mission and 5 <= p.numeric_tokens <= 25:
            out.append(
                {
                    "doc_id": "jlbc-baseline-fy23",
                    "page": p.page,
                    "why": "FY23 Baseline agency overview (Mission + small inline table) — pair with FY27 candidate for cross-year drift",
                    "score": p.char_count,
                }
            )
            break

    # JLBC Approps line-item-marker page — tests whether extractors
    # preserve SPECIAL LINE ITEMS / OPERATING LUMP SUM as structural signals.
    for p in corpus["jlbc-approps-fy26"]:
        if p.line_item_marker and p.numeric_tokens >= 20:
            out.append(
                {
                    "doc_id": "jlbc-approps-fy26",
                    "page": p.page,
                    "why": f"Approps page with explicit SPECIAL LINE ITEMS / OPERATING LUMP SUM marker; {p.numeric_tokens} numbers",
                    "score": p.numeric_tokens,
                }
            )
            break

    return out[:5]


# ---------- output ----------


def emit_section(title: str, target: int, candidates: list[dict]) -> None:
    print(f"\n## {title} (target: {target} page{'s' if target != 1 else ''})")
    if not candidates:
        print("\n_No candidates found — relax heuristics or pick manually._")
        return
    print()
    print("| doc_id | page | why |")
    print("|---|---|---|")
    for c in candidates:
        # Strip internal-only fields before display
        why = c["why"]
        print(f"| `{c['doc_id']}` | {c['page']} | {why} |")


def main() -> int:
    corpus = extract_corpus()

    total_pages = sum(len(ps) for ps in corpus.values())
    print("# Phase 0 Task 4 — Scouting Shortlist")
    print()
    print(
        f"Scouted {total_pages} pages across {len(corpus)} PDFs. "
        f"Pick ~3–5 from each archetype below to fill `samples/scoring-pages.yaml`."
    )
    print()
    print(
        "Heuristics are simple (regex + counts), so candidates need a quick "
        "human eyeball before committing — open the PDF to the page, confirm "
        "it actually exhibits the archetype, swap if it doesn't."
    )

    emit_section(
        "Multi-page tables (last page of a long table run)",
        5,
        find_multi_page_tables(corpus),
    )
    emit_section(
        "Restated AFR tables",
        3,
        find_restated_afr(corpus),
    )
    emit_section(
        "Multi-column narrative (Baseline Book agency descriptions)",
        3,
        find_multi_column_narrative(corpus),
    )
    emit_section(
        "Footnote-heavy schedules",
        3,
        find_footnote_heavy(corpus),
    )
    emit_section(
        "Cross-doc-name entity-resolution stress",
        3,
        find_cross_doc_name(corpus),
    )
    emit_section(
        "Misc (variety — different doc types / page styles)",
        3,
        find_misc(corpus),
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
