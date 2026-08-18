"""The [[cN]] marker grammar — the model's inline provenance claims.

A marker is a HYPOTHESIS the system verifies, never a fact (spec A2). It
must strip out of every consumer-visible string: an analyst seeing [[c3]]
in an answer is a P1 bug, so stripping is deliberately greedy about
malformed shapes — anything that starts like a marker is removed even
when it cannot be parsed into a Tag.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Well-formed: [[c3]] or [[c3, c12]]. Only c<digits> aliases — [[A.R.S.
# 35-142]] is legislative prose, not a marker, and must survive.
#
# The per-alias separator also allows an optional `]` before the comma and
# an optional `[` after it, so `[[c3],[c4]]` and `[[c3], [c4]]` parse as
# multi-alias markers instead of leaking their tail (`,[c4]]`) into the
# answer. Real models emit this bracket-wrapped form under load, and a
# leaked marker is a P1 UI bug. The stray brackets are stripped from each
# alias when the tag is built (see `_clean_alias`).
_WELL_FORMED = r"\[\[\s*(?P<aliases>c\d+(?:\s*\]?\s*,\s*\[?\s*c\d+)*)\s*\]\]"
# Unterminated bracket-wrapped chain at end of text — a streaming frame
# that has only emitted "[[c3],"/"[[c3],[c4" so far, or a final answer cut
# there by max_tokens. The greedy-strip rule applies: starts like a marker
# → removed whole. Tried BEFORE the generic malformed form so the generic
# one cannot stop at the first `]` and leak the ", [c4" tail. The trailing
# `[? c\d*` also swallows a cut mid-alias-name ("[[c3],[c" — the `[c` has
# no digits yet). No Tag is built — an unterminated marker yields no
# readable aliases anyway.
_UNTERMINATED = (
    r"\[\[\s*c\d+(?:\s*\]?\s*,\s*\[?\s*c\d+)*\s*\]?\s*,?\s*(?:\[?\s*c\d*)?$"
)
# Malformed-but-marker-like: starts [[c<digit>, ends in ] or ]] with junk
# inside, or runs unterminated to end of text.
_MALFORMED = r"\[\[\s*c\d+[^\]\n]*(?:\]{1,2}|$)"
_ANY_MARKER = re.compile(f"{_WELL_FORMED}|{_UNTERMINATED}|{_MALFORMED}")

# `[[c3],[c4]]` puts the c<digits> tokens between stray `]`/`[` separators;
# the well-formed capture group keeps those brackets to stay unambiguous
# about where one alias ends. They are dropped here so downstream alias
# resolution still sees bare `c3`, `c4` names.
def _clean_alias(alias: str) -> str:
    return alias.strip().strip("[]")

# For the stream: any trailing prefix that COULD still become a marker is
# held back. The delta frames carry full accumulated text, so held-back
# characters reappear the moment they resolve into (non-)marker text.
_TRAILING_PARTIAL = re.compile(r"\[{1,2}\s*(?:c\d*)?$")

# Horizontal space only. A newline is never swallowed — collapsing
# "[[c3]]\n\n" would merge two paragraphs of the answer.
_SPACE = " \t"


@dataclass(frozen=True)
class Tag:
    aliases: tuple[str, ...]
    at: int  # offset in the STRIPPED text where the marker began


def parse_markers(raw: str) -> tuple[str, list[Tag]]:
    """Strip every marker-like span; return stripped text + parsed tags.

    Tag offsets index the stripped text because that is the string every
    downstream consumer (figure extractor, UI, transcripts) sees — an
    offset into the raw text would be off by the width of every earlier
    marker.
    """
    out: list[str] = []
    tags: list[Tag] = []
    pos = 0
    removed = 0
    for m in _ANY_MARKER.finditer(raw):
        out.append(raw[pos:m.start()])
        aliases = m.group("aliases")
        if aliases:
            parts = tuple(_clean_alias(a) for a in aliases.split(","))
            tags.append(Tag(aliases=parts, at=m.start() - removed))
        end = m.end()
        # The model writes "million [[c3]] this", so removing the marker
        # alone leaves a double space in the rendered answer. Swallow ONE
        # trailing space — but only when the marker was itself preceded by
        # one, or "$8.2M[[c3]]and" would fuse into "$8.2Mand".
        if (m.start() > 0 and raw[m.start() - 1] in _SPACE
                and end < len(raw) and raw[end] in _SPACE):
            end += 1
        removed += end - m.start()
        pos = end
    out.append(raw[pos:])
    return "".join(out), tags


def strip_for_stream(text: str) -> str:
    """What a streaming frame may show: complete markers removed, a
    trailing could-be-marker prefix held back."""
    stripped, _ = parse_markers(text)
    return _TRAILING_PARTIAL.sub("", stripped)
