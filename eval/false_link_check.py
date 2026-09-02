"""The A8 ship gate: measure the FALSE-LINK rate, not coverage.

Citation linking was previously accepted on coverage — how often a link
was PRODUCED — and shipped a system where 34% of linked figures matched a
value in more than one document and the source was picked by document
authority (review memo §5.1). Coverage rises as a matcher gets looser, so
it cannot detect that. Only the error rate can.

Method (memo §5.2): invent figures at a given digit profile and attempt to
link them against a REAL turn's retrieved chunks. No invented figure
appears in any answer, so **every link is false by construction** and the
rate needs no hand-labelled ground truth. Reported per digit profile,
because a rounded `$12.49B` fingerprints four digits while an exactly
written `1,391,157,700` is nearly unique — a ~10x difference the old code
was blind to.

The companion measurement (memo §9) is the verdict distribution over the
same recorded answers. Recorded transcripts carry no `[[cN]]` markers, so
that number measures the UNTAGGED fallback path specifically — it is the
honest floor for coverage, not the shipped figure, which comes from a live
run with tagging enabled.

Usage:
    uv run python -m eval.false_link_check <run_dir> [--seed 7] [--n 40]
    uv run python -m eval.false_link_check <run_dir> --labelled-pool

`--labelled-pool` is the phase A (spec section 5) gate: it renders every
pool chunk through `render_labelled` before inventing figures against it,
so the check measures the false-link rate against what the model ACTUALLY
reads today, not the pre-phase-A raw text. Every recorded transcript
predates phase A, so its chunk dicts carry no `is_table` flag to gate on
(and even a chunk built by the current `_chunk_entry` does not serialize
one — it is an internal attribute, only used to decide whether to ATTEMPT
labelling). `render_labelled` itself returns `None` for anything without a
tab-joined row and a detectable header row, so calling it unconditionally
on every chunk's text is the correct proxy for "is this a table chunk" and
needs no such flag.

Reads the gitignored `*-r1.jsonl` transcripts and costs nothing.
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any, Iterator

from citation.annotate import annotate_answer
from citation.figures import Figure
from eval.agent_transcript import final_answer, read_transcript, retrieve_calls
from retrieval.table_view import render_labelled

# (significant digits to invent, scale, decimals to render).
# The three profiles are the memo's: rounded billions and rounded millions
# are what answers actually write for large sums, and the exactly-written
# grouped integer is the strong-fingerprint control they are judged
# against.
PROFILES: dict[str, tuple[int, int, int | None]] = {
    "4sig-billions": (4, 1_000_000_000, 2),   # $12.49B
    "4sig-millions": (4, 1_000_000, 1),       # $376.2M
    "exact-grouped": (9, 1, None),            # 391,157,700
}
# Metadata an annotation needs to be openable in the viewer. doc_id is the
# load-bearing one — the ambiguity refusal keys on distinct doc_ids.
_META_FIELDS = ("doc_id", "doc_type", "doc_title", "publisher",
                "fiscal_year", "page_start", "page_end", "bbox")


def invent_figures(profile: str, n: int, seed: int) -> list[Figure]:
    """`n` figures nobody wrote, rendered the way an answer would write
    them. Seeded so a gate number can be re-derived; the seed is mixed with
    the profile name so the three profiles never draw the same digits."""
    sig, scale, decimals = PROFILES[profile]
    rng = random.Random(f"{profile}:{seed}")
    out: list[Figure] = []
    for _ in range(n):
        digits = rng.randint(10 ** (sig - 1), 10 ** sig - 1)
        if decimals is None:
            text = f"{digits:,}"
            value: float = float(digits)
        else:
            # The rendering is the point: the specificity floor reads the
            # WRITTEN digits, so "$12.49B" must carry four of them. Format
            # explicitly rather than interpolating the float, so the digit
            # count is a property of the profile and not of float repr.
            value = digits / (10 ** decimals)
            suffix = "B" if scale == 1_000_000_000 else "M"
            text = f"${value:.{decimals}f}{suffix}"
        out.append(Figure(text, 0, len(text), value, scale))
    return out


def false_link_rate(figs: list[Figure], chunks: dict[str, str],
                    meta: dict[str, dict[str, Any]]) -> float:
    """Share of invented figures that linked to something. Every one of
    them is a figure the system would have sourced to a document that does
    not support it, so ANY link counts as false — including a link the old
    authority rule would have called correct."""
    linked = 0
    for fig in figs:
        # Annotate the figure's own text as a whole answer: the pipeline
        # re-extracts figures from prose, so handing it the rendering is
        # what exercises the real extractor + floor + matcher chain.
        # tags=[] because an invented figure carries no model attestation —
        # this measures the untagged fallback, the only path a value can
        # take without the model vouching for it.
        ann = annotate_answer(fig.text, chunks, meta, tags=[], alias_map={})
        if any(f["verdict"] == "linked" for f in ann["figures"]):
            linked += 1
    return linked / len(figs) if figs else 0.0


def pools(run_dir: Path, *, labelled: bool = False
          ) -> Iterator[tuple[str, dict[str, str],
                              dict[str, dict[str, Any]], str]]:
    """(stem, chunks, meta, final answer) per recorded transcript.

    Uses eval.agent_transcript's accessors rather than re-parsing the
    JSONL: the retrieve results live on the TERMINAL frame's `toolCalls`,
    not on the per-event lines, and a second hand-rolled reader would be a
    second dialect to keep in sync.

    `labelled=True` is the G-OT gate for phase A (spec section 5): every
    chunk's text is run through `render_labelled` first, and only its
    `None` (not-a-table, or over the size cap) falls back to the raw text
    — the same choice `harness/tools.py::_chunk_entry` makes at request
    time. This is a POOL-TEXT substitution only; it changes what the
    invented figures are matched against, not which chunks exist.
    """
    for path in sorted(run_dir.glob("*-r1.jsonl")):
        t = read_transcript(path)
        chunks: dict[str, str] = {}
        meta: dict[str, dict[str, Any]] = {}
        for call in retrieve_calls(t):
            for c in call.get("chunks") or []:
                chunk_id = c.get("chunk_id")
                if not chunk_id:
                    continue
                text = c.get("text") or ""
                if labelled:
                    text = render_labelled(text) or text
                chunks[chunk_id] = text
                meta[chunk_id] = {k: c.get(k) for k in _META_FIELDS}
        if chunks:
            yield path.stem, chunks, meta, final_answer(t)


def verdict_counts(run_dir: Path, *, labelled: bool = False) -> dict[str, int]:
    """Verdict distribution over the recorded answers (memo §9) — each
    answer annotated against its OWN retrieved pool."""
    counts = {"linked": 0, "derived": 0, "unverified": 0, "total": 0}
    for _stem, chunks, meta, answer in pools(run_dir, labelled=labelled):
        ann = annotate_answer(answer, chunks, meta, tags=[], alias_map={})
        for entry in ann["figures"]:
            counts["total"] += 1
            verdict = entry.get("verdict")
            if verdict in counts:
                counts[verdict] += 1
    return counts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--n", type=int, default=40,
                    help="invented figures per pool per profile")
    ap.add_argument("--labelled-pool", action="store_true",
                    help="use render_labelled(text) as the pool text for "
                         "table chunks (phase A gate, spec section 5)")
    args = ap.parse_args(argv)

    all_pools = list(pools(args.run_dir, labelled=args.labelled_pool))
    if not all_pools:
        print(f"no transcripts with retrieved chunks in {args.run_dir}")
        return 1

    report: dict[str, Any] = {"run_dir": str(args.run_dir), "seed": args.seed,
                              "labelled_pool": args.labelled_pool,
                              "pools": len(all_pools), "profiles": {}}
    print(f"{len(all_pools)} pools, {args.n} invented figures each\n")
    print(f"{'profile':16s} {'trials':>7s} {'false links':>12s} {'rate':>8s}")
    for profile in PROFILES:
        linked = trials = 0
        for i, (_stem, chunks, meta, _answer) in enumerate(all_pools):
            # A per-pool seed, so the pools measure DIFFERENT invented
            # numbers instead of re-testing one 40-figure sample 31 times.
            # Same 40 everywhere would report the luck of one sample with
            # false confidence; derived from the index so it is still
            # exactly reproducible.
            figs = invent_figures(profile, n=args.n, seed=args.seed + i)
            linked += round(false_link_rate(figs, chunks, meta) * len(figs))
            trials += len(figs)
        rate = linked / trials if trials else 0.0
        report["profiles"][profile] = {"trials": trials, "false_links": linked,
                                       "rate": rate}
        print(f"{profile:16s} {trials:7d} {linked:12d} {rate:8.2%}")

    counts = verdict_counts(args.run_dir, labelled=args.labelled_pool)
    total = counts["total"]
    coverage = ((counts["linked"] + counts["derived"]) / total) if total else None
    report["verdicts"] = counts
    report["coverage"] = coverage
    print(f"\nverdict distribution over {total} recorded figures "
          f"(UNTAGGED fallback — recorded transcripts carry no markers)")
    for verdict in ("linked", "derived", "unverified"):
        share = counts[verdict] / total if total else 0.0
        print(f"{verdict:16s} {counts[verdict]:7d} {share:8.1%}")
    if coverage is not None:
        print(f"{'coverage':16s} {'':7s} {coverage:8.1%}  (linked + derived)")

    suffix = "-labelled" if args.labelled_pool else ""
    out = args.run_dir / f"false-link-report{suffix}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
