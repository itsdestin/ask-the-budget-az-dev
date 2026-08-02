# Judge model comparison — can a cheaper model grade the Layer 2 eval?

**Date:** 2026-08-02
**Question:** the judge is `anthropic/claude-sonnet-5` at $2/$10 per M. Can a
cheaper model do the job, so we can afford far more eval runs?
**Answer: yes — `z-ai/glm-5.2`. Destin's call, 2026-08-02: it judges
everything from now on, sonnet-5 is retired as a judge.** The two deepseek
configurations were rejected; glm-5.2 tracks sonnet closely at ~8x less.

All runs judge the SAME 31 recorded answers
(`eval/results/agent/2026-08-02T0900Z-0b08221/`), so differences are the
judge and nothing else. Per-judge outputs are committed beside the run as
`judge-<model>.json`; `judge.json` is the canonical grading and now holds
the glm-5.2 pass.

## Results

| | sonnet-5 | **glm-5.2 (adopted)** | deepseek-v4-flash-0731 (reasoning off) | deepseek-v4-flash-0731 (reasoning on) |
|---|---|---|---|---|
| errors | 0 | **0** | 0 | **8 of 31** |
| holistic mean | 4.06 | **4.13** | 4.58 | 3.96 |
| **weak answers caught (≤3)** | 9 of 9 | **5 of 9** | **1 of 9** | 3 of 5 comparable |
| `answered_wrong_question` | 2 | 1 | **0** | — |
| load-bearing claims found | 135 | **144 (1.07×)** | 0.84× | 0.78× |
| latency / query | ~10 s | ~15 s | 4 s | 59 s |
| cost / 31-query pass | ~$0.60 | **~$0.08** | ~$0.03 | ~$0.08 |

## Why glm-5.2 was adopted

Every disagreement with sonnet is **within one point** (31/31), rank
correlation 0.89, and it identifies slightly MORE load-bearing claims than
sonnet (1.07x) where both deepseek configs found 16-22% fewer. That last
number is what makes `claim_coverage_*` keep roughly its old meaning.

It caught 5 of the 9 answers sonnet graded weak; the 4 it missed all sit on
the 3-vs-4 boundary rather than being wild misreads.

**Accepted risk, stated plainly:** glm-5.2 is currently also the model under
test, so it grades its own output, and generosity at the weak-answer
threshold is the shape self-evaluation bias takes. Its overall mean (4.13 vs
4.06) argues against a strong effect, but this data cannot separate "glm is
slightly lenient" from "glm is lenient about glm". The confound disappears
if the agent tier moves off glm-5.2.

## Why the deepseek options failed

**Reasoning off — misses the problems.** It caught 1 of the 9 answers
sonnet graded ≤3, and zero of the 2 it flagged as answering the wrong
question. It grades higher than sonnet on 15 queries and lower on 1:
systematic leniency, not noise. A judge that reports a regression as fine
is worse than no judge, because it is trusted.

**Reasoning on — cannot finish.** It judges far better (60% weak-answer
recall vs 11%, and slightly harsher than sonnet overall) but exhausts
`max_tokens=8000` on 8 of 31 queries, losing 26% of the sample. Raising the
cap trades away the latency that made it attractive: it already takes 59 s
per query, i.e. ~30 minutes per pass against sonnet's ~5.

Both find materially fewer load-bearing claims than sonnet (0.78–0.84×),
which shifts `claim_coverage_precision` for reasons unrelated to the agent
under test — so judge results are **not comparable across judge models**.

## A real bug this surfaced, now fixed

The first deepseek run failed on 5 of 31 queries with
`AttributeError: 'NoneType' object has no attribute 'strip'`.

That was **our** defect, not the model's. `deepseek-v4-flash-0731` is a
reasoning model: it spends completion tokens thinking before answering, and
`judge_one` set no `max_tokens`, so the provider default cut it off
mid-thought — `finish_reason: "length"`, `content: null`, grade lost.

Fixed in `eval/judge_agent_run.py`:
- `JUDGE_MAX_TOKENS = 8000`, leaving room for reasoning *and* the JSON.
- A null `content` now raises a message naming the real cause.
- `--no-reasoning` for providers that support disabling chain-of-thought,
  measured 15× faster and 2.75× cheaper on the same query. Reasoning stays
  ON by default and the setting is recorded in `judge.json`, because it
  changes the grades.

## Where the cost saving actually is

Judge cost is not the bottleneck. A pass is ~$0.60, so judging every run is
already affordable. The 8.4× saving lives on the **agent** side: the same
full run costs $1.205 on `z-ai/glm-5.2` and ~$0.14 on
`deepseek-v4-flash-0731` (4.29M input / 118k output tokens, 86% cached).
That is the change that makes many more runs practical — and it is also a
product question worth answering with the harness rather than assuming.

## Carried forward

- **Drop the mechanical narration lexicon.** All three judges flagged
  meta-narration on 17–21 of 31 answers; `NARRATION_MARKERS` caught **1**.
  Rely on the judge for narration. Keep `token_leak`, which is a precise
  regex for a specific observed failure, not a fuzzy judgment.
- **`deepseek/deepseek-v4-pro`** ($0.435/M in) remains untested.
- **Judge results are not comparable across judge models** — sonnet and
  deepseek found 135 vs 113 load-bearing claims on identical answers. That
  is now enforced: `compare_agent_runs.py` withholds the judge section when
  the two runs used different judge models, alongside its existing corpus
  and query-set guards.
- **The committed baseline was re-judged with glm-5.2** and `judge.json`
  re-pointed, so future comparisons diff like against like. The sonnet and
  deepseek outputs are kept beside it as `judge-<model>.json`.
