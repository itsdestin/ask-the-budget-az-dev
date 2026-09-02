"""Where a document's cached extractor output lives, for READ-side tools.

The write side already knows this layout: `ingest/worker.py::_extract_dir`
writes `<root>/extractor-output/<doc_id>/<method>/page-N.json` per rung, and
`_legacy_extract_dir` re-claims the pre-rung `<doc_id>/page-N.json` shape.
Both are keyed on a job record, which a corpus repair does not have. This is
the same rule keyed on what a repair DOES have: the doc_id and the sidecar's
`extraction.method`.

WHY the method comes from `documents.json` and never from a folder
precedence: `agao-afr-fy2024` holds BOTH `mineru/` and `mineru-ocr/` -- the
2026-08-13 forced-fallback experiment wrote the OCR reading, and the corpus
holds the MinerU one (sidecar `extraction.method == "mineru"`). Any rule that
picks by folder name reads the wrong document; the repair's body gate then
skips it, and that is the one document spec G-T4's prediction is about.
"""
from __future__ import annotations

import json
from pathlib import Path


def resolve_extract_dir(
    doc_id: str, root: Path, *, method: str | None = None
) -> tuple[Path, str] | None:
    """`(directory, extractor)` for `doc_id`, or None when nothing usable is cached.

    `method` is the sidecar's `extraction.method` when the document has an
    extraction record (141 of 7,574 on 2026-08-26 -- everything ingested
    since Plan B). Documents without one live in the un-suffixed legacy
    directory. A recorded method whose folder is missing returns None
    rather than falling back to another folder: "the reading the corpus
    holds is not on disk" is a finding, and guessing would hide it.

    The extractor NAME is read from the first page file's own `extractor`
    field, never from `manifest.json` -- thousands of documents have no
    manifest, and `agao-afr-fy2024`'s says `opendataloader` while the
    reading in the corpus is MinerU's.
    """
    base = root / "extractor-output" / doc_id
    if not base.is_dir():
        return None
    directory = base / method if method else base
    first = next(iter(sorted(directory.glob("page-*.json"))), None)
    if first is None:
        return None
    try:
        extractor = str(json.loads(first.read_text(encoding="utf-8")).get("extractor", ""))
    except (OSError, ValueError):
        return None
    return directory, extractor
