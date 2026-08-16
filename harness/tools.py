"""The six tools the model can call, as in-process Python (Plan 4, S2).

These used to be four TypeScript files behind an MCP server that talked
HTTP to a FastAPI sidecar. Spec decision S2 drops MCP entirely: the
protocol layer dies, the tool LOGIC survives verbatim. What the model
sees — schemas, response shapes, error strings — is unchanged apart from
the deliberate edits noted below, because that surface was tuned over
months of dogfooding and every quirk in it is a fix for something that
actually went wrong.

**What changed on purpose, and why**

* *One refusal threshold.* The old tool description told the model to
  refuse below `0.30` while the system prompt said `1.9` and stale
  comments said `0.65`. All three reached the model at once. There is
  now one number, `harness.constants.REFUSAL_THRESHOLD`, injected into
  the description below rather than typed into a string literal.
* *The first-call cap is per-executor.* The TypeScript version used a
  module-level boolean, which was correct there — one MCP process per
  session. This process serves the whole office, so a module-level flag
  would mean the second analyst's opening question skips the sampling
  discipline because the first analyst already asked one. The flag is
  instance state and `tests/test_harness_tools.py` proves two executors
  are independent.
* *`fiscal-note` joins the doc_type enum.* Plan 3 adds a second corpus.
* *Provider-neutral wording.* The model reading these descriptions has
  never heard of MCP, Claude Code, sessions, or a sidecar.
* *`create_document` is new* (S3) — the only tool that produces a file,
  and it takes no path from the model (see Invariant 7 below).
* *`document_guide` is new* — house rules for a document the model is
  about to write. A TOOL rather than more system prompt because the
  prompt is the cached prefix every conversation pays for on every step,
  and this guidance is wanted on the small minority of turns that
  produce a document. Its CONTENT lives in `harness/guides/*.md`, loaded
  by `harness/guides.py` — under `harness/` and not `memo/` because the
  import allowlist below permits `harness` and forbids `pathlib`, so a
  guide loader outside this package is what keeps that guard intact.

**Invariant 7 — the model-callable surface has no filesystem access.**
No shell tool, no file read/write tool, and no path-typed argument
anywhere in these schemas. `create_document` names its output by TITLE;
`harness/documents.py` decides where bytes land (under the user's local
app-data folder, never under the shared data directory). The guard is
structural, not aspirational: the tests walk every schema recursively
for path-shaped parameter names and assert this module's import graph
stays inside an allowlist, so `subprocess`, `pathlib`, or anything from
`ingest` fails the suite rather than review.
"""
from __future__ import annotations

import json
import sys
import threading
import uuid
from typing import Any, Callable, Iterable, Mapping

from harness.constants import (
    DEFAULT_TIER,
    FIRST_CALL_TOP_K_CAP,
    FISCAL_YEAR_MAX,
    FISCAL_YEAR_MIN,
    INTENT_TOP_K,
    REFUSAL_THRESHOLD,
    SPREAD_DEFAULT_PER_GROUP,
    SPREAD_MAX_GROUPS,
    SPREAD_MAX_PER_GROUP,
    SPREAD_MAX_TOTAL,
    SPREAD_MIN_PER_GROUP,
    TIER_BUDGETS,
)
# Aliased on import: this module already has DEFAULT_TIER and
# DEFAULT_PIPELINE_TOP_K in scope, and a bare DEFAULT_TYPE beside them
# reads as "the default of what?".
from harness.guides import DEFAULT_TYPE as DEFAULT_REPORT_TYPE, REPORT_TYPES, guide_for
from retrieval import (
    DEFAULT_PIPELINE_TOP_K,
    RetrievalRequest,
    SpreadSpec,
    pipeline,
    retrieve,
    retrieve_spread,
)
from retrieval.citations import CiteValidateBody, validate_cite, validate_cites
from store.chunk_store import CORPUS_TABLES
from identity.resolve import resolve_titles
from store.documents import (
    humanize_doc_id,
    load_documents,
    reset_documents_cache,
)

# ---------------------------------------------------------------------------
# Corpus naming
# ---------------------------------------------------------------------------
# Two vocabularies meet here. The HTTP contract (Plan 2, frozen) says
# "budget" / "fiscal_notes"; LanceDB and every retrieval call want the
# table name. Accepting both and normalizing once means a Task 6/8 wiring
# mistake can't quietly search the wrong corpus — and an unrecognized name
# raises at CONSTRUCTION, before a conversation starts, because that is a
# programming error at the call site, not something the model did.
_CORPUS_ALIASES = {"budget": "budget_chunks", "fiscal_notes": "fiscal_note_chunks"}


def resolve_corpus(name: str) -> str:
    """Wire name or table name -> LanceDB table name."""
    table = _CORPUS_ALIASES.get(name, name)
    if table not in CORPUS_TABLES:
        raise ValueError(
            f"Unknown corpus {name!r}. Valid names are: "
            f"{', '.join(sorted(set(_CORPUS_ALIASES) | set(CORPUS_TABLES)))}."
        )
    return table


# ---------------------------------------------------------------------------
# Document titles
# ---------------------------------------------------------------------------
# doc_title is in every retrieve() result the model reads, so a blank or
# ugly one shows up in ANSWERS, not just in the UI.
#
# The cache, the parse, the humanizer and the acronym table all moved to
# `store/documents.py` in Plan 5 Task 19 — there used to be four copies
# and they had already drifted. These are thin aliases so the harness's
# internal call sites (and the tests that reach for the reset hook) keep
# their existing names.
#
# NOTE the harness deliberately does NOT pass `require_ingested=True`:
# here the sidecar is the ONLY title source, so gating out the 378
# migration-era entries would swap real agency names for doc-id slugs in
# answers. See `store.documents.title_for`.

reset_document_title_cache = reset_documents_cache
_document_metadata = load_documents
_title_from_doc_id = humanize_doc_id

# WHY this stopped being `titles_for` (2026-08-16): three surfaces resolved a
# document's display title three different ways — search results preferred a
# vendored scrape of JLBC's website index, the browse listing used the sidecar
# ungated, and AI Mode used the sidecar ungated — so the same document could be
# named one thing on the page and another inside an answer, with no test able
# to compare them. `identity.resolve` is now the only ladder, and a spec
# asserts all three agree. See spec I12.
#
# Only the READ side of `identity` may be reached from here — Invariant 7. The
# guard is `tests/test_harness_tools.py::
# test_tools_module_reaches_only_the_read_side_of_identity`.
_doc_titles = resolve_titles


# ---------------------------------------------------------------------------
# Agency-name catalog (guarded import)
# ---------------------------------------------------------------------------


def _agency_names() -> dict[str, str]:
    """canonical_id -> human agency name, or {} when unavailable.

    GUARDED ON PURPOSE, TEMPORARILY: `chunking/agency_catalog.py` is
    being written right now by the parallel session executing Plan 3.
    Until both plans merge, this module must tolerate the catalog being
    absent — and once it exists, tolerate it being reshaped. Every
    failure mode (no module, no `id_to_name` attribute, an unexpected
    type, a callable that raises) degrades to raw canonical_ids, which
    is what the tool returned before the catalog existed at all. A live
    conversation must never die because a metadata nicety is missing.

    REMOVE THE GUARD once Plan 3 is merged — noted for Plan 5. It hides
    real breakage the moment the module is a dependency we can count on.

    SCOPE: this guards STRUCTURE, not CORRECTNESS. A catalog that
    imports cleanly and type-checks fine but maps `agency:tre` to the
    wrong agency passes here untouched, and a wrong name looks exactly
    as authoritative to the model (and to the analyst reading the
    answer) as a right one. Nothing in this module can tell the
    difference; correctness of the mapping is Plan 3's to own, and if it
    ever needs verifying, that belongs in a test against the catalog
    itself, not in a defensive import here.
    """
    try:
        from chunking.agency_catalog import id_to_name  # type: ignore[attr-defined]

        mapping = id_to_name() if callable(id_to_name) else id_to_name
        if not isinstance(mapping, Mapping):
            return {}
        return {str(k): str(v) for k, v in mapping.items()}
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Tool schemas (OpenAI function-calling form)
# ---------------------------------------------------------------------------
# Plain JSON Schema dicts rather than a generated-from-pydantic shape:
# these strings are the model's ONLY documentation for the tools, they go
# on the wire verbatim in the /chat/completions request body, and the
# wording matters more than the typing convenience would. Written out
# here, a description edit is a one-line diff a reviewer can read.

# The doc_type values below MUST match the values actually present in the
# corpus. Pre-2026-05-08 this enum drifted from the data and the failure
# was SILENT: it accepted `baseline-agency` / `approps-report` /
# `baseline-cross-cut` / `primer` (none of which exist, so a filtered
# search returned zero chunks and the model concluded the corpus lacked
# the answer) while rejecting the values that DO exist. If a future
# ingest adds a doc_type, extend this list AND the system prompt.
# `list_filter_values` is the RUNTIME source of truth; this enum only
# validates input at the tool boundary.
#
# tests/test_new_doc_types.py::test_the_doc_type_enum_matches_the_registry_exactly
# pins this list to ingest.doc_types.all_types() exactly, so it can never
# drift from data/document-types.yaml again the way it drifted before
# 2026-05-08. NOTE (Plan A Task 4 self-review, 2026-08-11): that pin pulls in
# `baseline-book` and `approps-report`, which the registry marks
# `redirect: add-jlbc-book` -- the "Add a JLBC book" tool always expands them
# into per-agency (`baseline-per-agency` / `approps-per-agency`) and section
# (`s-pdf`/`bh-pdf`/`bd-pdf`/`detailed-list-pdf`/`topic-pdf`) documents, so no
# corpus chunk is ever stamped with the literal `baseline-book` or
# `approps-report` doc_type (see ingest/book_discovery.py and the "does not
# actually use" note in retrieval/query_doc_type.py). A model that filters on
# either value today gets an honest zero-result page, not the historical
# silent-drift failure this comment describes -- but it is still an empty
# page for a value this enum now claims is valid. Flagged for review rather
# than silently omitted, since the registry-parity test above is what a
# future ingest adding book-level chunks would need anyway.
_DOC_TYPES = [
    "baseline-per-agency",
    "approps-per-agency",
    "baseline-book",
    "approps-report",
    "s-pdf",
    "bd-pdf",
    "bh-pdf",
    "detailed-list-pdf",
    "topic-pdf",
    "afr",
    "governors-budget",
    "budget-bill",
    # JLBC's summary of the budget bills in progress. Precedes the
    # Appropriations Report and is superseded by it -- see the lifecycle
    # section of system-prompt.md.
    "budget-bill-summary",
    # An agency's own budget request, one per agency per year.
    "agency-submission",
    # Added for Plan 3's fiscal-note corpus.
    "fiscal-note",
]

# WHY "agency": the 2026-06 harvest records the *agency name* as publisher
# for each of the 78 agency budget requests (78 distinct values) -- adding
# all 78 here would destroy the publisher filter's usefulness. The agency
# identity already lives in the entity stamper / agency_canonical_id, so one
# `agency` publisher is the right granularity (data/document-types.yaml:
# agency-submission declares publisher: agency).
_PUBLISHERS = ["jlbc", "legislature", "governor", "agao", "agency"]

_FILTERS_SCHEMA = {
    "type": "object",
    "description": "Optional filters to narrow the search.",
    "additionalProperties": False,
    "properties": {
        "fiscal_year": {
            "type": "array",
            "items": {
                "type": "integer",
                "minimum": FISCAL_YEAR_MIN,
                "maximum": FISCAL_YEAR_MAX,
            },
            "description": "Restrict to documents covering these fiscal years (any-of).",
        },
        "doc_type": {
            "type": "array",
            "items": {"type": "string", "enum": _DOC_TYPES},
            "description": "Restrict to document types (any-of).",
        },
        "publisher": {
            "type": "array",
            "items": {"type": "string", "enum": _PUBLISHERS},
            "description": "Restrict to publishers (any-of).",
        },
        "agency_canonical_id": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Restrict to chunks tagged with these agency ids (e.g. "
                "'agency:adc'; any-of). Call list_filter_values first if "
                "you are not certain of an id — a wrong one silently "
                "returns nothing."
            ),
        },
        "fund_canonical_id": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Restrict to chunks whose primary fund matches (any-of).",
        },
        "is_table": {
            "type": "boolean",
            "description": (
                "If true, return only tabular chunks; if false, only narrative."
            ),
        },
    },
}

# The threshold is INTERPOLATED, never typed as a literal — that is the
# whole point of harness/constants.py.
#
# Corpus-NEUTRAL wording on purpose: one registry serves both corpora
# (Arizona budget documents and, from Plan 3, legislative fiscal notes),
# and a conversation is scoped to exactly one of them by the executor.
# Naming "the budget corpus" here would be wrong half the time; which
# corpus is in play is stated once, in the system prompt.
_RETRIEVE_DESCRIPTION = (
    "Search this conversation's corpus of Arizona fiscal documents (your "
    "instructions say which corpus that is) and return the most relevant "
    "passages for a query. Call this BEFORE answering any question about "
    "its content. You MAY call it several times in one turn (for example, "
    "once per side of a comparison). Use filters when the question implies them "
    "(a specific fiscal year, agency, publisher). Each result carries a "
    "chunk_id you must echo back into cite() — never invent one. If "
    f"`top_score` is below {REFUSAL_THRESHOLD}, do NOT cite; say you could "
    "not find support, using the refusal wording from your instructions. "
    "PROGRESSIVE RETRIEVAL: the FIRST search of a conversation returns at "
    f"most {FIRST_CALL_TOP_K_CAP} passages no matter what you ask for — "
    "read that sample, then search again with a sharper query if you need "
    "more. The response carries `first_call_capped: true` when that "
    "happened."
)

# Spec N4. The model already knows retrieve(), so this is a PARAMETER rather
# than a sixth tool: every retrieve affordance — filters, aliases, citations,
# the refusal comparison — applies to spread results for free, and a new tool
# schema would be more surface to misuse.
_SPREAD_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["by", "groups"],
    "description": (
        "Structured multi-group search: run this ONE query separately inside "
        "each named group and return the best passages from EACH, so "
        "near-identical editions cannot crowd each other out of the results. "
        "Use it for multi-year comparisons ('X across FY2022-2026'), for "
        "'which years mention X', and whenever plain search keeps returning "
        "the same edition. Bounded: at most "
        f"{SPREAD_MAX_GROUPS} groups x {SPREAD_MAX_PER_GROUP} passages per "
        f"group, {SPREAD_MAX_TOTAL} passages in total. It counts as your one "
        "first search but is NOT cut down to the small first-call sample. "
        "Cannot be combined with top_k, intent or deep_dive."
    ),
    "properties": {
        "by": {
            "type": "string",
            "enum": ["fiscal_year", "doc_id"],
            "description": (
                "Which axis the groups name: 'fiscal_year' for years, "
                "'doc_id' for specific documents you have already seen."
            ),
        },
        "groups": {
            "type": "array",
            "minItems": 1,
            "maxItems": SPREAD_MAX_GROUPS,
            "description": (
                "The group values, in the order you want them back: "
                "four-digit fiscal years for by=fiscal_year, doc_ids from "
                "earlier results for by=doc_id. Check the corpus inventory "
                "in your instructions first — a group with no edition in the "
                "corpus comes back empty and wastes one of your groups."
            ),
            # Deliberately untyped: `by` decides whether these are integers
            # or strings, and a JSON Schema union here reads to a model as
            # "either is fine on either axis". The coercion below enforces
            # the real rule with an error that names the axis.
            "items": {},
        },
        "per_group": {
            "type": "integer",
            "minimum": SPREAD_MIN_PER_GROUP,
            "maximum": SPREAD_MAX_PER_GROUP,
            "description": (
                f"Passages to keep per group (default {SPREAD_DEFAULT_PER_GROUP})."
            ),
        },
    },
}

_RETRIEVE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "retrieve",
        "description": _RETRIEVE_DESCRIPTION,
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "required": ["query"],
            "properties": {
                "query": {
                    "type": "string",
                    "minLength": 1,
                    "description": (
                        "Natural-language search query. Expand acronyms before "
                        "calling (e.g. 'AHCCCS' -> 'Arizona Health Care Cost "
                        "Containment System AHCCCS'). Be specific; vague "
                        "queries reduce recall."
                    ),
                },
                "filters": _FILTERS_SCHEMA,
                "top_k": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "description": (
                        "How many passages to return. When `intent` is set and "
                        "top_k is not, the intent's default applies (lookup 5, "
                        "compare 12, analyze 18); with neither, 15. The first "
                        "search of a conversation is capped regardless — see "
                        "deep_dive."
                    ),
                },
                "intent": {
                    "type": "string",
                    "enum": ["lookup", "compare", "analyze"],
                    "description": (
                        "How deep the question is. 'lookup' = one specific fact "
                        "(terse answer). 'compare' = two entities or years "
                        "side by side. 'analyze' = open-ended overview "
                        "(structured answer). This picks the answer FORMAT and "
                        "a default breadth; omit it when unsure. Breadth "
                        "otherwise comes from searching again, not from one "
                        "large search."
                    ),
                },
                "spread": _SPREAD_SCHEMA,
                "deep_dive": {
                    "type": "boolean",
                    "description": (
                        "Set true ONLY when the analyst explicitly asked for "
                        "thorough / comprehensive / 'deep dive' coverage and "
                        "you need full breadth on the very FIRST search. Most "
                        "questions do not need it, and it has no effect after "
                        "the first search. On the Standard tier it is ignored "
                        "and the first search still returns a small sample; "
                        "the response says so."
                    ),
                },
            },
        },
    },
}

_CITE_PROPERTIES = {
    "chunk_id": {
        "type": "string",
        "minLength": 1,
        "description": (
            "Identifier of the passage that supports the claim. Must be a "
            "value returned by retrieve() in this conversation. Do NOT "
            "invent ids."
        ),
    },
    "quote": {
        "type": "string",
        "minLength": 1,
        "description": (
            "PREFERRED. The exact substring of the passage text that supports "
            "the claim; the server finds it and derives the offsets. It must "
            "appear VERBATIM and exactly ONCE in that passage — if it appears "
            "more than once the cite is rejected and you should extend the "
            "quote with surrounding context until it is unique."
        ),
    },
    "span_start": {
        "type": "integer",
        "minimum": 0,
        "description": (
            "Legacy alternative to `quote`: character offset (inclusive) into "
            "the passage text. Prefer `quote`."
        ),
    },
    "span_end": {
        "type": "integer",
        "minimum": 1,
        "description": (
            "Legacy alternative to `quote`: character offset (exclusive). "
            "Prefer `quote`."
        ),
    },
    "confidence": {
        "type": "string",
        "enum": ["verbatim", "paraphrase"],
        "description": (
            "'verbatim' = the claim is a direct quote from the passage "
            "(allowing minor formatting normalization). 'paraphrase' = the "
            "claim restates it in different words."
        ),
    },
    "claim_span": {
        "type": "string",
        "minLength": 1,
        # 2000, not 500: the server soft-clamps to 500 and flags
        # `truncated` rather than rejecting. Seven cites in one dogfood
        # transcript died at the old hard 500-char boundary, and a
        # truncated claim_span still attaches the chip correctly.
        "maxLength": 2000,
        "description": (
            "The literal substring of the answer you just wrote that this "
            "citation supports — a complete clause or sentence. The interface "
            "attaches the citation marker by searching your answer for this "
            "string, so type it back exactly."
        ),
    },
}

_CITE_REQUIRED = ["chunk_id", "confidence", "claim_span"]

_CITE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "cite",
        "description": (
            "Record that one claim in the answer you just wrote is supported "
            "by a specific passage. Supply either `quote` (preferred) or "
            "span_start + span_end. Returns ok:false with an actionable error "
            "— unknown id, quote not found, quote ambiguous, span too broad — "
            "so you can fix it and try again. Use cite_batch instead whenever "
            "the answer has more than one citation."
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "required": _CITE_REQUIRED,
            "properties": _CITE_PROPERTIES,
        },
    },
}

_CITE_BATCH_SCHEMA = {
    "type": "function",
    "function": {
        "name": "cite_batch",
        "description": (
            "Register MULTIPLE citations in one call. Use this instead of "
            "calling cite() N times: it costs one round trip rather than N, "
            "which is dramatically faster for long answers. The response is a "
            "parallel array — the i-th result belongs to the i-th input — and "
            "one bad citation does not invalidate the others. An empty array "
            "is allowed."
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "required": ["citations"],
            "properties": {
                "citations": {
                    "type": "array",
                    # Defensive guard against a runaway tool call; no real
                    # answer cites 50 distinct claims.
                    "maxItems": 50,
                    "description": (
                        "Citations to register, each shaped exactly like a "
                        "cite() call. Order is preserved in the response."
                    ),
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": _CITE_REQUIRED,
                        "properties": _CITE_PROPERTIES,
                    },
                }
            },
        },
    },
}

_LIST_FILTER_VALUES_SCHEMA = {
    "type": "function",
    "function": {
        "name": "list_filter_values",
        # WHY this tool exists (2026-05-08 audit): you cannot see the
        # corpus, so a mis-remembered id like 'agency:trs' for the
        # Treasurer (really 'agency:tre') returns zero chunks with no
        # error and reads as "the corpus doesn't cover this". That one
        # typo burned ten searches and produced no citations in a single
        # conversation.
        "description": (
            "List the filter values that actually exist in the corpus for one "
            "dimension (agency, doc_type, publisher, fund), with how much "
            "material each covers and a sample document title so opaque ids "
            "are recognizable. USE THIS BEFORE filtering a search when you "
            "are not certain of an agency or fund id — a wrong id returns "
            "nothing at all, with no error to tell you why. Cheap; one round "
            "trip; the answer is stable for the whole conversation."
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "required": ["field"],
            "properties": {
                "field": {
                    "type": "string",
                    "enum": ["agency", "doc_type", "publisher", "fund"],
                    "description": "Which dimension to enumerate.",
                }
            },
        },
    },
}

_CREATE_DOCUMENT_SCHEMA = {
    "type": "function",
    "function": {
        "name": "create_document",
        "description": (
            "Turn an answer you have already written into a downloadable Word "
            "or Markdown file for the analyst. Offer this for memo-shaped "
            "requests ('write this up', 'draft a memo') — never for a simple "
            "answer. Write the full body yourself in Markdown; headings, "
            "bullets, bold and pipe tables are rendered. The TITLE becomes "
            "the memo's SUBJECT line, so write it like a subject. You name "
            "the document by TITLE only; where it is saved is not yours to "
            "choose. Call document_guide first for the house rules on "
            "sections, tables and numbers. Returns a download token the "
            "interface turns into a link."
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "required": ["title", "body_markdown"],
            "properties": {
                "title": {
                    "type": "string",
                    "minLength": 1,
                    "description": (
                        "Document title. Also the basis of the download name."
                    ),
                },
                "to": {
                    "type": "string",
                    "description": (
                        "Who the memo is addressed to — ONLY when the analyst "
                        "named an audience ('write this up for the Director'). "
                        "Omit it otherwise; the document prints a placeholder "
                        "for them to fill in. Never guess a name."
                    ),
                },
                "body_markdown": {
                    "type": "string",
                    "minLength": 1,
                    "description": "The full document body, in Markdown.",
                },
                "format": {
                    "type": "string",
                    "enum": ["docx", "md"],
                    "description": "Output format. Defaults to docx.",
                },
            },
        },
    },
}

# The guidance itself is NOT in this schema, and that is the point of
# making it a tool rather than more system prompt: only these ~90 words
# join the cached prefix every conversation pays for on every step, while
# the ~800-word guide is fetched only on the turns that write a document.
#
# `report_type` is OPTIONAL and its handler falls back rather than
# rejecting. There is nothing useful a model can do with "unknown report
# type" except guess again, so a required argument would buy a round-trip
# and no correctness.
_DOCUMENT_GUIDE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "document_guide",
        "description": (
            "House formatting and structure guidance for a document you "
            "are about to write. Call it BEFORE create_document, once, "
            "with the report type that fits: 'research-memo' (the "
            "default — a question with an answer), 'comparison' (two or "
            "more years, agencies or funds), 'agency-profile' (one "
            "agency's budget). Returns JLBC's conventions for sections, "
            "tables, numbers and voice. Free and instant — no search, no "
            "cost."
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "report_type": {
                    "type": "string",
                    "enum": list(REPORT_TYPES),
                    "description": (
                        "Which kind of document. Defaults to "
                        f"'{DEFAULT_REPORT_TYPE}' when omitted."
                    ),
                },
            },
        },
    },
}

# Tuple, not list: this is a process-wide global handed to every request
# builder, and one caller doing `TOOLS.append(...)` would change what
# every conversation in the office sees.
#
# APPENDED, never inserted: the order is what the model reads in the
# request body, and reordering the tool block changes the cached prefix
# byte-for-byte (S22) — every conversation in the office would lose its
# cache hit.
TOOLS: tuple[dict[str, Any], ...] = (
    _RETRIEVE_SCHEMA,
    _CITE_SCHEMA,
    _CITE_BATCH_SCHEMA,
    _LIST_FILTER_VALUES_SCHEMA,
    _CREATE_DOCUMENT_SCHEMA,
    _DOCUMENT_GUIDE_SCHEMA,
)

TOOL_NAMES: tuple[str, ...] = tuple(t["function"]["name"] for t in TOOLS)


# ---------------------------------------------------------------------------
# Argument coercion
# ---------------------------------------------------------------------------
# Models emit malformed arguments. Not occasionally — routinely: a scalar
# where the schema says array, a stringified number, a key that does not
# exist. Every one of those must come back as a readable tool result the
# model can retry from, because an exception here unwinds the tool loop
# and loses the whole conversation.


class _ArgumentError(ValueError):
    """Raised by the coercion helpers; caught by execute() and turned
    into a tool-visible error rather than propagating."""


def _as_object(args: Any) -> dict[str, Any]:
    """Accept the parsed object OR the raw JSON string.

    OpenAI-compatible tool calls carry `arguments` as a JSON STRING
    assembled from streamed fragments. Parsing it here — inside the
    boundary that already turns failures into tool results — means the
    tool loop never has to wrap a json.loads in its own try block, and a
    model that truncates its JSON gets told so instead of crashing us.
    """
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError as err:
            raise _ArgumentError(
                f"arguments were not valid JSON ({err}). Send the arguments "
                "again as a complete JSON object."
            ) from err
    if args is None:
        return {}
    if not isinstance(args, Mapping):
        raise _ArgumentError(
            f"arguments must be a JSON object, got {type(args).__name__}."
        )
    return dict(args)


def _req_str(args: Mapping[str, Any], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        raise _ArgumentError(f"{key} is required and must be a non-empty string.")
    return value


def _opt_str(args: Mapping[str, Any], key: str) -> str:
    """An optional string argument, or "" when absent, blank or the wrong
    type.

    Absent and empty are the same thing to every caller here, so they are
    not distinguished — and unlike `_opt_int`, a wrong type is NOT an
    error. Models emit `"to": null` and `"to": "  "` routinely; failing
    the whole call over a decorative argument would cost the analyst the
    document. Whitespace is stripped rather than passed through because a
    blank recipient prints an empty TO line where the renderer's
    `[Recipient(s)]` placeholder belongs — a memo addressed to nobody
    that looks finished.
    """
    value = args.get(key)
    return value.strip() if isinstance(value, str) else ""


def _opt_int(args: Mapping[str, Any], key: str, lo: int, hi: int) -> int | None:
    value = args.get(key)
    if value is None:
        return None
    # bool is an int subclass in Python; True would silently become 1.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _ArgumentError(f"{key} must be a whole number between {lo} and {hi}.")
    if isinstance(value, float) and not value.is_integer():
        raise _ArgumentError(f"{key} must be a whole number between {lo} and {hi}.")
    number = int(value)
    if not lo <= number <= hi:
        raise _ArgumentError(f"{key} must be between {lo} and {hi} (got {number}).")
    return number


def _opt_bool(args: Mapping[str, Any], key: str) -> bool:
    value = args.get(key)
    if value is None:
        return False
    if not isinstance(value, bool):
        raise _ArgumentError(f"{key} must be true or false.")
    return value


def _opt_enum(args: Mapping[str, Any], key: str, allowed: Iterable[str]) -> str | None:
    value = args.get(key)
    if value is None:
        return None
    allowed = list(allowed)
    if value not in allowed:
        raise _ArgumentError(f"{key} must be one of: {', '.join(allowed)}.")
    return str(value)


def _as_array(value: Any, key: str, allowed: list[str] | None = None) -> list | None:
    """Coerce one filter value to a list.

    A bare scalar is wrapped rather than rejected — models write
    `"publisher": "jlbc"` for a single value constantly, the intent is
    unambiguous, and bouncing it costs a whole turn step for nothing.
    Unknown ENUM members are NOT tolerated, though: a value that isn't in
    the corpus produces zero results with no error, which reads to the
    model as "the corpus doesn't cover this" — the exact silent failure
    the 2026-05-08 enum-drift bug caused.
    """
    if value is None:
        return None
    if isinstance(value, (str, int)) and not isinstance(value, bool):
        value = [value]
    if not isinstance(value, list):
        raise _ArgumentError(f"filters.{key} must be an array.")
    if allowed is not None:
        unknown = [v for v in value if v not in allowed]
        if unknown:
            raise _ArgumentError(
                f"filters.{key} has unknown value(s) {unknown}. Valid values: "
                f"{', '.join(allowed)}. Call list_filter_values to see what "
                "the corpus actually contains."
            )
    return list(value)


def _fiscal_years(value: Any) -> list[int] | None:
    """Fiscal years as REAL integers.

    Worth its own helper because fiscal_year is the most-used filter and
    the failure is invisible: the column is an integer, so a `"2027"`
    string (which models emit constantly, and which JSON happily carries)
    builds a predicate that matches no rows, and the model reads the
    empty result as "the corpus has nothing for FY2027".
    """
    years = _as_array(value, "fiscal_year")
    if years is None:
        return None
    out: list[int] = []
    for year in years:
        if isinstance(year, bool):
            raise _ArgumentError("filters.fiscal_year must contain years, e.g. 2027.")
        if isinstance(year, int):
            out.append(year)
            continue
        try:
            out.append(int(str(year).strip()))
        except ValueError as err:
            raise _ArgumentError(
                f"filters.fiscal_year has a non-numeric entry {year!r} — use "
                "four-digit years, e.g. 2027."
            ) from err
    return out


_FILTER_KEYS = tuple(_FILTERS_SCHEMA["properties"])


def _filters(raw: Any) -> dict[str, Any]:
    """Validate the filters object into RetrievalRequest kwargs."""
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise _ArgumentError("filters must be an object.")
    unknown = [k for k in raw if k not in _FILTER_KEYS]
    if unknown:
        # Silently ignoring an unrecognized filter key is how a search
        # ends up unfiltered while the model believes it was narrowed.
        raise _ArgumentError(
            f"filters has unknown key(s) {unknown}. Valid keys: "
            f"{', '.join(_FILTER_KEYS)}."
        )
    is_table = raw.get("is_table")
    if is_table is not None and not isinstance(is_table, bool):
        raise _ArgumentError("filters.is_table must be true or false.")
    return {
        "fiscal_year": _fiscal_years(raw.get("fiscal_year")),
        "doc_type": _as_array(raw.get("doc_type"), "doc_type", _DOC_TYPES),
        "publisher": _as_array(raw.get("publisher"), "publisher", _PUBLISHERS),
        "agency_canonical_id": _as_array(
            raw.get("agency_canonical_id"), "agency_canonical_id"
        ),
        "fund_canonical_id": _as_array(
            raw.get("fund_canonical_id"), "fund_canonical_id"
        ),
        "is_table": is_table,
    }


_SPREAD_KEYS = tuple(_SPREAD_SCHEMA["properties"])
_SPREAD_AXES = tuple(_SPREAD_SCHEMA["properties"]["by"]["enum"])


def _spread(raw: Any) -> SpreadSpec | None:
    """Validate the spread object into a SpreadSpec, or None when absent.

    Every rejection names the number it violated and what to do instead: a
    model that gets "invalid spread" spends a step guessing, and a step is
    the cost this feature exists to save.
    """
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise _ArgumentError(
            "spread must be an object, e.g. "
            '{"by": "fiscal_year", "groups": [2025, 2026]}.'
        )
    unknown = [k for k in raw if k not in _SPREAD_KEYS]
    if unknown:
        raise _ArgumentError(
            f"spread has unknown key(s) {unknown}. Valid keys: "
            f"{', '.join(_SPREAD_KEYS)}."
        )

    by = raw.get("by")
    if by not in _SPREAD_AXES:
        raise _ArgumentError(
            f"spread.by must be one of: {', '.join(_SPREAD_AXES)}."
        )

    raw_groups = raw.get("groups")
    if not isinstance(raw_groups, list) or not raw_groups:
        raise _ArgumentError(
            "spread.groups must be a non-empty array naming the groups to "
            'search, e.g. {"by": "fiscal_year", "groups": [2025, 2026]}.'
        )
    if len(raw_groups) > SPREAD_MAX_GROUPS:
        raise _ArgumentError(
            f"spread.groups has {len(raw_groups)} entries; at most "
            f"{SPREAD_MAX_GROUPS} are allowed. Narrow the range, or run a "
            "second spread for the rest."
        )

    groups: list = []
    if by == "fiscal_year":
        # The string-"2027" trap, identical to filters.fiscal_year: the
        # column is an integer, so a quoted year matches no rows and the
        # empty group reads to the model as "the corpus has no FY2027".
        for value in raw_groups:
            if isinstance(value, bool):
                raise _ArgumentError(
                    "spread.groups must contain fiscal years, e.g. 2026."
                )
            try:
                groups.append(int(str(value).strip()))
            except (ValueError, AttributeError, TypeError) as err:
                raise _ArgumentError(
                    f"spread.groups has a non-numeric entry {value!r} — with "
                    "by=fiscal_year, use four-digit years, e.g. 2026."
                ) from err
    else:
        for value in raw_groups:
            if not isinstance(value, str) or not value.strip():
                raise _ArgumentError(
                    f"spread.groups has an invalid entry {value!r} — with "
                    "by=doc_id, each entry must be a doc_id string from an "
                    "earlier search result."
                )
            groups.append(value.strip())

    # Duplicates are rejected rather than silently collapsed: the response
    # reports one entry per requested group, so a repeated group would
    # either double a row or quietly return fewer groups than were asked for.
    seen = {g for g in groups}
    if len(seen) != len(groups):
        repeated = sorted({str(g) for g in groups if groups.count(g) > 1})
        raise _ArgumentError(
            f"spread.groups names {', '.join(repeated)} twice. Each group "
            "must appear once — a group is searched separately, so repeating "
            "one buys nothing."
        )

    per_group = raw.get("per_group")
    if per_group is None:
        per_group = SPREAD_DEFAULT_PER_GROUP
    elif isinstance(per_group, bool) or not isinstance(per_group, int):
        raise _ArgumentError(
            f"spread.per_group must be a whole number between "
            f"{SPREAD_MIN_PER_GROUP} and {SPREAD_MAX_PER_GROUP}."
        )
    elif not SPREAD_MIN_PER_GROUP <= per_group <= SPREAD_MAX_PER_GROUP:
        raise _ArgumentError(
            f"spread.per_group is {per_group}; it must be between "
            f"{SPREAD_MIN_PER_GROUP} and {SPREAD_MAX_PER_GROUP}."
        )

    total = len(groups) * per_group
    if total > SPREAD_MAX_TOTAL:
        # The arithmetic is in the message on purpose — "too large" leaves
        # the model to work out which of the two numbers to lower.
        raise _ArgumentError(
            f"spread would return {len(groups)} groups x {per_group} = "
            f"{total} passages; the limit is {SPREAD_MAX_TOTAL}. Lower "
            "per_group or search fewer groups."
        )
    return SpreadSpec(by=by, groups=tuple(groups), per_group=per_group)


def _cite_body(raw: Any, where: str) -> CiteValidateBody:
    """One citation argument object -> the validator's request model."""
    item = _as_object(raw)
    body = CiteValidateBody(
        chunk_id=_req_str(item, "chunk_id"),
        quote=item.get("quote") or None,
        span_start=_opt_int(item, "span_start", 0, 10_000_000),
        span_end=_opt_int(item, "span_end", 1, 10_000_000),
        claim_span=_req_str(item, "claim_span"),
        confidence=_opt_enum(item, "confidence", ["verbatim", "paraphrase"]),
    )
    if body.quote is None and (body.span_start is None or body.span_end is None):
        raise _ArgumentError(
            f"{where} needs either `quote` or both span_start and span_end. "
            "Paste the exact supporting text as `quote` and the offsets are "
            "derived for you."
        )
    return body


# ---------------------------------------------------------------------------
# Filter-value aggregation
# ---------------------------------------------------------------------------
# Ported from retrieval/api.py's /list_values, which cannot be imported
# (it builds a FastAPI app at import time). Consolidating the two into a
# shared module is a Plan 5 item, once the sidecar is retired.

# Projected explicitly: a full-row scan would drag every chunk's text and
# embedding through memory for what is really a metadata question.
_LIST_VALUES_COLUMNS = [
    "doc_id",
    "agency_canonical_ids",
    "fund_canonical_id",
    "doc_type",
    "publisher",
]


def _most_populated_doc(chunks_per_doc: dict[str, int]) -> str:
    """The document contributing the most chunks to one value; ties break
    on lowest doc_id so the same corpus always yields the same sample.

    NOT the newest document: the newest one mentioning almost any agency
    is the FY2027 Governor's Budget, a cross-cutting book touching ~134
    agencies. Sampling it would tell the model nothing about which agency
    `agency:axs` is, which is this field's entire job.
    """
    return min(chunks_per_doc.items(), key=lambda kv: (-kv[1], kv[0]))[0]


def _values_by_chunk(rows: list[dict[str, Any]], values_of) -> list[dict[str, Any]]:
    """Count CHUNKS per value (the agency / fund dimensions). One chunk
    can count toward several agencies — agency ids are an array column."""
    counts: dict[str, int] = {}
    per_doc: dict[str, dict[str, int]] = {}
    for row in rows:
        for value in values_of(row):
            counts[value] = counts.get(value, 0) + 1
            docs = per_doc.setdefault(value, {})
            docs[row["doc_id"]] = docs.get(row["doc_id"], 0) + 1
    samples = {value: _most_populated_doc(docs) for value, docs in per_doc.items()}
    titles = _doc_titles(set(samples.values()))
    return _sorted_values(
        counts, {value: titles[doc_id] for value, doc_id in samples.items()}
    )


def _values_by_document(rows: list[dict[str, Any]], column: str) -> list[dict[str, Any]]:
    """Count DOCUMENTS per value (the doc_type / publisher dimensions).

    Inherited semantics, kept deliberately: these two have always been
    counted as distinct documents rather than chunks, and changing it
    would silently change what the model reads off the same field name.

    The sample title is the ALPHABETICALLY FIRST title in the group
    (`min` over the strings) — deliberately NOT the most-populated-doc
    rule its sibling `_values_by_chunk` uses, and the difference is not
    an oversight. That rule exists to answer "which document is actually
    ABOUT `agency:axs`", because the id itself is opaque. These two
    dimensions have no such question: every document of doc_type `afr`
    is equally an AFR, and the value is already self-describing. All the
    sample owes the model here is a concrete example, so the only
    property that matters is that it is STABLE between calls on the same
    corpus — which alphabetical-first is, and cheaply. (It is also what
    the original SQL's `MIN(title)` did, so the model reads the same
    sample it always has.)
    """
    doc_ids: dict[str, set[str]] = {}
    for row in rows:
        doc_ids.setdefault(row[column], set()).add(row["doc_id"])
    looked_up = _doc_titles({d for ids in doc_ids.values() for d in ids})
    return _sorted_values(
        {value: len(ids) for value, ids in doc_ids.items()},
        {value: min(looked_up[d] for d in ids) for value, ids in doc_ids.items()},
    )


def _sorted_values(
    counts: dict[str, int], titles: dict[str, str]
) -> list[dict[str, Any]]:
    """Most-used first, so a client that truncates keeps the head and
    drops the long tail of one-off ids. Ties break on the id itself so
    the order is stable between calls."""
    return [
        {
            "canonical_id": value,
            "chunk_count": count,
            "sample_doc_title": titles.get(value),
        }
        for value, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


def _dump(payload: dict[str, Any]) -> str:
    """One place that turns a tool result into the string the model reads.

    `ensure_ascii=False` on purpose: document titles are full of em
    dashes and the corpus has the occasional accented name. Escaped as
    `\\u2014` each one costs six characters (and several tokens) of the
    model's context instead of one, in a payload that already carries
    fifteen passages of text. The transport is UTF-8 either way.

    Compact rather than indented — the old implementation pretty-printed
    for debug readability, but nothing reads this raw now (the interface
    parses it) and indentation is pure token cost.
    """
    return json.dumps(payload, ensure_ascii=False)


def _error(message: str) -> str:
    """The one failure envelope. `ok:false` + an actionable message; the
    model is expected to read it and try something different."""
    return _dump({"ok": False, "error": message})


class ToolExecutor:
    """Runs one conversation's tool calls.

    ONE INSTANCE PER CONVERSATION. That is not a style preference: the
    progressive-retrieval cap ("the first search returns a small sample")
    is instance state, and sharing an executor between conversations
    would let one analyst's opening question consume another's cap.

    Collaborators are injectable in the codebase's usual style —
    `store=` mirrors `retrieval.citations`, `materialize=` lets Task 3's
    tests exercise create_document before Task 4 writes it. Passing
    nothing uses the process-wide singletons, which is right: a second
    ChunkStore would open a second set of LanceDB handles against the
    same files on the share.
    """

    def __init__(
        self,
        conversation_id: str,
        corpus: str = "budget",
        tier: str = DEFAULT_TIER,
        *,
        user: str = "",
        display_name: str = "",
        store: Any = None,
        materialize: Callable[..., tuple[str, Any]] | None = None,
    ) -> None:
        self.conversation_id = conversation_id
        self.corpus = resolve_corpus(corpus)
        self.tier = tier
        self.user = user
        # Resolved by the HTTP route, not here: this module's import
        # allowlist forbids `app.*`, and resolving a name means reading
        # per-machine config. Injecting a finished string is what keeps
        # that guard structural rather than a promise (spec M7). Empty is
        # a legitimate value — an unnameable analyst loses attribution on
        # a memo, never the ability to generate one.
        self.display_name = display_name
        self._store = store
        self._materialize = materialize

        budget = TIER_BUDGETS.get(tier)
        if budget is None:
            # Degrade rather than raise: settings.json accepts arbitrary
            # tier names, so an admin adding a third tier must not take
            # down every conversation. Standard is the conservative
            # choice — a mis-typed tier gets the cheap budget, never the
            # expensive one.
            print(
                f"harness.tools: unknown tier {tier!r} — using "
                f"{DEFAULT_TIER!r} effort limits.",
                file=sys.stderr,
            )
            budget = TIER_BUDGETS[DEFAULT_TIER]
        self._deep_dive_allowed = bool(budget["deep_dive_allowed"])

        # Guarded by a lock because a turn may dispatch several tool
        # calls concurrently; only the earliest may win the cap, exactly
        # as the flip-before-the-await did in the old implementation.
        self._lock = threading.Lock()
        self._first_retrieve_pending = True

        # chunk_id -> alias ("c1", "c2", …), assigned at first sight and
        # never reused (spec A1). Monotonic per CONVERSATION, not per
        # turn: reusing c3 for a different chunk while the old c3 is
        # still in the model's history would let a stale tag verify
        # against the wrong text — the exact wrong-doc failure this
        # design exists to remove.
        self._alias_by_chunk: dict[str, str] = {}

    # -- dispatch ---------------------------------------------------------

    def execute(self, name: str, args: Any) -> str:
        """Run one tool call and return its result as a JSON STRING.

        A string because that is what goes into the `{"role": "tool"}`
        message and what the interface renders. Nothing raises: an
        unknown tool, malformed arguments, or a backend that is down all
        come back as `{"ok": false, "error": ...}` so the model can
        recover. An exception here would unwind the tool loop and lose
        the conversation, which is a far worse outcome than a bad answer.
        """
        handler = {
            "retrieve": self._retrieve,
            "cite": self._cite,
            "cite_batch": self._cite_batch,
            "list_filter_values": self._list_filter_values,
            "create_document": self._create_document,
            "document_guide": self._document_guide,
        }.get(name)
        if handler is None:
            return _error(
                f"There is no tool named {name!r}. Available tools: "
                f"{', '.join(TOOL_NAMES)}."
            )
        try:
            return _dump(handler(_as_object(args)))
        except _ArgumentError as err:
            return _error(str(err))
        except Exception as err:  # noqa: BLE001 — see docstring
            # Also say it OUT LOUD. Swallowing the exception is right for
            # the conversation but wrong for the operator: one process
            # serves the whole office, so without this line the only
            # record of a genuine backend failure (a store hiccup, a
            # corrupt table) lives inside one analyst's chat transcript,
            # where nobody will ever grep it. Malformed arguments are
            # deliberately NOT logged above — those are ordinary model
            # traffic and would bury the real failures. The conversation
            # id is included so a log line can be tied back to the
            # transcript that shows what the model did next.
            print(
                f"harness.tools: {name}() failed in conversation "
                f"{self.conversation_id!r} — {type(err).__name__}: {err}",
                file=sys.stderr,
            )
            return _error(
                f"{name}() failed: {type(err).__name__}: {err}. "
                "Tell the analyst this part of the system is unavailable "
                "rather than answering without it."
            )

    def _chunk_store(self):
        """The process-wide ChunkStore unless one was injected.

        `pipeline._get_store()` is private to the retrieval package, not
        across a real boundary — it is the single owner of the LanceDB
        handles, and `reset_default_collaborators()` is its public reset
        hook. Reaching for it in one place keeps every call site here
        consistent (retrieval/api.py does the same for the same reason).
        """
        return self._store if self._store is not None else pipeline._get_store()

    # -- retrieve ---------------------------------------------------------

    @property
    def alias_map(self) -> dict[str, str]:
        """alias -> chunk_id, for the turn-end annotator.

        Inverted on read rather than kept as a second dict: one mapping
        cannot drift from the other, and an alias is only ever resolved
        once per answer.
        """
        with self._lock:
            return {alias: cid for cid, alias in self._alias_by_chunk.items()}

    def _retrieve(self, args: dict[str, Any]) -> dict[str, Any]:
        query = _req_str(args, "query")
        filters = _filters(args.get("filters"))
        top_k = _opt_int(args, "top_k", 1, 50)
        intent = _opt_enum(args, "intent", INTENT_TOP_K)
        deep_dive = _opt_bool(args, "deep_dive")
        spread = _spread(args.get("spread"))

        # One breadth mechanism per call. Rejected rather than ignored: a
        # model that asks for `intent: analyze` and gets 9 grouped passages
        # with nothing saying why is the haunted-tool failure this module's
        # other coercions exist to avoid.
        if spread is not None:
            conflicting = [
                name for name, value in
                (("top_k", top_k), ("intent", intent), ("deep_dive", deep_dive or None))
                if value is not None
            ]
            if conflicting:
                raise _ArgumentError(
                    f"spread cannot be combined with {', '.join(conflicting)} "
                    "— spread already decides how many passages come back "
                    "(groups x per_group). Drop the other argument."
                )

        # S16: Standard tier cannot opt out of the sample. Ignoring the
        # flag silently would leave the model re-asking for a deep dive
        # and never understanding why it kept getting five passages, so
        # the response says what happened.
        deep_dive_ignored = deep_dive and not self._deep_dive_allowed
        effective_deep_dive = deep_dive and self._deep_dive_allowed

        # Claim the first-call cap (and release it) BEFORE any slow work,
        # so concurrent calls in one turn don't all see "first".
        with self._lock:
            is_first = self._first_retrieve_pending
            self._first_retrieve_pending = False
        # Spec N6: a spread call is already self-limiting (groups x per_group
        # <= SPREAD_MAX_TOTAL) and structured, so truncating it to the 5-chunk
        # sample would break its contract and force the extra round the
        # feature exists to remove. It still CONSUMES the slot — it is a real
        # first search. Layer 2 watches `input_tokens_mean` for abuse of this
        # exemption; revert it if the number shows up there.
        capped = is_first and not effective_deep_dive and spread is None

        # Resolution order: the cap overrides everything, then an
        # explicit top_k, then the intent's default, then the pipeline's.
        if capped:
            resolved_top_k = FIRST_CALL_TOP_K_CAP
        elif top_k is not None:
            resolved_top_k = top_k
        elif intent is not None:
            resolved_top_k = INTENT_TOP_K[intent]
        else:
            resolved_top_k = DEFAULT_PIPELINE_TOP_K

        request = RetrievalRequest(
            query=query, top_k=resolved_top_k, corpus=self.corpus, **filters
        )
        # No collaborators injected: the pipeline's process-wide
        # singletons own the store and both ONNX models, and a second set
        # would mean a second copy of the model weights in memory.
        if spread is not None:
            # `top_k` is meaningless here — per_group decides the volume —
            # and the conflict check above has already refused a caller who
            # passed one.
            result = retrieve_spread(request, spread)
        else:
            result = retrieve(request)

        # Under the lock because a turn may dispatch several retrieves
        # concurrently, and two threads minting an alias from the same
        # length would hand one name to two chunks.
        with self._lock:
            for c in result.chunks:
                if c.chunk_id not in self._alias_by_chunk:
                    self._alias_by_chunk[c.chunk_id] = f"c{len(self._alias_by_chunk) + 1}"

        titles = _doc_titles({c.doc_id for c in result.chunks})

        def _group_of(chunk) -> Any:
            """Which spread group this chunk came back in.

            Read off the chunk's own axis value rather than tracked through
            the pipeline: `retrieve_spread` partitions on exactly these two
            attributes, so they cannot disagree with the grouping — and a
            second bookkeeping path could.
            """
            if spread is None:
                return None
            return chunk.fiscal_year if spread.by == "fiscal_year" else chunk.doc_id

        response: dict[str, Any] = {
            "chunks": [
                {
                    "chunk_id": c.chunk_id,
                    # The short handle the model tags figures with
                    # (`[[c3]]`). Short on purpose: it is written after
                    # every figure in the answer, and a full chunk_id
                    # there would cost tokens on every number.
                    "alias": self._alias_by_chunk[c.chunk_id],
                    "doc_id": c.doc_id,
                    "doc_title": titles.get(c.doc_id, ""),
                    "publisher": c.publisher,
                    "fiscal_year": c.fiscal_year,
                    "doc_type": c.doc_type,
                    "section_path": c.section_path,
                    # v1 chunks are single-page, so start == end. Both
                    # fields exist because the interface renders a range.
                    "page_start": c.page,
                    "page_end": c.page,
                    "bbox": c.bbox,
                    "text": c.text,
                    # Saves the model counting characters when it wants
                    # explicit offsets instead of a quote.
                    "text_length": len(c.text or ""),
                    "score": c.score,
                    **({"group": _group_of(c)} if spread is not None else {}),
                }
                for c in result.chunks
            ],
            # Raw cross-encoder logit (roughly -10..10, negatives normal),
            # NOT a 0..1 probability. Compare it against the refusal
            # threshold in the instructions, nothing else.
            "top_score": result.top_score,
            "retrieval_id": str(uuid.uuid4()),
            "bm25_count": result.bm25_count,
            "dense_count": result.dense_count,
            "fused_count": result.fused_count,
        }
        if result.year_coverage:
            # Spec N7: what the pool cap hid — the candidate distribution by
            # fiscal year WITHIN the filters that were in force, which the
            # N11 fields below name. Approximate (pre-rerank), and the prompt
            # says so; it exists so the model can tell "all FY2026 because
            # that is all there is" from "the cap hid the other years".
            # String keys because this is JSON.
            response["year_coverage"] = {
                str(year): count for year, count in sorted(result.year_coverage.items())
            }
        if spread is not None:
            # One entry per REQUESTED group, in request order, including the
            # ones that matched nothing (count 0, top_score null). The model
            # has to be able to tell "FY2020 holds nothing" from "FY2020 was
            # never searched" — see spec N5's error handling.
            response["spread"] = {
                "by": spread.by,
                "groups": list(result.spread_groups),
            }
        if result.inferred_fiscal_years:
            # S21 layer 1. Present ONLY when the pipeline read a fiscal
            # year out of the query text and filtered on it, so the model
            # can tell "these are all FY 2019 because you said FY 2019"
            # apart from "this is everything the corpus has". Absent when
            # the model passed its own filters.fiscal_year — that one it
            # already knows about.
            response["inferred_fiscal_years"] = list(result.inferred_fiscal_years)
        # Spec N11 — the rest of what the pipeline inferred, which it has
        # always computed and this layer always dropped. Same style as the
        # years above: present only when non-empty, so absence means "nothing
        # was guessed".
        if result.inferred_doc_types:
            # A HARD filter guessed from the query text. Today that narrowing
            # is invisible to the model — the "haunted tool" failure named in
            # RetrievalResult's own docstring, in its worse direction: a
            # filter invisibly NOT applied is bad, one invisibly APPLIED is
            # worse, because the model reads a narrowed corpus as the corpus.
            response["inferred_doc_types"] = list(result.inferred_doc_types)
        if result.dropped_filters:
            # Spec Q3's abandoned guess. Without it the model cannot tell
            # "unfiltered because nothing was guessed" from "unfiltered
            # because the guess matched nothing".
            response["dropped_filters"] = list(result.dropped_filters)
        if result.inferred_agencies:
            # NAMED `preferred_agencies` on the wire deliberately. Agency is a
            # ranking PREFERENCE, never a filter (measured: a hard filter
            # costs ~5 points of recall at every cutoff, because the corpus is
            # stamped incompletely and a correct reading of the question can
            # still exclude the answer). Nothing is removed from the results.
            # The field NAME carries that distinction structurally — a future
            # consumer cannot read `preferred_agencies` as a filter, where it
            # could easily misread `inferred_agencies` as one.
            response["preferred_agencies"] = list(result.inferred_agencies)
        if capped:
            # Present ONLY when the cap fired — its absence is how the
            # model knows it got everything it asked for.
            response["first_call_capped"] = True
        if deep_dive_ignored:
            response["deep_dive_ignored"] = True
            response["note"] = (
                "deep_dive is not available on this tier, so this first "
                f"search returned {FIRST_CALL_TOP_K_CAP} passages. Read them, "
                "then search again with a sharper query for more."
            )
        return response

    # -- cite / cite_batch -------------------------------------------------

    def _cite(self, args: dict[str, Any]) -> dict[str, Any]:
        body = _cite_body(args, "cite()")
        return self._cite_result(
            validate_cite(body, corpus=self.corpus, store=self._chunk_store())
        )

    def _cite_batch(self, args: dict[str, Any]) -> dict[str, Any]:
        raw = args.get("citations")
        if raw is None:
            raise _ArgumentError("citations is required and must be an array.")
        if not isinstance(raw, list):
            raise _ArgumentError("citations must be an array of citation objects.")

        # Pre-validate locally so a malformed entry occupies its own slot
        # instead of failing the batch — the model re-pairs results with
        # its arguments BY INDEX, so lengths and order are contractual.
        bodies: list[CiteValidateBody | None] = []
        local_errors: dict[int, str] = {}
        for index, item in enumerate(raw):
            try:
                bodies.append(_cite_body(item, f"citations[{index}]"))
            except _ArgumentError as err:
                bodies.append(None)
                local_errors[index] = str(err)

        # ONE store read for every citation. Each read is a network round
        # trip on the office share (~3s measured); an analyze-shaped
        # answer carries 15-20 cites, so looping validate_cite would put
        # a minute back into the turn. Never replace this with a loop.
        verdicts = validate_cites(
            [b for b in bodies if b is not None],
            corpus=self.corpus,
            store=self._chunk_store(),
        )

        # Stitch verdicts back into their original slots. Defensive on
        # length: the validator guarantees one verdict per body, but if
        # that ever stopped being true we fail closed on the affected
        # slot rather than shifting every later citation onto the wrong
        # claim — a silently mis-paired citation is worse than a rejected
        # one.
        forwarded = [index for index, body in enumerate(bodies) if body is not None]
        verdict_by_slot = {
            slot: verdicts[position] if position < len(verdicts) else None
            for position, slot in enumerate(forwarded)
        }
        out: list[dict[str, Any]] = []
        for index in range(len(bodies)):
            if index in local_errors:
                out.append({"ok": False, "error": local_errors[index]})
                continue
            verdict = verdict_by_slot[index]
            if verdict is None:
                out.append(
                    {"ok": False, "error": "validation returned fewer results than requested"}
                )
                continue
            out.append(self._cite_result(verdict))
        return {"citations": out}

    @staticmethod
    def _cite_result(verdict) -> dict[str, Any]:
        """One validator verdict -> what the model (and the interface) see.

        The citation_id is minted HERE rather than in the validator: the
        validator answers "is this admissible", and an id is only owed to
        an admissible one.
        """
        if not verdict.ok:
            result: dict[str, Any] = {"ok": False, "error": verdict.error or "validation failed"}
            if verdict.chunk_text_length is not None:
                result["chunk_text_length"] = verdict.chunk_text_length
            if verdict.cited_text_preview is not None:
                result["cited_text_preview"] = verdict.cited_text_preview
            return result
        result = {"ok": True, "citation_id": str(uuid.uuid4())}
        # The resolved offsets drive the PDF text-layer highlight. Without
        # them a quote-only citation falls back to a sentinel range that
        # does not point at the cited text, and the viewer shows its
        # "couldn't pinpoint this" badge instead of a highlight.
        if verdict.resolved_span_start is not None:
            result["resolved_span_start"] = verdict.resolved_span_start
        if verdict.resolved_span_end is not None:
            result["resolved_span_end"] = verdict.resolved_span_end
        if verdict.truncated:
            result["truncated"] = True
        return result

    # -- list_filter_values ------------------------------------------------

    def _list_filter_values(self, args: dict[str, Any]) -> dict[str, Any]:
        field = _req_str(args, "field").strip().lower()
        if field not in ("agency", "fund", "doc_type", "publisher"):
            raise _ArgumentError(
                f"unknown field {field!r} — must be one of 'agency', "
                "'doc_type', 'publisher', 'fund'."
            )
        rows = self._chunk_store().scan(self.corpus, _LIST_VALUES_COLUMNS)
        if field == "agency":
            values = _values_by_chunk(rows, lambda r: r["agency_canonical_ids"] or [])
            # Real names when the catalog is available — the sample title
            # only implies what an id means; the catalog states it.
            names = _agency_names()
            for value in values:
                name = names.get(value["canonical_id"])
                if name:
                    value["name"] = name
        elif field == "fund":
            # Nullable column: a NULL must never become a value literally
            # named "None".
            values = _values_by_chunk(
                rows,
                lambda r: [r["fund_canonical_id"]] if r["fund_canonical_id"] else [],
            )
        else:
            values = _values_by_document(rows, field)
        return {"field": field, "values": values}

    # -- create_document ---------------------------------------------------

    def _create_document(self, args: dict[str, Any]) -> dict[str, Any]:
        title = _req_str(args, "title")
        body_markdown = _req_str(args, "body_markdown")
        fmt = _opt_enum(args, "format", ["docx", "md"]) or "docx"

        materialize = self._materialize
        if materialize is None:
            # Imported lazily so this module stays importable (and this
            # task's tests runnable) before Task 4 writes harness/documents.py.
            from harness.documents import materialize  # type: ignore[no-redef]

        # The model supplies content, a title and — when the analyst named
        # one — an audience; it never supplies a destination. Invariant 7
        # lives or dies on that split. The SENDER is not the model's to
        # choose either: it is the finished string injected at
        # construction, so no answer text can put a name on a memo.
        token, path = materialize(
            title,
            body_markdown,
            fmt,
            user=self.user,
            sender=self.display_name,
            recipient=_opt_str(args, "to"),
        )
        return {"ok": True, "download_token": token, "filename": path.name}

    # -- document_guide ----------------------------------------------------

    def _document_guide(self, args: dict[str, Any]) -> dict[str, Any]:
        """House guidance for a document the model is about to write.

        Reads nothing, writes nothing, costs nothing — the only tool here
        that touches neither the store nor the model's own output.

        `report_type` echoes back the type ACTUALLY used, not the one
        requested. Reflecting the request instead would tell a model it
        got `comparison` guidance when it got the default, so a document
        written to the wrong shape would look correct to the thing that
        wrote it.

        `_opt_str` rather than `_opt_enum`, deliberately: the schema's
        enum is advice to the model, and a value outside it must resolve
        to the default rather than raise. Models emit `null` and invented
        type names routinely, and there is nothing a model can usefully
        do with "unknown report type" except spend a step guessing again.
        """
        requested = _opt_str(args, "report_type")
        resolved = requested if requested in REPORT_TYPES else DEFAULT_REPORT_TYPE
        return {"ok": True, "report_type": resolved, "guide": guide_for(resolved)}
