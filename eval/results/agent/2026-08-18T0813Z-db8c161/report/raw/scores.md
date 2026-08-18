# Agent-eval scores — 2026-08-18T0813Z-db8c161

## Summary

- **n**: 5
- **errors**: 0
- **provider_errors**: 0
- **accurate_n**: 0
- **accurate_rate**: 0
- **tokens_to_accurate_mean**: None
- **turns_to_accurate_mean**: None
- **accurate_headline_by_set**: {}
- **steps_mean**: 2.6
- **retrieve_calls_mean**: 1.8
- **input_tokens_mean**: 5.589e+04
- **output_tokens_mean**: 1094
- **cached_tokens_mean**: 2.995e+04
- **total_cost_usd**: 0.0138
- **cost_missing_queries**: 0
- **cost_mean_usd**: 0.002759
- **key_fact_rate_mean**: 0.4
- **figure_coverage_mean**: 0.82
- **unverified_rate**: 0.18
- **marker_coverage_mean**: 0.6397
- **tag_accuracy_mean**: 0.9333
- **retrieval_efficiency_mean**: 0.09
- **retrieves_after_sufficient_mean**: 0
- **retrieves_after_sufficient_n**: 2
- **retrieves_after_sufficient_eligible_queries**: 5
- **retrieve_calls_with_filters**: 7
- **filtered_retrieve_rate**: 0.7778
- **filter_dimension_counts**: {'fiscal_year': 7, 'doc_type': 3, 'publisher': 0, 'agency_canonical_id': 2, 'fund_canonical_id': 0, 'is_table': 0}
- **retrieve_calls_with_intent**: 9
- **retrieve_calls_with_top_k**: 2
- **deep_dive_calls**: 0
- **citations_per_answer_mean**: 0
- **cite_pass_rate**: None
- **first_try_cite_rate**: None
- **retries_per_citation**: None
- **median_quote_len_mean**: None
- **refusal_correct_rate**: None
- **false_refusals**: 3
- **narration_hit_queries**: 1
- **token_leaks**: 0
- **internal_vocab_queries**: 0
- **document_correctness_mean**: None
- **multi_unanswered_n**: 0

## Per query

| id | shape | ok | facts | cites ok | cite pass | 1st-try | retr eff | steps | cost |
|---|---|---|---|---|---|---|---|---|---|
| an-ahcccs-enrollment | analyze | ✓ | 0.00 | 0 | — | — | 0.00 | 2 | 0.0027 |
| hs-bsf-draw-2008 | historical | ✓ | 1.00 | 0 | — | — | 0.05 | 4 | 0.0041 |
| lk-adc-total-fy2026 | lookup | ✓ | 0.00 | 0 | — | — | 0.00 | 3 | 0.0028 |
| lk-k12-basic-aid-fy2026 | lookup | ✓ | 1.00 | 0 | — | — | 0.40 | 2 | 0.0020 |
| lk-roc-operating-fy2025 | lookup | ✓ | 0.00 | 0 | — | — | 0.00 | 2 | 0.0022 |

## Hygiene flags

- an-ahcccs-enrollment: false refusal
- hs-bsf-draw-2008: narration x1
- lk-adc-total-fy2026: false refusal
- lk-roc-operating-fy2025: false refusal
