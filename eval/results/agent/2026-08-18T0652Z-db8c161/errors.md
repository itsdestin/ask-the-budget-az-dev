# Agent-eval tool errors — 2026-08-18T0652Z-db8c161

## By kind

| kind | count | queries |
|---|---|---|
| cite_failure | 24 | an-ahcccs-gf-drivers, cm-des-gf-growth, lk-adc-total-fy2026, lk-agr-operating-fy2025, lk-asu-operating-fy2026, lk-bsf-balance-fy2026, lk-djc-juvenile-corrections-fy2025, lk-dps-historical-operating-fy2013, lk-gf-revenue-fy2026, lk-k12-basic-aid-fy2026, lk-psp-operating-fy2025, lk-vsc-veterans-services-fy2025, mm-adc-briefing |
| retrieve_error | 3 | cm-basic-aid-3yr, cm-des-gf-growth, lk-dps-historical-operating-fy2013 |

## Per query

- an-ahcccs-gf-drivers turn 5: cite_failure (cite) — {'ok': False, 'error': "quote not found in chunk.text — the substring you supplied as `quote` does not appear verbatim in the chunk. Pick text that exists in the chunk (read the retrieve() result's `t
- cm-basic-aid-3yr turn 1: retrieve_error (retrieve) — spread cannot be combined with intent — spread already decides how many passages come back (groups x per_group). Drop the other argument.
- cm-des-gf-growth turn 3: retrieve_error (retrieve) — filters has unknown key(s) ['page_start']. Valid keys: fiscal_year, doc_type, publisher, agency_canonical_id, fund_canonical_id, is_table.
- cm-des-gf-growth turn 11: cite_failure (cite) — {'ok': False, 'error': "quote appears multiple times in chunk.text (positions: 589, 785). Extend the quote with more surrounding context so it's unique within this chunk.", 'chunk_text_length': 866}
- cm-des-gf-growth turn 11: cite_failure (cite) — {'ok': False, 'error': "quote appears multiple times in chunk.text (positions: 370, 701). Extend the quote with more surrounding context so it's unique within this chunk.", 'chunk_text_length': 834}
- lk-adc-total-fy2026 turn 2: cite_failure (cite) — {'ok': False, 'error': "quote not found in chunk.text — the substring you supplied as `quote` does not appear verbatim in the chunk. Pick text that exists in the chunk (read the retrieve() result's `t
- lk-agr-operating-fy2025 turn 4: cite_failure (cite) — {'ok': False, 'error': "quote not found in chunk.text — the substring you supplied as `quote` does not appear verbatim in the chunk. Pick text that exists in the chunk (read the retrieve() result's `t
- lk-asu-operating-fy2026 turn 4: cite_failure (cite) — {'ok': False, 'error': "quote not found in chunk.text — the substring you supplied as `quote` does not appear verbatim in the chunk. Pick text that exists in the chunk (read the retrieve() result's `t
- lk-bsf-balance-fy2026 turn 3: cite_failure (cite) — {'ok': False, 'error': "quote not found in chunk.text — the substring you supplied as `quote` does not appear verbatim in the chunk. Pick text that exists in the chunk (read the retrieve() result's `t
- lk-bsf-balance-fy2026 turn 3: cite_failure (cite) — {'ok': False, 'error': "quote not found in chunk.text — the substring you supplied as `quote` does not appear verbatim in the chunk. Pick text that exists in the chunk (read the retrieve() result's `t
- lk-bsf-balance-fy2026 turn 3: cite_failure (cite) — {'ok': False, 'error': "quote not found in chunk.text — the substring you supplied as `quote` does not appear verbatim in the chunk. Pick text that exists in the chunk (read the retrieve() result's `t
- lk-bsf-balance-fy2026 turn 3: cite_failure (cite) — {'ok': False, 'error': "quote not found in chunk.text — the substring you supplied as `quote` does not appear verbatim in the chunk. Pick text that exists in the chunk (read the retrieve() result's `t
- lk-djc-juvenile-corrections-fy2025 turn 2: cite_failure (cite) — {'ok': False, 'error': "quote not found in chunk.text — the substring you supplied as `quote` does not appear verbatim in the chunk. Pick text that exists in the chunk (read the retrieve() result's `t
- lk-djc-juvenile-corrections-fy2025 turn 2: cite_failure (cite) — {'ok': False, 'error': "quote appears multiple times in chunk.text (positions: 285, 953, 1416). Extend the quote with more surrounding context so it's unique within this chunk.", 'chunk_text_length': 
- lk-dps-historical-operating-fy2013 turn 0: retrieve_error (retrieve) — arguments were not valid JSON (Expecting ',' delimiter: line 1 column 190 (char 189)). Send the arguments again as a complete JSON object.
- lk-dps-historical-operating-fy2013 turn 3: cite_failure (cite) — {'ok': False, 'error': "quote not found in chunk.text — the substring you supplied as `quote` does not appear verbatim in the chunk. Pick text that exists in the chunk (read the retrieve() result's `t
- lk-gf-revenue-fy2026 turn 1: cite_failure (cite) — {'ok': False, 'error': "quote not found in chunk.text — the substring you supplied as `quote` does not appear verbatim in the chunk. Pick text that exists in the chunk (read the retrieve() result's `t
- lk-gf-revenue-fy2026 turn 1: cite_failure (cite) — {'ok': False, 'error': "quote not found in chunk.text — the substring you supplied as `quote` does not appear verbatim in the chunk. Pick text that exists in the chunk (read the retrieve() result's `t
- lk-k12-basic-aid-fy2026 turn 2: cite_failure (cite) — {'ok': False, 'error': "quote not found in chunk.text — the substring you supplied as `quote` does not appear verbatim in the chunk. Pick text that exists in the chunk (read the retrieve() result's `t
- lk-k12-basic-aid-fy2026 turn 2: cite_failure (cite) — {'ok': False, 'error': "quote not found in chunk.text — the substring you supplied as `quote` does not appear verbatim in the chunk. Pick text that exists in the chunk (read the retrieve() result's `t
- lk-k12-basic-aid-fy2026 turn 2: cite_failure (cite) — {'ok': False, 'error': "quote not found in chunk.text — the substring you supplied as `quote` does not appear verbatim in the chunk. Pick text that exists in the chunk (read the retrieve() result's `t
- lk-k12-basic-aid-fy2026 turn 2: cite_failure (cite) — {'ok': False, 'error': "quote not found in chunk.text — the substring you supplied as `quote` does not appear verbatim in the chunk. Pick text that exists in the chunk (read the retrieve() result's `t
- lk-k12-basic-aid-fy2026 turn 2: cite_failure (cite) — {'ok': False, 'error': "quote not found in chunk.text — the substring you supplied as `quote` does not appear verbatim in the chunk. Pick text that exists in the chunk (read the retrieve() result's `t
- lk-k12-basic-aid-fy2026 turn 2: cite_failure (cite) — {'ok': False, 'error': "quote appears multiple times in chunk.text (positions: 233, 416). Extend the quote with more surrounding context so it's unique within this chunk.", 'chunk_text_length': 496}
- lk-psp-operating-fy2025 turn 2: cite_failure (cite) — {'ok': False, 'error': "quote not found in chunk.text — the substring you supplied as `quote` does not appear verbatim in the chunk. Pick text that exists in the chunk (read the retrieve() result's `t
- lk-vsc-veterans-services-fy2025 turn 2: cite_failure (cite) — {'ok': False, 'error': "quote appears multiple times in chunk.text (positions: 482, 1235, 1671). Extend the quote with more surrounding context so it's unique within this chunk.", 'chunk_text_length':
- mm-adc-briefing turn 4: cite_failure (cite) — {'ok': False, 'error': "quote not found in chunk.text — the substring you supplied as `quote` does not appear verbatim in the chunk. Pick text that exists in the chunk (read the retrieve() result's `t
