# Agent-eval scores — 2026-08-18T0747Z-db8c161

## Summary

- **n**: 10
- **errors**: 0
- **accurate_n**: 5
- **accurate_rate**: 0.5
- **tokens_to_accurate_mean**: 2.243e+05
- **turns_to_accurate_mean**: 4.8
- **accurate_headline_by_set**: {'quick': {'n': 5, 'tokens_mean': 224280.0, 'turns_mean': 4.8}}
- **steps_mean**: 4.5
- **retrieve_calls_mean**: 2.7
- **input_tokens_mean**: 1.23e+05
- **output_tokens_mean**: 7015
- **cached_tokens_mean**: 9.196e+04
- **total_cost_usd**: 0.05313
- **cost_missing_queries**: 0
- **cost_mean_usd**: 0.005313
- **key_fact_rate_mean**: 0.9167
- **figure_coverage_mean**: 0.5987
- **unverified_rate**: 0.4013
- **marker_coverage_mean**: 0.5102
- **tag_accuracy_mean**: 0.6126
- **retrieval_efficiency_mean**: 0.3228
- **retrieves_after_sufficient_mean**: 0.3333
- **retrieves_after_sufficient_n**: 9
- **retrieves_after_sufficient_eligible_queries**: 10
- **retrieve_calls_with_filters**: 18
- **filtered_retrieve_rate**: 0.6667
- **filter_dimension_counts**: {'fiscal_year': 17, 'doc_type': 11, 'publisher': 1, 'agency_canonical_id': 8, 'fund_canonical_id': 0, 'is_table': 1}
- **retrieve_calls_with_intent**: 26
- **retrieve_calls_with_top_k**: 8
- **deep_dive_calls**: 0
- **citations_per_answer_mean**: 5
- **cite_pass_rate**: 0.9615
- **first_try_cite_rate**: 0.9804
- **retries_per_citation**: 0.01961
- **median_quote_len_mean**: 155.7
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
| quick | 5 | 224280 | 4.8 |

## Tool-error ledger

| kind | count | queries |
|---|---|---|
| cite_failure | 2 | an-ahcccs-enrollment, mm-adc-briefing |

## Per query

| id | shape | ok | facts | cites ok | cite pass | 1st-try | retr eff | steps | cost |
|---|---|---|---|---|---|---|---|---|---|
| an-ahcccs-enrollment | analyze | ✓ | 1.00 | 11 | 0.92 | 1.00 | 0.22 | 5 | 0.0055 |
| an-ahcccs-gf-drivers | analyze | ✓ | 0.67 | 7 | 1.00 | 1.00 | 0.46 | 5 | 0.0069 |
| an-esa-growth | analyze | ✓ | 0.50 | 8 | 1.00 | 1.00 | 0.20 | 5 | 0.0067 |
| hs-arra-k12-stabilization-2010 | historical | ✓ | 1.00 | 2 | 1.00 | 1.00 | 0.40 | 3 | 0.0015 |
| hs-bsf-draw-2008 | historical | ✓ | 1.00 | 0 | — | — | 0.05 | 7 | 0.0116 |
| hs-full-day-kindergarten-2005 | historical | ✓ | 1.00 | 2 | 1.00 | 1.00 | 0.20 | 3 | 0.0016 |
| hs-fy2010-oneshot-financing | historical | ✓ | 1.00 | 0 | — | — | 0.20 | 2 | 0.0009 |
| hs-leaseback-prisons-2010 | historical | ✓ | 1.00 | 0 | — | — | 1.00 | 2 | 0.0010 |
| mm-adc-briefing | memo | ✓ | 1.00 | 10 | 0.91 | 0.91 | 0.31 | 7 | 0.0065 |
| mm-esa-memo | memo | ✓ | 1.00 | 10 | 1.00 | 1.00 | 0.20 | 6 | 0.0110 |

## Hygiene flags

- hs-bsf-draw-2008: narration x2
