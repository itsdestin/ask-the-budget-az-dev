"""Build a document's display name, and settle supplier disagreements.

Spec I5 (one format, and it must be unique) and I1 (two witnesses).

WHY the stamp beats the supplier: measured 2026-08-16 over the 218
mis-titled documents, the agency STAMP was correct in every case where the
TITLE was wrong (`jlbc-approps-fy2005-bar` is stamped `agency:bar` and
titled "Agriculture"). The document already knows who it is; only the field
taken from a third party is wrong.

WHY an uncorroborated stamp does NOT overrule the supplier: that is one
witness, and one witness is precisely today's behaviour and the cause of
every finding in the audit. Where the stamp is the broken witness — the 721
`ost` documents — composing from it would write the error into the title.
"""
from __future__ import annotations

from identity.validator import distinctive_words, validate_name


def compose_title(
    *,
    name: str,
    fiscal_year: int,
    book: str,
    distinguisher: str | None = None,
) -> str:
    """`{Name} — FY {year} {Book}`, raising on a name that cannot be trusted.

    Raises `ValueError` if EITHER `name` or `distinguisher` fails
    `validate_name` — the same refusal applies to both arguments, because a
    guessed-at distinguisher writes the same class of corruption into the
    title that a guessed-at name would. This is not a hard failure of
    ingest: a bad name must never block a document from being ingested, so
    callers are expected to catch this, fall back to an uncomposed title,
    and record an advisory note rather than let the raise propagate.
    """
    verdict = validate_name(name)
    if not verdict.ok:
        raise ValueError(f"unusable name {name!r}: {verdict.reason}")
    stem = verdict.value
    if distinguisher:
        d = validate_name(distinguisher)
        if not d.ok:
            raise ValueError(
                f"unusable distinguisher {distinguisher!r}: {d.reason}"
            )
        stem = f"{stem} ({d.value})"
    return f"{stem} — FY {fiscal_year} {book}"


def resolve_supplier_disagreement(
    *, supplied: str, stamp_name: str | None, doc_text: str
) -> tuple[str, str | None]:
    """(chosen name, note) — the note is the I8 reversal record's reason."""
    if not stamp_name:
        return supplied, None

    stamp_words = distinctive_words(stamp_name)
    supplied_words = distinctive_words(supplied)
    if stamp_words & supplied_words:
        return supplied, None

    text = (doc_text or "").lower()
    # `any()` over an empty iterable is already False, so no explicit
    # `bool(stamp_words) and` guard is needed — a name with no distinctive
    # words (e.g. every word is a stop word) correctly reads as
    # uncorroborated on its own.
    corroborated = any(w in text for w in stamp_words)
    if not corroborated:
        return supplied, (
            f"supplier said {supplied!r}, stamp said {stamp_name!r}, and the "
            "stamp is not corroborated by the document text — left unchanged"
        )
    return stamp_name, (
        f"supplier said {supplied!r}; the document's own text says "
        f"{stamp_name!r} — stamp wins (2 witnesses to 1)"
    )
