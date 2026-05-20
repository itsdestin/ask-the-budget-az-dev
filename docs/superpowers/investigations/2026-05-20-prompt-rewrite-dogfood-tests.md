# Prompt-rewrite dogfood test plan

After landing the 2026-05-20 system-prompt rewrite (Tasks 11, 12, 6),
verify these in a live YouCoded session against the budget app.

## Lookup test

Ask: *"What was ADC's FY 2027 General Fund baseline appropriation?"*

Expected:
- Answer opens with "**Quick lookup:**"
- One specific number, 1–3 sentences, 1–3 cites
- No bullets, no "Sources:" section, no preamble
- No internal vocabulary in prose ("retrieve", "chunk_id", etc.)
- No canonical_ids in prose ("agency:adc", "fund:gf")

## Compare test

Ask: *"How does Governor's FY 2027 recommendation for ADC compare to
JLBC's baseline for the same year?"*

Expected:
- Answer opens with "**Comparison:**"
- Side-by-side table OR two paragraphs (Governor / JLBC)
- 4–8 cites
- Plain English agency names (no canonical_ids)

## Analysis test

Ask: *"Tell me about AHCCCS's FY 2027 budget — what should I know?"*

Expected:
- Answer opens with "**Analysis:**"
- Multiple sections (overview, fund-by-fund, changes from prior year)
- 10+ cites
- Still no internal vocabulary in prose

## Recovery silence test

Ask a question with a confusing agency abbreviation (e.g., ask about
"Game and Fish" without saying Arizona Game and Fish Department).

Expected:
- The model silently calls list_filter_values to find the right slug
- The model retries retrieve() with the corrected slug
- The answer mentions ONLY the agency in plain English ("Arizona Game
   and Fish Department"), never the slug or the recovery step

## Refusal test

Ask: *"What's the Aviation Fund balance for FY 2022?"* (out of corpus
coverage).

Expected:
- Refusal text names documents and years ("the corpus currently
   covers FY 2025 onward"), not tools
- No internal vocabulary

## Bridge-offline test

Stop the FastAPI sidecar (`Ctrl-C` it) and ask a budget question.

Expected:
- The system-health banner appears at the top of the chat (Task 14)
- If the model tries to retrieve() and the call fails, it says once:
   "The retrieval service appears to be offline." Then stops. No
   retry narration.

## Sign-off

After each test, paste the FULL assistant answer (no editing) into
this file under a header like `### 2026-05-21 lookup answer`. Compare
against the expected behavior. If any expected behavior fails, file
the gap as a follow-up task.
