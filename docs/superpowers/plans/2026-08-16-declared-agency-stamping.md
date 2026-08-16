# Scope — stamping the agency an uploader declared

**Status: SCOPED, NOT BUILT.** Three decisions below need answers before
any code is written. Written 2026-08-16, off the back of the upload page's
new agency picker (merge `039c3ad`).

> **⚠ SEQUENCING — do this AFTER the identity spec's Phase 2, not before.**
> [`../specs/2026-08-16-corpus-identity-consistency-design.md`](../specs/2026-08-16-corpus-identity-consistency-design.md)
> repairs three poisoned catalog names and re-stamps the corpus, and it
> touches the same `chunking/entity_stamper.py` ladder this document adds a
> Rule 0 to. Two facts below are also refined by it: the stamper's weakness
> is not only the 103-of-157 alias gap but **three canonical names that are
> table-of-contents rows**, one of which mis-stamps 721 documents; and
> Decision 2's "office ids cannot be rendered" is sharpened by the identity
> spec's I9, which merges duplicate ids in the data. **Nothing here is
> withdrawn** — declared-agency stamping is still the right fix for the
> ~78 incoming budget requests, and its "do it before they land" argument
> is unchanged.

## The one sentence

The upload page now asks which agency a budget request belongs to, and
throws that answer away after writing it into the document's title — this
would keep it, so that filtering or searching by agency actually finds the
document.

## Why this is worth doing, in numbers

| | |
|---|---|
| Agencies in the shipped catalog | **157** |
| Of those, carrying **no alias** the text-matcher can recognise | **103** |
| Agency-submission documents currently in the corpus | **0** |
| Agency budget requests waiting to be uploaded (FY2027 alone) | **~78** |

The stamper resolves an agency by reading the document's text and matching
catalog names. On an agency's own budget request that is the weakest case
it faces: two thirds of agencies have no alias, and a document titled
*"FY 2027 Budget Request"* whose own agency is never spelled the catalog's
way resolves to **nothing**. `ingest/validate.py` already reports this as
a percentage and would flag every one of them.

Meanwhile a person uploading it has just told us the answer, from a list of
canonical ids, and we discard it.

**The 0 in that table is the reason to do it NOW rather than later.** No
agency submission has ever been ingested, so there is no back-catalogue to
re-stamp and no re-ingest to schedule. Every one of the ~78 lands correctly
the first time. Do this after they are loaded and it becomes a re-ingest.

## Why it is small: the mechanism already exists

`chunking/entity_stamper.py::_resolve` is a ladder, and **Rule 1 is already
an out-of-band hint applied ahead of reading any text**:

```python
# Rule 1: slug from URL (with rule-2 alias hop folded in)
slug = slug_from_jlbc_url(source_url)
```

That is a JLBC book page saying "I am the AHCCCS page" through its URL. A
declared agency is the same kind of statement from a person instead of a
URL. This is not a new mechanism — it is a second source for one that ships.

The plumbing is equally short, because `source_url` already rides the same
route and there is exactly **one** `stamp()` call site in the codebase.

## The change, file by file

| File | Change | Size |
|---|---|---|
| `chunking/types.py` | `DocMeta` gains `declared_agency: str \| None = None`, beside the existing `source_url` | 1 field |
| `chunking/entity_stamper.py` | `stamp()` / `resolve_all()` / `_resolve()` accept it; new **Rule 0** ahead of the URL slug | ~25 lines |
| `chunking/builder.py:112` | pass `doc_meta.declared_agency` into `stamp()` | 1 line |
| `ingest/worker.py:1004` | build `DocMeta(..., declared_agency=job.agency_canonical_id)` | 1 line |
| `ingest/worker.py:1135` | pass it into `resolve_all()` for the table path | 1 line |
| `ingest/validate.py:29` | add `agency-submission` to `PER_AGENCY_DOC_TYPES` so the stamp rate is actually checked | 1 line |

`JobRecord.agency_canonical_id` already exists and is already persisted —
that landed with the picker. Nothing new is stored.

**Roughly 30 lines of production code.** The work is in the decisions and
the tests, not the typing.

---

## 🔴 Decision 1 — does a declared agency beat the document's own text?

This is the substantive one, and it is NOT the same question as the title,
where declared already wins.

| | What happens | Cost |
|---|---|---|
| **A. Declared fills gaps only** | The text matcher runs first; the declared agency is used only where it found nothing | Safe. But on a document whose text names a *different* agency in passing — a budget request quoting a JLBC schedule — those chunks stay stamped as the other agency, and the person's answer loses to a passing mention |
| **B. Declared is primary on every chunk; tables still add the rest** (recommended) | Every chunk is stamped with the declared agency. Table chunks, which legitimately name many agencies (decision D2), still scan and append the others | Matches how the URL-slug rule already behaves for book pages, and matches the title rule shipped in `039c3ad`. Risk: one person's mistake stamps the WHOLE document, where today a bad stamp is one chunk |

**Recommendation: B**, because it is what Rule 1 already does for a JLBC
book page and the document is genuinely *about* one agency — that is the
defining property of the type. The risk it carries is real and is
Decision 3's problem.

## 🔴 Decision 2 — what happens to an agency the office added?

An admin-added agency has an id like `agency:office-broadband`. It is not
in the catalog, which has consequences the picker does not have:

- **Retrieval works.** `store/chunk_store.py` filters `agency_canonical_ids`
  by list overlap on whatever string is in the column. It does not consult
  the catalog.
- **Display does not.** `app/routes/corpus.py` and `app/search_terms.py`
  resolve ids to names *through the catalog*, so an office id would show a
  blank or a raw slug in the agency facet.
- **The query side cannot reach it.** `retrieval/query_agency.py` maps typed
  words → catalog ids. Nobody typing "broadband" would ever produce
  `agency:office-broadband`, so the stamp would be reachable only by an
  exact filter nothing offers.

| | |
|---|---|
| **A. Stamp office ids anyway** | Honest data, but creates ids that filter and never display, and that no query can produce |
| **B. Stamp only catalog ids; office ids title the document and stop there** (recommended) | The picker still names the document correctly, which is what an office entry was added for. Nothing enters the corpus that the rest of the app cannot describe |
| **C. Let an admin map an office agency onto a catalog id** | Solves it properly, but that is the alias overlay's job and a much bigger surface |

**Recommendation: B for now**, with the reason recorded at the code.
Office-added agencies are the rare escape hatch — the 157 cover the state
budget as of 2026 — so the common path is unaffected either way, and B
keeps the corpus free of ids nothing can render.

## 🔴 Decision 3 — is a wrong pick worse than no stamp?

Under Decision 1B one mis-click stamps every passage of a document with the
wrong agency, and **it is silent**: nothing looks wrong, the document just
answers to the wrong agency filter for ever. Today's failure mode is the
opposite — an unstamped document is invisible to the filter, which is
visible as an absence.

Three ways to bound it, not mutually exclusive:

1. **Confirm on screen at submit.** The upload form already knows the name;
   show the title it is about to create — *"This will be filed as: FY 2027
   Budget Request — Corrections, State Department of"*. Cheap, and it turns
   a silent mis-click into something you read before pressing Add.
2. **Disagreement is a warning, not a failure.** `ingest/validate.py` runs
   advisory checks after every ingest. If the text resolves confidently to a
   *different* agency than the one declared, say so on the queue row. This
   is exactly the shape of the existing "only 17% agency-stamped" warning.
3. **Do nothing.** A wrong pick is a human error the same way a wrong file
   is, and the app does not second-guess the file either.

**Recommendation: 1 and 2.** #1 is a few lines on a form that already has
the data. #2 reuses a mechanism built for precisely this class of problem
and has already caught one real defect (the mislabelled Industrial
Commission upload, recorded in STATUS.md).

---

## What this does NOT fix

Worth stating plainly, because the numbers above invite the wrong
conclusion:

- **The 103-of-157 alias gap is untouched.** This gives ONE document type a
  way around it. Every other type still depends on the text matcher, and
  fixing that properly needs the alias work recorded in STATUS.md under
  "The corpus has the SAME missing-alias problem, on the ingest side".
- **The existing 7,434 documents do not change.** Nothing is re-stamped.
- **It does not make agency a hard filter.** Agency is deliberately a
  *preference*, not a filter (measured: the hard filter lost, 88.10% →
  83.33% recall@5). This change is evidence toward re-measuring that
  decision later — better stamping is exactly the condition STATUS.md names
  for re-opening it — but it is not that change.

## How it gets measured, and the honest problem

**There is nothing in the eval set to measure this with.** Zero
agency-submission documents exist, so no eval query can have ground truth
in one. Claiming an eval improvement here would be claiming a number the
instrument cannot produce.

So the gate is a real ingest, not a recall figure:

1. **Control first.** Run `eval.run_eval` before and after. `chunking/` is
   on the changed path, so a no-regression run is required by CLAUDE.md.
   Expect *identical* numbers — no existing chunk changes.
2. **Ingest one real agency budget request** through the upload page with
   an agency picked. Then check three things:
   - **stamp rate** — should be ~100% of passages, against a measured 0% for
     the same document with the agency left off. That is the before/after
     pair, and it needs both halves run on the same document.
   - an agency-filtered search returns it;
   - the agency facet on Budget Documents shows it under the right name.
3. **Then a second one with the agency deliberately WRONG**, to see what
   Decision 3's warning does.

Steps 2 and 3 need one real PDF and about ten minutes each of MinerU time.

## Effort

| | |
|---|---|
| Production code | ~30 lines across 6 files |
| Tests | ~10 specs — Rule 0 precedence, tables still multi-stamping, office ids per Decision 2, nothing declared → today's behaviour byte-identical |
| Eval | one control run, ~60 s |
| Live verification | 2 ingests, ~20 min |
| **Realistic total** | **half a day**, most of it verification |

## The order to do it in

1. Answer Decisions 1–3.
2. Decision 3 item #1 (the confirm-on-screen line) can ship on its own,
   today, with no ingest change at all — it improves the picker whether or
   not the rest of this happens.
3. The stamping change, eval-gated.
4. The live before/after on one real document.
