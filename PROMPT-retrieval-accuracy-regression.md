# Handoff — the post-backfill retrieval accuracy regression

**Status: ACTIVE.** Written 2026-08-03. Needs a keyed machine (spends money).

You are picking up a **measured, diagnosed, unfixed accuracy regression** in
AI Mode, plus one experiment left running mid-flight.

Read `STATUS.md` first, then this. Do not re-derive what is below — it is
measured, and re-measuring costs money and hours.

---

## 1. The regression

The backfill finished on 2026-08-02: `budget_chunks` went **28,530 → 77,574**,
FY2005–FY2027 (was FY2021–2027). Query understanding shipped in the same
window and took Layer 1 recall@5 from 62% to **88.10%**.

End-to-end answer accuracy went **down**.

Same model, same 31 queries, same judge, only the platform beneath changed:

| metric | before (28.5k corpus) | after (77.5k + query understanding) | |
|---|---|---|---|
| **key_fact_rate** | 0.808 | **0.660** | 🔴 −15 pts |
| cite_pass_rate | 0.837 | 0.986 | ✅ |
| first_try_cite_rate | 0.900 | 0.986 | ✅ |
| citations/answer | 10.1 | 4.5 | ✅ system links figures now |
| filtered_retrieve_rate | 0.246 | 0.403 | ✅ query understanding |
| steps/answer | 4.81 | 3.45 | ✅ |
| input tokens/answer | 138k | 76k | ✅ −45% |
| cost/answer | $0.039 | $0.023 | ✅ −41% |
| wall p95 | 228s | 58s | ✅ −75% |

Runs: `eval/results/agent/2026-08-02T0900Z-0b08221/` (before) and
`eval/results/agent/2026-08-03T0156Z-9a8fd91/` (after).

**Everything improved except the thing that matters most.**

## 2. The diagnosis — already done, do not repeat it

Of the 19 missed key facts in the new run:

- **14 (74%) were never retrieved at all** → retrieval problem
- 5 (26%) were retrieved and the model did not use them → answer problem

So this is overwhelmingly retrieval, not generation.

Reproduce for free at any time (reads recorded transcripts, no model calls):

```bash
uv run python - <<'EOF'
import glob
from eval.agent_schema import load_agent_queries
from eval.agent_scoring import fact_matches
from eval.agent_transcript import read_transcript, final_answer, retrieve_calls
RUN = "eval/results/agent/2026-08-03T0156Z-9a8fd91"
qs = {q.id: q for q in load_agent_queries("eval/agent_queries.yaml")}
never = unused = 0
for f in sorted(glob.glob(f"{RUN}/*-r1.jsonl")):
    t = read_transcript(f); q = qs.get(t.meta.get("query_id"))
    if not q or not q.key_facts: continue
    ans = final_answer(t)
    blob = "\n".join(c.get("text") or ""
                     for call in retrieve_calls(t) for c in call["chunks"])
    for kf in q.key_facts:
        try:
            if fact_matches(kf, ans): continue
            never += 0 if fact_matches(kf, blob) else 1
            unused += 1 if fact_matches(kf, blob) else 0
        except Exception:
            pass
print(f"never retrieved {never}, retrieved-but-unused {unused}")
EOF
```

**Why it happens.** The corpus went from 7 fiscal years to 23, so the right
edition of a document now competes with ~20 other editions for the same
top-k slots. Meanwhile the model still issues **60% of its searches with no
filter at all** (`filtered_retrieve_rate` 0.403). An unfiltered search was
survivable across 7 years; across 23 it is not.

**The Layer 1 / Layer 2 divergence is real and is not a contradiction.**
Layer 1 asks whether one ground-truth chunk lands in top-k for a single
`retrieve()` call. Layer 2 asks whether the agent surfaces the fact across
its whole loop against 2.7× more competition. Layer 1 improving while
Layer 2 fell is exactly the blind spot Layer 2 exists to catch. **Do not
use Layer 1 recall alone to justify a retrieval change from here.**

## 3. How to think about fixing it

The goal is to make the agent narrow its search in a 23-year corpus. Ranked
by expected value against the measured cause:

1. **Make the model filter by fiscal year.** 60% of searches carry no filter.
   Most budget questions name or imply a year. The year parser already exists
   (S21, `inferred_fiscal_years`) — the question is whether inference should
   become a *default filter* rather than a ranking hint when the query names
   a year. Highest leverage: it targets the 74% directly.
2. **A corpus map in the system prompt.** The model does not reliably know
   the corpus now spans FY2005–2027. Generate it from the corpus at startup
   so it cannot drift. Cheap, cached, and it also lets the model refuse
   out-of-range years instantly instead of searching first.
3. **Revisit top_k.** `DEFAULT_PIPELINE_TOP_K` and `INTENT_TOP_K` were tuned
   against a 28.5k corpus. Unchanged, they now sample a third as much of the
   corpus. Measure before changing — more chunks costs tokens, which the
   platform changes just bought back.
4. **Re-check the recency boost.** It was re-calibrated for the finished
   corpus (0.85 / 1.46, commit `013d1a6`), but that calibration used Layer 1.
   Re-check it against Layer 2 key-fact rate now that 23 years compete.

Anything that looks promising: **smoke run → compare → full run**. Never
merge a retrieval change on Layer 1 numbers alone again.

## 4. Left running mid-flight

A head-to-head was in progress when this was written:
**glm-5.2 vs deepseek-v4-flash-0731 as the agent model**, both on the current
corpus/prompt/query set.

- glm baseline: `eval/results/agent/2026-08-03T0156Z-9a8fd91/` — **complete
  and scored**, 31/31, 0 errors, $0.71.
- deepseek: `eval/results/agent/2026-08-03T0242Z-9a8fd91/` — was **14/31**
  when this was written. If it is incomplete, re-run it:

```bash
uv run python -m eval.run_agent_eval --sets quick,multi,deep,refusal \
    --model deepseek/deepseek-v4-flash-0731 --note "head-to-head"
uv run python -m eval.score_agent_run  <run_dir>
uv run python -m eval.judge_agent_run  <run_dir>          # glm-5.2 by default
uv run python -m eval.compare_agent_runs \
    eval/results/agent/2026-08-03T0156Z-9a8fd91 <run_dir>
```

Why it is worth finishing: on the smoke set deepseek cost **$0.034 vs glm's
$0.425** (12×), used filters on 60% of retrieves vs glm's 26%, and had
`cite_pass_rate` 0.97. It is a live candidate for the office Standard tier —
and if it wins, glm-5.2 stops grading its own output, which retires the
self-judging caveat on the judge (§6).

## 5. The eval set is now partly stale

`eval/agent_queries.yaml`'s `historical` queries target FY2022–23 **because
that was the corpus floor when they were authored**. FY2005 onward now
exists, so those five queries no longer test what their name claims. The
citation spec anticipated this and says to re-author them when the backfill
lands. Do that before treating `historical` numbers as meaningful.

Key facts elsewhere in the set were also authored against the 28.5k corpus.
They still exist in the corpus, but a fact that is now one of twenty near
-identical editions is a harder target than the author intended. Worth an
audit pass, not a rewrite.

## 6. Working discipline for this area

- **The judge is `z-ai/glm-5.2`** for everything (Destin, 2026-08-02).
  Evidence and rejected alternatives:
  `docs/superpowers/investigations/2026-08-02-judge-model-comparison.md`.
  Accepted risk: it currently grades its own output.
- **Judge results are not comparable across judge models.** Enforced —
  `compare_agent_runs.py` withholds the judge section when they differ, as
  it does for differing corpus counts and query sets. If a comparison
  refuses, that is the tool working; fix the inputs, do not `--force`.
- **Scoring is free and re-runnable** over recorded transcripts. Diagnose
  before spending. Most of §2 cost nothing.
- **Costs:** full run ≈ $0.71 (glm) / ≈ $0.15 (deepseek); judge pass ≈ $0.08;
  smoke ≈ $0.43 / $0.03. Check the key's remaining limit before a run —
  the *key* cap binds before the account balance does
  (`GET https://openrouter.ai/api/v1/auth/key`).
- `harness/session.py` now caps `MAX_COMPLETION_TOKENS = 16_000`. Without a
  cap, OpenRouter reserves credit for the model's maximum (65,536) and
  refuses requests on a healthy-looking balance. Do not remove it.

## 7. Also open, not part of this regression

- **Citation linking overclaims.** Shipped, then three browser sessions found
  eight defects; five fixed, three fundamental ones open (34.2% of linked
  figures match several documents; a rounded figure falsely links 3.7% of the
  time; `reconcile` asserts "computed from" on figures that are not).
  `docs/superpowers/investigations/2026-08-02-citation-linking-review.md`.
  **Accept future citation work on false-link rate, never on coverage** —
  coverage measures whether a link is produced, not whether it is right, and
  that wrong gate let ~2,000 passing tests miss all of it. A replacement
  design (attested citation linking, A1–A9) and an 11-task plan exist.
- **The mechanical narration lexicon should be deleted.** It caught 1 of 31
  answers where every LLM judge caught 17–21. Keep `token_leak` (a precise
  regex for a specific observed failure). Rely on the judge for narration.
- **Two answers are simply wrong** — `lk-asrs-rate-fy2026` and
  `lk-asu-operating-fy2026`, both flagged `answered_wrong_question`.
