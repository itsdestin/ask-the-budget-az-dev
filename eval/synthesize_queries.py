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
