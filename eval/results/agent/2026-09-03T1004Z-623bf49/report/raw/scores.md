# Agent-eval scores — 2026-09-03T1004Z-623bf49

## Summary

- **n**: 7
- **errors**: 0
- **provider_errors**: 0
- **accurate_n**: 3
- **accurate_rate**: 0.4286
- **tokens_to_accurate_mean**: 1.123e+05
- **turns_to_accurate_mean**: 2.667
- **accurate_headline_by_set**: {'quick': {'n': 3, 'tokens_mean': 112271.33333333333, 'turns_mean': 2.6666666666666665}}
- **steps_mean**: 3.286
- **retrieve_calls_mean**: 2.143
- **input_tokens_mean**: 9.302e+04
- **output_tokens_mean**: 3721
- **cached_tokens_mean**: 6.205e+04
- **total_cost_usd**: 0.02965
- **cost_missing_queries**: 0
- **cost_mean_usd**: 0.004236
- **key_fact_rate_mean**: 0.4286
- **figure_coverage_mean**: 0.9274
- **unverified_rate**: 0.07256
- **marker_coverage_mean**: 0.7446
- **tag_accuracy_mean**: 0.9439
- **retrieval_efficiency_mean**: 0.1205
- **retrieves_after_sufficient_mean**: 0
- **retrieves_after_sufficient_n**: 1
- **retrieves_after_sufficient_eligible_queries**: 7
- **retrieve_calls_with_filters**: 14
- **filtered_retrieve_rate**: 0.9333
- **filter_dimension_counts**: {'fiscal_year': 14, 'doc_type': 10, 'publisher': 0, 'agency_canonical_id': 8, 'fund_canonical_id': 0, 'is_table': 2}
- **retrieve_calls_with_intent**: 15
- **retrieve_calls_with_top_k**: 5
- **deep_dive_calls**: 0
- **citations_per_answer_mean**: 0.4286
- **cite_pass_rate**: 1
- **first_try_cite_rate**: 1
- **retries_per_citation**: 0
- **median_quote_len_mean**: 88.5
- **refusal_correct_rate**: None
- **false_refusals**: 3
- **narration_hit_queries**: 0
- **token_leaks**: 0
- **internal_vocab_queries**: 0
- **document_correctness_mean**: None
- **multi_unanswered_n**: 0

## Headline by set (accurate queries only)

| set | n | tokens_to_accurate | turns_to_accurate |
|---|---|---|---|
| quick | 3 | 112271 | 2.7 |

## Per query

| id | shape | ok | facts | cites ok | cite pass | 1st-try | retr eff | steps | cost |
|---|---|---|---|---|---|---|---|---|---|
| cm-supplementals-fy2026 | comparison | ✓ | 0.00 | 0 | — | — | 0.00 | 5 | 0.0071 |
| cm-university-funding-dr | comparison | ✓ | 0.00 | 2 | 1.00 | 1.00 | 0.04 | 6 | 0.0065 |
| lk-adc-total-fy2026 | lookup | ✓ | 1.00 | 0 | — | — | 0.00 | 3 | 0.0029 |
| lk-asu-operating-fy2026 | lookup | ✓ | 1.00 | 1 | 1.00 | 1.00 | 0.80 | 3 | 0.0044 |
| lk-dps-operating-fy2026 | lookup | ✓ | 0.00 | 0 | — | — | 0.00 | 2 | 0.0036 |
| lk-min-operating-fy2025 | lookup | ✓ | 1.00 | 0 | — | — | 0.00 | 2 | 0.0017 |
| lk-tou-tourism-fy2026 | lookup | ✓ | 0.00 | 0 | — | — | 0.00 | 2 | 0.0034 |

## Hygiene flags

- cm-supplementals-fy2026: false refusal
- lk-dps-operating-fy2026: false refusal
- lk-tou-tourism-fy2026: false refusal
