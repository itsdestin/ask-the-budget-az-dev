"""Per-doc-type extractor dispatch.

Given (doc_type, source_format), pick the right extractor and run it
against a local source file. Concrete extractor implementations wrap
the Phase 0 scripts in ``scripts/run_*.py``; this module provides the
unified interface that downstream chunking can call without knowing
which underlying tool produced the output.

## Routing rules

Per chunk-shape D4 + spec §9. Tagged PDFs (with structure tree) go
through OpenDataLoader for cell-level fidelity. Untagged JLBC PDFs go
through MinerU for layout reconstruction + table detection. DOCX bills
use python-docx with paragraph-id provenance.

| doc_type              | source_format | extractor      |
|-----------------------|---------------|----------------|
| afr                   | pdf           | opendataloader |
| governors-budget      | pdf           | opendataloader |
| baseline-book         | pdf           | mineru         |
| approps-report        | pdf           | mineru         |
| baseline-per-agency   | pdf           | mineru         |
| approps-per-agency    | pdf           | mineru         |
| s-pdf                 | pdf           | mineru         |
| bh-pdf                | pdf           | mineru         |
| bd-pdf                | pdf           | mineru         |
| topic-pdf             | pdf           | mineru         |
| budget-bill           | docx          | python-docx    |

Mismatched combinations (e.g., budget-bill + pdf) raise — almost
always a caller bug.

## Per-doc manifest

``extract()`` writes ``<output_dir>/manifest.json`` with the extractor
name, version, source sha256, doc_type, and page list. Phase 1b reads
these to decide whether to re-extract on a doc reissue and to populate
provenance fields on chunks.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable


# ----------------------------------------------------------------------------
# Extractor protocol + concrete implementations
# ----------------------------------------------------------------------------


@runtime_checkable
class Extractor(Protocol):
    """Minimum surface every extractor implementation provides."""

    name: str

    def get_version(self) -> str: ...

    def extract(
        self,
        *,
        source_path: Path,
        output_dir: Path,
        pages: list[int] | None,
    ) -> None: ...


def _pdf_page_count(path: Path) -> int:
    """Lightweight page counter using PyMuPDF (already a dev dep)."""
    import fitz  # PyMuPDF

    doc = fitz.open(path)
    try:
        return doc.page_count
    finally:
        doc.close()


def _import_phase0_module(module_name: str):
    """Import a Phase 0 script that lives under ``scripts/``.

    The scripts directory isn't a package — it's a flat collection of
    CLI entry points. We add it to sys.path on demand so the dispatcher
    can call into ``run_mineru()`` etc. without restructuring Phase 0
    code. Lazy: only invoked when an extractor is actually run.
    """
    scripts_dir = (Path(__file__).resolve().parent.parent / "scripts").resolve()
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    return __import__(module_name)


@dataclass
class MinerUExtractor:
    name: str = "mineru"

    def get_version(self) -> str:
        # Lazy: MinerU imports torch + transformers, which is heavy
        # enough that a "what version?" call shouldn't trigger it
        # unless we're actually about to extract.
        try:
            import mineru  # type: ignore[import-not-found]
            return getattr(mineru, "__version__", "unknown")
        except ImportError:
            return "unknown"

    def extract(
        self,
        *,
        source_path: Path,
        output_dir: Path,
        pages: list[int] | None,
    ) -> None:
        run_mineru_mod = _import_phase0_module("run_mineru")
        if pages is None:
            pages = list(range(1, _pdf_page_count(source_path) + 1))
        run_mineru_mod.run_mineru(source_path, output_dir, pages)


@dataclass
class OpenDataLoaderExtractor:
    name: str = "opendataloader"

    def get_version(self) -> str:
        try:
            from importlib.metadata import version
            return version("opendataloader-pdf")
        except Exception:
            return "unknown"

    def extract(
        self,
        *,
        source_path: Path,
        output_dir: Path,
        pages: list[int] | None,
    ) -> None:
        run_odl_mod = _import_phase0_module("run_opendataloader")
        if pages is None:
            pages = list(range(1, _pdf_page_count(source_path) + 1))
        run_odl_mod.run_opendataloader(source_path, output_dir, pages)


@dataclass
class PythonDocxExtractor:
    name: str = "python-docx"

    def get_version(self) -> str:
        try:
            from importlib.metadata import version
            return version("python-docx")
        except Exception:
            return "unknown"

    def extract(
        self,
        *,
        source_path: Path,
        output_dir: Path,
        pages: list[int] | None,
    ) -> None:
        # DOCX has no concept of pages at extraction time. Ignore.
        del pages
        run_docx_mod = _import_phase0_module("run_docx_ingest")
        run_docx_mod.run_docx_ingest(source_path, output_dir)


# ----------------------------------------------------------------------------
# Registry + dispatch
# ----------------------------------------------------------------------------


# (doc_type, source_format) -> extractor class
EXTRACTOR_REGISTRY: dict[tuple[str, str], type] = {
    # Tagged PDFs.
    ("afr", "pdf"): OpenDataLoaderExtractor,
    ("governors-budget", "pdf"): OpenDataLoaderExtractor,
    # Untagged JLBC singlefiles.
    ("baseline-book", "pdf"): MinerUExtractor,
    ("approps-report", "pdf"): MinerUExtractor,
    # JLBC per-agency.
    ("baseline-per-agency", "pdf"): MinerUExtractor,
    ("approps-per-agency", "pdf"): MinerUExtractor,
    # JLBC cross-cuts (s/bh/bd/topic).
    ("s-pdf", "pdf"): MinerUExtractor,
    ("bh-pdf", "pdf"): MinerUExtractor,
    ("bd-pdf", "pdf"): MinerUExtractor,
    ("topic-pdf", "pdf"): MinerUExtractor,
    # Budget bill DOCX.
    ("budget-bill", "docx"): PythonDocxExtractor,
}


def pick_extractor(doc_type: str, source_format: str) -> Extractor:
    """Resolve (doc_type, source_format) to an instantiated extractor.

    Raises ``ValueError`` on unknown combinations — including
    mismatches like (budget-bill, pdf) that almost always indicate a
    caller bug. Loud failure beats silent wrong-extractor routing.
    """
    cls = EXTRACTOR_REGISTRY.get((doc_type, source_format))
    if cls is None:
        valid_types = sorted({dt for (dt, _f) in EXTRACTOR_REGISTRY})
        valid_formats = sorted({f for (_d, f) in EXTRACTOR_REGISTRY})
        raise ValueError(
            f"pick_extractor: unsupported combination "
            f"(doc_type={doc_type!r}, source_format={source_format!r}). "
            f"Known doc_types: {valid_types}. "
            f"Known source_formats: {valid_formats}."
        )
    return cls()


# ----------------------------------------------------------------------------
# extract() — top-level callable
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class ExtractionResult:
    """Metadata produced by one extract() run.

    The actual extracted content lives on disk under ``output_dir``.
    Phase 1b's chunk-builder reads from ``output_dir`` and joins this
    metadata into per-chunk provenance.
    """

    extractor: str
    extractor_version: str
    source_path: Path
    output_dir: Path
    doc_type: str
    source_format: str
    pages_extracted: list[int] | None
    extracted_at: str
    source_sha256: str


def _utcnow_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _sha256_of_file(path: Path, chunk_size: int = 1 << 20) -> str:
    """Stream-hash a file. Avoids loading the whole PDF into memory."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            buf = fh.read(chunk_size)
            if not buf:
                break
            h.update(buf)
    return h.hexdigest()


def extract(
    *,
    source_path: Path,
    doc_type: str,
    source_format: str,
    output_dir: Path,
    pages: list[int] | None = None,
    extractor: Extractor | None = None,
) -> ExtractionResult:
    """Run the extractor for ``doc_type`` against ``source_path``.

    If ``extractor`` is None, ``pick_extractor`` resolves one from the
    registry. The explicit injection point exists so tests can swap in
    a mock without monkey-patching.

    Writes ``<output_dir>/manifest.json`` capturing extractor name,
    version, source sha, and doc_type. Returns the matching
    ``ExtractionResult``.
    """
    if extractor is None:
        extractor = pick_extractor(doc_type, source_format)

    output_dir.mkdir(parents=True, exist_ok=True)
    extractor.extract(
        source_path=source_path,
        output_dir=output_dir,
        pages=pages,
    )

    result = ExtractionResult(
        extractor=extractor.name,
        extractor_version=extractor.get_version(),
        source_path=source_path,
        output_dir=output_dir,
        doc_type=doc_type,
        source_format=source_format,
        pages_extracted=pages,
        extracted_at=_utcnow_iso(),
        source_sha256=_sha256_of_file(source_path),
    )

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "extractor": result.extractor,
                "extractor_version": result.extractor_version,
                "source_path": str(result.source_path),
                "doc_type": result.doc_type,
                "source_format": result.source_format,
                "pages_extracted": result.pages_extracted,
                "extracted_at": result.extracted_at,
                "source_sha256": result.source_sha256,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    return result
