# Agent-eval scores — 2026-08-18T0655Z-db8c161

## Summary

- **n**: 45
- **errors**: 0
- **provider_errors**: 10
- **accurate_n**: 20
- **accurate_rate**: 0.5714
- **tokens_to_accurate_mean**: 1.137e+05
- **turns_to_accurate_mean**: 2.9
- **accurate_headline_by_set**: {'quick': {'n': 20, 'tokens_mean': 113679.3, 'turns_mean': 2.9}}
- **steps_mean**: 3.114
- **retrieve_calls_mean**: 1.857
- **input_tokens_mean**: 7.06e+04
- **output_tokens_mean**: 2445
- **cached_tokens_mean**: 5.649e+04
- **total_cost_usd**: 0.08414
- **cost_missing_queries**: 10
- **cost_mean_usd**: 0.002404
- **key_fact_rate_mean**: 0.619
- **figure_coverage_mean**: 0.8713
- **unverified_rate**: 0.1287
- **marker_coverage_mean**: 0.4836
- **tag_accuracy_mean**: 0.901
- **retrieval_efficiency_mean**: 0.2307
- **retrieves_after_sufficient_mean**: 0.1667
- **retrieves_after_sufficient_n**: 18
- **retrieves_after_sufficient_eligible_queries**: 35
- **retrieve_calls_with_filters**: 53
- **filtered_retrieve_rate**: 0.8154
- **filter_dimension_counts**: {'fiscal_year': 47, 'doc_type': 35, 'publisher': 1, 'agency_canonical_id': 31, 'fund_canonical_id': 0, 'is_table': 8}
- **retrieve_calls_with_intent**: 60
- **retrieve_calls_with_top_k**: 4
- **deep_dive_calls**: 0
- **citations_per_answer_mean**: 1.029
- **cite_pass_rate**: 0.9231
- **first_try_cite_rate**: 0.973
- **retries_per_citation**: 0.05405
- **median_quote_len_mean**: 131
- **refusal_correct_rate**: None
- **false_refusals**: 11
- **narration_hit_queries**: 2
- **token_leaks**: 0
- **internal_vocab_queries**: 0
- **document_correctness_mean**: None
- **multi_unanswered_n**: 0

## Headline by set (accurate queries only)

| set | n | tokens_to_accurate | turns_to_accurate |
|---|---|---|---|
| quick | 20 | 113679 | 2.9 |

## Tool-error ledger

| kind | count | queries |
|---|---|---|
| cite_failure | 3 | cm-supplementals-fy2026, lk-asrs-rate-fy2026, lk-dps-historical-operating-fy2013 |
| crashed_query | 10 | an-ahcccs-enrollment, an-ahcccs-gf-drivers, an-esa-growth, hs-arra-k12-stabilization-2010, hs-bsf-draw-2008, hs-full-day-kindergarten-2005, hs-fy2010-oneshot-financing, hs-leaseback-prisons-2010, mm-adc-briefing, mm-esa-memo |
| retrieve_error | 2 | cm-basic-aid-3yr, cm-highway-construction |

## Per query

| id | shape | ok | facts | cites ok | cite pass | 1st-try | retr eff | steps | cost |
|---|---|---|---|---|---|---|---|---|---|
| an-ahcccs-enrollment | analyze | ✗ | 0.00 | 0 | — | — | — | 4 | — |
| an-ahcccs-gf-drivers | analyze | ✗ | 0.00 | 0 | — | — | — | 3 | — |
| an-esa-growth | analyze | ✗ | 0.00 | 0 | — | — | — | 6 | — |
| cm-basic-aid-3yr | comparison | ✓ | 1.00 | 6 | 1.00 | 1.00 | 0.43 | 5 | 0.0046 |
| cm-des-gf-growth | comparison | ✓ | 0.67 | 0 | — | — | 0.06 | 6 | 0.0053 |
| cm-highway-construction | comparison | ✓ | 0.00 | 0 | — | — | 0.00 | 4 | 0.0038 |
| cm-supplementals-fy2026 | comparison | ✓ | 0.00 | 10 | 0.91 | 0.91 | 0.26 | 7 | 0.0075 |
| cm-university-funding-dr | comparison | ✓ | 0.00 | 0 | — | — | 0.00 | 3 | 0.0020 |
| hs-arra-k12-stabilization-2010 | historical | ✗ | 0.00 | 0 | — | — | — | 1 | — |
| hs-bsf-draw-2008 | historical | ✗ | 0.00 | 0 | — | — | — | 1 | — |
| hs-full-day-kindergarten-2005 | historical | ✗ | 0.00 | 0 | — | — | — | 1 | — |
| hs-fy2010-oneshot-financing | historical | ✗ | 0.00 | 0 | — | — | — | 1 | — |
| hs-leaseback-prisons-2010 | historical | ✗ | 0.00 | 0 | — | — | — | 1 | — |
| lk-adc-officer-stipend-fy2026 | lookup | ✓ | 1.00 | 4 | 1.00 | 1.00 | 0.60 | 3 | 0.0019 |
| lk-adc-total-fy2026 | lookup | ✓ | 1.00 | 0 | — | — | 0.00 | 4 | 0.0046 |
| lk-agr-horse-liaison-fy2025 | lookup | ✓ | 1.00 | 1 | 1.00 | 1.00 | 0.20 | 3 | 0.0012 |
| lk-agr-operating-fy2025 | lookup | ✓ | 0.00 | 0 | — | — | 0.00 | 2 | 0.0028 |
| lk-asrs-rate-fy2026 | lookup | ✓ | 1.00 | 4 | 0.80 | 1.00 | 0.60 | 4 | 0.0021 |
| lk-asu-operating-fy2026 | lookup | ✓ | 1.00 | 0 | — | — | 0.17 | 2 | 0.0024 |
| lk-bsf-balance-fy2026 | lookup | ✓ | 1.00 | 0 | — | — | 0.11 | 3 | 0.0013 |
| lk-djc-juvenile-corrections-fy2025 | lookup | ✓ | 1.00 | 0 | — | — | 0.20 | 2 | 0.0016 |
| lk-dor-revenue-operating-fy2025 | lookup | ✓ | 0.00 | 0 | — | — | 0.00 | 2 | 0.0010 |
| lk-dps-historical-operating-fy2013 | historical | ✓ | 1.00 | 2 | 0.67 | 1.00 | 0.40 | 4 | 0.0026 |
| lk-dps-operating-fy2026 | lookup | ✓ | 0.00 | 1 | 1.00 | 1.00 | 0.08 | 4 | 0.0028 |
| lk-eorp-offset | lookup | ✓ | 1.00 | 0 | — | — | 1.00 | 2 | 0.0008 |
| lk-fis-game-and-fish-fy2025 | lookup | ✓ | 0.00 | 0 | — | — | 0.00 | 3 | 0.0016 |
| lk-gam-operating-fy2025 | lookup | ✓ | 0.00 | 0 | — | — | 0.00 | 2 | 0.0016 |
| lk-gf-revenue-fy2026 | lookup | ✓ | 1.00 | 0 | — | — | 0.40 | 2 | 0.0020 |
| lk-hurf-split | lookup | ✓ | 1.00 | 3 | 1.00 | 1.00 | 0.26 | 4 | 0.0043 |
| lk-k12-basic-aid-fy2026 | lookup | ✓ | 1.00 | 0 | — | — | 0.11 | 3 | 0.0017 |
| lk-liq-operating-fy2025 | lookup | ✓ | 1.00 | 0 | — | — | 0.20 | 2 | 0.0009 |
| lk-lot-operating-fy2025 | lookup | ✓ | 1.00 | 0 | — | — | 0.20 | 2 | 0.0009 |
| lk-min-operating-fy2025 | lookup | ✓ | 1.00 | 0 | — | — | 0.00 | 3 | 0.0031 |
| lk-nursing-board-operating-fy2025 | lookup | ✓ | 0.00 | 0 | — | — | 0.00 | 3 | 0.0018 |
| lk-prop123-increment | lookup | ✓ | 1.00 | 4 | 1.00 | 1.00 | 1.00 | 3 | 0.0020 |
| lk-psp-operating-fy2025 | lookup | ✓ | 1.00 | 0 | — | — | 0.00 | 2 | 0.0021 |
| lk-roc-operating-fy2025 | lookup | ✓ | 1.00 | 0 | — | — | 0.40 | 2 | 0.0026 |
| lk-scotus-salary | lookup | ✓ | 1.00 | 1 | 1.00 | 1.00 | 1.00 | 3 | 0.0013 |
| lk-sos-secretary-of-state-fy2025 | lookup | ✓ | 1.00 | 0 | — | — | 0.40 | 2 | 0.0017 |
| lk-tou-tourism-fy2026 | lookup | ✓ | 0.00 | 0 | — | — | 0.00 | 2 | 0.0020 |
| lk-uhsc-arizona-health-fy2026 | lookup | ✓ | 0.00 | 0 | — | — | 0.00 | 5 | 0.0026 |
| lk-vsc-veterans-services-fy2025 | lookup | ✓ | 0.00 | 0 | — | — | 0.00 | 4 | 0.0028 |
| lk-wat-operating-fy2025 | lookup | ✓ | 0.00 | 0 | — | — | 0.00 | 2 | 0.0009 |
| mm-adc-briefing | memo | ✗ | 0.00 | 0 | — | — | — | 2 | — |
| mm-esa-memo | memo | ✗ | 0.00 | 0 | — | — | — | 1 | — |

## Hygiene flags

- cm-des-gf-growth: narration x1
- cm-highway-construction: false refusal
- cm-university-funding-dr: false refusal
- lk-agr-operating-fy2025: false refusal
- lk-dor-revenue-operating-fy2025: false refusal
- lk-fis-game-and-fish-fy2025: false refusal
- lk-gam-operating-fy2025: false refusal
- lk-k12-basic-aid-fy2026: narration x1
- lk-nursing-board-operating-fy2025: false refusal
- lk-tou-tourism-fy2026: false refusal
- lk-uhsc-arizona-health-fy2026: false refusal
- lk-vsc-veterans-services-fy2025: false refusal
- lk-wat-operating-fy2025: false refusal
