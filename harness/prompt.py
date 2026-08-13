"""Builds the system prompt the model reads (Plan 4, Task 7).

The prose lives next door in `system-prompt.md`; this module only turns
that template into the exact string one conversation gets. Two things
vary and nothing else does:

* **corpus** — one registry of tools serves two corpora, and the tool
  descriptions are deliberately corpus-neutral (see `harness/tools.py`).
  Naming which corpus is in scope is therefore THIS file's job, and a
  fiscal-note conversation must not be handed the budget corpus's
  document-lifecycle machinery: telling it to choose between
  `baseline-per-agency` and `approps-per-agency` would filter it to zero
  results and read as "the corpus has nothing".
* **tier** — S16's Standard / Deep Research split. The posture differs
  (answer from the first sample vs. search iteratively), and so does the
  step budget the model is allowed to spend, so the model is told which
  one it is in. `session.py` caches per tier for exactly this reason.

Numbers are INJECTED, never typed into the markdown. Before
`harness/constants.py` existed, three different refusal thresholds
reached the model at once (0.30 in a tool description, 0.65 in stale
comments, 1.9 in the prompt) and nobody could say which one it obeyed.
The template carries `{{REFUSAL_THRESHOLD}}`; the value comes from the
one module that owns it, and `tests/test_harness_prompt.py` fails if a
literal ever sneaks back in.

Deliberately light on imports (stdlib + `harness.constants`): building a
prompt must not drag LanceDB, the ONNX models, or a provider client into
a process that only wanted a string.
"""
from __future__ import annotations

import re
import threading
from pathlib import Path

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
    TIER_BUDGETS,
)
from harness.office_guidance import office_guidance_block

# Module-level (not a constant inside the function) so tests can repoint
# it. `__file__`-relative is safe for this app's shipping shape: S7
# unpacks a zip to %LOCALAPPDATA%, so the markdown sits next to this
# module on disk in both dev and install.
TEMPLATE_PATH = Path(__file__).with_name("system-prompt.md")


class PromptTemplateError(RuntimeError):
    """The template is missing or malformed.

    Its own type because the two audiences differ: a missing file is an
    INSTALL problem an operator can fix (hence the reinstall hint in the
    message), while a bad marker is a template-authoring bug that must
    fail loudly in tests rather than silently drop a section of the
    model's instructions.
    """


# Wire name (what the HTTP contract and session.py use) and LanceDB table
# name both accepted, normalized here.
#
# NOT a copy of `harness.tools.resolve_corpus`, and do not "de-duplicate"
# them: the two accept the same input spellings but normalize in OPPOSITE
# directions. tools resolves to the LanceDB TABLE name because that is
# what it queries; this file resolves to the short WIRE name because that
# is what the template's `{{#when corpus=…}}` markers read. A separate
# table exists here rather than an import because importing tools pulls
# in retrieval + store + the model weights, which is absurd for a
# four-entry dict, and this file must stay cheap to import.
_CORPUS_ALIASES = {
    "budget": "budget",
    "budget_chunks": "budget",
    "fiscal_notes": "fiscal_notes",
    "fiscal_note_chunks": "fiscal_notes",
}

# `{{#when corpus=budget}}` … `{{/when}}` — a whole-line marker so a
# conditional block can wrap markdown table rows without disturbing them.
_WHEN_OPEN = re.compile(r"^\{\{#when (corpus|tier)=([a-z_]+)\}\}\s*$")
# Anything that MEANT to be an open marker. Without this, a typo'd key
# simply fails to match, the line survives as literal prose, and the
# error surfaces on the `{{/when}}` several dozen lines below — sending
# the author to inspect the one line that was correct.
_WHEN_OPEN_LOOSE = re.compile(r"^\s*\{\{#when\b.*\}\}\s*$")
_WHEN_CLOSE = re.compile(r"^\{\{/when\}\}\s*$")
# Same courtesy on the closing side: `{{ /when}}` would otherwise become
# prose and the failure would be reported against the (correct) opening
# line, dozens of lines above.
_WHEN_CLOSE_LOOSE = re.compile(r"^\s*\{\{\s*/\s*when\b.*\}\}\s*$")
# `{{OFFICE_GUIDANCE}}` (spec E2) is excluded here and handled by its own
# whole-line substitution in `_insert_office_guidance`, run AFTER this
# generic pass — not through the values dict like every other placeholder.
# Two reasons: (1) the admin's guidance is free-form markdown a
# non-developer typed, and if it were spliced in BEFORE this regex runs, a
# stray literal "{{" in the admin's own prose would be re-scanned as a
# template placeholder and raise PromptTemplateError, taking down prompt
# building office-wide over admin content, not a template bug; (2) an
# empty block must delete the marker's WHOLE LINE (so a guidance-less
# office renders byte-identical to today), and a plain token substitution
# like every other placeholder gets would only blank the token, leaving a
# permanent stray blank line forever.
_PLACEHOLDER = re.compile(r"\{\{(?!OFFICE_GUIDANCE\}\})([A-Z_]+)\}\}")
# The marker's own line, including its trailing newline, so replacing it
# can remove the line entirely (empty guidance) or splice the block in
# with no extra bytes on either side (non-empty guidance) — see
# `_insert_office_guidance`.
_OFFICE_GUIDANCE_LINE = re.compile(r"^\{\{OFFICE_GUIDANCE\}\}\n", re.MULTILINE)

# What `{{CORPUS_MAP}}` renders as when the caller supplies nothing (spec
# N2). A missing sidecar must degrade to a sentence, never to a crashed
# conversation and never to an EMPTY section — a heading that says "what
# this corpus contains" followed by nothing reads to the model as "it
# contains nothing", which the map's own guidance line would then have it
# repeat to an analyst.
CORPUS_MAP_FALLBACK = (
    "(The corpus inventory is unavailable right now. Use list_filter_values "
    "to check what exists before concluding the corpus lacks something.)"
)

# What a block marker may switch on. Derived from the same two sources
# the renderer resolves against, so adding a tier to constants.py or a
# corpus above cannot leave the validator behind.
_BLOCK_VALUES: dict[str, set[str]] = {
    "corpus": set(_CORPUS_ALIASES.values()),
    "tier": set(TIER_BUDGETS),
}

_lock = threading.Lock()
# (path, text) of the template already read. Cached because this is read
# once per (corpus, tier) per conversation in a server that serves the
# whole office, and the file is ~900 lines.
_template: tuple[Path, str] | None = None


def reset_template_cache() -> None:
    """Test-only: force the next build to re-read the file from disk."""
    global _template
    with _lock:
        _template = None


def _read_template(path: Path) -> str:
    """Separate function so the tests can count disk reads."""
    return path.read_text(encoding="utf-8")


def _load_template() -> str:
    global _template
    path = TEMPLATE_PATH
    with _lock:
        if _template is not None and _template[0] == path:
            return _template[1]
        try:
            text = _read_template(path)
        except OSError as err:
            raise PromptTemplateError(
                f"The assistant's instructions file is missing or unreadable "
                f"({path}: {err}). AI Mode cannot run without it — reinstall "
                "the application to restore it."
            ) from err
        if not text.strip():
            raise PromptTemplateError(
                f"The assistant's instructions file is empty ({path}). AI Mode "
                "cannot run without it — reinstall the application to restore it."
            )
        _template = (path, text)
        return text


def _select_blocks(template: str, context: dict[str, str]) -> str:
    """Drop the `{{#when …}}` blocks that don't apply to this conversation.

    Line-based and non-nesting on purpose. A fancier templating language
    would be a second thing to get wrong in the file that determines
    answer quality; a marker on its own line is something a reviewer can
    check by eye.

    Markers inside a fenced code block are TEXT, not directives. The
    template is prose maintained over years, and "let me document how
    this `{{#when}}` syntax works" with a fenced example is an ordinary
    edit; executing that example would swallow either the sample block or
    the marker lines, leaving no `{{` behind for anything to notice. An
    unbalanced fence raises for the same reason — after it, every real
    marker would quietly become prose.
    """
    kept: list[str] = []
    open_marker: tuple[str, str] | None = None
    keeping = True
    fence_opened_at: int | None = None
    for number, line in enumerate(template.splitlines(), start=1):
        if line.strip().startswith("```"):
            fence_opened_at = None if fence_opened_at is not None else number
            if keeping:
                kept.append(line)
            continue
        if fence_opened_at is not None:
            if keeping:
                kept.append(line)
            continue
        opened = _WHEN_OPEN.match(line)
        if opened is None and _WHEN_OPEN_LOOSE.match(line):
            raise PromptTemplateError(
                f"{TEMPLATE_PATH}:{number}: {line.strip()} is not a valid "
                "block marker. Write `{{#when corpus=<name>}}` or "
                "`{{#when tier=<name>}}` on a line of its own."
            )
        if opened:
            if open_marker is not None:
                raise PromptTemplateError(
                    f"{TEMPLATE_PATH}:{number}: `{{{{#when}}}}` blocks cannot "
                    "nest; close the one opened above first."
                )
            key, value = opened.group(1), opened.group(2)
            if value not in _BLOCK_VALUES[key]:
                # A valid-looking marker with a misspelled VALUE matches
                # nothing, so its block would vanish from every rendering
                # with no error — a silent hole in the model's
                # instructions is the worst failure this file has.
                raise PromptTemplateError(
                    f"{TEMPLATE_PATH}:{number}: unknown {key} {value!r} in a "
                    f"block marker. Valid values: "
                    f"{', '.join(sorted(_BLOCK_VALUES[key]))}."
                )
            open_marker = (key, value)
            keeping = context[key] == value
            continue
        if _WHEN_CLOSE.match(line):
            if open_marker is None:
                raise PromptTemplateError(
                    f"{TEMPLATE_PATH}:{number}: `{{{{/when}}}}` with no open block."
                )
            open_marker, keeping = None, True
            continue
        if _WHEN_CLOSE_LOOSE.match(line):
            raise PromptTemplateError(
                f"{TEMPLATE_PATH}:{number}: {line.strip()} is not a valid "
                "closing marker. Write `{{/when}}` exactly, on a line of "
                "its own."
            )
        if keeping:
            kept.append(line)
    if fence_opened_at is not None:
        raise PromptTemplateError(
            f"{TEMPLATE_PATH}:{fence_opened_at}: this code fence is never "
            "closed. Every ``` needs a matching ```, or the block markers "
            "after it stop being read as markers."
        )
    if open_marker is not None:
        raise PromptTemplateError(
            f"{TEMPLATE_PATH}: unclosed `{{{{#when "
            f"{open_marker[0]}={open_marker[1]}}}}}` block — everything after "
            "it would be dropped from the model's instructions."
        )
    return "\n".join(kept).rstrip() + "\n"


def _substitute(text: str, values: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in values:
            # Silently leaving it would ship `{{REFUSAL_THRESHOLD}}` to
            # the model as the number to compare against.
            raise PromptTemplateError(
                f"{TEMPLATE_PATH}: unknown placeholder {{{{{name}}}}}. Known "
                f"placeholders: {', '.join(sorted(values))}."
            )
        return values[name]

    return _PLACEHOLDER.sub(replace, text)


def _insert_office_guidance(text: str, block: str) -> str:
    """Splice the admin's block (spec E2) into its slot.

    Runs LAST — after `_substitute` has already validated every real
    template placeholder — so the admin's own free-form text is never fed
    back through `_PLACEHOLDER`. `block` replaces the marker's entire line
    (including its trailing newline) verbatim: empty removes the line so a
    guidance-less office renders byte-identical to a template with the
    slot removed outright; non-empty splices in exactly `block`'s bytes,
    no more, so `prompt.replace(office_guidance_block(), "")` recovers the
    empty rendering exactly (pinned by
    `tests/test_office_guidance.py::test_prompt_is_byte_identical_when_guidance_absent`).
    """
    # WHY a callable replacement and not the string `block` directly: this
    # is load-bearing, not stylistic. `re.sub`'s STRING form interprets
    # `\1`, `\g<x>`, and a trailing backslash in the REPLACEMENT as
    # backreference syntax — and admin prose can contain any of those by
    # accident (a numbered note "\1) …", a UNC path ending in a
    # backslash). A trailing backslash there raises `re.error` outright,
    # which would take down prompt building office-wide over admin
    # content. A callable replacement's return value is inserted
    # literally, with no such interpretation.
    return _OFFICE_GUIDANCE_LINE.sub(lambda _match: block, text, count=1)


def build_system_prompt(
    *, corpus: str, tier: str, corpus_map: str | None = None
) -> str:
    """The full instructions for one conversation's corpus and tier.

    `corpus_map` is the inventory table built by `harness.corpus_map` and
    passed in by the caller (spec N2) — this module must not learn to read
    the corpus itself. Omitted or empty renders CORPUS_MAP_FALLBACK.

    `corpus` accepts the wire name (`budget` / `fiscal_notes`) or the
    LanceDB table name. An unrecognized corpus RAISES — that is a wiring
    bug at the call site, and answering a fiscal-note question under the
    budget corpus's instructions is a far worse outcome than a failed
    turn with a readable error. An unrecognized TIER does not raise: tier
    names come from settings.json, where a typo is an admin's, and
    `harness/tools.py` degrades the same way for the same reason —
    Standard is the conservative default.
    """
    resolved_corpus = _CORPUS_ALIASES.get(corpus)
    if resolved_corpus is None:
        raise ValueError(
            f"Unknown corpus {corpus!r}. Valid names are: "
            f"{', '.join(sorted(_CORPUS_ALIASES))}."
        )
    resolved_tier = tier if tier in TIER_BUDGETS else DEFAULT_TIER

    selected = _select_blocks(
        _load_template(), {"corpus": resolved_corpus, "tier": resolved_tier}
    )
    substituted = _substitute(
        selected,
        {
            "CORPUS_MAP": corpus_map or CORPUS_MAP_FALLBACK,
            "REFUSAL_THRESHOLD": str(REFUSAL_THRESHOLD),
            "FIRST_CALL_TOP_K_CAP": str(FIRST_CALL_TOP_K_CAP),
            "LOOKUP_TOP_K": str(INTENT_TOP_K["lookup"]),
            "COMPARE_TOP_K": str(INTENT_TOP_K["compare"]),
            "ANALYZE_TOP_K": str(INTENT_TOP_K["analyze"]),
            "MAX_STEPS": str(TIER_BUDGETS[resolved_tier]["max_steps"]),
            "FISCAL_YEAR_MIN": str(FISCAL_YEAR_MIN),
            "FISCAL_YEAR_MAX": str(FISCAL_YEAR_MAX),
            # Injected for the same reason as the threshold above: the tool
            # schema and the coercion's error messages state these caps too,
            # and a number typed into the prose drifts silently.
            "SPREAD_MAX_GROUPS": str(SPREAD_MAX_GROUPS),
            "SPREAD_MAX_PER_GROUP": str(SPREAD_MAX_PER_GROUP),
            "SPREAD_DEFAULT_PER_GROUP": str(SPREAD_DEFAULT_PER_GROUP),
            "SPREAD_MAX_TOTAL": str(SPREAD_MAX_TOTAL),
        },
    )
    # The admin's block (spec E2), spliced in last — see
    # `_insert_office_guidance` for why it cannot go through the generic
    # `_substitute` values dict above. Dynamic content in a "pure" prompt
    # is safe here because session.py memoizes per conversation — a
    # mid-conversation edit never changes a live cache prefix; new
    # conversations pick it up (and the admin UI says exactly that).
    return _insert_office_guidance(substituted, office_guidance_block())
