# Ask the Budget AZ

A Q&A tool over Arizona state budget documents — JLBC Appropriations Reports, Baseline Books, AGAO Annual Financial Reports, and the Governor's Executive Budget proposals.

**Audience:** JLBC staff and fiscal analysts (initially). Public-facing access is a possible Phase 4, gated on internal trust metrics.

**The product is auditable retrieval, not chat.** Every claim links to the exact PDF page and bounding box that supports it. Faithfulness is checked at generation time; failed citations are visibly stripped rather than silently accepted.

## Status

**Phase 0 — Investigation:** ✓ closed 2026-05-06. Outcomes in [`docs/superpowers/investigations/2026-05-06-phase-0-findings.md`](docs/superpowers/investigations/2026-05-06-phase-0-findings.md) (memo), [`2026-05-05-chunk-shape-decisions.md`](docs/superpowers/investigations/2026-05-05-chunk-shape-decisions.md) (chunking), and [`2026-05-06-data-model.md`](docs/superpowers/investigations/2026-05-06-data-model.md) (publisher landscape + cross-doc relationships).

**Phase 1a — Ingest + chunking:** ✓ closed 2026-05-06 (slice-validated). Tag `phase-1a-validated-slice`. 5 docs / 161 chunks / 91.3% agency-stamped / 227 funds. Hand-off contract at [`data/chunks/MANIFEST.md`](data/chunks/MANIFEST.md). Full-corpus ingest moves to Phase 1b kickoff.

**Phase 1b — Storage + retrieval:** in planning. See [`docs/superpowers/plans/2026-05-06-phase-1b-storage-and-retrieval.md`](docs/superpowers/plans/2026-05-06-phase-1b-storage-and-retrieval.md).

**Phase 1c — Companion + UI:** not started. See [`docs/superpowers/plans/2026-05-06-phase-1c-companion-and-ui.md`](docs/superpowers/plans/2026-05-06-phase-1c-companion-and-ui.md).

For architectural context across all phases, see [`docs/superpowers/specs/2026-05-04-ask-the-budget-az-design.md`](docs/superpowers/specs/2026-05-04-ask-the-budget-az-design.md).

## Repos in this project

| Repo | Purpose | Status |
|---|---|---|
| `ask-the-budget-az-dev` (this) | Workspace: docs, plans, specs | Active |
| `ask-the-budget-az` | Web app (Next.js + React + TypeScript) | Planned (Phase 1) |
| `ask-the-budget-az-companion` | JLBC Budget Agent — local companion app for Pro/Max-backed LLM calls | Planned (Phase 2) |
| `ask-the-budget-az-ingest` | Offline ingest pipeline (PDF → chunks → embeddings → Postgres) | Planned (Phase 1) |

## Quick links

- [Design spec](docs/superpowers/specs/2026-05-04-ask-the-budget-az-design.md)
- [Workspace conventions](CLAUDE.md)
- Phase 1a → Phase 1b hand-off contract: [`data/chunks/MANIFEST.md`](data/chunks/MANIFEST.md)
- Phase 1b plan (next): [`docs/superpowers/plans/2026-05-06-phase-1b-storage-and-retrieval.md`](docs/superpowers/plans/2026-05-06-phase-1b-storage-and-retrieval.md)
- Phase 1c plan (later): [`docs/superpowers/plans/2026-05-06-phase-1c-companion-and-ui.md`](docs/superpowers/plans/2026-05-06-phase-1c-companion-and-ui.md)
- Phase 0 findings memo: [`docs/superpowers/investigations/2026-05-06-phase-0-findings.md`](docs/superpowers/investigations/2026-05-06-phase-0-findings.md)
- Chunk-shape decisions: [`docs/superpowers/investigations/2026-05-05-chunk-shape-decisions.md`](docs/superpowers/investigations/2026-05-05-chunk-shape-decisions.md)
- Source-data model: [`docs/superpowers/investigations/2026-05-06-data-model.md`](docs/superpowers/investigations/2026-05-06-data-model.md)

## Why this exists

Fiscal analysts spend significant time finding the right line item across many heterogeneous documents that name the same program differently and present numbers in different formats. The hard part isn't summarizing — it's *locating with provenance*. This tool tries to accelerate that work without sacrificing the rigor analysts need.
