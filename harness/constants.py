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
REFUSAL_THRESHOLD = 1.9

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
