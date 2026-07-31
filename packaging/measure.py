"""Bundle feasibility spike — measure the distributable before building it (Plan 5, Task 14).

WHY this exists: S7 says "install = unzip to %LOCALAPPDATA%, embeddable Python,
all model weights pre-bundled, first run downloads nothing." Whether that is a
400 MB zip or a 6 GB zip decides the shape of the whole distribution, and
nobody had measured it. This script produces the number.

WHAT IT MEASURES, and the honest caveat: it resolves and downloads the **Windows**
wheel closure (`--python-platform x86_64-pc-windows-msvc`) from whatever machine
you run it on. uv can resolve for a foreign platform, so a Linux dev box produces
a real Windows *size*. It proves nothing about whether those wheels *import* on a
Windows PC — that is Task 15's acceptance criterion (server starts, network
unplugged, machine that has never had Python).

Profiles:
  client  — search + fiscal notes + AI Mode + upload-to-queue. No PDF extraction.
  ingest  — client + both extractors (MinerU pipeline, opendataloader-pdf).

Usage:
    python packaging/measure.py                     # both profiles, JSON + table to stdout
    python packaging/measure.py --profile client    # one profile
    python packaging/measure.py --keep              # don't delete the resolved trees
    python packaging/measure.py --json out.json
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# The Windows target the office runs. JLBC machines are 64-bit Intel.
WINDOWS_PLATFORM = "x86_64-pc-windows-msvc"
PYTHON_VERSION = "3.12"

# ---------------------------------------------------------------------------
# Requirement sets
# ---------------------------------------------------------------------------
# Derived from a repo-wide scan of third-party imports under app/, harness/,
# store/, ingest/, chunking/, retrieval/{pipeline,citations,local_*}.py — NOT
# from pyproject.toml, which still carries the retired Postgres/Voyage/Anthropic
# stack that Plan 5 Task 18 deletes. Bundling pyproject as-is would ship ~150 MB
# of dependencies for code that no longer exists.
#
# import -> distribution:
#   fastapi, starlette      -> fastapi
#   uvicorn                 -> uvicorn[standard]  (serves the SPA + API)
#   lancedb, pyarrow        -> lancedb  (pyarrow is transitive but pinned here
#                                        because store/schema.py imports it directly)
#   fastembed               -> fastembed  (lazy-imported by retrieval/local_embedder.py
#                                          and local_rerank.py; ONNX runtime + tokenizers)
#   httpx                   -> httpx  (OpenRouter tool loop + catalog fetch)
#   pydantic                -> pydantic
#   docx                    -> python-docx  (AI Mode memo export)
#   yaml                    -> pyyaml
#   bs4                     -> beautifulsoup4  (JLBC page scraper)
#   rapidfuzz               -> rapidfuzz  (agency-name matching)
#   requests                -> requests  (DownloadCache)
#   fitz                    -> pymupdf  (page counts + the PDF viewer's page/bbox work)
#
# tiktoken is deliberately NOT here: its only consumer is
# chunking/builders/_tokens.py, reached from chunking/builder.py and
# table_chunk.py — i.e. ingest only. See the note on INGEST_ONLY_REQUIREMENTS
# for why keeping it off client machines is more than a 2 MB saving.
CLIENT_REQUIREMENTS = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "lancedb>=0.36.0",
    "pyarrow",
    "fastembed>=0.8.0",
    "httpx>=0.28.1",
    "pydantic>=2.9.0",
    "python-docx>=1.2.0",
    "pyyaml>=6.0.3",
    "beautifulsoup4>=4.14.0",
    "rapidfuzz>=3.10.0",
    "requests>=2.32.0",
    "pymupdf",
]

# Ingest-only. Both are extractors: MinerU handles JLBC Appropriations Reports and
# Baseline Books; opendataloader-pdf handles AFRs and the Governor's budget
# (ingest/dispatcher.py's routing table). Neither is reachable from search or AI Mode.
#
# MinerU is PINNED, not floored. The live corpus was extracted with 3.1.6, and the
# plan explicitly declines the 3.4.4 upgrade because it changes chunk text
# corpus-wide (a full re-ingest plus re-authored eval ground truth). A bundle
# built from `>=3.1.6` silently resolves to 3.4.4 and quietly un-declines that
# decision — the ingest machine would then produce chunks that disagree with
# every chunk already in LanceDB.
#
# tiktoken lives here because chunk boundaries depend on it, and it FAILS SOFT.
# `_try_tiktoken()` wraps `get_encoding("cl100k_base")` in `except Exception` and
# falls back to a 4-chars-per-token heuristic — and tiktoken downloads that
# encoding from openaipublic.blob.core.windows.net on first use unless
# TIKTOKEN_CACHE_DIR is pre-populated (tiktoken/load.py:37). So an offline ingest
# machine with no primed cache would not error: it would quietly chunk on
# different boundaries than every chunk already in LanceDB. Same class of harm as
# the MinerU 3.4.4 upgrade the plan declined, arriving silently.
INGEST_ONLY_REQUIREMENTS = [
    "mineru[pipeline]==3.1.6",
    "opendataloader-pdf>=2.4.1",
    "tiktoken",
]

# torch source. MEASURED both ways (2026-08-01): on **Windows** the PyPI torch
# wheel and download.pytorch.org's `+cpu` wheel are the same build — torch 2.13.0,
# 442.6 MB, byte-identical closures apart from the local version tag. The CPU index
# is a no-op here. It is NOT a no-op on Linux, where PyPI torch drags in the bundled
# nvidia CUDA runtime (which is why this repo's pyproject routes torch to cu128 for
# the dev box's GPU). Kept as the default so a future Linux/`--platform` run of this
# script doesn't quietly measure a 3 GB CUDA closure and call it the office bundle.
TORCH_CPU_INDEX = "https://download.pytorch.org/whl/cpu"

# MEASURED BLOCKER (2026-08-01): mineru 3.1.6 — the version the live corpus was
# extracted with — depends on omegaconf>=2.3.0, which pins
# antlr4-python3-runtime==4.9.*, and antlr4 4.9.x publishes **no wheel**, only an
# sdist. A wheel-only closure (`--only-binary=:all:`, which is what S7's "prebuilt
# site-packages" means) therefore cannot resolve mineru 3.1.6 at all.
#
# It is a one-package problem with a clean fix: antlr4-python3-runtime is pure
# Python and builds to a `py3-none-any` wheel (144 KB, verified), so a wheel built
# once on any machine is valid on Windows. The bundle builder pre-builds it into a
# local wheel dir and passes --find-links. Point --find-links at that dir here to
# reproduce the pinned-3.1.6 measurement.
#
# mineru 3.4.4 dropped omegaconf and resolves wheel-only with no help — but taking
# 3.4.4 is the corpus-wide re-ingest the plan explicitly declined.

# ---------------------------------------------------------------------------
# Static (non-wheel) components of the bundle
# ---------------------------------------------------------------------------
# Sizes we can measure locally from real caches rather than guess.
FASTEMBED_MODELS = {
    "snowflake-arctic-embed-m (embeddings)": "models--Snowflake--snowflake-arctic-embed-m",
    "ms-marco-MiniLM-L-12-v2 (reranker)": "models--Xenova--ms-marco-MiniLM-L-12-v2",
}
# MinerU 3.x pipeline backend. Path comes from ~/mineru.json's models-dir.pipeline.
MINERU_MODEL_REPO = "models--opendatalab--PDF-Extract-Kit-1.0"

# python.org Windows embeddable distribution, amd64. Measured, not estimated:
# the script downloads it.
EMBEDDABLE_URL = "https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip"


@dataclass
class PackageSize:
    name: str
    bytes: int


@dataclass
class ProfileMeasurement:
    profile: str
    platform: str
    total_bytes: int = 0
    package_count: int = 0
    packages: list[PackageSize] = field(default_factory=list)
    resolved: list[str] = field(default_factory=list)
    error: str | None = None


def _human(n: int | None) -> str:
    if n is None:
        return "n/a"
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024.0
    return f"{n:.1f} GB"


def _tree_bytes(path: Path) -> int:
    """Real bytes on disk, following the HF cache's symlinked blobs once."""
    total = 0
    seen: set[tuple[int, int]] = set()
    for root, _dirs, files in os.walk(path, followlinks=False):
        for name in files:
            p = Path(root) / name
            try:
                st = p.stat()  # follow symlinks: HF cache snapshots point at blobs/
            except OSError:
                continue
            key = (st.st_dev, st.st_ino)
            if key in seen:
                continue
            seen.add(key)
            total += st.st_size
    return total


def _top_level_sizes(target: Path) -> list[PackageSize]:
    """Size per top-level entry in the --target tree, largest first.

    Groups `foo/` and `foo-1.2.3.dist-info/` together so a package's real
    footprint reads as one line instead of two.
    """
    sizes: dict[str, int] = {}
    for entry in target.iterdir():
        name = entry.name
        if name.endswith(".dist-info"):
            name = name.rsplit("-", 2)[0]
        elif name.endswith(".libs"):
            name = name[: -len(".libs")]
        size = _tree_bytes(entry) if entry.is_dir() else entry.stat().st_size
        sizes[name] = sizes.get(name, 0) + size
    return sorted(
        (PackageSize(n, b) for n, b in sizes.items()),
        key=lambda p: p.bytes,
        reverse=True,
    )


def resolve_closure(
    requirements: list[str],
    target: Path,
    *,
    platform: str,
    torch_cpu: bool,
    find_links: str | None = None,
) -> ProfileMeasurement:
    """`uv pip install --target` for a foreign platform. Resolution + download only."""
    profile = target.name
    m = ProfileMeasurement(profile=profile, platform=platform)
    cmd = [
        "uv", "pip", "install",
        "--target", str(target),
        "--python-platform", platform,
        "--python-version", PYTHON_VERSION,
        # Required for a cross-platform target: uv cannot build an sdist for a
        # platform it isn't running on, and a wheel-only closure is exactly what
        # the bundle ships anyway.
        "--only-binary=:all:",
        "--link-mode=copy",
    ]
    if torch_cpu:
        cmd += ["--extra-index-url", TORCH_CPU_INDEX, "--index-strategy", "unsafe-best-match"]
    if find_links:
        cmd += ["--find-links", find_links]
    cmd += requirements

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        m.error = (proc.stderr or proc.stdout).strip()[-4000:]
        return m

    # uv prints "+ name==version" per installed package on the final lines.
    m.resolved = sorted(
        line.strip()[2:]
        for line in (proc.stderr + proc.stdout).splitlines()
        if line.strip().startswith("+ ")
    )
    m.package_count = len(m.resolved)
    m.packages = _top_level_sizes(target)
    m.total_bytes = sum(p.bytes for p in m.packages)
    return m


def _find_model_repo(repo: str) -> Path | None:
    """Locate an HF-layout model dir across the caches this project actually uses.

    fastembed defaults to a `fastembed_cache` dir under the system temp dir, NOT
    ~/.cache/huggingface — so looking in one place reports a false "not present".
    """
    roots = [
        Path(os.environ.get("FASTEMBED_CACHE_PATH", "")) if os.environ.get("FASTEMBED_CACHE_PATH") else None,
        Path(tempfile.gettempdir()) / "fastembed_cache",
        Path.home() / ".cache" / "fastembed",
        Path.home() / ".cache" / "huggingface" / "hub",
    ]
    for root in roots:
        if root and (root / repo).exists():
            return root / repo
    return None


def measure_static() -> dict[str, int | None]:
    """Model weights, the embeddable runtime, and the built SPA."""
    out: dict[str, int | None] = {}
    hub = Path.home() / ".cache" / "huggingface" / "hub"

    for label, repo in FASTEMBED_MODELS.items():
        p = _find_model_repo(repo)
        out[label] = _tree_bytes(p) if p else None

    p = hub / MINERU_MODEL_REPO
    out["MinerU pipeline models (PDF-Extract-Kit-1.0)"] = (
        _tree_bytes(p) if p.exists() else None
    )

    dist = REPO_ROOT / "webapp" / "dist"
    out["webapp/dist (built SPA)"] = _tree_bytes(dist) if dist.exists() else None

    out["python 3.12 embeddable (amd64, unzipped)"] = _embeddable_bytes()
    return out


def _embeddable_bytes() -> int | None:
    """Download python.org's embeddable zip and measure it unzipped.

    Measured rather than estimated because it is the one component whose size
    is a hard floor for every profile — the client bundle can't drop it.
    """
    import urllib.request
    import zipfile

    try:
        with tempfile.TemporaryDirectory() as td:
            zpath = Path(td) / "embed.zip"
            urllib.request.urlretrieve(EMBEDDABLE_URL, zpath)
            unz = Path(td) / "unz"
            with zipfile.ZipFile(zpath) as zf:
                zf.extractall(unz)
            return _tree_bytes(unz)
    except Exception:  # offline, or python.org moved the file
        return None


def render(measurements: list[ProfileMeasurement], static: dict[str, int | None]) -> str:
    lines: list[str] = []
    for m in measurements:
        lines.append(f"\n=== profile: {m.profile}  ({m.platform}, py{PYTHON_VERSION}) ===")
        if m.error:
            lines.append(f"  RESOLUTION FAILED:\n{m.error}")
            continue
        lines.append(f"  site-packages total : {_human(m.total_bytes)}  ({m.package_count} packages)")
        lines.append("  top 20 by size:")
        for p in m.packages[:20]:
            lines.append(f"    {_human(p.bytes):>10}  {p.name}")

    lines.append("\n=== static components (measured locally) ===")
    for label, size in static.items():
        lines.append(f"    {_human(size):>10}  {label}")

    lines.append("\n=== bundle totals ===")
    static_common = sum(
        v or 0
        for k, v in static.items()
        if "MinerU" not in k
    )
    mineru_models = static.get("MinerU pipeline models (PDF-Extract-Kit-1.0)") or 0
    for m in measurements:
        if m.error:
            continue
        extra = mineru_models if m.profile != "client" else 0
        total = m.total_bytes + static_common + extra
        lines.append(f"    {_human(total):>10}  {m.profile} bundle (unzipped, on disk)")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--profile", choices=["client", "ingest", "both"], default="both")
    ap.add_argument("--platform", default=WINDOWS_PLATFORM)
    ap.add_argument("--workdir", default=None, help="where to resolve (default: a temp dir)")
    ap.add_argument("--keep", action="store_true", help="keep the resolved trees")
    ap.add_argument("--json", dest="json_out", default=None)
    ap.add_argument(
        "--torch-pypi",
        action="store_true",
        help="resolve torch from PyPI (the CUDA Windows wheel) instead of the CPU index",
    )
    ap.add_argument(
        "--find-links",
        default=None,
        help="local wheel dir — needed to resolve mineru 3.1.6 (see the antlr4 note above)",
    )
    ap.add_argument("--skip-static", action="store_true")
    args = ap.parse_args()

    if shutil.which("uv") is None:
        print("uv not found on PATH — this script drives `uv pip install`.", file=sys.stderr)
        return 2

    work = Path(args.workdir) if args.workdir else Path(tempfile.mkdtemp(prefix="jlbc-measure-"))
    work.mkdir(parents=True, exist_ok=True)
    print(f"resolving into {work}", file=sys.stderr)

    profiles: list[tuple[str, list[str]]] = []
    if args.profile in ("client", "both"):
        profiles.append(("client", CLIENT_REQUIREMENTS))
    if args.profile in ("ingest", "both"):
        profiles.append(("ingest", CLIENT_REQUIREMENTS + INGEST_ONLY_REQUIREMENTS))

    measurements = []
    for name, reqs in profiles:
        target = work / name
        if target.exists():
            shutil.rmtree(target)
        print(f"  resolving {name} ({len(reqs)} direct requirements)…", file=sys.stderr)
        measurements.append(
            resolve_closure(
                reqs,
                target,
                platform=args.platform,
                torch_cpu=not args.torch_pypi,
                find_links=args.find_links,
            )
        )

    static = {} if args.skip_static else measure_static()
    report = render(measurements, static)
    print(report)

    if args.json_out:
        payload = {
            "platform": args.platform,
            "python_version": PYTHON_VERSION,
            "torch_source": "pypi" if args.torch_pypi else "download.pytorch.org/whl/cpu",
            "profiles": [
                {
                    "profile": m.profile,
                    "error": m.error,
                    "total_bytes": m.total_bytes,
                    "package_count": m.package_count,
                    "packages": [{"name": p.name, "bytes": p.bytes} for p in m.packages],
                    "resolved": m.resolved,
                }
                for m in measurements
            ],
            "static": static,
        }
        Path(args.json_out).write_text(json.dumps(payload, indent=2))
        print(f"\nwrote {args.json_out}", file=sys.stderr)

    if not args.keep and args.workdir is None:
        shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
