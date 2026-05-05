# Phase 0 — Investigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a findings memo that informs all v1 architecture decisions for Ask the Budget AZ, anchored in real Arizona budget documents. Specifically: pick a winning PDF extractor, define Tier 1 entity-resolution scope, validate the chunking strategy, and produce a go/no-go decision for Phase 1.

**Architecture:** Mostly manual investigation procedure with small Python automation. Output artifacts are documents and structured data (YAML, CSV, Markdown), not running software. The plan combines code-shaped tasks (TDD applies: extractor wrapper, checksum verifier) with manual graded-procedure tasks (open PDF, score extractor output against ground truth, record). All work runs in `~/ask-the-budget-az-dev/` on `master`.

**Tech Stack:** Python 3.11+ (MinerU and Docling both ship as Python packages), `uv` for Python env management, YAML/CSV for structured data, Markdown for the memo. No web/Node tooling at this stage.

**Source spec:** `docs/superpowers/specs/2026-05-04-ask-the-budget-az-design.md` (especially §8).

---

## File Structure

Files created during Phase 0 (paths relative to `~/ask-the-budget-az-dev/`):

| Path | Purpose | Tracked? |
|---|---|---|
| `samples/manifest.yaml` | URLs + SHA256 checksums + metadata for source PDFs | ✓ |
| `samples/raw-pdfs/*.pdf` | The actual source PDFs | gitignored (large; reproducible from manifest) |
| `samples/scoring-pages.yaml` | The ~20 chosen pages with descriptions of why each was picked | ✓ |
| `samples/scoring-rubric.md` | The 0–3 scoring scale and what each level means per dimension | ✓ |
| `samples/extractor-output/mineru/<doc-id>/page-<N>.{json,md}` | MinerU output per page | gitignored |
| `samples/extractor-output/docling/<doc-id>/page-<N>.{json,md}` | Docling output per page | gitignored |
| `samples/scores-mineru.csv` | Manual MinerU scores | ✓ |
| `samples/scores-docling.csv` | Manual Docling scores | ✓ |
| `data/entity-targets.yaml` | The 10 agencies, 7 programs, 3 sub-programs we'll track | ✓ |
| `data/entity-variance-catalog.csv` | How each target is named across all 4 doc types | ✓ |
| `scripts/check_pdf_manifest.py` | Verify samples/raw-pdfs/ matches manifest checksums | ✓ |
| `scripts/run_mineru.py` | Wrapper to run MinerU on one PDF or page range | ✓ |
| `scripts/run_docling.py` | Same for Docling | ✓ |
| `scripts/aggregate_scores.py` | Compute per-extractor totals, per-dimension breakdowns | ✓ |
| `scripts/tests/` | Pytest tests for the wrapper scripts | ✓ |
| `pyproject.toml` | Python project config + dependencies | ✓ |
| `docs/superpowers/investigations/2026-MM-DD-phase-0-bakeoff.md` | Final findings memo (MM-DD = execution date) | ✓ |

Files modified:
| Path | Change |
|---|---|
| `.gitignore` | Already covers `samples/extractor-output/` and `samples/raw-pdfs/`; verify in Task 0 |

---

## Task 0: Verify environment and prerequisites

**Files:**
- Read: `.gitignore`, `CLAUDE.md`
- Verify: Python 3.11+ available, `uv` installed, ~5 GB free disk for models

- [ ] **Step 1: Confirm Python and uv**

```bash
python --version  # expect 3.11+
uv --version      # expect any
```

If `uv` is missing: `pip install uv` or `curl -LsSf https://astral.sh/uv/install.sh | sh`.

- [ ] **Step 2: Confirm gitignore coverage**

Read `.gitignore` and verify these lines exist (they should — added during scaffolding):

```
samples/extractor-output/
samples/raw-pdfs/
```

If missing, append them. Do NOT commit raw PDFs or extractor output to git — they bloat the repo and are reproducible from manifest + extractor scripts.

- [ ] **Step 3: Skim the spec sections that drive Phase 0**

Read `docs/superpowers/specs/2026-05-04-ask-the-budget-az-design.md` §8 (Phase 0 Investigation) and §3 (Core Invariants). Phase 0 produces the inputs Phase 1 depends on, so the bar for accuracy on the manual scoring tasks is high.

---

## Task 1: Acquire sample PDFs

**Files:**
- Create: `samples/manifest.yaml`
- Create: `samples/raw-pdfs/*.pdf` (downloaded; gitignored)

The spec calls for ~6–8 PDFs:
- 1× JLBC Baseline Book FY25 (current, narrative-dense)
- 1× JLBC Baseline Book FY23 (older, for cross-year testing)
- 1× JLBC Appropriations Report FY25
- 1× AGAO Annual Financial Report FY24 (different formatting, GAAP, restated tables)
- 1× Governor's Executive Budget FY26
- 1–2× misc (a JLBC fiscal note, a small supplement)

- [ ] **Step 1: Create the manifest skeleton**

Create `samples/manifest.yaml`:

```yaml
# Source PDFs for Phase 0 investigation. URLs and checksums let any
# future contributor re-download and verify the exact same files.
documents:
  - id: jlbc-baseline-fy25
    publisher: jlbc
    doc_type: baseline-book
    fiscal_year: 2025
    title: "JLBC FY 2025 Baseline Book"
    source_url: ""        # filled in Step 2
    sha256: ""            # filled in Step 4
    page_count: 0         # filled in Step 4
    local_path: "samples/raw-pdfs/jlbc-baseline-fy25.pdf"
    acquired_on: "2026-MM-DD"

  - id: jlbc-baseline-fy23
    publisher: jlbc
    doc_type: baseline-book
    fiscal_year: 2023
    title: "JLBC FY 2023 Baseline Book"
    source_url: ""
    sha256: ""
    page_count: 0
    local_path: "samples/raw-pdfs/jlbc-baseline-fy23.pdf"
    acquired_on: "2026-MM-DD"

  - id: jlbc-approps-fy25
    publisher: jlbc
    doc_type: approps-report
    fiscal_year: 2025
    title: "JLBC FY 2025 Appropriations Report"
    source_url: ""
    sha256: ""
    page_count: 0
    local_path: "samples/raw-pdfs/jlbc-approps-fy25.pdf"
    acquired_on: "2026-MM-DD"

  - id: agao-afr-fy24
    publisher: agao
    doc_type: afr
    fiscal_year: 2024
    title: "Arizona Annual Comprehensive Financial Report FY 2024"
    source_url: ""
    sha256: ""
    page_count: 0
    local_path: "samples/raw-pdfs/agao-afr-fy24.pdf"
    acquired_on: "2026-MM-DD"

  - id: governors-budget-fy26
    publisher: governor
    doc_type: governors-budget
    fiscal_year: 2026
    title: "Governor's Executive Budget FY 2026"
    source_url: ""
    sha256: ""
    page_count: 0
    local_path: "samples/raw-pdfs/governors-budget-fy26.pdf"
    acquired_on: "2026-MM-DD"

  - id: jlbc-fiscal-note-misc
    publisher: jlbc
    doc_type: fiscal-note
    fiscal_year: 2025
    title: "JLBC fiscal note (representative; specific bill chosen during execution)"
    source_url: ""
    sha256: ""
    page_count: 0
    local_path: "samples/raw-pdfs/jlbc-fiscal-note-misc.pdf"
    acquired_on: "2026-MM-DD"
```

- [ ] **Step 2: Discover URLs (with user help if needed)**

Search these public sites for the PDFs above. Where multiple revisions exist (e.g., two FY25 baseline books — preliminary vs. final), prefer the final published version unless a preliminary is being explicitly tested.

- JLBC documents: https://www.azjlbc.gov/current-year/ and https://www.azjlbc.gov/prior-years/
- AGAO Annual Financial Reports: https://gao.az.gov/financials/afr (Arizona General Accounting Office, the body that *prepares* the AFR — NOT the Auditor General at `azauditor.gov`, which is a separate body that audits it)
- Governor's Executive Budget: https://ospb.az.gov/governors-budget-requests (Office of Strategic Planning and Budgeting)

For each document, do a focused web search for the exact title + year. If a URL can't be confirmed unambiguously, **stop and ask the user** to confirm the right link before downloading. Wrong sample documents cascade into wrong findings.

Update each `source_url:` in `samples/manifest.yaml` with the confirmed URL.

- [ ] **Step 3: Write the checksum verifier**

Create `scripts/check_pdf_manifest.py`:

```python
"""Verify samples/raw-pdfs/ matches samples/manifest.yaml checksums.

Exits 0 if all files match their declared checksums, 1 otherwise.
Reports missing files, mismatched checksums, and orphan files separately.
"""

import hashlib
import sys
from pathlib import Path

import yaml

MANIFEST = Path("samples/manifest.yaml")
RAW_DIR = Path("samples/raw-pdfs")


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    if not MANIFEST.exists():
        print(f"manifest missing: {MANIFEST}", file=sys.stderr)
        return 1

    manifest = yaml.safe_load(MANIFEST.read_text())
    failures = []

    declared_paths = set()
    for doc in manifest["documents"]:
        local = Path(doc["local_path"])
        declared_paths.add(local)

        if not local.exists():
            # An empty checksum field means we haven't downloaded this yet — that's OK during Step 4.
            if doc["sha256"]:
                failures.append(f"missing: {local}")
            continue

        if not doc["sha256"]:
            print(f"NOTE: {local} downloaded but checksum not yet recorded")
            continue

        actual = sha256_of(local)
        if actual != doc["sha256"]:
            failures.append(f"checksum mismatch: {local}\n  expected: {doc['sha256']}\n  actual:   {actual}")

    if RAW_DIR.exists():
        for found in RAW_DIR.glob("*.pdf"):
            if found not in declared_paths:
                failures.append(f"orphan (not in manifest): {found}")

    if failures:
        for msg in failures:
            print(f"FAIL: {msg}", file=sys.stderr)
        return 1

    print("OK: all manifest entries verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Write a failing test for the verifier**

Create `scripts/tests/test_check_pdf_manifest.py`:

```python
"""Tests for scripts/check_pdf_manifest.py.

We don't ship real PDFs to the test fixture — we synthesize tiny binary
files and write a manifest pointing at them, so the test runs offline.
"""

import hashlib
import subprocess
import sys
import textwrap
from pathlib import Path


def write_fixture(tmp_path: Path, files: dict[str, bytes], manifest_text: str) -> None:
    raw = tmp_path / "samples" / "raw-pdfs"
    raw.mkdir(parents=True)
    for name, content in files.items():
        (raw / name).write_bytes(content)
    (tmp_path / "samples").mkdir(exist_ok=True)
    (tmp_path / "samples" / "manifest.yaml").write_text(manifest_text)
    # Copy the script into the fixture so cwd-relative paths work
    src = Path(__file__).parent.parent / "check_pdf_manifest.py"
    (tmp_path / "scripts").mkdir(exist_ok=True)
    (tmp_path / "scripts" / "check_pdf_manifest.py").write_text(src.read_text())


def run(tmp_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "scripts/check_pdf_manifest.py"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )


def test_passes_when_checksum_matches(tmp_path: Path) -> None:
    content = b"%PDF-1.4\nfake\n%%EOF\n"
    sha = hashlib.sha256(content).hexdigest()
    write_fixture(
        tmp_path,
        {"a.pdf": content},
        textwrap.dedent(f"""
            documents:
              - id: a
                publisher: jlbc
                doc_type: baseline-book
                fiscal_year: 2025
                title: A
                source_url: ""
                sha256: "{sha}"
                page_count: 0
                local_path: "samples/raw-pdfs/a.pdf"
                acquired_on: ""
        """),
    )
    result = run(tmp_path)
    assert result.returncode == 0, result.stderr


def test_fails_on_checksum_mismatch(tmp_path: Path) -> None:
    write_fixture(
        tmp_path,
        {"a.pdf": b"actual"},
        textwrap.dedent("""
            documents:
              - id: a
                publisher: jlbc
                doc_type: baseline-book
                fiscal_year: 2025
                title: A
                source_url: ""
                sha256: "0000000000000000000000000000000000000000000000000000000000000000"
                page_count: 0
                local_path: "samples/raw-pdfs/a.pdf"
                acquired_on: ""
        """),
    )
    result = run(tmp_path)
    assert result.returncode == 1
    assert "checksum mismatch" in result.stderr


def test_flags_orphan_file(tmp_path: Path) -> None:
    write_fixture(
        tmp_path,
        {"orphan.pdf": b"x"},
        "documents: []\n",
    )
    result = run(tmp_path)
    assert result.returncode == 1
    assert "orphan" in result.stderr
```

- [ ] **Step 5: Set up Python env and run the test**

```bash
cd ~/ask-the-budget-az-dev
uv init --no-readme --no-pin-python  # creates pyproject.toml if missing
uv add pyyaml --dev pytest
uv run pytest scripts/tests/test_check_pdf_manifest.py -v
```

Expected: 3 tests PASS.

- [ ] **Step 6: Download each PDF**

For each entry in `samples/manifest.yaml` with a confirmed `source_url`:

```bash
mkdir -p samples/raw-pdfs
curl -L -o samples/raw-pdfs/jlbc-baseline-fy25.pdf "<source_url>"
# repeat for each document
```

Then compute SHA256 and page count for each:

```bash
sha256sum samples/raw-pdfs/jlbc-baseline-fy25.pdf
# Use any PDF tool to get page count, e.g.:
uv run python -c "import pypdf; print(len(pypdf.PdfReader('samples/raw-pdfs/jlbc-baseline-fy25.pdf').pages))"
```

You'll need pypdf:

```bash
uv add pypdf
```

Update `samples/manifest.yaml`: fill in the `sha256:` and `page_count:` fields for each downloaded PDF, plus today's date in `acquired_on:`.

- [ ] **Step 7: Verify the manifest**

```bash
uv run python scripts/check_pdf_manifest.py
```

Expected: `OK: all manifest entries verified`

- [ ] **Step 8: Commit**

```bash
git add samples/manifest.yaml scripts/ pyproject.toml uv.lock
git commit -m "phase-0: acquire sample PDFs and add manifest verifier

Source URLs and SHA256 checksums for the 6 PDFs we'll bake-off against.
Raw PDFs are gitignored (they're public and reproducible from URL+checksum).
Verifier script + tests guard against silent corpus drift across sessions.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Set up MinerU 2.5 environment

**Files:**
- Modify: `pyproject.toml` (add MinerU dependency)
- Create: `scripts/run_mineru.py`
- Create: `scripts/tests/test_run_mineru.py`
- Create: `samples/extractor-output/mineru/README.md`

- [ ] **Step 1: Install MinerU**

```bash
uv add mineru
```

If MinerU's pip name differs at the time of execution, look it up at the project's GitHub README and adapt the command. MinerU may have model weights it downloads on first run (~2–5 GB) — that's expected.

- [ ] **Step 2: Write a failing test for the wrapper**

Create `scripts/tests/test_run_mineru.py`:

```python
"""Tests for scripts/run_mineru.py.

The wrapper is a thin CLI; we test argument parsing and the file-write
contract, not MinerU's internals (which are slow and download models).
The test injects a fake extractor function via a flag.
"""

import json
import subprocess
import sys
from pathlib import Path


def test_writes_per_page_outputs_to_target_dir(tmp_path: Path) -> None:
    pdf = tmp_path / "tiny.pdf"
    pdf.write_bytes(b"%PDF-1.4\nfake\n%%EOF\n")
    out = tmp_path / "out"

    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_mineru.py",
            "--pdf", str(pdf),
            "--out", str(out),
            "--pages", "1",
            "--dry-run",   # bypasses real extractor, writes a stub
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    page_json = out / "page-1.json"
    page_md = out / "page-1.md"
    assert page_json.exists()
    assert page_md.exists()
    payload = json.loads(page_json.read_text())
    assert payload["page"] == 1
    assert payload["extractor"] == "mineru-dry-run"


def test_rejects_missing_pdf(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_mineru.py",
            "--pdf", str(tmp_path / "nope.pdf"),
            "--out", str(out),
            "--pages", "1",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "not found" in (result.stderr + result.stdout).lower()
```

- [ ] **Step 3: Implement the wrapper**

Create `scripts/run_mineru.py`:

```python
"""Run MinerU 2.5 on one PDF, optionally restricted to a page range.

Outputs:
  <out>/page-<N>.json   — structured extraction (blocks with bboxes, page_number, text, type)
  <out>/page-<N>.md     — Markdown rendering of the same page

Why per-page files: keeps later scoring tasks tractable. Each scoring pass
opens one JSON + one Markdown side by side with the corresponding PDF page.
"""

import argparse
import json
import sys
from pathlib import Path


def parse_pages(arg: str, total_pages: int | None = None) -> list[int]:
    """Parse '1', '1-3', '1,3,5', '1-3,7' into a list of 1-indexed pages."""
    pages: set[int] = set()
    for piece in arg.split(","):
        piece = piece.strip()
        if "-" in piece:
            lo, hi = piece.split("-", 1)
            pages.update(range(int(lo), int(hi) + 1))
        else:
            pages.add(int(piece))
    return sorted(pages)


def write_dry_run(pdf: Path, out: Path, pages: list[int]) -> None:
    """Stub for testing — writes a minimal valid output without invoking MinerU."""
    out.mkdir(parents=True, exist_ok=True)
    for page in pages:
        (out / f"page-{page}.json").write_text(
            json.dumps(
                {
                    "extractor": "mineru-dry-run",
                    "source_pdf": str(pdf),
                    "page": page,
                    "blocks": [],
                },
                indent=2,
            )
        )
        (out / f"page-{page}.md").write_text(f"# Dry-run page {page}\n")


def run_mineru(pdf: Path, out: Path, pages: list[int]) -> None:
    """Real path. Uses MinerU's Python API."""
    # Lazy import: keeps --dry-run paths from triggering model downloads.
    from mineru import parse_pdf  # type: ignore[import-not-found]

    out.mkdir(parents=True, exist_ok=True)
    full = parse_pdf(str(pdf))  # MinerU returns a structured dict with per-page blocks

    by_page: dict[int, list[dict]] = {}
    for block in full.get("blocks", []):
        # MinerU page numbering may be 0-indexed; normalize to 1-indexed.
        page = block.get("page_idx", block.get("page", 0)) + 1
        by_page.setdefault(page, []).append(block)

    for page in pages:
        blocks = by_page.get(page, [])
        (out / f"page-{page}.json").write_text(
            json.dumps(
                {
                    "extractor": "mineru-2.5",
                    "source_pdf": str(pdf),
                    "page": page,
                    "blocks": blocks,
                },
                indent=2,
            )
        )
        # Markdown rendering: concatenate text blocks in order.
        md_lines = []
        for b in blocks:
            text = b.get("text") or b.get("content") or ""
            if text:
                md_lines.append(text)
        (out / f"page-{page}.md").write_text("\n\n".join(md_lines) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run MinerU 2.5 on a PDF, per-page output.")
    parser.add_argument("--pdf", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--pages", required=True, help="e.g. '5', '5-10', '5,7,9-11'")
    parser.add_argument("--dry-run", action="store_true", help="skip real extraction (test mode)")
    args = parser.parse_args(argv)

    if not args.pdf.exists():
        print(f"PDF not found: {args.pdf}", file=sys.stderr)
        return 2

    pages = parse_pages(args.pages)

    if args.dry_run:
        write_dry_run(args.pdf, args.out, pages)
    else:
        run_mineru(args.pdf, args.out, pages)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests**

```bash
uv run pytest scripts/tests/test_run_mineru.py -v
```

Expected: 2 tests PASS.

- [ ] **Step 5: Smoke test on a real PDF**

Pick one PDF (smallest one — probably the fiscal note). Run MinerU on its first page:

```bash
uv run python scripts/run_mineru.py \
  --pdf samples/raw-pdfs/jlbc-fiscal-note-misc.pdf \
  --out samples/extractor-output/mineru/jlbc-fiscal-note-misc \
  --pages 1
```

Expected: `samples/extractor-output/mineru/jlbc-fiscal-note-misc/page-1.json` and `page-1.md` exist with non-empty content.

If MinerU fails to install or run (model download fails, GPU mismatch, etc.), document the issue in `samples/extractor-output/mineru/README.md` and decide: retry on a different machine, use a smaller MinerU variant, or fall back to CPU-only mode. Do NOT proceed to scoring with a broken environment.

- [ ] **Step 6: Document the setup**

Create `samples/extractor-output/mineru/README.md`:

```markdown
# MinerU 2.5 Extractor Setup

## Version
- mineru: <pinned version from `uv pip list`>
- Python: 3.11+
- Hardware: <CPU / GPU vendor / VRAM>

## Models downloaded
On first run MinerU downloads layout + table models. Approx ~3 GB. Cached at `<cache path>`.

## Known footguns observed
- (to fill in as they appear during real runs)

## Reproduction
From `~/ask-the-budget-az-dev/`:
```
uv run python scripts/run_mineru.py --pdf <pdf> --out <dir> --pages <range>
```
```

- [ ] **Step 7: Commit**

```bash
git add scripts/run_mineru.py scripts/tests/test_run_mineru.py samples/extractor-output/mineru/README.md pyproject.toml uv.lock
git commit -m "phase-0: add MinerU 2.5 wrapper and smoke test

CLI wrapper writes per-page JSON+Markdown so scoring tasks can open one
file per page. --dry-run flag bypasses the real extractor for fast tests.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Set up Docling environment

**Files:**
- Modify: `pyproject.toml` (add docling dependency)
- Create: `scripts/run_docling.py` (mirror of `run_mineru.py`)
- Create: `scripts/tests/test_run_docling.py`
- Create: `samples/extractor-output/docling/README.md`

- [ ] **Step 1: Install Docling**

```bash
uv add docling
```

- [ ] **Step 2: Write the failing test**

Create `scripts/tests/test_run_docling.py` — same shape as `test_run_mineru.py` but invoking `scripts/run_docling.py`. Repeat the test bodies (do not import or share with the MinerU test — independence keeps regressions in one extractor from looking like regressions in the other):

```python
"""Tests for scripts/run_docling.py.

Mirror of test_run_mineru.py but for the Docling wrapper. Kept separate
so a regression in either path is isolated; do not factor into a shared
helper.
"""

import json
import subprocess
import sys
from pathlib import Path


def test_writes_per_page_outputs_to_target_dir(tmp_path: Path) -> None:
    pdf = tmp_path / "tiny.pdf"
    pdf.write_bytes(b"%PDF-1.4\nfake\n%%EOF\n")
    out = tmp_path / "out"

    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_docling.py",
            "--pdf", str(pdf),
            "--out", str(out),
            "--pages", "1",
            "--dry-run",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    page_json = out / "page-1.json"
    page_md = out / "page-1.md"
    assert page_json.exists()
    assert page_md.exists()
    payload = json.loads(page_json.read_text())
    assert payload["page"] == 1
    assert payload["extractor"] == "docling-dry-run"


def test_rejects_missing_pdf(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_docling.py",
            "--pdf", str(tmp_path / "nope.pdf"),
            "--out", str(out),
            "--pages", "1",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "not found" in (result.stderr + result.stdout).lower()
```

- [ ] **Step 3: Implement the wrapper**

Create `scripts/run_docling.py`:

```python
"""Run Docling on one PDF, optionally restricted to a page range.

Mirrors scripts/run_mineru.py — same output contract, separate code path.
Mixing the two would let a Docling-specific quirk leak into MinerU outputs
(or vice versa); we keep them independent on purpose.
"""

import argparse
import json
import sys
from pathlib import Path


def parse_pages(arg: str) -> list[int]:
    pages: set[int] = set()
    for piece in arg.split(","):
        piece = piece.strip()
        if "-" in piece:
            lo, hi = piece.split("-", 1)
            pages.update(range(int(lo), int(hi) + 1))
        else:
            pages.add(int(piece))
    return sorted(pages)


def write_dry_run(pdf: Path, out: Path, pages: list[int]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for page in pages:
        (out / f"page-{page}.json").write_text(
            json.dumps(
                {
                    "extractor": "docling-dry-run",
                    "source_pdf": str(pdf),
                    "page": page,
                    "blocks": [],
                },
                indent=2,
            )
        )
        (out / f"page-{page}.md").write_text(f"# Dry-run page {page}\n")


def run_docling(pdf: Path, out: Path, pages: list[int]) -> None:
    from docling.document_converter import DocumentConverter  # type: ignore[import-not-found]

    converter = DocumentConverter()
    result = converter.convert(str(pdf))
    doc = result.document

    out.mkdir(parents=True, exist_ok=True)
    by_page: dict[int, list[dict]] = {}
    # Docling's structured output uses doc.iterate_items() with (item, level) pairs;
    # each item carries .prov (provenance, including page and bbox).
    for item, _level in doc.iterate_items():
        prov_list = getattr(item, "prov", None) or []
        for prov in prov_list:
            page = getattr(prov, "page_no", None) or getattr(prov, "page", None)
            if page is None:
                continue
            page = int(page)
            bbox = getattr(prov, "bbox", None)
            block = {
                "type": item.label.value if hasattr(item, "label") else type(item).__name__,
                "text": getattr(item, "text", None) or getattr(item, "content", None) or "",
                "bbox": [bbox.l, bbox.t, bbox.r, bbox.b] if bbox else None,
                "page": page,
            }
            by_page.setdefault(page, []).append(block)

    for page in pages:
        blocks = by_page.get(page, [])
        (out / f"page-{page}.json").write_text(
            json.dumps(
                {
                    "extractor": "docling",
                    "source_pdf": str(pdf),
                    "page": page,
                    "blocks": blocks,
                },
                indent=2,
            )
        )
        md_lines = [b["text"] for b in blocks if b.get("text")]
        (out / f"page-{page}.md").write_text("\n\n".join(md_lines) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Docling on a PDF, per-page output.")
    parser.add_argument("--pdf", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--pages", required=True, help="e.g. '5', '5-10', '5,7,9-11'")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if not args.pdf.exists():
        print(f"PDF not found: {args.pdf}", file=sys.stderr)
        return 2

    pages = parse_pages(args.pages)

    if args.dry_run:
        write_dry_run(args.pdf, args.out, pages)
    else:
        run_docling(args.pdf, args.out, pages)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests**

```bash
uv run pytest scripts/tests/test_run_docling.py -v
```

Expected: 2 tests PASS.

- [ ] **Step 5: Smoke test on a real PDF**

```bash
uv run python scripts/run_docling.py \
  --pdf samples/raw-pdfs/jlbc-fiscal-note-misc.pdf \
  --out samples/extractor-output/docling/jlbc-fiscal-note-misc \
  --pages 1
```

Expected: page-1.json and page-1.md exist with non-empty content. If Docling returns extraction results that don't align with the assumed `iterate_items() + .prov` API (it has changed across recent versions), inspect with `python -c "from docling.document_converter import DocumentConverter; r = DocumentConverter().convert('samples/raw-pdfs/jlbc-fiscal-note-misc.pdf'); print(type(r.document)); print(dir(r.document))"` and adjust `run_docling()` to match the installed version's API. Document the version + adjustment in `samples/extractor-output/docling/README.md`.

- [ ] **Step 6: Document the setup**

Create `samples/extractor-output/docling/README.md`:

```markdown
# Docling Extractor Setup

## Version
- docling: <pinned version from `uv pip list`>
- Python: 3.11+
- Hardware: <CPU / GPU>

## Models downloaded
- (record on first run)

## API adjustments from baseline
- (note any changes from the assumed iterate_items / prov API)

## Known footguns observed
- (to fill in as they appear)

## Reproduction
From `~/ask-the-budget-az-dev/`:
```
uv run python scripts/run_docling.py --pdf <pdf> --out <dir> --pages <range>
```
```

- [ ] **Step 7: Commit**

```bash
git add scripts/run_docling.py scripts/tests/test_run_docling.py samples/extractor-output/docling/README.md pyproject.toml uv.lock
git commit -m "phase-0: add Docling wrapper and smoke test

Mirror of MinerU wrapper, kept independent so a regression in one path
doesn't masquerade as a regression in the other.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Pick the 20 representative pages

**Files:**
- Create: `samples/scoring-pages.yaml`

The point: deliberately surface every failure mode we know exists, not sample at random. Each chosen page targets at least one specific failure mode listed below.

- [ ] **Step 1: Open each PDF and identify candidate pages**

Use any PDF viewer. For each PDF, scroll through and mark candidate pages matching these archetypes (target totals across all PDFs):

- **5 pages: multi-page tables** — appropriations schedules that span 5+ pages, ideally with merged column headers (e.g., "FY 2024 Actual" / "FY 2025 Estimate" / "FY 2026 Request" header row spanning multiple sub-columns). Look in the JLBC Approps Report and the Governor's Budget.
- **3 pages: restated AFR tables** — fund-balance summaries or financial statements where prior-year figures were restated with a footnote like "(as restated)". AFR section "Notes to Financial Statements" usually has these.
- **3 pages: multi-column narrative** — JLBC Baseline Book program descriptions tend to be multi-column. Pick one that mixes prose with an inline small table.
- **3 pages: footnote-heavy schedules** — pages where one or more cells reference footnotes that are themselves at the bottom of the page (or the next page). Common in approps reports.
- **3 pages: cross-doc-name** — pick a program (e.g., "AHCCCS Acute Care") and find a page in the Baseline Book and a page in the Governor's Budget that both discuss it under different names. (This page targets entity-resolution stress; the bake-off scoring just notes whether each extractor preserves the on-page name accurately.)
- **3 pages: misc** — fiscal note prose+table, Baseline Book agency overview, AGAO MD&A narrative — variety to surface anything we haven't anticipated.

Total: ~20 pages.

- [ ] **Step 2: Record selections in `samples/scoring-pages.yaml`**

Create the file:

```yaml
# Pages selected for the Phase 0 extractor bake-off. Each entry names the
# specific failure modes that page targets; scoring will reference these
# labels to compute per-archetype quality, not just an overall score.
pages:
  - doc_id: jlbc-approps-fy25
    page: 47
    archetypes: ["multi-page-table", "merged-headers"]
    notes: "First page of ADC operating appropriations table — runs through page 51"

  - doc_id: jlbc-approps-fy25
    page: 51
    archetypes: ["multi-page-table"]
    notes: "Last page of same ADC table; tests reassembly"

  # ... etc for all ~20 pages
```

Fill in real page numbers from your actual PDFs.

- [ ] **Step 3: Sanity check — every archetype is represented**

Read the file. Confirm every archetype from Step 1 appears in at least one entry. If any are missing, find a page for it.

- [ ] **Step 4: Commit**

```bash
git add samples/scoring-pages.yaml
git commit -m "phase-0: select 20 representative pages for extractor bake-off

Pages chosen for failure-mode coverage, not random sampling. Archetype
tags let aggregate_scores.py compute per-archetype quality so we know
WHERE each extractor wins or loses, not just by how much.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Run both extractors on the chosen pages

**Files:**
- Generates: `samples/extractor-output/mineru/<doc-id>/page-<N>.{json,md}` (gitignored)
- Generates: `samples/extractor-output/docling/<doc-id>/page-<N>.{json,md}` (gitignored)

- [ ] **Step 1: Generate a runner from the page list**

Create a one-shot script that reads `samples/scoring-pages.yaml` and runs both extractors for each entry. This is throwaway — we don't need a test for it.

```bash
uv run python -c "
import yaml, subprocess, sys
from collections import defaultdict
pages = yaml.safe_load(open('samples/scoring-pages.yaml'))['pages']
by_doc = defaultdict(list)
for p in pages:
    by_doc[p['doc_id']].append(p['page'])
manifest = {d['id']: d for d in yaml.safe_load(open('samples/manifest.yaml'))['documents']}
for doc_id, page_list in by_doc.items():
    pages_str = ','.join(str(p) for p in sorted(set(page_list)))
    pdf = manifest[doc_id]['local_path']
    print(f'>>> {doc_id} pages {pages_str}')
    for tool in ['mineru', 'docling']:
        out = f'samples/extractor-output/{tool}/{doc_id}'
        subprocess.run(['uv', 'run', 'python', f'scripts/run_{tool}.py',
                        '--pdf', pdf, '--out', out, '--pages', pages_str],
                       check=True)
"
```

This may take significant wall-clock time (large PDFs, real extractors). If a page fails on either extractor, do NOT abort the whole run — capture the error in `samples/extractor-output/<tool>/<doc-id>/page-<N>.error.txt` and continue. (Adjust the script to wrap each tool invocation in try/except if needed.)

- [ ] **Step 2: Confirm all expected outputs exist**

```bash
uv run python -c "
import yaml
from pathlib import Path
pages = yaml.safe_load(open('samples/scoring-pages.yaml'))['pages']
missing = []
for p in pages:
    for tool in ['mineru', 'docling']:
        for ext in ['json', 'md']:
            f = Path(f'samples/extractor-output/{tool}/{p[\"doc_id\"]}/page-{p[\"page\"]}.{ext}')
            if not f.exists():
                missing.append(str(f))
if missing:
    print('MISSING:'); [print(' ', m) for m in missing]
else:
    print('OK: all outputs present')
"
```

If any outputs are missing for non-error reasons (extractor silently dropped the page), debug the wrapper before proceeding to scoring. Scoring against missing data produces meaningless numbers.

- [ ] **Step 3: Commit (no output files, just any wrapper fixes)**

If you adjusted `run_mineru.py` or `run_docling.py` to handle real-PDF surprises during this task, commit those changes:

```bash
git add scripts/run_mineru.py scripts/run_docling.py
git commit -m "phase-0: extractor-wrapper fixes from real-PDF runs

- <describe specific issues encountered>

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

If no fixes were needed, this step is a no-op.

---

## Task 6: Define scoring rubric

**Files:**
- Create: `samples/scoring-rubric.md`

- [ ] **Step 1: Write the rubric**

Create `samples/scoring-rubric.md`:

```markdown
# Scoring Rubric — Phase 0 Extractor Bake-Off

Five dimensions, scored 0–3 per (page × extractor). Not every dimension
applies to every page — see the "When applies" column. Use NA when a
dimension doesn't apply; aggregate stats compute over applicable cells only.

## Scale

| Score | Meaning |
|---|---|
| **3** | Clean. Output matches the PDF closely enough that downstream chunking + retrieval would work correctly. |
| **2** | Minor issues. Output is mostly right; an analyst reading the chunk would not be misled, but some quality is lost (e.g., column alignment off by one, paragraph break missing). |
| **1** | Major issues. Output contains a wrong fact (e.g., wrong dollar figure, footnote attached to wrong row, table column misaligned in a way that conflates rows). Downstream system would mislead an analyst. |
| **0** | Failed. Extractor errored, omitted the content entirely, or produced gibberish. |
| **NA** | Dimension does not apply to this page (e.g., footnote-attachment NA on a page with no footnotes). |

## Dimensions

### 1. Cell-level numeric accuracy
**When applies:** Pages with tables that have numeric cells.
**Procedure:** Pick 5–10 cells from the page (mix top, middle, bottom; mix small and large numbers). For each, compare the extracted value to the PDF.
- 3: All cells match exactly (digit-for-digit).
- 2: 1 cell off by formatting only (e.g., `$1.74B` vs `1740000000`); no numeric drift.
- 1: At least 1 cell has a wrong digit, dropped digit, or shifted decimal.
- 0: Numbers absent or scrambled.

### 2. Bbox quality
**When applies:** All pages.
**Procedure:** Open the JSON. For 3 randomly-chosen blocks, look at the reported `bbox` and overlay it mentally on the PDF page.
- 3: Bbox tightly surrounds the reported text on all 3 spot checks.
- 2: Bbox is a few pixels off but clearly indicates the right region on all 3.
- 1: At least 1 bbox points to the wrong region or is off by an amount that would highlight unrelated text in the side-panel viewer.
- 0: No bboxes provided, or bboxes are clearly wrong (zeros, negative, way outside the page).

### 3. Multi-page table reassembly
**When applies:** Pages flagged with `multi-page-table` archetype, AND specifically the LAST page of a multi-page table (not all pages of one).
**Procedure:** Look at the chunks/blocks from this page. Does the extractor know this content continues the table from previous pages? (Some extractors expose a `table_continues_from` flag; others rely on the structural type label being consistent across pages.)
- 3: Yes, with explicit linkage to the prior page's table object.
- 2: Yes, but only structurally (same column headers, same row pattern, no explicit linkage).
- 1: Treats this page as a fresh table, losing connection to the rest.
- 0: Fails to detect a table at all.

### 4. Section header detection
**When applies:** All pages.
**Procedure:** For each clear visual heading on the PDF page (look at font size, weight, vertical spacing), check whether the extractor labeled it as a heading (vs. body paragraph).
- 3: Every visual heading is labeled as a heading; no false positives.
- 2: 1 missing or 1 false positive.
- 1: ≥ 2 missing or ≥ 2 false positives, OR a critical heading is missed (e.g., agency name).
- 0: No heading detection at all (everything labeled as body text).

### 5. Footnote attachment
**When applies:** Pages flagged with `footnote-heavy` archetype, OR any page where a numeric cell carries a footnote marker (`*`, `(1)`, etc.).
**Procedure:** For 1 footnote on the page, check whether the extractor associated it with the correct cell/row.
- 3: Footnote is attached to the right row (either as part of the row's chunk or via an explicit reference).
- 2: Footnote text extracted but as an unattached block; analyst could pair them manually.
- 1: Footnote attached to the wrong row, OR text mangled.
- 0: Footnote dropped entirely.

## Recording

For each (page × extractor) combination, fill one row in:
- `samples/scores-mineru.csv`
- `samples/scores-docling.csv`

with this header:
`doc_id,page,archetypes,cell_accuracy,bbox_quality,multipage_reassembly,header_detection,footnote_attachment,notes`

Use `NA` for non-applicable dimensions. `notes` is freeform; capture anything surprising.
```

- [ ] **Step 2: Commit**

```bash
git add samples/scoring-rubric.md
git commit -m "phase-0: define 0-3 scoring rubric across 5 dimensions

NA cells handled explicitly; aggregate stats compute over applicable
cells only (so a page without footnotes doesn't drag down footnote
scores).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Score MinerU outputs

**Files:**
- Create: `samples/scores-mineru.csv`

This is **manual** — there's no automated way to do this honestly. Plan ~3–4 hours of focused work for ~20 pages.

- [ ] **Step 1: Write the CSV header**

Create `samples/scores-mineru.csv`:

```csv
doc_id,page,archetypes,cell_accuracy,bbox_quality,multipage_reassembly,header_detection,footnote_attachment,notes
```

- [ ] **Step 2: Score each page**

For each entry in `samples/scoring-pages.yaml`:

1. Open the PDF in a viewer, navigate to the page.
2. Open `samples/extractor-output/mineru/<doc-id>/page-<N>.json` and `.md` side by side.
3. For each applicable dimension (per the rubric's "When applies"), assign 0–3 or NA.
4. Append a CSV row.

If you encounter a surprising failure mode the rubric doesn't cover, capture it in `notes`. Do not silently invent a new dimension mid-scoring — capture as a note, decide post-hoc whether to add a 6th dimension.

- [ ] **Step 3: Spot-check internal consistency**

Pick 3 random rows. Re-score those pages from scratch (without looking at your prior score). If any score differs by more than 1 across both passes, your rubric is too subjective — refine the rubric (in `scoring-rubric.md`) and re-score those pages.

- [ ] **Step 4: Commit**

```bash
git add samples/scores-mineru.csv
git commit -m "phase-0: manual MinerU scores across 20 pages × 5 dimensions

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Score Docling outputs

**Files:**
- Create: `samples/scores-docling.csv`

Same procedure as Task 7, against `samples/extractor-output/docling/...`.

- [ ] **Step 1: Write the CSV header**

```csv
doc_id,page,archetypes,cell_accuracy,bbox_quality,multipage_reassembly,header_detection,footnote_attachment,notes
```

- [ ] **Step 2: Score each page**

Same procedure as Task 7. Important: **score against the same rubric**, not "compared to MinerU." Bias from already-knowing-MinerU-was-good leaks; minimize by scoring Docling without referring back to MinerU's score.

- [ ] **Step 3: Spot-check**

Same as Task 7 Step 3.

- [ ] **Step 4: Commit**

```bash
git add samples/scores-docling.csv
git commit -m "phase-0: manual Docling scores across 20 pages × 5 dimensions

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: Aggregate scores and identify the winner

**Files:**
- Create: `scripts/aggregate_scores.py`
- Create: `scripts/tests/test_aggregate_scores.py`
- Generates: `samples/score-summary.md`

- [ ] **Step 1: Write the failing test**

Create `scripts/tests/test_aggregate_scores.py`:

```python
"""Tests for scripts/aggregate_scores.py.

Computes per-extractor totals, per-dimension means, and per-archetype
breakdowns from the two scores CSVs. NA is excluded from means.
"""

import subprocess
import sys
import textwrap
from pathlib import Path


HEADER = "doc_id,page,archetypes,cell_accuracy,bbox_quality,multipage_reassembly,header_detection,footnote_attachment,notes\n"


def write_scores(path: Path, rows: list[str]) -> None:
    path.write_text(HEADER + "\n".join(rows) + "\n")


def run(tmp_path: Path) -> subprocess.CompletedProcess:
    src = Path(__file__).parent.parent / "aggregate_scores.py"
    (tmp_path / "scripts").mkdir(exist_ok=True)
    (tmp_path / "scripts" / "aggregate_scores.py").write_text(src.read_text())
    return subprocess.run(
        [sys.executable, "scripts/aggregate_scores.py"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )


def test_excludes_NA_from_means(tmp_path: Path) -> None:
    (tmp_path / "samples").mkdir()
    write_scores(
        tmp_path / "samples" / "scores-mineru.csv",
        [
            'doc1,1,"multi-page-table",3,3,3,3,NA,',
            'doc1,2,"footnote-heavy",NA,3,NA,3,2,',
        ],
    )
    write_scores(
        tmp_path / "samples" / "scores-docling.csv",
        [
            'doc1,1,"multi-page-table",2,2,2,2,NA,',
            'doc1,2,"footnote-heavy",NA,2,NA,2,1,',
        ],
    )

    result = run(tmp_path)
    assert result.returncode == 0, result.stderr

    summary = (tmp_path / "samples" / "score-summary.md").read_text()
    # MinerU footnote_attachment: only one applicable cell (value 2) -> mean = 2.0
    assert "footnote_attachment" in summary
    # Docling cell_accuracy: only one applicable cell (value 2) -> mean = 2.0
    assert "cell_accuracy" in summary


def test_winner_emerges_when_one_dominates(tmp_path: Path) -> None:
    (tmp_path / "samples").mkdir()
    write_scores(
        tmp_path / "samples" / "scores-mineru.csv",
        ['doc1,1,"x",3,3,3,3,3,'],
    )
    write_scores(
        tmp_path / "samples" / "scores-docling.csv",
        ['doc1,1,"x",1,1,1,1,1,'],
    )

    result = run(tmp_path)
    assert result.returncode == 0, result.stderr
    summary = (tmp_path / "samples" / "score-summary.md").read_text()
    assert "MinerU" in summary
```

- [ ] **Step 2: Implement the aggregator**

Create `scripts/aggregate_scores.py`:

```python
"""Aggregate Phase 0 extractor scores into a Markdown summary.

Reads:
  samples/scores-mineru.csv
  samples/scores-docling.csv

Writes:
  samples/score-summary.md  — per-dimension means, per-archetype means,
                              per-doc means, and a winner declaration.

Means exclude NA cells (computed only over applicable dimensions per page).
"""

import csv
import statistics
from pathlib import Path
from collections import defaultdict


DIMENSIONS = [
    "cell_accuracy",
    "bbox_quality",
    "multipage_reassembly",
    "header_detection",
    "footnote_attachment",
]


def load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open() as f:
        return list(csv.DictReader(f))


def parse_score(s: str) -> int | None:
    s = s.strip()
    if s.upper() == "NA" or s == "":
        return None
    return int(s)


def mean(values: list[int]) -> float | None:
    if not values:
        return None
    return statistics.mean(values)


def fmt(v: float | None) -> str:
    return "—" if v is None else f"{v:.2f}"


def aggregate(rows: list[dict]) -> dict:
    by_dim: dict[str, list[int]] = {d: [] for d in DIMENSIONS}
    by_arch: dict[str, list[int]] = defaultdict(list)
    by_doc: dict[str, list[int]] = defaultdict(list)
    for row in rows:
        for dim in DIMENSIONS:
            v = parse_score(row[dim])
            if v is not None:
                by_dim[dim].append(v)
                by_doc[row["doc_id"]].append(v)
                for arch in row["archetypes"].strip('"').split(";"):
                    if arch.strip():
                        by_arch[arch.strip()].append(v)
    return {
        "by_dim": {d: mean(vs) for d, vs in by_dim.items()},
        "by_arch": {a: mean(vs) for a, vs in by_arch.items()},
        "by_doc": {d: mean(vs) for d, vs in by_doc.items()},
        "overall": mean([v for vs in by_dim.values() for v in vs]),
    }


def main() -> int:
    mineru = aggregate(load(Path("samples/scores-mineru.csv")))
    docling = aggregate(load(Path("samples/scores-docling.csv")))

    lines: list[str] = []
    lines.append("# Phase 0 Extractor Bake-Off — Aggregate Scores\n")
    lines.append(f"Computed from `samples/scores-mineru.csv` and `samples/scores-docling.csv`.\n")

    lines.append("## Overall mean (NA-excluded, 0–3 scale)\n")
    lines.append(f"- MinerU: **{fmt(mineru['overall'])}**")
    lines.append(f"- Docling: **{fmt(docling['overall'])}**\n")

    lines.append("## Per-dimension mean\n")
    lines.append("| Dimension | MinerU | Docling |")
    lines.append("|---|---|---|")
    for d in DIMENSIONS:
        lines.append(f"| {d} | {fmt(mineru['by_dim'][d])} | {fmt(docling['by_dim'][d])} |")
    lines.append("")

    archs = sorted(set(mineru["by_arch"]) | set(docling["by_arch"]))
    lines.append("## Per-archetype mean\n")
    lines.append("| Archetype | MinerU | Docling |")
    lines.append("|---|---|---|")
    for a in archs:
        lines.append(f"| {a} | {fmt(mineru['by_arch'].get(a))} | {fmt(docling['by_arch'].get(a))} |")
    lines.append("")

    docs = sorted(set(mineru["by_doc"]) | set(docling["by_doc"]))
    lines.append("## Per-document mean\n")
    lines.append("| Document | MinerU | Docling |")
    lines.append("|---|---|---|")
    for d in docs:
        lines.append(f"| {d} | {fmt(mineru['by_doc'].get(d))} | {fmt(docling['by_doc'].get(d))} |")
    lines.append("")

    if mineru["overall"] is not None and docling["overall"] is not None:
        if mineru["overall"] > docling["overall"]:
            winner = "MinerU"
            margin = mineru["overall"] - docling["overall"]
        elif docling["overall"] > mineru["overall"]:
            winner = "Docling"
            margin = docling["overall"] - mineru["overall"]
        else:
            winner = "tie"
            margin = 0.0
        lines.append("## Headline\n")
        lines.append(
            f"**{winner}** leads by {margin:.2f} on overall mean. "
            f"See per-archetype table for where each excels — pick a winner with "
            f"per-archetype context, not just the overall number."
        )

    Path("samples/score-summary.md").write_text("\n".join(lines))
    print("wrote samples/score-summary.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: Run the tests**

```bash
uv run pytest scripts/tests/test_aggregate_scores.py -v
```

Expected: 2 tests PASS.

- [ ] **Step 4: Run the aggregator on real scores**

```bash
uv run python scripts/aggregate_scores.py
cat samples/score-summary.md
```

Expected: a markdown summary with overall mean, per-dimension table, per-archetype table, per-document table, and a "Headline" stating which extractor leads.

- [ ] **Step 5: Commit**

```bash
git add scripts/aggregate_scores.py scripts/tests/test_aggregate_scores.py samples/score-summary.md
git commit -m "phase-0: aggregate extractor scores into per-dim/per-arch summary

NA-excluded means; per-archetype breakdown lets us pick a winner
informed by where each extractor wins or loses, not just overall.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: Pick entity-resolution catalog targets

**Files:**
- Create: `data/entity-targets.yaml`

- [ ] **Step 1: Pick 10 agencies**

Pick 10 Arizona state agencies that appear in all four doc types and have meaningful budget activity. Prioritize variance in name conventions — include agencies known by short names (ADC, AHCCCS, ADE), full names ("Department of Health Services"), and any that have been reorganized recently (where prior years' AFRs may use a now-obsolete name).

Suggested starter list (adjust based on which actually appear in your sample PDFs):
- Department of Corrections
- AHCCCS (Arizona Health Care Cost Containment System)
- Arizona Department of Education
- Department of Economic Security
- Department of Health Services
- Department of Public Safety
- Department of Transportation
- Department of Revenue
- Department of Child Safety
- Universities (Arizona Board of Regents)

- [ ] **Step 2: Pick 7 programs**

For each of 4–5 agencies, pick 1–2 specific programs the JLBC Baseline Book describes. Look for programs that should appear in all 4 doc types, and ideally programs that have changed scope between FY23 and FY25 (so we can stress-test cross-year canonicalization).

- [ ] **Step 3: Pick 3 sub-program / line items**

These are the long-tail items — pick 3 specific line items (e.g., "County Reimbursement", "Special Line Item — Private Prison Per Diem Adjustment"). The hypothesis is that sub-programs are very messy across doc types; we're sampling to confirm.

- [ ] **Step 4: Record in YAML**

Create `data/entity-targets.yaml`:

```yaml
# Tier 0 entity-resolution catalog targets.
# We'll find each entity's name as it appears in each of the 4 doc types,
# then assess how tractable a canonical map would be at each tier.
agencies:
  - id: adc
    primary_name: "Department of Corrections"
    short_name: "ADC"
  - id: ahcccs
    primary_name: "Arizona Health Care Cost Containment System"
    short_name: "AHCCCS"
  # ... 8 more

programs:
  - id: adc-operating
    agency_id: adc
    primary_name: "Adult Corrections Operations"
  - id: ahcccs-acute-care
    agency_id: ahcccs
    primary_name: "AHCCCS Acute Care"
  # ... 5 more

line_items:
  - id: adc-county-reimbursement
    agency_id: adc
    program_id: adc-operating
    primary_name: "County Reimbursement"
  # ... 2 more
```

- [ ] **Step 5: Commit**

```bash
git add data/entity-targets.yaml
git commit -m "phase-0: pick 10 agencies, 7 programs, 3 line items for catalog

Variance-prioritized selection — short names, full names, recently
reorganized agencies — to stress-test canonical-map difficulty.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 11: Catalog entity name variance

**Files:**
- Create: `data/entity-variance-catalog.csv`

This is **manual** — for each target × 4 doc types, find how each is named.

- [ ] **Step 1: Write the CSV header**

Create `data/entity-variance-catalog.csv`:

```csv
target_id,target_tier,target_primary,doc_type,fiscal_year,observed_name,observed_page,notes
```

- [ ] **Step 2: Find each target in each doc type**

For each entity in `data/entity-targets.yaml`:

For each doc type (`baseline-book`, `approps-report`, `afr`, `governors-budget`):
- Open the corresponding PDF (use the FY25 docs unless otherwise noted)
- Search for the entity (Ctrl+F with the primary name and any obvious variants)
- Find the first authoritative mention (a heading, table row label, or section title — not a passing reference in body text)
- Record one row per (target × doc_type) in the CSV with:
  - `observed_name`: exact text on the page
  - `observed_page`: page number
  - `notes`: anything notable (e.g., "appears as 'Adult Corrections' in approps but 'Department of Corrections' in AFR")

If an entity doesn't appear in a given doc type, record `observed_name: "—"` and explain in notes.

- [ ] **Step 3: Spot-check for fabrications**

This is the tedious-but-mandatory step. Re-verify 3 random rows by opening the cited page and confirming the name matches. If any row is fabricated or wrong, the whole catalog is suspect — re-do those entries and audit the rest.

- [ ] **Step 4: Compute per-tier variance summary**

In one quick analysis (no script needed), count for each tier:
- How many distinct `observed_name` values per `target_id`?
- How many `target_id` values have ≥ 3 distinct names? (high-variance)
- Are there any `target_id` values where `observed_name` is missing in ≥ 2 doc types? (low-coverage)

Note these counts at the bottom of the CSV in a comment, or in a quick `data/entity-variance-summary.md`. Used in the findings memo (Task 13).

- [ ] **Step 5: Commit**

```bash
git add data/entity-variance-catalog.csv data/entity-variance-summary.md
git commit -m "phase-0: catalog entity name variance across 4 doc types

20 entities × 4 doc types observed; per-tier variance summary informs
Tier 1 entity-resolution scope decision in the findings memo.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 12: Validate chunking shape on the winning extractor

**Files:**
- Create: `samples/chunking-validation.md`

This task is **conditional**: skip if both extractors scored below 1.5 on overall mean (in which case we have a different problem). Use the winning extractor from Task 9.

- [ ] **Step 1: Pick 5 representative pages of extractor output**

From the 20 scored pages, pick 5 that span: a multi-page table (start page), a multi-column narrative, a footnote-heavy schedule, a fiscal note prose+table, and one "boring" page (clean single-column section).

- [ ] **Step 2: Apply the spec's chunking rules manually**

For each page's extractor output, manually mark up where chunks would split if we applied the spec's rules (§9 in the design spec):
- Section-aware (split at headers, not at fixed lengths)
- Tables atomic (never split mid-row; one chunk per table)
- Footnotes attach to their reference row's chunk
- Target 512 tokens per narrative chunk, max 1024
- ~15% overlap between adjacent narrative chunks

Annotate each chunk with: token count estimate, what metadata it would carry (`section_path`, `is_table`, `agency_canonical_id` from the entity catalog if known), and any problems you hit (e.g., "this section runs 3,000 tokens with no internal subheadings — what now?").

- [ ] **Step 3: Document findings**

Create `samples/chunking-validation.md`:

```markdown
# Chunking Validation — Phase 0

Applied the spec's structure-aware chunking rules (§9) to the winning
extractor's output on 5 representative pages.

## Cases that worked cleanly
- (list pages where the rules produced a sensible chunking with no manual fix)

## Cases that needed adjustment
- (list pages where the rules failed; describe the failure and the fix)

## Open issues for Phase 1
- (e.g., "agency sections in the FY23 Baseline Book occasionally exceed 5K
  tokens with no subheadings; need a fallback split heuristic")
```

- [ ] **Step 4: Commit**

```bash
git add samples/chunking-validation.md
git commit -m "phase-0: validate chunking strategy on winning extractor

5 pages × structure-aware rules; documents cases that worked vs. needed
manual adjustment, and surfaces open issues for Phase 1 chunker design.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 13: Write the findings memo

**Files:**
- Create: `docs/superpowers/investigations/2026-MM-DD-phase-0-bakeoff.md` (use the actual execution date)

- [ ] **Step 1: Write the memo**

The memo is the primary deliverable of Phase 0. It needs to be a self-contained document that someone with no Phase 0 context can read and understand the v1 architecture decisions that came out of it.

Create `docs/superpowers/investigations/2026-MM-DD-phase-0-bakeoff.md` (replace `MM-DD` with the actual date you finalize the memo):

```markdown
---
title: Phase 0 Findings — Extractor Bake-Off, Entity Catalog, Chunking Validation
date: 2026-MM-DD
status: complete
authors: Destin Moss, Claude
relates_to: docs/superpowers/specs/2026-05-04-ask-the-budget-az-design.md
---

# Phase 0 Findings

## TL;DR

- **Recommended extractor:** [MinerU 2.5 / Docling]. Overall mean: [X.XX] vs. [Y.YY] for the loser. See §2.
- **Tier 1 entity-resolution scope:** [agencies only / agencies + N programs]. See §3.
- **Chunking strategy:** [held / adjusted, see §4].
- **Phase 1 go/no-go:** [GO / GO with caveats / NO-GO]. See §6.

## 1. What we ran

[Briefly describe sample corpus: 6 PDFs, 20 pages, 5 dimensions, 2 extractors. Reference samples/manifest.yaml and samples/scoring-pages.yaml.]

## 2. Extractor bake-off

### 2.1 Overall scores
[Insert overall mean table from samples/score-summary.md.]

### 2.2 Per-dimension breakdown
[Insert per-dimension table.]

### 2.3 Per-archetype breakdown — where each wins or loses
[Insert per-archetype table. Discuss any surprises: e.g., "MinerU dominated on multi-page-table reassembly but lost on footnote-attachment, suggesting we'll need a footnote post-processor regardless of which extractor we use."]

### 2.4 Recommendation
[State the chosen primary extractor + one-paragraph reasoning. State the documented fallback. State any pages or page-types where the primary failed badly enough that we should pre-route those to the fallback (or to Claude vision escalation if we end up adding it).]

## 3. Entity-resolution catalog

### 3.1 Per-tier variance counts
[From data/entity-variance-summary.md: how many distinct names per agency, per program, per line item.]

### 3.2 Tier 1 scope recommendation
[State which tier(s) go into v1's canonical map. Justify with the variance counts: "Agency level had at most N distinct names per agency, all expressible as a small alias list — tractable. Program level had Y distinct names per program with M cases of cross-doc-type drift — possible but requires curation pipeline; defer to Tier 2. Line items: extreme variance — defer."]

### 3.3 Difficulty-rated catalog
| Tier | Tractable for v1? | Notes |
|---|---|---|
| Agency | [yes/no] | ... |
| Program | [yes/no] | ... |
| Sub-program / line item | [yes/no] | ... |

## 4. Chunking validation

[From samples/chunking-validation.md: which rules held, which needed adjustment, what new heuristics are needed for Phase 1.]

## 5. Surprises and footguns

[Anything we didn't anticipate. Examples to look for:
- An extractor consistently fails on a specific publisher's tables
- Restated AFR tables silently overwrite the prior year's numbers in the extractor output (or don't)
- A document we expected to be public has access barriers
- A failure mode we didn't catalog in the rubric]

## 6. Phase 1 go/no-go

State one of:
- **GO** — winning extractor scored above [threshold, e.g., 2.0 mean] and no critical archetype scored below [e.g., 1.5]. Phase 1 may proceed with the chosen stack.
- **GO with caveats** — winning extractor is good enough overall but we have known issues at [specific archetypes/doc types]. Phase 1 must include [specific mitigations].
- **NO-GO** — open-source quality insufficient. Reopen the paid-extractor question; revise the spec.

## 7. Files this memo references
- `samples/manifest.yaml`
- `samples/scoring-pages.yaml`
- `samples/scores-mineru.csv`
- `samples/scores-docling.csv`
- `samples/score-summary.md`
- `samples/chunking-validation.md`
- `data/entity-targets.yaml`
- `data/entity-variance-catalog.csv`
- `data/entity-variance-summary.md`
```

Fill in every bracketed section with real findings. **Do not commit the memo with bracketed placeholders.**

- [ ] **Step 2: Self-review the memo**

Read it cold. Three checks:
1. Could a future contributor read this without having run Phase 0 and understand what Phase 1 should do?
2. Are claims backed by data files? (Every quantitative claim should reference a CSV or summary file.)
3. Is the go/no-go decision concrete and falsifiable?

If any answer is no, fix inline.

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/investigations/2026-MM-DD-phase-0-bakeoff.md
git commit -m "phase-0: findings memo — extractor winner, Tier 1 scope, go/no-go

Phase 0 deliverable. Names the primary extractor with per-dimension and
per-archetype evidence; states Tier 1 entity-resolution scope based on
the variance catalog; identifies chunking adjustments for Phase 1.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 14: Update spec with Phase 0 outcomes and tag completion

**Files:**
- Modify: `docs/superpowers/specs/2026-05-04-ask-the-budget-az-design.md` (resolve some Open Questions in §16)
- Modify: `CLAUDE.md` (mark Phase 0 status complete)

- [ ] **Step 1: Update spec Open Questions**

Open `docs/superpowers/specs/2026-05-04-ask-the-budget-az-design.md`. Find §16 "Open Questions". For each question that Phase 0 resolved, replace the question with a brief resolution + a link to the memo. For questions still open, leave them.

Specifically:
- **Tier 1 entity scope** — resolved by §3 of the memo. Replace question with: "Resolved 2026-MM-DD by Phase 0 findings: Tier 1 includes [agencies / agencies + programs]. See `docs/superpowers/investigations/2026-MM-DD-phase-0-bakeoff.md`."
- **AFR restated tables** — resolved if Phase 0 tested them; otherwise still open. Update accordingly.
- **Comparison query decomposition heuristics** — likely still open; depends on Phase 1 query patterns.
- **Faithfulness verifier model choice** — still open; Phase 1 spike.
- **Companion app framework** — still open; Phase 2.
- **JLBC SSO availability** — still open; pending JLBC IT.

Also update §9's extractor row to reference the chosen winner directly, instead of listing both as options.

- [ ] **Step 2: Update CLAUDE.md phase status**

In `CLAUDE.md`, find the Project Phases table. Change Phase 0's status from "not started" to "complete (YYYY-MM-DD)". Optionally add a one-line note: "Findings memo: `docs/superpowers/investigations/...`".

- [ ] **Step 3: Tag the milestone in git**

```bash
git tag phase-0-complete -m "Phase 0 investigation complete; findings memo committed"
git tag --list  # verify
```

(No remote yet, so no push needed.)

- [ ] **Step 4: Commit the spec and CLAUDE.md updates**

```bash
git add docs/superpowers/specs/2026-05-04-ask-the-budget-az-design.md CLAUDE.md
git commit -m "phase-0: spec + CLAUDE.md updates from Phase 0 outcomes

Resolves Tier 1 entity scope, names the chosen extractor, marks Phase 0
status complete. Remaining §16 Open Questions stay open for Phase 1+.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

After writing this plan, the following spec coverage check passes:

| Spec section | Plan task(s) |
|---|---|
| §8.1 Sample corpus | Task 1 |
| §8.2 Extractor bake-off | Tasks 2, 3, 4, 5, 6, 7, 8, 9 |
| §8.3 Entity-resolution catalog | Tasks 10, 11 |
| §8.4 Chunking shape validation | Task 12 |
| §8.5 Phase 0 deliverables | All deliverables produced; final memo in Task 13 |
| Phase 1 go/no-go decision | Task 13 (§6 of memo) |

No bracketed placeholders remain in plan task content (the memo template intentionally has bracketed fill-in fields, since those resolve only at execution). All file paths are concrete; all commands include exact arguments. Type/method names are consistent across the four script files (`run_mineru.py`, `run_docling.py`, `check_pdf_manifest.py`, `aggregate_scores.py`) — no signature drift.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-04-phase-0-investigation.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using `executing-plans`, batch execution with checkpoints.

Which approach?
