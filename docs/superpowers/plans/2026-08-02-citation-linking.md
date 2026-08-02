# Citation Linking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the system — not the model — attach a citation to every figure in an answer, so each number carries a chip that links to its source, numbered in reading order.

**Architecture:** A new `citation/` package runs in-process at the end of a turn. It extracts every figure from the final answer with offsets, locates each value in the chunks that turn retrieved (scale-aware), ranks candidate sources by document authority, reconciles the leftovers as derived arithmetic, and emits one **annotation** over the answer. The webapp renders that annotation as chips; the eval judge renders the same annotation as inline markers, so the two cannot drift.

**Tech Stack:** Python 3.12, pydantic v2, pytest. TypeScript/React + vitest for the webapp. No new dependencies.

## Spec

`docs/superpowers/specs/2026-08-02-citation-linking-design.md`. Read it before Task 1.

## Global Constraints

- Python ≥ 3.12. Every new module opens with `from __future__ import annotations` and a docstring explaining WHY it exists.
- Non-trivial lines get a WHY comment. The project owner is a non-developer who reads comments to understand the code.
- Tests live in flat `tests/` as `tests/test_citation_*.py`. Webapp tests live beside their module under `webapp/src/**/__tests__/`.
- Run `uv run pytest tests/test_citation_*.py -v` before each commit. Webapp: `cd webapp && npx vitest run`.
- The linker must never raise into the turn. A failure yields an empty annotation and the answer still renders — a citation bug must not cost the user a paid answer.
- The linker performs **no retrieval and no store access**. Its only inputs are the answer text and chunk text already recorded on the turn.
- Never link a figure to a source below the specificity floor. Reporting `unverified` is always correct; guessing is not.
- Existing `cite`/`cite_batch` behaviour for prose is not changed except where a task says so.

## File structure

| File | Responsibility |
|---|---|
| `citation/__init__.py` (new) | Package exports |
| `citation/figures.py` (new) | Find figures in answer text with offsets + scale |
| `citation/matching.py` (new) | Scale-aware location of a value in chunk text |
| `citation/authority.py` (new) | Rank candidate chunks by document authority |
| `citation/reconcile.py` (new) | Identify derived figures as arithmetic over linked ones |
| `citation/annotate.py` (new) | Assemble the annotation; the one public entry point |
| `harness/session.py` (modify) | Call the linker at turn end; carry `annotation` on `_done` |
| `harness/system-prompt.md` (modify) | Stop asking the model to cite figures |
| `eval/judge_agent_run.py` (modify) | Render the annotation as inline markers for the judge |
| `eval/agent_judge_prompt.md` (modify) | Grade figure coverage and placement |
| `eval/agent_scoring.py` (modify) | Emit figure-coverage / derived / unverified metrics |
| `webapp/src/chat/citation-annotation.ts` (new) | Parse the annotation into render-ready chips |
| `webapp/src/chat/CitedMarkdownContent.tsx` (modify) | Render annotation chips |
| `webapp/src/chat/CitationChip.tsx` (modify) | Primary source, additional references, derived + unverified states |

---

### Task 1: Figure extraction

**Files:**
- Create: `citation/__init__.py`, `citation/figures.py`
- Test: `tests/test_citation_figures.py`

**Interfaces:**
- Produces: `Figure(text: str, start: int, end: int, value: float, scale: int)`; `extract_figures(answer: str) -> list[Figure]`.
  `start`/`end` are character offsets into `answer`. `value` is the figure as written (`8287.7` for `$8,287.7`). `scale` is the multiplier implied by nearby context (`1`, `1_000`, `1_000_000`, `1_000_000_000`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_citation_figures.py
"""Figure extraction tests.

Why offsets matter: the chip is placed at the figure's position in the
answer, so a wrong offset puts a citation on the wrong number. Why scale
matters: an answer renders "$8,287.7" under a "$ Millions" header while
the source document says "8,287,700,000" — measured at 67% of figures in
the 2026-08-01 baseline. Without scale the match fails.
"""
from __future__ import annotations

from citation.figures import Figure, extract_figures


def test_finds_plain_currency_with_offsets():
    ans = "ADC received $1,391,157,700 in FY 2025."
    figs = extract_figures(ans)
    assert len(figs) == 1
    f = figs[0]
    assert f.text == "$1,391,157,700"
    assert ans[f.start:f.end] == "$1,391,157,700"
    assert f.value == 1391157700.0
    assert f.scale == 1


def test_suffix_sets_scale():
    figs = extract_figures("the program cost $1.06 billion last year")
    assert figs[0].value == 1.06
    assert figs[0].scale == 1_000_000_000


def test_million_suffix():
    figs = extract_figures("a $376.2 million increase")
    assert figs[0].scale == 1_000_000


def test_table_header_sets_scale_for_the_whole_table():
    # The header declares the unit once; every cell inherits it.
    ans = (
        "| Agency | FY 2026 GF Appropriation ($ Millions) |\n"
        "|---|---|\n"
        "| ADE | $8,287.7 |\n"
        "| AHCCCS | $2,613.7 |\n"
    )
    figs = extract_figures(ans)
    cells = [f for f in figs if f.text in ("$8,287.7", "$2,613.7")]
    assert len(cells) == 2
    assert all(f.scale == 1_000_000 for f in cells)


def test_bare_grouped_integers_count_as_figures():
    figs = extract_figures("enrollment reached 101,602 students")
    assert [f.text for f in figs] == ["101,602"]
    assert figs[0].value == 101602.0


def test_years_and_percentages_are_not_figures():
    # "FY 2026" is a label and "3.8%" is almost always derived; neither
    # should demand a source chip.
    figs = extract_figures("In FY 2026 spending rose 3.8% over FY 2025.")
    assert figs == []


def test_offsets_are_correct_for_every_figure_in_order():
    ans = "First $1,000,000 then $2,500,000 and finally $3,750,000."
    figs = extract_figures(ans)
    assert [ans[f.start:f.end] for f in figs] == [
        "$1,000,000", "$2,500,000", "$3,750,000"]
    assert [f.start for f in figs] == sorted(f.start for f in figs)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_citation_figures.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'citation'`

- [ ] **Step 3: Implement**

```python
# citation/__init__.py
"""Deterministic citation linking for figures stated in an answer."""
from __future__ import annotations
```

```python
# citation/figures.py
"""Find every figure an answer states, with its exact offsets and the
scale its context implies.

Offsets are the whole point: the chip is placed at the figure's position
in the answer, so chips land on the number they support and number
themselves in reading order. Scale is the other half — the answer renders
"$8,287.7" beneath a "$ Millions" header while the source says
"8,287,700,000", which was 67% of figures in the 2026-08-01 baseline.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# A figure is a grouped integer (1,234,567) or a decimal with a currency
# marker ($8,287.7). A bare ungrouped integer is NOT a figure — it is far
# more often a count, a year, or a page number than a budget amount.
_FIGURE_RE = re.compile(
    r"\$\s?\d{1,3}(?:,\d{3})+(?:\.\d+)?"     # $1,391,157,700 / $8,287.7
    r"|\$\s?\d+\.\d+"                         # $1.06
    r"|\d{1,3}(?:,\d{3})+(?:\.\d+)?"          # 101,602
)
# "FY 2026" and "in 2026" are labels, never amounts.
_YEAR_CONTEXT = re.compile(r"(?:FY|fiscal year|in)\s*$", re.IGNORECASE)
_SUFFIX = (
    (re.compile(r"^\s*billion", re.IGNORECASE), 1_000_000_000),
    (re.compile(r"^\s*million", re.IGNORECASE), 1_000_000),
    (re.compile(r"^\s*thousand", re.IGNORECASE), 1_000),
)
# A markdown table header may declare the unit once for every cell below.
_HEADER_SCALE = (
    (re.compile(r"\$?\s*billions?\b", re.IGNORECASE), 1_000_000_000),
    (re.compile(r"\$?\s*millions?\b", re.IGNORECASE), 1_000_000),
    (re.compile(r"\$?\s*thousands?\b", re.IGNORECASE), 1_000),
)


@dataclass(frozen=True)
class Figure:
    text: str
    start: int
    end: int
    value: float
    scale: int

    @property
    def absolute(self) -> float:
        """The figure in plain dollars, scale applied."""
        return self.value * self.scale


def _table_scale(answer: str) -> int:
    """The unit a markdown table header declares, if any. A header states
    the unit once and every cell inherits it, so a per-figure suffix scan
    alone would read every cell as unscaled."""
    for line in answer.splitlines():
        if line.lstrip().startswith("|"):
            for pattern, scale in _HEADER_SCALE:
                if pattern.search(line):
                    return scale
    return 1


def extract_figures(answer: str) -> list[Figure]:
    table_scale = _table_scale(answer)
    figures: list[Figure] = []
    for m in _FIGURE_RE.finditer(answer):
        raw = m.group(0)
        # Reject year labels: "FY 2026" reads as a figure without this.
        if _YEAR_CONTEXT.search(answer[max(0, m.start() - 16):m.start()]):
            continue
        # A percentage is virtually always computed, not quoted.
        if answer[m.end():m.end() + 1] == "%":
            continue
        value = float(raw.replace("$", "").replace(",", "").strip())
        scale = 1
        tail = answer[m.end():m.end() + 12]
        for pattern, mult in _SUFFIX:
            if pattern.match(tail):
                scale = mult
                break
        else:
            # No explicit suffix: inherit the table's declared unit, but
            # only for decimals — a fully grouped integer like
            # 1,391,157,700 is already absolute.
            if table_scale != 1 and "." in raw:
                scale = table_scale
        figures.append(Figure(raw, m.start(), m.end(), value, scale))
    return figures
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_citation_figures.py -v`
Expected: 7 PASS

- [ ] **Step 5: Commit**

```bash
git add citation/__init__.py citation/figures.py tests/test_citation_figures.py
git commit -m "feat(citation): extract figures from an answer with offsets and scale"
```

---

### Task 2: Scale-aware matching

**Files:**
- Create: `citation/matching.py`
- Test: `tests/test_citation_matching.py`

**Interfaces:**
- Consumes: `Figure` from Task 1.
- Produces: `SourceHit(chunk_id: str, source_text: str, start: int, end: int, scale_used: int)`; `find_in_chunks(fig: Figure, chunks: dict[str, str], *, min_significant_digits: int = 4) -> list[SourceHit]`.
  `chunks` maps `chunk_id -> chunk text`. `source_text` is the figure **as the source renders it** — that string is what the PDF highlighter must search for. Returns `[]` when nothing clears the specificity floor.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_citation_matching.py
"""Scale-aware matching tests.

Two properties carry this module. First, the answer's rendering and the
source's rendering differ for two thirds of figures, so matching must
compare VALUES across scale. Second, the returned string must be the
SOURCE's rendering, because that is what exists in the PDF text layer.
"""
from __future__ import annotations

from citation.figures import Figure
from citation.matching import SourceHit, find_in_chunks


def fig(text, value, scale=1):
    return Figure(text=text, start=0, end=len(text), value=value, scale=scale)


def test_exact_match_returns_source_rendering():
    chunks = {"c-1": "ADC General Fund 1,391,157,700 in FY 2025"}
    hits = find_in_chunks(fig("$1,391,157,700", 1391157700.0), chunks)
    assert len(hits) == 1
    assert hits[0].chunk_id == "c-1"
    assert hits[0].source_text == "1,391,157,700"
    assert chunks["c-1"][hits[0].start:hits[0].end] == "1,391,157,700"


def test_scale_shifted_match():
    # The answer says "$8,287.7" under a "$ Millions" header; the document
    # prints the absolute figure.
    chunks = {"c-1": "Department of Education 8,287,700,000 total"}
    hits = find_in_chunks(fig("$8,287.7", 8287.7, scale=1_000_000), chunks)
    assert len(hits) == 1
    assert hits[0].source_text == "8,287,700,000"
    assert hits[0].scale_used == 1_000_000


def test_rounding_tolerance():
    # "$1,391.2 million" is a faithful rounding of 1,391,157,700.
    chunks = {"c-1": "appropriation of 1,391,157,700"}
    hits = find_in_chunks(fig("$1,391.2", 1391.2, scale=1_000_000), chunks)
    assert len(hits) == 1


def test_multiple_chunks_all_returned():
    chunks = {"c-1": "total 2,613,700,000", "c-2": "AHCCCS 2,613,700,000 GF"}
    hits = find_in_chunks(fig("$2,613,700,000", 2613700000.0), chunks)
    assert {h.chunk_id for h in hits} == {"c-1", "c-2"}


def test_short_figures_are_refused_by_the_specificity_floor():
    # "$37" collides incidentally everywhere. Refusing to link is correct;
    # guessing is not.
    chunks = {"c-1": "line 37 of the report shows 37 positions"}
    assert find_in_chunks(fig("$37", 37.0), chunks) == []


def test_fused_table_numbers_still_locate_correctly():
    # Extraction fuses adjacent cells: DCS 1,320,598,100 runs straight into
    # Chiropractic's 643,700. The offsets for the first figure are still
    # correct, which is what the highlighter needs.
    chunks = {"c-1": "Child Safety, Department of\t1,320,598,100643,700\tnext"}
    hits = find_in_chunks(fig("$1,320,598,100", 1320598100.0), chunks)
    assert len(hits) == 1
    assert chunks["c-1"][hits[0].start:hits[0].end] == "1,320,598,100"


def test_no_match_returns_empty():
    assert find_in_chunks(fig("$999,999,999", 999999999.0), {"c-1": "nothing"}) == []
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_citation_matching.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'citation.matching'`

- [ ] **Step 3: Implement**

```python
# citation/matching.py
"""Locate a figure's value inside chunk text, tolerating the scale the
answer rendered it in.

Returns the SOURCE's rendering of the number, not the answer's. That
distinction is load-bearing: the PDF text layer contains the source's
form, so highlighting must search for that string. The old path searched
for the answer's form and missed.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

from citation.figures import Figure

# Every grouped number in a chunk. Chunk text is machine-extracted and
# frequently fuses adjacent table cells, so this deliberately matches a
# greedy grouped run and lets the value comparison decide.
_CANDIDATE_RE = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?")

# Scales an answer may render a source figure in.
_SCALES = (1, 1_000, 1_000_000, 1_000_000_000)

# A faithful rounding ("$1,391.2 million" for 1,391,157,700) differs by
# well under 0.1%; a neighbouring budget line differs by far more.
_REL_TOL = 0.001


@dataclass(frozen=True)
class SourceHit:
    chunk_id: str
    source_text: str
    start: int
    end: int
    scale_used: int


def _significant_digits(value: float) -> int:
    """Digits before the decimal point, ignoring trailing zeros — a proxy
    for how distinctive a figure is. 37 scores 2; 1,320,598,100 scores 9."""
    whole = int(abs(value))
    if whole == 0:
        return 0
    return len(str(whole))


def find_in_chunks(
    fig: Figure,
    chunks: dict[str, str],
    *,
    min_significant_digits: int = 4,
) -> list[SourceHit]:
    target = fig.absolute
    # Refuse short figures outright: they collide incidentally, and a
    # wrong link is worse than an honest "unverified".
    if _significant_digits(target) < min_significant_digits:
        return []

    hits: list[SourceHit] = []
    for chunk_id, text in chunks.items():
        for m in _CANDIDATE_RE.finditer(text or ""):
            raw = m.group(0)
            candidate = float(raw.replace(",", ""))
            for scale in _SCALES:
                if math.isclose(candidate, target * scale,
                                rel_tol=_REL_TOL, abs_tol=0.5):
                    hits.append(SourceHit(chunk_id, raw, m.start(), m.end(),
                                          scale))
                    break
            else:
                continue
            break  # one hit per chunk is enough to cite it
    return hits
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_citation_matching.py -v`
Expected: 7 PASS

- [ ] **Step 5: Calibrate the specificity floor against real data**

The default of 4 significant digits is a starting point, not a measured
value. Calibrate it and commit the numbers:

```bash
uv run python - <<'EOF'
import glob, json
from citation.figures import extract_figures
from citation.matching import find_in_chunks
from eval.agent_transcript import read_transcript, final_answer, retrieve_calls

for floor in (3, 4, 5, 6):
    linked = unverified = ambiguous = 0
    for f in glob.glob("eval/results/agent/2026-08-02T0900Z-0b08221/*-r1.jsonl"):
        t = read_transcript(f)
        chunks = {c["chunk_id"]: (c.get("text") or "")
                  for call in retrieve_calls(t) for c in call["chunks"]}
        for fig in extract_figures(final_answer(t)):
            hits = find_in_chunks(fig, chunks, min_significant_digits=floor)
            if not hits:
                unverified += 1
            else:
                linked += 1
                if len({h.chunk_id for h in hits}) > 1:
                    ambiguous += 1
    total = linked + unverified
    print(f"floor={floor}: linked {linked}/{total} "
          f"({100*linked/total:.1f}%), ambiguous {ambiguous}, "
          f"unverified {unverified}")
EOF
```

Pick the lowest floor at which incidental links stop appearing, and record
the table in the commit message. Update the default in `find_in_chunks`
if the measurement disagrees with 4.

- [ ] **Step 6: Commit**

```bash
git add citation/matching.py tests/test_citation_matching.py
git commit -m "feat(citation): scale-aware matching that returns the source rendering

Calibration of min_significant_digits over the 31-query baseline:
<paste the table from Step 5>"
```

---

### Task 3: Authority ranking

**Files:**
- Create: `citation/authority.py`
- Test: `tests/test_citation_authority.py`

**Interfaces:**
- Consumes: `SourceHit` from Task 2.
- Produces: `rank_hits(hits: list[SourceHit], meta: dict[str, dict], *, prefer_fiscal_year: int | None = None) -> list[SourceHit]` — most authoritative first. `meta` maps `chunk_id -> {"doc_type": str, "fiscal_year": int | None}`, taken straight from the retrieve payload.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_citation_authority.py
"""Authority ranking tests.

81% of ambiguity is the same figure appearing in several editions of the
same material. The analyst's rule — audited actuals beat enacted, enacted
beats proposed — resolves it deterministically, so the primary citation
is the one an analyst would have chosen.
"""
from __future__ import annotations

from citation.authority import rank_hits
from citation.matching import SourceHit


def hit(chunk_id):
    return SourceHit(chunk_id, "1,000,000", 0, 9, 1)


def test_afr_outranks_approps_outranks_baseline_outranks_governor():
    hits = [hit("g"), hit("b"), hit("a"), hit("f")]
    meta = {
        "g": {"doc_type": "governors-budget", "fiscal_year": 2026},
        "b": {"doc_type": "baseline-per-agency", "fiscal_year": 2026},
        "a": {"doc_type": "approps-per-agency", "fiscal_year": 2026},
        "f": {"doc_type": "afr", "fiscal_year": 2026},
    }
    assert [h.chunk_id for h in rank_hits(hits, meta)] == ["f", "a", "b", "g"]


def test_matching_fiscal_year_wins_within_the_same_authority():
    hits = [hit("old"), hit("new")]
    meta = {
        "old": {"doc_type": "approps-per-agency", "fiscal_year": 2024},
        "new": {"doc_type": "approps-per-agency", "fiscal_year": 2026},
    }
    ranked = rank_hits(hits, meta, prefer_fiscal_year=2026)
    assert ranked[0].chunk_id == "new"


def test_authority_beats_fiscal_year():
    # A figure confirmed in the audited FY2025 AFR outranks the same figure
    # in a FY2026 proposal even when the question is about FY2026.
    hits = [hit("proposal"), hit("audited")]
    meta = {
        "proposal": {"doc_type": "governors-budget", "fiscal_year": 2026},
        "audited": {"doc_type": "afr", "fiscal_year": 2025},
    }
    ranked = rank_hits(hits, meta, prefer_fiscal_year=2026)
    assert ranked[0].chunk_id == "audited"


def test_unknown_doc_type_ranks_last_but_is_kept():
    hits = [hit("weird"), hit("known")]
    meta = {
        "weird": {"doc_type": "something-new", "fiscal_year": 2026},
        "known": {"doc_type": "baseline-per-agency", "fiscal_year": 2026},
    }
    ranked = rank_hits(hits, meta)
    assert [h.chunk_id for h in ranked] == ["known", "weird"]


def test_missing_metadata_does_not_crash():
    ranked = rank_hits([hit("a")], {})
    assert [h.chunk_id for h in ranked] == ["a"]


def test_ranking_is_stable_for_equal_authority():
    hits = [hit("first"), hit("second")]
    meta = {
        "first": {"doc_type": "afr", "fiscal_year": 2025},
        "second": {"doc_type": "afr", "fiscal_year": 2025},
    }
    assert [h.chunk_id for h in rank_hits(hits, meta)] == ["first", "second"]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_citation_authority.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'citation.authority'`

- [ ] **Step 3: Implement**

```python
# citation/authority.py
"""Order candidate sources the way an analyst would.

The same figure legitimately appears in several editions of the same
material — a Baseline projection, the enacted Appropriations Report, then
the audited AFR. This encodes the document lifecycle the system prompt
already teaches, so the primary citation is the most trustworthy edition
and the rest are shown as corroboration.
"""
from __future__ import annotations

from typing import Any

from citation.matching import SourceHit

# Lower number = more authoritative. Audited actuals beat what was
# enacted, which beats what was projected, which beats what was proposed.
_AUTHORITY = {
    "afr": 0,
    "approps-per-agency": 1,
    "approps-agency-pdf": 1,
    "budget-bill": 2,
    "baseline-per-agency": 3,
    "detailed-list-pdf": 4,
    "topic-pdf": 4,
    "s-pdf": 4,
    "bh-pdf": 4,
    "bd-pdf": 4,
    "governors-budget": 5,
}
# An unrecognised doc_type sorts last but is never discarded — a new
# publisher type should degrade to "least authoritative", not vanish.
_UNKNOWN = 99


def rank_hits(
    hits: list[SourceHit],
    meta: dict[str, dict[str, Any]],
    *,
    prefer_fiscal_year: int | None = None,
) -> list[SourceHit]:
    def key(h: SourceHit) -> tuple[int, int]:
        info = meta.get(h.chunk_id) or {}
        authority = _AUTHORITY.get(info.get("doc_type"), _UNKNOWN)
        # Fiscal year breaks ties WITHIN an authority level only; it must
        # never promote a proposal over an audited figure.
        fy_rank = 0
        if prefer_fiscal_year is not None:
            fy_rank = 0 if info.get("fiscal_year") == prefer_fiscal_year else 1
        return (authority, fy_rank)

    # sorted() is stable, so equal-authority hits keep their input order.
    return sorted(hits, key=key)
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_citation_authority.py -v`
Expected: 6 PASS

- [ ] **Step 5: Commit**

```bash
git add citation/authority.py tests/test_citation_authority.py
git commit -m "feat(citation): rank candidate sources by document authority"
```

---

### Task 4: Derived-figure reconciliation

**Files:**
- Create: `citation/reconcile.py`
- Test: `tests/test_citation_reconcile.py`

**Interfaces:**
- Consumes: `Figure` from Task 1.
- Produces: `Derivation(operation: str, inputs: list[int])`; `reconcile(target: Figure, linked: list[Figure]) -> Derivation | None`. `inputs` are indices into `linked`. `operation` is one of `"sum"`, `"difference"`, `"percent_change"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_citation_reconcile.py
"""Reconciliation tests.

A computed total that renders like a sourced figure is the kind of thing
that erodes trust in a whole table. Reconciliation is what lets a derived
number say what it was computed FROM, mechanically, so the model cannot
pass arithmetic off as provenance.
"""
from __future__ import annotations

from citation.figures import Figure
from citation.reconcile import Derivation, reconcile


def f(value, scale=1):
    return Figure(text=str(value), start=0, end=1, value=value, scale=scale)


def test_sum_of_two():
    d = reconcile(f(300.0), [f(100.0), f(200.0)])
    assert d == Derivation(operation="sum", inputs=[0, 1])


def test_sum_of_three():
    d = reconcile(f(600.0), [f(100.0), f(200.0), f(300.0)])
    assert d is not None and d.operation == "sum"
    assert sorted(d.inputs) == [0, 1, 2]


def test_difference():
    d = reconcile(f(376.2), [f(1000.0), f(623.8)])
    assert d is not None and d.operation == "difference"
    assert sorted(d.inputs) == [0, 1]


def test_percent_change():
    # 1,038 is 3.8% above 1,000.
    d = reconcile(f(3.8), [f(1000.0), f(1038.0)])
    assert d is not None and d.operation == "percent_change"


def test_unrelated_number_is_not_reconciled():
    assert reconcile(f(999999.0), [f(100.0), f(200.0)]) is None


def test_rounding_tolerated():
    # "$1.06 billion" restating 1,058,400,000.
    d = reconcile(f(1.06, scale=1_000_000_000), [f(1058400000.0)])
    assert d is not None and d.operation == "sum" and d.inputs == [0]


def test_no_linked_figures_means_no_derivation():
    assert reconcile(f(300.0), []) is None
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_citation_reconcile.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'citation.reconcile'`

- [ ] **Step 3: Implement**

```python
# citation/reconcile.py
"""Explain a figure that appears in no source as arithmetic over figures
that do.

Roughly 6% of stated figures are computed — year-over-year deltas, totals,
percent changes, restatements. Without this they would all read
"unverified", which is both noisy and wrong: they ARE supported, just
indirectly. With it, a derived figure can show exactly what it came from.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

from citation.figures import Figure

# Restatements round hard ("$1.06 billion" for 1,058,400,000), so this is
# looser than the matcher's tolerance. A false derivation is cheap: it
# still tells the analyst the figure is computed, not sourced.
_REL_TOL = 0.01
# Beyond three inputs a "sum" stops being an explanation a reader can
# check at a glance, and the combinatorics stop being free.
_MAX_INPUTS = 3


@dataclass(frozen=True)
class Derivation:
    operation: str
    inputs: list[int]
    # No hand-written __eq__: @dataclass generates one and would silently
    # overwrite it. The generated version compares the list by value,
    # which is exactly what the tests expect.


def _close(a: float, b: float) -> bool:
    if b == 0:
        return abs(a) < 1e-9
    return abs(a - b) <= abs(b) * _REL_TOL


def reconcile(target: Figure, linked: list[Figure]) -> Derivation | None:
    goal = target.absolute
    values = [x.absolute for x in linked]

    # A restatement of a single figure is a one-input "sum".
    for i, v in enumerate(values):
        if _close(goal, v):
            return Derivation("sum", [i])

    for n in (2, 3):
        if n > _MAX_INPUTS:
            break
        for combo in combinations(range(len(values)), n):
            if _close(goal, sum(values[i] for i in combo)):
                return Derivation("sum", list(combo))

    for a, b in combinations(range(len(values)), 2):
        if _close(goal, abs(values[a] - values[b])):
            return Derivation("difference", [a, b])
        # percent change in either direction
        for x, y in ((a, b), (b, a)):
            if values[x] and _close(goal,
                                    (values[y] - values[x]) / values[x] * 100):
                return Derivation("percent_change", [x, y])
    return None
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_citation_reconcile.py -v`
Expected: 7 PASS

- [ ] **Step 5: Commit**

```bash
git add citation/reconcile.py tests/test_citation_reconcile.py
git commit -m "feat(citation): reconcile derived figures as arithmetic over linked ones"
```

---

### Task 5: The annotation

**Files:**
- Create: `citation/annotate.py`
- Test: `tests/test_citation_annotate.py`

**Interfaces:**
- Consumes: Tasks 1–4.
- Produces: `annotate_answer(answer: str, chunks: dict[str, str], meta: dict[str, dict], *, prefer_fiscal_year: int | None = None) -> dict`.
  Returns a JSON-serialisable annotation:
  ```python
  {"figures": [
      {"text": "$8,287.7", "start": 42, "end": 50, "index": 1,
       "verdict": "linked",
       "primary": {"chunk_id": "c-1", "source_text": "8,287,700,000",
                   "start": 120, "end": 133},
       "additional": [{"chunk_id": "c-2", "source_text": "8,287,700,000",
                       "start": 88, "end": 101}],
       "derived_from": []},
      {"text": "$17,654.2", "start": 300, "end": 309, "index": 2,
       "verdict": "derived", "primary": None, "additional": [],
       "derived_from": [1]},
      {"text": "$999,999,999", "start": 400, "end": 412, "index": 3,
       "verdict": "unverified", "primary": None, "additional": [],
       "derived_from": []}]}
  ```
  `index` is 1-based in **reading order**. `derived_from` holds the `index` values of the figures a derivation used.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_citation_annotate.py
"""Annotation assembly tests.

This is the single artifact both consumers read: the webapp renders it as
chips, the eval judge renders it as inline markers. If they read the same
data they cannot disagree about what the analyst saw.
"""
from __future__ import annotations

from citation.annotate import annotate_answer

META = {
    "c-approps": {"doc_type": "approps-per-agency", "fiscal_year": 2026},
    "c-baseline": {"doc_type": "baseline-per-agency", "fiscal_year": 2026},
}


def test_linked_figure_carries_primary_and_additional():
    answer = "ADE received $1,391,157,700 in FY 2026."
    chunks = {"c-baseline": "ADE 1,391,157,700 projected",
              "c-approps": "ADE 1,391,157,700 enacted"}
    ann = annotate_answer(answer, chunks, META)
    fig = ann["figures"][0]
    assert fig["verdict"] == "linked"
    # Appropriations Report outranks Baseline.
    assert fig["primary"]["chunk_id"] == "c-approps"
    assert fig["primary"]["source_text"] == "1,391,157,700"
    assert [a["chunk_id"] for a in fig["additional"]] == ["c-baseline"]


def test_indices_follow_reading_order():
    answer = "First $1,000,000 then $2,000,000 then $3,000,000."
    chunks = {"c-approps": "1,000,000 2,000,000 3,000,000"}
    ann = annotate_answer(answer, chunks, META)
    assert [f["index"] for f in ann["figures"]] == [1, 2, 3]
    assert [f["text"] for f in ann["figures"]] == [
        "$1,000,000", "$2,000,000", "$3,000,000"]


def test_derived_total_points_at_its_inputs():
    answer = "ADE $1,000,000 and AHCCCS $2,000,000, totalling $3,000,000."
    chunks = {"c-approps": "ADE 1,000,000 AHCCCS 2,000,000"}
    ann = annotate_answer(answer, chunks, META)
    total = ann["figures"][2]
    assert total["verdict"] == "derived"
    assert total["primary"] is None
    assert sorted(total["derived_from"]) == [1, 2]


def test_unverified_when_neither_linked_nor_derived():
    answer = "Spending was $987,654,321 last year."
    ann = annotate_answer(answer, {"c-approps": "unrelated text"}, META)
    assert ann["figures"][0]["verdict"] == "unverified"
    assert ann["figures"][0]["primary"] is None


def test_offsets_index_the_answer_exactly():
    answer = "The total was $1,391,157,700 overall."
    chunks = {"c-approps": "1,391,157,700"}
    fig = annotate_answer(answer, chunks, META)["figures"][0]
    assert answer[fig["start"]:fig["end"]] == "$1,391,157,700"


def test_annotation_is_json_serialisable():
    import json
    answer = "ADE $1,391,157,700."
    ann = annotate_answer(answer, {"c-approps": "1,391,157,700"}, META)
    assert json.loads(json.dumps(ann)) == ann


def test_empty_answer_yields_empty_annotation():
    assert annotate_answer("", {}, {}) == {"figures": []}
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_citation_annotate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'citation.annotate'`

- [ ] **Step 3: Implement**

```python
# citation/annotate.py
"""Assemble the annotation: the one artifact describing what every figure
in an answer is backed by.

The webapp renders it as chips; the eval judge renders it as inline
markers. One representation, two consumers, so what the analyst sees and
what the eval grades cannot drift apart.
"""
from __future__ import annotations

from typing import Any

from citation.authority import rank_hits
from citation.figures import Figure, extract_figures
from citation.matching import find_in_chunks
from citation.reconcile import reconcile


def _hit_dict(hit) -> dict[str, Any]:
    return {"chunk_id": hit.chunk_id, "source_text": hit.source_text,
            "start": hit.start, "end": hit.end}


def annotate_answer(
    answer: str,
    chunks: dict[str, str],
    meta: dict[str, dict[str, Any]],
    *,
    prefer_fiscal_year: int | None = None,
) -> dict[str, Any]:
    figures = extract_figures(answer)
    records: list[dict[str, Any]] = []
    linked_figs: list[Figure] = []
    linked_indices: list[int] = []

    # Pass 1 — link what can be located in a source.
    for i, fig in enumerate(figures, start=1):
        hits = find_in_chunks(fig, chunks)
        record: dict[str, Any] = {
            "text": fig.text, "start": fig.start, "end": fig.end,
            "index": i, "verdict": "unverified",
            "primary": None, "additional": [], "derived_from": [],
        }
        if hits:
            ranked = rank_hits(hits, meta, prefer_fiscal_year=prefer_fiscal_year)
            record["verdict"] = "linked"
            record["primary"] = _hit_dict(ranked[0])
            # Outranked sources are corroboration, shown on demand.
            record["additional"] = [_hit_dict(h) for h in ranked[1:]]
            linked_figs.append(fig)
            linked_indices.append(i)
        records.append(record)

    # Pass 2 — explain the leftovers as arithmetic over what was linked.
    # Runs second because a derivation can only reference linked figures.
    for record, fig in zip(records, figures):
        if record["verdict"] != "unverified":
            continue
        derivation = reconcile(fig, linked_figs)
        if derivation is not None:
            record["verdict"] = "derived"
            record["derived_from"] = [linked_indices[j] for j in derivation.inputs]

    return {"figures": records}
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_citation_annotate.py -v`
Expected: 7 PASS

- [ ] **Step 5: Measure against the recorded baseline**

Confirms the design's headline numbers hold for the real implementation:

```bash
uv run python - <<'EOF'
import glob
from collections import Counter
from citation.annotate import annotate_answer
from eval.agent_transcript import read_transcript, final_answer, retrieve_calls

verdicts = Counter()
for f in glob.glob("eval/results/agent/2026-08-02T0900Z-0b08221/*-r1.jsonl"):
    t = read_transcript(f)
    chunks, meta = {}, {}
    for call in retrieve_calls(t):
        for c in call["chunks"]:
            chunks[c["chunk_id"]] = c.get("text") or ""
            meta[c["chunk_id"]] = {"doc_type": c.get("doc_type"),
                                   "fiscal_year": c.get("fiscal_year")}
    for rec in annotate_answer(final_answer(t), chunks, meta)["figures"]:
        verdicts[rec["verdict"]] += 1
total = sum(verdicts.values())
for k, v in verdicts.most_common():
    print(f"{k:12s} {v:4d}  {100*v/total:5.1f}%")
EOF
```

Expected shape: `linked` the large majority, `derived` a small share,
`unverified` small. Record the output in the commit message. If
`unverified` exceeds ~10%, stop and report — the matcher or the floor is
wrong, and shipping it would put warnings on correct numbers.

- [ ] **Step 6: Commit**

```bash
git add citation/annotate.py tests/test_citation_annotate.py
git commit -m "feat(citation): assemble the answer annotation

Verdict distribution over the 31-query baseline:
<paste the output from Step 5>"
```

---

### Task 6: Wire the linker into the turn

**Files:**
- Modify: `harness/session.py`
- Test: `tests/test_citation_session.py`

**Interfaces:**
- Consumes: `annotate_answer` from Task 5.
- Produces: `_done` frame gains `"annotation": {"figures": [...]}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_citation_session.py
"""The linker runs at turn end and rides on the terminal frame.

Isolation requirement: a citation-linking failure must never cost the user
a paid answer. The answer renders; the annotation degrades to empty.
"""
from __future__ import annotations

import json

from tests.test_harness_session import (
    FakeExecutor, Provider, finish_chunk, make_settings, sse, text_chunk,
    tool_chunk, usage_chunk,
)
from harness.session import HarnessSession

RETRIEVE_OUT = json.dumps({
    "top_score": 4.0, "retrieval_id": "r", "bm25_count": 1,
    "dense_count": 1, "fused_count": 1,
    "chunks": [{
        "chunk_id": "c-1", "doc_id": "d", "doc_title": "FY2026 Approps",
        "publisher": "jlbc", "fiscal_year": 2026,
        "doc_type": "approps-per-agency", "section_path": "ADC",
        "page_start": 3, "page_end": 3, "bbox": None,
        "text": "ADC General Fund 1,391,157,700 enacted",
        "text_length": 38, "score": 4.0}],
})


class CitingExecutor(FakeExecutor):
    def execute(self, name, args):
        super().execute(name, args)
        return RETRIEVE_OUT if name == "retrieve" else json.dumps({"ok": True})


def _session(provider, executor=None):
    return HarnessSession(
        "conv-cite", "budget", "standard", "analyst",
        make_settings(), executor=executor or CitingExecutor(),
        transport=provider.transport(), tools=[],
        system_prompt="test prompt",
    )


def _provider(answer_text):
    return Provider(
        lambda: sse(tool_chunk(0, call_id="c1", name="retrieve",
                               arguments='{"query": "ADC"}'),
                    finish_chunk("tool_calls"), usage_chunk()),
        lambda: sse(text_chunk(answer_text), finish_chunk("stop"),
                    usage_chunk()),
    )


def test_done_frame_carries_the_annotation():
    s = _session(_provider("ADC received $1,391,157,700 this year."))
    frame = s.send_turn("How much for ADC?")
    s.close()
    figs = frame["annotation"]["figures"]
    assert len(figs) == 1
    assert figs[0]["verdict"] == "linked"
    assert figs[0]["primary"]["chunk_id"] == "c-1"
    assert figs[0]["primary"]["source_text"] == "1,391,157,700"


def test_annotation_offsets_index_the_final_answer():
    s = _session(_provider("ADC received $1,391,157,700 this year."))
    frame = s.send_turn("How much for ADC?")
    s.close()
    fig = frame["annotation"]["figures"][0]
    answer = frame["finalAnswer"]
    assert answer[fig["start"]:fig["end"]] == "$1,391,157,700"


def test_a_linker_failure_does_not_lose_the_answer(monkeypatch):
    import harness.session as sess

    def boom(*a, **k):
        raise RuntimeError("linker exploded")

    monkeypatch.setattr(sess, "annotate_answer", boom)
    s = _session(_provider("ADC received $1,391,157,700 this year."))
    frame = s.send_turn("How much for ADC?")
    s.close()
    assert frame["type"] == "_done"
    assert "1,391,157,700" in frame["finalAnswer"]
    assert frame["annotation"] == {"figures": []}


def test_turn_with_no_figures_annotates_empty():
    s = _session(_provider("The corpus does not cover that question."))
    frame = s.send_turn("Anything?")
    s.close()
    assert frame["annotation"] == {"figures": []}
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_citation_session.py -v`
Expected: FAIL — `KeyError: 'annotation'`

- [ ] **Step 3: Implement**

In `harness/session.py`, add the import near the other local imports:

```python
from citation.annotate import annotate_answer
```

Add these two methods to `_Accumulator` (the class that already holds
`tool_calls` and `retrieved_chunk_ids`):

```python
    def _retrieved_chunk_map(self) -> tuple[dict[str, str], dict[str, dict]]:
        """chunk_id -> text, and chunk_id -> {doc_type, fiscal_year}, taken
        from this turn's retrieve results. The linker needs the text it was
        already sent; it must never go back to the store."""
        chunks: dict[str, str] = {}
        meta: dict[str, dict] = {}
        for call in self.tool_calls:
            if call.get("toolName") != "retrieve":
                continue
            try:
                parsed = json.loads(call.get("output") or "")
            except (TypeError, ValueError):
                continue
            for c in (parsed.get("chunks") or []):
                cid = c.get("chunk_id")
                if not cid:
                    continue
                chunks[cid] = c.get("text") or ""
                meta[cid] = {"doc_type": c.get("doc_type"),
                             "fiscal_year": c.get("fiscal_year")}
        return chunks, meta

    def annotation(self) -> dict:
        """Link every figure in the answer to a source. Never raises: a
        citation bug must not cost the user an answer they already paid
        for."""
        try:
            chunks, meta = self._retrieved_chunk_map()
            return annotate_answer(self.final_answer(), chunks, meta)
        except Exception as exc:  # noqa: BLE001 - deliberate, see docstring
            print(f"citation linking failed: {type(exc).__name__}: {exc}",
                  file=sys.stderr)
            return {"figures": []}
```

Then add one line to the `done_frame` return dict, after `"toolCalls"`:

```python
            "annotation": self.annotation(),
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_citation_session.py -v`
Expected: 4 PASS

Then confirm nothing upstream broke:

Run: `uv run pytest tests/test_harness_session.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add harness/session.py tests/test_citation_session.py
git commit -m "feat(citation): emit the figure annotation on the terminal frame"
```

---

### Task 7: Stop the model citing figures

**Files:**
- Modify: `harness/system-prompt.md`
- Test: `tests/test_citation_prompt.py`

**Interfaces:**
- Consumes: nothing. Produces: nothing programmatic.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_citation_prompt.py
"""The prompt must stop asking the model to cite figures.

The system links figures now. Leaving the old instruction in place would
pay for citation round-trips whose results are discarded, and would
re-introduce the quote-not-found failures the linker exists to remove.
"""
from __future__ import annotations

from harness.prompt import build_system_prompt

PROMPT = build_system_prompt(corpus="budget", tier="standard")


def test_prompt_tells_the_model_figures_are_linked_automatically():
    lowered = PROMPT.lower()
    assert "automatically" in lowered
    assert "figure" in lowered or "number" in lowered


def test_prompt_still_asks_for_prose_citations():
    # cite() survives, scoped to non-numeric claims.
    assert "cite(" in PROMPT or "`cite`" in PROMPT


def test_prompt_does_not_ask_the_model_to_quote_table_rows():
    # Table rows do not exist as contiguous text in extracted chunks, so
    # any instruction to quote one produces a guaranteed failure.
    lowered = PROMPT.lower()
    assert "quote the table row" not in lowered
    assert "quote the row" not in lowered
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_citation_prompt.py -v`
Expected: at least `test_prompt_tells_the_model_figures_are_linked_automatically` FAILS

- [ ] **Step 3: Edit the prompt**

Find the citation section of `harness/system-prompt.md`. Replace the
instruction to cite every claim with this, keeping the surrounding
formatting conventions of the file:

```markdown
## Citing your answer

**Do not cite dollar figures or other numbers.** Every figure you state is
linked to its source automatically, with the exact page and position — you
do not need to call `cite` for them, and doing so wastes a round-trip.

State figures plainly and accurately. If you compute a value (a total, a
year-over-year change, a percentage), state it normally; it is recognised
as computed and shown alongside the figures it came from.

**Use `cite` only for claims that are not numbers** — a policy change, a
statutory requirement, a description of what a program does. For those,
quote a short distinctive span that appears verbatim in the chunk.
```

Delete any remaining guidance instructing the model to quote table rows or
to cite each figure individually.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_citation_prompt.py -v`
Expected: 3 PASS

Then confirm the prompt-caching guard still holds — the cacheable prefix
must stay byte-identical across steps:

Run: `uv run pytest tests/test_harness_prompt_caching.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add harness/system-prompt.md tests/test_citation_prompt.py
git commit -m "feat(citation): stop asking the model to cite figures"
```

---

### Task 8: Eval — annotated answers for the judge

**Files:**
- Modify: `eval/judge_agent_run.py`, `eval/agent_judge_prompt.md`, `eval/agent_transcript.py`
- Test: `tests/test_citation_judge.py`

**Interfaces:**
- Consumes: the annotation from Task 6.
- Produces: `render_annotated_answer(answer: str, annotation: dict) -> str` in `eval/judge_agent_run.py`; `annotation(t: Transcript) -> dict` accessor in `eval/agent_transcript.py`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_citation_judge.py
"""The judge must see what the analyst sees.

Before this, the judge received raw answer text plus a detached list of
citation objects — so it could not see which figures had no chip. It
graded an abstraction and reported "over-citing" when the visible defect
was the opposite. Rendering the same annotation the UI renders closes that.
"""
from __future__ import annotations

from eval.judge_agent_run import build_judge_payload, render_annotated_answer
from eval.agent_transcript import Transcript

ANNOTATION = {"figures": [
    {"text": "$8,287.7", "start": 12, "end": 20, "index": 1,
     "verdict": "linked",
     "primary": {"chunk_id": "c-1", "source_text": "8,287,700,000",
                 "start": 0, "end": 13},
     "additional": [], "derived_from": []},
    {"text": "$2,613.7", "start": 25, "end": 33, "index": 2,
     "verdict": "unverified", "primary": None, "additional": [],
     "derived_from": []},
    {"text": "$10,901.4", "start": 40, "end": 49, "index": 3,
     "verdict": "derived", "primary": None, "additional": [],
     "derived_from": [1, 2]},
]}
ANSWER = "ADE gets $8,287.7 and $2,613.7, so $10,901.4 total."


def test_linked_figure_renders_its_index():
    out = render_annotated_answer(ANSWER, ANNOTATION)
    assert "$8,287.7 [1]" in out


def test_unverified_figure_is_visibly_marked():
    out = render_annotated_answer(ANSWER, ANNOTATION)
    assert "$2,613.7 [UNCITED]" in out


def test_derived_figure_names_its_inputs():
    out = render_annotated_answer(ANSWER, ANNOTATION)
    assert "$10,901.4 [DERIVED: 1, 2]" in out


def test_markers_do_not_corrupt_offsets_of_later_figures():
    # Inserted right-to-left, so an early marker cannot shift a later one.
    out = render_annotated_answer(ANSWER, ANNOTATION)
    assert out.index("$8,287.7") < out.index("$2,613.7") < out.index("$10,901.4")


def test_answer_without_annotation_is_returned_unchanged():
    assert render_annotated_answer(ANSWER, {"figures": []}) == ANSWER


def test_payload_carries_the_annotated_answer_and_figure_counts():
    from eval.agent_schema import AgentQuery
    t = Transcript(meta={}, events=[], terminal={"frame": {
        "type": "_done", "finalAnswer": ANSWER, "citations": [],
        "toolCalls": [], "annotation": ANNOTATION}})
    q = AgentQuery(id="q1", question="how much?", shape="lookup")
    payload = build_judge_payload(q, t)
    assert "[UNCITED]" in payload["annotated_answer"]
    assert payload["figure_counts"] == {
        "linked": 1, "derived": 1, "unverified": 1}
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_citation_judge.py -v`
Expected: FAIL — `ImportError: cannot import name 'render_annotated_answer'`

- [ ] **Step 3: Implement**

Add to `eval/agent_transcript.py`:

```python
def annotation(t: Transcript) -> dict[str, Any]:
    """The figure annotation recorded on the terminal frame. Absent on
    transcripts recorded before citation linking shipped."""
    return _frame(t).get("annotation") or {"figures": []}
```

Add to `eval/judge_agent_run.py`:

```python
def render_annotated_answer(answer: str, annotation: dict[str, Any]) -> str:
    """The answer as the analyst sees it, with each figure's citation state
    inline. The webapp draws chips from this same annotation, so the judge
    grades the artifact the user actually reads."""
    figures = sorted(annotation.get("figures") or [],
                     key=lambda f: f.get("start", 0), reverse=True)
    out = answer
    # Right-to-left insertion: a marker inserted early would shift every
    # later figure's offsets.
    for fig in figures:
        verdict = fig.get("verdict")
        if verdict == "linked":
            marker = f" [{fig.get('index')}]"
        elif verdict == "derived":
            inputs = ", ".join(str(i) for i in fig.get("derived_from") or [])
            marker = f" [DERIVED: {inputs}]"
        else:
            marker = " [UNCITED]"
        end = fig.get("end", 0)
        out = out[:end] + marker + out[end:]
    return out
```

In `build_judge_payload`, import `annotation` from `eval.agent_transcript`
and add two keys to the returned dict:

```python
    ann = annotation(t)
    counts = {"linked": 0, "derived": 0, "unverified": 0}
    for fig in ann.get("figures") or []:
        verdict = fig.get("verdict")
        if verdict in counts:
            counts[verdict] += 1
    payload["annotated_answer"] = render_annotated_answer(final_answer(t), ann)
    payload["figure_counts"] = counts
```

- [ ] **Step 4: Update the judge prompt**

In `eval/agent_judge_prompt.md`, add this to the payload description and
the rules, keeping the existing JSON schema intact:

```markdown
You also receive `annotated_answer`: the answer exactly as the analyst
sees it, with each figure's citation state inline — `[1]` for a figure
linked to a source, `[DERIVED: 1, 2]` for one computed from other figures,
and `[UNCITED]` for one that is neither.

Add these fields to your JSON output:

  "figure_coverage_ok": true|false,   // is EVERY figure either linked or derived?
  "placement_ok": true|false,         // is each marker on the figure it supports?

Judge figure coverage on the annotated answer, not on citation count. A
figure marked `[UNCITED]` is a defect. Many citations are not a defect —
completeness and correct placement are what matter.
```

- [ ] **Step 5: Run to verify pass**

Run: `uv run pytest tests/test_citation_judge.py tests/test_eval_agent_judge.py -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add eval/judge_agent_run.py eval/agent_judge_prompt.md \
        eval/agent_transcript.py tests/test_citation_judge.py
git commit -m "feat(eval): judge grades the annotated answer the analyst sees"
```

---

### Task 9: Eval — figure metrics in the mechanical scorer

**Files:**
- Modify: `eval/agent_scoring.py`, `eval/compare_agent_runs.py`
- Test: `tests/test_citation_metrics.py`

**Interfaces:**
- Consumes: `annotation` accessor from Task 8.
- Produces: per-query `figures_total`, `figures_linked`, `figures_derived`, `figures_unverified`, `figure_coverage`; summary `figure_coverage_mean`, `unverified_rate`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_citation_metrics.py
"""Figure metrics replace citation VOLUME as the citation-quality signal.

Coverage and correctness are the goal; a high citation count is not a
defect. These metrics measure what was actually asked for.
"""
from __future__ import annotations

import pytest

from eval.agent_scoring import aggregate, score_transcript
from eval.agent_schema import AgentQuery
from eval.agent_transcript import Transcript


def transcript(figures):
    return Transcript(meta={"query_id": "q1", "repeat": 1}, events=[],
                      terminal={"frame": {
                          "type": "_done", "stopReason": "end_turn",
                          "finalAnswer": "answer", "citations": [],
                          "retrievedChunkIds": [], "toolCalls": [],
                          "annotation": {"figures": figures},
                          "usage": {"inputTokens": 10, "outputTokens": 2,
                                    "cacheReadTokens": 0, "cost": 0.001}},
                          "wall_ms": 100})


def fig(verdict, index=1):
    return {"text": "$1,000,000", "start": 0, "end": 10, "index": index,
            "verdict": verdict, "primary": None, "additional": [],
            "derived_from": []}


QUERY = AgentQuery(id="q1", question="how much?", shape="lookup")


def test_full_coverage():
    row = score_transcript(QUERY, transcript(
        [fig("linked", 1), fig("derived", 2)]))
    assert row["figures_total"] == 2
    assert row["figures_linked"] == 1
    assert row["figures_derived"] == 1
    assert row["figures_unverified"] == 0
    assert row["figure_coverage"] == 1.0


def test_partial_coverage_matches_the_reported_defect():
    # Two of ten figures carry a citation — the shape of the screenshot
    # that prompted this work. It must score badly.
    figs = [fig("linked", 1), fig("linked", 2)] + [
        fig("unverified", i) for i in range(3, 11)]
    row = score_transcript(QUERY, transcript(figs))
    assert row["figure_coverage"] == pytest.approx(0.2)
    assert row["figures_unverified"] == 8


def test_no_figures_yields_none_not_zero():
    # An answer with no figures is not a coverage failure.
    row = score_transcript(QUERY, transcript([]))
    assert row["figures_total"] == 0
    assert row["figure_coverage"] is None


def test_aggregate_reports_coverage_and_unverified_rate():
    rows = [score_transcript(QUERY, transcript([fig("linked", 1)])),
            score_transcript(QUERY, transcript([fig("unverified", 1)]))]
    summary = aggregate(rows)
    assert summary["figure_coverage_mean"] == pytest.approx(0.5)
    assert summary["unverified_rate"] == pytest.approx(0.5)


def test_transcript_without_annotation_does_not_crash():
    t = Transcript(meta={"query_id": "q1", "repeat": 1}, events=[],
                   terminal={"frame": {"type": "_done", "stopReason": "end_turn",
                                       "finalAnswer": "a", "citations": [],
                                       "retrievedChunkIds": [], "toolCalls": [],
                                       "usage": {}}, "wall_ms": 1})
    row = score_transcript(QUERY, t)
    assert row["figures_total"] == 0
    assert row["figure_coverage"] is None
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_citation_metrics.py -v`
Expected: FAIL — `KeyError: 'figures_total'`

- [ ] **Step 3: Implement**

In `eval/agent_scoring.py`, import the accessor beside the others:

```python
from eval.agent_transcript import annotation
```

Add to `score_transcript`, before the `return row`:

```python
    # Figure-citation coverage. This replaces citation COUNT as the
    # citation-quality signal: many citations are fine, missing ones are
    # not. `None` when the answer states no figures — that is not a
    # coverage failure and must not average in as a zero.
    ann_figures = annotation(t).get("figures") or []
    counts = {"linked": 0, "derived": 0, "unverified": 0}
    for entry in ann_figures:
        verdict = entry.get("verdict")
        if verdict in counts:
            counts[verdict] += 1
    row["figures_total"] = len(ann_figures)
    row["figures_linked"] = counts["linked"]
    row["figures_derived"] = counts["derived"]
    row["figures_unverified"] = counts["unverified"]
    row["figure_coverage"] = (
        (counts["linked"] + counts["derived"]) / len(ann_figures)
        if ann_figures else None)
```

Add to `aggregate`, beside the other summary fields:

```python
        "figure_coverage_mean": _mean([r["figure_coverage"] for r in ok_rows]),
        "unverified_rate": _mean(
            [r["figures_unverified"] / r["figures_total"]
             for r in ok_rows if r["figures_total"]]),
```

In `eval/compare_agent_runs.py`, add `"figure_coverage_mean"` to
`_HIGHER_IS_BETTER` and `"unverified_rate"` to `_LOWER_IS_BETTER`.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_citation_metrics.py tests/test_eval_agent_score_run.py tests/test_eval_agent_compare.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add eval/agent_scoring.py eval/compare_agent_runs.py tests/test_citation_metrics.py
git commit -m "feat(eval): figure coverage and unverified rate replace citation volume"
```

---

### Task 10: Webapp — render the annotation

**Files:**
- Create: `webapp/src/chat/citation-annotation.ts`
- Modify: `webapp/src/chat/CitedMarkdownContent.tsx`, `webapp/src/chat/CitationChip.tsx`
- Test: `webapp/src/chat/__tests__/citation-annotation.test.ts`

**Interfaces:**
- Consumes: the `annotation` field on the `_done` frame.
- Produces: `AnnotationFigure` type and `figuresForRender(annotation: unknown): AnnotationFigure[]`.

- [ ] **Step 1: Write the failing test**

```ts
// webapp/src/chat/__tests__/citation-annotation.test.ts
/**
 * The annotation is the same artifact the eval judge reads. Parsing it
 * defensively matters because a turn recorded before citation linking
 * shipped has no annotation at all.
 */
import { describe, expect, it } from "vitest";
import { figuresForRender } from "../citation-annotation";

const ANNOTATION = {
  figures: [
    { text: "$8,287.7", start: 12, end: 20, index: 1, verdict: "linked",
      primary: { chunk_id: "c-1", source_text: "8,287,700,000", start: 0, end: 13 },
      additional: [{ chunk_id: "c-2", source_text: "8,287,700,000", start: 5, end: 18 }],
      derived_from: [] },
    { text: "$17,654.2", start: 40, end: 49, index: 2, verdict: "derived",
      primary: null, additional: [], derived_from: [1] },
    { text: "$99.9", start: 60, end: 65, index: 3, verdict: "unverified",
      primary: null, additional: [], derived_from: [] },
  ],
};

describe("figuresForRender", () => {
  it("returns figures in reading order", () => {
    const figs = figuresForRender(ANNOTATION);
    expect(figs.map((f) => f.index)).toEqual([1, 2, 3]);
    expect(figs.map((f) => f.start)).toEqual([12, 40, 60]);
  });

  it("carries the primary source and its corroborating references", () => {
    const [first] = figuresForRender(ANNOTATION);
    expect(first.primary?.chunkId).toBe("c-1");
    expect(first.primary?.sourceText).toBe("8,287,700,000");
    expect(first.additional).toHaveLength(1);
    expect(first.additional[0]!.chunkId).toBe("c-2");
  });

  it("marks derived figures with their inputs and no source", () => {
    const derived = figuresForRender(ANNOTATION)[1]!;
    expect(derived.verdict).toBe("derived");
    expect(derived.primary).toBeNull();
    expect(derived.derivedFrom).toEqual([1]);
  });

  it("marks unverified figures", () => {
    expect(figuresForRender(ANNOTATION)[2]!.verdict).toBe("unverified");
  });

  it("returns nothing for a turn recorded before linking shipped", () => {
    expect(figuresForRender(undefined)).toEqual([]);
    expect(figuresForRender({})).toEqual([]);
    expect(figuresForRender({ figures: null })).toEqual([]);
  });

  it("drops malformed entries rather than throwing", () => {
    const figs = figuresForRender({ figures: ["nonsense", { verdict: "linked" }] });
    expect(figs).toEqual([]);
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd webapp && npx vitest run src/chat/__tests__/citation-annotation.test.ts`
Expected: FAIL — cannot resolve `../citation-annotation`

- [ ] **Step 3: Implement**

```ts
// webapp/src/chat/citation-annotation.ts
/**
 * Parse the figure annotation the server attaches to a finished turn.
 *
 * This is the same artifact the eval judge renders as inline markers, so
 * what the analyst sees and what the eval grades come from one source.
 * Parsing is defensive because a turn recorded before citation linking
 * shipped carries no annotation.
 */

export type FigureVerdict = "linked" | "derived" | "unverified";

export interface AnnotationSource {
  chunkId: string;
  sourceText: string;
  start: number;
  end: number;
}

export interface AnnotationFigure {
  text: string;
  start: number;
  end: number;
  index: number;
  verdict: FigureVerdict;
  primary: AnnotationSource | null;
  additional: AnnotationSource[];
  derivedFrom: number[];
}

function toSource(raw: unknown): AnnotationSource | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  if (typeof r.chunk_id !== "string") return null;
  return {
    chunkId: r.chunk_id,
    sourceText: typeof r.source_text === "string" ? r.source_text : "",
    start: typeof r.start === "number" ? r.start : 0,
    end: typeof r.end === "number" ? r.end : 0,
  };
}

export function figuresForRender(annotation: unknown): AnnotationFigure[] {
  if (!annotation || typeof annotation !== "object") return [];
  const raw = (annotation as Record<string, unknown>).figures;
  if (!Array.isArray(raw)) return [];

  const figures: AnnotationFigure[] = [];
  for (const entry of raw) {
    if (!entry || typeof entry !== "object") continue;
    const e = entry as Record<string, unknown>;
    const verdict = e.verdict;
    if (verdict !== "linked" && verdict !== "derived" && verdict !== "unverified") {
      continue;
    }
    if (typeof e.text !== "string" || typeof e.start !== "number") continue;
    figures.push({
      text: e.text,
      start: e.start,
      end: typeof e.end === "number" ? e.end : e.start,
      index: typeof e.index === "number" ? e.index : figures.length + 1,
      verdict,
      primary: toSource(e.primary),
      additional: Array.isArray(e.additional)
        ? e.additional.map(toSource).filter((s): s is AnnotationSource => s !== null)
        : [],
      derivedFrom: Array.isArray(e.derived_from)
        ? e.derived_from.filter((n): n is number => typeof n === "number")
        : [],
    });
  }
  // Reading order — chip numbering follows the answer, not emission.
  return figures.sort((a, b) => a.start - b.start);
}
```

- [ ] **Step 4: Run to verify pass**

Run: `cd webapp && npx vitest run src/chat/__tests__/citation-annotation.test.ts`
Expected: 6 PASS

- [ ] **Step 5: Write the failing rendering test**

Read `CitedMarkdownContent.tsx` and `CitationChip.tsx` first — this step
reuses their existing sentinel-injection mechanism rather than adding a
second one. Then pin the contract:

```tsx
// webapp/src/chat/__tests__/annotation-render.test.tsx
/**
 * Chips come from the server annotation, land on the figure they support,
 * and are numbered in reading order. The reported defect was a ten-row
 * table with two chips numbered 1-3-4-2; this is the test that fails if
 * that returns.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CitedMarkdownContent } from "../CitedMarkdownContent";

const ANNOTATION = {
  figures: [
    { text: "$8,287.7", start: 9, end: 17, index: 1, verdict: "linked",
      primary: { chunk_id: "c-1", source_text: "8,287,700,000", start: 0, end: 13 },
      additional: [{ chunk_id: "c-2", source_text: "8,287,700,000", start: 0, end: 13 }],
      derived_from: [] },
    { text: "$2,613.7", start: 22, end: 30, index: 2, verdict: "linked",
      primary: { chunk_id: "c-3", source_text: "2,613,700,000", start: 0, end: 13 },
      additional: [], derived_from: [] },
    { text: "$10,901.4", start: 41, end: 50, index: 3, verdict: "derived",
      primary: null, additional: [], derived_from: [1, 2] },
    { text: "$99,999.9", start: 60, end: 69, index: 4, verdict: "unverified",
      primary: null, additional: [], derived_from: [] },
  ],
};
const ANSWER = "ADE gets $8,287.7 and $2,613.7, totalling $10,901.4; also $99,999.9.";

describe("annotation rendering", () => {
  it("renders one chip per figure, numbered in reading order", () => {
    render(<CitedMarkdownContent text={ANSWER} annotation={ANNOTATION} citations={[]} />);
    const chips = screen.getAllByTestId("citation-chip");
    expect(chips).toHaveLength(4);
    expect(chips.map((c) => c.textContent)).toEqual(["1", "2", "3", "4"]);
  });

  it("marks derived and unverified figures distinctly", () => {
    render(<CitedMarkdownContent text={ANSWER} annotation={ANNOTATION} citations={[]} />);
    expect(screen.getByTestId("citation-chip-derived-3")).toBeTruthy();
    expect(screen.getByTestId("citation-chip-unverified-4")).toBeTruthy();
  });

  it("renders nothing extra for a turn with no annotation", () => {
    render(<CitedMarkdownContent text={ANSWER} annotation={{ figures: [] }} citations={[]} />);
    expect(screen.queryAllByTestId("citation-chip")).toHaveLength(0);
  });
});
```

Run: `cd webapp && npx vitest run src/chat/__tests__/annotation-render.test.tsx`
Expected: FAIL — `CitedMarkdownContent` does not accept an `annotation` prop.

- [ ] **Step 6: Implement the rendering**

In `CitedMarkdownContent.tsx`: accept an `annotation` prop, call
`figuresForRender`, and inject a chip sentinel at each figure's `end`
offset **right-to-left**, so an earlier insertion cannot shift a later
figure's offsets. Use the existing sentinel mechanism; do not add a second
one. Model-issued prose citations keep rendering exactly as they do today.

In `CitationChip.tsx`, add three states, each carrying the `data-testid`
the test above expects:
- `linked` — current appearance showing `index`; the popover shows the
  primary source, and when `additional` is non-empty an "Also appears in:"
  list of the outranked editions.
- `derived` — visually distinct; popover reads "Computed from [n], [m]"
  and offers no PDF link.
- `unverified` — warning appearance; popover reads "This figure was not
  found in the retrieved sources."

Run: `cd webapp && npx vitest run src/chat/__tests__/annotation-render.test.tsx`
Expected: 3 PASS

- [ ] **Step 7: Verify the whole webapp suite**

Run: `cd webapp && npx vitest run`
Expected: all PASS

Run: `cd webapp && npx tsc -b`
Expected: exit 0 (the production build is stricter than `--noEmit`)

- [ ] **Step 8: Commit**

```bash
git add webapp/src/chat/citation-annotation.ts \
        webapp/src/chat/CitedMarkdownContent.tsx \
        webapp/src/chat/CitationChip.tsx \
        webapp/src/chat/__tests__/citation-annotation.test.ts \
        webapp/src/chat/__tests__/annotation-render.test.tsx
git commit -m "feat(webapp): render figure chips from the server annotation"
```

---

### Task 11: PDF highlight uses the source rendering

**Files:**
- Modify: `webapp/src/pdf/highlight-strategy.ts`
- Test: `webapp/src/pdf/__tests__/highlight-strategy.test.ts`

**Interfaces:**
- Consumes: `AnnotationSource.sourceText` from Task 10.

- [ ] **Step 1: Write the failing test**

```ts
// webapp/src/pdf/__tests__/highlight-strategy.test.ts
/**
 * The PDF text layer contains the SOURCE's rendering of a figure
 * ("8,287,700,000"), never the answer's ("$8,287.7"). Searching for the
 * answer's form is why highlights missed.
 */
import { describe, expect, it, vi } from "vitest";
import { TextLayerSearchStrategy } from "../highlight-strategy";

function fakePage(textItems: string[]) {
  return {
    getTextContent: vi.fn().mockResolvedValue({
      items: textItems.map((str) => ({ str, transform: [1, 0, 0, 1, 0, 0], width: 10, height: 5 })),
    }),
  } as never;
}

const viewport = { convertToViewportRectangle: (r: number[]) => r, height: 800 } as never;

describe("TextLayerSearchStrategy", () => {
  it("finds the source rendering when given sourceText", async () => {
    const page = fakePage(["Department of Education", "8,287,700,000"]);
    const rects = await new TextLayerSearchStrategy().resolve({
      page, viewport, quote: "$8,287.7", sourceText: "8,287,700,000",
      fullChunkText: "", bbox: null,
    } as never);
    expect(rects.length).toBeGreaterThan(0);
  });

  it("prefers sourceText over the answer's rendering", async () => {
    const page = fakePage(["8,287,700,000"]);
    const strategy = new TextLayerSearchStrategy();
    const withSource = await strategy.resolve({
      page, viewport, quote: "$8,287.7", sourceText: "8,287,700,000",
      fullChunkText: "", bbox: null,
    } as never);
    const withoutSource = await strategy.resolve({
      page, viewport, quote: "$8,287.7", fullChunkText: "", bbox: null,
    } as never);
    expect(withSource.length).toBeGreaterThan(0);
    expect(withoutSource.length).toBe(0);
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd webapp && npx vitest run src/pdf/__tests__/highlight-strategy.test.ts`
Expected: FAIL — `sourceText` is not part of `ResolveArgs`

- [ ] **Step 3: Implement**

Add `sourceText?: string` to the `ResolveArgs` interface, and put it first
in the candidate list inside `TextLayerSearchStrategy.resolve`:

```ts
    const targets = [sourceText, quote, fullChunkText].filter(
      (t): t is string => typeof t === "string" && t.length > 0,
    );
```

Pass `primary.sourceText` through from the chip's click handler.

- [ ] **Step 4: Run to verify pass**

Run: `cd webapp && npx vitest run src/pdf/`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add webapp/src/pdf/highlight-strategy.ts \
        webapp/src/pdf/__tests__/highlight-strategy.test.ts
git commit -m "fix(pdf): highlight the source rendering of a figure, not the answer's"
```

---

### Task 12: Verify end to end and re-baseline

**Files:** none — verification only.

- [ ] **Step 1: Full suites**

```bash
uv run pytest tests/ -q
cd webapp && npx vitest run && npx tsc -b
```
Expected: all green.

- [ ] **Step 2: Reproduce the reported defect**

```bash
cat > repro_tmp.py <<'EOF'
from harness.session import HarnessSession
from harness.settings import load_settings
from harness.ledger import LimitStatus

def allow(*a, **k): return LimitStatus("allowed", None, None, None, None)
s = HarnessSession("repro", corpus="budget", tier="standard", user="eval",
                   settings=load_settings(), check_limit=allow,
                   record_usage=lambda *a, **k: None)
frame = s.send_turn("what are the biggest agencies by budget")
s.close()
figs = frame["annotation"]["figures"]
from collections import Counter
print(Counter(f["verdict"] for f in figs))
print("indices in reading order:", [f["index"] for f in figs])
print("model cite calls:", sum(1 for c in frame["toolCalls"]
                               if c["toolName"] in ("cite", "cite_batch")))
EOF
uv run python repro_tmp.py; rm -f repro_tmp.py
```

Expected: nearly every figure `linked` or `derived`, indices strictly
ascending, and **zero** model cite calls for a numeric answer. If figures
are still `unverified` in bulk, stop and report before continuing.

- [ ] **Step 3: Re-baseline the Layer 2 eval**

```bash
uv run python -m eval.run_agent_eval --subset full --note "post citation-linking"
uv run python -m eval.score_agent_run eval/results/agent/<new-run>
uv run python -m eval.judge_agent_run eval/results/agent/<new-run>
uv run python -m eval.compare_agent_runs \
    eval/results/agent/2026-08-02T0900Z-0b08221 eval/results/agent/<new-run>
```

Expected direction: `figure_coverage_mean` high, `unverified_rate` low,
`steps_mean` and `input_tokens_mean` **down** (cite round-trips removed),
`cite_pass_rate` no longer dominated by figure citations.

- [ ] **Step 4: Commit the new baseline and update STATUS.md**

Commit `manifest.json`, `scores.json`, `scores.md`, `judge.json` and the
compare report. Add a STATUS.md section recording what shipped and the
before/after numbers, following the pattern of the neighbouring sections.

```bash
git add -f eval/results/agent/<new-run>/manifest.json \
           eval/results/agent/<new-run>/scores.json \
           eval/results/agent/<new-run>/scores.md \
           eval/results/agent/<new-run>/judge.json \
           eval/results/agent/compare-*.md
git add STATUS.md
git commit -m "eval: re-baseline after citation linking"
```
