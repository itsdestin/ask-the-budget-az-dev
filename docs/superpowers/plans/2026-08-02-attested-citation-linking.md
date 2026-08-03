# Attested Citation Linking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement spec A1–A6, A8, A9 of
`docs/superpowers/specs/2026-08-02-attested-citation-linking-design.md`:
the model attests each figure's source chunk with an inline `[[cN]]`
marker, the system verifies the claim mechanically, untagged figures link
only when unambiguous, matching runs at written precision, failed links
surface the near-miss, and the ship gate is the false-link rate.

**Scope note:** A7 (the ingest coordinate map) is a separate plan —
`2026-08-XX-citation-coordmap.md`, not yet written. Nothing in this plan
depends on it; the existing highlight chain keeps working.

**Architecture:** `ToolExecutor` assigns each retrieved chunk a stable
per-conversation alias (`c1`, `c2`, …) that rides on the retrieve JSON the
model reads. The model appends `[[cN]]` after each figure. At turn end the
accumulator parses markers out of the raw answer (they never reach any
consumer, including the streaming frames), and `citation/annotate.py`
verifies each attested figure against the named chunk only, falls back to
unambiguous-only linking for untagged figures, and reconciles leftovers at
written precision. `citation/authority.py` is deleted.

**Tech Stack:** Python 3.12 / pytest (harness + citation), TypeScript /
vitest (webapp), no new dependencies.

## Global Constraints

- **Never wrong-doc (spec R1):** no code path may pick a source by rank or
  authority among multiple candidate documents. Tag-verified or
  unambiguous, else no link.
- **Markers never reach a consumer (spec A1):** not the streaming frames,
  not `finalAnswer`, not transcripts. A leaked marker is a P1 render bug.
- **Annotation contract is extended, not broken:** existing fields
  (`text/start/end/index/verdict/primary/additional/derived_from`) keep
  their exact names and shapes; new fields are additive. The webapp parser
  is defensive, so an old transcript must still render.
- **Ship gate (spec A8):** false-link rate measured before/after with
  `eval/false_link_check.py`; figure coverage on the 31-query baseline
  transcripts must stay ≥ 92.9%. Report both numbers in the final commit.
- **Work in a worktree** (`~/ask-the-budget-az-worktrees/attested-citations/`)
  per CLAUDE.md; merge means merge AND push.
- **`harness/system-prompt.md` changes** trigger the CLAUDE.md eval rule:
  Layer 1 eval cannot see prompt changes (it calls `retrieve()` directly),
  so the mandatory check is the Layer 2 live smoke — which needs a key and
  becomes the runbook in Task 11.
- Python suite: `uv run pytest -x -q`. Webapp: `cd webapp && npx vitest run`
  and `npx tsc -b`. All green before merge.
- Non-trivial edits carry a WHY comment (Destin reads the code through the
  comments).

## File structure

| File | Responsibility |
|---|---|
| `citation/markers.py` (new) | marker grammar: parse + strip + streaming-safe strip |
| `citation/figures.py` | + written precision (`halfwidth`) and `written_significant_digits` |
| `citation/matching.py` | rewrite: interval match anchored on the figure's absolute value; `restrict_to`; `nearest_value` |
| `citation/reconcile.py` | tolerance becomes the target's written precision |
| `citation/annotate.py` | rewrite: tag verification → unambiguous fallback → derived → near-miss |
| `citation/authority.py` | **deleted** (with `tests/test_citation_authority.py`) |
| `harness/tools.py` | alias assignment on retrieve results; `alias_map` property |
| `harness/session.py` | strip markers from stream + final answer; pass tags/alias_map to annotate |
| `harness/system-prompt.md` | the tagging instruction |
| `webapp/src/chat/citation-annotation.ts` | parse new annotation fields |
| `webapp/src/chat/CitationChip.tsx` | near-miss / ambiguous / derived tooltip copy |
| `eval/agent_scoring.py` | marker coverage + tag accuracy metrics |
| `eval/false_link_check.py` (new) | the A8 gate script |
| `tests/test_citation_markers.py` (new), existing `tests/test_citation_*.py` | suites |

---

### Task 1: `citation/markers.py` — the marker grammar

**Files:**
- Create: `citation/markers.py`
- Test: `tests/test_citation_markers.py`

**Interfaces:**
- Produces: `Tag` (frozen dataclass: `aliases: tuple[str, ...]`, `at: int` —
  char offset **in the stripped text** where the marker began);
  `parse_markers(raw: str) -> tuple[str, list[Tag]]`;
  `strip_for_stream(text: str) -> str`.
- Consumed by: Task 5 (`annotate_answer(tags=…)`), Task 7 (session).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_citation_markers.py
"""The marker grammar. Markers are the model's provenance claims; they
must strip cleanly out of every consumer-visible string, including the
malformed shapes a model under load actually produces."""
from citation.markers import Tag, parse_markers, strip_for_stream


def test_well_formed_marker_is_stripped_and_recorded():
    stripped, tags = parse_markers("grew to $8,287.7 million [[c3]] this year")
    assert stripped == "grew to $8,287.7 million this year"
    assert tags == [Tag(aliases=("c3",), at=25)]
    # The offset indexes the STRIPPED text: position 25 is where the
    # marker used to sit, i.e. right after "million ".
    assert stripped[:tags[0].at].endswith("million ")


def test_multi_alias_marker():
    stripped, tags = parse_markers("fell [[c3, c12]].")
    assert stripped == "fell ."
    assert tags[0].aliases == ("c3", "c12")


def test_multiple_markers_offsets_all_index_stripped_text():
    raw = "A [[c1]] then B [[c2]] end"
    stripped, tags = parse_markers(raw)
    assert stripped == "A then B end"
    assert [t.at for t in tags] == [2, 9]


def test_malformed_markers_are_stripped_but_yield_no_tag():
    # single close bracket / junk after alias / unterminated at EOF —
    # every shape strips, none becomes a Tag.
    for raw in ("x [[c3] y", "x [[c3 oops]] y", "x [[c3"):
        stripped, tags = parse_markers(raw)
        assert "[[" not in stripped
        assert tags == []


def test_double_brackets_that_are_not_markers_are_left_alone():
    raw = "the statute [[A.R.S. 35-142]] says"
    stripped, tags = parse_markers(raw)
    assert stripped == raw  # only [[c<digit>… shapes are marker-like
    assert tags == []


def test_strip_for_stream_removes_complete_and_holds_back_partial():
    assert strip_for_stream("grew to $8.2M [[c3]] and") == "grew to $8.2M and"
    # A trailing partial marker is HELD BACK, not shown: the next frame
    # carries the full accumulated text again, so nothing is lost.
    assert strip_for_stream("grew to $8.2M [[c") == "grew to $8.2M "
    assert strip_for_stream("grew to $8.2M [[") == "grew to $8.2M "
    assert strip_for_stream("grew to $8.2M [") == "grew to $8.2M "
    # ...but an ordinary markdown link stays intact once complete.
    assert strip_for_stream("see [the report](url)") == "see [the report](url)"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_citation_markers.py -q`
Expected: FAIL — `ModuleNotFoundError: citation.markers`

- [ ] **Step 3: Implement `citation/markers.py`**

```python
"""The [[cN]] marker grammar — the model's inline provenance claims.

A marker is a HYPOTHESIS the system verifies, never a fact (spec A2). It
must strip out of every consumer-visible string: an analyst seeing [[c3]]
in an answer is a P1 bug, so stripping is deliberately greedy about
malformed shapes — anything that starts like a marker is removed even
when it cannot be parsed into a Tag.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Well-formed: [[c3]] or [[c3, c12]]. Only c<digits> aliases — [[A.R.S.
# 35-142]] is legislative prose, not a marker, and must survive.
_WELL_FORMED = r"\[\[\s*(?P<aliases>c\d+(?:\s*,\s*c\d+)*)\s*\]\]"
# Malformed-but-marker-like: starts [[c<digit>, ends in ] or ]] with junk
# inside, or runs unterminated to end of text.
_MALFORMED = r"\[\[\s*c\d+[^\]\n]*(?:\]{1,2}|$)"
_ANY_MARKER = re.compile(f"{_WELL_FORMED}|{_MALFORMED}")

# For the stream: any trailing prefix that COULD still become a marker is
# held back. The delta frames carry full accumulated text, so held-back
# characters reappear the moment they resolve into (non-)marker text.
_TRAILING_PARTIAL = re.compile(r"\[{1,2}\s*(?:c\d*)?$")


@dataclass(frozen=True)
class Tag:
    aliases: tuple[str, ...]
    at: int  # offset in the STRIPPED text where the marker began


def parse_markers(raw: str) -> tuple[str, list[Tag]]:
    """Strip every marker-like span; return stripped text + parsed tags.

    Tag offsets index the stripped text because that is the string every
    downstream consumer (figure extractor, UI, transcripts) sees — an
    offset into the raw text would be off by the width of every earlier
    marker.
    """
    out: list[str] = []
    tags: list[Tag] = []
    pos = 0
    removed = 0
    for m in _ANY_MARKER.finditer(raw):
        out.append(raw[pos:m.start()])
        aliases = m.group("aliases")
        if aliases:
            parts = tuple(a.strip() for a in aliases.split(","))
            tags.append(Tag(aliases=parts, at=m.start() - removed))
        removed += m.end() - m.start()
        pos = m.end()
    out.append(raw[pos:])
    return "".join(out), tags


def strip_for_stream(text: str) -> str:
    """What a streaming frame may show: complete markers removed, a
    trailing could-be-marker prefix held back."""
    stripped, _ = parse_markers(text)
    return _TRAILING_PARTIAL.sub("", stripped)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_citation_markers.py -q`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add citation/markers.py tests/test_citation_markers.py
git commit -m "feat(citation): [[cN]] marker grammar — parse, strip, stream-safe strip (spec A1)"
```

---

### Task 2: written precision on `Figure`

**Files:**
- Modify: `citation/figures.py`
- Test: `tests/test_citation_figures.py` (append)

**Interfaces:**
- Produces: `Figure.halfwidth -> float` (absolute-dollar half-width of the
  interval the written form certifies, spec A4);
  `written_significant_digits(raw: str) -> int` (module function — digits
  of the numeral, leading and trailing zeros stripped).
- Consumed by: Tasks 3, 4.

- [ ] **Step 1: Write the failing tests** (append to
  `tests/test_citation_figures.py`)

```python
from citation.figures import extract_figures, written_significant_digits


def test_halfwidth_is_half_the_last_written_decimal_place():
    # "$10.3M" certifies [10.25M, 10.35M] — half-width 0.05 * 1e6.
    (fig,) = extract_figures("total $10.3M this year")
    assert fig.scale == 1_000_000
    assert fig.halfwidth == 0.05 * 1_000_000


def test_halfwidth_of_a_grouped_integer_is_half_a_dollar():
    (fig,) = extract_figures("total 10,297,300 exactly")
    assert fig.halfwidth == 0.5


def test_halfwidth_of_cents_is_half_a_cent():
    (fig,) = extract_figures("took in $27,362,036.72 that month")
    assert fig.halfwidth == 0.005


def test_written_significant_digits_ignores_trailing_zeros():
    assert written_significant_digits("$12.49") == 4      # the §5.4 case
    assert written_significant_digits("37") == 2
    assert written_significant_digits("1,320,598,100") == 8
    assert written_significant_digits("10.30") == 3
    assert written_significant_digits("0.05") == 1
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_citation_figures.py -q`
Expected: FAIL — `ImportError: written_significant_digits`

- [ ] **Step 3: Implement.** In `citation/figures.py`, add to the `Figure`
  dataclass and module:

```python
    @property
    def halfwidth(self) -> float:
        """Absolute half-width of the interval this rendering certifies
        (spec A4). "$10.3M" certifies [10.25M, 10.35M]; a grouped integer
        certifies ±0.5. One rule replaces the flat ±0.1% window and
        reconcile's flat 1% — both of which accepted values the written
        form does not actually support."""
        numeral = self.text.replace("$", "").replace(",", "").strip()
        decimals = len(numeral.split(".")[1]) if "." in numeral else 0
        return 0.5 * (10 ** -decimals) * self.scale


def written_significant_digits(raw: str) -> int:
    """Distinctiveness of a figure AS WRITTEN — digits with leading and
    trailing zeros stripped. "$12.49 billion" scores 4, not 11: its
    magnitude is huge but only four digits fingerprint it, which is why
    rounded billions false-link ~10x more often than exact integers
    (review memo §5.2/§5.4)."""
    digits = re.sub(r"[^0-9]", "", raw)
    digits = digits.lstrip("0").rstrip("0")
    return len(digits)
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_citation_figures.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add citation/figures.py tests/test_citation_figures.py
git commit -m "feat(citation): written-precision halfwidth + honest significant digits (spec A4)"
```

---

### Task 3: rewrite `citation/matching.py`

**Files:**
- Rewrite: `citation/matching.py`
- Rewrite: `tests/test_citation_matching.py`

**Interfaces:**
- Produces: `SourceHit(chunk_id, source_text, start, end, scale_used)` —
  `scale_used` is now **the source's rendering multiplier** (source value ×
  scale_used = the figure's absolute value);
  `find_in_chunks(fig, chunks, *, restrict_to: list[str] | None = None,
  min_significant_digits: int = 4) -> list[SourceHit]`;
  `NearMiss(chunk_id, source_text, value, distance)` and
  `nearest_value(fig, chunks, *, restrict_to=None) -> NearMiss | None`.
- Consumed by: Task 5.

**The structural change:** the old ladder walked out from the value *as
written*, so an unknown-scale figure was searched as four different
absolute values — the collision multiplier of memo §5.2. The new match is
anchored on `fig.absolute` (a single target value); the ladder only varies
which multiplier the *source's table* used. That satisfies spec A4's
scale-pinning structurally instead of by special case. The old
double-scale bug class cannot recur because there is exactly one target.

- [ ] **Step 1: Write the failing tests** (replace
  `tests/test_citation_matching.py` — the old file pins the
  written-value-anchored ladder, which is exactly what this task removes)

```python
"""Interval matching anchored on the figure's absolute value (spec A4)."""
from citation.figures import extract_figures
from citation.matching import find_in_chunks, nearest_value


def _fig(text):
    (fig,) = extract_figures(text)
    return fig


def test_scale_shifted_match_returns_the_sources_rendering():
    fig = _fig("| $ Millions |\n| $8,287.7 |")
    hits = find_in_chunks(fig, {"k1": "General Fund total 8,287,700,000 for"})
    assert hits[0].source_text == "8,287,700,000"
    assert hits[0].scale_used == 1  # source printed the absolute value


def test_source_tabulating_in_thousands_matches_via_multiplier():
    fig = _fig("spent $10,297,300 on it")
    hits = find_in_chunks(fig, {"k1": "amount 10,297.3 (in thousands)"})
    assert hits[0].scale_used == 1_000


def test_written_precision_bounds_the_match():
    # "$10.3M" certifies [10.25M, 10.35M]
    fig = _fig("about $10.3M budgeted")
    assert find_in_chunks(fig, {"k": "total 10,297,300 net"})   # inside
    assert not find_in_chunks(fig, {"k": "total 10,352,000 net"})  # outside


def test_exact_integer_does_not_match_a_nearby_value():
    # the §5.3 shape: 16,830,000,000 stated, 16,770,000,000 in source
    fig = _fig("total $16,830,000,000 combined")
    assert not find_in_chunks(fig, {"k": "sum 16,770,000,000 was"})


def test_specificity_floor_uses_written_digits():
    # "$12.49B" is 4 written digits -> at floor 5 it must be refused even
    # though its magnitude is 11 digits (the §5.4 bypass).
    fig = _fig("about $12.49B overall")
    assert not find_in_chunks(fig, {"k": "12,490,000,000"},
                              min_significant_digits=5)
    assert find_in_chunks(fig, {"k": "12,490,000,000"},
                          min_significant_digits=4)


def test_restrict_to_searches_only_the_named_chunks():
    fig = _fig("was $1,391,157,700 total")
    chunks = {"a": "x 1,391,157,700 y", "b": "x 1,391,157,700 y"}
    hits = find_in_chunks(fig, chunks, restrict_to=["b"])
    assert [h.chunk_id for h in hits] == ["b"]


def test_nearest_value_reports_the_closest_source_number():
    # the §5.5 case: $12.49B stated, 12,515.4 (millions) in source
    fig = _fig("dipped to $12.49B in")
    nm = nearest_value(fig, {"k": "revenues of 12,515.4 were"})
    assert nm is not None
    assert nm.source_text == "12,515.4"
    assert 0.001 < nm.distance < 0.01  # ~0.2%


def test_nearest_value_beyond_five_percent_is_none():
    fig = _fig("cost $10,000,000.00 total")
    assert nearest_value(fig, {"k": "value 123,456 only"}) is None
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_citation_matching.py -q`
Expected: FAIL — `ImportError: nearest_value` (and interval tests fail on
the old tolerance)

- [ ] **Step 3: Rewrite `citation/matching.py`**

```python
"""Locate a figure's value inside chunk text, at the precision the answer
actually wrote (spec A4).

The match is anchored on the figure's ABSOLUTE value — one target, always.
The scale ladder only varies which multiplier the SOURCE's table used
(a document tabulating "10,297.3" under a thousands header). The old code
anchored on the value as written, which turned an unknown-scale figure
into four different targets and multiplied collisions (memo §5.2).

Returns the SOURCE's rendering, not the answer's: the PDF text layer
contains the source's form, so highlighting must search for that string.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from citation.figures import Figure, written_significant_digits

_CANDIDATE_RE = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?")
# Which multiplier the source's own rendering uses.
_SCALES = (1, 1_000, 1_000_000, 1_000_000_000)
# A near-miss farther than 5% is not "nearly the same number" to an
# analyst — report nothing rather than noise.
_NEAR_MISS_MAX = 0.05


@dataclass(frozen=True)
class SourceHit:
    chunk_id: str
    source_text: str
    start: int
    end: int
    # source value * scale_used == the figure's absolute value: 1 when the
    # source printed the absolute number, 1_000_000 when it tabulated in
    # millions.
    scale_used: int


@dataclass(frozen=True)
class NearMiss:
    chunk_id: str
    source_text: str
    value: float      # the candidate, at the scale that got closest
    distance: float   # relative distance to the figure's absolute value


def _chunk_ids(chunks: dict[str, str],
               restrict_to: list[str] | None) -> list[str]:
    if restrict_to is None:
        return list(chunks)
    return [c for c in restrict_to if c in chunks]


def find_in_chunks(
    fig: Figure,
    chunks: dict[str, str],
    *,
    restrict_to: list[str] | None = None,
    min_significant_digits: int = 4,
) -> list[SourceHit]:
    # The floor is judged on the WRITTEN digits — "$12.49B" is the four
    # digits that fingerprint it, not the eleven of its magnitude
    # (memo §5.4: the guard must apply hardest to rounded figures).
    if written_significant_digits(fig.text) < min_significant_digits:
        return []
    target = fig.absolute
    # A match must land inside the interval the written form certifies;
    # 0.5 is the floor so an exact integer still tolerates float noise.
    halfwidth = max(fig.halfwidth, 0.5)

    hits: list[SourceHit] = []
    for chunk_id in _chunk_ids(chunks, restrict_to):
        text = chunks.get(chunk_id) or ""
        for m in _CANDIDATE_RE.finditer(text):
            candidate = float(m.group(0).replace(",", ""))
            for scale in _SCALES:
                if abs(candidate * scale - target) <= halfwidth:
                    hits.append(SourceHit(chunk_id, m.group(0),
                                          m.start(), m.end(), scale))
                    break
            else:
                continue
            break  # one hit per chunk is enough to cite it
    return hits


def nearest_value(
    fig: Figure,
    chunks: dict[str, str],
    *,
    restrict_to: list[str] | None = None,
) -> NearMiss | None:
    """The closest source number to a figure that failed to link — the
    most useful thing the system knows about a failure (memo §5.5): the
    analyst catching a wrong answer needs "$12.515B is what the source
    says", not a bare refusal."""
    target = fig.absolute
    if target <= 0:
        return None
    best: NearMiss | None = None
    for chunk_id in _chunk_ids(chunks, restrict_to):
        text = chunks.get(chunk_id) or ""
        for m in _CANDIDATE_RE.finditer(text):
            candidate = float(m.group(0).replace(",", ""))
            for scale in _SCALES:
                dist = abs(candidate * scale - target) / target
                if best is None or dist < best.distance:
                    best = NearMiss(chunk_id, m.group(0),
                                    candidate * scale, dist)
    if best is None or best.distance > _NEAR_MISS_MAX:
        return None
    return best
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_citation_matching.py -q`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add citation/matching.py tests/test_citation_matching.py
git commit -m "feat(citation): interval matching anchored on absolute value + near-miss (spec A4, A6)"
```

---

### Task 4: `reconcile` at written precision

**Files:**
- Modify: `citation/reconcile.py`
- Modify: `tests/test_citation_reconcile.py`

**Interfaces:**
- Produces: `reconcile(target: Figure, linked: list[Figure]) -> Derivation
  | None` — same signature, but `_close` now uses
  `max(target.halfwidth, 0.5)` as an absolute tolerance instead of the
  flat 1% relative one.

- [ ] **Step 1: Write the failing test** (append)

```python
def test_written_precision_rejects_the_sixteen_seventy_seven_case():
    # memo §5.3: 13.24 + 3.53 = 16.77 must NOT explain a stated $16.83B.
    # "$16.83" certifies ±0.005B = ±5M; 16.77B is 60M away.
    figs = extract_figures("was $13.24B and $3.53B so total $16.83B held")
    a, b, target = figs
    assert reconcile(target, [a, b]) is None


def test_written_precision_accepts_true_arithmetic():
    figs = extract_figures("was $13.24B and $3.53B so total $16.77B held")
    a, b, target = figs
    d = reconcile(target, [a, b])
    assert d is not None and d.operation == "sum"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_citation_reconcile.py -q`
Expected: the new rejection test FAILS (flat 1% accepts 16.77 for 16.83)

- [ ] **Step 3: Implement.** In `citation/reconcile.py`: delete the
  `_REL_TOL` constant, change `_close` and thread the tolerance:

```python
def _close(a: float, goal: float, tol: float) -> bool:
    return abs(a - goal) <= tol


def reconcile(target: Figure, linked: list[Figure]) -> Derivation | None:
    goal = target.absolute
    # The result's WRITTEN precision is what an arithmetic claim must hit
    # (spec A5). The old flat 1% accepted 16.77 as "explaining" a stated
    # 16.83 billion — different numbers (memo §5.3).
    tol = max(target.halfwidth, 0.5)
    values = [x.absolute for x in linked]
    ...
```

Every `_close(x, goal)` call site becomes `_close(x, goal, tol)`; the
percent-change branch uses the same `tol` (a percent target's halfwidth is
tiny in absolute terms, which is correct — "grew 12.4%" certifies ±0.05).
Update any existing test that pinned the 1% behaviour to the new
tolerance; the property they protect (restatements and true sums still
reconcile) is covered by the acceptance test above.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_citation_reconcile.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add citation/reconcile.py tests/test_citation_reconcile.py
git commit -m "feat(citation): derived requires arithmetic at written precision (spec A5)"
```

---

### Task 5: rewrite `citation/annotate.py` — the attested pipeline

**Files:**
- Rewrite: `citation/annotate.py`
- Delete: `citation/authority.py`, `tests/test_citation_authority.py`
- Rewrite: `tests/test_citation_annotate.py`

**Interfaces:**
- Produces: `annotate_answer(answer: str, chunks: dict[str, str],
  meta: dict[str, dict], *, tags: list[Tag] | None = None,
  alias_map: dict[str, str] | None = None) -> dict`. (`prefer_fiscal_year`
  is removed — it only fed authority ranking.) Each figure record keeps
  every existing field and gains:
  - `attested_chunk_ids: list[str]` — what the model claimed (resolved,
    in-turn chunks only)
  - `link_basis: "tag" | "unambiguous-fallback" | None`
  - `ambiguity_count: int | None` — distinct docs containing the value,
    set when > 1 blocked a fallback link
  - `near_miss: {"chunk_id", "source_text", "value", "distance"} | None`
  - `operation: str | None` — on derived figures, for the tooltip equation
- Consumes: Task 1 `Tag`, Task 3 `find_in_chunks`/`nearest_value`.

**Verdict flow per figure (spec A2/A3/A5/A6), implement exactly:**
1. tags bound to figures (rule below) → attested chunk_ids
2. attested? search those chunks only with
   `min_significant_digits=2` → hit ⇒ `linked`, basis `"tag"`,
   primary = hit in first-attested order, additional = other attested
   hits. The lower floor is deliberate: the tag is independent evidence,
   so a round figure like `$1,000,000` (one written significant digit)
   may still verify inside the single chunk the model named — while the
   pool-wide fallback keeps the strict floor of 4, because there the
   value IS the only evidence.
3. no tag, or tag-verify missed? search the whole pool → hits in exactly
   one distinct `doc_id` ⇒ `linked`, basis `"unambiguous-fallback"`,
   primary = first hit, additional = same-doc rest; hits in >1 doc ⇒
   `unverified` + `ambiguity_count`
4. still unlinked → `reconcile` over linked figures ⇒ `derived` +
   `operation`
5. still unlinked → `near_miss` = `nearest_value` over the attested chunks
   when there was a tag, else the whole pool

**Tag→figure binding rule:** a tag binds to the closest preceding figure
(max `fig.end`) with `fig.end <= tag.at`, provided the intervening text is
≤ 24 chars and matches `^\s*(?:million|billion|thousand|[MBK])?[\s.,;:)%*_—-]*$`
(whitespace, one scale word, punctuation). An unbindable tag is dropped.
Aliases resolve through `alias_map`; a resolved chunk_id not present in
`chunks` (previous-turn retrieve) is dropped from `attested_chunk_ids` —
never silently redirected (spec §5 error handling).

- [ ] **Step 1: Write the failing tests** (replace
  `tests/test_citation_annotate.py`; carry forward its helpers for meta
  dicts). The load-bearing cases:

```python
CHUNKS = {"budget-a-0001": "General Fund total 8,287,700,000 for the year",
          "budget-b-0002": "reserve balance 8,287,700,000 held in trust"}
META = {"budget-a-0001": {"doc_id": "doc-a", "doc_type": "afr"},
        "budget-b-0002": {"doc_id": "doc-b", "doc_type": "baseline-per-agency"}}
ALIASES = {"c1": "budget-a-0001", "c2": "budget-b-0002"}


def _annotate(raw_answer):
    stripped, tags = parse_markers(raw_answer)
    return annotate_answer(stripped, CHUNKS, META,
                           tags=tags, alias_map=ALIASES)


def test_a_tag_links_to_the_named_chunk_even_when_two_docs_hold_the_value():
    ann = _annotate("The total was $8,287,700,000 [[c2]] that year.")
    (fig,) = ann["figures"]
    assert fig["verdict"] == "linked"
    assert fig["link_basis"] == "tag"
    assert fig["primary"]["chunk_id"] == "budget-b-0002"
    assert fig["attested_chunk_ids"] == ["budget-b-0002"]


def test_an_untagged_ambiguous_value_is_refused_not_ranked():
    # Both docs hold the value; the old authority rule would have picked
    # the AFR. Spec A3: refuse and say why.
    ann = _annotate("The total was $8,287,700,000 that year.")
    (fig,) = ann["figures"]
    assert fig["verdict"] == "unverified"
    assert fig["ambiguity_count"] == 2
    assert fig["link_basis"] is None


def test_an_untagged_unambiguous_value_still_links():
    chunks = {"budget-a-0001": CHUNKS["budget-a-0001"]}
    ann = annotate_answer("It was $8,287,700,000 net.", chunks, META,
                          tags=[], alias_map=ALIASES)
    (fig,) = ann["figures"]
    assert fig["verdict"] == "linked"
    assert fig["link_basis"] == "unambiguous-fallback"


def test_a_tag_that_fails_verification_reports_the_near_miss_from_its_chunk():
    ann = _annotate("The total was $8,290,000,000 [[c1]] that year.")
    (fig,) = ann["figures"]
    assert fig["verdict"] == "unverified"
    assert fig["near_miss"]["chunk_id"] == "budget-a-0001"
    assert fig["near_miss"]["source_text"] == "8,287,700,000"


def test_a_tag_naming_an_out_of_turn_chunk_falls_back_not_redirects():
    ann = annotate_answer(
        "It was $8,287,700,000 net.",
        {"budget-a-0001": CHUNKS["budget-a-0001"]}, META,
        tags=[Tag(aliases=("c9",), at=21)], alias_map=ALIASES)
    (fig,) = ann["figures"]
    assert fig["attested_chunk_ids"] == []
    assert fig["link_basis"] == "unambiguous-fallback"


def test_derived_carries_its_operation():
    # Distinctive inputs (5 written significant digits each) so the
    # unambiguous fallback links them; the exact total then derives.
    chunks = {"k": "parts 1,391,200 and 2,547,300 listed"}
    meta = {"k": {"doc_id": "d"}}
    ann = annotate_answer("From $1,391,200 and $2,547,300, total $3,938,500.",
                          chunks, meta, tags=[], alias_map={})
    total = ann["figures"][-1]
    assert total["verdict"] == "derived"
    assert total["operation"] == "sum"
    assert total["derived_from"] == [1, 2]
```

Plus: binding-rule tests (a tag after "million " binds across the scale
word; a tag 30 chars of prose away does not bind), and reading-order
`index` preserved — port those assertions from the old file.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_citation_annotate.py -q`
Expected: FAIL — `annotate_answer` rejects the `tags` kwarg

- [ ] **Step 3: Rewrite `citation/annotate.py`**

```python
"""Assemble the annotation: what every figure in an answer is backed by.

The webapp renders it as chips; the eval judge renders it as inline
markers. One representation, two consumers, so what the analyst sees and
what the eval grades cannot drift apart.

Linking policy (spec A2/A3): a model tag is verified against the named
chunk only; an untagged figure links only when exactly ONE document in
the turn's pool contains the value. Nothing here ranks candidate
documents — the authority tie-break was the mechanism behind the
wrong-doc defect (memo §5.1) and is deleted, not demoted.
"""
from __future__ import annotations

import re
from dataclasses import asdict
from typing import Any

from citation.figures import Figure, extract_figures
from citation.markers import Tag
from citation.matching import find_in_chunks, nearest_value
from citation.reconcile import reconcile

# A tag binds leftward across at most a scale word and punctuation:
# "$8,287.7 million [[c3]]" binds; a tag a clause away does not — better
# an untagged figure (which still gets the fallback) than a tag bound to
# the wrong number.
_BIND_MAX_GAP = 24
_BIND_GAP_RE = re.compile(
    r"^\s*(?:million|billion|thousand|[MBK])?[\s.,;:)%*_—-]*$",
    re.IGNORECASE)


def _bind_tags(answer: str, figures: list[Figure],
               tags: list[Tag]) -> dict[int, list[str]]:
    """figure position -> the aliases the model attached to it."""
    bound: dict[int, list[str]] = {}
    for tag in tags:
        best: int | None = None
        for i, fig in enumerate(figures):
            if fig.end <= tag.at and (best is None
                                      or fig.end > figures[best].end):
                best = i
        if best is None:
            continue
        gap = answer[figures[best].end:tag.at]
        if len(gap) <= _BIND_MAX_GAP and _BIND_GAP_RE.match(gap):
            bound.setdefault(best, []).extend(tag.aliases)
    return bound


def _hit_dict(hit, meta: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """One source record, carrying enough to OPEN it (doc_id, pages, bbox
    — a chunk_id alone leaves the viewer on "Couldn't open source PDF").
    Chunk TEXT stays absent: it would ship a chunk body per figure."""
    info = meta.get(hit.chunk_id) or {}
    return {"chunk_id": hit.chunk_id, "source_text": hit.source_text,
            "start": hit.start, "end": hit.end,
            "doc_id": info.get("doc_id"), "doc_type": info.get("doc_type"),
            "doc_title": info.get("doc_title"),
            "publisher": info.get("publisher"),
            "fiscal_year": info.get("fiscal_year"),
            "page_start": info.get("page_start"),
            "page_end": info.get("page_end"), "bbox": info.get("bbox")}


def annotate_answer(
    answer: str,
    chunks: dict[str, str],
    meta: dict[str, dict[str, Any]],
    *,
    tags: list[Tag] | None = None,
    alias_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    figures = extract_figures(answer)
    bound = _bind_tags(answer, figures, tags or [])
    aliases = alias_map or {}

    records: list[dict[str, Any]] = []
    linked_figs: list[Figure] = []
    linked_indices: list[int] = []

    for i, fig in enumerate(figures):
        # Resolve the model's claim to in-turn chunks. An alias that is
        # unknown or points at a chunk not retrieved THIS turn is dropped
        # — never redirected — so a stale tag degrades to the fallback
        # instead of verifying against the wrong text (spec §5).
        attested = [aliases[a] for a in bound.get(i, [])
                    if a in aliases and aliases[a] in chunks]
        record: dict[str, Any] = {
            "text": fig.text, "start": fig.start, "end": fig.end,
            "index": i + 1, "verdict": "unverified",
            "primary": None, "additional": [], "derived_from": [],
            "attested_chunk_ids": attested, "link_basis": None,
            "ambiguity_count": None, "near_miss": None, "operation": None,
        }

        # Tag path: floor 2, because the tag is independent evidence and
        # a round "$1,000,000" (one written significant digit) must still
        # verify inside the ONE chunk the model named. The pool-wide
        # fallback below keeps the strict floor — there the value is the
        # only evidence.
        hits = (find_in_chunks(fig, chunks, restrict_to=attested,
                               min_significant_digits=2)
                if attested else [])
        if hits:
            record["verdict"] = "linked"
            record["link_basis"] = "tag"
        else:
            # Fallback — also runs when a tag failed to verify, because
            # the value may genuinely live in one other document (R2).
            pool_hits = find_in_chunks(fig, chunks)
            docs = {(meta.get(h.chunk_id) or {}).get("doc_id")
                    for h in pool_hits}
            if pool_hits and len(docs) == 1:
                hits = pool_hits
                record["verdict"] = "linked"
                record["link_basis"] = "unambiguous-fallback"
            elif len(docs) > 1:
                record["ambiguity_count"] = len(docs)

        if record["verdict"] == "linked":
            record["primary"] = _hit_dict(hits[0], meta)
            record["additional"] = [_hit_dict(h, meta) for h in hits[1:]]
            linked_figs.append(fig)
            linked_indices.append(i + 1)
        records.append(record)

    # Derived pass — after linking so a sourced figure can never be
    # misexplained as arithmetic (the §5.3 identity trap).
    for record, fig in zip(records, figures):
        if record["verdict"] != "unverified":
            continue
        derivation = reconcile(fig, linked_figs)
        if derivation is not None:
            record["verdict"] = "derived"
            record["operation"] = derivation.operation
            record["derived_from"] = [linked_indices[j]
                                      for j in derivation.inputs]
            continue
        # Near-miss (spec A6): scoped to the chunk the model NAMED when
        # there was a tag — "you said c3; c3's nearest value is X" is the
        # actionable sentence.
        nm = nearest_value(fig, chunks,
                           restrict_to=record["attested_chunk_ids"] or None)
        if nm is not None:
            record["near_miss"] = asdict(nm)

    return {"figures": records}
```

Delete `citation/authority.py` and `tests/test_citation_authority.py`.
`grep -rn "authority" --include="*.py" .` must return no live importers.

- [ ] **Step 4: Run the citation suites**

Run: `uv run pytest tests/test_citation_annotate.py tests/test_citation_markers.py tests/test_citation_matching.py tests/test_citation_figures.py tests/test_citation_reconcile.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add -A citation/ tests/
git commit -m "feat(citation): attested pipeline — tag verify, unambiguous fallback, near-miss; authority ranking deleted (spec A2, A3, A6)"
```

---

### Task 6: chunk aliases in `harness/tools.py`

**Files:**
- Modify: `harness/tools.py` (`ToolExecutor.__init__` ~line 867, `_retrieve`
  ~line 1009)
- Test: `tests/test_harness_tools.py` (append; if retrieve-response tests
  live elsewhere, follow `grep -rln "retrieval_id" tests/`)

**Interfaces:**
- Produces: each chunk dict in the retrieve response gains
  `"alias": "cN"`; `ToolExecutor.alias_map -> dict[str, str]`
  (alias → chunk_id).
- Consumed by: Task 7.

**Design note (records a spec §3-A1 amendment):** aliases are
**per-conversation monotonic**, not per-turn. The spec said per-turn; a
per-turn reset would reuse `c3` for a different chunk while the old
`c3`-labelled chunk is still visible in history — a model tagging from
memory would then verify against the WRONG chunk, which is an R1 hazard.
Monotonic aliases can never collide; a previous-turn alias resolves to a
chunk absent from the current turn's pool and Task 5 already degrades that
to the fallback. Same observable behaviour the spec requires, stronger
guarantee.

- [ ] **Step 1: Write the failing tests**

```python
def test_retrieve_chunks_carry_stable_aliases(executor_with_fake_store):
    ex = executor_with_fake_store          # use the file's existing fixture
    out1 = json.loads(ex.execute("retrieve", {"query": "adc budget"}))
    aliases = [c["alias"] for c in out1["chunks"]]
    assert aliases == [f"c{i}" for i in range(1, len(aliases) + 1)]
    # A chunk retrieved again keeps its alias; new chunks continue the
    # numbering — an alias never means two different chunks.
    out2 = json.loads(ex.execute("retrieve", {"query": "adc budget again"}))
    for c in out2["chunks"]:
        assert ex.alias_map[c["alias"]] == c["chunk_id"]
    assert len(set(ex.alias_map)) == len(ex.alias_map)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_harness_tools.py -q -k alias`
Expected: FAIL — `KeyError: 'alias'`

- [ ] **Step 3: Implement.** In `__init__` (after `_first_retrieve_pending`):

```python
        # chunk_id -> alias ("c1", "c2", …), assigned at first sight and
        # never reused (spec A1). Monotonic per CONVERSATION, not per
        # turn: reusing c3 for a different chunk while the old c3 is
        # still in the model's history would let a stale tag verify
        # against the wrong text — the exact wrong-doc failure this
        # design exists to remove.
        self._alias_by_chunk: dict[str, str] = {}
```

In `_retrieve`, after `result = retrieve(request)`:

```python
        with self._lock:
            for c in result.chunks:
                if c.chunk_id not in self._alias_by_chunk:
                    self._alias_by_chunk[c.chunk_id] = (
                        f"c{len(self._alias_by_chunk) + 1}")
```

Add `"alias": self._alias_by_chunk[c.chunk_id],` to the chunk dict right
after `"chunk_id"`. Add the property:

```python
    @property
    def alias_map(self) -> dict[str, str]:
        """alias -> chunk_id, for the turn-end annotator."""
        return {alias: cid for cid, alias in self._alias_by_chunk.items()}
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_harness_tools.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add harness/tools.py tests/test_harness_tools.py
git commit -m "feat(harness): per-conversation chunk aliases on retrieve results (spec A1)"
```

---

### Task 7: session wiring — strip everywhere, annotate with tags

**Files:**
- Modify: `harness/session.py` — `_Accumulator.__init__` (~line 1641),
  `final_answer` (~line 1718), `annotation` (~line 1769), the
  `assistant_text_delta` emit in `_stream_completion` (~line 883), and
  `_run_turn` just before `done_frame` (~line 733)
- Test: `tests/test_citation_session.py` (append)

**Interfaces:**
- Consumes: Task 1 (`parse_markers`, `strip_for_stream`), Task 5
  (`annotate_answer(tags=, alias_map=)`), Task 6 (`executor.alias_map`).
- Produces: `finalAnswer` and every `assistant_text_delta.text` are
  marker-free; `_Accumulator.alias_map: dict[str, str]` attribute
  (default `{}`), set by `_run_turn` from the executor before the done
  frame.

- [ ] **Step 1: Write the failing tests** (append to
  `tests/test_citation_session.py`, using that file's existing fake-
  transport helpers)

```python
def test_markers_never_reach_final_answer_or_delta_frames(...):
    # Drive a turn whose model text is:
    #   "ADC spent $1,391,157,700 [[c1]] that year."
    # Assert: every assistant_text_delta frame contains no "[[";
    # the _done frame's finalAnswer == "ADC spent $1,391,157,700 that year.";
    # the annotation's single figure has link_basis == "tag" and
    # attested_chunk_ids == [<the chunk c1 named>].


def test_a_delta_ending_mid_marker_holds_the_partial_back(...):
    # Feed the same answer split so one delta ends "...$1,391,157,700 [[c"
    # Assert that frame's text ends "$1,391,157,700 " and the next frame
    # (full text) renders the rest.
```

Write these as real tests against the file's existing
`HarnessSession`-with-fake-transport pattern (see
`test_citation_session.py`'s current specs for the scaffolding — reuse its
fixtures; do not invent a parallel harness).

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_citation_session.py -q`
Expected: FAIL — markers appear in frames; `annotate_answer` gets no tags

- [ ] **Step 3: Implement, four edits:**

1. Import: `from citation.markers import parse_markers, strip_for_stream`.
2. `_Accumulator.__init__`: add `self.alias_map: dict[str, str] = {}`.
3. Refactor raw-vs-stripped:

```python
    def _raw_answer(self) -> str:
        return "\n\n".join(self._text_by_uuid[u] for u in self._text_order)

    def final_answer(self) -> str:
        """…(keep existing docstring, add:) Markers ([[cN]]) are the
        model's provenance claims, consumed by annotation(); they are
        stripped here so no consumer — UI, transcript, judge — ever sees
        one."""
        stripped, _ = parse_markers(self._raw_answer())
        return stripped

    def annotation(self) -> dict:
        try:
            stripped, tags = parse_markers(self._raw_answer())
            chunks, meta = self._retrieved_chunk_map()
            return annotate_answer(stripped, chunks, meta,
                                   tags=tags, alias_map=self.alias_map)
        except Exception as exc:  # noqa: BLE001 - deliberate, see docstring
            ...  # unchanged
```

4. Streaming (~line 883): keep `accumulator.record_text(result.uuid,
   result.text)` recording RAW; the yielded frame's `text` becomes
   `strip_for_stream(result.text)` with a WHY comment: the frame is
   consumer-visible; the raw text is the audit input the annotator parses.
5. `_run_turn`, before `yield accumulator.done_frame(...)` (~line 733):

```python
        if self._executor is not None:
            # The annotator resolves [[cN]] through the aliases this
            # conversation's retrieves actually assigned.
            accumulator.alias_map = self._executor.alias_map
```

- [ ] **Step 4: Run the harness suites**

Run: `uv run pytest tests/test_citation_session.py tests/test_citation_end_to_end.py tests/test_harness_prompt_caching.py -q`
Expected: PASS (the caching suite guards that none of this touched the
cacheable prefix)

- [ ] **Step 5: Commit**

```bash
git add harness/session.py tests/test_citation_session.py
git commit -m "feat(harness): strip markers from stream and finalAnswer; annotate with tags (spec A1, A2)"
```

---

### Task 8: the system-prompt tagging instruction

**Files:**
- Modify: `harness/system-prompt.md` (the figures section, ~line 448)
- Modify: `tests/test_citation_prompt.py`

- [ ] **Step 1: Write the failing tests** — in
  `tests/test_citation_prompt.py`, following its existing render-and-assert
  pattern:

```python
def test_prompt_teaches_the_marker_and_the_alias():
    text = rendered_prompt()          # the file's existing helper
    assert "[[c3]]" in text           # a concrete example, not just prose
    assert "alias" in text
    # The model must know tags are invisible and verified — otherwise it
    # narrates them, and output-hygiene bans that.
    assert "never mention" in text.lower() or "invisible" in text.lower()


def test_prompt_still_bans_citing_figures_via_cite():
    text = rendered_prompt()
    assert "Do not cite dollar figures" in text
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_citation_prompt.py -q`
Expected: new tests FAIL

- [ ] **Step 3: Edit the prompt.** In the figures section (directly after
  the "**Do not cite dollar figures or other numbers.**" paragraph, which
  stays), replace the "State figures plainly" paragraph with:

```markdown
**Tag every figure with the passage it came from.** Each passage in a
`retrieve` result carries an `alias` like `c3`. Immediately after every
dollar amount or count you take from a passage, append its alias in
double brackets:

> The General Fund total grew to $8,287.7 million [[c3]], while filled
> positions fell to 1,043 [[c7]].

- One figure from two passages: `[[c3,c7]]`.
- A figure YOU computed (a total, a difference, a percent change): no
  tag. The interface detects arithmetic and labels it as computed.
- Tags are invisible to the analyst — the interface verifies each one
  against the passage and renders a citation chip. Never mention the
  tags or the aliases in your prose, and never use `cite` for numbers.
- Tag the figure even when you repeat it later in the answer.

An untagged figure can only be cited when its value appears in exactly
one retrieved document, so an accurate tag is what gets your figure a
verified citation.
```

Keep every surrounding rule intact. Verify the marker example does not
enter the cacheable-prefix guard's banned patterns:
`uv run pytest tests/test_harness_prompt_caching.py -q` must stay green.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_citation_prompt.py tests/test_harness_prompt_caching.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add harness/system-prompt.md tests/test_citation_prompt.py
git commit -m "feat(prompt): figure tagging instruction — [[alias]] after every sourced figure (spec A1)"
```

---

### Task 9: webapp — parse and render the new verdict detail

**Files:**
- Modify: `webapp/src/chat/citation-annotation.ts`
- Modify: `webapp/src/chat/CitationChip.tsx` (`FigureTooltip`, line ~217)
- Test: `webapp/src/chat/citation-annotation.test.ts`,
  `webapp/src/chat/CitationChip.test.tsx` (append; follow the existing
  spec style in each file)

**Interfaces:**
- Produces: `AnnotationFigure` gains
  `linkBasis: "tag" | "unambiguous-fallback" | null`,
  `ambiguityCount: number | null`, `operation: string | null`,
  `nearMiss: { chunkId: string; sourceText: string; value: number;
  distance: number } | null`.

- [ ] **Step 1: Write the failing tests**

```typescript
// citation-annotation.test.ts — append
it("parses near_miss, ambiguity_count, link_basis and operation", () => {
  const figs = figuresForRender({
    figures: [{
      text: "$12.49B", start: 0, end: 7, index: 1, verdict: "unverified",
      primary: null, additional: [], derived_from: [],
      attested_chunk_ids: ["k1"], link_basis: null, ambiguity_count: null,
      operation: null,
      near_miss: { chunk_id: "k1", source_text: "12,515.4",
                   value: 12_515_400_000, distance: 0.002 },
    }],
  });
  expect(figs[0].nearMiss?.sourceText).toBe("12,515.4");
  expect(figs[0].nearMiss?.distance).toBeCloseTo(0.002);
});

it("defaults the new fields to null on old annotations", () => {
  const figs = figuresForRender({ figures: [{
    text: "$1,000,000", start: 0, end: 10, index: 1, verdict: "linked",
    primary: null, additional: [], derived_from: [],
  }]});
  expect(figs[0].nearMiss).toBeNull();
  expect(figs[0].ambiguityCount).toBeNull();
});
```

```tsx
// CitationChip.test.tsx — append, using the file's render helpers
it("an unverified figure with a near miss says what the source holds", () => {
  // render FigureChip with nearMiss {sourceText: "12,515.4", distance: 0.002}
  // hover → tooltip text matches /Nearest source value: 12,515\.4/
  //                       and /differs by 0\.2%/
});
it("an ambiguous figure says how many documents matched", () => {
  // ambiguityCount: 3 → tooltip matches /appears in 3 different documents/
});
it("a derived figure names its operation", () => {
  // operation: "difference", derivedFrom: [2,5]
  // tooltip matches /Computed \(difference\) from \[2\] and \[5\]/
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd webapp && npx vitest run src/chat/citation-annotation.test.ts src/chat/CitationChip.test.tsx`
Expected: FAIL

- [ ] **Step 3: Implement.** In `citation-annotation.ts`, extend the
  interface and `figuresForRender` parsing (same defensive style — a
  malformed `near_miss` yields `null`, never a throw):

```typescript
export interface AnnotationNearMiss {
  chunkId: string;
  sourceText: string;
  value: number;
  distance: number;
}
// on AnnotationFigure:
  linkBasis: "tag" | "unambiguous-fallback" | null;
  ambiguityCount: number | null;
  operation: string | null;
  nearMiss: AnnotationNearMiss | null;
```

In `FigureTooltip`:
- `derived` branch: `Computed ({figure.operation ?? "arithmetic"}) from
  {inputs}`.
- `unverified` branch becomes three-way. Copy, exactly (it must report,
  never accuse — spec A6):

```tsx
if (figure.verdict === "unverified") {
  const pct = figure.nearMiss
    ? `${(figure.nearMiss.distance * 100).toFixed(1)}%` : null;
  return (
    <div role="tooltip" className="chat-cite-tooltip">
      <div className="chat-cite-tooltip-head">
        <span className="chat-cite-tooltip-index">[{figure.index}]</span>
        <span className="chat-cite-tooltip-title">No source found</span>
      </div>
      <div className="chat-cite-fail">
        {figure.ambiguityCount != null && figure.ambiguityCount > 1 ? (
          <div>
            This value appears in {figure.ambiguityCount} different
            documents, so no single source is claimed.
          </div>
        ) : (
          <div>This figure was not found in the retrieved sources.</div>
        )}
        {figure.nearMiss && (
          <div>
            Nearest source value: {figure.nearMiss.sourceText} (differs
            by {pct}).
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run to verify pass, then the full webapp gate**

Run: `cd webapp && npx vitest run && npx tsc -b`
Expected: PASS, exit 0

- [ ] **Step 5: Commit**

```bash
git add webapp/src/chat/citation-annotation.ts webapp/src/chat/CitationChip.tsx webapp/src/chat/*.test.*
git commit -m "feat(webapp): near-miss, ambiguity and operation on figure chips (spec A6)"
```

---

### Task 10: eval — marker metrics and the false-link gate

**Files:**
- Modify: `eval/agent_scoring.py` (per-row block ~line 398, `aggregate`
  ~line 480)
- Create: `eval/false_link_check.py`
- Test: `tests/test_citation_metrics.py` (append),
  `tests/test_false_link_check.py` (new)

**Interfaces:**
- Produces per-row: `figures_attested` (int), `figures_tag_linked` (int);
  aggregate: `marker_coverage_mean` (attested/total over figure-bearing
  rows), `tag_accuracy_mean` (tag_linked/attested over rows with
  attested > 0). Script:
  `uv run python -m eval.false_link_check <run_dir> [--seed 7]` prints a
  per-profile false-link table and writes
  `<run_dir>/false-link-report.json`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_citation_metrics.py — append, using the file's transcript
# fixtures
def test_marker_metrics_count_attested_and_tag_linked():
    # annotation with 3 figures: one link_basis "tag" +
    # attested ["k1"], one "unambiguous-fallback" + attested [], one
    # unverified + attested ["k2"]
    row = score_transcript(query, transcript)
    assert row["figures_attested"] == 2
    assert row["figures_tag_linked"] == 1
```

```python
# tests/test_false_link_check.py
from eval.false_link_check import invent_figures, false_link_rate

def test_invented_figures_are_deterministic_and_in_profile():
    a = invent_figures("4sig-billions", n=20, seed=7)
    assert a == invent_figures("4sig-billions", n=20, seed=7)
    assert all(f.scale == 1_000_000_000 for f in a)

def test_false_link_rate_counts_any_link_as_false():
    pool = {"k1": "total 12,490,000,000 held"}
    meta = {"k1": {"doc_id": "d1"}}
    figs = invent_figures("4sig-billions", n=200, seed=7)
    rate = false_link_rate(figs, pool, meta)
    assert 0.0 < rate < 1.0  # the planted value catches some inventions
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_citation_metrics.py tests/test_false_link_check.py -q`
Expected: FAIL

- [ ] **Step 3: Implement.** `agent_scoring.py`, in the annotation block:

```python
    row["figures_attested"] = sum(
        1 for e in ann_figures if e.get("attested_chunk_ids"))
    row["figures_tag_linked"] = sum(
        1 for e in ann_figures if e.get("link_basis") == "tag")
```

In `aggregate` (same figureless-row exclusion the neighbouring means use):

```python
        "marker_coverage_mean": _mean(
            [r["figures_attested"] / r["figures_total"]
             for r in ok_rows if r["figures_total"]]),
        "tag_accuracy_mean": _mean(
            [r["figures_tag_linked"] / r["figures_attested"]
             for r in ok_rows if r["figures_attested"]]),
```

`eval/false_link_check.py` — the memo §5.2 method as a committed script:

```python
"""The A8 gate: link INVENTED figures against real retrieve pools; every
link is false by construction. Report the rate per digit profile.

Usage: uv run python -m eval.false_link_check eval/results/agent/<run>/
Reads the gitignored *-r1.jsonl transcripts; costs nothing.
"""
from __future__ import annotations

import json
import random
import sys
from dataclasses import dataclass
from pathlib import Path

from citation.annotate import annotate_answer
from citation.figures import Figure

PROFILES = {
    # (significant digits to invent, scale, rendering)
    "4sig-billions": (4, 1_000_000_000, "$~.2fB"),
    "4sig-millions": (4, 1_000_000, "$~.1fM"),
    "exact-grouped": (9, 1, "grouped"),
}


def invent_figures(profile: str, n: int, seed: int) -> list[Figure]:
    sig, scale, form = PROFILES[profile]
    rng = random.Random(f"{profile}:{seed}")
    out = []
    for _ in range(n):
        digits = rng.randint(10 ** (sig - 1), 10 ** sig - 1)
        if form == "grouped":
            text = f"{digits:,}"
            value, s = float(digits), 1
        else:
            value = digits / (100 if form.endswith("fB") else 10)
            suffix = "B" if scale == 1_000_000_000 else "M"
            text = f"${value}{suffix}"
            s = scale
        out.append(Figure(text, 0, len(text), value, s))
    return out


def false_link_rate(figs, chunks, meta) -> float:
    linked = 0
    for fig in figs:
        ann = annotate_answer(fig.text, chunks, meta, tags=[], alias_map={})
        if any(f["verdict"] == "linked" for f in ann["figures"]):
            linked += 1
    return linked / len(figs) if figs else 0.0


def _pools(run_dir: Path):
    """(chunks, meta) per transcript — chunk text and doc_id from each
    recorded retrieve output."""
    for path in sorted(run_dir.glob("*-r1.jsonl")):
        chunks, meta = {}, {}
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                frame = json.loads(line)
            except ValueError:
                continue
            for call in frame.get("toolCalls") or []:
                if call.get("toolName") != "retrieve":
                    continue
                try:
                    parsed = json.loads(call.get("output") or "")
                except (TypeError, ValueError):
                    continue
                for c in parsed.get("chunks") or []:
                    if c.get("chunk_id"):
                        chunks[c["chunk_id"]] = c.get("text") or ""
                        meta[c["chunk_id"]] = {"doc_id": c.get("doc_id")}
        if chunks:
            yield path.stem, chunks, meta


def main() -> int:
    run_dir = Path(sys.argv[1])
    seed = int(sys.argv[sys.argv.index("--seed") + 1]) if "--seed" in sys.argv else 7
    report = {}
    for profile in PROFILES:
        rates = []
        for _stem, chunks, meta in _pools(run_dir):
            figs = invent_figures(profile, n=40, seed=seed)
            rates.append(false_link_rate(figs, chunks, meta))
        report[profile] = sum(rates) / len(rates) if rates else None
        print(f"{profile:16s}  false-link rate "
              f"{report[profile]:.3%}" if rates else f"{profile}: no pools")
    out = run_dir / "false-link-report.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_citation_metrics.py tests/test_false_link_check.py -q`
Expected: PASS

- [ ] **Step 5: THE GATE — run the offline measurements** against the
  baseline transcripts (`eval/results/agent/2026-08-02T0900Z-0b08221/`):

```bash
uv run python -m eval.false_link_check eval/results/agent/2026-08-02T0900Z-0b08221/
```

Also re-run the verdict distribution over the same transcripts (the
memo §9 method — annotate each recorded answer against its own pool; no
tags exist in recorded transcripts, so this measures the FALLBACK path)
and record: false-link rate per profile vs the memo's 3.7% / 2.9% / 0.4%,
and coverage vs 92.9%. **Expected direction: false-link down hard
(ambiguous links are now refused); coverage on old transcripts DOWN too
(they carry no tags — the ambiguity share converts to `unverified`).**
That coverage drop is the honest untagged floor, not the shipped number;
the shipped number comes from the live run (Task 11). Write all figures
into the commit message.

- [ ] **Step 6: Commit**

```bash
git add eval/agent_scoring.py eval/false_link_check.py tests/
git commit -m "feat(eval): marker metrics + false-link gate script, with baseline numbers (spec A8, A9)"
```

---

### Task 11: end-to-end test, full gates, STATUS, live runbook

**Files:**
- Modify: `tests/test_citation_end_to_end.py`
- Modify: `STATUS.md`, `PROMPT-citation-linking-baseline.md` → superseded
- Create: `PROMPT-attested-citation-baseline.md`

- [ ] **Step 1: Extend the end-to-end test.** Following the existing
  real-`HarnessSession`-through-real-SSE-route pattern in
  `tests/test_citation_end_to_end.py`, add one scenario whose scripted
  model answer contains: a tagged figure (verifies → `linked`/`tag`), a
  tagged figure whose named chunk lacks the value but one other document
  has it (→ `linked`/`unambiguous-fallback`), an untagged value present in
  two documents (→ `unverified` + `ambiguity_count == 2`), a computed
  total (→ `derived` with `operation == "sum"`), and a figure near a
  source value (→ `near_miss` populated). Assert additionally: no `[[`
  anywhere in any SSE frame, and zero `cite`/`cite_batch` calls.

- [ ] **Step 2: Run the full suites**

```bash
uv run pytest -x -q
cd webapp && npx vitest run && npx tsc -b; cd ..
```

Expected: all green. Fix stragglers — likely suspects are suites that
snapshot retrieve-response JSON (now carries `alias`) and any transcript
fixture asserting the old annotation field set.

- [ ] **Step 3: Write the live runbook**
  `PROMPT-attested-citation-baseline.md` (modelled on
  `PROMPT-citation-linking-baseline.md`, which it supersedes — mark that
  file superseded at the top, keep it in place). Contents: needs an
  OpenRouter key + spends real money; steps = (1) one live browser
  reproduction of "what are the biggest agencies by budget" watching for
  leaked `[[` text, chip tooltips, near-miss copy; (2) Layer 2
  `--subset smoke` then `--subset full`; (3) `compare_agent_runs.py`
  against `eval/results/agent/2026-08-02T0900Z-0b08221`; (4) read
  `marker_coverage_mean` and `tag_accuracy_mean` — the design's one open
  risk. Decision table: marker coverage ≥ 0.8 and tag accuracy ≥ 0.9 →
  ship stands; below that → iterate the Task 8 prompt wording and re-run
  smoke; coverage of linked+derived must beat the Task 10 untagged floor
  and the token delta must be ≈ +150 output/answer, not thousands.

- [ ] **Step 4: Update `STATUS.md`** — new section "Attested citation
  linking — code complete, live baseline OUTSTANDING": what shipped
  (A1–A6, A8, A9), the Task 10 gate numbers, authority.py deleted, the
  spec A1 per-conversation-alias amendment, and the runbook pointer.
  Mark the old citation-linking OUTSTANDING section superseded by this
  one.

- [ ] **Step 5: Commit, merge, push**

```bash
git add -A && git commit -m "feat(citation): attested linking e2e + status + live-baseline runbook"
# then merge the worktree branch to master AND push (CLAUDE.md: merge means merge and push)
```

---

## Self-review record

- **Spec coverage:** A1 → Tasks 1, 6, 7, 8; A2 → Tasks 5, 7; A3 → Task 5;
  A4 → Tasks 2, 3; A5 → Task 4; A6 → Tasks 3, 5, 9; A8 → Task 10;
  A9 → Tasks 10, 11. A7 is explicitly the follow-up plan.
- **Known deviation from spec, recorded in Task 6:** per-conversation
  monotonic aliases instead of per-turn (strictly stronger against R1).
- **Live verification (A9) cannot complete inside this plan** — no key on
  this machine. Task 11's runbook is the same pattern every prior prompt
  change used.
