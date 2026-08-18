# Agent-eval scores — 2026-08-18T0652Z-db8c161

## Summary

- **n**: 45
- **errors**: 0
- **accurate_n**: 26
- **accurate_rate**: 0.5778
- **tokens_to_accurate_mean**: 2.303e+05
- **turns_to_accurate_mean**: 4.731
- **accurate_headline_by_set**: {'quick': {'n': 26, 'tokens_mean': 230342.15384615384, 'turns_mean': 4.730769230769231}}
- **steps_mean**: 4.822
- **retrieve_calls_mean**: 2.644
- **input_tokens_mean**: 1.275e+05
- **output_tokens_mean**: 2859
- **cached_tokens_mean**: 1.101e+05
- **total_cost_usd**: 2.196
- **cost_missing_queries**: 0
- **cost_mean_usd**: 0.04879
- **key_fact_rate_mean**: 0.7593
- **figure_coverage_mean**: 0.8132
- **unverified_rate**: 0.1868
- **marker_coverage_mean**: 0.6029
- **tag_accuracy_mean**: 0.851
- **retrieval_efficiency_mean**: 0.3253
- **retrieves_after_sufficient_mean**: 1.061
- **retrieves_after_sufficient_n**: 33
- **retrieves_after_sufficient_eligible_queries**: 45
- **retrieve_calls_with_filters**: 64
- **filtered_retrieve_rate**: 0.5378
- **filter_dimension_counts**: {'fiscal_year': 57, 'doc_type': 47, 'publisher': 0, 'agency_canonical_id': 48, 'fund_canonical_id': 4, 'is_table': 6}
- **retrieve_calls_with_intent**: 95
- **retrieve_calls_with_top_k**: 52
- **deep_dive_calls**: 0
- **citations_per_answer_mean**: 4.711
- **cite_pass_rate**: 0.8983
- **first_try_cite_rate**: 0.9372
- **retries_per_citation**: 0.0583
- **median_quote_len_mean**: 145.4
- **refusal_correct_rate**: None
- **false_refusals**: 3
- **narration_hit_queries**: 6
- **token_leaks**: 0
- **internal_vocab_queries**: 0
- **document_correctness_mean**: None
- **multi_unanswered_n**: 0

## Headline by set (accurate queries only)

| set | n | tokens_to_accurate | turns_to_accurate |
|---|---|---|---|
| quick | 26 | 230342 | 4.7 |

## Tool-error ledger

| kind | count | queries |
|---|---|---|
| cite_failure | 24 | an-ahcccs-gf-drivers, cm-des-gf-growth, lk-adc-total-fy2026, lk-agr-operating-fy2025, lk-asu-operating-fy2026, lk-bsf-balance-fy2026, lk-djc-juvenile-corrections-fy2025, lk-dps-historical-operating-fy2013, lk-gf-revenue-fy2026, lk-k12-basic-aid-fy2026, lk-psp-operating-fy2025, lk-vsc-veterans-services-fy2025, mm-adc-briefing |
| retrieve_error | 3 | cm-basic-aid-3yr, cm-des-gf-growth, lk-dps-historical-operating-fy2013 |

## Per query

| id | shape | ok | facts | cites ok | cite pass | 1st-try | retr eff | steps | cost |
|---|---|---|---|---|---|---|---|---|---|
| an-ahcccs-enrollment | analyze | ✓ | 0.50 | 18 | 1.00 | 1.00 | 0.21 | 4 | 0.0685 |
| an-ahcccs-gf-drivers | analyze | ✓ | 1.00 | 12 | 0.92 | 1.00 | 0.26 | 6 | 0.1064 |
| an-esa-growth | analyze | ✓ | 1.00 | 22 | 1.00 | 1.00 | 0.45 | 4 | 0.0550 |
| cm-basic-aid-3yr | comparison | ✓ | 0.00 | 7 | 1.00 | 1.00 | 0.15 | 5 | 0.0604 |
| cm-des-gf-growth | comparison | ✓ | 0.67 | 22 | 0.92 | 0.91 | 0.38 | 14 | 0.1728 |
| cm-highway-construction | comparison | ✓ | 1.00 | 0 | — | — | 0.09 | 10 | 0.0871 |
| cm-supplementals-fy2026 | comparison | ✓ | 0.50 | 20 | 1.00 | 1.00 | 0.33 | 5 | 0.0753 |
| cm-university-funding-dr | comparison | ✓ | 0.00 | 2 | 1.00 | 1.00 | 0.04 | 6 | 0.0577 |
| hs-arra-k12-stabilization-2010 | historical | ✓ | 1.00 | 6 | 1.00 | 1.00 | 0.20 | 3 | 0.0111 |
| hs-bsf-draw-2008 | historical | ✓ | 1.00 | 3 | 1.00 | 1.00 | 0.20 | 4 | 0.0190 |
| hs-full-day-kindergarten-2005 | historical | ✓ | 1.00 | 5 | 1.00 | 1.00 | 0.40 | 3 | 0.0129 |
| hs-fy2010-oneshot-financing | historical | ✓ | 1.00 | 5 | 1.00 | 1.00 | 0.40 | 3 | 0.0212 |
| hs-leaseback-prisons-2010 | historical | ✓ | 1.00 | 6 | 1.00 | 1.00 | 1.00 | 3 | 0.0287 |
| lk-adc-officer-stipend-fy2026 | lookup | ✓ | 1.00 | 3 | 1.00 | 1.00 | 0.40 | 3 | 0.0226 |
| lk-adc-total-fy2026 | lookup | ✓ | 0.50 | 1 | 0.50 | 0.50 | 0.07 | 5 | 0.0313 |
| lk-agr-horse-liaison-fy2025 | lookup | ✓ | 0.00 | 1 | 1.00 | 1.00 | 0.20 | 3 | 0.0416 |
| lk-agr-operating-fy2025 | lookup | ✓ | 1.00 | 2 | 0.67 | 0.67 | 0.20 | 8 | 0.0850 |
| lk-asrs-rate-fy2026 | lookup | ✓ | 1.00 | 0 | — | — | 0.40 | 2 | 0.0088 |
| lk-asu-operating-fy2026 | lookup | ✓ | 0.50 | 2 | 0.67 | 0.67 | 0.25 | 6 | 0.0511 |
| lk-bsf-balance-fy2026 | lookup | ✓ | 1.00 | 2 | 0.33 | 0.67 | 0.12 | 7 | 0.0416 |
| lk-djc-juvenile-corrections-fy2025 | lookup | ✓ | 1.00 | 4 | 0.67 | 0.75 | 0.27 | 6 | 0.0495 |
| lk-dor-revenue-operating-fy2025 | lookup | ✓ | 0.00 | 2 | 1.00 | 1.00 | 0.20 | 3 | 0.0325 |
| lk-dps-historical-operating-fy2013 | historical | ✓ | 1.00 | 2 | 0.67 | 0.67 | 0.13 | 5 | 0.0480 |
| lk-dps-operating-fy2026 | lookup | ✓ | 0.00 | 0 | — | — | 0.00 | 2 | 0.0364 |
| lk-eorp-offset | lookup | ✓ | 1.00 | 4 | 1.00 | 1.00 | 1.00 | 3 | 0.0276 |
| lk-fis-game-and-fish-fy2025 | lookup | ✓ | 1.00 | 2 | 1.00 | 1.00 | 0.27 | 7 | 0.0827 |
| lk-gam-operating-fy2025 | lookup | ✓ | 1.00 | 3 | 1.00 | 1.00 | 0.29 | 6 | 0.0851 |
| lk-gf-revenue-fy2026 | lookup | ✓ | 1.00 | 6 | 0.75 | 0.86 | 0.60 | 4 | 0.0383 |
| lk-hurf-split | lookup | ✓ | 1.00 | 4 | 1.00 | 1.00 | 0.60 | 4 | 0.0339 |
| lk-k12-basic-aid-fy2026 | lookup | ✓ | 1.00 | 5 | 0.45 | 0.56 | 0.21 | 11 | 0.1043 |
| lk-liq-operating-fy2025 | lookup | ✓ | 1.00 | 0 | — | — | 0.11 | 3 | 0.0221 |
| lk-lot-operating-fy2025 | lookup | ✓ | 1.00 | 4 | 1.00 | 1.00 | 0.80 | 3 | 0.0293 |
| lk-min-operating-fy2025 | lookup | ✓ | 1.00 | 2 | 1.00 | 1.00 | 0.11 | 6 | 0.0538 |
| lk-nursing-board-operating-fy2025 | lookup | ✓ | 1.00 | 3 | 1.00 | 1.00 | 0.22 | 4 | 0.0157 |
| lk-prop123-increment | lookup | ✓ | 1.00 | 3 | 1.00 | 1.00 | 1.00 | 3 | 0.0126 |
| lk-psp-operating-fy2025 | lookup | ✓ | 1.00 | 1 | 0.50 | 0.50 | 0.40 | 4 | 0.0409 |
| lk-roc-operating-fy2025 | lookup | ✓ | 1.00 | 0 | — | — | 0.20 | 2 | 0.0119 |
| lk-scotus-salary | lookup | ✓ | 1.00 | 3 | 1.00 | 1.00 | 0.80 | 3 | 0.0273 |
| lk-sos-secretary-of-state-fy2025 | lookup | ✓ | 0.00 | 0 | — | — | 0.00 | 3 | 0.0104 |
| lk-tou-tourism-fy2026 | lookup | ✓ | 0.00 | 0 | — | — | 0.00 | 6 | 0.0858 |
| lk-uhsc-arizona-health-fy2026 | lookup | ✓ | 0.00 | 1 | 1.00 | 1.00 | 0.10 | 5 | 0.0475 |
| lk-vsc-veterans-services-fy2025 | lookup | ✓ | 1.00 | 3 | 0.75 | 1.00 | 0.40 | 4 | 0.0453 |
| lk-wat-operating-fy2025 | lookup | ✓ | 1.00 | 0 | — | — | 0.12 | 5 | 0.0228 |
| mm-adc-briefing | memo | ✓ | 0.50 | 9 | 0.90 | 1.00 | 0.73 | 5 | 0.0873 |
| mm-esa-memo | memo | ✓ | 1.00 | 12 | 1.00 | 1.00 | 0.34 | 6 | 0.0868 |

## Hygiene flags

- cm-basic-aid-3yr: narration x1
- cm-highway-construction: narration x1
- cm-supplementals-fy2026: narration x1
- lk-agr-horse-liaison-fy2025: narration x1
- lk-dps-operating-fy2026: false refusal
- lk-fis-game-and-fish-fy2025: narration x1
- lk-lot-operating-fy2025: narration x1
- lk-sos-secretary-of-state-fy2025: false refusal
- lk-tou-tourism-fy2026: false refusal
