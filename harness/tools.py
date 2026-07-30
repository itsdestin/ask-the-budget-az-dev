"""The five tools the model can call, as in-process Python (Plan 4, S2).

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
    INTENT_TOP_K,
    REFUSAL_THRESHOLD,
    TIER_BUDGETS,
)
from retrieval import DEFAULT_PIPELINE_TOP_K, RetrievalRequest, pipeline, retrieve
from retrieval.citations import CiteValidateBody, validate_cite, validate_cites
from store.chunk_store import CORPUS_TABLES
from store.config import documents_path

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
# WHY a local copy of this cache: the same lookup lives in
# `retrieval/api.py`, but importing that module builds a FastAPI app at
# import time — the harness would drag the entire retired sidecar in just
# to read a JSON file. `app/search_provider.py` has a third variant.
# Three copies is one too many; the right home is a `store/documents.py`
# next to `documents_path()`, and consolidating them is a Plan 5 item
# (this task may not touch `store/`). Until then the shapes are kept
# deliberately identical so they cannot drift in behavior.

_docs_lock = threading.Lock()
_docs_cache: dict[str, dict[str, Any]] = {}
# (path, mtime, size) of the file the cache was built from. Comparing all
# three invalidates the cache both when the file is rewritten AND when
# JLBC_DATA_DIR is repointed at a different corpus.
_docs_stamp: tuple[str, float, int] | None = None


def reset_document_title_cache() -> None:
    """Test-only: force the next lookup to re-stat and re-parse."""
    global _docs_cache, _docs_stamp
    with _docs_lock:
        _docs_cache, _docs_stamp = {}, None


def _document_metadata() -> dict[str, dict[str, Any]]:
    """Parsed documents.json, cached until the file changes on disk.

    Reload is mtime+size based rather than load-once-at-startup so an
    ingest (or a `--docs-only` refresh) shows up without restarting the
    server. A missing file is normal and returns {}; a malformed one
    warns to stderr and also returns {}, because degrading to derived
    titles beats failing every search.
    """
    global _docs_cache, _docs_stamp
    path = documents_path()
    try:
        st = path.stat()
        stamp: tuple[str, float, int] | None = (str(path), st.st_mtime, st.st_size)
    except OSError:
        stamp = None  # absent or unreadable — fall back silently
    with _docs_lock:
        if stamp == _docs_stamp:
            return _docs_cache
        if stamp is None:
            _docs_cache, _docs_stamp = {}, None
            return _docs_cache
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict):
                raise ValueError(
                    "expected a JSON object of doc_id -> metadata, got "
                    f"{type(loaded).__name__}"
                )
        except (OSError, ValueError) as err:
            print(
                f"harness.tools: ignoring {path} ({err}) — document titles fall "
                "back to doc_id slugs. Rebuild it with: uv run python "
                "scripts/migrate_to_lancedb.py --docs-only",
                file=sys.stderr,
            )
            loaded = {}
        _docs_cache, _docs_stamp = loaded, stamp
        return _docs_cache


# Slug parts that are acronyms, not words — .capitalize() would render
# them "Jlbc" / "Afr". Kept character-identical to the copies in
# retrieval/api.py and app/search_provider.py so no two layers ever show
# a different title for the same document.
_SLUG_ACRONYMS = ("jlbc", "agao", "afr", "sad")


def _title_from_doc_id(doc_id: str) -> str:
    """FALLBACK ONLY: 'jlbc-baseline-fy2027-axs' -> 'JLBC Baseline FY 2027
    Axs'. The real ingest title ('JLBC FY2026 — AHCCCS') is much better,
    which is why documents.json wins whenever it knows the doc."""
    out: list[str] = []
    for part in doc_id.split("-"):
        if part.startswith("fy") and part[2:].isdigit():
            out.append(f"FY {part[2:]}")
        elif part in _SLUG_ACRONYMS:
            out.append(part.upper())
        else:
            out.append(part.capitalize())
    return " ".join(out)


def _doc_titles(doc_ids: Iterable[str]) -> dict[str, str]:
    """doc_id -> display title, real title preferred, slug as fallback."""
    docs = _document_metadata()
    return {
        doc_id: (docs.get(doc_id, {}).get("title") or _title_from_doc_id(doc_id))
        for doc_id in doc_ids
    }


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
_DOC_TYPES = [
    "baseline-per-agency",
    "approps-per-agency",
    "s-pdf",
    "bd-pdf",
    "bh-pdf",
    "detailed-list-pdf",
    "topic-pdf",
    "afr",
    "governors-budget",
    "budget-bill",
    # Added for Plan 3's fiscal-note corpus.
    "fiscal-note",
]

_PUBLISHERS = ["jlbc", "legislature", "governor", "agao"]

_FILTERS_SCHEMA = {
    "type": "object",
    "description": "Optional filters to narrow the search.",
    "additionalProperties": False,
    "properties": {
        "fiscal_year": {
            "type": "array",
            "items": {"type": "integer", "minimum": 2015, "maximum": 2030},
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
            "bullets, bold and pipe tables are rendered. You name the "
            "document by TITLE only; where it is saved is not yours to "
            "choose. Returns a download token the interface turns into a "
            "link."
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

# Tuple, not list: this is a process-wide global handed to every request
# builder, and one caller doing `TOOLS.append(...)` would change what
# every conversation in the office sees.
TOOLS: tuple[dict[str, Any], ...] = (
    _RETRIEVE_SCHEMA,
    _CITE_SCHEMA,
    _CITE_BATCH_SCHEMA,
    _LIST_FILTER_VALUES_SCHEMA,
    _CREATE_DOCUMENT_SCHEMA,
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
        store: Any = None,
        materialize: Callable[..., tuple[str, Any]] | None = None,
    ) -> None:
        self.conversation_id = conversation_id
        self.corpus = resolve_corpus(corpus)
        self.tier = tier
        self.user = user
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

    def _retrieve(self, args: dict[str, Any]) -> dict[str, Any]:
        query = _req_str(args, "query")
        filters = _filters(args.get("filters"))
        top_k = _opt_int(args, "top_k", 1, 50)
        intent = _opt_enum(args, "intent", INTENT_TOP_K)
        deep_dive = _opt_bool(args, "deep_dive")

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
        capped = is_first and not effective_deep_dive

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
        result = retrieve(request)

        titles = _doc_titles({c.doc_id for c in result.chunks})
        response: dict[str, Any] = {
            "chunks": [
                {
                    "chunk_id": c.chunk_id,
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

        # The model supplies content and a title; it never supplies a
        # destination. Invariant 7 lives or dies on that split.
        token, path = materialize(title, body_markdown, fmt, user=self.user)
        return {"ok": True, "download_token": token, "filename": path.name}
