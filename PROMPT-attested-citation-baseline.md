# Handoff — attested citation linking: live baseline

**Status: ACTIVE.** Run this on a machine that has an OpenRouter key
configured (`<data_dir>/settings.json`). It **spends real money** —
roughly **$0.50–1.50** for the full run, plus the judge as a separate
charge on top. Nothing here is safe to run unattended.

Supersedes [`PROMPT-citation-linking-baseline.md`](PROMPT-citation-linking-baseline.md),
which was written for the post-hoc linker this design replaced.

Spec: `docs/superpowers/specs/2026-08-02-attested-citation-linking-design.md`.
Plan: `docs/superpowers/plans/2026-08-02-attested-citation-linking.md`.

---

## Why this exists — the one thing that could not be measured offline

The design's whole premise is that **the model reliably tags each figure
with the passage it came from**. Everything else was measured on this
machine against recorded transcripts and is pinned by tests. Marker
compliance was not, and cannot be: it only exists when a real model
answers under the new prompt.

`eval/run_eval.py` (Layer 1) cannot see it either — it calls `retrieve()`
directly and never reads the system prompt.

**The offline gate already passed** (see `STATUS.md`):

| profile | before | after |
|---|---|---|
| false-link, 4-sig billions | 3.7% | **0.28%** |
| false-link, 4-sig millions | 2.9% | **0.19%** |
| false-link, exact grouped | 0.4% | **0.00%** |

Coverage on those same recorded transcripts fell **92.9% → 50.3%**. That
is **expected and is not the shipped number**: recorded transcripts carry
no tags, so it measures the untagged fallback floor alone. What this
runbook measures is how much of that gap tagging buys back.

---

## 0. Prerequisites

```bash
cd <repo> && git fetch origin && git pull origin master
uv run python -c "
from harness.settings import load_settings, ai_available
print(ai_available(load_settings(), 'standard'))"
```

Expect `(True, ...)`. If it says `no API key configured`, stop.

---

## 1. The live browser reproduction

Start the app (`cd webapp && npm run build` once, then
`uv run uvicorn app.main:create_app --factory --port 9300`), open AI Mode,
and ask:

> what are the biggest agencies by budget

**Watch for, in priority order:**

1. **`[[` anywhere in the visible answer.** This is a P1 render bug and
   the single most likely failure. If it appears *while streaming* but not
   in the final text, the fault is `strip_for_stream` in the
   `assistant_text_delta` emit. If it survives into the final answer, the
   fault is `_Accumulator.final_answer()`. Those are the only two places.
2. **The model narrating its tags** ("I'll mark that with c3"). Output
   hygiene bans it; it means the prompt wording needs work, not the code.
3. Chip click opens the PDF at the source rendering.
4. An unverified chip's tooltip copy — the near-miss line reads
   "Nearest source value: X (differs by Y%)", and an ambiguous figure says
   "appears in N different documents" with **no** near-miss line beside it.

---

## 2. Layer 2 — smoke, then full

```bash
uv run python -m eval.run_full_layer2 --sets quick,multi,refusal --workers 4
```

Read `marker_coverage_mean` and `tag_accuracy_mean` FIRST — see §3. If
they clear the bar, proceed:

```bash
uv run python -m eval.run_full_layer2 --sets quick,multi,deep,refusal --workers 4
uv run python -m eval.compare_agent_runs \
    eval/results/agent/2026-08-02T0900Z-0b08221 \
    eval/results/agent/<new-run>
```

---

## 3. The decision table

Two new metrics carry the design's open risk. **Read them before anything
else in the report.**

| metric | meaning | bar |
|---|---|---|
| `marker_coverage_mean` | share of figures the model tagged | **≥ 0.80** |
| `tag_accuracy_mean` | share of tagged figures that verified against the named chunk | **≥ 0.90** |

- **Both clear the bar** → the design holds. Record the shipped coverage
  (linked + derived) — it must beat the **50.3%** untagged floor by a wide
  margin, or tagging is not doing its job.
- **`marker_coverage_mean` below 0.80** → the model is not tagging enough.
  Iterate the Task 8 prompt wording and re-run smoke. Do NOT compensate by
  loosening the fallback floor without reading §5 first.
- **`tag_accuracy_mean` below 0.90** → the model is tagging the WRONG
  chunk. This is the serious one: it means attestation is not trustworthy
  evidence, and the floor-2 concession on the tag path should be
  reconsidered. A low number here is a reason to stop and re-think, not to
  tune.

Also check: **token delta should be ≈ +150 output tokens per answer**, not
thousands. A marker is ~6 tokens and there are ~14 figures in a typical
answer. If the delta is large, the model is narrating rather than tagging.

Expected directions elsewhere: `steps_mean` and `input_tokens_mean` DOWN
(cite round-trips for figures are gone), `cite_pass_rate` no longer
dominated by figure citations.

---

## 4. What NOT to conclude

- **A coverage number below 92.9% is not automatically a regression.** The
  old 92.9% counted links produced, including the 34.2% that matched more
  than one document and were resolved by a document-authority rule that no
  longer exists. Some of that coverage was wrong by construction. Compare
  false-link rate first, coverage second.
- **Do not re-run `eval/false_link_check.py` expecting it to move.** It
  measures the untagged fallback and is deliberately independent of model
  behaviour. It is the regression guard, not the live metric.

---

## 5. The one calibration deliberately left open

The **fallback specificity floor is 4 written significant digits**
(`min_significant_digits` default in `citation/matching.py`; the tag path
uses 2). It was swept offline against the 27 baseline pools, and it is a
monotonic trade with **no plateau** — so no rule picks it, and the right
answer depends on how much traffic the fallback actually carries:

| floor | coverage | false-link (bil / mil / exact) |
|---|---|---|
| 2 | 63.7% | 0.46% / 0.19% / 0.00% |
| 3 | 60.0% | 0.37% / 0.19% / 0.00% |
| **4 (shipped)** | **50.3%** | **0.28% / 0.19% / 0.00%** |
| 5 | 38.4% | 0.00% / 0.00% / 0.00% |
| 6 | 29.0% | 0.00% / 0.00% / 0.00% |

**Settle this with the live `marker_coverage_mean` in hand, not before.**
If tagging covers ≥ 0.9 of figures the fallback is a thin safety net and
floor 4's strictness is nearly free; if it covers ~0.5 the fallback is
carrying half the answer and floor 3 buys ~10 points of coverage for
+0.09pp of false links. That is a real decision with numbers on both
sides — record which one you picked and why.
