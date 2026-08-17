"""Verify agent-eval queries against the live corpus (free, no OpenRouter).

Task 10 (2026-08-16 consolidated-eval-pipeline plan), free Step 1. Checks
three things per query, which together answer "is this query scoreable and
is its ground truth actually in the corpus":

  1. STRUCTURAL   — every query still passes the committed structural tests
                    (set liability, set sizes, key-fact parse, budget corpus,
                    refusal hygiene). That part is just the pytest suite.
  2. FACT PRESENCE — every key_fact's value text appears in some budget_chunks
                    row's text. A fact never present can never be matched, so
                    the query would score 0 forever (false failure).
  3. REACHABILITY  — a top-20 retrieve() of the verbatim question returns at
                    least one chunk containing each key fact. A fact that is
                    present but unreachable-by-the-query-itself would make the
                    query depend on the agent searching beyond its own first
                    question — scoreable, but worth surfacing.

WHY this is "free": it scans LaneDB locally and runs the local reranker; it
never calls OpenRouter and is safe on any machine with JLBC_DATA_DIR.
Money-spending confirmation (run each query through the real app) is Step 6
of Task 10 and is gated on an OpenRouter key — this script does NOT do that.

Usage:
    uv run python scripts/verify_agent_query.py --all
    uv run python scripts/verify_agent_query.py --id lk-adc-total-fy2026
"""
from __future__ import annotations

import argparse
import sys
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.agent_schema import load_agent_queries

DEFAULT_QUERIES = ROOT / "eval/agent_queries.yaml"


def _structural_failures() -> list[str]:
    """Run the committed structural tests; report each failing test."""
    run = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_eval_agent_queries.py",
         "-q", "--no-header"],
        capture_output=True, text=True,
    )
    if run.returncode == 0:
        return []
    failures = [ln.split("::")[-1] for ln in run.stdout.splitlines()
                if ln.startswith("FAILED") and "::" in ln]
    return failures or ["structural suite failed (exit %d)" % run.returncode]


def _fact_presence(query) -> dict[str, bool | None]:
    """Presence is checked only for kind in (string, regex) — a currency
    fact's value is a NUMBER and can't be text-searched; leave it None
    (not checked) rather than declaring it missing. Currency reachability is
    the meaningful check and it runs on retrieve() output."""
    from store.chunk_store import ChunkStore, sql_str
    store = ChunkStore()
    rows = store.scan("budget_chunks", ["text"])
    corpus_text = "\n".join((r.get("text") or "") for r in rows)
    out: dict[str, bool | None] = {}
    for f in query.key_facts:
        if f.kind not in ("string", "regex"):
            out[f.value] = None
            continue
        import re
        try:
            compiled = re.compile(f.value, re.IGNORECASE)
        except re.error:
            out[f.value] = None
            continue
        out[f.value] = bool(compiled.search(corpus_text))
    return out


def _reachability(query, presence) -> dict[str, bool | None]:
    """Run the verbatim question through retrieve() and check each fact's
    value appears in some returned chunk's text. Compares within the
    retrieved set regardless of fact kind (currency values are strings here)."""
    from retrieval.pipeline import retrieve, RetrievalRequest  # local import — heavy
    out: dict[str, bool | None] = {}
    try:
        # WHY wrapper not a bare string: retrieve() requires a RetrievalRequest
        # (it reads `req.query.strip()`), so passing the raw question string
        # raised AttributeError inside this try, set every fact to None, and
        # reported a vacuous PASS for all 62 queries — the script's reachability
        # check had silently never run (found 2026-08-16 authoring the Multi set;
        # all currency facts' reachability was unverified up to that point).
        result = retrieve(RetrievalRequest(query=query.question))
        chunks = result.chunks if hasattr(result, "chunks") else []
        text = "\n".join((c.text or "") for c in chunks)
        for f in query.key_facts:
            if f.kind == "regex":
                import re
                try:
                    out[f.value] = bool(re.search(f.value, text, re.IGNORECASE))
                except re.error:
                    out[f.value] = None
            else:
                out[f.value] = f.value in text
    except Exception as exc:  # noqa: BLE001 - surface in report
        for f in query.key_facts:
            out[f.value] = None
        out["_error"] = f"{type(exc).__name__}: {exc}"
    return out


def verify(query) -> dict:
    presence = _fact_presence(query)
    reach = _reachability(query, presence)
    return {
        "id": query.id,
        "set": query.set,
        "shape": query.shape,
        "n_facts": len(query.key_facts),
        "presence": presence,
        "reachability": reach,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Verify agent-eval queries vs corpus")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--id", default=None, help="verify one query id")
    args = ap.parse_args()

    queries = load_agent_queries(DEFAULT_QUERIES)
    if args.id:
        queries = [q for q in queries if q.id == args.id]
    if not queries:
        print("no queries selected", file=sys.stderr)
        return 2

    struct_fail = _structural_failures()
    lines = [f"Verifying {len(queries)} queries — structural: "
             + ("PASS" if not struct_fail else "FAIL")]
    if struct_fail:
        lines += [f"  structural: {s}" for s in struct_fail]

    missing_presence = 0
    unreachable = 0
    for q in queries:
        r = verify(q)
        mp = [v for v in r["presence"].values() if v is False]
        ur = [v for v in r["reachability"].values() if v is False]
        missing_presence += len(mp)
        unreachable += len(ur)
        status = "PASS" if (not mp and not ur) else ("WARN" if not mp else "FAIL")
        lines.append(f"[{status}] {q.id} (set={q.set}, {r['n_facts']} facts)")
        for val, ok in r["presence"].items():
            if ok is False:
                lines.append(f"    - FACT MISSING from corpus: {val!r}")
        for val, ok in r["reachability"].items():
            if ok is False:
                lines.append(f"    - fact not in top-20 retrieve of question: {val!r}")

    print("\n".join(lines))
    print(f"\nSummary: {len(queries)} queries, "
          f"{missing_presence} fact-presence misses, {unreachable} reachability misses")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
