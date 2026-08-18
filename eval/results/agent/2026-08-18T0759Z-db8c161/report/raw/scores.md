# Agent-eval scores — 2026-08-18T0759Z-db8c161

## Summary

- **n**: 5
- **errors**: 0
- **accurate_n**: 1
- **accurate_rate**: 0.2
- **tokens_to_accurate_mean**: 2.108e+05
- **turns_to_accurate_mean**: 5
- **accurate_headline_by_set**: {'quick': {'n': 1, 'tokens_mean': 210827.0, 'turns_mean': 5.0}}
- **steps_mean**: 3.8
- **retrieve_calls_mean**: 2.4
- **input_tokens_mean**: 8.446e+04
- **output_tokens_mean**: 4555
- **cached_tokens_mean**: 7.188e+04
- **total_cost_usd**: 0.01503
- **cost_missing_queries**: 0
- **cost_mean_usd**: 0.003006
- **key_fact_rate_mean**: 0.7
- **figure_coverage_mean**: 0.7363
- **unverified_rate**: 0.2637
- **marker_coverage_mean**: 0.5213
- **tag_accuracy_mean**: 0.8333
- **retrieval_efficiency_mean**: 0.102
- **retrieves_after_sufficient_mean**: 0
- **retrieves_after_sufficient_n**: 3
- **retrieves_after_sufficient_eligible_queries**: 5
- **retrieve_calls_with_filters**: 11
- **filtered_retrieve_rate**: 0.9167
- **filter_dimension_counts**: {'fiscal_year': 11, 'doc_type': 6, 'publisher': 0, 'agency_canonical_id': 7, 'fund_canonical_id': 0, 'is_table': 1}
- **retrieve_calls_with_intent**: 12
- **retrieve_calls_with_top_k**: 2
- **deep_dive_calls**: 0
- **citations_per_answer_mean**: 2.6
- **cite_pass_rate**: 1
- **first_try_cite_rate**: 1
- **retries_per_citation**: 0
- **median_quote_len_mean**: 137.8
- **refusal_correct_rate**: None
- **false_refusals**: 0
- **narration_hit_queries**: 1
- **token_leaks**: 0
- **internal_vocab_queries**: 0
- **document_correctness_mean**: None
- **multi_unanswered_n**: 0

## Headline by set (accurate queries only)

| set | n | tokens_to_accurate | turns_to_accurate |
|---|---|---|---|
| quick | 1 | 210827 | 5.0 |

## Per query

| id | shape | ok | facts | cites ok | cite pass | 1st-try | retr eff | steps | cost |
|---|---|---|---|---|---|---|---|---|---|
| an-ahcccs-enrollment | analyze | ✓ | 0.00 | 11 | 1.00 | 1.00 | 0.23 | 4 | 0.0053 |
| hs-bsf-draw-2008 | historical | ✓ | 1.00 | 2 | 1.00 | 1.00 | 0.07 | 5 | 0.0031 |
| lk-adc-total-fy2026 | lookup | ✓ | 0.50 | 0 | — | — | 0.00 | 4 | 0.0026 |
| lk-k12-basic-aid-fy2026 | lookup | ✓ | 1.00 | 0 | — | — | 0.10 | 3 | 0.0026 |
| lk-roc-operating-fy2025 | lookup | ✓ | 1.00 | 0 | — | — | 0.11 | 3 | 0.0015 |

## Hygiene flags

- hs-bsf-draw-2008: narration x1
