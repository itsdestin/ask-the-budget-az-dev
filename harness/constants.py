"""Numbers the harness has to agree with itself about (Plan 4).

Everything here is read by at least two modules that would otherwise
each hold their own literal. That is not a hypothetical: before this
file existed, THREE different refusal thresholds reached the model at
once — 0.30 in the tool description the model read, 0.65 in stale
comments, and 1.9 in the system prompt it also read. A model told two
numbers picks one, and nobody can say which.

Deliberately import-free (beyond the stdlib) so every layer — tools,
prompt, tool loop, and later an admin page — can import it without
dragging retrieval, storage, or a model provider along.
"""
from __future__ import annotations

from types import MappingProxyType

# Refuse to cite when `top_score` (the reranker's score for the best
# chunk) falls below this. Calibrated 2026-07-30 against the LOCAL
# cross-encoder's logit distribution — precision 0.67 / recall 0.40 /
# retrieval pass-rate 0.97 on the 34-query eval set.
#
# WHY the scale matters: after Plan 1 these are raw cross-encoder logits
# (roughly -10..10, negatives normal), not Voyage's old 0..1. Any
# threshold inherited from the Voyage era is meaningless here — 0.65 on
# this scale sits below almost every real hit and would never fire, and
# 0.30 is worse for the same reason. Re-run
# `eval/calibrate_refusal.py` after any corpus or rerank-model change
# and edit this ONE number; `harness/prompt.py` and `harness/tools.py`
# both inject it, so they can never disagree.
# RE-CALIBRATED 2026-08-01 from 1.9 -> 1.04, because RECENCY_BOOST_PER_YEAR
# went 0.0 -> 2.064 on the same day. The boost is a PENALTY on age: it can only
# ever lower a score, so it lowers `top_score` too, and this number is compared
# against `top_score`. Leaving it at 1.9 would have quietly made the system
# refuse more often — looking like caution, actually just a units mismatch.
#
# RE-CALIBRATED AGAIN 2026-08-02, 1.04 -> 1.46, when the weight came DOWN to
# 0.85 against the completed FY2005-2027 corpus. The coupling runs both ways:
# a SMALLER penalty depresses `top_score` less, so scores rise and a threshold
# tuned for the larger penalty stops separating. Observed directly — refusal
# query q-030 scored -1.17 at weight 2.064 and +1.42 at 0.85, sailing over the
# old 1.04 and answering a question it should have refused. That is Invariant 3
# failing quietly, which is why these two numbers must always move together.
# Sweep: eval/calibrate_refusal.py against
# eval/results/2026-08-02T1107Z-c9c16b7.json — at 1.46 refusal precision is
# 1.00 (nothing is refused that shouldn't be), refusal recall 0.60, and
# retrieval pass-rate 1.00 (no real question is turned away).
#
# RE-CHECKED 2026-08-02 after MATCH_PENALTY was calibrated (query
# understanding, spec Q4) and DELIBERATELY LEFT AT 1.46. Recorded because
# `calibrate_refusal.py` recommends -0.77 against that run and a future reader
# will wonder why the recommendation was ignored:
#
#   1. The new penalty did not move the distribution. `max_top_score` was
#      8.6779 at EVERY weight from 0.0 to 4.0 — a penalty only lowers
#      NON-matching chunks, and the best chunk on these queries always
#      matched. Refusal precision is 0.60 both before and after the change.
#   2. -0.77 trades refusal RECALL (0.60 -> 0.40) for PRECISION (0.60 ->
#      1.00), i.e. it refuses LESS. Invariant 3 wants the opposite: "high
#      refusal rate = fixable, confident hallucination = trust-destroying."
#   3. It is derived from five refusal queries. That is a thin basis for
#      moving a shipped constant.
#
# Moving this belongs in its own change with its own evidence, not smuggled
# in beside an unrelated calibration.
REFUSAL_THRESHOLD = 1.46

# Bounds the model may pass in a `fiscal_year` filter.
#
# WHY they are not "the years currently in the corpus": the S20 backfill
# adds editions back to FY1984, and a schema that stops at 2015 would
# make the historical years unreachable through the ONE mechanism the
# model controls — it would have to smuggle the year into its query text
# and hope the parser catches it. These mirror MIN/MAX_PLAUSIBLE_YEAR in
# `retrieval/query_year.py` (this file stays import-free, so the two are
# kept in step by tests/test_harness_constants_year_bounds.py rather than
# by an import). A filter value no document carries simply matches
# nothing, so a generous range costs nothing.
FISCAL_YEAR_MIN = 1984
FISCAL_YEAR_MAX = 2035

# How small the FIRST search of a conversation is forced to be
# (progressive retrieval). Matches `lookup`'s top_k so a question whose
# first call lands well needs no follow-up. Named rather than inlined
# because the tool description, the system prompt, and the executor all
# state the same number to the model.
FIRST_CALL_TOP_K_CAP = 5

# `intent` -> how many chunks to return. From the 2026-05-20 dogfood
# hardening pass: tight for lookup (the analyst wants one number),
# broader for analyze (the analyst wants context).
#
# analyze was lowered 25 -> 18 because 25 produced ~50K-char tool
# results that pushed the old harness into spilling results to disk and
# re-reading them (+5-10s per turn). 18 still gives more context than
# compare's 12 while staying under that line. When no intent is given
# the pipeline's own DEFAULT_PIPELINE_TOP_K (15) applies — that default
# lives in retrieval, not here, because it is the retrieval pipeline's
# property and the eval harness reads it too.
INTENT_TOP_K = MappingProxyType({"lookup": 5, "compare": 12, "analyze": 18})

# S16 tiers: how much effort each analyst-facing tier is allowed to
# spend. NOT admin-configurable (harness/settings.py owns the "which
# model" knob and explains why): an admin who accidentally set
# Standard's step cap to 1 would silently break every quick lookup with
# no error surface.
#
# Two consumers, which is why this lives in constants.py rather than in
# either of them: `harness/session.py` enforces `max_steps` in the tool
# loop, and `harness/tools.py` consults `deep_dive_allowed` so a
# Standard-tier `deep_dive: true` is ignored (with a note in the tool
# result, so the model knows why it got a small sample instead of
# silently re-asking). Standard stays cheap by construction rather than
# by the model's good behavior. Putting it in either module would make
# the other import it, and session.py already constructs a ToolExecutor
# — that direction of dependency has to stay one-way.
#
# Read-only mapping: this is a process-wide global in a server that
# serves the whole office, so a stray mutation would change every
# conversation's budget at once.
TIER_BUDGETS = MappingProxyType(
    {
        "standard": MappingProxyType({"max_steps": 15, "deep_dive_allowed": False}),
        "deep_research": MappingProxyType({"max_steps": 50, "deep_dive_allowed": True}),
    }
)

# The tier a conversation gets when nobody chose one.
DEFAULT_TIER = "standard"

# S19: fraction of a user's monthly dollar limit at which
# `harness/ledger.py`'s `check_limit()` starts returning "warn" instead
# of "allowed". Named (not inlined as 0.8) because that function and,
# later, an admin-page usage panel (Plan 5) must never disagree on where
# "getting close to the limit" starts — the same failure mode this
# module exists to prevent for REFUSAL_THRESHOLD above, applied here to
# a second number two layers would otherwise each hardcode.
WARN_THRESHOLD_RATIO = 0.8
