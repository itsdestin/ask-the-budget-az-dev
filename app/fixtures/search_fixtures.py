"""Deterministic fake corpus rows for StubSearchProvider — realistic
field values so the UI port renders true-to-life during Plan 2."""

FIXTURE_ROWS = [
    dict(chunk_id=f"stub-{i:03d}", doc_id=doc_id, doc_title=title,
         snippet=snippet, page=page, score=round(0.95 - i * 0.07, 2),
         doc_type=doc_type, fiscal_year=fy, publisher=publisher,
         agencies=agencies)
    for i, (doc_id, title, snippet, page, doc_type, fy, publisher, agencies) in enumerate([
        ("jlbc-baseline-fy2027-ahcccs", "FY 2027 Baseline — AHCCCS",
         "…provider rate increases of $58.1 million from the General Fund…",
         14, "baseline-per-agency", 2027, "jlbc", ["ahcccs"]),
        ("jlbc-approps-fy2025-dcs", "FY 2025 Appropriations Report — DCS",
         "…caseworker staffing levels increased by 112 FTE positions…",
         9, "approps-per-agency", 2025, "jlbc", ["dcs"]),
        ("agao-afr-fy2025", "FY 2025 Annual Financial Report",
         "…General Fund ending balance of $1.2 billion…",
         31, "afr", 2025, "agao", []),
        ("governor-governors-budget-fy2027", "FY 2027 Executive Budget",
         "…the Executive recommends $65.3 million for homelessness services…",
         102, "governors-budget", 2027, "governor", ["ades"]),
        ("legislature-budget-bill-fy2026-sb1735-2025", "FY 2026 Budget Bill (SB 1735)",
         "…appropriates $19,800,000 to the department for fiscal year 2025-2026…",
         3, "budget-bill", 2026, "legislature", ["adoa"]),
    ])
]
