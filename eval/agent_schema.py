"""Query-set schema for the Layer 2 agent-loop eval.

Separate from eval/schema.py (Layer 1) on purpose: Layer 1 queries pin
ground-truth chunk_ids for a deterministic retrieval regression detector;
Layer 2 queries pin ANSWER-level key facts for a stochastic agent eval.
Mixing the two schemas would invite cross-diffing runs that measure
different things (the same reason Layer 1 prefixes fiscal-note results).
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from ruamel.yaml import YAML


class KeyFact(BaseModel):
    """One mechanically checkable fact a correct answer must contain.

    kind=currency matches numbers with formatting tolerance
    ($1,234.5M == 1234.5 million); string is a case-insensitive
    substring; regex is a case-insensitive search pattern.
    """

    # Forbid unknown fields — a typo'd key (e.g. "vlaue" for "value") in the
    # hand-authored YAML would otherwise be silently dropped by pydantic's
    # default extra="ignore", leaving this fact permanently unchecked and
    # the query scoring a false pass/fail with no error anywhere.
    model_config = ConfigDict(extra="forbid")

    kind: Literal["currency", "string", "regex"]
    value: str


class AgentQuery(BaseModel):
    # Forbid unknown fields — a typo'd key (e.g. "keyfacts" for "key_facts")
    # would otherwise load silently with the field's default ([]) instead of
    # erroring, turning a real query into a permanent, invisible failure
    # (always 0 key facts checked) that nobody would notice without diffing
    # the YAML against this schema by hand.
    model_config = ConfigDict(extra="forbid")

    id: str
    question: str
    corpus: Literal["budget", "fiscal_notes"] = "budget"
    tier: Literal["standard", "deep_research"] = "standard"
    # shape drives authoring quotas and per-shape score breakdowns.
    shape: Literal["lookup", "comparison", "analyze", "memo", "refusal", "historical"]
    # subset tags select what a run includes: smoke (~10), full (all
    # standard-tier), dr-probe (the 4 deep_research queries).
    subsets: list[str] = Field(default_factory=lambda: ["full"])
    should_refuse: bool = False
    key_facts: list[KeyFact] = Field(default_factory=list)
    judge_notes: str = ""


def load_agent_queries(path: str | Path) -> list[AgentQuery]:
    yaml = YAML(typ="safe")
    with open(path, encoding="utf-8") as f:
        raw = yaml.load(f) or []
    queries = [AgentQuery.model_validate(q) for q in raw]
    ids = [q.id for q in queries]
    if len(ids) != len(set(ids)):
        # Duplicate ids would silently overwrite each other's transcripts
        # (one file per id), so a run would LOOK complete while missing data.
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        raise ValueError(f"duplicate query ids: {dupes}")
    return queries
