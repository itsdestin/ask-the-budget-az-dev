# Agent-eval scores — 2026-09-03T1004Z-c20f8c4

## Summary

- **n**: 7
- **errors**: 0
- **provider_errors**: 0
- **accurate_n**: 2
- **accurate_rate**: 0.2857
- **tokens_to_accurate_mean**: 1.313e+05
- **turns_to_accurate_mean**: 3
- **accurate_headline_by_set**: {'quick': {'n': 2, 'tokens_mean': 131290.5, 'turns_mean': 3.0}}
- **steps_mean**: 2.857
- **retrieve_calls_mean**: 2.286
- **input_tokens_mean**: 7.078e+04
- **output_tokens_mean**: 4755
- **cached_tokens_mean**: 5.401e+04
- **total_cost_usd**: 0.0231
- **cost_missing_queries**: 0
- **cost_mean_usd**: 0.0033
- **key_fact_rate_mean**: 0.2857
- **figure_coverage_mean**: 0.8312
- **unverified_rate**: 0.1688
- **marker_coverage_mean**: 0.6111
- **tag_accuracy_mean**: 0.781
- **retrieval_efficiency_mean**: 0.1143
- **retrieves_after_sufficient_mean**: 0
- **retrieves_after_sufficient_n**: 1
- **retrieves_after_sufficient_eligible_queries**: 7
- **retrieve_calls_with_filters**: 16
- **filtered_retrieve_rate**: 1
- **filter_dimension_counts**: {'fiscal_year': 16, 'doc_type': 12, 'publisher': 0, 'agency_canonical_id': 4, 'fund_canonical_id': 0, 'is_table': 1}
- **retrieve_calls_with_intent**: 16
- **retrieve_calls_with_top_k**: 6
- **deep_dive_calls**: 0
- **citations_per_answer_mean**: 0.1429
- **cite_pass_rate**: 1
- **first_try_cite_rate**: 1
- **retries_per_citation**: 0
- **median_quote_len_mean**: 99
- **refusal_correct_rate**: None
- **false_refusals**: 5
- **narration_hit_queries**: 0
- **token_leaks**: 0
- **internal_vocab_queries**: 0
- **document_correctness_mean**: None
- **multi_unanswered_n**: 0

## Headline by set (accurate queries only)

| set | n | tokens_to_accurate | turns_to_accurate |
|---|---|---|---|
| quick | 2 | 131290 | 3.0 |

## Per query

| id | shape | ok | facts | cites ok | cite pass | 1st-try | retr eff | steps | cost |
|---|---|---|---|---|---|---|---|---|---|
| cm-supplementals-fy2026 | comparison | ✓ | 0.00 | 0 | — | — | 0.00 | 5 | 0.0087 |
| cm-university-funding-dr | comparison | ✓ | 0.00 | 0 | — | — | 0.00 | 3 | 0.0049 |
| lk-adc-total-fy2026 | lookup | ✓ | 0.00 | 0 | — | — | 0.00 | 2 | 0.0011 |
| lk-asu-operating-fy2026 | lookup | ✓ | 1.00 | 1 | 1.00 | 1.00 | 0.80 | 3 | 0.0041 |
| lk-dps-operating-fy2026 | lookup | ✓ | 0.00 | 0 | — | — | 0.00 | 2 | 0.0012 |
| lk-min-operating-fy2025 | lookup | ✓ | 1.00 | 0 | — | — | 0.00 | 3 | 0.0020 |
| lk-tou-tourism-fy2026 | lookup | ✓ | 0.00 | 0 | — | — | 0.00 | 2 | 0.0009 |

## Hygiene flags

- cm-supplementals-fy2026: false refusal
- cm-university-funding-dr: false refusal
- lk-adc-total-fy2026: false refusal
- lk-dps-operating-fy2026: false refusal
- lk-tou-tourism-fy2026: false refusal
