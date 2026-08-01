"""LLM-driven query synthesizer.

Pulls chunks from the corpus, asks Claude to write a realistic analyst
question whose answer is in each chunk, builds EvalQuery records, and
writes to eval/queries.yaml.

Three query types:
  - lookup (25 queries): one chunk per query.
  - comparison (5 queries): chunk PAIR across two FYs of same agency.
  - refusal (5 queries): no chunk seed; Claude generates out-of-scope.

Vocabulary-contamination mitigation: the prompt explicitly asks Claude
to paraphrase rather than borrow rare terms from the source chunk.

Seeds come from the embedded LanceDB corpus via store.chunk_store —
sampling that the Postgres original pushed into SQL (`ORDER BY RANDOM()`,
a self-join for the comparison pairs) happens in Python here, because
LanceDB offers neither.

Invocation:
    uv run python -m eval.synthesize_queries           # full set (35)
    uv run python -m eval.synthesize_queries --append  # add to existing
    uv run python -m eval.synthesize_queries --corpus fiscal_note_chunks \\
        --output eval/fiscal_note_queries.yaml        # the corpus with
                                                      # no ground truth yet
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from anthropic import Anthropic

from eval.schema import EvalQuery, ExpectedChunk, QueryDimensions
from store.chunk_store import ChunkStore

# The model the synthesizer uses. Hardcoded — bumping this is a
# deliberate decision, not a config tweak.
SYNTH_MODEL = "claude-opus-4-7"

# How many lookup queries to synthesize per invocation by default.
DEFAULT_LOOKUP_COUNT = 25
DEFAULT_COMPARISON_COUNT = 5
DEFAULT_REFUSAL_COUNT = 5

DEFAULT_CORPUS = "budget_chunks"

# Chunks shorter than this were "degenerate" in the Postgres original —
# a stray heading or page number that no realistic analyst question can
# be answered from. Kept verbatim so a re-synthesized set is comparable
# to the one already committed.
MIN_TOKENS = 80

# Columns the synthesizer needs. Projected explicitly: a bare scan drags
# the 768-float vector out of every row, which on a 22k-chunk corpus is
# ~65 MB of data nothing here reads.
_SEED_COLUMNS = [
    "chunk_id",
    "text",
    "publisher",
    "doc_type",
    "fiscal_year",
    "agency_canonical_ids",
]


def _scan_seed_chunks(store: Any, corpus: str) -> list[dict]:
    """Every non-degenerate chunk of `corpus`, projected to what we need.

    WHY a full scan instead of a sampled query: LanceDB has no
    `ORDER BY RANDOM()`, so the Postgres version's push-down sampling has
    no equivalent — the random pick happens in Python. Reading the whole
    corpus is affordable precisely because of the projection above
    (six scalar columns over ~22k rows), and this is an offline
    eval-authoring tool, not a request path.
    """
    return store.scan(corpus, _SEED_COLUMNS, where=f"token_count > {MIN_TOKENS}")


def sample_lookup_chunks(
    n: int, *, corpus: str = DEFAULT_CORPUS, store: Any | None = None
) -> list[dict]:
    """Sample n chunks balanced across publishers.

    Round-robins the publishers so a publisher with 20x the chunks
    doesn't take 20x the seeds; the old SQL did the same thing with a
    per-publisher ROW_NUMBER window. Doesn't try to be perfectly
    balanced — the synthesizer's prompt is robust to over-representing
    one publisher, and a publisher that runs out simply stops
    contributing.
    """
    rows = _scan_seed_chunks(store or ChunkStore(), corpus)

    by_publisher: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_publisher[row.get("publisher") or "(unknown)"].append(row)
    for bucket in by_publisher.values():
        random.shuffle(bucket)

    # Deal one chunk to each publisher in turn until we have n or the
    # corpus is exhausted. Sampling is without replacement — two eval
    # queries sharing one ground-truth chunk would inflate recall.
    picked: list[dict] = []
    buckets = list(by_publisher.values())
    random.shuffle(buckets)
    while len(picked) < n and any(buckets):
        for bucket in buckets:
            if not bucket:
                continue
            picked.append(bucket.pop())
            if len(picked) == n:
                break
    random.shuffle(picked)
    return picked


def parse_lookup_response(raw: str) -> dict:
    """Extract {query, anchor_text} from Claude's response. Accepts
    markdown-fenced JSON or bare JSON. Raises ValueError on malformed
    input — the synthesizer should fail loudly per query rather than
    emit bad data."""
    # Strip leading/trailing markdown fences if present.
    text = raw.strip()
    fence_match = re.match(r"```(?:json)?\s*(.+?)\s*```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1)
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"synthesizer response not JSON: {raw[:200]}") from e
    if "query" not in obj or "anchor_text" not in obj:
        raise ValueError(
            f"synthesizer response missing keys: {list(obj.keys())}"
        )
    return obj


_LOOKUP_PROMPT_TEMPLATE = """You are a query writer for an Arizona budget Q&A eval set.

Given the following chunk of text from a state budget document, write ONE realistic question that a JLBC fiscal analyst would ask, whose answer is contained in this chunk.

Source chunk ({publisher}, {doc_type}, FY{fiscal_year}, agency={agency}):

\"\"\"
{chunk_text}
\"\"\"

REQUIREMENTS:
- Phrase the question the way a real analyst would ask it conversationally.
- Do NOT borrow rare or distinctive terms from the source chunk verbatim. Use synonyms, paraphrase numeric figures into rounder form ("$3.3M" instead of "$3,290,400"), and avoid quoting the chunk's exact phrasing.
- The question must be specific enough that this chunk is the right answer — vague generic questions don't help.
- Also provide a short "anchor_text" (3-15 words) — a distinctive phrase from the source chunk that would identify it after re-ingest (used by a refresh tool to find the successor chunk).

Output ONLY valid JSON with two keys: "query" and "anchor_text". No prose, no markdown wrapper.

Example output:
{{"query": "What was AHCCCS's FY26 General Fund appropriation?", "anchor_text": "$2,587,400 from the General Fund"}}
"""


def synthesize_lookup_query(
    seed_chunk: dict, client: Anthropic, q_id: str
) -> EvalQuery:
    """One lookup query from one seed chunk. Calls Claude, parses,
    builds EvalQuery."""
    agency = (
        seed_chunk["agency_canonical_ids"][0]
        if seed_chunk.get("agency_canonical_ids")
        else "(none)"
    )
    prompt = _LOOKUP_PROMPT_TEMPLATE.format(
        publisher=seed_chunk["publisher"],
        doc_type=seed_chunk["doc_type"],
        fiscal_year=seed_chunk["fiscal_year"],
        agency=agency,
        chunk_text=seed_chunk["text"][:2000],
    )

    response = client.messages.create(
        model=SYNTH_MODEL,
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text
    parsed = parse_lookup_response(raw)

    return EvalQuery(
        id=q_id,
        query=parsed["query"],
        type="lookup",
        expected_chunks=[
            ExpectedChunk(
                chunk_id=seed_chunk["chunk_id"],
                dimensions=QueryDimensions(
                    publisher=seed_chunk["publisher"],
                    doc_type=seed_chunk["doc_type"],
                    fiscal_year=seed_chunk["fiscal_year"],
                    agency=(
                        seed_chunk["agency_canonical_ids"][0]
                        if seed_chunk.get("agency_canonical_ids")
                        else None
                    ),
                ),
                anchor_text=parsed["anchor_text"],
            )
        ],
        expected_refusal=False,
        synthesized_by=SYNTH_MODEL,
        synthesized_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
    )


def sample_comparison_pairs(
    n: int, *, corpus: str = DEFAULT_CORPUS, store: Any | None = None
) -> list[tuple[dict, dict]]:
    """Find chunk pairs that stamp to the same agency across two
    different fiscal years. Returns up to n pairs.

    The Postgres original expressed this as a self-join on
    `b.agency_canonical_ids = a.agency_canonical_ids AND b.fiscal_year >
    a.fiscal_year AND b.doc_type = a.doc_type`. DataFusion can't join a
    Lance table to itself through `ChunkStore`, so the same grouping is
    done in Python over one scan — the join key becomes a dict key.
    """
    rows = _scan_seed_chunks(store or ChunkStore(), corpus)

    # Group on the SAME key the old self-join used: the full agency array
    # (not just its first element) plus doc_type. Comparing across
    # doc_types would pit a Baseline estimate against an Approps actual,
    # which reads as a year-over-year change but isn't one.
    grouped: dict[tuple, dict[int, list[dict]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for row in rows:
        agencies = tuple(row.get("agency_canonical_ids") or ())
        fiscal_year = row.get("fiscal_year")
        if not agencies or fiscal_year is None:
            continue  # ARRAY_LENGTH(...) >= 1 in the old SQL
        grouped[(agencies, row.get("doc_type"))][int(fiscal_year)].append(row)

    candidates = [g for g in grouped.values() if len(g) >= 2]
    random.shuffle(candidates)

    pairs: list[tuple[dict, dict]] = []
    for by_year in candidates:
        if len(pairs) >= n:
            break
        earlier, later = random.sample(sorted(by_year), 2)
        if earlier > later:
            earlier, later = later, earlier
        pairs.append(
            (random.choice(by_year[earlier]), random.choice(by_year[later]))
        )
    return pairs


_COMPARISON_PROMPT_TEMPLATE = """You are a query writer for an Arizona budget Q&A eval set.

Given TWO chunks from state budget documents (same agency, different fiscal years), write ONE comparison question that requires BOTH chunks to answer.

Chunk A ({publisher}, {doc_type}, FY{fy_a}, agency={agency}):

\"\"\"
{chunk_text_a}
\"\"\"

Chunk B ({publisher}, {doc_type}, FY{fy_b}, agency={agency}):

\"\"\"
{chunk_text_b}
\"\"\"

REQUIREMENTS:
- The question must require BOTH chunks to answer (comparison, change-over-time, side-by-side).
- Phrase it naturally; do NOT borrow rare terms from either chunk verbatim.
- Provide TWO anchor_text fragments (one from each chunk) — distinctive phrases the refresh tool will use to find successor chunks after re-ingest.

Output ONLY valid JSON with three keys: "query", "anchor_text_a", "anchor_text_b". No prose, no markdown wrapper.
"""


def synthesize_comparison_query(
    chunk_a: dict, chunk_b: dict, client: Anthropic, q_id: str
) -> EvalQuery:
    """One comparison query from a chunk PAIR."""
    agency = (
        chunk_a["agency_canonical_ids"][0]
        if chunk_a.get("agency_canonical_ids")
        else "(none)"
    )
    prompt = _COMPARISON_PROMPT_TEMPLATE.format(
        publisher=chunk_a["publisher"],
        doc_type=chunk_a["doc_type"],
        fy_a=chunk_a["fiscal_year"],
        fy_b=chunk_b["fiscal_year"],
        agency=agency,
        chunk_text_a=chunk_a["text"][:1500],
        chunk_text_b=chunk_b["text"][:1500],
    )
    response = client.messages.create(
        model=SYNTH_MODEL,
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text
    parsed = _parse_comparison_response(raw)

    return EvalQuery(
        id=q_id,
        query=parsed["query"],
        type="comparison",
        expected_chunks=[
            ExpectedChunk(
                chunk_id=chunk_a["chunk_id"],
                dimensions=QueryDimensions(
                    publisher=chunk_a["publisher"],
                    doc_type=chunk_a["doc_type"],
                    fiscal_year=chunk_a["fiscal_year"],
                    agency=agency if agency != "(none)" else None,
                ),
                anchor_text=parsed["anchor_text_a"],
            ),
            ExpectedChunk(
                chunk_id=chunk_b["chunk_id"],
                dimensions=QueryDimensions(
                    publisher=chunk_b["publisher"],
                    doc_type=chunk_b["doc_type"],
                    fiscal_year=chunk_b["fiscal_year"],
                    agency=agency if agency != "(none)" else None,
                ),
                anchor_text=parsed["anchor_text_b"],
            ),
        ],
        expected_refusal=False,
        synthesized_by=SYNTH_MODEL,
        synthesized_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
    )


def _parse_comparison_response(raw: str) -> dict:
    text = raw.strip()
    fence_match = re.match(r"```(?:json)?\s*(.+?)\s*```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1)
    obj = json.loads(text)
    if not all(k in obj for k in ("query", "anchor_text_a", "anchor_text_b")):
        raise ValueError(f"comparison response missing keys: {list(obj.keys())}")
    return obj


_REFUSAL_PROMPT = """You are a query writer for an Arizona budget Q&A eval set.

The eval set needs questions the corpus CANNOT answer, so we can verify the system correctly refuses instead of hallucinating.

The corpus contains: JLBC, AGAO, Governor's Office, and Arizona Legislature publications covering Arizona state government finances for FY25–FY27. It does NOT contain: opinion or policy recommendations, future-fiscal-year predictions beyond FY27, agencies that don't exist, local/municipal budgets, or other states.

Write ONE realistic-sounding question that the corpus CANNOT answer. Examples of out-of-scope shapes:
- Opinion: "What should Arizona's tax policy be?"
- Future-FY: "What will the AHCCCS appropriation be in FY 2030?"
- Missing entity: "What did the Arizona Office of Made-Up Programs spend in FY 2026?"
- Other state/local: "What was Tucson's general fund balance in FY 2026?"

Output ONLY valid JSON with one key: "query". No prose, no markdown wrapper.
"""


def synthesize_refusal_query(client: Anthropic, q_id: str) -> EvalQuery:
    """One refusal query — Claude generates an out-of-scope question
    independently (no chunk seed)."""
    response = client.messages.create(
        model=SYNTH_MODEL,
        max_tokens=256,
        messages=[{"role": "user", "content": _REFUSAL_PROMPT}],
    )
    raw = response.content[0].text
    text = raw.strip()
    fence_match = re.match(r"```(?:json)?\s*(.+?)\s*```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1)
    obj = json.loads(text)
    return EvalQuery(
        id=q_id,
        query=obj["query"],
        type="refusal",
        expected_chunks=[],
        expected_refusal=True,
        synthesized_by=SYNTH_MODEL,
        synthesized_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
    )


def _write_queries_yaml(queries: list[EvalQuery], path: str) -> None:
    """Write the queries list to YAML. Uses ruamel.yaml so future
    in-place edits by the refresh tool can preserve structure."""
    from ruamel.yaml import YAML

    yaml = YAML()
    yaml.default_flow_style = False
    yaml.indent(mapping=2, sequence=4, offset=2)
    serializable = [q.model_dump(exclude_none=True) for q in queries]
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(serializable, f)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Synthesize the eval query set"
    )
    parser.add_argument(
        "--lookup", type=int, default=DEFAULT_LOOKUP_COUNT,
        help="Number of lookup queries to synthesize",
    )
    parser.add_argument(
        "--comparison", type=int, default=DEFAULT_COMPARISON_COUNT,
        help="Number of comparison queries",
    )
    parser.add_argument(
        "--refusal", type=int, default=DEFAULT_REFUSAL_COUNT,
        help="Number of refusal queries",
    )
    parser.add_argument(
        "--corpus", default=DEFAULT_CORPUS,
        choices=("budget_chunks", "fiscal_note_chunks"),
        help="Which corpus table to seed queries from",
    )
    parser.add_argument(
        "--output", default="eval/queries.yaml",
        help="Path to write queries.yaml",
    )
    parser.add_argument(
        "--append", action="store_true",
        help="Append to existing queries.yaml (default: overwrite)",
    )
    args = parser.parse_args()

    client = Anthropic()  # ANTHROPIC_API_KEY from env
    queries: list[EvalQuery] = []
    next_id = 1

    if args.append:
        # Read existing queries and start IDs after the largest existing one.
        from ruamel.yaml import YAML
        yaml = YAML()
        with open(args.output) as f:
            existing = yaml.load(f) or []
        for raw in existing:
            queries.append(EvalQuery.model_validate(raw))
        # Find max existing id (assumes id format "q-NNN").
        existing_ids = [
            int(q.id.split("-")[1]) for q in queries if q.id.startswith("q-")
        ]
        next_id = (max(existing_ids) + 1) if existing_ids else 1

    print(
        f"Synthesizing {args.lookup} lookup + {args.comparison} comparison "
        f"+ {args.refusal} refusal queries using {SYNTH_MODEL}..."
    )

    # One store for the whole run — opening it twice would re-connect to
    # LanceDB and re-scan the corpus for the comparison pass.
    store = ChunkStore()

    print(f"Sampling lookup chunks from {args.corpus}...")
    lookup_chunks = sample_lookup_chunks(
        args.lookup, corpus=args.corpus, store=store
    )
    print(f"Got {len(lookup_chunks)} chunks.")
    for chunk in lookup_chunks:
        q_id = f"q-{next_id:03d}"
        next_id += 1
        try:
            query = synthesize_lookup_query(chunk, client, q_id)
            queries.append(query)
            print(f"  {q_id}: {query.query[:70]}...")
        except Exception as e:
            print(f"  {q_id}: FAILED — {e}", file=sys.stderr)

    print("Sampling comparison chunk pairs...")
    pairs = sample_comparison_pairs(
        args.comparison, corpus=args.corpus, store=store
    )
    print(f"Got {len(pairs)} pairs.")
    for chunk_a, chunk_b in pairs:
        q_id = f"q-{next_id:03d}"
        next_id += 1
        try:
            query = synthesize_comparison_query(chunk_a, chunk_b, client, q_id)
            queries.append(query)
            print(f"  {q_id}: {query.query[:70]}...")
        except Exception as e:
            print(f"  {q_id}: FAILED — {e}", file=sys.stderr)

    print("Generating refusal queries (out-of-scope)...")
    for _ in range(args.refusal):
        q_id = f"q-{next_id:03d}"
        next_id += 1
        try:
            query = synthesize_refusal_query(client, q_id)
            queries.append(query)
            print(f"  {q_id}: {query.query[:70]}...")
        except Exception as e:
            print(f"  {q_id}: FAILED — {e}", file=sys.stderr)

    _write_queries_yaml(queries, args.output)
    print(f"\nWrote {len(queries)} queries to {args.output}.")


if __name__ == "__main__":
    main()
