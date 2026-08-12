# Corpus Navigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship spec N1–N7 + N11 (`docs/superpowers/specs/2026-08-12-corpus-navigation-design.md`): a corpus map in the system prompt, a `spread` parameter on retrieve(), a `year_coverage` histogram, and the inferred-filter echo — so the AI Mode agent stops missing passages it never retrieved.

**Architecture:** Three seams. (1) `harness/corpus_map.py` builds a per-corpus inventory string from the `documents.json` sidecar and `session.py` snapshots it per conversation into a new `{{CORPUS_MAP}}` prompt placeholder. (2) `retrieval/pipeline.py` gains `retrieve_spread()` — one embed, per-group BM25+dense legs, one batched rerank, agency penalty BEFORE the per-group trim, recency never — exposed as a `spread` parameter on the existing retrieve tool. (3) `harness/tools.py`'s retrieve response gains `year_coverage` plus the inferred-filter fields the pipeline already computes.

**Tech Stack:** Python 3.12, pytest, existing fakes (`tests/test_pipeline.py` seams, `tests/test_harness_session.py` Provider/FakeExecutor). No new dependencies.

## Global Constraints

- Read the spec first: `docs/superpowers/specs/2026-08-12-corpus-navigation-design.md` (N1–N11, G-N1–G-N3).
- **Plan code blocks are sketches to RUN AND CORRECT, not text to transcribe** (this repo's recorded lesson: plan prose holds up; plan example code has divided by zero, called APIs that don't exist, and asserted the unsatisfiable). TDD every step; the test output is the authority.
- Nothing in `tests/` may open a real LanceDB directory or load ONNX weights (CLAUDE.md testing convention). Monkeypatch the two Lance legs; inject fake embedder/reranker; pass `documents=` dicts to the map builder.
- The three coupled ranking constants (`RECENCY_BOOST_PER_YEAR`, `MATCH_PENALTY`, `REFUSAL_THRESHOLD`) must not move. No code path may add a score BONUS — penalties only (`top_score` feeds refusal).
- Spread caps (spec N4): groups ≤ 8, per_group 1–5 (default 3), groups × per_group ≤ 24.
- Every non-trivial edit carries a WHY comment (Destin is a non-developer; record the evidence, not just the choice).
- Work in a worktree at `~/ask-the-budget-az-worktrees/corpus-navigation/` branched off current master; `ln -s <main-repo>/.venv <worktree>/.venv`. Sync master immediately before merging.
- Run the FULL pytest suite at the end of every task, not just the task's file: `uv run pytest -q` (expect ~2392 passed / 5 skipped at baseline, growing as tasks land).
- After all code tasks: Layer 1 eval (needs `JLBC_DATA_DIR`), then Layer 2 on the keyed machine (spends real money — Task 11 has the commands and gates).

---

### Task 1: Hoist the book-family rule to `store/book_family.py`

The corpus map must derive family from `source_url` (spec N1) — doc_id is wrong for 21 documents. The rule lives in `app/book_sections.py`; `harness/` must not import `app/`, so the rule moves to `store/` and `app/book_sections.py` re-exports it. `ingest/section_types.py` is a leaf module (no imports) and `ingest/__init__.py` is empty, so `store` importing it cannot cycle.

**Files:**
- Create: `store/book_family.py`
- Modify: `app/book_sections.py` (becomes a re-export shim)
- Test: `tests/test_book_family.py` (new; existing book-section tests stay wherever they are and must stay green)

**Interfaces:**
- Produces: `store.book_family.section_of(doc_type: str | None, source_url: str | None) -> str | None` — returns `"Baseline"`, `"Appropriations Report"`, or `None`. Exact same behavior as today's `app.book_sections.section_of`.
- `app.book_sections.section_of` continues to exist (imports from the new home) so webapp-side consumers are untouched.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_book_family.py
"""The family rule in its store/ home (spec N1 / book-sections B1-B2).

The one case that justifies source_url over doc_id: a section whose
doc_id says approps but whose published URL says baseline. 21 such
documents exist (the make_doc_id collision class); jlbc-approps-fy2022-497
is the recorded example.
"""
from store.book_family import section_of


def test_wrong_doc_id_section_resolves_by_url_not_id():
    # doc_id jlbc-approps-fy2022-497, but JLBC published it under 22baseline/
    assert section_of("detailed-list-pdf", "https://azjlbc.gov/22baseline/497.pdf") == "Baseline"


def test_approps_directories_both_spellings():
    assert section_of("s-pdf", "https://azjlbc.gov/25ar/bd10.pdf") == "Appropriations Report"
    assert section_of("s-pdf", "https://azjlbc.gov/05app/bd10.pdf") == "Appropriations Report"


def test_old_baseline_book_spelling():
    assert section_of("bd-pdf", "https://azjlbc.gov/12book1/x.pdf") == "Baseline"


def test_non_section_doc_types_are_left_alone():
    assert section_of("afr", "https://azjlbc.gov/22baseline/497.pdf") is None
    assert section_of("baseline-per-agency", "https://azjlbc.gov/22baseline/dcs.pdf") is None


def test_missing_url_returns_none():
    assert section_of("s-pdf", None) is None
    assert section_of("s-pdf", "") is None


def test_app_shim_still_exports_the_same_function():
    from app.book_sections import section_of as app_section_of
    from store.book_family import section_of as store_section_of
    assert app_section_of is store_section_of
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_book_family.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'store.book_family'`

- [ ] **Step 3: Move the implementation**

Create `store/book_family.py` by MOVING the body of `app/book_sections.py` (docstring, `_BOOK_DIR`, `_FAMILY`, `section_of`) verbatim — including the `from ingest.section_types import SECTION_DOC_TYPES` import. Add to its docstring one paragraph: moved from `app/book_sections.py` for spec N1 so `harness/corpus_map.py` can use the rule without importing `app/`; `ingest.section_types` is a leaf module, so this adds no store→ingest cycle.

Replace `app/book_sections.py`'s body with a shim that keeps the module and its public name:

```python
"""Re-export shim. The family rule moved to store/book_family.py (spec
2026-08-12 N1) so harness/corpus_map.py can use it without importing
app/. This module stays because webapp-facing code imports it by this
path; the docstring history lives at the new home."""
from __future__ import annotations

from store.book_family import section_of

__all__ = ["section_of"]
```

- [ ] **Step 4: Run the new test AND the pre-existing consumers**

Run: `uv run pytest tests/test_book_family.py -q && uv run pytest -q -k "book_section or book_family or search_provider"`
Expected: PASS everywhere. If any existing test imported the private `_FAMILY`/`_BOOK_DIR` from `app.book_sections`, update that import to the new home rather than re-exporting privates.

- [ ] **Step 5: Full suite, then commit**

Run: `uv run pytest -q`
Expected: same pass count as baseline plus the new file's tests.

```bash
git add store/book_family.py app/book_sections.py tests/test_book_family.py
git commit -m "refactor: hoist book-family rule to store/ for corpus map (spec N1)"
```

---

### Task 2: `harness/corpus_map.py` — the map builder

**Files:**
- Create: `harness/corpus_map.py`
- Test: `tests/test_corpus_map.py`

**Interfaces:**
- Produces: `build_corpus_map(corpus: str, *, documents: Mapping[str, Mapping] | None = None) -> str | None`
  - `corpus` accepts wire names (`budget`, `fiscal_notes`) or table names (`budget_chunks`, `fiscal_note_chunks`); unknown raises `ValueError`.
  - `documents=None` → reads `store.documents.load_documents()`. Tests always inject.
  - Returns a markdown table + one guidance line, or **None** when there is nothing to say (no documents / all unusable) — the caller renders the prompt fallback then.
- Consumes: `store.book_family.section_of` (Task 1), `store.documents.load_documents`.

**Row grouping (spec N1):** each budget document gets a family label:

| condition | label |
|---|---|
| `doc_type == "baseline-per-agency"` | `JLBC — Baseline (per-agency pages)` |
| `doc_type == "approps-per-agency"` | `JLBC — Appropriations Report (per-agency pages)` |
| doc_type in SECTION_DOC_TYPES and `section_of(...)` returns a family | `JLBC — {family} (book sections)` |
| doc_type in SECTION_DOC_TYPES and `section_of(...)` is None | `JLBC — book sections (unclassified)` |
| `doc_type == "afr"` | `AGAO — Annual Financial Report` |
| `doc_type == "governors-budget"` | `Governor — Executive Budget` |
| `doc_type == "budget-bill"` | `Legislature — Budget bill` |
| anything else | `{publisher} — {doc_type}` (honest raw fallback; a new doc_type must appear, not vanish) |

The fiscal-notes map is a single row over `doc_type == "fiscal-note"` documents. The budget map EXCLUDES fiscal-note documents; the fiscal-notes map includes ONLY them.

**Year-range formatting (deterministic, tested):** given the sorted set of years in a group — contiguous → `FY2021–FY2025`; ≤ 4 missing years inside the span → `FY2012–FY2027 (missing FY2013, FY2015)`; more than 4 missing → `FY2005–FY2026 (12 of 22 years)`; single year → `FY2026 only`; no year on any doc → `year unknown`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_corpus_map.py
"""Spec N1: the corpus map the model reads. Built ONLY from injected
document dicts — never the real sidecar (CLAUDE.md test convention)."""
import pytest

from harness.corpus_map import build_corpus_map


def _doc(doc_type, fy, publisher="jlbc", source_url=None):
    return {
        "doc_type": doc_type,
        "fiscal_year": fy,
        "publisher": publisher,
        "source_url": source_url,
    }


def test_contiguous_years_render_as_a_range():
    docs = {f"afr-{y}": _doc("afr", y, publisher="agao") for y in (2021, 2022, 2023, 2024, 2025)}
    out = build_corpus_map("budget", documents=docs)
    assert "AGAO — Annual Financial Report" in out
    assert "FY2021–FY2025" in out
    assert "| 5 |" in out  # document count column


def test_small_gaps_are_named():
    years = [2012, 2014, 2015, 2016, 2017]
    docs = {f"b-{y}": _doc("baseline-per-agency", y) for y in years}
    out = build_corpus_map("budget", documents=docs)
    assert "missing FY2013" in out


def test_sparse_coverage_summarizes_instead_of_listing():
    years = [2005, 2008, 2011, 2014, 2017, 2020, 2023, 2026]  # 8 of 22
    docs = {f"a-{y}": _doc("approps-per-agency", y) for y in years}
    out = build_corpus_map("budget", documents=docs)
    assert "8 of 22 years" in out


def test_single_year_reads_only():
    docs = {"bill": _doc("budget-bill", 2026, publisher="legislature")}
    out = build_corpus_map("budget", documents=docs)
    assert "FY2026 only" in out


def test_sections_grouped_by_source_url_family_not_doc_id():
    # The recorded wrong-doc_id case: baseline section published under
    # 22baseline/ — must count toward Baseline, whatever its id implies.
    docs = {
        "jlbc-approps-fy2022-497": _doc(
            "detailed-list-pdf", 2022, source_url="https://azjlbc.gov/22baseline/497.pdf"
        ),
        "s1": _doc("s-pdf", 2027, source_url="https://azjlbc.gov/27baseline/s1.pdf"),
        "bd1": _doc("bd-pdf", 2026, source_url="https://azjlbc.gov/26ar/bd1.pdf"),
    }
    out = build_corpus_map("budget", documents=docs)
    assert "Baseline (book sections)" in out
    assert "Appropriations Report (book sections)" in out
    # The wrong-id doc landed in the Baseline sections row (count 2).
    baseline_row = next(l for l in out.splitlines() if "Baseline (book sections)" in l)
    assert "| 2 |" in baseline_row


def test_budget_map_excludes_fiscal_notes_and_vice_versa():
    docs = {
        "note": _doc("fiscal-note", 2020, publisher="legislature"),
        "afr": _doc("afr", 2024, publisher="agao"),
    }
    budget = build_corpus_map("budget", documents=docs)
    notes = build_corpus_map("fiscal_notes", documents=docs)
    assert "fiscal-note" not in budget.lower() or "Fiscal notes" not in budget
    assert "Annual Financial Report" not in notes
    assert "FY2020" in notes


def test_unknown_doc_type_appears_raw_rather_than_vanishing():
    docs = {"x": _doc("agency-budget-request", 2027, publisher="governor")}
    out = build_corpus_map("budget", documents=docs)
    assert "agency-budget-request" in out


def test_empty_documents_returns_none():
    assert build_corpus_map("budget", documents={}) is None


def test_guidance_line_is_present():
    docs = {"afr": _doc("afr", 2024, publisher="agao")}
    out = build_corpus_map("budget", documents=docs)
    assert "do not search repeatedly" in out


def test_unknown_corpus_raises():
    with pytest.raises(ValueError):
        build_corpus_map("nope", documents={})


def test_table_names_accepted():
    docs = {"afr": _doc("afr", 2024, publisher="agao")}
    assert build_corpus_map("budget_chunks", documents=docs) == build_corpus_map(
        "budget", documents=docs
    )


def test_deterministic_output():
    docs = {f"d{i}": _doc("afr", 2020 + i, publisher="agao") for i in range(5)}
    assert build_corpus_map("budget", documents=docs) == build_corpus_map(
        "budget", documents=dict(reversed(list(docs.items())))
    )
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_corpus_map.py -q`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

```python
# harness/corpus_map.py
"""Builds the corpus-inventory string the system prompt carries (spec N1).

WHY the model needs this: it cannot see the corpus. Before this map it
discovered "there is no FY2020 AFR" by searching, getting weak results,
and retrying — wasted rounds, or a confident answer from the wrong
edition. The map states coverage once, so the model filters right on the
first call and refuses honestly when coverage genuinely ends.

Family comes from source_url via store.book_family, NEVER from doc_id:
doc_id parses for all 647 book sections and is WRONG for 21 of them
(the make_doc_id collision class). A map built from doc_id would claim
editions that do not exist, and the guidance line below would then
instruct the model to assert a falsehood.

Deliberately cheap to import (json-reading store.documents + the leaf
family rule); session.py calls this once per conversation.
"""
from __future__ import annotations

from typing import Any, Mapping

from ingest.section_types import SECTION_DOC_TYPES
from store.book_family import section_of

_CORPUS_ALIASES = {
    "budget": "budget",
    "budget_chunks": "budget",
    "fiscal_notes": "fiscal_notes",
    "fiscal_note_chunks": "fiscal_notes",
}

_GUIDANCE = (
    "If this table shows no edition for a year or document type, tell the "
    "analyst the corpus does not hold it — do not search repeatedly for "
    "material that does not exist."
)

_PLAIN_LABELS = {
    "baseline-per-agency": "JLBC — Baseline (per-agency pages)",
    "approps-per-agency": "JLBC — Appropriations Report (per-agency pages)",
    "afr": "AGAO — Annual Financial Report",
    "governors-budget": "Governor — Executive Budget",
    "budget-bill": "Legislature — Budget bill",
}


def _label(doc: Mapping[str, Any]) -> str:
    doc_type = doc.get("doc_type") or "unknown"
    if doc_type in _PLAIN_LABELS:
        return _PLAIN_LABELS[doc_type]
    if doc_type in SECTION_DOC_TYPES:
        family = section_of(doc_type, doc.get("source_url"))
        if family:
            return f"JLBC — {family} (book sections)"
        return "JLBC — book sections (unclassified)"
    return f"{doc.get('publisher') or 'unknown'} — {doc_type}"


def _year_phrase(years: list[int]) -> str:
    present = sorted({y for y in years if isinstance(y, int)})
    if not present:
        return "year unknown"
    if len(present) == 1:
        return f"FY{present[0]} only"
    lo, hi = present[0], present[-1]
    span = hi - lo + 1
    missing = sorted(set(range(lo, hi + 1)) - set(present))
    if not missing:
        return f"FY{lo}–FY{hi}"
    if len(missing) <= 4:
        missing_txt = ", ".join(f"FY{y}" for y in missing)
        return f"FY{lo}–FY{hi} (missing {missing_txt})"
    return f"FY{lo}–FY{hi} ({len(present)} of {span} years)"


def build_corpus_map(
    corpus: str, *, documents: Mapping[str, Mapping[str, Any]] | None = None
) -> str | None:
    resolved = _CORPUS_ALIASES.get(corpus)
    if resolved is None:
        raise ValueError(
            f"Unknown corpus {corpus!r}. Valid names: {', '.join(sorted(_CORPUS_ALIASES))}."
        )
    if documents is None:
        from store.documents import load_documents

        documents = load_documents()

    wanted_notes = resolved == "fiscal_notes"
    groups: dict[str, list[int]] = {}
    counts: dict[str, int] = {}
    for doc in documents.values():
        is_note = doc.get("doc_type") == "fiscal-note"
        if is_note != wanted_notes:
            continue
        label = "Legislature — Fiscal notes" if is_note else _label(doc)
        groups.setdefault(label, []).append(doc.get("fiscal_year"))
        counts[label] = counts.get(label, 0) + 1
    if not groups:
        return None

    lines = [
        "| Collection | Years in corpus | Docs |",
        "|---|---|---|",
    ]
    for label in sorted(groups):
        lines.append(f"| {label} | {_year_phrase(groups[label])} | {counts[label]} |")
    lines.append("")
    lines.append(_GUIDANCE)
    return "\n".join(lines)
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_corpus_map.py -q`
Expected: PASS. Adjust tests/implementation where the sketch was wrong — the test intent (labels, ranges, exclusions, determinism, None-on-empty) is the contract, exact copy is not.

- [ ] **Step 5: Sanity-check against the REAL dev corpus, then commit**

Run: `uv run python -c "import os; os.environ.setdefault('JLBC_DATA_DIR','data/insight-data'); from harness.corpus_map import build_corpus_map; print(build_corpus_map('budget')); print(); print(build_corpus_map('fiscal_notes'))"`
Expected: a readable table — JLBC rows spanning FY2005–FY2027, AFR FY2021–2025, one budget bill row, notes FY1999–FY2026. **Read it.** If a row is nonsense (e.g. a huge "unclassified" bucket), fix the labeling before proceeding — this string goes into every conversation. Also check its size: `... | wc -c` should be well under ~4 KB.

```bash
git add harness/corpus_map.py tests/test_corpus_map.py
git commit -m "feat: corpus-map builder from the documents sidecar (spec N1)"
```

---

### Task 3: `{{CORPUS_MAP}}` placeholder in the prompt template

**Files:**
- Modify: `harness/prompt.py` (`build_system_prompt` signature + `_substitute` values)
- Modify: `harness/system-prompt.md` (add the map section)
- Test: `tests/test_harness_prompt.py` (extend)

**Interfaces:**
- Produces: `build_system_prompt(*, corpus: str, tier: str, corpus_map: str | None = None) -> str`. `corpus_map=None` (or empty) renders the fallback sentence; a string renders verbatim in place of `{{CORPUS_MAP}}`.
- Constant `CORPUS_MAP_FALLBACK` exported from `harness/prompt.py` so tests and callers share the exact sentence.
- `harness/prompt.py` stays import-light: it never imports `harness.corpus_map` or `store` — the caller supplies the string (spec N2).

- [ ] **Step 1: Write the failing tests** (add to `tests/test_harness_prompt.py`)

```python
def test_corpus_map_renders_when_supplied():
    from harness.prompt import build_system_prompt

    out = build_system_prompt(
        corpus="budget", tier="standard", corpus_map="| MAPMARKER | FY2005–FY2026 | 9 |"
    )
    assert "MAPMARKER" in out
    assert "{{CORPUS_MAP}}" not in out


def test_corpus_map_falls_back_when_absent():
    from harness.prompt import CORPUS_MAP_FALLBACK, build_system_prompt

    out = build_system_prompt(corpus="budget", tier="standard")
    assert CORPUS_MAP_FALLBACK in out
    assert "{{CORPUS_MAP}}" not in out


def test_fiscal_notes_prompt_also_carries_the_placeholder_section():
    from harness.prompt import build_system_prompt

    out = build_system_prompt(corpus="fiscal_notes", tier="standard", corpus_map="NOTEMAP")
    assert "NOTEMAP" in out
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_harness_prompt.py -q -k corpus_map`
Expected: FAIL — unexpected keyword `corpus_map` / unknown placeholder.

- [ ] **Step 3: Implement**

In `harness/prompt.py`:

```python
# Near the other module constants:
CORPUS_MAP_FALLBACK = (
    "(The corpus inventory is unavailable right now. Use "
    "list_filter_values to check what exists before concluding the "
    "corpus lacks something.)"
)
```

Change the signature and the substitution dict:

```python
def build_system_prompt(*, corpus: str, tier: str, corpus_map: str | None = None) -> str:
    ...
    return _substitute(
        selected,
        {
            "CORPUS_MAP": corpus_map or CORPUS_MAP_FALLBACK,
            "REFUSAL_THRESHOLD": str(REFUSAL_THRESHOLD),
            # ... existing entries unchanged ...
        },
    )
```

In `harness/system-prompt.md`, add a section OUTSIDE any `{{#when}}` block (the caller builds the map for the conversation's own corpus, so one placeholder serves both), placed near the existing retrieval-recipes/filter material:

```markdown
## What this corpus contains

The table below is generated from the live corpus at the start of this
conversation. It is the authoritative statement of which collections and
fiscal years exist.

{{CORPUS_MAP}}
```

WHY placement matters: keep it AFTER the tool instructions the model reads first, and remember the whole file is the cacheable prefix — nothing here may vary within a conversation.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_harness_prompt.py tests/test_harness_prompt_caching.py -q`
Expected: PASS, including the pre-existing `test_the_real_system_prompt_renders_identically_every_time` (no map → deterministic fallback).

- [ ] **Step 5: Full suite + commit**

```bash
uv run pytest -q
git add harness/prompt.py harness/system-prompt.md tests/test_harness_prompt.py
git commit -m "feat: CORPUS_MAP placeholder with fallback in the system prompt (spec N1/N2)"
```

---

### Task 4: Snapshot the map per conversation (session + route + eval runner wiring)

**Files:**
- Modify: `harness/session.py` (`HarnessSession.__init__` + `_system_prompt_text`)
- Modify: `app/routes/conversations.py` (~line 372, where `HarnessSession(` is constructed)
- Modify: `eval/run_agent_eval.py` (~line 92, same)
- Test: `tests/test_harness_prompt_caching.py` (extend), `tests/test_conversations_route.py` or nearest route-test file (extend)

**Interfaces:**
- Produces: `HarnessSession(..., corpus_map: str | None = None)`. When set, `_system_prompt_text()` calls the builder as `builder(corpus=..., tier=..., corpus_map=self._corpus_map)`; when None, the builder is called WITHOUT the kwarg (existing fake builders in tests take only `corpus`/`tier` and must not break).
- The snapshot rule (spec N3): the string is computed ONCE, at session construction time, by the CALLER — never re-read mid-conversation.

- [ ] **Step 1: Write the failing tests** (add to `tests/test_harness_prompt_caching.py`)

```python
def test_corpus_map_is_snapshotted_and_prefix_stays_identical_across_turns():
    """Spec N3: the map is per-conversation state. Even if the sidecar
    changes mid-conversation, this session's prefix must not move."""
    provider = Provider(
        lambda: sse(text_chunk("ok"), finish_chunk("stop"), usage_chunk()),
        lambda: sse(text_chunk("ok"), finish_chunk("stop"), usage_chunk()),
    )
    calls = []

    def builder(*, corpus, tier, corpus_map=None):
        calls.append(corpus_map)
        return f"PROMPT[{corpus_map}]"

    session = _session(provider, system_prompt=None, prompt_builder=builder, corpus_map="MAP-V1")
    session.send_turn("q1")
    session.send_turn("q2")

    assert calls and all(c == "MAP-V1" for c in calls)
    assert _prefix(provider.bodies[0]) == _prefix(provider.bodies[1])


def test_sessions_without_a_map_call_the_builder_without_the_kwarg():
    """Existing fake builders take (corpus, tier) only; a session built
    with no map must not pass a kwarg they don't accept."""
    provider = Provider(lambda: sse(text_chunk("ok"), finish_chunk("stop"), usage_chunk()))
    seen = {}

    def old_style_builder(*, corpus, tier):
        seen["called"] = True
        return "OLD"

    _session(provider, system_prompt=None, prompt_builder=old_style_builder).send_turn("q")
    assert seen.get("called")


def test_two_sessions_with_the_same_map_share_a_prefix():
    """Spec N3 amended property: identical across conversations WHILE the
    sidecar stamp (here: the injected map string) is unchanged."""
    provider = Provider(
        lambda: sse(text_chunk("ok"), finish_chunk("stop"), usage_chunk()),
        lambda: sse(text_chunk("ok"), finish_chunk("stop"), usage_chunk()),
    )

    def builder(*, corpus, tier, corpus_map=None):
        return f"PROMPT[{corpus_map}]"

    _session(provider, conversation_id="a", system_prompt=None,
             prompt_builder=builder, corpus_map="MAP-V1").send_turn("q1")
    _session(provider, conversation_id="b", system_prompt=None,
             prompt_builder=builder, corpus_map="MAP-V1").send_turn("q2")
    assert _prefix(provider.bodies[0]) == _prefix(provider.bodies[1])
```

Note: `_session()` in that file passes `system_prompt=SYSTEM_PROMPT`; the helper needs `system_prompt=None` pass-through via `**over` (it already forwards `**over` — passing `system_prompt=None` overrides).

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_harness_prompt_caching.py -q -k corpus_map`
Expected: FAIL — unexpected keyword `corpus_map` on `HarnessSession`.

- [ ] **Step 3: Implement the session side**

In `HarnessSession.__init__`, after `self._prompt_builder = prompt_builder`:

```python
        # Spec N3: the corpus map is SNAPSHOTTED per conversation. The
        # caller (route / eval runner) computes it once at creation;
        # nothing here ever re-reads the sidecar mid-conversation,
        # because the system prompt is the S22 cacheable prefix and a
        # mid-conversation change would be a silent 10x cache miss.
        self._corpus_map = corpus_map
```

(and `corpus_map: str | None = None` in the signature, keyword-only section).

In `_system_prompt_text`, replace the builder call:

```python
            if self._corpus_map is not None:
                prompt = builder(corpus=self.corpus, tier=self.tier, corpus_map=self._corpus_map)
            else:
                # No kwarg at all: injected fake builders accept only
                # (corpus, tier), and the real builder falls back on its
                # own when the map is absent.
                prompt = builder(corpus=self.corpus, tier=self.tier)
```

- [ ] **Step 4: Wire the two construction sites**

In `app/routes/conversations.py`, next to the `HarnessSession(` construction (~372), compute the snapshot:

```python
    # Spec N1/N3: inventory snapshot for this conversation's prompt.
    # Degrades to None (prompt renders its fallback sentence) — a broken
    # sidecar must not block conversations, per the map's whole design.
    try:
        from harness.corpus_map import build_corpus_map

        corpus_map = build_corpus_map(corpus)
    except Exception as err:
        print(f"conversations: corpus map unavailable — {err}", file=sys.stderr)
        corpus_map = None
```

and pass `corpus_map=corpus_map` to the constructor. Mirror the same (small helper or inline) in `eval/run_agent_eval.py`'s `HarnessSession(` call — the Layer 2 run must exercise the map, or Task 11 measures nothing.

Add a route-level test (in the conversations route test file, following its existing fixture style): monkeypatch `harness.corpus_map.build_corpus_map` to raise, create a conversation, assert the route still returns 200 — the degrade path is the contract.

- [ ] **Step 5: Full suite + commit**

```bash
uv run pytest -q
git add harness/session.py app/routes/conversations.py eval/run_agent_eval.py tests/test_harness_prompt_caching.py tests/<route-test-file>
git commit -m "feat: per-conversation corpus-map snapshot wired into prompt build (spec N3)"
```

---

### Task 5: `doc_id` filter dimension (prerequisite for by=doc_id spread)

**Files:**
- Modify: `retrieval/types.py` (`RetrievalFilters`: add `doc_id: list[str] | None = None`, include in `is_empty`)
- Modify: `retrieval/search_lance.py` (`_where` passes it)
- Modify: `store/chunk_store.py` (`filter_expr` accepts `doc_id=` and emits the same ANY()-against-scalar shape `doc_type` uses)
- Test: `tests/test_chunk_store_filters.py` or wherever `filter_expr` is currently tested (find with `grep -rn "filter_expr" tests/`)

**Interfaces:**
- Produces: `RetrievalFilters(doc_id=["jlbc-approps-fy2026-adc"])` filters both legs to those documents. NOT exposed on `RetrievalRequest` or the tool filter schema — spread is its only consumer (YAGNI; widening the tool surface is a separate decision).

- [ ] **Step 1: Locate the existing `filter_expr` tests and add**

```python
def test_filter_expr_doc_id():
    expr = store.filter_expr(doc_id=["d1", "d2"])
    assert "doc_id" in expr and "d1" in expr and "d2" in expr


def test_filters_is_empty_sees_doc_id():
    from retrieval.types import RetrievalFilters

    assert not RetrievalFilters(doc_id=["d1"]).is_empty()
    assert RetrievalFilters().is_empty()
```

Follow the file's existing fixture style exactly (it tests SQL-string assembly, no real Lance).

- [ ] **Step 2: Run to verify failure** — `uv run pytest -q -k "filter_expr or is_empty"` → FAIL.

- [ ] **Step 3: Implement** — mirror the `doc_type` handling in all three files (scalar string column, ANY-of list, SQL-escaped the same way). Keep parameter order alphabetical-consistent with the existing signature style.

- [ ] **Step 4: Verify pass, full suite.**

- [ ] **Step 5: Commit**

```bash
git add retrieval/types.py retrieval/search_lance.py store/chunk_store.py tests/<filter-test-file>
git commit -m "feat: doc_id filter dimension for spread retrieval (spec N4)"
```

---### Task 6: `retrieve_spread()` in the pipeline

**Files:**
- Modify: `retrieval/pipeline.py` (add `SpreadSpec`, `retrieve_spread`, `RetrievalResult.spread_groups`)
- Modify: `retrieval/__init__.py` (export both)
- Test: `tests/test_pipeline_spread.py` (new; reuse `tests/test_pipeline.py`'s `Seams`/`FakeEmbedder`/`FakeReranker` by import)

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True)
class SpreadSpec:
    by: str                      # "fiscal_year" | "doc_id"
    groups: tuple                # tuple[int, ...] or tuple[str, ...], 1..8 entries
    per_group: int = 3           # 1..5

def retrieve_spread(
    req: RetrievalRequest,
    spread: SpreadSpec,
    *,
    store=None, embedder=None, reranker=None,
) -> RetrievalResult
```

- `RetrievalResult` gains `spread_groups: list[dict] = field(default_factory=list)` — one entry per REQUESTED group, in request order: `{"value": <year-or-doc_id>, "top_score": <float-or-None>, "count": <int>}`. An empty group appears with `count: 0, top_score: None` (spec: visible, never dropped).
- Behavioral contract (spec N5):
  - `req.query` embedded ONCE regardless of group count.
  - Per group: both legs run with the group value merged into `req.to_filters()` (`fiscal_year=[year]` exact — deliberately NOT the ±1 adjacent-year window: the model named the group, wobbling it would blur cross-group comparison; `doc_id=[id]` for the other axis). Per-group RRF fuse with `fused_top_k = max(2 * per_group, 6)`.
  - **No S21/Q2 inference of any kind on the spread path** — no year parsing, no doc-type hard-filter inference. Weak agency/doc-type parsing DOES run, for the penalty only (that is the "rerank + agency penalty" score the spec's groups summary promises).
  - ONE `reranker.rerank(query, all_candidates, top_k=len(all_candidates))` call over the concatenated per-group candidates (dedup by chunk_id across groups is NOT needed for `fiscal_year`/`doc_id` axes — a chunk has exactly one year and one doc — assert that assumption in a comment).
  - `apply_match_penalty` over the FULL reranked candidate list BEFORE the per-group trim (spec review fix #2).
  - **`apply_recency_boost` is never called** (spec review fix #3).
  - Then partition by group value (`chunk.fiscal_year` / `chunk.doc_id`) and keep the top `per_group` per group by penalized score.
  - `chunks` = concatenation in REQUEST group order, each group's chunks score-descending. `top_score` = max chunk score, `NO_RESULTS_TOP_SCORE` when nothing anywhere.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_pipeline_spread.py
"""Spec N4/N5. Same discipline as test_pipeline.py: legs monkeypatched,
fake embedder/reranker, nothing opens Lance or loads ONNX."""
import pytest

from retrieval import RetrievalRequest
from retrieval.pipeline import SpreadSpec, retrieve_spread
from tests.test_pipeline import FakeEmbedder, FakeReranker, _chunk


def _year_chunk(cid, fy, score=1.0):
    c = _chunk(cid, score=score)
    return type(c)(**{**c.__dict__, "fiscal_year": fy})  # dataclasses.replace also fine


class SpreadSeams:
    """Legs that answer per-filter, so each group sees its own slice."""

    def __init__(self, by_year):
        self.by_year = by_year          # {year: [chunks]}
        self.bm25_calls = []

    def bm25(self, query, *, store, corpus, top_k, filters):
        self.bm25_calls.append(filters)
        return list(self.by_year.get((filters.fiscal_year or [None])[0], []))

    def dense(self, query_vector, *, store, corpus, top_k, filters):
        return []


@pytest.fixture
def year_seams(monkeypatch):
    s = SpreadSeams({
        2025: [_year_chunk("a-2025", 2025, 3.0), _year_chunk("b-2025", 2025, 2.0),
               _year_chunk("c-2025", 2025, 1.5), _year_chunk("d-2025", 2025, 1.0)],
        2026: [_year_chunk("a-2026", 2026, 2.5)],
        2020: [],
    })
    monkeypatch.setattr("retrieval.pipeline.bm25_query_lance", s.bm25)
    monkeypatch.setattr("retrieval.pipeline.dense_query_lance", s.dense)
    return s


def _spread(**kw):
    return SpreadSpec(**{"by": "fiscal_year", "groups": (2025, 2026, 2020), "per_group": 2, **kw})


def test_groups_come_back_in_request_order_with_counts(year_seams):
    result = retrieve_spread(
        RetrievalRequest(query="ahcccs"), _spread(),
        embedder=FakeEmbedder(), reranker=FakeReranker(),
    )
    assert [g["value"] for g in result.spread_groups] == [2025, 2026, 2020]
    assert [g["count"] for g in result.spread_groups] == [2, 1, 0]
    assert result.spread_groups[2]["top_score"] is None  # empty group visible


def test_per_group_trim_caps_each_group(year_seams):
    result = retrieve_spread(
        RetrievalRequest(query="q"), _spread(per_group=2),
        embedder=FakeEmbedder(), reranker=FakeReranker(),
    )
    from_2025 = [c for c in result.chunks if c.fiscal_year == 2025]
    assert len(from_2025) == 2  # 4 candidates, trimmed to 2


def test_embed_happens_once_for_all_groups(year_seams):
    embedder = FakeEmbedder()
    retrieve_spread(RetrievalRequest(query="q"), _spread(),
                    embedder=embedder, reranker=FakeReranker())
    assert embedder.calls == 1  # add a counter to FakeEmbedder if absent


def test_recency_is_never_applied(year_seams, monkeypatch):
    """Spec review fix #3: a recency pass would skew cross-group
    top_scores by up to ~13.6 logits and lie about old groups."""
    def boom(*a, **kw):
        raise AssertionError("recency must not run on the spread path")
    monkeypatch.setattr("retrieval.pipeline.apply_recency_boost", boom)
    retrieve_spread(RetrievalRequest(query="q"), _spread(),
                    embedder=FakeEmbedder(), reranker=FakeReranker())


def test_penalty_runs_before_the_trim(year_seams, monkeypatch):
    """Spec review fix #2: a chunk at position per_group+1 that the
    penalty would PROMOTE must be able to enter the group's results.
    Penalize the two leaders; the trailing chunks must win the trim."""
    from retrieval import pipeline

    def penalize_leaders(chunks, *, agency_ids, doc_types, weight=None):
        return sorted(
            (type(c)(**{**c.__dict__, "score": c.score - (5.0 if c.chunk_id in ("a-2025", "b-2025") else 0.0)})
             for c in chunks),
            key=lambda c: -c.score,
        )

    monkeypatch.setattr(pipeline, "apply_match_penalty", penalize_leaders)
    monkeypatch.setattr(pipeline, "parse_query_agencies", lambda q: [type("M", (), {"value": "agency:x"})()])
    result = retrieve_spread(RetrievalRequest(query="q"), _spread(per_group=2),
                             embedder=FakeEmbedder(), reranker=FakeReranker())
    ids_2025 = {c.chunk_id for c in result.chunks if c.fiscal_year == 2025}
    assert ids_2025 == {"c-2025", "d-2025"}


def test_no_year_inference_on_spread(year_seams):
    """The query names FY2019; the groups say 2025/2026/2020. Groups win,
    and no filter beyond the group's own year may reach the legs."""
    retrieve_spread(RetrievalRequest(query="fy2019 budget"), _spread(),
                    embedder=FakeEmbedder(), reranker=FakeReranker())
    years_seen = {tuple(f.fiscal_year or []) for f in year_seams.bm25_calls}
    assert years_seen == {(2025,), (2026,), (2020,)}


def test_top_score_is_max_and_penalty_only(year_seams):
    result = retrieve_spread(RetrievalRequest(query="q"), _spread(),
                             embedder=FakeEmbedder(), reranker=FakeReranker())
    assert result.top_score == max(c.score for c in result.chunks)


def test_all_groups_empty_returns_no_results_sentinel(monkeypatch):
    monkeypatch.setattr("retrieval.pipeline.bm25_query_lance", lambda *a, **kw: [])
    monkeypatch.setattr("retrieval.pipeline.dense_query_lance", lambda *a, **kw: [])
    from retrieval.pipeline import NO_RESULTS_TOP_SCORE

    result = retrieve_spread(RetrievalRequest(query="q"), _spread(),
                             embedder=FakeEmbedder(), reranker=FakeReranker())
    assert result.chunks == []
    assert result.top_score == NO_RESULTS_TOP_SCORE
    assert [g["count"] for g in result.spread_groups] == [0, 0, 0]
```

Note the FakeReranker in `test_pipeline.py` may score by dict lookup — passing scores through unchanged (identity rerank) is what these tests want; extend the fake if needed rather than writing a new one.

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_pipeline_spread.py -q` → FAIL (no `SpreadSpec`).

- [ ] **Step 3: Implement `retrieve_spread`**

Sketch (verify every referenced name against the real file — the default `retrieve()` above it is the style guide):

```python
def retrieve_spread(
    req: RetrievalRequest,
    spread: SpreadSpec,
    *,
    store: ChunkStore | None = None,
    embedder: LocalEmbedder | None = None,
    reranker: LocalReranker | None = None,
    bm25_top_k: int = BM25_TOP_K,
    dense_top_k: int = DENSE_TOP_K,
    rrf_k: int = 60,
) -> RetrievalResult:
    """One query, searched once per group, reranked as one batch (spec N5).

    The structural fix for edition monoculture: FY2026 cannot be crowded
    out of the pool when FY2026 IS its own pool.

    Deliberate differences from retrieve(), each load-bearing:
    * NO query-understanding inference — the groups are the instruction.
      Weak agency/doc-type parsing still runs, but only to feed the
      penalty, never a filter.
    * NO recency: every fiscal_year group is a year filter (the default
      path already skips recency under one), and per-group top_scores
      must stay comparable ACROSS groups — an anchor-relative recency
      pass would depress an old group by more than the whole logit range
      and read as "FY2010 has nothing" when FY2010 holds a perfect hit.
    * Agency penalty runs over the FULL candidate set BEFORE the
      per-group trim — an adjustment can only reorder chunks it can see
      (same lesson as the rerank-then-trim comment in retrieve()).
    """
    if not req.query.strip() or not spread.groups:
        return RetrievalResult()
    if store is None:
        store = _get_store()
    if embedder is None:
        embedder = _get_embedder()

    base = req.to_filters()
    qvec = embedder.embed_one(req.query, input_type="query")
    overfetch = max(2 * spread.per_group, 6)

    candidates_by_group: dict[Any, list[RetrievedChunk]] = {}
    for value in spread.groups:
        if spread.by == "fiscal_year":
            active = dataclass_replace(base, fiscal_year=[int(value)])
        else:
            active = dataclass_replace(base, doc_id=[str(value)])
        bm25_hits = bm25_query_lance(
            req.query, store=store, corpus=req.corpus, top_k=bm25_top_k, filters=active
        )
        dense_hits = dense_query_lance(
            qvec, store=store, corpus=req.corpus, top_k=dense_top_k, filters=active
        )
        candidates_by_group[value] = rrf_fuse(
            [RankedList(chunks=bm25_hits), RankedList(chunks=dense_hits)],
            k=rrf_k, top_k=overfetch,
        )

    all_candidates = [c for group in candidates_by_group.values() for c in group]
    if not all_candidates:
        return RetrievalResult(
            spread_groups=[{"value": v, "top_score": None, "count": 0} for v in spread.groups]
        )

    if reranker is None:
        reranker = _get_reranker()
    reranked = reranker.rerank(req.query, all_candidates, top_k=len(all_candidates))

    weak_agencies = [m.value for m in parse_query_agencies(req.query)] if not req.agency_canonical_id else []
    weak_doc_types = [m.value for m in parse_query_doc_types(req.query)] if not req.doc_type else []
    if weak_agencies or weak_doc_types:
        reranked = apply_match_penalty(reranked, agency_ids=weak_agencies, doc_types=weak_doc_types)

    score_of = {c.chunk_id: c.score for c in reranked}
    scored_by_group = {
        value: sorted(
            (dataclass_replace(c, score=score_of[c.chunk_id]) for c in chunks),
            key=lambda c: -c.score,
        )[: spread.per_group]
        for value, chunks in candidates_by_group.items()
    }
    # ^ NB: RetrievedChunk may not be a dataclass replace target the same
    # way — reuse however rerank() returns scored chunks; the point is
    # "top per_group by penalized score, per group, in request order".

    chunks: list[RetrievedChunk] = []
    groups_summary: list[dict[str, Any]] = []
    for value in spread.groups:
        kept = scored_by_group.get(value, [])
        chunks.extend(kept)
        groups_summary.append({
            "value": value,
            "top_score": kept[0].score if kept else None,
            "count": len(kept),
        })

    return RetrievalResult(
        chunks=chunks,
        top_score=max((c.score for c in chunks), default=NO_RESULTS_TOP_SCORE),
        reranker_scores=[c.score for c in chunks],
        fused_count=len(all_candidates),
        spread_groups=groups_summary,
    )
```

Watch for: the reranker returns rescored chunk objects — partition THOSE by `chunk.fiscal_year` / `chunk.doc_id` directly instead of round-tripping a score map if that's simpler and correct; verify with the tests. Chunks whose `fiscal_year` is None can only appear via the doc_id axis — partition by the axis attribute, and drop nothing silently.

- [ ] **Step 4: Verify pass** — `uv run pytest tests/test_pipeline_spread.py tests/test_pipeline.py -q` → PASS (default-path tests untouched and green).

- [ ] **Step 5: Full suite + commit**

```bash
uv run pytest -q
git add retrieval/pipeline.py retrieval/__init__.py tests/test_pipeline_spread.py
git commit -m "feat: retrieve_spread — per-group pools, one rerank, penalty-before-trim, no recency (spec N5)"
```

---

### Task 7: The `spread` tool parameter

**Files:**
- Modify: `harness/constants.py` (caps), `harness/tools.py` (schema + coercion + executor + response)
- Test: `tests/test_harness_tools.py` (extend)

**Interfaces:**
- Constants: `SPREAD_MAX_GROUPS = 8`, `SPREAD_MIN_PER_GROUP = 1`, `SPREAD_MAX_PER_GROUP = 5`, `SPREAD_DEFAULT_PER_GROUP = 3`, `SPREAD_MAX_TOTAL = 24` in `harness/constants.py`.
- Schema: `spread` property on `_RETRIEVE_SCHEMA.parameters.properties`:

```python
"spread": {
    "type": "object",
    "additionalProperties": False,
    "required": ["by", "groups"],
    "description": (
        "Structured multi-group search: run this one query separately "
        "inside each named group and return the best passages from EACH, "
        "so near-identical editions cannot crowd each other out. Use for "
        "multi-year comparisons ('X across FY2022-2026'), for 'which "
        "years mention X', and to force edition diversity. Bounded: at "
        f"most {SPREAD_MAX_GROUPS} groups x {SPREAD_MAX_PER_GROUP} per "
        f"group, {SPREAD_MAX_TOTAL} passages total. Counts as your one "
        "first search but is not truncated by the first-call sample cap."
    ),
    "properties": {
        "by": {"type": "string", "enum": ["fiscal_year", "doc_id"]},
        "groups": {
            "type": "array", "minItems": 1, "maxItems": SPREAD_MAX_GROUPS,
            "description": (
                "The group values: four-digit fiscal years for "
                "by=fiscal_year, doc_ids (from earlier results) for "
                "by=doc_id."
            ),
            "items": {},
        },
        "per_group": {
            "type": "integer",
            "minimum": SPREAD_MIN_PER_GROUP, "maximum": SPREAD_MAX_PER_GROUP,
            "description": f"Passages per group (default {SPREAD_DEFAULT_PER_GROUP}).",
        },
    },
},
```

- Coercion `_spread(raw) -> SpreadSpec | None`: `None` in → `None` out; year groups run through the same int coercion as `_fiscal_years` (the string-"2027" trap, spec N4); doc_id groups must be non-empty strings; duplicate group values rejected with an actionable message; `groups × per_group ≤ SPREAD_MAX_TOTAL` enforced with the arithmetic in the error text.
- Executor `_retrieve`: when spread is present — build `SpreadSpec`, call `retrieve_spread(request_without_top_k_or_intent, spec)`; **the call consumes the first-call slot but is never capped** (spec N6); `intent`/`top_k`/`deep_dive` are rejected alongside `spread` with an error naming the conflict (one breadth mechanism per call — silently ignoring them would be the haunted-tool failure).
- Response additions: every chunk dict gains `"group": <its axis value>`; top-level `"spread": {"by": ..., "groups": [{value, top_score, count}, ...]}`.

- [ ] **Step 1: Write the failing tests** (extend `tests/test_harness_tools.py`, using its existing executor fixture/fake-store style)

```python
def test_spread_response_carries_groups_and_per_chunk_group(...):
    # retrieve with spread over (2025, 2026); patched retrieve_spread
    # returns two chunks in 2025, one in 2026 → response["spread"]["groups"]
    # mirrors it and each chunk carries "group".

def test_spread_is_exempt_from_the_first_call_cap_but_consumes_it(...):
    # First call WITH spread: no "first_call_capped" in response and all
    # chunks returned. Second call WITHOUT spread: also not capped —
    # the slot was consumed.

def test_spread_group_year_strings_are_coerced(...):
    # groups: ["2025", "2026"] reaches SpreadSpec as (2025, 2026).

def test_spread_caps_are_enforced_with_actionable_errors(...):
    # 9 groups → error naming 8; per_group 6 → error; 8 groups x 4 = 32
    # → error naming the 24 total; duplicate group → error.

def test_spread_conflicts_with_top_k_intent_deep_dive(...):
    # Passing spread + top_k → ok:false naming both fields.

def test_spread_chunks_mint_aliases_like_any_retrieve(...):
    # Chunks from a spread call appear in executor.alias_map.
```

Write these fully against the file's existing helpers (it already fakes `retrieve` via monkeypatching `harness.tools.retrieve`; add the same for `retrieve_spread`).

- [ ] **Step 2: Verify failure.** `uv run pytest tests/test_harness_tools.py -q -k spread` → FAIL.

- [ ] **Step 3: Implement** per the interface block above. The first-call logic becomes:

```python
        with self._lock:
            is_first = self._first_retrieve_pending
            self._first_retrieve_pending = False
        # Spec N6: a spread call is already self-limiting (groups x
        # per_group <= 24) and structured; truncating it to the 5-chunk
        # sample would break its contract and force the extra round the
        # feature exists to remove. It still consumes the slot — it IS a
        # real first search. Layer 2 watches input_tokens_mean for abuse;
        # revert the exemption if it shows up there.
        capped = is_first and not effective_deep_dive and spread_spec is None
```

- [ ] **Step 4: Verify pass; run the whole tools file.** `uv run pytest tests/test_harness_tools.py -q`

- [ ] **Step 5: Full suite + commit**

```bash
uv run pytest -q
git add harness/constants.py harness/tools.py tests/test_harness_tools.py
git commit -m "feat: spread parameter on the retrieve tool, first-call-cap exempt (spec N4/N6)"
```

---

### Task 8: `year_coverage` on the default retrieve path

**Files:**
- Modify: `retrieval/pipeline.py` (`RetrievalResult.year_coverage: dict[int, int]`, counted in `retrieve()`)
- Modify: `harness/tools.py` (emit when non-empty)
- Test: `tests/test_pipeline.py` + `tests/test_harness_tools.py` (extend)

**Interfaces:**
- `RetrievalResult.year_coverage: dict[int, int] = field(default_factory=dict)` — candidate CHUNK count per fiscal year over the union (by chunk_id) of the bm25 and dense legs, before fusion trims to 20 (spec N7: it reports what the pool cap hid). Chunks with `fiscal_year=None` are skipped. Populated on the DEFAULT path only — `retrieve_spread` already reports per-group structure.
- Tool response: `"year_coverage": {"2005": 41, ...}` (string keys — JSON), present only when non-empty.

- [ ] **Step 1: Failing tests**

```python
# tests/test_pipeline.py addition
def test_year_coverage_counts_the_legs_not_the_final_pool(seams, ...):
    # Seams: bm25 returns 30 chunks across FY2005..2026, dense returns 10
    # overlapping ones; fused pool trims to 20. year_coverage must count
    # the UNION of the legs (dedup by chunk_id), so years absent from the
    # final chunks still appear.
    ...
    assert set(result.year_coverage) > {c.fiscal_year for c in result.chunks}

def test_year_coverage_skips_yearless_chunks(...):
    ...

# tests/test_harness_tools.py addition
def test_year_coverage_reaches_the_response_with_string_keys(...):
    ...
def test_year_coverage_absent_when_empty(...):
    ...
```

- [ ] **Step 2: Verify failure.**

- [ ] **Step 3: Implement.** In `retrieve()`, right after the final `_search` call succeeds (both the first-try and dropped-filter retry paths flow through the same tail — compute from the surviving `bm25_hits`/`dense_hits` locals):

```python
    seen: dict[str, int | None] = {}
    for hit in [*bm25_hits, *dense_hits]:
        seen.setdefault(hit.chunk_id, hit.fiscal_year)
    year_coverage: dict[int, int] = {}
    for fy in seen.values():
        if isinstance(fy, int):
            year_coverage[fy] = year_coverage.get(fy, 0) + 1
```

and pass `year_coverage=year_coverage` into both `RetrievalResult(...)` constructions that return results (the no-candidates early return keeps the default empty dict). In `tools.py::_retrieve`, after `inferred_fiscal_years` handling:

```python
        if result.year_coverage:
            # Spec N7: what the pool cap hid — candidate distribution
            # WITHIN the active filters, keyed by year. Approximate
            # relevance signal (pre-rerank), for filter-vs-spread
            # decisions; the prompt says how to read it.
            response["year_coverage"] = {
                str(year): count for year, count in sorted(result.year_coverage.items())
            }
```

- [ ] **Step 4: Verify pass; Step 5: Full suite + commit**

```bash
uv run pytest -q
git add retrieval/pipeline.py harness/tools.py tests/test_pipeline.py tests/test_harness_tools.py
git commit -m "feat: year_coverage histogram from the candidate legs (spec N7)"
```

---

### Task 9: Echo the inferred filters (N11)

**Files:**
- Modify: `harness/tools.py` (response fields)
- Test: `tests/test_harness_tools.py` (extend)

**Interfaces:** in `_retrieve`'s response, following the existing `inferred_fiscal_years` pattern (present only when non-empty):
- `"inferred_doc_types"` — list, the doc-type HARD filter the pipeline guessed and applied.
- `"dropped_filters"` — list, guessed filters that matched nothing and were abandoned (only ever `["doc_type"]` today).
- `"preferred_agencies"` — list, from `result.inferred_agencies`. **Named `preferred_agencies` on the wire deliberately** (spec N11 requires wording that marks it a preference; a self-describing field name is that wording, structurally — a future consumer cannot read `preferred_agencies` as a filter).

- [ ] **Step 1: Failing tests**

```python
def test_inferred_doc_type_filter_is_visible_in_the_response(...):
    # fake retrieve returns RetrievalResult(inferred_doc_types=["afr"]) →
    # response["inferred_doc_types"] == ["afr"]

def test_dropped_filters_are_visible(...):

def test_agency_preference_uses_the_preference_name(...):
    # inferred_agencies=["agency:adc"] → response["preferred_agencies"];
    # "inferred_agencies" is NOT a response key.

def test_absent_when_empty(...):
    # A result with none of them set adds none of the keys.
```

- [ ] **Step 2: Verify failure. Step 3: Implement** (mirror the `inferred_fiscal_years` block, one comment citing N11 and the haunted-tool line). **Step 4: Verify pass.**

- [ ] **Step 5: Full suite + commit**

```bash
uv run pytest -q
git add harness/tools.py tests/test_harness_tools.py
git commit -m "feat: echo inferred doc-type filter, dropped filters, agency preference (spec N11)"
```

---

### Task 10: System-prompt guidance (N9)

**Files:**
- Modify: `harness/system-prompt.md`
- Test: `tests/test_harness_prompt.py` (renders + key phrases present in the right corpus variants)

**Content to add** (final wording is the implementer's to polish; the CLAIMS are fixed):

1. **Under the retrieval-recipes area, a spread subsection** (outside `{{#when}}` — both corpora get it): use `spread` with `by: "fiscal_year"` for any question comparing years or asking "across years"/"over time"; use it when an analyst asks for the NEWEST edition of something and plain search keeps returning older ones; use `by: "doc_id"` to sample several specific documents already identified. One spread call replaces several sequential searches; it is exempt from the first-call sample but still counts as the first search.
2. **year_coverage line:** "Every search response may carry `year_coverage` — the approximate distribution of candidate passages by fiscal year WITHIN the current filters, including years the returned passages don't show. If it reveals years you need that the results lack, filter to them or use `spread`."
3. **Inferred-filter lines:** `inferred_doc_types` means the system guessed a document-type filter from your wording and APPLIED it — if that guess is wrong, re-search with an explicit `filters.doc_type`. `dropped_filters` means a guess found nothing and was abandoned. `preferred_agencies` is a ranking preference only — nothing was filtered out.
4. **Corpus-map reading guidance** already landed with Task 3's section; extend it with one sentence tying it to spread: "For comparisons across years, check the map first — spreading over a year with no edition wastes a group."

- [ ] **Step 1: Write failing tests** — assert the rendered budget prompt contains `spread`, `year_coverage`, `preferred_agencies`, and that `{{` never appears; assert the fiscal-notes prompt renders without error and carries the spread guidance too.

- [ ] **Step 2: Verify failure. Step 3: Write the sections. Step 4: Verify pass** — including the whole caching test file (the prompt is still static per (corpus, tier, map)).

- [ ] **Step 5: Full suite + commit**

```bash
uv run pytest -q
git add harness/system-prompt.md tests/test_harness_prompt.py
git commit -m "docs(prompt): spread, year_coverage, inferred-filter guidance (spec N9)"
```

---

### Task 11: Verification — suites, Layer 1, Layer 2

- [ ] **Step 1: Full local gates**

```bash
uv run pytest -q                       # everything, count recorded
cd webapp && npx tsc -b && npx vitest run && cd ..   # untouched, but merge discipline
```

Expected: all green. The webapp is untouched by this plan; if a vitest spec fails, that is drift from master, not this work — investigate before blaming the branch.

- [ ] **Step 2: Layer 1 eval (free, needs `JLBC_DATA_DIR`)**

```bash
uv run python -m eval.run_eval
```

Gate **G-N1**: recall@5 / @15 / @20 and refusal precision byte-comparable to the current baseline (88.10 / 100 / 100 / 60% as of 2026-08-03) — spread is opt-in and year_coverage is metadata, so ANY movement on the default path is a stop signal: find the cause before proceeding. Commit the `eval/results/<...>.{json,md}` files with the branch.

- [ ] **Step 3: Merge prep** — sync master (`git fetch origin && git pull origin master` in the main repo, re-merge into the worktree branch), re-run `uv run pytest -q`, then merge AND push per CLAUDE.md. Clean up the worktree.

- [ ] **Step 4: Layer 2 (keyed machine, spends real money — G-N2)**

On the keyed machine, post-merge:

```bash
uv run python -m eval.run_agent_eval --subset smoke        # ~$0.15-0.30
uv run python -m eval.score_agent_run <run-dir>            # free
uv run python -m eval.compare_agent_runs <baseline> <run>  # vs 2026-08-02T0900Z-0b08221 (smoke rows)
```

Read the compare before spending on `full`. Expected direction: `key_fact_rate` up (the point of all of this); watch `input_tokens_mean` and `retrieval_efficiency` for the N6 token-blowup failure mode, and `marker_coverage_mean` / `tag_accuracy_mean` (spread chunks must tag and verify like any retrieve chunk). Then:

```bash
uv run python -m eval.run_full_layer2 --subset full        # run + score + judge, ~$1.50-3
```

Gate **G-N2** (from the spec): `key_fact_rate` not worse than baseline, no citation-metric regression, `input_tokens_mean` within ~15% of baseline unless `key_fact_rate` improved to justify it. Commit `manifest.json` / `scores.*` / `judge.json` / the compare report; transcripts stay gitignored. Update STATUS.md with the numbers and the outcome — including a revert of the N6 cap exemption if that is what the numbers say.

If this session has no key, stop after Step 3 and write the Layer 2 half into a `PROMPT-corpus-navigation-baseline.md` handoff at the repo root, modeled on `PROMPT-attested-citation-baseline.md`, and record that in STATUS.md as the outstanding piece.

---

## Self-review record

- Spec coverage: N1→T2, N2→T2/T3, N3→T4, N4→T7 (+T5 prerequisite), N5→T6, N6→T7, N7→T8, N9→T10, N10→structural (spread opt-in, default path asserted unchanged in T6/T8 tests + G-N1), N11→T9. G-N1/G-N2/G-N3 → T11 + T4 tests.
- The S22 stamp-conditioned amendment (spec N3) is realized as: session snapshots whatever the caller passed; the caching tests pin within-conversation and same-map cross-conversation identity. No test reads `sidecar_stamp()` directly — the map STRING is the stamp's proxy, which is the actual cache-relevant object.
- Type consistency: `SpreadSpec` (T6) is what `_spread` (T7) constructs; `RetrievalResult.spread_groups` / `.year_coverage` (T6/T8) are what `tools.py` reads (T7/T8); `build_corpus_map` (T2) is what T4's wiring calls; `corpus_map=` kwarg name is identical on `build_system_prompt` (T3) and `HarnessSession` (T4).
