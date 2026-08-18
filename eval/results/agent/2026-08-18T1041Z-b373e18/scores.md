# Agent-eval scores — 2026-08-18T1041Z-b373e18

## Summary

- **n**: 45
- **errors**: 0
- **provider_errors**: 0
- **accurate_n**: 34
- **accurate_rate**: 0.7556
- **tokens_to_accurate_mean**: 1.44e+05
- **turns_to_accurate_mean**: 3.353
- **accurate_headline_by_set**: {'quick': {'n': 34, 'tokens_mean': 143983.4705882353, 'turns_mean': 3.3529411764705883}}
- **steps_mean**: 3.489
- **retrieve_calls_mean**: 1.667
- **input_tokens_mean**: 8.224e+04
- **output_tokens_mean**: 1060
- **cached_tokens_mean**: 7.046e+04
- **total_cost_usd**: 0.2531
- **cost_missing_queries**: 0
- **cost_mean_usd**: 0.005626
- **key_fact_rate_mean**: 0.8037
- **figure_coverage_mean**: 0.8675
- **unverified_rate**: 0.1325
- **marker_coverage_mean**: 0.9182
- **tag_accuracy_mean**: 0.8873
- **retrieval_efficiency_mean**: 0.2143
- **retrieves_after_sufficient_mean**: 0.2174
- **retrieves_after_sufficient_n**: 23
- **retrieves_after_sufficient_eligible_queries**: 45
- **retrieve_calls_with_filters**: 64
- **filtered_retrieve_rate**: 0.8533
- **filter_dimension_counts**: {'fiscal_year': 59, 'doc_type': 56, 'publisher': 5, 'agency_canonical_id': 38, 'fund_canonical_id': 0, 'is_table': 24}
- **retrieve_calls_with_intent**: 70
- **retrieve_calls_with_top_k**: 67
- **deep_dive_calls**: 0
- **citations_per_answer_mean**: 1.4
- **cite_pass_rate**: 1
- **first_try_cite_rate**: 1
- **retries_per_citation**: 0
- **median_quote_len_mean**: 131.4
- **refusal_correct_rate**: None
- **false_refusals**: 1
- **narration_hit_queries**: 0
- **token_leaks**: 0
- **internal_vocab_queries**: 0
- **document_correctness_mean**: None
- **multi_unanswered_n**: 0

## Headline by set (accurate queries only)

| set | n | tokens_to_accurate | turns_to_accurate |
|---|---|---|---|
| quick | 34 | 143983 | 3.4 |

## Per query

| id | shape | ok | facts | cites ok | cite pass | 1st-try | retr eff | steps | cost |
|---|---|---|---|---|---|---|---|---|---|
| an-ahcccs-enrollment | analyze | ✓ | 1.00 | 2 | 1.00 | 1.00 | 0.12 | 5 | 0.0095 |
| an-ahcccs-gf-drivers | analyze | ✓ | 0.00 | 2 | 1.00 | 1.00 | 0.04 | 4 | 0.0077 |
| an-esa-growth | analyze | ✓ | 0.50 | 0 | — | — | 0.06 | 4 | 0.0095 |
| cm-basic-aid-3yr | comparison | ✓ | 0.00 | 5 | 1.00 | 1.00 | 0.19 | 4 | 0.0085 |
| cm-des-gf-growth | comparison | ✓ | 0.67 | 6 | 1.00 | 1.00 | 0.35 | 5 | 0.0102 |
| cm-highway-construction | comparison | ✓ | 0.50 | 0 | — | — | 0.19 | 3 | 0.0073 |
| cm-supplementals-fy2026 | comparison | ✓ | 0.00 | 5 | 1.00 | 1.00 | 0.07 | 6 | 0.0179 |
| cm-university-funding-dr | comparison | ✓ | 0.00 | 3 | 1.00 | 1.00 | 0.10 | 4 | 0.0152 |
| hs-arra-k12-stabilization-2010 | historical | ✓ | 1.00 | 1 | 1.00 | 1.00 | 0.20 | 3 | 0.0026 |
| hs-bsf-draw-2008 | historical | ✓ | 0.00 | 2 | 1.00 | 1.00 | 0.20 | 4 | 0.0037 |
| hs-full-day-kindergarten-2005 | historical | ✓ | 1.00 | 0 | — | — | 0.20 | 2 | 0.0017 |
| hs-fy2010-oneshot-financing | historical | ✓ | 1.00 | 0 | — | — | 0.10 | 3 | 0.0029 |
| hs-leaseback-prisons-2010 | historical | ✓ | 1.00 | 1 | 1.00 | 1.00 | 0.20 | 3 | 0.0024 |
| lk-adc-officer-stipend-fy2026 | lookup | ✓ | 1.00 | 2 | 1.00 | 1.00 | 0.32 | 5 | 0.0082 |
| lk-adc-total-fy2026 | lookup | ✓ | 0.50 | 0 | — | — | 0.00 | 3 | 0.0034 |
| lk-agr-horse-liaison-fy2025 | lookup | ✓ | 1.00 | 1 | 1.00 | 1.00 | 0.20 | 3 | 0.0024 |
| lk-agr-operating-fy2025 | lookup | ✓ | 1.00 | 0 | — | — | 0.20 | 3 | 0.0043 |
| lk-asrs-rate-fy2026 | lookup | ✓ | 1.00 | 1 | 1.00 | 1.00 | 0.20 | 3 | 0.0076 |
| lk-asu-operating-fy2026 | lookup | ✓ | 0.00 | 3 | 1.00 | 1.00 | 0.29 | 4 | 0.0041 |
| lk-bsf-balance-fy2026 | lookup | ✓ | 1.00 | 0 | — | — | 0.00 | 2 | 0.0024 |
| lk-djc-juvenile-corrections-fy2025 | lookup | ✓ | 1.00 | 0 | — | — | 0.20 | 3 | 0.0039 |
| lk-dor-revenue-operating-fy2025 | lookup | ✓ | 1.00 | 1 | 1.00 | 1.00 | 0.25 | 3 | 0.0029 |
| lk-dps-historical-operating-fy2013 | historical | ✓ | 1.00 | 1 | 1.00 | 1.00 | 0.05 | 5 | 0.0068 |
| lk-dps-operating-fy2026 | lookup | ✓ | 0.00 | 0 | — | — | 0.00 | 2 | 0.0025 |
| lk-eorp-offset | lookup | ✓ | 1.00 | 1 | 1.00 | 1.00 | 0.40 | 3 | 0.0028 |
| lk-fis-game-and-fish-fy2025 | lookup | ✓ | 1.00 | 0 | — | — | 0.00 | 4 | 0.0101 |
| lk-gam-operating-fy2025 | lookup | ✓ | 1.00 | 0 | — | — | 0.20 | 3 | 0.0042 |
| lk-gf-revenue-fy2026 | lookup | ✓ | 1.00 | 0 | — | — | 0.60 | 2 | 0.0016 |
| lk-hurf-split | lookup | ✓ | 1.00 | 2 | 1.00 | 1.00 | 0.24 | 4 | 0.0079 |
| lk-k12-basic-aid-fy2026 | lookup | ✓ | 1.00 | 2 | 1.00 | 1.00 | 0.29 | 4 | 0.0048 |
| lk-liq-operating-fy2025 | lookup | ✓ | 1.00 | 0 | — | — | 0.00 | 2 | 0.0016 |
| lk-lot-operating-fy2025 | lookup | ✓ | 1.00 | 1 | 1.00 | 1.00 | 0.33 | 3 | 0.0027 |
| lk-min-operating-fy2025 | lookup | ✓ | 1.00 | 2 | 1.00 | 1.00 | 0.40 | 4 | 0.0050 |
| lk-nursing-board-operating-fy2025 | lookup | ✓ | 1.00 | 0 | — | — | 0.00 | 3 | 0.0036 |
| lk-prop123-increment | lookup | ✓ | 1.00 | 1 | 1.00 | 1.00 | 0.78 | 4 | 0.0089 |
| lk-psp-operating-fy2025 | lookup | ✓ | 1.00 | 0 | — | — | 0.20 | 3 | 0.0039 |
| lk-roc-operating-fy2025 | lookup | ✓ | 1.00 | 0 | — | — | 0.00 | 3 | 0.0036 |
| lk-scotus-salary | lookup | ✓ | 1.00 | 2 | 1.00 | 1.00 | 0.80 | 3 | 0.0030 |
| lk-sos-secretary-of-state-fy2025 | lookup | ✓ | 1.00 | 0 | — | — | 0.40 | 2 | 0.0019 |
| lk-tou-tourism-fy2026 | lookup | ✓ | 1.00 | 0 | — | — | 0.00 | 3 | 0.0039 |
| lk-uhsc-arizona-health-fy2026 | lookup | ✓ | 1.00 | 0 | — | — | 0.00 | 4 | 0.0040 |
| lk-vsc-veterans-services-fy2025 | lookup | ✓ | 1.00 | 0 | — | — | 0.00 | 3 | 0.0036 |
| lk-wat-operating-fy2025 | lookup | ✓ | 1.00 | 0 | — | — | 0.20 | 2 | 0.0018 |
| mm-adc-briefing | memo | ✓ | 1.00 | 10 | 1.00 | 1.00 | 0.60 | 7 | 0.0190 |
| mm-esa-memo | memo | ✓ | 1.00 | 6 | 1.00 | 1.00 | 0.50 | 5 | 0.0075 |

## Hygiene flags

- lk-dps-operating-fy2026: false refusal
