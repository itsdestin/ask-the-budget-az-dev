# Agent-eval tool errors — 2026-08-18T0655Z-db8c161

## By kind

| kind | count | queries |
|---|---|---|
| cite_failure | 3 | cm-supplementals-fy2026, lk-asrs-rate-fy2026, lk-dps-historical-operating-fy2013 |
| crashed_query | 10 | an-ahcccs-enrollment, an-ahcccs-gf-drivers, an-esa-growth, hs-arra-k12-stabilization-2010, hs-bsf-draw-2008, hs-full-day-kindergarten-2005, hs-fy2010-oneshot-financing, hs-leaseback-prisons-2010, mm-adc-briefing, mm-esa-memo |
| retrieve_error | 2 | cm-basic-aid-3yr, cm-highway-construction |

## Per query

- an-ahcccs-enrollment turn -1: crashed_query () — terminal frame not _done
- an-ahcccs-gf-drivers turn -1: crashed_query () — terminal frame not _done
- an-esa-growth turn -1: crashed_query () — terminal frame not _done
- cm-basic-aid-3yr turn 0: retrieve_error (retrieve) — spread cannot be combined with intent — spread already decides how many passages come back (groups x per_group). Drop the other argument.
- cm-highway-construction turn 1: retrieve_error (retrieve) — spread cannot be combined with intent — spread already decides how many passages come back (groups x per_group). Drop the other argument.
- cm-supplementals-fy2026 turn 4: cite_failure (cite) — {'ok': False, 'error': "quote not found in chunk.text — the substring you supplied as `quote` does not appear verbatim in the chunk. Pick text that exists in the chunk (read the retrieve() result's `t
- hs-arra-k12-stabilization-2010 turn -1: crashed_query () — terminal frame not _done
- hs-bsf-draw-2008 turn -1: crashed_query () — terminal frame not _done
- hs-full-day-kindergarten-2005 turn -1: crashed_query () — terminal frame not _done
- hs-fy2010-oneshot-financing turn -1: crashed_query () — terminal frame not _done
- hs-leaseback-prisons-2010 turn -1: crashed_query () — terminal frame not _done
- lk-asrs-rate-fy2026 turn 1: cite_failure (cite) — {'ok': False, 'error': "quote not found in chunk.text — the substring you supplied as `quote` does not appear verbatim in the chunk. Pick text that exists in the chunk (read the retrieve() result's `t
- lk-dps-historical-operating-fy2013 turn 1: cite_failure (cite) — {'ok': False, 'error': "quote appears multiple times in chunk.text (positions: 535, 700). Extend the quote with more surrounding context so it's unique within this chunk.", 'chunk_text_length': 865}
- mm-adc-briefing turn -1: crashed_query () — terminal frame not _done
- mm-esa-memo turn -1: crashed_query () — terminal frame not _done
