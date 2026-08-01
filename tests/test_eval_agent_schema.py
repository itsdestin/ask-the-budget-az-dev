"""Schema tests for the Layer 2 agent-eval query set.

Why: the query file is hand-and-agent-authored YAML; a typo'd field must
fail loudly at load time, not silently score as 0.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from eval.agent_schema import AgentQuery, KeyFact, load_agent_queries

VALID = """
- id: aq-001
  question: What was ADC's FY 2025 General Fund appropriation?
  corpus: budget
  tier: standard
  shape: lookup
  subsets: [smoke, full]
  should_refuse: false
  key_facts:
    - kind: currency
      value: "$1,391,157,700"
    - kind: string
      value: "Department of Corrections"
  judge_notes: "AFR figure preferred over Baseline per accuracy hierarchy."
"""


def _write(tmp_path, text):
    p = tmp_path / "queries.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_valid_entry_loads_with_defaults(tmp_path):
    queries = load_agent_queries(_write(tmp_path, VALID))
    assert len(queries) == 1
    q = queries[0]
    assert q.id == "aq-001"
    assert q.corpus == "budget"
    assert q.tier == "standard"
    assert q.shape == "lookup"
    assert q.key_facts[0] == KeyFact(kind="currency", value="$1,391,157,700")


def test_defaults_applied(tmp_path):
    minimal = """
- id: aq-002
  question: Is out of scope?
  shape: refusal
  should_refuse: true
"""
    q = load_agent_queries(_write(tmp_path, minimal))[0]
    assert q.corpus == "budget" and q.tier == "standard"
    assert q.subsets == ["full"] and q.key_facts == [] and q.judge_notes == ""


def test_unknown_corpus_rejected(tmp_path):
    bad = VALID.replace("corpus: budget", "corpus: postgres")
    with pytest.raises(ValidationError):
        load_agent_queries(_write(tmp_path, bad))


def test_duplicate_ids_rejected(tmp_path):
    with pytest.raises(ValueError, match="duplicate"):
        load_agent_queries(_write(tmp_path, VALID + VALID))


def test_misspelled_key_facts_field_rejected(tmp_path):
    # A typo'd "keyfacts:" (missing underscore) must fail loudly at load
    # time — with extra="ignore" (pydantic's default) this would silently
    # load with key_facts=[] and the query would score as a permanent,
    # invisible failure. See module docstring.
    bad = VALID.replace("key_facts:", "keyfacts:")
    with pytest.raises(ValidationError):
        load_agent_queries(_write(tmp_path, bad))
