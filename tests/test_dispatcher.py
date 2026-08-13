"""Tests for ingest.dispatcher — doc_type → extractor selection.

Scope: dispatch correctness only. The actual extractor behavior
(MinerU output shape, OpenDataLoader bbox accuracy, python-docx
paragraph IDs) is covered by ``scripts/tests/test_run_*.py``. End-to-
end extract validation lives in WS6 (smoke queries against full
ingested corpus).

Tests inject a mock extractor where they need to verify dispatcher
→ extractor wiring without triggering real MinerU/ODL/python-docx
runs (slow + heavy).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from ingest.dispatcher import (
    EXTRACTOR_REGISTRY,
    ExtractionResult,
    MinerUExtractor,
    MinerUOcrExtractor,
    OpenDataLoaderExtractor,
    PythonDocxExtractor,
    extract,
    pick_extractor,
)


# --- pick_extractor — doc_type → Extractor class ---


@pytest.mark.parametrize(
    ("doc_type", "source_format", "expected_cls"),
    [
        # Tagged PDFs → OpenDataLoader.
        ("afr", "pdf", OpenDataLoaderExtractor),
        ("governors-budget", "pdf", OpenDataLoaderExtractor),
        # Untagged JLBC PDFs (singlefiles + per-agency + cross-cuts) → MinerU.
        ("baseline-book", "pdf", MinerUExtractor),
        ("approps-report", "pdf", MinerUExtractor),
        ("baseline-per-agency", "pdf", MinerUExtractor),
        ("approps-per-agency", "pdf", MinerUExtractor),
        ("s-pdf", "pdf", MinerUExtractor),
        ("bh-pdf", "pdf", MinerUExtractor),
        ("bd-pdf", "pdf", MinerUExtractor),
        ("topic-pdf", "pdf", MinerUExtractor),
        # Bill DOCX → python-docx.
        ("budget-bill", "docx", PythonDocxExtractor),
    ],
)
def test_pick_extractor_routes_by_doc_type(
    doc_type: str, source_format: str, expected_cls: type
) -> None:
    extractor = pick_extractor(doc_type, source_format)
    assert isinstance(extractor, expected_cls)
    assert extractor.name in {"mineru", "opendataloader", "python-docx"}


def test_pick_extractor_rejects_format_mismatch() -> None:
    """A bill in PDF or an AFR in DOCX is almost certainly a caller bug.
    The dispatcher must reject the combination rather than silently
    routing to a wrong extractor."""
    with pytest.raises(ValueError, match="doc_type|source_format|combination"):
        pick_extractor("budget-bill", "pdf")
    with pytest.raises(ValueError, match="doc_type|source_format|combination"):
        pick_extractor("afr", "docx")


def test_pick_extractor_rejects_unknown_doc_type() -> None:
    with pytest.raises(ValueError, match="doc_type|combination"):
        pick_extractor("nonsense", "pdf")


def test_extractor_registry_covers_every_doc_type_in_plan() -> None:
    """Pin the doc_type taxonomy: every doc_type the plan / discovery
    layer can produce must have a route here. If the discovery layer
    introduces a new doc_type, this test forces an explicit decision
    rather than letting it slip through."""
    expected_doc_types = {
        # Singlefile / full publisher views.
        "baseline-book", "approps-report", "afr", "governors-budget",
        "budget-bill",
        # Discovery output (cross-cuts + per-agency).
        "baseline-per-agency", "approps-per-agency",
        "s-pdf", "bh-pdf", "bd-pdf", "topic-pdf", "detailed-list-pdf",
    }
    actual_doc_types = {dt for (dt, _fmt) in EXTRACTOR_REGISTRY}
    missing = expected_doc_types - actual_doc_types
    assert not missing, f"doc_types not in EXTRACTOR_REGISTRY: {missing}"


# --- extract() — wrapping the chosen extractor ---


@dataclass
class _MockExtractor:
    """Records calls; matches the Extractor protocol."""

    name: str = "mock"
    version_str: str = "0.0.1"
    calls: list[dict] = field(default_factory=list)

    def get_version(self) -> str:
        return self.version_str

    def extract(self, *, source_path: Path, output_dir: Path, pages: list[int] | None) -> None:
        self.calls.append({
            "source_path": source_path,
            "output_dir": output_dir,
            "pages": pages,
        })
        # Fake side effect: create the output dir so the result can be
        # asserted as "produced something."
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "page-1.json").write_text("{}", encoding="utf-8")


def test_extract_delegates_to_injected_extractor(tmp_path: Path) -> None:
    mock = _MockExtractor()
    source = tmp_path / "src.pdf"
    source.write_bytes(b"%PDF-1.7 fake")
    out = tmp_path / "out"

    result = extract(
        source_path=source,
        doc_type="s-pdf",
        source_format="pdf",
        output_dir=out,
        pages=[1, 2, 3],
        extractor=mock,
    )

    assert isinstance(result, ExtractionResult)
    assert mock.calls == [
        {"source_path": source, "output_dir": out, "pages": [1, 2, 3]},
    ]


def test_extract_records_metadata_in_result(tmp_path: Path) -> None:
    mock = _MockExtractor(name="mock", version_str="9.9.9")
    source = tmp_path / "src.pdf"
    source.write_bytes(b"%PDF-1.7")
    out = tmp_path / "out"

    result = extract(
        source_path=source,
        doc_type="afr",
        source_format="pdf",
        output_dir=out,
        pages=None,
        extractor=mock,
    )

    assert result.extractor == "mock"
    assert result.extractor_version == "9.9.9"
    assert result.source_path == source
    assert result.output_dir == out
    assert result.doc_type == "afr"
    assert result.source_format == "pdf"
    assert result.pages_extracted is None
    # Timestamp is ISO-8601 with timezone.
    import datetime as dt
    dt.datetime.fromisoformat(result.extracted_at)


def test_extract_writes_per_doc_manifest(tmp_path: Path) -> None:
    """Each extract() run must drop a manifest.json into output_dir
    capturing extractor + version + source sha + doc_type. Phase 1b
    will read these to decide whether to re-extract on a doc reissue
    and to populate provenance fields on chunks."""
    import json

    mock = _MockExtractor(name="mock", version_str="1.0.0")
    source = tmp_path / "src.pdf"
    source.write_bytes(b"hello-world")
    out = tmp_path / "out"

    result = extract(
        source_path=source,
        doc_type="s-pdf",
        source_format="pdf",
        output_dir=out,
        pages=[1, 2],
        extractor=mock,
    )

    manifest_path = out / "manifest.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["extractor"] == "mock"
    assert manifest["extractor_version"] == "1.0.0"
    assert manifest["doc_type"] == "s-pdf"
    assert manifest["source_format"] == "pdf"
    assert manifest["pages_extracted"] == [1, 2]
    # Source sha is the source_path's sha256 — stable independent of where
    # the file lives, so the manifest survives a cache relocation.
    import hashlib
    expected_sha = hashlib.sha256(b"hello-world").hexdigest()
    assert manifest["source_sha256"] == expected_sha


def test_extract_uses_pick_extractor_when_no_extractor_passed(tmp_path: Path) -> None:
    """Without an explicit extractor= argument, extract() routes via
    pick_extractor. We verify the routing without firing the real
    extractor by intercepting at the registry layer."""
    source = tmp_path / "fake.pdf"
    source.write_bytes(b"%PDF-1.7")
    out = tmp_path / "out"

    # Monkeypatch the registry temporarily — easier than a fixture
    # because we want to isolate this test's dispatch surface.
    original = EXTRACTOR_REGISTRY[("s-pdf", "pdf")]
    EXTRACTOR_REGISTRY[("s-pdf", "pdf")] = _MockExtractor  # type: ignore[assignment]
    try:
        result = extract(
            source_path=source,
            doc_type="s-pdf",
            source_format="pdf",
            output_dir=out,
        )
        assert result.extractor == "mock"
    finally:
        EXTRACTOR_REGISTRY[("s-pdf", "pdf")] = original


# --- MinerUOcrExtractor — the ladder's last rung (T7) ---


def test_ocr_extractor_is_never_a_first_choice() -> None:
    """data/document-types.yaml declares each type's PREFERRED extractor.

    mineru-ocr is registered in _EXTRACTOR_CLASSES (ingest/ladder.py needs
    to name it) but must never come out of EXTRACTOR_REGISTRY -- that would
    mean some doc_type declared OCR as its first choice, which is the exact
    mistake the brief calls out by name. Nothing in the registry-building
    code stops that from compiling silently, so this is the guard."""
    assert MinerUOcrExtractor not in EXTRACTOR_REGISTRY.values()


def test_ocr_extractor_calls_run_mineru_with_the_ocr_method(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The entire point of this class is the `method` it passes through.

    If `extract()` silently dropped `method="ocr"` (a typo, a forgotten
    kwarg, a copy-paste from MinerUExtractor), MinerUOcrExtractor would run
    byte-for-byte the same extraction as plain `mineru` under a different
    name -- a scanned document would still come back empty, and nothing
    about the ladder itself would show it."""
    calls: list[tuple[tuple, dict]] = []

    class _FakeRunMineruModule:
        @staticmethod
        def run_mineru(*args, **kwargs):
            calls.append((args, kwargs))

    monkeypatch.setattr(
        "ingest.dispatcher._import_phase0_module",
        lambda name: _FakeRunMineruModule(),
    )

    source = tmp_path / "scan.pdf"
    source.write_bytes(b"%PDF-1.7 fake")
    out = tmp_path / "out"

    MinerUOcrExtractor().extract(source_path=source, output_dir=out, pages=[1, 2])

    assert calls == [((source, out, [1, 2]), {"method": "ocr"})]


def test_pick_named_reaches_a_rung_the_registry_cannot() -> None:
    """`mineru-ocr` is deliberately absent from data/document-types.yaml, so
    `pick_extractor` can never return it. The ladder still has to be able to
    ask for it by name, and that is the whole reason `pick_named` exists."""
    from ingest.dispatcher import pick_named

    assert isinstance(pick_named("mineru-ocr"), MinerUOcrExtractor)
    assert pick_named("opendataloader").name == "opendataloader"


def test_pick_named_refuses_an_unknown_name() -> None:
    """A typo'd rung must not resolve to None and then be run as "no
    extractor" — the worker would report success having extracted nothing."""
    from ingest.dispatcher import pick_named

    with pytest.raises(ValueError, match="unknown extractor"):
        pick_named("minerU")


def test_ocr_extractor_has_its_own_rung_name() -> None:
    """MinerUOcrExtractor subclasses MinerUExtractor rather than duplicating
    it -- `get_version()` is inherited unchanged (comparing it against the
    plain extractor's own `get_version()` would be tautological: the same
    method called on two instances with no instance state involved), and
    the only real difference is this name, which is what the ladder
    (ingest/ladder.py) and the chunker's reader registry both key on."""
    ocr = MinerUOcrExtractor()
    assert ocr.name == "mineru-ocr"
