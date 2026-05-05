# Ask the Budget AZ

A Q&A tool over Arizona state budget documents — JLBC Appropriations Reports, Baseline Books, AGAO Annual Financial Reports, and the Governor's Executive Budget proposals.

**Audience:** JLBC staff and fiscal analysts (initially). Public-facing access is a possible Phase 4, gated on internal trust metrics.

**The product is auditable retrieval, not chat.** Every claim links to the exact PDF page and bounding box that supports it. Faithfulness is checked at generation time; failed citations are visibly stripped rather than silently accepted.

## Status

**Phase 0 — Investigation** (not started). See [`docs/superpowers/specs/2026-05-04-ask-the-budget-az-design.md`](docs/superpowers/specs/2026-05-04-ask-the-budget-az-design.md) for the full design.

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
- Phase 0 findings (when available): `docs/superpowers/investigations/`

## Why this exists

Fiscal analysts spend significant time finding the right line item across many heterogeneous documents that name the same program differently and present numbers in different formats. The hard part isn't summarizing — it's *locating with provenance*. This tool tries to accelerate that work without sacrificing the rigor analysts need.
