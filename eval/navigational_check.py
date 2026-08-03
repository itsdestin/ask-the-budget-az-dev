"""Measure NAVIGATIONAL queries — "show me this agency's document of this type".

WHY this is not in `eval/queries.yaml`, which is where the plan first put it:
that file is a FACTUAL-recall instrument. Each entry names chunk_ids and asks
whether retrieval found those passages. A navigational query has no single
right passage — any chunk of the right document answers it — so recall@k
scores it badly in both directions.

Both directions were observed, not reasoned about, on 2026-08-02:

  * FALSE FAIL. "ahcccs baseline" returns jlbc-baseline-fy2027-axs at ranks 1
    AND 3 — exactly right — while the specific chunk chosen as ground truth
    sat outside the top 20. It scored as a pass only because
    `eval/scoring.py`'s loose dimensions fallback credited a different chunk
    of the same document.
  * POLLUTED HEADLINE. Adding four such entries moved whole-set recall@15
    from 97.62% to 91.30%, which reads as a retrieval regression and is
    nothing of the kind — it is a query-set change. Layer 1 numbers are only
    comparable across identical query sets.

So this reports what a navigational query actually promises, as three
separate numbers, and leaves queries.yaml at its comparable 47.

    JLBC_DATA_DIR=... .venv/bin/python -m eval.navigational_check
"""
from __future__ import annotations

import argparse
import json

from retrieval.pipeline import RetrievalRequest, retrieve

# The six queries Destin typed on 2026-08-02 when asking why ranking looked
# wrong. `expect_doc_type=None` means the query names no type, so any type is
# acceptable and only the agency is scored.
CASES: list[dict] = [
    {"query": "ahcccs baseline", "agency": "agency:axs",
     "doc_type": "baseline-per-agency"},
    {"query": "doc baseline", "agency": "agency:adc",
     "doc_type": "baseline-per-agency"},
    {"query": "ahcccs appropriations report", "agency": "agency:axs",
     "doc_type": "approps-per-agency"},
    {"query": "dema ar", "agency": "agency:ema",
     "doc_type": "approps-per-agency"},
    # No FY2027 Appropriations Report exists (approps-per-agency stops at
    # FY2026), so the correct behaviour is the best available edition, not a
    # miss. Scored on agency and type only.
    {"query": "ahcccs 27ar", "agency": "agency:axs",
     "doc_type": "approps-per-agency"},
    {"query": "ahcccs 2027 approps report", "agency": "agency:axs",
     "doc_type": "approps-per-agency"},
]

TOP_N = 5


def _chronological(years: list[int]) -> float:
    """Share of adjacent pairs that are newest-first (ties count as ordered).

    Same idea as `eval/chronological.py` applies to the recency sweep; kept
    local because that module scores a different input shape.
    """
    pairs = list(zip(years, years[1:]))
    if not pairs:
        return 1.0
    return sum(1 for a, b in pairs if a >= b) / len(pairs)


def run(top_n: int = TOP_N) -> list[dict]:
    rows = []
    for case in CASES:
        result = retrieve(RetrievalRequest(query=case["query"], top_k=top_n))
        chunks = result.chunks
        n = len(chunks) or 1

        agency_hits = sum(
            1 for c in chunks if case["agency"] in (c.agency_canonical_ids or [])
        )
        type_hits = sum(1 for c in chunks if c.doc_type == case["doc_type"])
        years = [c.fiscal_year for c in chunks if c.fiscal_year]

        rows.append({
            "query": case["query"],
            "agency_precision": round(agency_hits / n, 3),
            "doc_type_precision": round(type_hits / n, 3),
            "chronological": round(_chronological(years), 3),
            "newest_year": max(years) if years else None,
            "years": years,
            "inferred_agencies": result.inferred_agencies,
            "inferred_doc_types": result.inferred_doc_types,
            "dropped_filters": result.dropped_filters,
        })
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    ap.add_argument("--top-n", type=int, default=TOP_N)
    args = ap.parse_args()

    rows = run(args.top_n)
    print(f"{'query':<30} {'agency':>7} {'type':>7} {'chrono':>7}  years")
    for r in rows:
        print(
            f"{r['query']:<30} {r['agency_precision']:>7.2f} "
            f"{r['doc_type_precision']:>7.2f} {r['chronological']:>7.2f}  {r['years']}"
        )

    mean_agency = sum(r["agency_precision"] for r in rows) / len(rows)
    mean_type = sum(r["doc_type_precision"] for r in rows) / len(rows)
    mean_chrono = sum(r["chronological"] for r in rows) / len(rows)
    print(
        f"\nmean agency precision@{args.top_n} {mean_agency:.3f}  "
        f"doc-type {mean_type:.3f}  chronological {mean_chrono:.3f}"
    )

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "top_n": args.top_n,
                    "rows": rows,
                    "mean_agency_precision": round(mean_agency, 3),
                    "mean_doc_type_precision": round(mean_type, 3),
                    "mean_chronological": round(mean_chrono, 3),
                },
                fh,
                indent=2,
            )
        print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
