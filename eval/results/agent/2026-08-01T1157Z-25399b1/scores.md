# Agent-eval scores — 2026-08-01T1157Z-25399b1

## Summary

- **n**: 11
- **errors**: 0
- **steps_mean**: 3.545
- **retrieve_calls_mean**: 2.091
- **input_tokens_mean**: 8.363e+04
- **output_tokens_mean**: 3231
- **cached_tokens_mean**: 6.027e+04
- **total_cost_usd**: 0.4254
- **cost_missing_queries**: 0
- **cost_mean_usd**: 0.03867
- **wall_p50_ms**: 15898
- **wall_p95_ms**: 54273
- **key_fact_rate_mean**: 0.9074
- **retrieval_efficiency_mean**: 0.341
- **retrieves_after_sufficient_mean**: 0.1667
- **retrieves_after_sufficient_n**: 6
- **retrieves_after_sufficient_eligible_queries**: 9
- **retrieve_calls_with_filters**: 6
- **filtered_retrieve_rate**: 0.2609
- **filter_dimension_counts**: {'fiscal_year': 6, 'doc_type': 3, 'publisher': 0, 'agency_canonical_id': 6, 'fund_canonical_id': 0, 'is_table': 1}
- **retrieve_calls_with_intent**: 21
- **retrieve_calls_with_top_k**: 8
- **deep_dive_calls**: 0
- **citations_per_answer_mean**: 9
- **cite_pass_rate**: 0.99
- **first_try_cite_rate**: 1
- **retries_per_citation**: 0.0101
- **median_quote_len_mean**: 131.1
- **refusal_correct_rate**: 1
- **false_refusals**: 0
- **narration_hit_queries**: 1
- **token_leaks**: 0
- **internal_vocab_queries**: 0

## Per query

| id | shape | ok | facts | cites ok | cite pass | 1st-try | retr eff | steps | cost |
|---|---|---|---|---|---|---|---|---|---|
| an-ahcccs-gf-drivers | analyze | ✓ | 0.67 | 12 | 1.00 | 1.00 | 0.25 | 4 | 0.0514 |
| cm-basic-aid-3yr | comparison | ✓ | 1.00 | 17 | 1.00 | 1.00 | 0.12 | 7 | 0.1241 |
| cm-des-gf-growth | comparison | ✓ | 1.00 | 11 | 1.00 | 1.00 | 0.38 | 4 | 0.0396 |
| hs-promise-program-2023 | historical | ✓ | 1.00 | 4 | 1.00 | 1.00 | 0.14 | 5 | 0.0275 |
| lk-adc-total-fy2026 | lookup | ✓ | 1.00 | 15 | 1.00 | 1.00 | 0.40 | 3 | 0.0431 |
| lk-dps-operating-fy2026 | lookup | ✓ | 1.00 | 3 | 1.00 | 1.00 | 0.20 | 3 | 0.0120 |
| lk-k12-basic-aid-fy2026 | lookup | ✓ | 1.00 | 5 | 1.00 | 1.00 | 0.40 | 3 | 0.0253 |
| lk-prop123-increment | lookup | ✓ | 1.00 | 4 | 1.00 | 1.00 | 1.00 | 3 | 0.0117 |
| mm-adc-briefing | memo | ✓ | 0.50 | 28 | 0.97 | 1.00 | 0.18 | 5 | 0.0667 |
| rf-federal-budget | refusal | ✓ | — | 0 | — | — | — | 1 | 0.0205 |
| rf-other-state | refusal | ✓ | — | 0 | — | — | — | 1 | 0.0035 |

## Hygiene flags

- cm-basic-aid-3yr: narration x1
