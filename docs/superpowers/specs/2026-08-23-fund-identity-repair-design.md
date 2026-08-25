# Fund identity repair — catalog names, ingest stamps, and the surgical unstamp

**Date:** 2026-08-23 · **Status:** DRAFT, for independent review
**Follows:** `2026-08-22-fund-names-design.md` (display allowlist, shipped on
`easy-wins`) · **Shape precedent:** the 2026-08-16 corpus identity repair
(agency labels), `identity/relabel.py`.

Destin's directive: *"we should fix this more robustly so it works in the way
a typical JLBC analyst would expect it to work."* The easy-wins allowlist
stopped wrong names from rendering; it did not make the fund dimension
BEHAVE — the model's fund list still carries 49 raw codes, several "funds"
are not funds, and 7,000+ chunks carry stamps minted by a substring bug.

## What a typical analyst expects (the acceptance frame)

1. Asking "what funds can you filter by?" lists real funds with their real
   names — no `fund:` codes, no schedule rows, no agency names.
2. Filtering by a fund returns passages actually about that fund.
3. No junk dimension values exist to be picked at all.

## The three measured defect classes (all corpus-wide, 2026-08-23)

**Class T — truncated names (repairable).** The s18 catalog parser cut real
fund names mid-phrase. For these ids, most of their own stamped chunks
contain the full name; the discriminator is *recovery coverage* (share of
stamped chunks containing `truncated name + continuation ending in
Fund/Account/Subaccount`) and *dominance* (share of the top recovered form
among all recovered forms).

**Class J — junk entries (deletable).** Catalog rows that are not funds:
`Total -`/`SUBTOTAL` schedule rows, agency names, FY-2026 budget-adjustment
lines, generic fragments (`Account`, `Block Grant`). Their "recoveries" are
collisions (`Child Safety, Department of` + the `General Fund` column of the
next table cell) — recognizable because coverage is low and the dominant
form is not a fund name.

**Class S — severed tails.** A short `X Fund` entry that is really the tail
of a longer fund's name. Measured discriminator: what word precedes `X Fund`
in that id's own stamped text. `Corrections/Podiatry/Recycling/
Telecommunications/AHCCCS Fund` are REAL short-named funds (bare form
dominates: 201/75/60/73/120 occurrences). `fund:species` ("Species Fund") is
NOT: 15 of its 18 chunks print **Endangered Species Fund**.

**Mechanism, both halves:** (a) parser truncation at catalog build; (b)
`chunking/entity_stamper.py::_scan_for_names` matches fund names as plain
casefolded substrings with NO word boundaries — which is how `Account`
stamped 5,238 chunks from inside "Account**ing**".

## Disposition table (every row carries its measured evidence)

### REPAIR — rename in place, keep stamps (17 ids)

Rule: coverage ≥ 0.6 with dominance ≥ 0.75, OR dominance = 1.00 with the
recovered form corroborated corpus-wide, OR a direct corpus-wide count
settling it. `cov`/`dom` from the full-corpus scan; `x N` = occurrence count.

| id (fund:) | new canonical_name | evidence |
|---|---|---|
| nursing-care-institution-resident-protection | Nursing Care Institution Resident Protection Revolving Fund | cov .98 dom .88 |
| department-of-education-empowerment | Department of Education Empowerment Scholarship Account | cov .95 dom 1.00 |
| nursing-care-institution-administrators-licensing-and-assisted-living-facility | Nursing Care Institution Administrators' Licensing and Assisted Living Facility Managers' Certification Fund | cov .91 dom .88 |
| board-for-private-postsecondary-education | Board for Private Postsecondary Education Fund | cov .85 dom .98 |
| special-employee-health-insurance | Special Employee Health Insurance Trust Fund | cov .77 dom .77 |
| environmental-laboratory-licensure | Environmental Laboratory Licensure Revolving Fund | cov .71 dom 1.00 |
| board-of-osteopathic-examiners-in-medicine | Board of Osteopathic Examiners in Medicine and Surgery Fund | cov .67 dom .99 |
| child-support-enforcement-administration | Child Support Enforcement Administration Fund | cov .65 dom .76 (alt is the "(CSEA)" variant of the same fund) |
| giitem-border-security-and-law | GIITEM Border Security and Law Enforcement Subaccount | cov .65 dom 1.00 |
| court-appointed-special-advocate-and | Court Appointed Special Advocate and Vulnerable Persons Fund | cov .43 dom 1.00 |
| investment-management-regulatory-and | Investment Management Regulatory and Enforcement Fund | cov .25 dom 1.00 |
| children-and-family-services-training | Children and Family Services Training Program Fund | cov .15 dom 1.00 |
| state-charitable-penal-and-reformatory | State Charitable, Penal and Reformatory Institutions Land Fund | corpus-wide: "Institutions Land Fund" ×242 vs "Land Fund" ×24 |
| motor-vehicle-liability-insurance | Motor Vehicle Liability Insurance Enforcement Fund | corpus-wide ×290 vs bare "…Insurance Fund" ×2 |
| barbering-and-cosmetology-board | Barbering and Cosmetology Board Fund | base-consistent form ×24; see open question 2 |
| federal-temporary-assistance-for-needy | Federal Temporary Assistance for Needy Families Block Grant | corpus-wide "Families Block Grant" ×94+44 |
| workforce-investment-act-grant | (unchanged — already complete) | phrase ends there in text; figures follow |

`fund:species` and `Game,Nongame, Fish and Endangered`: the implementer
READS the 18 `fund:species` chunks. If they are Game & Fish material
printing a shorthand of the statutory *Game, Nongame, Fish and Endangered
Species Fund*, DELETE `fund:species` (entry + 18 stamps) and rename the
`Game,Nongame…` entry to the full statutory name; if the bare *Endangered
Species Fund* stands as its own fund in context, RENAME `fund:species` to
"Endangered Species Fund" and keep its stamps. Decision recorded with the
read evidence either way.

### DELETE — remove catalog entry AND null its stamps

Rule, not a hand list (self-checking): **after** the renames above, delete
every catalog entry whose name still fails
`funds/names.py::_looks_like_a_fund_name` with `grant` added to the tail
words. Measured result of that rule on today's catalog: ~50 entries deleted
(all `Total -`/`SUBTOTAL` rows, all FY-2026 adjustment lines, all bare
agency names incl. `Department of Juvenile Corrections` cov .05 /
`University of Arizona - Main Campus` cov .08 / `Child Safety, Department
of` cov .17-false / `Industrial Commission of Arizona` / `Game and Fish
Department, Arizona` / `Homeopathic…` / `Juvenile Corrections, Department
of` (its cov .43 recovery is the `…Department of General Fund` column
collision, not a fund) / `Education,Department of` / `Criminal Justice
Commission,Arizona` / `Osteopathic Examiner…Board of`, plus `Account`,
`Block Grant`, `Education Sales Tax - Accountability`, `Capital Outlay -
Building Renewal/Projects`). The implementer prints and READS the final
delete list before applying — the rule proposes, the reading disposes.

Stamps carried by deleted ids: ~7,300 chunks get `fund_canonical_id`
nulled; any occurrence of a deleted id inside `fund_mentions` (if that
column is stored — verify against `store/schema.py`) is scrubbed too.

### KEEP unchanged

The 138 already-named ids, plus the real short-named funds
(`ahcccs/corrections/podiatry/recycling/telecommunications`).

## Code changes

1. **`data/fund-catalog.yaml`** — renames + deletions in place, `_meta`
   updated (`unique_funds`, a `repaired: 2026-08-23` note pointing here).
   Guard test: every entry passes the fund-name shape (so junk cannot
   return unnoticed). The catalog is generated, so
   `scripts/build_fund_catalog.py` gains the same shape filter (a
   regeneration must not resurrect junk) and a docstring warning that
   regeneration loses the in-place renames (the s18 source PDFs are not
   committed, so regeneration is already a manual affair).
2. **`chunking/entity_stamper.py`** — fund matching gains word boundaries:
   a fund-name match must not begin or end inside a word (`account` no
   longer matches in `accounting`). Scoped to the FUND path only —
   `_scan_for_names` is shared with the agency path, whose behavior was
   calibrated by the 2026-08-16 relabel and must not move (pin with a test
   that agency resolution is byte-identical on a fixture). TDD: the
   Accounting-Policies case red first.
3. **`funds/names.py`** — `_TAIL_WORDS` gains `grant` (safe once the junk
   `Block Grant` entry is deleted; TANF and WIA become displayable).
   Allowlist stays as defense in depth.
4. **`funds/unstamp.py` (new)** — the surgical pass, mirroring
   `identity/relabel.py`'s discipline: dry-run prints per-id counts →
   snapshot → write only changed rows → verify (chunk-id set identical,
   every non-fund column byte-identical on a sample, changed-row count ==
   dry-run prediction) → reversal record
   `<data_dir>/fund-unstamp-reversal-<ts>.json` holding
   `(chunk_id, old fund_canonical_id, old fund_mentions)` for every row
   touched. Both corpora checked; expectation is that
   `fiscal_note_chunks` carries no fund stamps (verify, don't assume).

## Gates

- pytest suites for stamper/catalog/names/unstamp; mutation checks on the
  boundary rule and the catalog guard.
- **Layer 1 eval, control discipline:** run on the UNMODIFIED corpus
  immediately before the write and again after; expectation identical
  (fund is a hard filter only when requested — no eval query requests
  one — and no ranking constant reads it). Any movement = stop and read.
- Full pytest + vitest + tsc + build on the branch.
- After the pass: re-run the easy-wins audit (names served / codes shown /
  junk gone) and record before/after in STATUS.

## What the analyst sees after

The fund list: ~155 real funds, every one named, zero codes, zero totals
rows, zero agencies. A fund filter no longer has junk values to return.
The 5,238 "Account" stamps stop polluting anything.

## Risks and what NOT to do

- **Do not re-run the stamper corpus-wide** to re-derive fund stamps — the
  surgical null is bounded and reversible; a re-derivation churns 97k rows
  under an uncalibrated new rule. Future ingests get the fixed rule.
- **Do not touch agency resolution** — same function, different calibrated
  path. Pin it.
- **Do not delete borderline REAL funds** — the delete rule runs after
  renames precisely so repaired names survive it; the implementer reads
  the final list.
- **Do not add truncated old names as `name_variants`** — that re-mints
  prefix matching, the bug this fixes.
- Eval-gated paths touched: `chunking/` → the eval run is OWED (and
  scheduled above). Nothing under `retrieval/`, `citation/`, `ingest/`,
  or the system prompt.

## Open questions for review

1. Is the delete-rule-then-read procedure sufficient, or should the spec
   hand-pin the full delete list? (Rule is self-checking; hand list rots.)
2. `barbering-and-cosmetology-board`: corpus prefers bare "Barbering and
   Cosmetology Fund" ×72 over "…Board Fund" ×24. The table keeps the
   base-consistent "…Board Fund". Should the ×72 form win instead?
3. Should `fund_mentions` scrubbing be in scope if the column exists but
   nothing reads it? (Verify consumers first.)

Code sketches in this spec are to be run and corrected, not transcribed.

## Amendments from independent review (2026-08-23) — these govern

Every measurement in the disposition table was independently re-derived
and reproduced (CASA 10/23 with "Vulnerable Persons Fund" in 32 chunks
corpus-wide; the Juvenile Corrections "recovery" confirmed as the
`general fund 614.0 …` column collision; Motor Vehicle 235 chunks vs 2;
Charitable 351 chunks; Investment Management 48 chunks). Corrections:

1. **`fund:block-grant` is hand-pinned for deletion, outside the rule.**
   Two words with a `grant` tail PASSES the allowlist once `grant` is a
   tail word, so the rule as written cannot delete it, and running the rule
   before adding `grant` would delete the renamed TANF and WIA entries
   instead. One pinned exception, with this reason at the code. Everything
   else (49 entries) is the rule's — enumerated against the real catalog
   with the renames applied: all junk, no real fund killed (no catalog
   entry ends in Trust/Endowment/Initiative/Authority).
2. **Both corpora are in scope.** `fiscal_note_chunks` carries 1,071 rows
   with a `fund_canonical_id` (654 `fund:account`, 68 `fund:block-grant`,
   20 `fund:department-of-juvenile-corrections`) and 84 with
   `fund_mentions`. Dry-run counts are reported PER TABLE. Budget-side:
   6,010 primary stamps on deleted ids + 2,159 rows carrying one in
   `fund_mentions` (before the block-grant pin; final counts from the
   dry run).
3. **Order:** the `Game,Nongame…` / `fund:species` decision and any rename
   it produces happen BEFORE the delete rule runs, or the rule deletes the
   truncated Game entry. `fund:species` count corrected: 16 of 18 chunks
   print "Endangered Species Fund".
4. **The unstamp mirrors five named `identity/relabel.py` disciplines:**
   (a) the ingest lock held around the write; (b) a snapshot proven
   restorable by opening the archive (`zipfile.testzip`), not merely
   present; (c) batched writes with a progress line per batch; (d)
   post-write verification that chunk-id SETS are identical and every
   non-fund column is byte-identical on touched rows plus a sample of
   untouched ones, raising "restore from the snapshot this pass just took"
   on any mismatch; (e) the reversal record written tmp+rename. The
   reversal captures the FULL old `fund_mentions` list per row — removing
   one id from a list is not invertible from the id alone.
5. **Q2 decided: `barbering-and-cosmetology-board` → canonical_name
   "Barbering and Cosmetology Fund"** (current FY2026/27 books print it 23
   vs 17; corpus-wide 62 vs 24), with "Barbering and Cosmetology Board
   Fund" as a `name_variant` — a full name, not a truncated prefix, so it
   cannot re-mint the bug.
6. **Q3 decided: `fund_mentions` scrubbing is mandatory** — it is a filter
   dimension (`store/chunk_store.py:419`), so junk left there is exactly
   the defect.
7. **Known residuals, recorded not fixed:** ~9 "Juvenile Corrections
   Fund" mentions will keep stamping as `fund:corrections` (a boundary
   rule cannot cure a real fund name that CONTAINS another real fund's
   name; only a catalog entry for the longer fund would); `RetrieveView`
   still renders fund FILTER ARGUMENTS as uppercased raw codes — the
   model's own chosen id echoed back, honest but not a name; out of scope
   here (needs the server to echo names beside filter arguments). Saved
   AI-Mode transcripts are unaffected: retrieve JSON carries no
   `fund_canonical_id`; an old `list_filter_values` card keeps whatever it
   captured.
