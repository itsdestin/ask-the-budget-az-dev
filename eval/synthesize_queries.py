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

Invocation:
    uv run python -m eval.synthesize_queries           # full set (35)
    uv run python -m eval.synthesize_queries --append  # add to existing
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from typing import Any

from anthropic import Anthropic

from eval.schema import EvalQuery, ExpectedChunk, QueryDimensions
# Re-export the pooled connection helper at module scope so tests can
# monkeypatch it as `eval.synthesize_queries.get_connection`. The pool
# helper runs `register_vector` on each connection — required for the
# refresh tool's cosine fallback (find_cosine_match casts a Python list
# to ::vector) and harmless here.
from db.connection import get_connection

# The model the synthesizer uses. Hardcoded — bumping this is a
# deliberate decision, not a config tweak.
SYNTH_MODEL = "claude-opus-4-7"

# How many lookup queries to synthesize per invocation by default.
DEFAULT_LOOKUP_COUNT = 25
DEFAULT_COMPARISON_COUNT = 5
DEFAULT_REFUSAL_COUNT = 5


def sample_lookup_chunks(n: int) -> list[dict]:
    """Sample n chunks balanced across publishers.

    Uses ORDER BY RANDOM() with publisher-grouped LIMITs to roughly
    balance representation. Doesn't try to be perfectly balanced — the
    synthesizer's prompt is robust to over-representing one publisher.
    """
    per_publisher = max(1, n // 4)  # 4 publishers in v1 corpus
    sql = """
        WITH ranked AS (
            SELECT
                c.chunk_id,
                c.text,
                d.publisher,
                c.doc_type,
                c.fiscal_year,
                c.agency_canonical_ids,
                ROW_NUMBER() OVER (
                    PARTITION BY d.publisher ORDER BY RANDOM()
                ) AS rn
            FROM chunks c
            JOIN documents d ON d.doc_id = c.doc_id
            WHERE c.token_count > 80  -- filter degenerate chunks
        )
        SELECT chunk_id, text, publisher, doc_type, fiscal_year,
               agency_canonical_ids
        FROM ranked
        WHERE rn <= %s
        ORDER BY RANDOM()
        LIMIT %s
    """
    with get_connection() as conn:
        cur = conn.execute(sql, (per_publisher, n))
        return cur.fetchall()


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


def sample_comparison_pairs(n: int) -> list[tuple[dict, dict]]:
    """Find chunk pairs that stamp to the same agency across two
    different fiscal years. Returns up to n pairs."""
    sql = """
        WITH paired AS (
            SELECT
                a.chunk_id AS a_id, a.text AS a_text,
                b.chunk_id AS b_id, b.text AS b_text,
                d.publisher AS publisher,
                a.doc_type AS doc_type,
                a.fiscal_year AS a_fy, b.fiscal_year AS b_fy,
                a.agency_canonical_ids AS agencies
            FROM chunks a
            JOIN chunks b ON b.agency_canonical_ids = a.agency_canonical_ids
                          AND b.fiscal_year > a.fiscal_year
                          AND b.doc_type = a.doc_type
            JOIN documents d ON d.doc_id = a.doc_id
            WHERE a.token_count > 80 AND b.token_count > 80
              AND ARRAY_LENGTH(a.agency_canonical_ids, 1) >= 1
            ORDER BY RANDOM()
            LIMIT %s
        )
        SELECT * FROM paired
    """
    with get_connection() as conn:
        rows = conn.execute(sql, (n,)).fetchall()
    pairs = []
    for r in rows:
        chunk_a = {
            "chunk_id": r["a_id"],
            "text": r["a_text"],
            "publisher": r["publisher"],
            "doc_type": r["doc_type"],
            "fiscal_year": r["a_fy"],
            "agency_canonical_ids": r["agencies"],
        }
        chunk_b = {
            "chunk_id": r["b_id"],
            "text": r["b_text"],
            "publisher": r["publisher"],
            "doc_type": r["doc_type"],
            "fiscal_year": r["b_fy"],
            "agency_canonical_ids": r["agencies"],
        }
        pairs.append((chunk_a, chunk_b))
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

    print("Sampling lookup chunks from corpus...")
    lookup_chunks = sample_lookup_chunks(args.lookup)
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
    pairs = sample_comparison_pairs(args.comparison)
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
