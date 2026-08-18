# Agent-eval scores — 2026-08-18T0850Z-6a28d03

## Summary

- **n**: 45
- **errors**: 0
- **provider_errors**: 0
- **accurate_n**: 32
- **accurate_rate**: 0.7111
- **tokens_to_accurate_mean**: 1.275e+05
- **turns_to_accurate_mean**: 3
- **accurate_headline_by_set**: {'quick': {'n': 32, 'tokens_mean': 127539.65625, 'turns_mean': 3.0}}
- **steps_mean**: 3.489
- **retrieve_calls_mean**: 2.289
- **input_tokens_mean**: 9.02e+04
- **output_tokens_mean**: 2809
- **cached_tokens_mean**: 7.09e+04
- **total_cost_usd**: 0.209
- **cost_missing_queries**: 0
- **cost_mean_usd**: 0.004645
- **key_fact_rate_mean**: 0.7852
- **figure_coverage_mean**: 0.8255
- **unverified_rate**: 0.1745
- **marker_coverage_mean**: 0.7344
- **tag_accuracy_mean**: 0.8828
- **retrieval_efficiency_mean**: 0.2205
- **retrieves_after_sufficient_mean**: 0.4333
- **retrieves_after_sufficient_n**: 30
- **retrieves_after_sufficient_eligible_queries**: 45
- **retrieve_calls_with_filters**: 83
- **filtered_retrieve_rate**: 0.8058
- **filter_dimension_counts**: {'fiscal_year': 74, 'doc_type': 55, 'publisher': 0, 'agency_canonical_id': 45, 'fund_canonical_id': 0, 'is_table': 6}
- **retrieve_calls_with_intent**: 88
- **retrieve_calls_with_top_k**: 27
- **deep_dive_calls**: 0
- **citations_per_answer_mean**: 1.133
- **cite_pass_rate**: 0.8947
- **first_try_cite_rate**: 0.9107
- **retries_per_citation**: 0.01786
- **median_quote_len_mean**: 169.8
- **refusal_correct_rate**: None
- **false_refusals**: 6
- **narration_hit_queries**: 6
- **token_leaks**: 0
- **internal_vocab_queries**: 0
- **document_correctness_mean**: None
- **multi_unanswered_n**: 0

## Headline by set (accurate queries only)

| set | n | tokens_to_accurate | turns_to_accurate |
|---|---|---|---|
| quick | 32 | 127540 | 3.0 |

## Tool-error ledger

| kind | count | queries |
|---|---|---|
| cite_failure | 6 | cm-basic-aid-3yr, lk-agr-operating-fy2025, mm-adc-briefing, mm-esa-memo |
| retrieve_error | 1 | cm-basic-aid-3yr |

## Per query

| id | shape | ok | facts | cites ok | cite pass | 1st-try | retr eff | steps | cost |
|---|---|---|---|---|---|---|---|---|---|
| an-ahcccs-enrollment | analyze | ✓ | 0.00 | 0 | — | — | 0.00 | 4 | 0.0034 |
| an-ahcccs-gf-drivers | analyze | ✓ | 1.00 | 3 | 1.00 | 1.00 | 0.15 | 4 | 0.0041 |
| an-esa-growth | analyze | ✓ | 1.00 | 4 | 1.00 | 1.00 | 0.22 | 3 | 0.0089 |
| cm-basic-aid-3yr | comparison | ✓ | 0.67 | 9 | 0.82 | 0.82 | 0.12 | 7 | 0.0278 |
| cm-des-gf-growth | comparison | ✓ | 0.67 | 5 | 1.00 | 1.00 | 0.22 | 12 | 0.0146 |
| cm-highway-construction | comparison | ✓ | 1.00 | 0 | — | — | 0.13 | 4 | 0.0047 |
| cm-supplementals-fy2026 | comparison | ✓ | 0.50 | 0 | — | — | 0.03 | 6 | 0.0085 |
| cm-university-funding-dr | comparison | ✓ | 0.00 | 0 | — | — | 0.00 | 5 | 0.0060 |
| hs-arra-k12-stabilization-2010 | historical | ✓ | 1.00 | 1 | 1.00 | 1.00 | 0.10 | 4 | 0.0022 |
| hs-bsf-draw-2008 | historical | ✓ | 1.00 | 0 | — | — | 0.20 | 2 | 0.0009 |
| hs-full-day-kindergarten-2005 | historical | ✓ | 1.00 | 4 | 1.00 | 1.00 | 0.40 | 3 | 0.0042 |
| hs-fy2010-oneshot-financing | historical | ✓ | 1.00 | 0 | — | — | 0.06 | 3 | 0.0051 |
| hs-leaseback-prisons-2010 | historical | ✓ | 1.00 | 1 | 1.00 | 1.00 | 0.60 | 3 | 0.0017 |
| lk-adc-officer-stipend-fy2026 | lookup | ✓ | 1.00 | 3 | 1.00 | 1.00 | 1.00 | 3 | 0.0015 |
| lk-adc-total-fy2026 | lookup | ✓ | 0.50 | 0 | — | — | 0.00 | 3 | 0.0023 |
| lk-agr-horse-liaison-fy2025 | lookup | ✓ | 1.00 | 0 | — | — | 0.00 | 2 | 0.0030 |
| lk-agr-operating-fy2025 | lookup | ✓ | 0.00 | 2 | 0.67 | 1.00 | 0.20 | 5 | 0.0038 |
| lk-asrs-rate-fy2026 | lookup | ✓ | 1.00 | 0 | — | — | 0.40 | 2 | 0.0013 |
| lk-asu-operating-fy2026 | lookup | ✓ | 1.00 | 0 | — | — | 0.20 | 2 | 0.0015 |
| lk-bsf-balance-fy2026 | lookup | ✓ | 1.00 | 0 | — | — | 0.14 | 5 | 0.0094 |
| lk-djc-juvenile-corrections-fy2025 | lookup | ✓ | 1.00 | 0 | — | — | 0.20 | 2 | 0.0011 |
| lk-dor-revenue-operating-fy2025 | lookup | ✓ | 1.00 | 0 | — | — | 0.20 | 2 | 0.0010 |
| lk-dps-historical-operating-fy2013 | historical | ✓ | 0.00 | 0 | — | — | 0.00 | 4 | 0.0055 |
| lk-dps-operating-fy2026 | lookup | ✓ | 1.00 | 0 | — | — | 0.11 | 3 | 0.0071 |
| lk-eorp-offset | lookup | ✓ | 1.00 | 0 | — | — | 1.00 | 2 | 0.0030 |
| lk-fis-game-and-fish-fy2025 | lookup | ✓ | 0.00 | 0 | — | — | 0.00 | 4 | 0.0028 |
| lk-gam-operating-fy2025 | lookup | ✓ | 1.00 | 1 | 1.00 | 1.00 | 0.09 | 4 | 0.0042 |
| lk-gf-revenue-fy2026 | lookup | ✓ | 1.00 | 0 | — | — | 0.38 | 2 | 0.0012 |
| lk-hurf-split | lookup | ✓ | 1.00 | 4 | 1.00 | 1.00 | 0.26 | 4 | 0.0049 |
| lk-k12-basic-aid-fy2026 | lookup | ✓ | 1.00 | 0 | — | — | 0.20 | 2 | 0.0009 |
| lk-liq-operating-fy2025 | lookup | ✓ | 1.00 | 0 | — | — | 0.20 | 2 | 0.0042 |
| lk-lot-operating-fy2025 | lookup | ✓ | 1.00 | 0 | — | — | 0.20 | 2 | 0.0025 |
| lk-min-operating-fy2025 | lookup | ✓ | 0.00 | 0 | — | — | 0.00 | 3 | 0.0026 |
| lk-nursing-board-operating-fy2025 | lookup | ✓ | 1.00 | 0 | — | — | 0.20 | 2 | 0.0015 |
| lk-prop123-increment | lookup | ✓ | 1.00 | 2 | 1.00 | 1.00 | 1.00 | 3 | 0.0052 |
| lk-psp-operating-fy2025 | lookup | ✓ | 1.00 | 0 | — | — | 0.00 | 2 | 0.0010 |
| lk-roc-operating-fy2025 | lookup | ✓ | 1.00 | 0 | — | — | 0.20 | 3 | 0.0015 |
| lk-scotus-salary | lookup | ✓ | 1.00 | 3 | 1.00 | 1.00 | 0.29 | 3 | 0.0113 |
| lk-sos-secretary-of-state-fy2025 | lookup | ✓ | 1.00 | 0 | — | — | 0.40 | 2 | 0.0022 |
| lk-tou-tourism-fy2026 | lookup | ✓ | 0.00 | 0 | — | — | 0.00 | 2 | 0.0031 |
| lk-uhsc-arizona-health-fy2026 | lookup | ✓ | 0.00 | 1 | 1.00 | 1.00 | 0.12 | 4 | 0.0026 |
| lk-vsc-veterans-services-fy2025 | lookup | ✓ | 1.00 | 0 | — | — | 0.00 | 2 | 0.0017 |
| lk-wat-operating-fy2025 | lookup | ✓ | 1.00 | 0 | — | — | 0.00 | 2 | 0.0012 |
| mm-adc-briefing | memo | ✓ | 1.00 | 3 | 0.60 | 0.60 | 0.40 | 7 | 0.0148 |
| mm-esa-memo | memo | ✓ | 1.00 | 5 | 0.83 | 0.83 | 0.30 | 7 | 0.0070 |

## Hygiene flags

- an-ahcccs-enrollment: false refusal
- cm-des-gf-growth: narration x1
- cm-university-funding-dr: false refusal
- hs-arra-k12-stabilization-2010: narration x1
- hs-fy2010-oneshot-financing: narration x1
- lk-agr-operating-fy2025: narration x1
- lk-dps-historical-operating-fy2013: false refusal
- lk-fis-game-and-fish-fy2025: narration x1, false refusal
- lk-min-operating-fy2025: false refusal
- lk-tou-tourism-fy2026: false refusal
- mm-adc-briefing: narration x1
