"""The committed merge table for split agency ids (spec I9).

Six agencies live under more than one `agency_canonical_id`, so their
documents are split across ids and any per-agency count or `list_filter_
values` listing is wrong. Child Safety is the worst case: it carries FOUR
ids, so `MERGE_MAP` below has nine entries for six agencies, not six.

**Why this matters beyond bookkeeping:** `list_filter_values` is the tool
AI Mode uses to discover which agencies exist, and it shows the model each
id as its own agency. A question like "how much does Child Safety spend"
gets answered from whichever one of four ids the model happens to pick --
a fraction of the corpus's real answer -- not because retrieval failed, but
because the CATALOG told the model there were four different agencies to
choose from.

`MERGE_MAP` is old id -> surviving id, committed as data (not derived at
runtime) because applying it asserts a specific, disputable claim: that a
predecessor unit and its successor department -- or two duplicate catalog
rows for the identical name -- are ONE agency. A budget analyst may
disagree with any single entry, so the claim has to be visible and
reviewable, not buried inside a resolver function. `identity/relabel.py`'s
reversal-record + snapshot discipline (which `identity/merge_agencies.py`
reuses) is what makes acting on this map undoable if that disagreement
turns out to be correct.

## Target selection rule, in order (spec I9)

1. the id already referenced by the eval set, so measurement does not
   churn under this pass. `agency:dcs` qualifies on this rule alone --
   both `eval/queries_recency.yaml` (line 189) and
   `eval/queries_historical.yaml` (lines 140, 279) name it, while
   `agency:cs` -- despite having MORE primary-labelled documents (49 vs
   24, measured against the live corpus 2026-08-16) -- is not named
   anywhere in either file. Rule 1 overrides rule 3 here specifically so a
   merge doesn't quietly move the eval's own ground truth.
2. else the id whose abbreviation matches the agency's MODERN name.
   `agency:wifa` (Water Infrastructure Finance Authority) beats
   `agency:wif` on this rule even though `wif` has more primary documents
   (23 vs 7, same measurement) -- "wifa" is the name the agency uses today.
   Likewise `agency:oeo` (Equal Opportunity) over `agency:oco`, and
   `agency:cet` (Constable Ethics) over `agency:cna`.
3. else the id with the most documents. `agency:uniasu` (95 primary
   documents) over `agency:uniasum` (1) for Arizona State University, and
   `agency:dor` (81) over `agency:rev` (0, i.e. `rev` never appears as any
   chunk's primary label in the live corpus) for Revenue.

## The guard this map does NOT enforce by itself

A merge is only safe when its two ids never label a chunk from the SAME
fiscal year -- two ids that alternate across years are one agency renamed;
two ids that run in parallel every year are two real units, and merging
them would destroy information. STATUS.md records both shapes side by
side: ASU's pre-2019 and post-2019 ids are contiguous, printed in the
JLBC book catalog as "Arizona State University - Tempe/DPC" through
FY2018 and plain "Arizona State University" from FY2019 (contiguous,
never overlapping in the catalog's own per-agency page mapping); the
University of Arizona's Main Campus (`agency:uniumain`) and Health
Sciences Center (`agency:uniuhsc`) run in PARALLEL every single year --
measured against the live corpus: full overlap across all 23 years
present (FY2005-FY2027), ~42-43 primary documents each, every single
year -- and MUST NEVER be merged. That pair is deliberately absent from
this map.

Nothing in THIS module checks co-occurrence -- that requires reading the
live corpus, which a committed data file cannot do for itself.
`identity.merge_agencies.check_merge_guard` runs the guard, in two
stages: same-canonical-name first (unconditional -- see below), then
`check_cooccurrence` as the fallback for pairs whose names genuinely
differ, scoped to each chunk's PRIMARY (first) `agency_canonical_id`
rather than every id a chunk carries -- see that function's docstring for
why the wider scope is useless here (a single statewide summary table can
name dozens of agencies in one table chunk, per `chunking/entity_
stamper.py`'s decision D2, which would otherwise make almost every agency
pair look like it "co-occurs" in almost every year).

## CORRECTED 2026-08-16: co-occurrence alone was the wrong test here

A first pass gated every entry on co-occurrence alone and, measured
against the live corpus (`data/insight-data`, 83,197 rows), only FOUR of
these nine entries passed with zero overlap -- `agency:doa-cfs` ->
`agency:dcs`, `agency:doacfs` -> `agency:dcs` (neither old id is ever a
primary label -- vacuously safe), `agency:cna` -> `agency:cet` (contiguous
FY2011-2019 then FY2020-2027, genuinely a clean rename), and `agency:rev`
-> `agency:dor` (`rev` is never a primary label either). The other FIVE --
`agency:cs`, `agency:doa-csf`, `agency:uniasum`, `agency:wif`,
`agency:oco` -- showed real overlap and were refused.

**That refusal was the wrong conclusion, found by comparing canonical
names** (`samples/entity-catalog.yaml`) across every pair: ALL NINE
entries share the SAME canonical name as a sorted token multiset --
`agency:cs` "Child Safety, Department of" and `agency:dcs` "Child Safety,
Department of" is not two units that happen to overlap, it is ONE catalog
entry recorded twice under two ids, and `agency:doa-csf` "Department of
Child Safety" is the identical set of words in a different order. Both ids
of a duplicated catalog row get stamped in the same fiscal year BY
CONSTRUCTION, so co-occurrence between them is expected, not evidence
against merging. Under the corrected two-stage guard
(`identity.merge_agencies.check_merge_guard`: same-name first,
co-occurrence only as the fallback for genuinely different names), **all
nine entries clear** -- see `identity/merge_agencies.py`'s module
docstring for the full mechanism and the task-8 report for the per-pair
verdicts and the new dry-run change count.

The negative control this correction had to keep protecting: the
University of Arizona's Main Campus (`agency:uniumain`) and Health
Sciences Center (`agency:uniuhsc`) carry two genuinely DIFFERENT canonical
names ("University of Arizona - Main Campus" / "... - Health Sciences
Center"), so the same-name test does not fire for that pair -- it falls
through to co-occurrence, which still correctly refuses it (full overlap,
all 23 corpus years). That pair remains deliberately absent from
`MERGE_MAP`.
"""
from __future__ import annotations

MERGE_MAP: dict[str, str] = {
    "agency:cs": "agency:dcs",
    "agency:doa-csf": "agency:dcs",
    "agency:doa-cfs": "agency:dcs",
    "agency:doacfs": "agency:dcs",
    "agency:uniasum": "agency:uniasu",
    "agency:wif": "agency:wifa",
    "agency:oco": "agency:oeo",
    "agency:cna": "agency:cet",
    "agency:rev": "agency:dor",
}
