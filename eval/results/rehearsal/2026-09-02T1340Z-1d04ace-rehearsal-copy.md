# Eval result — 2026-09-02T1340Z (1d04ace)

> ⚠ **NOT A LIVE RUN.** This was run against the Task 11b rehearsal **COPY**
> of the corpus, in a scratch data dir, AFTER the operating-table repair was
> applied to that copy. The live corpus was never written to. Its control is
> `2026-09-02T1339Z-1d04ace.{json,md}`, run minutes earlier against the LIVE
> corpus at the same commit. See
> `docs/superpowers/investigations/2026-09-01-operating-table-rebuild-dry-run.md`
> → "G-OT2".

## Summary

- **recall@5:** 86% (tracked, not gated)
- **recall@15:** 98% (gate G1: >= 90%)
- **recall@20:** 100% (gate G1: >= 95%)
- **fallback rate:** 31% of passes
- **latency:** p50 860ms, p95 960ms
- **refusal precision:** 60%

## By type

| Type | Count | recall@5 | recall@15 | recall@20 | Notes |
|---|---|---|---|---|---|
| lookup | 37 | 89% | 97% | 100% | |
| comparison | 5 | 60% | 100% | 100% | |
| refusal | 5 | — | — | — | precision: 60% |

## Failures

### q-033 (refusal)
- top_score: 5.54  latency: 769ms
- top chunk_ids: `jlbc-baseline-fy2025-hla-0003, jlbc-approps-fy2027-hla-0002, jlbc-baseline-fy2027-hla-0002, legislature-budget-bill-fy2026-sb1735-2025-0041, jlbc-baseline-fy2027-hla-0009`

### q-034 (refusal)
- top_score: 4.07  latency: 731ms
- top chunk_ids: `jlbc-approps-fy2027-496-0003, jlbc-baseline-fy2027-502-0013, jlbc-approps-fy2026-bh3-0004, jlbc-approps-fy2026-426-0026, jlbc-baseline-fy2027-502-0015`
