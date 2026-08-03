# Agent-eval scores — 2026-08-03T2010Z-dsv4flash-957262c

## Summary

- **n**: 11
- **errors**: 0
- **steps_mean**: 5.182
- **retrieve_calls_mean**: 3
- **input_tokens_mean**: 1.631e+05
- **output_tokens_mean**: 3097
- **cached_tokens_mean**: 1.34e+05
- **total_cost_usd**: 0.06024
- **cost_missing_queries**: 0
- **cost_mean_usd**: 0.005476
- **wall_p50_ms**: 29543
- **wall_p95_ms**: 119743
- **key_fact_rate_mean**: 0.6296
- **figure_coverage_mean**: 0.9631
- **unverified_rate**: 0.03694
- **retrieval_efficiency_mean**: 0.2426
- **retrieves_after_sufficient_mean**: 0.25
- **retrieves_after_sufficient_n**: 4
- **retrieves_after_sufficient_eligible_queries**: 9
- **retrieve_calls_with_filters**: 30
- **filtered_retrieve_rate**: 0.9091
- **filter_dimension_counts**: {'fiscal_year': 22, 'doc_type': 21, 'publisher': 2, 'agency_canonical_id': 30, 'fund_canonical_id': 0, 'is_table': 2}
- **retrieve_calls_with_intent**: 31
- **retrieve_calls_with_top_k**: 21
- **deep_dive_calls**: 0
- **citations_per_answer_mean**: 4.182
- **cite_pass_rate**: 0.8679
- **first_try_cite_rate**: 0.9
- **retries_per_citation**: 0.06
- **median_quote_len_mean**: 97.42
- **refusal_correct_rate**: 1
- **false_refusals**: 1
- **narration_hit_queries**: 2
- **token_leaks**: 0
- **internal_vocab_queries**: 0

## Per query

| id | shape | ok | facts | cites ok | cite pass | 1st-try | retr eff | steps | cost |
|---|---|---|---|---|---|---|---|---|---|
| an-ahcccs-gf-drivers | analyze | ✓ | 0.00 | 16 | 0.94 | 0.94 | 0.35 | 5 | 0.0059 |
| cm-basic-aid-3yr | comparison | ✓ | 1.00 | 4 | 0.80 | 0.80 | 0.20 | 6 | 0.0059 |
| cm-des-gf-growth | comparison | ✓ | 0.67 | 9 | 0.90 | 1.00 | 0.24 | 14 | 0.0151 |
| hs-arra-k12-stabilization-2010 | historical | ✓ | 1.00 | 0 | — | — | 0.20 | 2 | 0.0012 |
| lk-adc-total-fy2026 | lookup | ✓ | 0.00 | 1 | 1.00 | 1.00 | 0.20 | 3 | 0.0026 |
| lk-dps-operating-fy2026 | lookup | ✓ | 0.00 | 0 | — | — | 0.00 | 3 | 0.0031 |
| lk-k12-basic-aid-fy2026 | lookup | ✓ | 1.00 | 0 | — | — | 0.05 | 3 | 0.0032 |
| lk-prop123-increment | lookup | ✓ | 1.00 | 3 | 1.00 | 1.00 | 1.00 | 3 | 0.0024 |
| mm-adc-briefing | memo | ✓ | 1.00 | 13 | 0.76 | 0.80 | 0.19 | 15 | 0.0197 |
| rf-federal-budget | refusal | ✓ | — | 0 | — | — | — | 1 | 0.0003 |
| rf-other-state | refusal | ✓ | — | 0 | — | — | 0.00 | 2 | 0.0009 |

## Hygiene flags

- cm-des-gf-growth: narration x1
- lk-dps-operating-fy2026: false refusal
- lk-k12-basic-aid-fy2026: narration x1
