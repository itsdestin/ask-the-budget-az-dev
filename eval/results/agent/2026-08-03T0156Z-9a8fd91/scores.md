# Agent-eval scores — 2026-08-03T0156Z-9a8fd91

## Summary

- **n**: 31
- **errors**: 0
- **steps_mean**: 3.452
- **retrieve_calls_mean**: 2.161
- **input_tokens_mean**: 7.605e+04
- **output_tokens_mean**: 2351
- **cached_tokens_mean**: 6.194e+04
- **total_cost_usd**: 0.7071
- **cost_missing_queries**: 0
- **cost_mean_usd**: 0.02281
- **wall_p50_ms**: 16745
- **wall_p95_ms**: 57879
- **key_fact_rate_mean**: 0.6603
- **figure_coverage_mean**: 0.9016
- **unverified_rate**: 0.09839
- **retrieval_efficiency_mean**: 0.3327
- **retrieves_after_sufficient_mean**: 0.6
- **retrieves_after_sufficient_n**: 15
- **retrieves_after_sufficient_eligible_queries**: 26
- **retrieve_calls_with_filters**: 27
- **filtered_retrieve_rate**: 0.403
- **filter_dimension_counts**: {'fiscal_year': 21, 'doc_type': 20, 'publisher': 1, 'agency_canonical_id': 22, 'fund_canonical_id': 0, 'is_table': 2}
- **retrieve_calls_with_intent**: 54
- **retrieve_calls_with_top_k**: 7
- **deep_dive_calls**: 0
- **citations_per_answer_mean**: 4.484
- **cite_pass_rate**: 0.9858
- **first_try_cite_rate**: 0.9858
- **retries_per_citation**: 0
- **median_quote_len_mean**: 156.9
- **refusal_correct_rate**: 1
- **false_refusals**: 2
- **narration_hit_queries**: 2
- **token_leaks**: 0
- **internal_vocab_queries**: 0

## Per query

| id | shape | ok | facts | cites ok | cite pass | 1st-try | retr eff | steps | cost |
|---|---|---|---|---|---|---|---|---|---|
| an-ahcccs-enrollment | analyze | ✓ | 0.00 | 15 | 1.00 | 1.00 | 0.17 | 4 | 0.0326 |
| an-ahcccs-gf-drivers | analyze | ✓ | 0.33 | 6 | 0.86 | 0.86 | 0.30 | 4 | 0.0411 |
| an-esa-growth | analyze | ✓ | 0.50 | 9 | 1.00 | 1.00 | 0.32 | 5 | 0.0541 |
| cm-basic-aid-3yr | comparison | ✓ | 0.67 | 0 | — | — | 0.40 | 2 | 0.0095 |
| cm-des-gf-growth | comparison | ✓ | 0.67 | 15 | 1.00 | 1.00 | 0.18 | 4 | 0.0486 |
| cm-highway-construction | comparison | ✓ | 0.00 | 0 | — | — | 0.00 | 7 | 0.0248 |
| cm-supplementals-fy2026 | comparison | ✓ | 1.00 | 0 | — | — | 0.01 | 4 | 0.0483 |
| hs-building-renewal-2023 | historical | ✓ | 1.00 | 7 | 1.00 | 1.00 | 0.50 | 4 | 0.0233 |
| hs-enhanced-fmap-2022 | historical | ✓ | 1.00 | 8 | 1.00 | 1.00 | 0.43 | 3 | 0.0324 |
| hs-esa-cost-2022 | historical | ✓ | 1.00 | 5 | 1.00 | 1.00 | 0.60 | 3 | 0.0141 |
| hs-promise-program-2023 | historical | ✓ | 1.00 | 3 | 1.00 | 1.00 | 0.20 | 4 | 0.0247 |
| hs-water-augmentation-2023 | historical | ✓ | 1.00 | 14 | 1.00 | 1.00 | 0.23 | 3 | 0.0256 |
| lk-adc-officer-stipend-fy2026 | lookup | ✓ | 1.00 | 4 | 1.00 | 1.00 | 0.41 | 4 | 0.0167 |
| lk-adc-total-fy2026 | lookup | ✓ | 0.00 | 0 | — | — | 0.00 | 2 | 0.0083 |
| lk-asrs-rate-fy2026 | lookup | ✓ | 0.00 | 5 | 1.00 | 1.00 | 0.40 | 3 | 0.0163 |
| lk-asu-operating-fy2026 | lookup | ✓ | 0.00 | 3 | 1.00 | 1.00 | 0.11 | 4 | 0.0280 |
| lk-bsf-balance-fy2026 | lookup | ✓ | 0.50 | 4 | 1.00 | 1.00 | 0.20 | 3 | 0.0089 |
| lk-dps-operating-fy2026 | lookup | ✓ | 0.00 | 5 | 0.83 | 0.83 | 0.11 | 5 | 0.0244 |
| lk-eorp-offset | lookup | ✓ | 1.00 | 3 | 1.00 | 1.00 | 1.00 | 3 | 0.0122 |
| lk-gf-revenue-fy2026 | lookup | ✓ | 1.00 | 3 | 1.00 | 1.00 | 0.80 | 3 | 0.0130 |
| lk-hurf-split | lookup | ✓ | 1.00 | 3 | 1.00 | 1.00 | 0.44 | 4 | 0.0186 |
| lk-k12-basic-aid-fy2026 | lookup | ✓ | 1.00 | 0 | — | — | 0.00 | 3 | 0.0161 |
| lk-prop123-increment | lookup | ✓ | 1.00 | 3 | 1.00 | 1.00 | 1.00 | 3 | 0.0078 |
| lk-scotus-salary | lookup | ✓ | 1.00 | 2 | 1.00 | 1.00 | 0.80 | 3 | 0.0107 |
| mm-adc-briefing | memo | ✓ | 0.50 | 13 | 1.00 | 1.00 | 0.56 | 5 | 0.0306 |
| mm-esa-memo | memo | ✓ | 1.00 | 9 | 1.00 | 1.00 | 0.13 | 5 | 0.0912 |
| rf-city-budget | refusal | ✓ | — | 0 | — | — | — | 1 | 0.0027 |
| rf-county-budget | refusal | ✓ | — | 0 | — | — | 0.00 | 2 | 0.0061 |
| rf-federal-budget | refusal | ✓ | — | 0 | — | — | — | 1 | 0.0028 |
| rf-future-budget | refusal | ✓ | — | 0 | — | — | — | 4 | 0.0083 |
| rf-other-state | refusal | ✓ | — | 0 | — | — | 0.00 | 2 | 0.0053 |

## Hygiene flags

- an-ahcccs-enrollment: narration x1
- an-esa-growth: narration x1
- cm-highway-construction: false refusal
- lk-adc-total-fy2026: false refusal
