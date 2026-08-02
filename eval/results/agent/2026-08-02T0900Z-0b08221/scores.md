# Agent-eval scores — 2026-08-02T0900Z-0b08221

## Summary

- **n**: 31
- **errors**: 0
- **steps_mean**: 4.806
- **retrieve_calls_mean**: 2.226
- **input_tokens_mean**: 1.384e+05
- **output_tokens_mean**: 3817
- **cached_tokens_mean**: 1.185e+05
- **total_cost_usd**: 1.205
- **cost_missing_queries**: 0
- **cost_mean_usd**: 0.03887
- **wall_p50_ms**: 34726
- **wall_p95_ms**: 228360
- **key_fact_rate_mean**: 0.8077
- **retrieval_efficiency_mean**: 0.4412
- **retrieves_after_sufficient_mean**: 0.3333
- **retrieves_after_sufficient_n**: 21
- **retrieves_after_sufficient_eligible_queries**: 26
- **retrieve_calls_with_filters**: 17
- **filtered_retrieve_rate**: 0.2464
- **filter_dimension_counts**: {'fiscal_year': 11, 'doc_type': 16, 'publisher': 1, 'agency_canonical_id': 9, 'fund_canonical_id': 0, 'is_table': 3}
- **retrieve_calls_with_intent**: 35
- **retrieve_calls_with_top_k**: 6
- **deep_dive_calls**: 0
- **citations_per_answer_mean**: 10.1
- **cite_pass_rate**: 0.8369
- **first_try_cite_rate**: 0.8997
- **retries_per_citation**: 0.1032
- **median_quote_len_mean**: 139.7
- **refusal_correct_rate**: 1
- **false_refusals**: 0
- **narration_hit_queries**: 1
- **token_leaks**: 0
- **internal_vocab_queries**: 0

## Per query

| id | shape | ok | facts | cites ok | cite pass | 1st-try | retr eff | steps | cost |
|---|---|---|---|---|---|---|---|---|---|
| an-ahcccs-enrollment | analyze | ✓ | 0.50 | 12 | 0.43 | 0.59 | 0.19 | 15 | 0.1161 |
| an-ahcccs-gf-drivers | analyze | ✓ | 1.00 | 20 | 0.91 | 0.90 | 0.32 | 6 | 0.0444 |
| an-esa-growth | analyze | ✓ | 1.00 | 27 | 0.63 | 0.62 | 0.93 | 7 | 0.0585 |
| cm-basic-aid-3yr | comparison | ✓ | 0.33 | 15 | 0.83 | 0.94 | 0.24 | 8 | 0.0678 |
| cm-des-gf-growth | comparison | ✓ | 0.67 | 13 | 0.81 | 0.77 | 0.35 | 5 | 0.0471 |
| cm-highway-construction | comparison | ✓ | 0.50 | 16 | 1.00 | 1.00 | 0.29 | 4 | 0.0115 |
| cm-supplementals-fy2026 | comparison | ✓ | 1.00 | 12 | 1.00 | 1.00 | 0.13 | 5 | 0.0327 |
| hs-building-renewal-2023 | historical | ✓ | 1.00 | 7 | 1.00 | 1.00 | 1.00 | 3 | 0.0139 |
| hs-enhanced-fmap-2022 | historical | ✓ | 1.00 | 17 | 1.00 | 1.00 | 0.85 | 4 | 0.0266 |
| hs-esa-cost-2022 | historical | ✓ | 1.00 | 6 | 1.00 | 1.00 | 0.40 | 3 | 0.0123 |
| hs-promise-program-2023 | historical | ✓ | 1.00 | 4 | 1.00 | 1.00 | 0.30 | 4 | 0.0162 |
| hs-water-augmentation-2023 | historical | ✓ | 1.00 | 7 | 1.00 | 1.00 | 0.40 | 3 | 0.0148 |
| lk-adc-officer-stipend-fy2026 | lookup | ✓ | 1.00 | 5 | 1.00 | 1.00 | 0.80 | 3 | 0.0118 |
| lk-adc-total-fy2026 | lookup | ✓ | 0.50 | 14 | 1.00 | 1.00 | 0.07 | 4 | 0.0405 |
| lk-asrs-rate-fy2026 | lookup | ✓ | 0.00 | 13 | 1.00 | 1.00 | 0.28 | 4 | 0.0919 |
| lk-asu-operating-fy2026 | lookup | ✓ | 0.00 | 10 | 1.00 | 1.00 | 0.21 | 4 | 0.0740 |
| lk-bsf-balance-fy2026 | lookup | ✓ | 0.50 | 2 | 1.00 | 1.00 | 0.40 | 3 | 0.0209 |
| lk-dps-operating-fy2026 | lookup | ✓ | 1.00 | 35 | 0.83 | 0.97 | 0.04 | 15 | 0.1493 |
| lk-eorp-offset | lookup | ✓ | 1.00 | 6 | 1.00 | 1.00 | 1.00 | 3 | 0.0128 |
| lk-gf-revenue-fy2026 | lookup | ✓ | 1.00 | 3 | 1.00 | 1.00 | 0.80 | 3 | 0.0106 |
| lk-hurf-split | lookup | ✓ | 1.00 | 6 | 1.00 | 1.00 | 0.18 | 4 | 0.0311 |
| lk-k12-basic-aid-fy2026 | lookup | ✓ | 1.00 | 5 | 0.31 | 0.62 | 0.13 | 15 | 0.1120 |
| lk-prop123-increment | lookup | ✓ | 1.00 | 3 | 1.00 | 1.00 | 1.00 | 3 | 0.0073 |
| lk-scotus-salary | lookup | ✓ | 1.00 | 3 | 1.00 | 1.00 | 1.00 | 3 | 0.0163 |
| mm-adc-briefing | memo | ✓ | 1.00 | 33 | 0.92 | 0.97 | 0.25 | 7 | 0.0894 |
| mm-esa-memo | memo | ✓ | 1.00 | 19 | 1.00 | 1.00 | 0.34 | 4 | 0.0581 |
| rf-city-budget | refusal | ✓ | — | 0 | — | — | — | 1 | 0.0022 |
| rf-county-budget | refusal | ✓ | — | 0 | — | — | 0.00 | 2 | 0.0062 |
| rf-federal-budget | refusal | ✓ | — | 0 | — | — | — | 1 | 0.0028 |
| rf-future-budget | refusal | ✓ | — | 0 | — | — | — | 2 | 0.0050 |
| rf-other-state | refusal | ✓ | — | 0 | — | — | — | 1 | 0.0009 |

## Hygiene flags

- hs-water-augmentation-2023: narration x1
