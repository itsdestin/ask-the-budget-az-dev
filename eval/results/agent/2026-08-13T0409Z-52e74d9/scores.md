# Agent-eval scores — 2026-08-13T0409Z-52e74d9

## Summary

- **n**: 11
- **errors**: 0
- **steps_mean**: 5.273
- **retrieve_calls_mean**: 3.455
- **input_tokens_mean**: 1.49e+05
- **output_tokens_mean**: 3064
- **cached_tokens_mean**: 1.187e+05
- **total_cost_usd**: 0.7814
- **cost_missing_queries**: 0
- **cost_mean_usd**: 0.07103
- **wall_p50_ms**: 40877
- **wall_p95_ms**: 219643
- **key_fact_rate_mean**: 0.463
- **figure_coverage_mean**: 0.9531
- **unverified_rate**: 0.0469
- **marker_coverage_mean**: 0.6528
- **tag_accuracy_mean**: 0.9009
- **retrieval_efficiency_mean**: 0.3083
- **retrieves_after_sufficient_mean**: 0.6667
- **retrieves_after_sufficient_n**: 3
- **retrieves_after_sufficient_eligible_queries**: 9
- **retrieve_calls_with_filters**: 30
- **filtered_retrieve_rate**: 0.7895
- **filter_dimension_counts**: {'fiscal_year': 30, 'doc_type': 28, 'publisher': 0, 'agency_canonical_id': 21, 'fund_canonical_id': 0, 'is_table': 2}
- **retrieve_calls_with_intent**: 27
- **retrieve_calls_with_top_k**: 18
- **deep_dive_calls**: 0
- **citations_per_answer_mean**: 4
- **cite_pass_rate**: 0.898
- **first_try_cite_rate**: 0.9149
- **retries_per_citation**: 0.04255
- **median_quote_len_mean**: 175.2
- **refusal_correct_rate**: 1
- **false_refusals**: 2
- **narration_hit_queries**: 1
- **token_leaks**: 0
- **internal_vocab_queries**: 0

## Per query

| id | shape | ok | facts | cites ok | cite pass | 1st-try | retr eff | steps | cost |
|---|---|---|---|---|---|---|---|---|---|
| an-ahcccs-gf-drivers | analyze | ✓ | 0.00 | 0 | — | — | 0.00 | 4 | 0.0403 |
| cm-basic-aid-3yr | comparison | ✓ | 0.67 | 11 | 0.92 | 0.92 | 0.24 | 7 | 0.1444 |
| cm-des-gf-growth | comparison | ✓ | 0.00 | 0 | — | — | 0.00 | 15 | 0.1496 |
| hs-arra-k12-stabilization-2010 | historical | ✓ | 0.00 | 5 | 1.00 | 1.00 | 0.40 | 3 | 0.0109 |
| lk-adc-total-fy2026 | lookup | ✓ | 0.50 | 1 | 1.00 | 1.00 | 0.10 | 5 | 0.1184 |
| lk-dps-operating-fy2026 | lookup | ✓ | 0.50 | 5 | 0.83 | 0.83 | 0.23 | 6 | 0.0875 |
| lk-k12-basic-aid-fy2026 | lookup | ✓ | 1.00 | 9 | 0.75 | 0.80 | 0.10 | 8 | 0.1675 |
| lk-prop123-increment | lookup | ✓ | 1.00 | 4 | 1.00 | 1.00 | 1.00 | 3 | 0.0103 |
| mm-adc-briefing | memo | ✓ | 0.50 | 9 | 1.00 | 1.00 | 0.70 | 5 | 0.0468 |
| rf-federal-budget | refusal | ✓ | — | 0 | — | — | — | 1 | 0.0034 |
| rf-other-state | refusal | ✓ | — | 0 | — | — | — | 1 | 0.0023 |

## Hygiene flags

- an-ahcccs-gf-drivers: false refusal
- cm-des-gf-growth: false refusal
- lk-dps-operating-fy2026: narration x2
