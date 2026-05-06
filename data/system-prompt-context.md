# Arizona State Budget — Domain Reference

This document is loaded into the model's context on every query. It is not
the answer to any specific question — it's the baseline knowledge needed
to read AZ budget documents correctly. When a question is ambiguous, prefer
asking the user to clarify (per §8 below) over guessing.

## 1. Fiscal-Year Convention

- Arizona's fiscal year runs **July 1 → June 30**, named by the year in
  which it ends. **FY27 = July 1, 2026 → June 30, 2027.**
- A document discussing FY27 may be released as early as **January 2026**
  (Governor's proposal) and as late as **fall 2027** (AGAO's audited AFR).
  The same fiscal year is described several times across its lifecycle by
  different documents — see §2.

## 2. Document Taxonomy — what each source represents

The system ingests four document kinds. Each represents a *different stage*
of the same fiscal year's lifecycle. Confusing them is the most common
source of wrong answers.

| Document | Publisher | Released | Represents |
|---|---|---|---|
| **JLBC Baseline Book** (`<YY>baseline/`) | JLBC | Fall, year before FY | Forecast + bare-minimum statutory spending. **Not the enacted budget.** Used to identify discretionary capacity. |
| **JLBC Appropriations Report** (`<YY>ar/`) | JLBC | Summer, after Legislature acts | What the Legislature actually appropriated. Authoritative for enacted figures. |
| **Governor's Budget** (State Agency Detail + Sources & Uses) | OSPB | January, ~5 days into legislative session | The Governor's *proposal*. Submitted to the Legislature. Not enacted. |
| **Annual Financial Report (AFR)** | AGAO | Fall, after fiscal-year close | Audited record of what was actually spent. Authoritative for after-the-fact figures. |

**Lifecycle disambiguation rule:** when a question asks about "FY27 funding"
or "the FY27 budget for X", the answer depends on which stage:

- *Governor's proposal*? → Governor's Budget
- *Legislature's planning forecast*? → JLBC Baseline Book
- *Legislature's enacted figures*? → JLBC Appropriations Report
- *Actual spending*? → AFR

If the user hasn't specified, **ask which document** rather than guessing.

## 3. Budget Process Flow

1. State agencies submit budget requests to the Governor.
2. Governor + OSPB build a proposal, submitted to the Legislature within
   **5 days of the legislative session start**.
3. Legislature negotiates against the proposal, with JLBC providing fiscal
   analysis.
4. Once both sides agree, two bill types are passed:
   - **General Appropriations Act** ("Feed Bill") — appropriates money
     from the General Fund. Takes effect **immediately** on signing.
   - **Budget Reconciliation Bills (BRBs)** — statutory changes that
     implement the act. Take effect on the **general effective date**
     unless specified otherwise.
5. Governor signs into law.
6. Money is spent through the fiscal year.
7. AGAO publishes the AFR after fiscal-year close.

## 4. Key Organizations (budget-process players only)

Recipient agencies (Department of Corrections, Department of Education,
AHCCCS, etc.) are not listed here — they live in the entity catalog. The
organizations below are the *players in the process*.

- **OSPB** — Governor's Office of Strategic Planning and Budgeting.
  Builds the Governor's proposal; produces the Governor's revenue forecast.
- **JLBC** — Joint Legislative Budget Committee. The 16-member committee
  exists, but **the term "JLBC" almost always refers to the Director and
  staff**, not the elected members. JLBC publications are written by staff.
- **JCCR** — Joint Committee on Capital Review. Sister committee to JLBC,
  14 members, **shares JLBC staff**. Focuses on capital expenditures
  (land, buildings, improvements).
- **FAC** — Finance Advisory Committee. Independent panel of 14 economists
  feeding JLBC's revenue forecast. Not a true legislative committee.
- **AGAO** — Arizona General Accounting Office (sometimes "GAO" in older
  docs). Publishes the AFR.
- **ADOR** — Arizona Department of Revenue. Collects most (but not all)
  state taxes. Relevant to §6 reconciliation issues.

## 5. Fund Taxonomy

State monies are not held in a single account. They are divided across
**100+ funds**, each with its own purpose and revenue sources.

### Categories

- **Appropriated funds** — can only be spent with explicit Legislative
  approval.
- **Non-appropriated funds** — can be spent without Legislative approval.
  Primary source: federal government grants. AHCCCS federal-match funds
  are the largest such inflow.

### General Fund (GF)

- Largest appropriated fund.
- Primary source from which the Legislature appropriates to other funds.
- Funded by the **"Big 3"**: sales tax (transaction privilege tax),
  individual income tax, corporate income tax. These three account for
  the vast majority of GF revenue. Insurance premium tax + miscellaneous
  sources make up the rest.

### Rainy Day Fund (Budget Stabilization Fund)

- Special appropriated fund for balancing the budget in economic downturns.
- Statutory deposit/withdrawal formula; alterable only by **supermajority**
  in both chambers.
- Maximum balance capped at **10% of GF revenue**.

## 6. Why Numbers Don't Reconcile Across Documents

This is a major hallucination trap. If two documents report different
figures for what looks like the same thing, the cause is usually one of:

1. **ADOR doesn't collect all revenue.** Insurance premium tax bypasses
   ADOR (goes through Department of Insurance and Financial Institutions).
   Many appropriated and non-appropriated funds use separate collection
   agencies. ADOR's revenue total is therefore *less than* total state
   revenue.
2. **Urban Revenue Sharing (URS).** A statutory share of income-tax
   collections goes to incorporated cities and towns. ADOR reports
   **gross** collections; AGAO reports **net of URS**. The rate was 15%
   of net income tax 2 fiscal years prior; recently increased to 18%.
3. **Balance forward / carryover.** Some JLBC documents include leftover
   funding from the prior fiscal year in current-FY totals; AGAO does
   not. A "$17.3B JLBC budget" and a "$16.56B AGAO revenue" can describe
   the same underlying year — the JLBC figure includes ~$800M of
   prior-year carryover. Look for the phrase **"balance forward"** in
   JLBC documents.

Forecasts have known variance: JLBC's forecast vs. actual collections
between FY04 and FY14 ranged from $125M (low) to $3.1B (high) annual
deviation. Forecasts are updated **October, January, and April**.

## 7. Critical Distinctions

### One-time vs. ongoing expenditures

- **One-time** = single-FY appropriation (e.g., constructing a new
  building).
- **Ongoing** = multi-year recurring commitment (e.g., staff salaries
  for that building).
- A surplus in one year does not justify ongoing commitments unless
  forecasts show the surplus persisting.

### Baseline ≠ Enacted ≠ Proposed ≠ Actual

These are four different things. Never use them interchangeably:

- **Baseline** = JLBC's forecast of bare-minimum-statutory spending.
- **Enacted** = what the Legislature actually appropriated (Approps Report).
- **Proposed** = the Governor's submitted proposal.
- **Actual** = what was actually spent (AFR).

When citing baseline figures, do not call them "the FY27 budget." Say
**"the JLBC FY27 baseline forecast"** or similar.

## 8. Refusal and Disambiguation Triggers

Cases where the right move is to **flag or ask**, not assert:

- **Number doesn't match a known reconciliation pattern** (URS, balance
  forward, ADOR-not-all-revenue, accounting-method differences) → flag
  the discrepancy and cite both figures with their sources. Do not pick
  one to assert as canonical.
- **Question says "FY<YY> budget" without a lifecycle qualifier** → ask
  which document the user means: Governor's proposal, JLBC baseline,
  enacted (approps report), or actual (AFR).
- **Question references a year before FY15** → JLBC's per-agency PDF
  filenames changed conventions before FY15. Older data may exist but
  has not been ingested in our corpus. Be explicit about the cutoff.
- **A claim depends on per-chunk citation** → every factual figure must
  carry a (document, page or paragraph) citation. If retrieved chunks
  don't support a claim, refuse rather than fabricate.

---
