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
    INTENT_TOP_K,
    REFUSAL_THRESHOLD,
    TIER_BUDGETS,
)

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
# name both accepted, normalized here. Duplicated from
# `harness.tools.resolve_corpus` ON PURPOSE: importing that module pulls
# in retrieval + store + the model weights, which is absurd for a
# two-entry dict, and this file must stay cheap to import.
_CORPUS_ALIASES = {
    "budget": "budget",
    "budget_chunks": "budget",
    "fiscal_notes": "fiscal_notes",
    "fiscal_note_chunks": "fiscal_notes",
}

# `{{#when corpus=budget}}` … `{{/when}}` — a whole-line marker so a
# conditional block can wrap markdown table rows without disturbing them.
_WHEN_OPEN = re.compile(r"^\{\{#when (corpus|tier)=([a-z_]+)\}\}\s*$")
_WHEN_CLOSE = re.compile(r"^\{\{/when\}\}\s*$")
_PLACEHOLDER = re.compile(r"\{\{([A-Z_]+)\}\}")

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
    """
    kept: list[str] = []
    open_marker: tuple[str, str] | None = None
    keeping = True
    for number, line in enumerate(template.splitlines(), start=1):
        opened = _WHEN_OPEN.match(line)
        if opened:
            if open_marker is not None:
                raise PromptTemplateError(
                    f"{TEMPLATE_PATH}:{number}: `{{{{#when}}}}` blocks cannot "
                    "nest; close the one opened above first."
                )
            key, value = opened.group(1), opened.group(2)
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
        if keeping:
            kept.append(line)
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


def build_system_prompt(*, corpus: str, tier: str) -> str:
    """The full instructions for one conversation's corpus and tier.

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
    return _substitute(
        selected,
        {
            "REFUSAL_THRESHOLD": str(REFUSAL_THRESHOLD),
            "FIRST_CALL_TOP_K_CAP": str(FIRST_CALL_TOP_K_CAP),
            "LOOKUP_TOP_K": str(INTENT_TOP_K["lookup"]),
            "COMPARE_TOP_K": str(INTENT_TOP_K["compare"]),
            "ANALYZE_TOP_K": str(INTENT_TOP_K["analyze"]),
            "MAX_STEPS": str(TIER_BUDGETS[resolved_tier]["max_steps"]),
        },
    )
