# Agent-eval scores — 2026-08-03T2009Z-gpt56luna-957262c

## Summary

- **n**: 11
- **errors**: 0
- **steps_mean**: 3.364
- **retrieve_calls_mean**: 1.636
- **input_tokens_mean**: 6.05e+04
- **output_tokens_mean**: 1271
- **cached_tokens_mean**: 5.11e+04
- **total_cost_usd**: 0.02693
- **cost_missing_queries**: 0
- **cost_mean_usd**: 0.002448
- **wall_p50_ms**: 25502
- **wall_p95_ms**: 52285
- **key_fact_rate_mean**: 0.4815
- **figure_coverage_mean**: 0.9768
- **unverified_rate**: 0.02317
- **retrieval_efficiency_mean**: 0.1911
- **retrieves_after_sufficient_mean**: 0
- **retrieves_after_sufficient_n**: 3
- **retrieves_after_sufficient_eligible_queries**: 9
- **retrieve_calls_with_filters**: 18
- **filtered_retrieve_rate**: 1
- **filter_dimension_counts**: {'fiscal_year': 18, 'doc_type': 15, 'publisher': 14, 'agency_canonical_id': 12, 'fund_canonical_id': 0, 'is_table': 18}
- **retrieve_calls_with_intent**: 18
- **retrieve_calls_with_top_k**: 18
- **deep_dive_calls**: 0
- **citations_per_answer_mean**: 1.455
- **cite_pass_rate**: 1
- **first_try_cite_rate**: 1
- **retries_per_citation**: 0
- **median_quote_len_mean**: 139.1
- **refusal_correct_rate**: 1
- **false_refusals**: 1
- **narration_hit_queries**: 0
- **token_leaks**: 0
- **internal_vocab_queries**: 0

## Per query

| id | shape | ok | facts | cites ok | cite pass | 1st-try | retr eff | steps | cost |
|---|---|---|---|---|---|---|---|---|---|
| an-ahcccs-gf-drivers | analyze | ✓ | 0.00 | 2 | 1.00 | 1.00 | 0.06 | 4 | 0.0031 |
| cm-basic-aid-3yr | comparison | ✓ | 0.33 | 3 | 1.00 | 1.00 | 0.07 | 4 | 0.0047 |
| cm-des-gf-growth | comparison | ✓ | 0.00 | 0 | — | — | 0.00 | 3 | 0.0022 |
| hs-arra-k12-stabilization-2010 | historical | ✓ | 1.00 | 1 | 1.00 | 1.00 | 0.20 | 3 | 0.0028 |
| lk-adc-total-fy2026 | lookup | ✓ | 0.50 | 1 | 1.00 | 1.00 | 0.20 | 3 | 0.0013 |
| lk-dps-operating-fy2026 | lookup | ✓ | 0.00 | 2 | 1.00 | 1.00 | 0.20 | 4 | 0.0016 |
| lk-k12-basic-aid-fy2026 | lookup | ✓ | 1.00 | 1 | 1.00 | 1.00 | 0.12 | 4 | 0.0024 |
| lk-prop123-increment | lookup | ✓ | 1.00 | 1 | 1.00 | 1.00 | 0.60 | 3 | 0.0027 |
| mm-adc-briefing | memo | ✓ | 0.50 | 5 | 1.00 | 1.00 | 0.46 | 5 | 0.0045 |
| rf-federal-budget | refusal | ✓ | — | 0 | — | — | 0.00 | 3 | 0.0013 |
| rf-other-state | refusal | ✓ | — | 0 | — | — | — | 1 | 0.0002 |

## Hygiene flags

- cm-des-gf-growth: false refusal
