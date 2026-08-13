"""Deterministic fake corpus rows for StubSearchProvider — realistic
field values so the UI port renders true-to-life during Plan 2.

Every doc_id carries a `stub-` prefix so it can NEVER collide with a real
corpus doc_id. Plan 4's PDF panel keys on doc_id + page, so an un-namespaced
id (two of these started life as real ids) would pull up a genuine PDF page
next to this file's fabricated snippet — exactly the sort of unauditable
citation the repo forbids. Titles, snippets, and pages stay realistic on
purpose — the containment comes from the namespaced id: nothing can resolve
these rows against a real document.
"""

FIXTURE_ROWS = [
    # doc_url=None on every fixture: stub rows must never link anywhere (the
    # namespaced ids resolve to no real document), and None is exactly what the
    # real provider emits when the sidecar has no record — same degraded shape.
    #
    # Scores are LOGIT-scale (6.5 down to 0.1), matching the real reranker's
    # raw cross-encoder output — NOT 0..1. The UI shows sigmoid(score) as a
    # confidence %; fixture scores on a 0..1 scale would all sigmoid into a
    # meaningless 50-72% band and the stub would look nothing like real data.
    # Titles + meta lines mimic the WEBSITE MOCKUP INDEX's own formats
    # ("Agency, Department of — FY 2027 Baseline" / "category · doc_type ·
    # FY") so the stub renders true-to-life next to joined real rows.
    #
    # text field: stub satisfies the same contract as LanceSearchProvider
    # (which emits the full passage text) because StubSearchProvider is the
    # fallback on any fresh clone or CI run without a migrated corpus. A
    # browser reading .text will get undefined at runtime if the stub lacks it.
    # section_of=None on every fixture: LanceSearchProvider derives it from
    # each row's source_url (app/book_sections.py), and every fixture row
    # above already carries doc_url=None -- there is no URL to derive a
    # parent book from, so None is the only value consistent with the rest
    # of this file. Added 2026-08-11 because the field existed on the real
    # provider's rows but not on the stub's, so a fresh clone (which serves
    # the stub) returned a different response SHAPE than a machine with a
    # migrated corpus -- caught by tests/test_search_route.py's contract test.
    dict(chunk_id=f"stub-{i:03d}", doc_id=doc_id, doc_title=title,
         snippet=snippet, text=snippet, section_path=[], page=page, score=round(6.5 - i * 1.6, 1),
         doc_type=doc_type, fiscal_year=fy, publisher=publisher,
         agencies=agencies, doc_url=None, doc_meta=meta, section_of=None,
         # Which corpus this row belongs to. NOT part of the /api/search row
         # contract -- StubSearchProvider pops it before returning (see there
         # for why it exists at all).
         corpus="budget")
    for i, (doc_id, title, meta, snippet, page, doc_type, fy, publisher, agencies) in enumerate([
        ("stub-jlbc-baseline-fy2027-ahcccs",
         "Health Care Cost Containment System, Arizona — FY 2027 Baseline",
         "Agency Budget Detail · Baseline Book · FY 2027",
         "…provider rate increases of $58.1 million from the General Fund…",
         14, "baseline-per-agency", 2027, "jlbc", ["ahcccs"]),
        ("stub-jlbc-approps-fy2025-dcs",
         "Child Safety, Department of — FY 2025 Appropriations Report",
         "Agency Budget Detail · Appropriations Report · FY 2025",
         "…caseworker staffing levels increased by 112 FTE positions…",
         9, "approps-per-agency", 2025, "jlbc", ["dcs"]),
        ("stub-agao-afr-fy2025",
         "FY 2025 Annual Financial Report",
         "Annual Financial Report · FY 2025",
         "…General Fund ending balance of $1.2 billion…",
         31, "afr", 2025, "agao", []),
        ("stub-governor-governors-budget-fy2027",
         "FY 2027 State Agency Detail — Arizona Executive Budget",
         "Executive Budget · State Agency Detail · FY 2027",
         "…the Executive recommends $65.3 million for homelessness services…",
         102, "governors-budget", 2027, "governor", ["ades"]),
        ("stub-legislature-budget-bill-fy2026-sb1735-2025",
         "FY 2026 Budget Bill (SB 1735)",
         "Budget Bill · FY 2026",
         "…appropriates $19,800,000 to the department for fiscal year 2025-2026…",
         3, "budget-bill", 2026, "legislature", ["adoa"]),
    ])
]

# Fiscal-note rows, so a machine with no ingested corpus does not answer a FISCAL NOTES
# search with BUDGET documents (Destin, 2026-08-13, looking at the running page).
#
# WHY this was a real defect and not just a dev-mode oddity: `_default_provider` probes
# `budget_chunks` and falls back to this stub when it is empty — which is exactly what a
# FRESH INSTALL looks like before anyone has ingested anything. So the first thing a new
# user saw when searching note text on the Fiscal Notes page was five budget documents,
# presented as note matches. The stub had always ignored its `corpus` argument; nothing
# noticed while the fiscal-note search was a small box in the rail, and the browse rebuild
# promoted it to the page's headline feature.
#
# These carry the ingest-built title shape the REAL fiscal-note corpus uses —
# "Fiscal Note - <NUMBER>: <title>" — so the stub exercises the card's own title parsing
# (spec F16) rather than accidentally rendering a pre-split title the real corpus never
# produces. Same `stub-` id namespacing as above: nothing here can resolve to a real note.
FISCAL_NOTE_FIXTURE_ROWS = [
    dict(chunk_id=f"stub-fn-{i:03d}", doc_id=doc_id, doc_title=title,
         snippet=snippet, text=snippet, section_path=["JLBC Fiscal Note", section], page=page,
         score=round(6.2 - i * 1.5, 1),
         doc_type="fiscal-note", fiscal_year=fy, publisher="azleg",
         agencies=agencies, doc_url=None, doc_meta=None, section_of=None,
         corpus="fiscal_notes")
    for i, (doc_id, title, section, snippet, page, fy, agencies) in enumerate([
        ("stub-fn-2026-sb1035",
         "Fiscal Note - SB 1035: state department of corrections; appropriation",
         "Estimated Impact",
         "…would appropriate $28,700,000 from the General Fund to the State Department of "
         "Corrections in FY 2027 for inmate health care contracts…",
         1, 2026, ["adc"]),
        ("stub-fn-2026-hb2407",
         "Fiscal Note - HB 2407: victim notification; automated system",
         "Estimated Impact",
         "…one-time cost of $1,400,000 and ongoing costs of $310,000 annually beginning in "
         "FY 2027…",
         2, 2026, []),
        ("stub-fn-2025-hb2082",
         "Fiscal Note - HB 2082: TPT; exemption; wastewater; pipes",
         "Estimated Impact",
         "…would reduce General Fund revenues by an estimated $2,300,000 in FY 2026, "
         "growing to $2,900,000 by FY 2029…",
         1, 2025, ["ador"]),
        ("stub-fn-2024-hb2186",
         "Fiscal Note - HB 2186: <strike>remedial groundwater incentive</strike> "
         "(NOW: brackish groundwater; incentive)",
         "Fiscal Analysis",
         "…the Department of Water Resources estimates administrative costs of $185,000 in "
         "the first year…",
         3, 2024, ["adwr"]),
    ])
]
