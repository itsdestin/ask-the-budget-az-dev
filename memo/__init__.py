"""Render Markdown as a JLBC memo.

The one public entry point is `render()`. It returns a `Document`; it does
not save, does not name a file, and does not know who is asking. See
`docs/superpowers/specs/2026-08-12-jlbc-memo-formatting-design.md`.
"""
from __future__ import annotations

from docx.document import Document as DocumentT

from memo import markdown, style

__all__ = ["render"]


def render(
    body_markdown: str,
    *,
    subject: str,
    sender: str = "",
    recipient: str = "",
    date: str | None = None,
) -> DocumentT:
    """Build the memo.

    Every argument is a finished string. Resolving who the analyst is and
    what today's date is happens at the HTTP boundary, not here — that
    split is what keeps this module free of any path to identity or to the
    shared drive (spec M7).
    """
    doc = style.new_document()
    style.add_masthead(doc)
    style.add_rule(doc)
    style.add_memo_block(
        doc,
        date=date or style.today_long(),
        recipient=recipient,
        sender=sender,
        subject=subject,
    )
    markdown.render_body(doc, body_markdown)
    return doc
