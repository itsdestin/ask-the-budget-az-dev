"""The ordered extraction attempts for one document (spec T7).

A ladder is a list of extractor NAMES to try in order. Rung 1 is whatever
`data/document-types.yaml` declares for the type -- so a document that
extracts cleanly on the first attempt behaves EXACTLY as it does today, and
the fallbacks exist only for the documents that would otherwise have been
written empty.

Inspection can only REMOVE rungs from the front, never reorder them, and it
has exactly ONE rule:

  no text layer  ->  go straight to OCR

Spec T7 also asked for "no structure tree -> skip OpenDataLoader". That was
MEASURED and dropped: an untagged 639-page Executive Budget scores 92.2%
through OpenDataLoader while the one document that fails is tagged, so the
rule would divert a healthy document to a slower tool and predict nothing.
See ingest/inspection.py's docstring for the numbers.

Cost: a document that needs a fallback pays extraction twice. Measured as
acceptable on 2026-08-12 -- at the calibrated floor, 2 documents of 7,434
(0.03%) are below it.
"""
from __future__ import annotations

from ingest.dispatcher import EXTRACTOR_REGISTRY
from ingest.inspection import SourceInspection

# The PDF ladder, in cost order. Not derived from the registry: this is a
# statement about the TOOLS, not about any document type.
_PDF_LADDER = ("opendataloader", "mineru", "mineru-ocr")


def ladder_for(
    doc_type: str,
    source_format: str,
    inspection: SourceInspection,
) -> list[str]:
    """Extractor names to try, in order. Empty when the combination is unknown."""
    cls = EXTRACTOR_REGISTRY.get((doc_type, source_format))
    if cls is None:
        # (budget-bill, pdf) and friends. `pick_extractor` raises on these
        # and that behaviour is unchanged; the ladder just has nothing to say.
        return []

    preferred = cls().name

    if source_format != "pdf":
        # DOCX: the structure is in the file and there is no second tool.
        return [preferred]

    if not inspection.has_text_layer:
        # A scan. Nothing above OCR can read it, so do not spend hours
        # proving that -- true even when the declared preference is
        # already `mineru`, so this check runs before, not as part of,
        # the cost-order truncation below.
        return ["mineru-ocr"]

    # Start on the declared preference, keeping everything below it.
    rungs = list(_PDF_LADDER)
    if preferred in rungs:
        rungs = rungs[rungs.index(preferred):]
    return rungs
