# Analyst Shorthand in the Title Filter — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `26ar dema` find the FY 2026 Department of Emergency and Military Affairs Appropriations Report in the Budget Documents filter box, using vocabulary this repo already curates rather than a new hand-maintained list.

**Architecture:** `/api/corpus/documents` attaches a small `terms` list to each document, computed server-side from `samples/entity-catalog.yaml` (agency slug + reviewed aliases), `retrieval/query_agency.py` (suppression), and `retrieval/query_year.py` (the JLBC shorthand map). The browser's `queryHit` becomes all-words: every whitespace-separated token must match the title by substring, the publisher by substring, or a term by exact equality. No per-keystroke network call is introduced.

**Tech Stack:** FastAPI + pytest on the server; React 19 + TypeScript with `vitest` + `@testing-library/react` in `webapp/`; the corpus eval at `eval/run_eval.py`.

**Spec:** `docs/superpowers/specs/2026-08-11-title-filter-shorthand-design.md`

## Global Constraints

- **Task 1 changes `retrieval/`, so the eval gate fires there and ONLY there.** `uv run python -m eval.run_eval` (~60s, needs `JLBC_DATA_DIR`), with `eval/results/<...>.{json,md}` committed alongside. This is the 60-second recall eval, **not** the Layer 2 agent eval that spends money. Tasks 2–4 touch no eval-gated directory.
- **Purely additive to existing matching.** Nothing this plan does may remove a match that works today. `insurance` must still find "Insurance, Department of" by title; `ahccc` must still find AHCCCS by partial title. `AMBIGUOUS_PHRASES` is deliberately never consulted.
- **Every non-trivial edit carries a WHY comment** recording the *evidence*, not just the choice. The repo owner is a non-developer. **A comment that contradicts the code is a defect** — `queryHit`'s existing comment says "NOT multi-term AND … splitting would redesign the filter", and Task 4 must rewrite it, not leave it.
- **Suppression applies only to the new terms**, never to title or publisher matching.
- **Everything compares lowercased on both sides.** Terms are stored lowercase; the query is lowercased before splitting. `26AR DEMA` and `26ar dema` behave identically — JLBC's own URLs spell it `/26AR/`.
- **Tests may not open a real LanceDB or load ONNX weights** (repo testing convention). `tests/test_corpus_documents_route.py` already has the autouse `budget_corpus` fixture that stubs `ChunkStore.scan`; reuse it.
- **No new dependencies.** `yaml` and the catalog loader are already in the closure.
- **Run before claiming any task done:** the task's own commands, listed per task.

---

## File Structure

| File | Responsibility |
|---|---|
| `retrieval/query_year.py` | **Modify.** Add `br`/`afr`/`exec` to the shorthand map and its regex; make the map public, since it now has a consumer outside retrieval. |
| `tests/test_query_year.py` | **Modify.** Pin the three new forms, and pin that `26bill` does not parse. |
| `app/search_terms.py` | **Create.** Pure: one document's metadata in, its search terms out. Owns the suppression maths and the carve-out. No FastAPI, no I/O beyond the cached catalog read. |
| `tests/test_search_terms.py` | **Create.** Unit tests for the above, no TestClient. |
| `app/routes/corpus.py` | **Modify.** `document_listing()` attaches `terms` to each row. |
| `tests/test_corpus_documents_route.py` | **Modify.** The listing carries terms; degradation posture unchanged. |
| `webapp/src/api.ts` | **Modify.** `CorpusDocument` gains `terms: string[]`. |
| `webapp/src/pages/Search.tsx` | **Modify.** `queryHit` becomes all-words and consults terms + publisher code. |
| `webapp/src/pages/Search.test.tsx` | **Modify.** Fixture helper gains `terms`; new matching tests. |

---

## Task 1: Teach the shorthand map `br`, `afr` and `exec`

The map currently holds exactly two forms. Three are added, `budget-bill` deliberately gets none, and the constant becomes public because Task 2 consumes it from outside `retrieval/`.

**Files:**
- Modify: `retrieval/query_year.py:105-109` (the regex and the map), `:159` (its one use)
- Modify: `tests/test_query_year.py` (the shorthand section, around `:143-190`)
- Create: `eval/results/<generated>.{json,md}` (whatever `run_eval` writes)

**Interfaces:**
- Produces: `retrieval.query_year.SHORTHAND_DOC_TYPE: dict[str, str]` — form → doc_type, e.g. `{"ar": "approps-per-agency", "baseline": "baseline-per-agency", "br": "baseline-per-agency", "afr": "afr", "exec": "governors-budget"}`. Task 2 inverts this.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_query_year.py`, in the `parse_jlbc_shorthand` section:

```python
def test_the_new_forms_parse_like_jlbcs_own_two():
    # br/afr/exec are OUR additions (Destin, 2026-08-11), not JLBC directory
    # names — analysts asked for them because the published convention only
    # covers two of the corpus's report types.
    assert parse_jlbc_shorthand("dema 26br") == [(2026, "baseline-per-agency")]
    assert parse_jlbc_shorthand("26afr") == [(2026, "afr")]
    assert parse_jlbc_shorthand("27exec") == [(2027, "governors-budget")]


def test_br_and_baseline_are_the_same_report_type():
    assert parse_jlbc_shorthand("26br") == parse_jlbc_shorthand("26baseline")


def test_the_budget_bill_has_no_shorthand():
    # Deliberate (Destin, 2026-08-11): JLBC never published one, and the
    # corpus holds a single budget bill per year — shorthand earns nothing.
    assert parse_jlbc_shorthand("26bill") == []


def test_the_new_forms_keep_the_designator_guard():
    # The guard that stops "chapter 21 baseline" must cover the new forms too,
    # since the regex's optional space applies to all of them equally.
    assert parse_jlbc_shorthand("chapter 26 afr") == []
    assert parse_jlbc_shorthand("laws 2025, chapter 26 br") == []


def test_a_longer_form_is_not_shadowed_by_a_shorter_one():
    # "afr" must not be read as "ar" plus a stray letter, in either
    # alternation order.
    assert parse_jlbc_shorthand("26afr") == [(2026, "afr")]
    assert parse_jlbc_shorthand("26arf") == []
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `.venv/bin/python -m pytest tests/test_query_year.py -q -k "new_forms or br_and_baseline or budget_bill or shadowed"`
Expected: FAIL — `parse_jlbc_shorthand("26br")` returns `[]` because the regex alternation is `(ar|baseline)`.

- [ ] **Step 3: Extend the regex and the map**

In `retrieval/query_year.py`, replace lines 102–109:

```python
# JLBC's own URL convention: azjlbc.gov/26AR/508.pdf, /21baseline/adc.pdf.
# The type suffix is REQUIRED — it is what makes the two digits a fiscal
# year rather than an ordinary number.
#
# `ar` and `baseline` are JLBC's, read off the website's directory names.
# `br`, `afr` and `exec` are OURS (Destin, 2026-08-11): the published
# convention covers only two of the corpus's report types, so an analyst who
# learned the pattern hit a wall on Annual Financial Reports and Executive
# Budgets. The budget bill deliberately gets none — there is one per year and
# shorthand earns nothing.
#
# Alternation is ordered LONGEST FIRST. The trailing `(?![\w])` already
# prevents "26afr" from being read as "26ar" + stray "f", but relying on a
# lookahead to undo a wrong alternative is a subtlety the next reader
# shouldn't have to re-derive.
_JLBC_SHORTHAND = re.compile(
    r"(?<![\w$])(\d{2})\s?(baseline|exec|afr|br|ar)(?![\w])", re.IGNORECASE
)

# PUBLIC (2026-08-11): `app/search_terms.py` inverts this to label documents
# with their own shorthand, so the filter box and the query parser cannot
# disagree about what "26afr" means. It was private while retrieval was its
# only consumer.
SHORTHAND_DOC_TYPE = {
    "ar": "approps-per-agency",
    "baseline": "baseline-per-agency",
    "br": "baseline-per-agency",
    "afr": "afr",
    "exec": "governors-budget",
}
```

Then update its one use at what was line 159:

```python
        out.append((year, SHORTHAND_DOC_TYPE[match.group(2).lower()], match.group(0)))
```

- [ ] **Step 4: Run the new tests, then the whole parser suite**

Run: `.venv/bin/python -m pytest tests/test_query_year.py tests/test_query_doc_type.py tests/test_query_understanding_eval_safety.py -q`
Expected: PASS. `test_query_doc_type.py` matters because `query_doc_type.py:160` is the map's other consumer; `test_query_understanding_eval_safety.py` checks the parsers against the eval set's own ground truth in under a second and is the cheap guard before spending an eval run.

- [ ] **Step 5: Run the full backend suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: `2167 passed, 5 skipped` or better. Any new failure here is this change reaching further than intended — stop and report rather than adjusting the failing test.

- [ ] **Step 6: Run the eval and read the result**

Run: `JLBC_DATA_DIR=<the migrated data dir> uv run python -m eval.run_eval`
Expected: ~60s. Compare recall@5 / recall@20 against the previous committed run in `eval/results/`. A widened regex can only add parses, so recall should hold or improve; **a drop means a new form is firing on ordinary budget prose** — report the number rather than proceeding.

- [ ] **Step 7: Commit, with the eval results in the same commit**

```bash
git add retrieval/query_year.py tests/test_query_year.py eval/results
git commit -m "feat(query): br, afr and exec join JLBC's ar and baseline shorthand

The published convention (azjlbc.gov/26AR/) covers two of the corpus's
report types, so an analyst who learned the pattern hit a wall on AFRs and
Executive Budgets. br/afr/exec are our additions; the budget bill gets none.

SHORTHAND_DOC_TYPE is now public: app/search_terms.py inverts it to label
documents with their own shorthand, so the Budget Documents filter box and
the query parser cannot disagree about what '26afr' means."
```

---

## Task 2: The search-terms module

One document's metadata in, its search terms out. All of the spec's judgement — which agency, which aliases survive suppression, which shorthand — lives here, unit-testable without a TestClient.

**Files:**
- Create: `app/search_terms.py`
- Create: `tests/test_search_terms.py`

**Interfaces:**
- Consumes: `retrieval.query_year.SHORTHAND_DOC_TYPE` (Task 1); `chunking.agency_catalog.load_agency_catalog() -> dict[str, AgencyEntry]` where `AgencyEntry` has `.canonical_id`, `.canonical_name`, `.slug: str | None`, `.aliases: list[str]`; `retrieval.query_agency.{SUPPRESSED_ALIASES, AMBIGUOUS_ALIASES, AMBIGUOUS_AGENCIES}`.
- Produces: `app.search_terms.search_terms(doc_id: str, doc_type: str | None, fiscal_year: int | None) -> list[str]` — sorted, lowercase, deduplicated. Task 3 calls exactly this.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_search_terms.py`:

```python
"""Per-document search terms for the Budget Documents filter box.

Typing "dema" or "ema" returns 0 documents without these; both are already
reviewed vocabulary (a curated alias in samples/entity-catalog.yaml, and the
agency's own JLBC URL slug). See
docs/superpowers/specs/2026-08-11-title-filter-shorthand-design.md.
"""
from __future__ import annotations

from app.search_terms import search_terms


def test_a_per_agency_document_carries_its_slug_and_reviewed_aliases():
    terms = search_terms("jlbc-approps-fy2026-ema", "approps-per-agency", 2026)
    assert "ema" in terms      # the JLBC URL slug
    assert "dema" in terms     # the reviewed alias — what an analyst says


def test_a_document_carries_its_type_shorthand_bare_and_year_prefixed():
    terms = search_terms("jlbc-baseline-fy2026-adc", "baseline-per-agency", 2026)
    # Bare forms filter too (Destin, 2026-08-11): "pick 2026 in the rail,
    # type br".
    assert {"br", "baseline", "26br", "26baseline"} <= set(terms)


def test_the_budget_bill_gets_no_type_shorthand():
    assert search_terms("jlbc-budget-bill-fy2026", "budget-bill", 2026) == []


def test_a_raw_slug_doc_type_gets_no_type_shorthand():
    # s-pdf/bd-pdf/topic-pdf have no curated family and no shorthand.
    assert search_terms("jlbc-s-fy2027-01", "s-pdf", 2027) == []


def test_suppressed_and_ambiguous_aliases_never_become_terms():
    # "for" is Forestry's slug and SUPPRESSED; "bar" is the Board of Barbers'
    # and AMBIGUOUS. Both are ordinary English before they are agencies, and
    # both were measured against 247,607 tokens of real budget prose.
    assert "for" not in search_terms("jlbc-baseline-fy2026-for", "baseline-per-agency", 2026)
    assert "bar" not in search_terms("jlbc-baseline-fy2026-bar", "baseline-per-agency", 2026)


def test_the_carve_out_survives_suppression():
    # D7: the lists were measured against document PROSE. In a box labelled
    # "Agency or keyword", "dot" is as unambiguous as "dema".
    #
    # The two arrive by different routes, verified against the catalog
    # 2026-08-11: "dot" IS Transportation's slug, while "doc" is a reviewed
    # ALIAS on Corrections, whose slug is "adc". Hence the two doc_ids.
    assert "dot" in search_terms("jlbc-baseline-fy2026-dot", "baseline-per-agency", 2026)
    assert "doc" in search_terms("jlbc-baseline-fy2026-adc", "baseline-per-agency", 2026)


def test_an_alias_survives_its_agencys_slug_being_suppressed():
    # Forestry's slug "for" is SUPPRESSED, but its reviewed alias "dffm" is on
    # no list. The agency stays findable by the acronym an analyst actually
    # types — suppression removes a STRING, not an agency.
    terms = search_terms("jlbc-baseline-fy2026-for", "baseline-per-agency", 2026)
    assert "for" not in terms
    assert "dffm" in terms


def test_an_ambiguous_agency_contributes_nothing():
    # agency:gov is demoted across every tier in retrieval — in a budget
    # question "the Governor" names a document or an actor far more often
    # than the Office of the Governor's own budget.
    assert "gov" not in search_terms("jlbc-baseline-fy2026-gov", "baseline-per-agency", 2026)


def test_an_unknown_trailing_segment_yields_no_agency_terms():
    # The FY2005-2012 sub-unit pages (adeassis, axsacute) have no catalog
    # entry. They must still list, and still match by title — their titles
    # ARE the slug uppercased.
    terms = search_terms("jlbc-approps-fy2005-adeassis", "approps-per-agency", 2005)
    assert "adeassis" not in terms
    assert "05ar" in terms  # the type shorthand still applies


def test_the_year_prefixed_form_stops_below_the_conventions_floor():
    # The shorthand is a 20xx-only convention (see _SHORTHAND_MIN_YEAR).
    terms = search_terms("jlbc-baseline-fy1998-adc", "baseline-per-agency", 1998)
    assert "98br" not in terms
    assert "br" in terms  # the bare form is ours and has no such floor


def test_a_missing_fiscal_year_still_yields_the_bare_form():
    terms = search_terms("jlbc-baseline-adc", "baseline-per-agency", None)
    assert "br" in terms
    assert not any(t[0].isdigit() for t in terms)


def test_terms_are_lowercase_sorted_and_unique():
    terms = search_terms("jlbc-approps-fy2026-ema", "approps-per-agency", 2026)
    assert terms == sorted(set(terms))
    assert all(t == t.lower() for t in terms)


def test_an_unreadable_catalog_degrades_to_no_agency_terms(monkeypatch):
    # Same failure posture as budget_doc_ids: never take the page down.
    def boom(*_a, **_kw):
        raise OSError("catalog unreadable")

    monkeypatch.setattr("app.search_terms._catalog_by_slug", boom)
    terms = search_terms("jlbc-approps-fy2026-ema", "approps-per-agency", 2026)
    assert "ema" not in terms
    assert "26ar" in terms  # the type shorthand needs no catalog
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `.venv/bin/python -m pytest tests/test_search_terms.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.search_terms'`.

- [ ] **Step 3: Write the module**

Create `app/search_terms.py`:

```python
"""Per-document search terms for the Budget Documents filter box.

WHY this exists: typing "dema" into that box returns ZERO documents today, and
so does "ema" — measured against the live 5,330-document corpus. Both are how
an analyst refers to the Department of Emergency and Military Affairs, and both
are already reviewed vocabulary in this repo: "dema" is a curated alias in
`samples/entity-catalog.yaml` and "ema" is the agency's JLBC URL slug. The
knowledge existed; it just never reached the browser, because title filtering
runs client-side over a listing payload that carried no agency and no shorthand.

So the listing carries the terms, computed HERE — server-side, once per page
load, next to the data that defines them. The browser's matcher stays dumb:
tokens in, boolean out. The alternative (ship the catalog to the browser and
parse there) means a second implementation of JLBC's convention in TypeScript,
and two implementations of one convention drift — this branch already shipped
that exact bug class once, in the doc-type slug map.

Design: docs/superpowers/specs/2026-08-11-title-filter-shorthand-design.md
"""
from __future__ import annotations

from functools import lru_cache

# The lists below were tuned for QUESTIONS, where a stray "for" hard-filtered 13
# of 47 eval queries onto Forestry. A filter box has no ranking — a term matches
# or it does not — so retrieval's "demote to a boost" has no analogue here and
# both lists simply EXCLUDE.
#
# `AMBIGUOUS_PHRASES` is deliberately NOT imported. It governs name matching in
# retrieval, and honouring it here would REMOVE matching that works today:
# "insurance" already finds "Insurance, Department of" through the title. This
# module may only ever ADD.
from retrieval.query_agency import (
    AMBIGUOUS_AGENCIES,
    AMBIGUOUS_ALIASES,
    SUPPRESSED_ALIASES,
)
from retrieval.query_year import SHORTHAND_DOC_TYPE

# Deliberate, reviewed divergence from retrieval (Destin, 2026-08-11).
#
# Both suppression lists were measured against document PROSE, where "dot" and
# "doc" are ordinary English words. They were never measured against what
# someone types into a box labelled "Agency or keyword" — and there, "dot" is
# about as unambiguous as "dema".
#
# Kept as an explicit named set rather than a policy so the divergence is
# visible in one place. Every OTHER entry on both lists stays excluded.
FILTER_BOX_CARVE_OUT: frozenset[str] = frozenset({"dot", "doc"})

# The 20xx-only floor the JLBC convention itself observes — mirrors
# `retrieval.query_year._SHORTHAND_MIN_YEAR`. Below it, "98br" is a reference to
# nothing: JLBC spelled pre-2000 editions out in full (FY1984AppropRpt.pdf).
# The BARE form ("br") is ours and carries no such floor.
_SHORTHAND_MIN_YEAR = 2000


def _blocked() -> frozenset[str]:
    """Alias strings that may not become search terms."""
    return frozenset(SUPPRESSED_ALIASES | AMBIGUOUS_ALIASES) - FILTER_BOX_CARVE_OUT


@lru_cache(maxsize=1)
def _doc_type_forms() -> dict[str, tuple[str, ...]]:
    """`{doc_type: (form, ...)}` — the inverse of `SHORTHAND_DOC_TYPE`.

    DERIVED, never written out by hand: two lists of the same forms is how one
    silently stops matching a type somebody added to only the other. A doc_type
    can have several forms ("baseline-per-agency" has both "baseline" and "br").
    """
    out: dict[str, list[str]] = {}
    for form, doc_type in SHORTHAND_DOC_TYPE.items():
        out.setdefault(doc_type, []).append(form)
    return {doc_type: tuple(sorted(forms)) for doc_type, forms in out.items()}


@lru_cache(maxsize=1)
def _catalog_by_slug() -> dict[str, tuple[str, tuple[str, ...]]]:
    """`{slug: (canonical_id, aliases)}` for every agency that has a slug.

    ~a dozen catalog entries are Gov-outline-only and carry `slug: None`; they
    are skipped rather than keyed under None.
    """
    from chunking.agency_catalog import load_agency_catalog

    out: dict[str, tuple[str, tuple[str, ...]]] = {}
    for entry in load_agency_catalog().values():
        if not entry.slug:
            continue
        aliases = tuple(a.lower() for a in (entry.aliases or []))
        out[entry.slug.lower()] = (entry.canonical_id, aliases)
    return out


def _agency_terms(doc_id: str) -> set[str]:
    """The agency vocabulary for `doc_id`, or an empty set.

    The agency comes from the TRAILING SEGMENT of the doc_id
    (`jlbc-approps-fy2005-ema` -> `ema`) matched against the 157 known catalog
    slugs. Measured on the live corpus: 4,321 of 4,674 per-agency documents
    (92%) resolve this way. Also matching titles against canonical names
    rescues only 60 more (93% combined), which does not earn a second code
    path.

    The 293 that resolve by neither are FY2005-2012 sub-unit pages JLBC
    published that never got a catalog entry (adeassis, adeboe, axsacute).
    They lose nothing: their titles are the slug uppercased, so typing the slug
    already finds them by TITLE.

    Failure posture: an unreadable catalog yields no agency terms rather than a
    500 — same rule as `app.routes.corpus.budget_doc_ids`. Type shorthand needs
    no catalog and still applies.
    """
    slug = doc_id.rsplit("-", 1)[-1].lower()
    try:
        entry = _catalog_by_slug().get(slug)
    except Exception:  # noqa: BLE001 — absent or corrupt catalog
        return set()
    if entry is None:
        return set()
    canonical_id, aliases = entry
    # An agency demoted across EVERY tier contributes nothing at all, however
    # it was named — agency:gov is the case that forced this list.
    if canonical_id in AMBIGUOUS_AGENCIES:
        return set()
    return ({slug} | set(aliases)) - _blocked()


def _type_terms(doc_type: str | None, fiscal_year: int | None) -> set[str]:
    """The shorthand vocabulary for a document's report type.

    Both the bare form and the year-prefixed one: a FY2026 baseline carries
    "br", "baseline", "26br" and "26baseline". Bare forms filter too (Destin,
    2026-08-11) so "pick 2026 in the rail, type br" works.
    """
    forms = _doc_type_forms().get(doc_type or "", ())
    terms = set(forms)
    if fiscal_year and fiscal_year >= _SHORTHAND_MIN_YEAR:
        terms |= {f"{fiscal_year % 100:02d}{form}" for form in forms}
    return terms


def search_terms(
    doc_id: str, doc_type: str | None, fiscal_year: int | None
) -> list[str]:
    """Extra strings the filter box matches this document on, sorted and unique.

    These are matched by EXACT token equality in the browser, never as
    substrings — "ar" as a substring would match "arizona" in nearly every
    title in the corpus.
    """
    return sorted(_agency_terms(doc_id) | _type_terms(doc_type, fiscal_year))
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_search_terms.py -q`
Expected: PASS, 12 tests.

Verified against the catalog while writing this plan (2026-08-11), so these are facts, not guesses: `dot` is Transportation's **slug**; `doc` is a reviewed **alias** on Corrections, whose slug is `adc`; `for` is Forestry's slug and `dffm` its alias; `gov` is the Office of the Governor's slug and `agency:gov` is on `AMBIGUOUS_AGENCIES`; `ema` is Emergency and Military Affairs' slug with alias `dema`. The catalog holds exactly **10** reviewed aliases across 157 agencies.

- [ ] **Step 5: Commit**

```bash
git add app/search_terms.py tests/test_search_terms.py
git commit -m "feat(corpus): per-document search terms for the filter box

Typing 'dema' or 'ema' returns 0 documents today, measured against the
live 5,330-document corpus, though both are already reviewed vocabulary.
This computes each document's agency slug, its reviewed aliases and its
JLBC shorthand server-side, so the browser's matcher stays dumb and no
second copy of the convention exists in TypeScript.

Suppression is reused from retrieval rather than re-tuned, with one named
carve-out: those lists were measured against document prose, where 'dot'
and 'doc' are ordinary words, not against a box labelled 'Agency or
keyword'."
```

---

## Task 3: Attach the terms to the listing

**Files:**
- Modify: `app/routes/corpus.py` — `document_listing()` (currently `:107-153`)
- Modify: `tests/test_corpus_documents_route.py`

**Interfaces:**
- Consumes: `app.search_terms.search_terms(doc_id, doc_type, fiscal_year) -> list[str]` (Task 2).
- Produces: each row of `GET /api/corpus/documents` gains `"terms": list[str]`. Task 4 reads it.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_corpus_documents_route.py`:

```python
def test_the_listing_carries_each_documents_search_terms(client, tmp_path):
    _write(tmp_path, {"jlbc-approps-fy2026-ema": _entry(doc_type="approps-per-agency",
                                                        fiscal_year=2026)})
    row = client.get("/api/corpus/documents").json()["documents"][0]
    # The filter box matches these by exact token equality; see
    # app/search_terms.py for where each comes from.
    assert "ema" in row["terms"]    # JLBC URL slug
    assert "dema" in row["terms"]   # reviewed alias
    assert "26ar" in row["terms"]   # JLBC shorthand


def test_every_row_has_a_terms_list_even_when_empty(client, tmp_path):
    # The client types `terms` as required, so the key must always be present —
    # a raw-slug doc type with an unknown agency has nothing to contribute.
    _write(tmp_path, {"jlbc-s-fy2027-01": _entry(doc_type="s-pdf", fiscal_year=2027)})
    row = client.get("/api/corpus/documents").json()["documents"][0]
    assert row["terms"] == []
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `.venv/bin/python -m pytest tests/test_corpus_documents_route.py -q -k "search_terms or terms_list"`
Expected: FAIL — `KeyError: 'terms'`.

- [ ] **Step 3: Attach the terms**

In `app/routes/corpus.py`, add the import inside `document_listing()` alongside the existing one, and one row key:

```python
    from store.documents import load_documents, title_for

    from app.search_terms import search_terms

    docs = load_documents()
    in_budget = budget_doc_ids()
    rows = [
        {
            "doc_id": doc_id,
            "title": title_for(doc_id),
            "publisher": meta.get("publisher"),
            "doc_type": meta.get("doc_type"),
            "fiscal_year": meta.get("fiscal_year"),
            "doc_url": meta.get("source_url"),
            # Extra strings the filter box matches by EXACT token equality —
            # the agency's JLBC slug and reviewed aliases, plus this report
            # type's shorthand ("26ar"). Computed here rather than in the
            # browser so JLBC's convention has exactly one implementation; see
            # app/search_terms.py for the measurement that motivated it
            # ("dema" matched 0 of 5,330 documents before this).
            "terms": search_terms(
                doc_id, meta.get("doc_type"), meta.get("fiscal_year")
            ),
        }
```

Also extend `document_listing`'s docstring — it currently enumerates the row's fields as "id, display title, publisher, doc_type, fiscal_year and the source URL", which this makes incomplete:

```python
    One flat row per document: id, display title, publisher, doc_type,
    fiscal_year, the source URL the row links to, and the search `terms` the
    filter box matches on. The page filters, groups and searches this
    client-side, so there is exactly one request on mount and none per
    keystroke.
```

- [ ] **Step 4: Run the route suite**

Run: `.venv/bin/python -m pytest tests/test_corpus_documents_route.py -q`
Expected: PASS — the 10 pre-existing tests plus the 2 new ones. The degradation tests (corrupt sidecar, unreadable chunk table) must still pass untouched; if one needed editing, the failure posture changed and that is a defect, not a test to fix.

- [ ] **Step 5: Commit**

```bash
git add app/routes/corpus.py tests/test_corpus_documents_route.py
git commit -m "feat(corpus): the document listing carries per-document search terms"
```

---

## Task 4: All-words matching in the browser

The behaviour change. `queryHit` today is one case-insensitive substring test over the whole query, which `26ar dema` can never satisfy at any vocabulary — it is not a substring of anything.

**Files:**
- Modify: `webapp/src/api.ts:144-154` (`CorpusDocument`)
- Modify: `webapp/src/pages/Search.tsx:163-175` (`queryHit` and its comment)
- Modify: `webapp/src/pages/Search.test.tsx` (fixture helper + new tests)

**Interfaces:**
- Consumes: `CorpusDocument.terms: string[]` from Task 3.

- [ ] **Step 1: Write the failing tests**

Add to `webapp/src/pages/Search.test.tsx`.

**There is no `doc()` factory in this file** (verified 2026-08-11). Fixtures are object literals in a `const DOCS: api.CorpusDocument[]` array, and the helper is `mount(docs = DOCS, entry = "/search")`. So: add `terms: []` to each of the **9** existing `DOCS` literals — that keeps every current test's behaviour identical, because the client never computes terms, it only reads what it is handed — and build the new tests' fixtures as literals too.

```tsx
// Two real-shaped rows for the shorthand tests. Terms are supplied
// explicitly: the client never computes them, it only matches what the
// route handed it (app/search_terms.py).
const SHORTHAND_DOCS: api.CorpusDocument[] = [
  {
    doc_id: "jlbc-approps-fy2026-ema",
    title: "Emergency and Military Affairs, Department of — FY 2026 Appropriations Report",
    publisher: "jlbc",
    doc_type: "approps-per-agency",
    fiscal_year: 2026,
    doc_url: "https://x/ar-ema.pdf",
    terms: ["26ar", "ar", "dema", "ema"],
  },
  {
    doc_id: "jlbc-approps-fy2026-adc",
    title: "Corrections, State Department of — FY 2026 Appropriations Report",
    publisher: "jlbc",
    doc_type: "approps-per-agency",
    fiscal_year: 2026,
    doc_url: "https://x/ar-adc.pdf",
    terms: ["26ar", "adc", "ar", "doc"],
  },
];

test("shorthand finds a document whose title contains none of it", async () => {
  // "dema" matched 0 of 5,330 titles before this — it is the agency's spoken
  // acronym, not any word in "Emergency and Military Affairs, Department of".
  mount(SHORTHAND_DOCS);
  await screen.findByRole("button", { name: /Fiscal Year 2026:/i });
  fireEvent.change(screen.getByLabelText(/filter documents by agency or keyword/i), {
    target: { value: "26ar dema" },
  });
  expect(screen.getByText(/Emergency and Military Affairs/i)).toBeInTheDocument();
  expect(screen.queryByText(/Corrections, Department of/i)).toBeNull();
});

test("every word must match — one unmatchable word returns nothing", async () => {
  mount();
  await screen.findByRole("button", { name: /Fiscal Year 2027:/i });
  fireEvent.change(screen.getByLabelText(/filter documents by agency or keyword/i), {
    target: { value: "ahcccs zzz-no-such-thing" },
  });
  expect(screen.queryByText(/AHCCCS/i)).toBeNull();
});

test("terms match whole tokens only, never as substrings", async () => {
  // "ar" must not match a document merely because its terms contain "26ar" —
  // exact equality is what stops short slugs matching half the corpus.
  // NOTE the title deliberately contains no "ar": title matching stays
  // substring, so a title with "Arizona" in it would match "ar" honestly and
  // prove nothing about terms.
  mount([
    {
      doc_id: "jlbc-s-fy2027-01",
      title: "Something Else Entirely",
      publisher: "jlbc",
      doc_type: "s-pdf",
      fiscal_year: 2027,
      doc_url: null,
      terms: ["26ar"],
    },
  ]);
  await screen.findByRole("button", { name: /Fiscal Year 2027:/i });
  fireEvent.change(screen.getByLabelText(/filter documents by agency or keyword/i), {
    target: { value: "ar" },
  });
  expect(screen.queryByText(/Something Else Entirely/i)).toBeNull();
});

test("partial title typing still works", async () => {
  // Title matching stays SUBSTRING. This change may only ever add.
  mount();
  await screen.findByRole("button", { name: /Fiscal Year 2027:/i });
  fireEvent.change(screen.getByLabelText(/filter documents by agency or keyword/i), {
    target: { value: "ahccc" },
  });
  expect(screen.getByText(/AHCCCS/i)).toBeInTheDocument();
});

test("a stored publisher code matches, not just its display label", async () => {
  // publisherLabel maps "governor" -> "OSPB", and only the label was searched,
  // so typing the code a reader sees in the corpus matched nothing.
  mount([
    {
      doc_id: "ospb-exec-fy2027",
      title: "Executive Budget — FY 2027",
      publisher: "governor",
      doc_type: "governors-budget",
      fiscal_year: 2027,
      doc_url: "https://x/eb27.pdf",
      terms: ["27exec", "exec"],
    },
  ]);
  await screen.findByRole("button", { name: /Fiscal Year 2027:/i });
  fireEvent.change(screen.getByLabelText(/filter documents by agency or keyword/i), {
    target: { value: "governor" },
  });
  expect(screen.getByText(/Executive Budget/i)).toBeInTheDocument();
});

test("matching is case-insensitive on both sides", async () => {
  // JLBC's own URLs spell it /26AR/.
  mount(SHORTHAND_DOCS);
  await screen.findByRole("button", { name: /Fiscal Year 2026:/i });
  fireEvent.change(screen.getByLabelText(/filter documents by agency or keyword/i), {
    target: { value: "26AR DEMA" },
  });
  expect(screen.getByText(/Emergency and Military Affairs/i)).toBeInTheDocument();
});
```

The last test reuses `SHORTHAND_DOCS`, so it asserts only the EMA row and must not assert the absence of Corrections — a single-fixture test would be a weaker version of the first one.

- [ ] **Step 2: Run them and confirm they fail**

Run: `cd webapp && npx vitest run src/pages/Search.test.tsx -t "shorthand finds"`
Expected: FAIL — `26ar dema` matches nothing, because the whole string is tested as one substring.

- [ ] **Step 3: Add `terms` to the client type**

In `webapp/src/api.ts`, inside `CorpusDocument`:

```ts
  /** Extra strings the filter box matches by EXACT token equality — the
   *  agency's JLBC URL slug and reviewed aliases, plus this report type's
   *  shorthand ("26ar"). Computed server-side in app/search_terms.py so
   *  JLBC's convention has one implementation, not two. Always present;
   *  empty for a document with neither a known agency nor a shorthand type. */
  terms: string[];
```

- [ ] **Step 4: Rewrite `queryHit`**

In `webapp/src/pages/Search.tsx`, replace the function and its comment at `:163-175`:

```tsx
/** Does this document match the typed query?
 *
 *  EVERY whitespace-separated word must match something. This replaced a
 *  single whole-query substring test (2026-08-11), which was not a
 *  preference: "26ar dema" cannot match under it at any vocabulary, because
 *  it is not a substring of anything. The old comment here said splitting
 *  "would redesign the filter" — it does, and that is the change.
 *
 *  Title and publisher stay SUBSTRING so partial typing keeps working
 *  ("ahccc" finds AHCCCS). `terms` are matched by EXACT equality instead:
 *  they are 2-6 character slugs, and "ar" as a substring would match
 *  "arizona" in nearly every title in the corpus.
 *
 *  Publisher matches on the stored CODE as well as the display label,
 *  because publisherLabel maps "governor" to "OSPB" and typing the code
 *  matched nothing at all.
 *
 *  `terms.includes` is a linear scan of at most ~6 short strings; a Set per
 *  document would cost more to build than it saves. */
function queryHit(d: api.CorpusDocument, q: string): boolean {
  const tokens = q.toLowerCase().split(/\s+/).filter(Boolean);
  if (!tokens.length) return false;
  const title = d.title.toLowerCase();
  const label = publisherLabel(d.publisher).toLowerCase();
  const code = d.publisher.toLowerCase();
  return tokens.every(
    (t) => title.includes(t) || label.includes(t) || code.includes(t) || d.terms.includes(t),
  );
}
```

- [ ] **Step 5: Run the webapp suite**

Run: `cd webapp && npx tsc -b --noEmit && npx vitest run`
Expected: PASS. The suite was at **622** before this task; the 6 new tests bring it to 628.

`tsc` will flag every fixture missing `terms` — that is the type doing its job. Add `terms: []` to the fixture helper's base rather than to each fixture, and do not make the field optional to avoid the work: the route always sends it, and an optional field would misdescribe the contract.

If a pre-existing matching test fails, read it before touching it. A test asserting that a two-word query matches a phrase is asserting the behaviour this task deliberately replaces — update it and name it in your report. A test asserting partial-title matching is a real regression — stop.

- [ ] **Step 6: Verify against the real corpus**

With the dev server running on the branch:

```bash
cd webapp && npm run build
JLBC_DATA_DIR=<the migrated data dir> .venv/bin/uvicorn app.main:create_app --factory --port 9301 &
curl -s http://127.0.0.1:9301/api/corpus/documents | python3 -c "
import sys,json
d=json.load(sys.stdin)['documents']
ema=[x for x in d if x['doc_id'].endswith('-ema') and x['fiscal_year']==2026]
print('FY2026 EMA rows:', len(ema))
for x in ema: print(' ', x['doc_id'], x['terms'])
print('rows with no terms:', sum(1 for x in d if not x['terms']))
"
```
Expected: the EMA rows carry `dema`, `ema` and their type shorthand; the no-terms count is a few hundred (the raw-slug types and unmatched sub-unit pages), not thousands. A count in the thousands means `_agency_terms` is failing to resolve slugs — report the number.

- [ ] **Step 7: Commit**

```bash
git add webapp/src/api.ts webapp/src/pages/Search.tsx webapp/src/pages/Search.test.tsx
git commit -m "feat(docs-page): analyst shorthand and all-words matching in the filter box

'dema' matched 0 of 5,330 documents; it is the agency's spoken acronym and
a reviewed alias, and now it matches. Every whitespace-separated word must
now match the title by substring, the publisher by substring, or one of the
document's terms exactly — forced by the feature, since '26ar dema' is not
a substring of anything.

Publisher now matches the stored code as well as the display label:
publisherLabel maps 'governor' to 'OSPB', so typing 'governor' found
nothing."
```

---

## Self-Review

**Spec coverage.** D1 (silent, rail unmoved) — no rail code is touched, satisfied by omission. D2 all-words — Task 4 Step 4. D3 exact terms / substring title, lowercased — Task 4 Steps 4 and 1. D4 server-side terms — Tasks 2–3. D5 doc_id trailing segment — Task 2 `_agency_terms`. D6 suppression, additive only — Task 2, plus the Global Constraint. D7 carve-out — Task 2 `FILTER_BOX_CARVE_OUT`. D8 publisher codes — Task 4. D9 vocabulary — Task 1. D10 eval — Task 1 Steps 6–7. D11 bare type — Task 2 `_type_terms`.

**Placeholder scan.** The only bracketed text is `<the migrated data dir>` in the eval and verification commands, which is a real per-machine path the runner must supply and cannot be hardcoded.

**Type consistency.** `search_terms(doc_id, doc_type, fiscal_year) -> list[str]` is defined in Task 2 and called with those three arguments in Task 3. `SHORTHAND_DOC_TYPE` is made public in Task 1 and imported in Task 2. `CorpusDocument.terms: string[]` is produced in Task 3 and read in Task 4.

**Ordering.** Task 2 imports `SHORTHAND_DOC_TYPE` from Task 1, so Task 1 must land first. Tasks 3 and 4 are strictly sequential after it. There is no parallel opportunity in this plan — every task consumes the previous one's interface.

**Two assumptions found and resolved during review**, rather than left for the implementer to hit:

1. The carve-out test originally used `jlbc-baseline-fy2026-doc`, assuming `doc` was Corrections' slug. It is **not a slug at all** — it is a reviewed *alias* on `adc`. The test now uses `-adc`, and a companion test pins the same distinction for Forestry (slug `for` suppressed, alias `dffm` surviving), which is the clearest statement of what suppression does: it removes a string, not an agency.
2. Task 4's tests were originally written against a `doc({...})` fixture factory. **No such helper exists** — `Search.test.tsx` uses object literals in a `DOCS` array with `mount(docs = DOCS)`. The tests are now literals, and the step names the exact count of existing fixtures needing `terms: []`.

**One residual risk, stated not solved.** Task 1's regex widening is the only change here that can affect an existing shipped behaviour, and its blast radius is every query the retrieval pipeline parses — not just this page. Step 6's eval is the instrument, and Step 4's `test_query_understanding_eval_safety.py` is the cheap pre-check. If the eval's recall drops, the answer is to narrow the new alternation (most likely `exec`, the longest and most word-like of the three), not to accept the number.
