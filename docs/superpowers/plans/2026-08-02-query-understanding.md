# Query Understanding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An analyst typing `doc baseline`, `dema ar` or `ahcccs 27ar` gets that agency's documents, of that type, newest first.

**Architecture:** Three query-side parsers mirroring the existing `retrieval/query_year.py`, feeding filters that ALREADY exist on `RetrievalRequest` and already reach LanceDB. An unambiguous match becomes a hard filter; an ambiguous one becomes a post-rerank penalty on non-matching chunks. A hard filter that returns nothing retries unfiltered and reports that it was dropped.

**Tech Stack:** Python 3.12, pytest, rapidfuzz (already a dependency, used by `chunking/entity_stamper.py`), PyYAML.

**Spec:** `docs/superpowers/specs/2026-08-02-query-understanding-design.md` (Q1–Q6).

---

## Global Constraints

Every task's requirements implicitly include this section.

- **Work in a worktree:** `git worktree add ~/ask-the-budget-az-worktrees/query-understanding -b query-understanding origin/master`.
- **Baseline to beat, measured 2026-08-02 on the finished corpus:** recall@5 **73.81%**, recall@15 **97.62%**, recall@20 **97.62%**, refusal precision **60%**, p95 **852 ms**. Gate G1 is recall@15 ≥ 90% and recall@20 ≥ 95%.
- **Shipped constants that must not move without recalibration:** `RECENCY_BOOST_PER_YEAR = 0.85` (`retrieval/recency.py`), `REFUSAL_THRESHOLD = 1.46` (`harness/constants.py`). They are COUPLED — `tests/test_recency.py::test_the_shipped_weight_and_refusal_threshold_move_together` fails if one moves alone.
- **A boost must be a PENALTY on non-matching chunks, never a bonus on matching ones.** `top_score` after boosting is what `REFUSAL_THRESHOLD` is compared against; a bonus would inflate it and silently weaken refusal.
- **Run the full suite before each commit:** `.venv/bin/python -m pytest tests/ -q` (baseline **1986 passed**).
- **`eval/run_eval.py` is MANDATORY** — this changes `retrieval/`. Commit the `eval/results/` files alongside the code.
- **Annotate non-trivial code with a WHY comment.** The project owner is a non-developer who relies on comments.
- The corpus is at `data/insight-data/`; from a worktree, export `JLBC_DATA_DIR=/home/destin/YouCoded/Projects/ask-the-budget-az-dev/data/insight-data` and treat it as **read-only**.

---

## File Structure

| File | Responsibility |
|---|---|
| `samples/entity-catalog.yaml` | **Modify.** New `aliases:` field per agency; fix the `agency:des` garbage variant. |
| `chunking/agency_catalog.py` | **Modify.** Surface `aliases` and the slug on `AgencyEntry`. |
| `retrieval/query_match.py` | **Create.** The shared `Match`/`Confidence` types both parsers return. One place, so filter-vs-boost logic is not written twice. |
| `retrieval/query_agency.py` | **Create.** Resolve agencies from query text. |
| `retrieval/query_doc_type.py` | **Create.** Resolve doc types from query text. |
| `retrieval/query_year.py` | **Modify.** JLBC shorthand (`27ar`, `26baseline`). |
| `retrieval/pipeline.py` | **Modify.** Wire parsers in; filter-with-fallback; echo what was inferred. |
| `retrieval/agency_boost.py` | **Create.** Post-rerank penalty for the low-confidence path. |
| `scripts/draft_agency_aliases.py` | **Create.** Generates the review checklist for Destin. |

---

## Task 1: Catalog gains an `aliases` field, a slug variant, and loses its garbage

**Files:**
- Modify: `chunking/agency_catalog.py`, `samples/entity-catalog.yaml`
- Test: `tests/test_agency_catalog.py`

**Interfaces:**
- Produces: `AgencyEntry` gains `aliases: list[str]` (analyst shorthand, reviewed) and keeps `slug`. `name_variants` is UNCHANGED in meaning — publisher-observed printed names only.

**Why a new field rather than appending to `name_variants`:** that list is derived from `names_observed_jlbc`, which is provenance — "names actually printed in JLBC documents". Putting `DOC` there would make the provenance a lie and corrupt the stamper's evidence trail.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_agency_catalog.py  (append)
from chunking.agency_catalog import load_agency_catalog


def test_every_agency_exposes_its_slug_as_an_alias():
    """JLBC's own URL slug IS an acronym: 26AR/adc.pdf. Derived, not invented."""
    cat = load_agency_catalog()
    adc = cat["agency:adc"]
    assert "adc" in [a.lower() for a in adc.aliases]


def test_aliases_are_separate_from_publisher_observed_names():
    """name_variants is PROVENANCE — names really printed by JLBC. An analyst
    acronym is not one, and must not contaminate it."""
    cat = load_agency_catalog()
    adc = cat["agency:adc"]
    assert adc.name_variants == ["Corrections, State Department of"]
    assert "adc" not in [v.lower() for v in adc.name_variants]


def test_the_des_extraction_garbage_variant_is_gone():
    """'pp y, Economic Security, Department of' is PDF-extraction debris that
    reached the catalog. It would fuzzy-match noise."""
    cat = load_agency_catalog()
    for v in cat["agency:des"].name_variants:
        assert "pp y" not in v


def test_no_variant_or_alias_is_extraction_debris():
    """Guard the whole catalog, not just the one we happened to find."""
    cat = load_agency_catalog()
    for entry in cat.values():
        for text in list(entry.name_variants) + list(entry.aliases):
            assert len(text) >= 2, f"{entry.canonical_id}: {text!r}"
            assert not text.startswith(("pp y", "y, ")), f"{entry.canonical_id}: {text!r}"
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_agency_catalog.py -q`
Expected: FAIL — `AgencyEntry` has no attribute `aliases`.

- [ ] **Step 3: Implement**

In `chunking/agency_catalog.py`, add to the dataclass and the loader:

```python
@dataclass
class AgencyEntry:
    canonical_id: str
    canonical_name: str
    slug: str | None
    name_variants: list[str]
    # Analyst shorthand — "DOC", "DEMA" — plus the JLBC slug. Deliberately
    # SEPARATE from name_variants, which is provenance (names really printed
    # in JLBC documents). An acronym an analyst says out loud is not one.
    aliases: list[str] = field(default_factory=list)
```

```python
def _aliases(entry: dict) -> list[str]:
    """Analyst-facing shorthand for one agency.

    The slug is included unconditionally because it is DERIVED, not invented:
    JLBC's own URLs are /26AR/adc.pdf, so `adc` is already how the publisher
    abbreviates this agency. Reviewed colloquial acronyms come from the
    catalog's own `aliases:` key — see scripts/draft_agency_aliases.py.
    """
    out: list[str] = []
    slug = entry.get("slug")
    if slug:
        out.append(slug)
    for alias in entry.get("aliases") or []:
        if alias and alias not in out:
            out.append(alias)
    return out
```

Wire `aliases=_aliases(entry)` into the `AgencyEntry(...)` construction.

Then fix the YAML: find the `agency:des` block and delete the
`pp y, Economic Security, Department of` key from its `names_observed_jlbc`.

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_agency_catalog.py -q`
Expected: PASS

- [ ] **Step 5: Confirm the stamper is unaffected**

The stamper reads `name_variants`; this task did not change its meaning, and
removing one garbage variant can only reduce false matches.

Run: `.venv/bin/python -m pytest tests/test_entity_stamper.py tests/ -q`
Expected: `1990 passed` (1986 + 4 new)

- [ ] **Step 6: Commit**

```bash
git add chunking/agency_catalog.py samples/entity-catalog.yaml tests/test_agency_catalog.py
git commit -m "feat(catalog): analyst aliases as their own field; drop extraction debris"
```

---

## Task 2: The shared match type

**Files:**
- Create: `retrieval/query_match.py`
- Test: `tests/test_query_match.py`

**Interfaces:**
- Produces: `Confidence` (str enum: `"exact"`, `"weak"`); `Match` dataclass with `value: str`, `confidence: Confidence`, `matched_text: str`; `is_filterable(matches: Sequence[Match]) -> bool` returning True only when every match is `exact`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_query_match.py
from retrieval.query_match import Confidence, Match, is_filterable


def test_all_exact_matches_are_filterable():
    ms = [Match("agency:adc", Confidence.EXACT, "corrections")]
    assert is_filterable(ms) is True


def test_one_weak_match_makes_the_whole_set_boost_only():
    """Mixed confidence must not hard-filter: the weak one could be wrong,
    and a wrong hard filter empties the page."""
    ms = [Match("agency:adc", Confidence.EXACT, "corrections"),
          Match("agency:ade", Confidence.WEAK, "ed")]
    assert is_filterable(ms) is False


def test_no_matches_is_not_filterable():
    assert is_filterable([]) is False
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_query_match.py -q`
Expected: FAIL — no module `retrieval.query_match`.

- [ ] **Step 3: Implement**

```python
"""Shared shape for anything parsed out of a query (spec Q2).

WHY this is one module rather than a convention repeated in each parser: the
filter-versus-boost decision is the safety-critical part of this feature, and
two copies of it would eventually disagree.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Sequence


class Confidence(StrEnum):
    EXACT = "exact"   # unambiguous: hard filter is safe
    WEAK = "weak"     # fuzzy, ambiguous, or a stoplisted word: boost only


@dataclass(frozen=True)
class Match:
    value: str            # e.g. "agency:adc" or "approps-per-agency"
    confidence: Confidence
    matched_text: str     # the span of the query that produced it


def is_filterable(matches: Sequence[Match]) -> bool:
    """True only when EVERY match is exact.

    Deliberately all-or-nothing. A set containing one weak match must not
    hard-filter, because the weak one could be wrong and a wrong hard filter
    returns an empty page for a question the analyst asked in good faith.
    """
    return bool(matches) and all(m.confidence is Confidence.EXACT for m in matches)
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_query_match.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add retrieval/query_match.py tests/test_query_match.py
git commit -m "feat(retrieval): shared Match/Confidence type for query parsers"
```

---

## Task 3: The agency parser (spec Q1, Q2)

**Files:**
- Create: `retrieval/query_agency.py`
- Test: `tests/test_query_agency.py`

**Interfaces:**
- Consumes: `retrieval.query_match.{Match, Confidence}`, `chunking.agency_catalog.load_agency_catalog`.
- Produces: `parse_query_agencies(query: str) -> list[Match]`; `AMBIGUOUS_ALIASES: frozenset[str]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_query_agency.py
from retrieval.query_agency import AMBIGUOUS_ALIASES, parse_query_agencies
from retrieval.query_match import Confidence


def _ids(query):
    return [m.value for m in parse_query_agencies(query)]


def test_the_full_canonical_name_is_an_exact_match():
    ms = parse_query_agencies("corrections, state department of budget")
    assert ms[0].value == "agency:adc"
    assert ms[0].confidence is Confidence.EXACT


def test_a_partial_but_distinctive_name_resolves():
    assert "agency:adc" in _ids("corrections baseline")


def test_the_jlbc_slug_resolves_exactly():
    """JLBC's own URL shorthand: /26AR/adc.pdf"""
    ms = parse_query_agencies("adc baseline")
    assert ms[0].value == "agency:adc"
    assert ms[0].confidence is Confidence.EXACT


def test_a_stoplisted_alias_matches_but_only_weakly():
    """'doc' is both the Corrections acronym and an ordinary English word.
    It must still MATCH -- it just must not hard-filter."""
    assert "doc" in AMBIGUOUS_ALIASES
    ms = parse_query_agencies("doc baseline")
    assert [m.value for m in ms] == ["agency:adc"]
    assert ms[0].confidence is Confidence.WEAK


def test_an_alias_shared_by_two_agencies_is_weak():
    """Ambiguity is decided by the catalog, not by a hand-written list."""
    ms = parse_query_agencies("juvenile corrections")
    assert all(m.confidence is Confidence.WEAK for m in ms) or len(ms) == 1


def test_a_query_naming_no_agency_returns_nothing():
    assert parse_query_agencies("what changed since last year") == []


def test_an_empty_query_returns_nothing():
    assert parse_query_agencies("") == []
    assert parse_query_agencies("   ") == []


def test_matching_is_case_insensitive():
    assert _ids("AHCCCS baseline") == _ids("ahcccs baseline")


def test_a_short_token_does_not_fuzzy_match_everything():
    """rapidfuzz on 2-3 character tokens matches far too much. The floor
    exists so 'ar' does not resolve to 'Agriculture, Arizona Department of'."""
    assert "agency:ada" not in _ids("dema ar")
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_query_agency.py -q`
Expected: FAIL — no module `retrieval.query_agency`.

- [ ] **Step 3: Implement**

Build `parse_query_agencies` with this resolution order, most confident first:

1. **Canonical name or a publisher-observed `name_variant`** appearing in the
   normalized query → `EXACT`.
2. **A distinctive single word from a canonical name** (e.g. "corrections")
   that belongs to exactly one agency → `EXACT`.
3. **An alias** (slug or reviewed acronym) matching exactly one agency →
   `EXACT`, unless it is in `AMBIGUOUS_ALIASES` → `WEAK`.
4. **rapidfuzz `token_set_ratio` ≥ 85** against canonical names, mirroring the
   floor `chunking/entity_stamper.py` already uses → `WEAK`.

`AMBIGUOUS_ALIASES` starts as `frozenset({"doc", "ar", "afr", "des", "pp"})`
— aliases that are also ordinary words or other agencies' shorthand — with a
comment explaining that it is hand-maintained and why (spec Q2).

Guard short tokens: do not fuzzy-match anything under 4 characters, or "ar"
matches half the catalog.

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_query_agency.py -q`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add retrieval/query_agency.py tests/test_query_agency.py
git commit -m "feat(retrieval): resolve agencies from query text, confidence-tiered"
```

---

## Task 4: The document-type parser (spec Q1)

**Files:**
- Create: `retrieval/query_doc_type.py`
- Test: `tests/test_query_doc_type.py`

**Interfaces:**
- Produces: `parse_query_doc_types(query: str) -> list[Match]`.

The ten real values: `approps-per-agency`, `baseline-per-agency`,
`detailed-list-pdf`, `governors-budget`, `s-pdf`, `afr`, `bd-pdf`,
`topic-pdf`, `bh-pdf`, `budget-bill`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_query_doc_type.py
from retrieval.query_doc_type import parse_query_doc_types
from retrieval.query_match import Confidence


def _vals(q):
    return [m.value for m in parse_query_doc_types(q)]


def test_baseline_resolves():
    assert "baseline-per-agency" in _vals("ahcccs baseline")


def test_appropriations_report_resolves():
    assert "approps-per-agency" in _vals("ahcccs appropriations report")


def test_approps_report_shorthand_resolves():
    assert "approps-per-agency" in _vals("ahcccs approps report")


def test_afr_resolves_and_is_not_confused_with_ar():
    assert _vals("agao afr") == ["afr"]
    assert "afr" not in _vals("dema ar")


def test_bare_ar_is_weak_because_it_is_two_letters():
    ms = parse_query_doc_types("dema ar")
    assert [m.value for m in ms] == ["approps-per-agency"]
    assert ms[0].confidence is Confidence.WEAK


def test_executive_budget_resolves():
    assert "governors-budget" in _vals("governor's executive budget fy2027")


def test_a_query_naming_no_type_returns_nothing():
    assert parse_query_doc_types("ahcccs provider rates") == []
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_query_doc_type.py -q`
Expected: FAIL — no module.

- [ ] **Step 3: Implement**

A phrase table mapping natural language onto the ten values. Longest phrase
wins, so "appropriations report" is not shadowed by "report". Multi-word
phrases are `EXACT`; bare two-letter shorthand (`ar`) is `WEAK` for the same
reason `doc` is.

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_query_doc_type.py -q`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add retrieval/query_doc_type.py tests/test_query_doc_type.py
git commit -m "feat(retrieval): resolve document type from query text"
```

---

## Task 5: JLBC shorthand — `27ar`, `26baseline` (spec Q5)

**Files:**
- Modify: `retrieval/query_year.py`, `retrieval/query_doc_type.py`
- Test: `tests/test_query_year.py`, `tests/test_query_doc_type.py`

**Interfaces:**
- Produces: `retrieval.query_year.parse_jlbc_shorthand(query: str) -> list[tuple[int, str]]` returning `(fiscal_year, doc_type)` pairs. `parse_query_years` and `parse_query_doc_types` both consume it.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_query_year.py  (append)
from retrieval.query_year import parse_jlbc_shorthand, parse_query_years


def test_the_corpus_url_convention_is_understood():
    """azjlbc.gov/26AR/508.pdf and /21baseline/adc.pdf — this is how an
    analyst who lives in these files writes a citation."""
    assert parse_jlbc_shorthand("ahcccs 27ar") == [(2027, "approps-per-agency")]
    assert parse_jlbc_shorthand("adc 21baseline") == [(2021, "baseline-per-agency")]


def test_shorthand_feeds_the_year_parser():
    assert 2027 in parse_query_years("ahcccs 27ar")


def test_shorthand_is_case_insensitive():
    assert parse_jlbc_shorthand("AHCCCS 27AR") == [(2027, "approps-per-agency")]


def test_a_bare_two_digit_number_is_not_shorthand():
    """'27' alone is not a JLBC file reference and must not become FY2027
    here — the existing two-digit rule already governs that case."""
    assert parse_jlbc_shorthand("27 positions") == []


def test_an_implausible_year_is_rejected():
    assert parse_jlbc_shorthand("99ar") == []
```

```python
# tests/test_query_doc_type.py  (append)
def test_shorthand_yields_the_document_type_too():
    assert "approps-per-agency" in _vals("ahcccs 27ar")
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_query_year.py tests/test_query_doc_type.py -q`
Expected: FAIL — no `parse_jlbc_shorthand`.

- [ ] **Step 3: Implement**

```python
_JLBC_SHORTHAND = re.compile(
    r"(?<![\w$])(\d{2})\s?(ar|baseline)(?![\w])", re.IGNORECASE
)

_SHORTHAND_DOC_TYPE = {"ar": "approps-per-agency", "baseline": "baseline-per-agency"}


def parse_jlbc_shorthand(query: str) -> list[tuple[int, str]]:
    """`(fiscal_year, doc_type)` pairs from JLBC's own URL convention.

    WHY this exists: the corpus's source URLs are literally
    azjlbc.gov/26AR/508.pdf and /21baseline/adc.pdf, so an analyst who works
    from those files types "27ar" without thinking about it. Reusing the
    publisher's own shorthand costs one regex and removes a whole class of
    zero-result query.

    Requires the type suffix. A bare "27" stays with the ordinary two-digit
    rule, which needs an "FY" or apostrophe prefix — otherwise every
    "27 positions" in a budget table becomes a fiscal year.
    """
    out: list[tuple[int, str]] = []
    for match in _JLBC_SHORTHAND.finditer(query or ""):
        year = _expand_two_digit(int(match.group(1)))
        if year is None:
            continue
        out.append((year, _SHORTHAND_DOC_TYPE[match.group(2).lower()]))
    return out
```

Then have `parse_query_years` fold in `y for y, _ in parse_jlbc_shorthand(query)`,
and `parse_query_doc_types` fold in the doc types as `EXACT` matches (the
suffix makes them unambiguous, unlike a bare "ar").

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_query_year.py tests/test_query_doc_type.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add retrieval/query_year.py retrieval/query_doc_type.py tests/test_query_year.py tests/test_query_doc_type.py
git commit -m "feat(retrieval): understand JLBC URL shorthand — 27ar, 26baseline"
```

---

## Task 6: Wire the parsers into the pipeline, with fallback (spec Q3)

**Files:**
- Modify: `retrieval/pipeline.py`
- Test: `tests/test_pipeline_query_understanding.py`

**Interfaces:**
- Consumes: all three parsers.
- Produces: `RetrievalResult` gains `inferred_agencies: list[str]`, `inferred_doc_types: list[str]`, `dropped_filters: list[str]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_pipeline_query_understanding.py
import pytest

from retrieval.pipeline import RetrievalRequest, retrieve

pytestmark = pytest.mark.corpus     # follow the existing corpus-marker convention


def test_an_exact_agency_hard_filters():
    res = retrieve(RetrievalRequest(query="corrections baseline",
                                    corpus="budget_chunks", top_k=8))
    assert res.inferred_agencies == ["agency:adc"]
    assert all("adc" in c.doc_id or "jc" in c.doc_id for c in res.chunks)


def test_a_stoplisted_alias_does_not_hard_filter_but_still_helps():
    """'doc baseline' returned ZERO Corrections documents before this work."""
    res = retrieve(RetrievalRequest(query="doc baseline",
                                    corpus="budget_chunks", top_k=8))
    assert res.inferred_agencies == []          # weak -> not applied as a filter
    assert any("adc" in c.doc_id for c in res.chunks)   # ...but boosted in


def test_a_hard_filter_that_matches_nothing_retries_unfiltered():
    """An analyst must never get a blank page because the parser was
    confidently wrong."""
    res = retrieve(RetrievalRequest(query="corrections 1altair-report",
                                    corpus="budget_chunks", top_k=5))
    assert res.chunks != []
    assert "doc_type" in res.dropped_filters or "agency" in res.dropped_filters


def test_a_callers_explicit_filter_always_wins():
    """Same precedence the year parser already has: an explicit filter means
    the caller decided, and inference must not override it."""
    res = retrieve(RetrievalRequest(query="corrections baseline",
                                    agency_canonical_id=["agency:ade"],
                                    corpus="budget_chunks", top_k=5))
    assert res.inferred_agencies == []


def test_the_six_shorthand_queries_return_their_agency():
    """The fixture this whole spec came from."""
    cases = [("ahcccs baseline", "axs"), ("doc baseline", "adc"),
             ("ahcccs appropriations report", "axs"), ("dema ar", "ema"),
             ("ahcccs 27ar", "axs"), ("ahcccs 2027 approps report", "axs")]
    for query, slug in cases:
        res = retrieve(RetrievalRequest(query=query, corpus="budget_chunks", top_k=10))
        assert any(slug in c.doc_id for c in res.chunks), f"{query!r} found no {slug}"
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_pipeline_query_understanding.py -q`
Expected: FAIL — `RetrievalResult` has no `inferred_agencies`.

- [ ] **Step 3: Implement**

Immediately after the existing year-inference block at `retrieval/pipeline.py:266`:

```python
    # Same precedence rule the year parser already follows: a caller that
    # passed its own filter has DECIDED, and inference must not overrule it.
    inferred_agencies: list[str] = []
    if not req.agency_canonical_id:
        agency_matches = parse_query_agencies(req.query)
        if is_filterable(agency_matches):
            inferred_agencies = [m.value for m in agency_matches]
            filters = dataclass_replace(filters, agency_canonical_id=inferred_agencies)

    inferred_doc_types: list[str] = []
    if not req.doc_type:
        type_matches = parse_query_doc_types(req.query)
        if is_filterable(type_matches):
            inferred_doc_types = [m.value for m in type_matches]
            filters = dataclass_replace(filters, doc_type=inferred_doc_types)
```

Then wrap the retrieval body so that **an inferred filter yielding zero chunks
is retried without the inferred filters**, recording what was dropped:

```python
    # WHY retry rather than return nothing: an inferred filter is a GUESS.
    # A wrong guess must cost the analyst ranking quality, never the whole
    # page. `dropped_filters` is reported so the UI can say "showing all
    # documents — no Corrections results matched" instead of leaving them to
    # wonder where everything went. A filter that is invisibly not applied is
    # worse than one that is visibly relaxed.
```

Only filters this pipeline INFERRED are droppable — a caller's explicit filter
is never silently discarded.

Add the three new fields to `RetrievalResult` with docstrings modelled on the
existing `inferred_fiscal_years` paragraph.

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_pipeline_query_understanding.py -q`
Expected: PASS (5 tests)

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: `2011 passed`

- [ ] **Step 5: Commit**

```bash
git add retrieval/pipeline.py tests/test_pipeline_query_understanding.py
git commit -m "feat(retrieval): apply inferred agency and doc-type filters, with fallback"
```

---

## Task 7: The weak-match boost (spec Q4)

**Files:**
- Create: `retrieval/agency_boost.py`
- Modify: `retrieval/pipeline.py`
- Test: `tests/test_agency_boost.py`

**Interfaces:**
- Produces: `apply_match_penalty(chunks, *, agency_ids, doc_types, weight=None) -> list[RetrievedChunk]`; `MATCH_PENALTY` constant.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_agency_boost.py
from retrieval.agency_boost import MATCH_PENALTY, apply_match_penalty
from retrieval.types import RetrievedChunk


def make_chunk(chunk_id: str, *, score: float, agency_ids: list[str]) -> RetrievedChunk:
    """Local helper — there is no shared tests/helpers.py in this repo.

    Modelled on `_chunk` in tests/test_recency.py, which is the house pattern
    for building a RetrievedChunk by hand; this one varies agency ids where
    that one varies fiscal_year.
    """
    return RetrievedChunk(
        chunk_id=chunk_id,
        doc_id=f"doc-{chunk_id}",
        text=f"text of {chunk_id}",
        score=score,
        section_path=[],
        page=1,
        bbox=None,
        source_anchor=None,
        agency_canonical_ids=agency_ids,
        fund_canonical_id=None,
        fund_mentions=[],
        fiscal_year=2026,
        doc_type="baseline-per-agency",
        is_table=False,
        table_html=None,
        token_count=10,
        publisher="jlbc",
    )


def test_non_matching_chunks_are_penalised_and_matching_ones_are_untouched():
    """A PENALTY, never a bonus: top_score feeds REFUSAL_THRESHOLD, and
    inflating it would silently weaken refusal."""
    chunks = [make_chunk("a", score=5.0, agency_ids=["agency:ade"]),
              make_chunk("b", score=4.0, agency_ids=["agency:adc"])]
    out = apply_match_penalty(chunks, agency_ids=["agency:adc"], doc_types=[], weight=2.0)
    by_id = {c.chunk_id: c.score for c in out}
    assert by_id["b"] == 4.0          # matching: unchanged
    assert by_id["a"] == 3.0          # non-matching: penalised


def test_the_top_score_can_only_fall():
    chunks = [make_chunk("a", score=5.0, agency_ids=["agency:ade"])]
    out = apply_match_penalty(chunks, agency_ids=["agency:adc"], doc_types=[], weight=2.0)
    assert max(c.score for c in out) <= 5.0


def test_zero_weight_is_a_no_op_and_does_not_resort():
    chunks = [make_chunk("a", score=4.0, agency_ids=["agency:ade"]),
              make_chunk("b", score=4.0, agency_ids=["agency:adc"])]
    out = apply_match_penalty(chunks, agency_ids=["agency:adc"], doc_types=[], weight=0.0)
    assert [c.chunk_id for c in out] == ["a", "b"]


def test_no_matches_means_no_change():
    chunks = [make_chunk("a", score=4.0, agency_ids=["agency:ade"])]
    out = apply_match_penalty(chunks, agency_ids=[], doc_types=[], weight=2.0)
    assert [c.score for c in out] == [4.0]


def test_an_unstamped_chunk_is_treated_as_non_matching():
    """20% of the corpus carries no agency stamp. 'We don't know' must not be
    rewarded as 'it matches' — that is how a Governor's budget outranked a
    DEMA query."""
    chunks = [make_chunk("a", score=5.0, agency_ids=[])]
    out = apply_match_penalty(chunks, agency_ids=["agency:adc"], doc_types=[], weight=2.0)
    assert out[0].score == 3.0
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_agency_boost.py -q`
Expected: FAIL — no module.

- [ ] **Step 3: Implement**

Mirror `retrieval/recency.py` closely — the same penalty shape, the same
chunk_id tiebreak on re-sort, the same no-op-at-zero behaviour including NOT
re-sorting. Ship at `MATCH_PENALTY = 0.0` pending Task 9's calibration.

- [ ] **Step 4: Wire into the pipeline**

Apply at the same seam as the recency boost (`retrieval/pipeline.py:332`),
using the WEAK matches that were not applied as filters.

- [ ] **Step 5: Run**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: `2016 passed`

- [ ] **Step 6: Commit**

```bash
git add retrieval/agency_boost.py retrieval/pipeline.py tests/test_agency_boost.py
git commit -m "feat(retrieval): penalty-shaped boost for weak agency/type matches"
```

---

## Task 8: Draft the alias list — STOPS FOR REVIEW (spec Q6)

**Files:**
- Create: `scripts/draft_agency_aliases.py`, `docs/superpowers/investigations/2026-08-02-agency-alias-review.md`

**⚠ This task ends with a HUMAN REVIEW GATE. Do not merge drafted aliases into
`samples/entity-catalog.yaml` until Destin has approved them.** A missing alias
merely fails to help; a wrong one under a hard filter sends a query confidently
to the wrong agency.

- [ ] **Step 1: Write the generator**

`scripts/draft_agency_aliases.py` proposes acronyms for each of the 157
agencies from its canonical name (initials of significant words, with and
without a leading "A" for Arizona), skipping any that collide with another
agency's proposal or with an existing alias. Emit a markdown checklist with
one row per agency: canonical name, JLBC slug, proposed aliases, and a
confidence marker.

- [ ] **Step 2: Run it and write the review document**

```bash
.venv/bin/python scripts/draft_agency_aliases.py > docs/superpowers/investigations/2026-08-02-agency-alias-review.md
```

Head the document with: what an alias does, that an approved alias may become
a HARD filter, and that anything uncertain should be struck rather than
guessed.

- [ ] **Step 3: Commit the draft and STOP**

```bash
git add scripts/draft_agency_aliases.py docs/superpowers/investigations/2026-08-02-agency-alias-review.md
git commit -m "docs(investigation): drafted agency aliases for review — NOT yet applied"
```

**Hand the checklist to Destin. Do not proceed to Task 9 until it comes back
approved.** Then add the approved aliases under each agency's `aliases:` key
in `samples/entity-catalog.yaml`, add any that are ordinary English words to
`AMBIGUOUS_ALIASES`, and commit separately.

---

## Task 9: Calibrate, eval, and record

**Files:**
- Modify: `eval/queries.yaml`, `retrieval/agency_boost.py`, `harness/constants.py` (only if the sweep says so), `STATUS.md`

- [ ] **Step 1: Add shorthand queries to the eval set**

Add the six fixture queries with real, verified `chunk_id` ground truth — every
id checked against the live corpus first, the way
`tests/test_harness_history.py` style checks are done. **Do not invent ids.**

- [ ] **Step 2: Sweep `MATCH_PENALTY`**

Reuse `eval/sweep_recency.py`'s shape. Pass an EXPLICIT `--weights` grid —
the derived grid is coarse, and taking its recommendation uncritically is
exactly how `RECENCY_BOOST_PER_YEAR` was set to 2.064 when 0.85 was free.

Choose the largest weight that costs no recall.

- [ ] **Step 3: Re-check the refusal threshold**

A penalty lowers `top_score`, so `REFUSAL_THRESHOLD` may need to move with it.

```bash
.venv/bin/python -m eval.run_eval
.venv/bin/python -m eval.calibrate_refusal --result eval/results/<the run just written>.json
```

**Pass `--result` explicitly** — `calibrate_refusal` otherwise grabs the newest
file in `eval/results/`, which may be a sweep JSON with a different shape, and
dies with `KeyError: 'per_query'`.

If the threshold moves, update `tests/test_recency.py::test_the_shipped_weight_and_refusal_threshold_move_together` and the literal in `tests/test_harness_tools.py`.

- [ ] **Step 4: Confirm gate G1 and no regression**

Baseline to beat: recall@5 **73.81%**, recall@15 **97.62%**, recall@20
**97.62%**, p95 **852 ms**. G1 needs recall@15 ≥ 90% and recall@20 ≥ 95%.

**If recall@5 drops, stop and report rather than tuning until it passes.**

- [ ] **Step 5: Record in STATUS.md**

The before/after on the six queries, the chosen penalty weight and why, any
threshold move, and the fact that fund resolution has the identical gap and
was deliberately deferred.

- [ ] **Step 6: Commit**

```bash
git add eval/ retrieval/ harness/ tests/ STATUS.md
git commit -m "feat(retrieval): calibrate the match penalty; eval the shorthand queries"
```

---

## Risks

1. **A wrong alias under a hard filter is the worst outcome here** — it sends a query confidently to the wrong agency, which is harder to notice than getting nothing. Task 8's review gate is the control, and it is not optional.
2. **`AMBIGUOUS_ALIASES` is hand-maintained** and will drift as aliases are added. Reviewed whenever the catalog changes.
3. **The penalty and the recency penalty compose.** Both lower `top_score`, and `REFUSAL_THRESHOLD` is compared against it. Calibrate together, never separately.
4. **80% agency-stamp coverage means 20% of chunks can never match an agency filter.** That is why the fallback in Task 6 exists, and why the boost treats unstamped chunks as non-matching rather than neutral.
