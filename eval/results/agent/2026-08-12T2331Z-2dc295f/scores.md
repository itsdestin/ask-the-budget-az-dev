# Agent-eval scores — 2026-08-12T2331Z-2dc295f

## Summary

- **n**: 11
- **errors**: 0
- **steps_mean**: 3.182
- **retrieve_calls_mean**: 2.636
- **input_tokens_mean**: 8.812e+04
- **output_tokens_mean**: 2808
- **cached_tokens_mean**: 6.363e+04
- **total_cost_usd**: 0.3525
- **cost_missing_queries**: 0
- **cost_mean_usd**: 0.03204
- **wall_p50_ms**: 36103
- **wall_p95_ms**: 146550
- **key_fact_rate_mean**: 0.6852
- **figure_coverage_mean**: 0.8637
- **unverified_rate**: 0.1363
- **marker_coverage_mean**: 0.6285
- **tag_accuracy_mean**: 0.9439
- **retrieval_efficiency_mean**: 0.3002
- **retrieves_after_sufficient_mean**: 2
- **retrieves_after_sufficient_n**: 4
- **retrieves_after_sufficient_eligible_queries**: 9
- **retrieve_calls_with_filters**: 11
- **filtered_retrieve_rate**: 0.3793
- **filter_dimension_counts**: {'fiscal_year': 10, 'doc_type': 9, 'publisher': 0, 'agency_canonical_id': 11, 'fund_canonical_id': 0, 'is_table': 3}
- **retrieve_calls_with_intent**: 15
- **retrieve_calls_with_top_k**: 14
- **deep_dive_calls**: 0
- **citations_per_answer_mean**: 3.909
- **cite_pass_rate**: 1
- **first_try_cite_rate**: 1
- **retries_per_citation**: 0
- **median_quote_len_mean**: 121.3
- **refusal_correct_rate**: 1
- **false_refusals**: 1
- **narration_hit_queries**: 2
- **token_leaks**: 0
- **internal_vocab_queries**: 0

## Per query

| id | shape | ok | facts | cites ok | cite pass | 1st-try | retr eff | steps | cost |
|---|---|---|---|---|---|---|---|---|---|
| an-ahcccs-gf-drivers | analyze | ✓ | 0.67 | 25 | 1.00 | 1.00 | 0.39 | 4 | 0.0531 |
| cm-basic-aid-3yr | comparison | ✓ | 0.33 | 0 | — | — | 0.02 | 5 | 0.0492 |
| cm-des-gf-growth | comparison | ✓ | 0.67 | 6 | 1.00 | 1.00 | 0.26 | 4 | 0.0294 |
| hs-arra-k12-stabilization-2010 | historical | ✓ | 1.00 | 3 | 1.00 | 1.00 | 0.60 | 3 | 0.0121 |
| lk-adc-total-fy2026 | lookup | ✓ | 0.50 | 0 | — | — | 0.00 | 3 | 0.0272 |
| lk-dps-operating-fy2026 | lookup | ✓ | 0.00 | 0 | — | — | 0.00 | 2 | 0.0273 |
| lk-k12-basic-aid-fy2026 | lookup | ✓ | 1.00 | 0 | — | — | 0.03 | 5 | 0.0818 |
| lk-prop123-increment | lookup | ✓ | 1.00 | 2 | 1.00 | 1.00 | 1.00 | 3 | 0.0163 |
| mm-adc-briefing | memo | ✓ | 1.00 | 7 | 1.00 | 1.00 | 0.40 | 4 | 0.0507 |
| rf-federal-budget | refusal | ✓ | — | 0 | — | — | — | 1 | 0.0030 |
| rf-other-state | refusal | ✓ | — | 0 | — | — | — | 1 | 0.0025 |

## Hygiene flags

- an-ahcccs-gf-drivers: narration x1
- lk-dps-operating-fy2026: false refusal
- mm-adc-briefing: narration x1
