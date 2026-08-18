# Handoff — Consolidated Eval Pipeline: iteration on UI/flow, query sets, test runs

**Prepared:** 2026-08-18 · **Branch:** `consolidated-eval-pipeline` (27 commits, **not merged, not pushed**)
**For:** Destin — further iteration on the eval UI/flow, the remaining query sets (multi, quick growth/tuning), and test runs.

---

## TL;DR — where things stand

The consolidated eval pipeline is **built, code-reviewed, and works end-to-end**, on a feature branch. A 15-question paid smoke run proved it (73.3% accurate, $0.44). The report auto-opens as a styled HTML site at the end of every run. The remaining work is: **merge the branch**, **author the multi set**, **run the full 45-question baseline**, and **any UI/flow iteration you want on the report**.

---

## The one-command workflow (this is what you'll do most)

```bash
# Run the eval (spends money), then it scores, judges, and OPENS the report:
uv run python -m eval.run_full_layer2 --sets quick,multi,refusal --workers 4

# Regenerate/reopen any past run's report without re-running the model:
uv run python -m eval.report_bundle eval/results/agent/<run-dir>
```

- Report lives at `eval/results/agent/<run>/report/index.html` (auto-opened).
- Cheap iteration: leave `deep` out of `--sets` (each deep query ~$2–3; quick ~$0.01 each).
- Judge is a second charge — `run_full_layer2` judges by default; `--skip-judge` to skip.

## The report — what it is and how to iterate on it

`eval/report_bundle.py` builds a **self-contained styled HTML site** per run:

- `index.html` — headline metric cards (accurate rate, tokens/turns-to-accurate, cite pass, judge means) with **hover tooltips** explaining each stat; full per-query table (every metric) that is **click-to-sort**; **hover a query id to see its full user message**; tool-error ledger.
- `per-query/<id>.html` — metrics, judge review (holistic, chunk_relevance, ✓/✗ load-bearing claims, flags), and the **conversation rendered with the LIVE app's chat classes** (navy user bubble, white assistant bubbles, tool cards for retrieve/cite, citation pills).

**Key implementation notes for iterating on it:**
- The app styling is **ported** (not imported): the CSS in `report_bundle.py` copies the class vocabulary + tokens from `webapp/src/styles/app.css` / `tokens.css` (`.chat-turn`, `.chat-user-bubble`, `.chat-bubble`, `.chat-tool`, `.chat-cite-pill`, etc.). If the app's chat styling changes, update the ported block in `report_bundle.py` to match.
- Conversation reconstruction: transcripts stream deltas; some models re-emit growing prefixes, so the **readable message is the LAST delta of a phase**. A tool call with no preceding deltas = the model went straight to the tool. There is deliberately NO separate "final answer" section — the last bubble IS the answer.
- Client-side markdown renderer (`md()` in the JS) handles bold/tables/code/lists; no server dependency (static folder).
- `--no-open` builds without launching the browser.

## The query set — current state

**53 queries: quick 45 / deep 3 / refusal 5 / multi 0.**

| Set | Count | Notes |
|---|---|---|
| quick | 45 | Diversified (niche agencies: Agriculture, Lottery, Gaming, Registrar, Liquor, Mine Inspector, Water Resources, State Parks, Game & Fish, Secretary of State, Juvenile Corrections, Tourism, Veterans, Nursing Board, Revenue, UA Health Sciences; FY2025 + FY2013 historical). All **solvable** (0 presence misses). |
| deep | 3 | General Fund revenue seed + structural + tax-cut. Expensive (~$2–3 each). |
| refusal | 5 | Federal/other-state/city/county/future-FY — must refuse. |
| **multi** | **0** | **DEFERRED follow-up — needs authoring.** |

**Verification:** `uv run python scripts/verify_agent_query.py --all` — free, checks every key fact is present in the corpus (0 misses currently). **Re-run after any query edit.**

**Authoring rules (machine-checked):** every query needs `set:` (required), `shape`, `key_facts` (currency/regex — never a parenthesized negative, the scorer raises), non-empty `judge_notes`, `set: deep` queries must carry ≥1 key fact. See `tests/test_eval_agent_queries.py`.

## Open items (in priority order)

1. **Merge the branch to master** (`consolidated-eval-pipeline`, 27 commits). Everything is reviewed + green (3259 pytest). Nothing is pushed — the whole branch sits locally. Merge + push per CLAUDE.md, then close any dev server.
2. **Author the multi set** (~10 queries): `mt-` id prefix, spans 2–3 narrow agencies × 2–3 fiscal years, hand-pinned `correct_response_docs` (exact doc_ids from the corpus — `ChunkStore().scan(...)`), `set: multi`, verified present + reachable. Decoy: cite the Baseline when the question asks what was appropriated → must cite the Approps Report. This is the `document_correctness` axis's whole reason to exist.
3. **Run the full 45-question quick baseline** (~$1.50 + judge) — gives the real headline numbers (accurate rate, tokens/turns-to-accurate over all 45). The smoke run (15 queries) is the only paid data so far: 73.3% accurate, key_fact_rate 0.83, cite pass 94.6%, holistic 3.4, chunk_relevance 0.78, $0.44.
4. **Re-confirm a handful of anchors** — a few quick queries were re-pinned to real corpus figures; a full baseline will tell you if any wording needs tightening (the smoke's 4 misses: `an-ahcccs-enrollment` pin looked wrong, `cm-university-funding-dr` searched 10× without converging, `cm-supplementals-fy2026` over-cited, `lk-sos-secretary-of-state-fy2025` found the fact but cited nothing — the honesty gate working).

## Honest caveats a future session must know

- **The reachability check was once vacuous.** `scripts/verify_agent_query.py`'s reachability leg (does a single top-20 `retrieve()` of the bare question surface the fact?) silently passed for 62 queries due to a bug (raw string passed to `retrieve()`, which needs `RetrievalRequest`). **Fixed 2026-08-16.** Presence (full-corpus scan) was always genuine. The remaining "reachability misses" are facts that exist but need retrieval effort — that is the AGENT's job, scored on the agent axis, NOT a query defect. Don't "fix" them by loosening the verifier to silence it; the WARN is honest signal.
- **Year/doc-type filters do NOT help reachability** (measured: year filter changed 0/42). The agent-built-filters idea was tested cheap and dropped. Don't rebuild it without new evidence.
- **Wall-clock is not a metric** (Destin's call — network/machine-load dominated). Headline is tokens/turns-to-accurate.
- **The `--subset`/smoke/full/dr-probe mechanism is retired** — any doc telling you to use it is stale (this handoff scrubbed the live ones).
- **Raw transcripts are gitignored** (full chunk text); scores/judge/report HTML are committed. `report/per-query/*.jsonl` copies are now gitignored too.

## Key files

| File | What |
|---|---|
| `eval/run_full_layer2.py` | The orchestrator: run → score → judge → report (auto-opens) |
| `eval/report_bundle.py` | The HTML report builder (iterate here for UI/flow) |
| `eval/agent_queries.yaml` | The 53 queries (author here) |
| `eval/agent_schema.py` | Query schema (`set:` required, `correct_response_docs`) |
| `eval/agent_scoring.py` | Mechanical scorer (headline, axes) |
| `scripts/verify_agent_query.py` | Free corpus verification (`--all`, `--id <qid>`) |
| `eval/results/agent/2026-08-17T2324Z-88f90b3/` | The smoke run (report committed) |
| `docs/superpowers/specs/2026-08-16-consolidated-eval-pipeline-design.md` | The spec |
| `docs/superpowers/plans/2026-08-16-consolidated-eval-pipeline.md` | The plan |
| `docs/superpowers/plans/2026-08-16-eval-query-inventory.md` | Query inventory + scoring guide |

## The smoke run's report (your reference example)

Open `eval/results/agent/2026-08-17T2324Z-88f90b3/report/index.html` — it shows the full styling: hover tooltips, sortable table, query-hover previews, and per-query pages with the app-class conversation. Use it as the visual baseline for UI iteration.
