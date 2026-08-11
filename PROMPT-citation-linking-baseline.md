# Handoff — citation linking: live reproduction + Layer 2 re-baseline

> ## ⬛ SUPERSEDED 2026-08-11 — do not execute
>
> The post-hoc linker this runbook was written for has been **replaced**
> by attested linking (the model tags each figure, the system verifies the
> tag). `citation/authority.py` — the document-authority ranking whose
> output this runbook was meant to measure — is deleted.
>
> **Use [`PROMPT-attested-citation-baseline.md`](PROMPT-attested-citation-baseline.md)
> instead.** It carries the live steps, the new decision table, and the
> offline numbers the live run is measured against.
>
> Kept in place as the record of what was owed against the old design.

**Status: SUPERSEDED (was ACTIVE).** Run this on a machine that has an OpenRouter key
configured (`<data_dir>/settings.json`). It **spends real money** —
roughly **$0.50–1.50** for the full run, plus the judge as a separate
charge on top. Nothing here is safe to run unattended.

**Why it exists:** citation linking shipped 2026-08-02 (see the
"Citation linking" section of `STATUS.md`). Everything in it is measured
against recorded transcripts or pinned by tests **except the system-prompt
change**, which by construction only shows up when a real model answers.
`eval/run_eval.py` cannot see it either — Layer 1 calls `retrieve()`
directly and never reads the system prompt.

Spec: `docs/superpowers/specs/2026-08-02-citation-linking-design.md`.
Plan: `docs/superpowers/plans/2026-08-02-citation-linking.md` (Task 12).

---

## 0. Prerequisites

```bash
cd <repo> && git fetch origin && git pull origin master
uv run python -c "
from harness.settings import load_settings, ai_available
print(ai_available(load_settings(), 'standard'))"
```

Expect `(True, ...)`. If it says `no API key configured`, stop — that is
the condition that blocked this work in the first place, and no amount of
re-running changes it.

---

## 1. The live reproduction

This is the question that started the whole design: it returned a ten-row
table in which **two numbers carried a chip**, numbered 1 → 3 → 4 → 2.

```bash
cat > repro_tmp.py <<'EOF'
from collections import Counter

from harness.session import HarnessSession
from harness.settings import load_settings
from harness.ledger import LimitStatus

def allow(*a, **k):
    return LimitStatus("allowed", None, None, None, None)

s = HarnessSession("repro", corpus="budget", tier="standard", user="eval",
                   settings=load_settings(), check_limit=allow,
                   record_usage=lambda *a, **k: None)
frame = s.send_turn("what are the biggest agencies by budget")
s.close()

figs = frame["annotation"]["figures"]
print(Counter(f["verdict"] for f in figs))
print("indices in reading order:", [f["index"] for f in figs])
print("model cite calls:", sum(1 for c in frame["toolCalls"]
                               if c["toolName"] in ("cite", "cite_batch")))
for f in figs:
    print(f"  [{f['index']}] {f['text']:>16}  {f['verdict']}")
EOF
uv run python repro_tmp.py; rm -f repro_tmp.py
```

**Pass:** nearly every figure `linked` or `derived`, indices strictly
ascending, and **zero** model cite calls for a numeric answer.

**If figures come back `unverified` in bulk, STOP and report** — do not
tune the floor to make the number look better. The offline measurement
over 31 recorded transcripts puts unverified at 7.1%, so a bulk-unverified
live run means something differs between the recorded corpus and this
machine's, and that is the finding, not the floor.

Note the `LimitStatus(...)` positional arity above is from the plan as
written; if the dataclass has changed, construct an allowed status
whatever way it now wants rather than working around the error.

---

## 2. The Layer 2 re-baseline

```bash
uv run python -m eval.run_agent_eval --subset full --note "post citation-linking"
uv run python -m eval.score_agent_run  eval/results/agent/<new-run>
uv run python -m eval.judge_agent_run  eval/results/agent/<new-run>
uv run python -m eval.compare_agent_runs \
    eval/results/agent/2026-08-02T0900Z-0b08221 \
    eval/results/agent/<new-run>
```

`--subset full` is all 31 **Standard-tier** queries and contains no Deep
Research query — that exclusivity is pinned by
`tests/test_eval_agent_queries.py`, so do not "fix" it by adding the DR
probe into `full`.

### What the comparison should say

| metric | direction | why |
|---|---|---|
| `figure_coverage_mean` | **high** (~0.93) | new metric; offline says 92.9% |
| `unverified_rate` | **low** (~0.07) | new metric |
| `steps_mean` | **down** | cite round-trips removed |
| `input_tokens_mean` | **down** | same |
| `cost_mean_usd` | **down** | same |
| `cite_pass_rate` | changes meaning | it now measures PROSE citations only, so its population moved — do not read the delta as a quality change |
| `key_fact_rate_mean` | **unchanged** | nothing here touches retrieval |

`key_fact_rate_mean` moving is the one that should worry you: the prompt
edit is the only thing that could move it, and it would mean the rewrite
changed what the model says, not just how it cites.

**Single runs are stochastic.** `compare_agent_runs.py` prints a warning
whenever either side is a single run. If a delta looks marginal, re-run
with `--repeats` rather than believing it.

---

## 3. Commit the result

Transcripts are gitignored by policy; the derived record is not.

```bash
git add -f eval/results/agent/<new-run>/manifest.json \
           eval/results/agent/<new-run>/scores.json \
           eval/results/agent/<new-run>/scores.md \
           eval/results/agent/<new-run>/judge.json \
           eval/results/agent/compare-*.md
git commit -m "eval: re-baseline after citation linking"
```

Then update the **"🔴 OUTSTANDING"** block of the citation-linking section
in `STATUS.md` with the real before/after numbers and delete the
outstanding marker — or, if the numbers disagree with the table above,
replace that block with what actually happened. A handoff that records a
disappointing result honestly is worth more than one that quietly stops.

---

## 4. Also unverified: the chips in a real browser

Independent of the eval, and free:

```bash
cd webapp && npm run build
cd .. && uv run uvicorn app.main:create_app --factory --port 9300
```

Ask a question that produces a table of dollar figures, then check:

- every figure carries a chip, numbered in reading order down the page;
- a **derived** chip looks different from a linked one and its popover
  reads "Computed from [n], [m]" with **no** PDF link;
- an **unverified** chip reads "This figure was not found in the
  retrieved sources.";
- a linked chip's popover shows "Also appears in:" when the same figure
  sits in more than one edition;
- clicking a linked chip opens the PDF and highlights **the source's**
  rendering of the number.

That last one is the payoff of the whole design and the only part no test
can prove. 22 vitest specs cover the logic underneath; nobody has watched
it render.

**Shut the dev server down when you're done** — the project rule is that
pushing to master green-lights closing it, and orphan processes on port
9300 confuse the next session.
