# Agent-eval tool errors — 2026-08-18T0850Z-6a28d03

## By kind

| kind | count | queries |
|---|---|---|
| cite_failure | 6 | cm-basic-aid-3yr, lk-agr-operating-fy2025, mm-adc-briefing, mm-esa-memo |
| retrieve_error | 1 | cm-basic-aid-3yr |

## Per query

- cm-basic-aid-3yr turn 0: retrieve_error (retrieve) — spread cannot be combined with intent — spread already decides how many passages come back (groups x per_group). Drop the other argument.
- cm-basic-aid-3yr turn 6: cite_failure (cite) — {'ok': False, 'error': "quote not found in chunk.text — the substring you supplied as `quote` does not appear verbatim in the chunk. Pick text that exists in the chunk (read the retrieve() result's `t
- cm-basic-aid-3yr turn 6: cite_failure (cite) — {'ok': False, 'error': "quote not found in chunk.text — the substring you supplied as `quote` does not appear verbatim in the chunk. Pick text that exists in the chunk (read the retrieve() result's `t
- lk-agr-operating-fy2025 turn 3: cite_failure (cite) — {'ok': False, 'error': "quote not found in chunk.text — the substring you supplied as `quote` does not appear verbatim in the chunk. Pick text that exists in the chunk (read the retrieve() result's `t
- mm-adc-briefing turn 2: cite_failure (cite) — {'ok': False, 'error': "quote not found in chunk.text — the substring you supplied as `quote` does not appear verbatim in the chunk. Pick text that exists in the chunk (read the retrieve() result's `t
- mm-adc-briefing turn 2: cite_failure (cite) — {'ok': False, 'error': "quote not found in chunk.text — the substring you supplied as `quote` does not appear verbatim in the chunk. Pick text that exists in the chunk (read the retrieve() result's `t
- mm-esa-memo turn 4: cite_failure (cite) — {'ok': False, 'error': "quote not found in chunk.text — the substring you supplied as `quote` does not appear verbatim in the chunk. Pick text that exists in the chunk (read the retrieve() result's `t
