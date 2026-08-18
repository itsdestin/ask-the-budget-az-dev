# Agent-eval scores — 2026-08-17T2324Z-88f90b3

## Summary

- **n**: 15
- **errors**: 0
- **accurate_n**: 11
- **accurate_rate**: 0.7333
- **tokens_to_accurate_mean**: 1.915e+05
- **turns_to_accurate_mean**: 4.182
- **accurate_headline_by_set**: {'quick': {'n': 11, 'tokens_mean': 191480.18181818182, 'turns_mean': 4.181818181818182}}
- **steps_mean**: 4.133
- **retrieve_calls_mean**: 2.333
- **input_tokens_mean**: 1.041e+05
- **output_tokens_mean**: 2665
- **cached_tokens_mean**: 8.796e+04
- **total_cost_usd**: 0.4394
- **cost_missing_queries**: 0
- **cost_mean_usd**: 0.02929
- **key_fact_rate_mean**: 0.8333
- **figure_coverage_mean**: 0.7342
- **unverified_rate**: 0.2658
- **marker_coverage_mean**: 0.5768
- **tag_accuracy_mean**: 0.8709
- **retrieval_efficiency_mean**: 0.449
- **retrieves_after_sufficient_mean**: 0.5385
- **retrieves_after_sufficient_n**: 13
- **retrieves_after_sufficient_eligible_queries**: 15
- **retrieve_calls_with_filters**: 15
- **filtered_retrieve_rate**: 0.4286
- **filter_dimension_counts**: {'fiscal_year': 15, 'doc_type': 12, 'publisher': 2, 'agency_canonical_id': 8, 'fund_canonical_id': 0, 'is_table': 2}
- **retrieve_calls_with_intent**: 27
- **retrieve_calls_with_top_k**: 8
- **deep_dive_calls**: 0
- **citations_per_answer_mean**: 5.867
- **cite_pass_rate**: 0.9462
- **first_try_cite_rate**: 0.9667
- **retries_per_citation**: 0.03333
- **median_quote_len_mean**: 169.6
- **refusal_correct_rate**: None
- **false_refusals**: 0
- **narration_hit_queries**: 4
- **token_leaks**: 0
- **internal_vocab_queries**: 0
- **document_correctness_mean**: None
- **multi_unanswered_n**: 0

## Headline by set (accurate queries only)

| set | n | tokens_to_accurate | turns_to_accurate |
|---|---|---|---|
| quick | 11 | 191480 | 4.2 |

## Tool-error ledger

| kind | count | queries |
|---|---|---|
| cite_failure | 5 | cm-highway-construction, lk-lot-operating-fy2025 |

## Per query

| id | shape | ok | facts | cites ok | cite pass | 1st-try | retr eff | steps | cost |
|---|---|---|---|---|---|---|---|---|---|
| an-ahcccs-enrollment | analyze | ✓ | 0.00 | 9 | 1.00 | 1.00 | 0.12 | 4 | 0.0237 |
| an-esa-growth | analyze | ✓ | 1.00 | 14 | 1.00 | 1.00 | 0.50 | 3 | 0.0401 |
| cm-highway-construction | comparison | ✓ | 1.00 | 4 | 0.57 | 0.75 | 0.29 | 7 | 0.0455 |
| cm-supplementals-fy2026 | comparison | ✓ | 0.50 | 23 | 1.00 | 1.00 | 0.47 | 6 | 0.0322 |
| cm-university-funding-dr | comparison | ✓ | 0.00 | 1 | 1.00 | 1.00 | 0.03 | 4 | 0.0568 |
| hs-arra-k12-stabilization-2010 | historical | ✓ | 1.00 | 5 | 1.00 | 1.00 | 0.60 | 3 | 0.0194 |
| hs-bsf-draw-2008 | historical | ✓ | 1.00 | 2 | 1.00 | 1.00 | 0.20 | 4 | 0.0124 |
| lk-adc-officer-stipend-fy2026 | lookup | ✓ | 1.00 | 6 | 1.00 | 1.00 | 1.00 | 3 | 0.0097 |
| lk-asrs-rate-fy2026 | lookup | ✓ | 1.00 | 3 | 1.00 | 1.00 | 0.21 | 4 | 0.0412 |
| lk-eorp-offset | lookup | ✓ | 1.00 | 3 | 1.00 | 1.00 | 1.00 | 3 | 0.0356 |
| lk-gf-revenue-fy2026 | lookup | ✓ | 1.00 | 10 | 1.00 | 1.00 | 0.35 | 7 | 0.0310 |
| lk-k12-basic-aid-fy2026 | lookup | ✓ | 1.00 | 3 | 1.00 | 1.00 | 0.16 | 4 | 0.0144 |
| lk-lot-operating-fy2025 | lookup | ✓ | 1.00 | 3 | 0.60 | 0.60 | 0.60 | 5 | 0.0477 |
| lk-scotus-salary | lookup | ✓ | 1.00 | 2 | 1.00 | 1.00 | 1.00 | 3 | 0.0155 |
| lk-sos-secretary-of-state-fy2025 | lookup | ✓ | 1.00 | 0 | — | — | 0.20 | 2 | 0.0142 |

## Hygiene flags

- cm-supplementals-fy2026: narration x1
- cm-university-funding-dr: narration x1
- lk-asrs-rate-fy2026: narration x2
- lk-gf-revenue-fy2026: narration x2
