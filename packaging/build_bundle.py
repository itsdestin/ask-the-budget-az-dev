"""Build the distributable Windows bundle (Plan 5, Task 15 — spec S7).

Produces `dist/JLBC-Search-<version>.zip`. `Install-JLBC-Search.cmd` on
the USB does the entire install: no admin rights, no Python on the machine,
no PATH edits, no registry writes, and — the property that matters — **no
downloads on first run**.

Runs on Linux or Windows. Every Windows-specific artefact (the embeddable
runtime, the wheel closure, the Java runtime) is downloaded rather than built,
so the Z13 can produce the office bundle. Building it is not the same as
proving it works: see `docs/superpowers/investigations/2026-08-01-bundle-size.md`
for what is measured versus inferred, and Task 15's acceptance criterion —
the server starting with the network cable unplugged, on a machine that has
never had Python.

Layout produced (paths matter — the app resolves data files relative to its
own source tree, so this mirrors the repo root):

    JLBC-Search-<version>/
      python/            embeddable CPython, ._pth patched to see site-packages
      site-packages/     the Windows wheel closure
      jre/               Temurin JRE — opendataloader-pdf shells out to java
      app/ harness/ store/ ingest/ chunking/ retrieval/ scripts/
      samples/ data/     committed reference data (NOT the corpus)
      webapp/dist/       the built SPA
      models/
        fastembed/       the two ONNX models, HF cache layout, symlinks resolved
        mineru/          PDF-Extract-Kit-1.0 weights
        mineru.json      points models-dir.pipeline at ./mineru
        tiktoken/        pre-seeded cl100k_base
      launcher.pyw  QUICKSTART.md  VERSION  MANIFEST.json

Usage:
    python packaging/build_bundle.py --version 1.0.0
    python packaging/build_bundle.py --version 1.0.0 --skip-zip     # faster iteration
    python packaging/build_bundle.py --plan                         # print, build nothing
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

PYTHON_VERSION = "3.12"
EMBEDDABLE_URL = "https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip"
WINDOWS_PLATFORM = "x86_64-pc-windows-msvc"

# Temurin publishes a standalone Windows JRE as a plain zip — no installer, no
# admin rights, no registry. GPLv2 **with the Classpath Exception**, which is
# the grant that permits redistributing it inside another application.
# Measured 2026-08-01: 47 MB compressed, 146 MB unpacked.
JRE_URL = (
    "https://github.com/adoptium/temurin21-binaries/releases/download/"
    "jdk-21.0.12%2B8/OpenJDK21U-jre_x64_windows_hotspot_21.0.12_8.zip"
)

# tiktoken fetches this on first use unless the cache is pre-seeded, and
# `chunking/builders/_tokens.py` swallows the failure and falls back to a
# 4-chars-per-token heuristic — so an unseeded offline machine chunks on
# different boundaries than the existing corpus, silently. Cache key is
# sha1(url), not a filename (tiktoken/load.py:51).
TIKTOKEN_URL = "https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken"

# ---------------------------------------------------------------------------
# Requirements. Kept in sync with packaging/measure.py — see that file for the
# import-to-distribution derivation and for why mineru is pinned rather than floored.
# ---------------------------------------------------------------------------
REQUIREMENTS = [
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
    "tiktoken",
    # Ingest. Shipped on every machine (decided 2026-08-01: one bundle
    # everywhere; whether a machine actually drains the queue is a setting).
    "mineru[pipeline]==3.1.6",
    "opendataloader-pdf>=2.4.1",
]

# Packages with no wheel on PyPI, pre-built here into a local wheel dir.
# antlr4-python3-runtime 4.9.x is sdist-only and is reached via
# mineru 3.1.6 -> omegaconf -> antlr4. It is pure Python, so a wheel built on
# any machine is a valid `py3-none-any` wheel for Windows.
#
# WHY not simply drop `--only-binary=:all:` and let uv build it: uv will then
# happily build *any* sdist it meets, and a non-pure one would compile a Linux
# binary straight into the Windows tree — a bundle that builds clean and fails
# at import on the target. Naming the exception keeps the failure loud: a new
# sdist-only dependency stops the build with its own name in the error.
PREBUILT_SDISTS = ["antlr4-python3-runtime==4.9.3"]

# ---------------------------------------------------------------------------
# Source selection
# ---------------------------------------------------------------------------
# The file list comes from `git ls-files`, NOT a directory walk. That is a
# structural guarantee rather than a hopeful denylist: anything gitignored —
# `.env`, `.env.local`, `data/insight-data/` (the corpus), `samples/raw-pdfs/`,
# `.venv/`, `__pycache__/` — cannot reach the bundle even if someone adds a new
# secret file later. Invariant 8 (no corpus content in the distributable) then
# holds by construction instead of by vigilance.
#
# On top of that, these trees are tracked but must not ship.
EXCLUDED_PREFIXES = (
    "docs/",                    # specs, plans, investigations — not runtime
    "tests/",                   # dev only
    "eval/",                    # dev only
    "primer/",                  # authoring tooling for the reference primer
    "funds/",                   # Phase 0 working notes
    "webapp/src/",              # source; only webapp/dist ships
    "webapp/reference/",
    "webapp/public/",
    "samples/phase-0-archive/", # scoring screenshots, ~10 MB of PNGs
    "samples/extractor-output/",
    "data/chunks/",             # Phase 1a hand-off manifest, not runtime
    "data/jlbc-book-sources/",  # crawl working files
    ".github/",
    "packaging/",               # the builder does not ship inside its own output
    "mockups/",                 # HTML mockups — design record, not runtime
)
EXCLUDED_SUFFIXES = (".pyc",)
EXCLUDED_NAMES = (
    "PROMPT-plan1-storage-retrieval.md", "PROMPT-plan2-app-shell.md",
    "PROMPT-plan3-ingest.md", "PROMPT-plan4-ai-mode.md",
    "PROMPT-plan5-session-a.md", "PROMPT-plan5-session-b.md",
    "PROMPT-plan5-session-c.md", "PROMPT-volume-ingest.md",
    "PROMPT-z13-backfill.md", "PROMPT-parallel-write-plan5.md",
    "PROMPT-parallel-ingest-defects.md", "PROMPT-parallel-ai-hardening.md",
    "uv.lock", "pyproject.toml", "setup.sh", "STATUS.md",
    # Retired Postgres-era modules that still `import db.connection`. Nothing
    # live imports them (`retrieval/__init__.py` stopped re-exporting them), but
    # shipping a module that raises ModuleNotFoundError the moment anyone touches
    # it is a trap for whoever inherits this. Task 18 deletes them from the repo,
    # at which point these entries become harmless no-ops.
    # Caught by test_every_first_party_import_resolves.
    "retrieval/bm25.py", "retrieval/dense.py", "retrieval/rerank.py",
    "retrieval/api.py",
    "scripts/embed_corpus.py", "scripts/load_slice.py",
    "scripts/redownload_cached_pdfs.py",
    # Dev-only query verifier against the live corpus: imports eval/ (dev-only
    # tree, excluded above), so it must not ship to the office bundle. Same
    # exclusion pattern as the other dev-only scripts.
    # Caught by test_every_first_party_import_resolves.
    "scripts/verify_agent_query.py",
)

# Files re-admitted despite an EXCLUDED_PREFIXES hit. Each one is READ AT
# RUNTIME by shipped code — check with `grep -rn "<name>" app store harness`
# before removing an entry. Pinned by tests/test_packaging_manifest.py.
INCLUDED_FILES = (
    # app/search_provider.py::MOCKUP_INDEX_PATH — the vendored site index that
    # supplies the Budget Documents meta line and the exact-URL join. Missing
    # from 0.9.1: every row rendered as a humanised doc_id with no Open link.
    "webapp/reference/assets/search/index-lite.js",
)

# Entries the launcher cannot start without. Asserted by
# tests/test_packaging_manifest.py against a built manifest, and by
# validate_manifest() below during the build itself.
REQUIRED_ENTRIES = (
    "python/python.exe",
    "python/pythonw.exe",
    "site-packages/fastapi/__init__.py",
    "site-packages/uvicorn/__init__.py",
    "site-packages/lancedb/__init__.py",
    "site-packages/fastembed/__init__.py",
    "jre/bin/java.exe",
    "app/main.py",
    "harness/system-prompt.md",
    "webapp/dist/index.html",
    "models/fastembed/models--Snowflake--snowflake-arctic-embed-m",
    "models/fastembed/models--Xenova--ms-marco-MiniLM-L-12-v2",
    "models/mineru.json",
    "models/tiktoken",
    "launcher.pyw",
    "QUICKSTART.md",
    "VERSION",
)

# Things whose presence in the manifest is a shipping bug. Each is a substring
# match against the bundle-relative POSIX path.
#
# `settings.json` carries the OpenRouter key; `data/insight-data/` is the corpus
# (Invariant 8: the distributable never contains corpus content); `.pdf` covers
# any source document that slipped in. `.git` and `.env` are already impossible
# via git ls-files — asserted anyway, because the day someone "simplifies" the
# file list into an os.walk is the day that stops being true.
FORBIDDEN_SUBSTRINGS = (
    ".env",
    ".git/",
    ".gitignore",
    "settings.json",
    "data/insight-data/",
    "/.venv/",
    "__pycache__",
    ".pdf",
    "node_modules/",
    "site-packages/bin/",   # POSIX console scripts with the dev venv's shebang
    "mockups/",
)

# Root-level handoff prompts, matched by prefix: the by-name list rotted
# (seven newer PROMPT-*.md files were shipping on 0.9.1).
FORBIDDEN_ROOT_PREFIXES = ("PROMPT-",)


def validate_manifest(paths: list[str]) -> list[str]:
    """Return a list of problems with a bundle file list. Empty means good.

    Pure function over relative POSIX paths so the test suite can exercise it
    on Linux without building a 3.3 GB bundle.
    """
    problems: list[str] = []
    normalised = [p.replace("\\", "/") for p in paths]
    as_set = set(normalised)

    for required in REQUIRED_ENTRIES:
        # A directory requirement is satisfied by any file beneath it.
        if required in as_set:
            continue
        if any(p.startswith(required.rstrip("/") + "/") for p in normalised):
            continue
        problems.append(f"missing required entry: {required}")

    for p in normalised:
        for bad in FORBIDDEN_SUBSTRINGS:
            if bad in p:
                problems.append(f"forbidden content in bundle: {p} (matched {bad!r})")
        if "/" not in p and p.startswith(FORBIDDEN_ROOT_PREFIXES):
            problems.append(f"forbidden content in bundle: {p} (root handoff prompt)")
    return problems


def source_files(repo_root: Path = REPO_ROOT) -> list[str]:
    """Repo-relative paths of the application source that ships.

    `git ls-files` is the source of truth — see EXCLUDED_PREFIXES for why.
    """
    out = subprocess.run(
        ["git", "ls-files"], cwd=repo_root, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    keep = []
    for rel in out:
        if rel.startswith(EXCLUDED_PREFIXES) and rel not in INCLUDED_FILES:
            continue
        if rel.endswith(EXCLUDED_SUFFIXES):
            continue
        if rel in EXCLUDED_NAMES:
            continue
        if "/" not in rel and rel.startswith(FORBIDDEN_ROOT_PREFIXES):
            continue
        # Dotfiles are dev metadata, never runtime. Caught by
        # tests/test_packaging_manifest.py: `.gitignore` is tracked and was
        # shipping, and `db/.env.example` would have put a file named like a
        # secrets file inside a bundle people email around.
        if any(part.startswith(".") for part in rel.split("/")):
            continue
        keep.append(rel)
    return sorted(keep)


# ---------------------------------------------------------------------------
# Build steps
# ---------------------------------------------------------------------------

def _log(msg: str) -> None:
    print(f"  {msg}", flush=True)


def _download(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        _log(f"cached  {dest.name}")
        return dest
    _log(f"fetch   {url.rsplit('/', 1)[-1]}")
    urllib.request.urlretrieve(url, dest)
    return dest


def _copy_resolving_symlinks(src: Path, dst: Path) -> None:
    """Copy a tree, materialising symlinks as real files.

    The HuggingFace cache stores one blob and symlinks each snapshot file at
    it. Windows will not create those symlinks without Developer Mode or admin
    rights — exactly what S7 rules out — so the bundle carries real files and
    pays the duplication. (It does not, in fact, pay it: only the snapshot side
    is copied, so the bytes land once.)
    """
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.rglob("*"):
        rel = item.relative_to(src)
        target = dst / rel
        if item.is_dir() and not item.is_symlink():
            target.mkdir(parents=True, exist_ok=True)
        elif item.is_symlink() or item.is_file():
            resolved = item.resolve()
            if not resolved.is_file():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(resolved, target)


def step_python(out: Path, cache: Path) -> None:
    """Embeddable CPython, with the one edit that makes it usable."""
    zpath = _download(EMBEDDABLE_URL, cache / "python-embed.zip")
    target = out / "python"
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zpath) as zf:
        zf.extractall(target)

    # The shipped `python312._pth` is two lines and has `import site` commented
    # out, so the interpreter cannot see a site-packages directory at all.
    # Without this edit the bundle builds perfectly and then fails on the first
    # `import fastapi`. This is the single most likely cause of a
    # builds-but-does-not-start bundle.
    pth = next(target.glob("python3*._pth"))
    pth.write_text(
        "python312.zip\n"
        ".\n"
        "../site-packages\n"
        "..\n"          # the bundle root, so `import app`, `import harness` resolve
        "import site\n"
    )
    _log(f"python  {pth.name} patched to see ../site-packages and the bundle root")


def step_wheels(out: Path, cache: Path) -> None:
    """The Windows wheel closure, plus the one sdist-only package pre-built."""
    wheels = cache / "prebuilt-wheels"
    wheels.mkdir(parents=True, exist_ok=True)
    if not any(wheels.glob("*.whl")):
        _log("prebuild sdist-only packages (pure-python -> py3-none-any)")
        with tempfile.TemporaryDirectory() as td:
            venv = Path(td) / "v"
            subprocess.run(["uv", "venv", "--python", PYTHON_VERSION, str(venv)],
                           check=True, capture_output=True)
            py = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            subprocess.run([str(py), "-m", "ensurepip"], check=True, capture_output=True)
            subprocess.run(
                [str(py), "-m", "pip", "wheel", "--no-deps", "-w", str(wheels),
                 *PREBUILT_SDISTS],
                check=True, capture_output=True,
            )
    for w in wheels.glob("*.whl"):
        if not w.name.endswith("-py3-none-any.whl") and "-none-any" not in w.name:
            raise SystemExit(
                f"pre-built wheel {w.name} is not platform-independent — it would "
                f"put a non-Windows binary in the bundle. Build it on Windows instead."
            )

    target = out / "site-packages"
    _log(f"wheels  resolving {len(REQUIREMENTS)} requirements for {WINDOWS_PLATFORM}")
    subprocess.run(
        ["uv", "pip", "install", "--target", str(target),
         "--python-platform", WINDOWS_PLATFORM, "--python-version", PYTHON_VERSION,
         "--only-binary=:all:", "--link-mode=copy",
         "--find-links", str(wheels), *REQUIREMENTS],
        check=True,
    )
    # uv lays console scripts into site-packages/bin/ with the BUILD machine's
    # venv shebang (`#!/home/destin/.../.venv/bin/python3`). They cannot run
    # on Windows and the bundle's own mineru rung is `-m mineru.cli.client`
    # (ingest/mineru_runner.py), so nothing needs them.
    shutil.rmtree(target / "bin", ignore_errors=True)


def step_jre(out: Path, cache: Path) -> None:
    """Temurin JRE — opendataloader-pdf shells out to `java` (runner.py:24)."""
    zpath = _download(JRE_URL, cache / "temurin-jre.zip")
    with tempfile.TemporaryDirectory() as td:
        with zipfile.ZipFile(zpath) as zf:
            zf.extractall(td)
        # The archive has a single versioned top-level dir; flatten it so the
        # launcher's PATH entry is a stable `jre/bin` across JRE upgrades.
        inner = next(Path(td).iterdir())
        shutil.copytree(inner, out / "jre", dirs_exist_ok=True)
    _log("jre     Temurin flattened to jre/")


def step_source(out: Path) -> list[str]:
    files = source_files()
    for rel in files:
        src = REPO_ROOT / rel
        if not src.is_file():
            continue
        dst = out / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    _log(f"source  {len(files)} tracked files")
    return files


def step_webapp(out: Path) -> None:
    dist = REPO_ROOT / "webapp" / "dist"
    if not (dist / "index.html").exists():
        raise SystemExit(
            "webapp/dist/index.html is missing — run `cd webapp && npm ci && npm run build` "
            "first. Refusing to ship a bundle whose UI is an empty directory."
        )
    shutil.copytree(dist, out / "webapp" / "dist", dirs_exist_ok=True)
    _log("webapp  dist copied")


def _find_model_repo(repo: str) -> Path | None:
    roots = [
        Path(os.environ["FASTEMBED_CACHE_PATH"]) if os.environ.get("FASTEMBED_CACHE_PATH") else None,
        Path(tempfile.gettempdir()) / "fastembed_cache",
        Path.home() / ".cache" / "fastembed",
        Path.home() / ".cache" / "huggingface" / "hub",
    ]
    for root in roots:
        if root and (root / repo).exists():
            return root / repo
    return None


def step_models(out: Path, cache: Path) -> None:
    """Pre-bundle every model weight. This is what makes first run offline (S7)."""
    fe_dir = out / "models" / "fastembed"
    for repo in ("models--Snowflake--snowflake-arctic-embed-m",
                 "models--Xenova--ms-marco-MiniLM-L-12-v2"):
        src = _find_model_repo(repo)
        if src is None:
            raise SystemExit(
                f"{repo} is not in any local cache. Run the app once (or the eval) "
                f"to populate it, then rebuild — the builder deliberately does not "
                f"download model weights it cannot verify."
            )
        # Only the snapshots/ side: it is the complete file set, and copying
        # blobs/ too would double 0.53 GB for nothing.
        for snap in (src / "snapshots").iterdir():
            _copy_resolving_symlinks(snap, fe_dir / src.name / "snapshots" / snap.name)
        for meta in src.glob("*.json"):
            shutil.copy2(meta, fe_dir / src.name / meta.name)
        for refs in (src / "refs",):
            if refs.exists():
                _copy_resolving_symlinks(refs, fe_dir / src.name / "refs")
    _log("models  fastembed ONNX models copied (symlinks resolved for Windows)")

    mineru_src = Path.home() / ".cache" / "huggingface" / "hub" / "models--opendatalab--PDF-Extract-Kit-1.0"
    if not mineru_src.exists():
        raise SystemExit(f"MinerU pipeline weights not found at {mineru_src}")
    snap = next((mineru_src / "snapshots").iterdir())
    _copy_resolving_symlinks(snap, out / "models" / "mineru")
    # MinerU reads models-dir.pipeline out of this file; the launcher points
    # MINERU_TOOLS_CONFIG_JSON at it as an absolute path
    # (mineru/utils/config_reader.py:17-22). The path is rewritten at install
    # time by Install-JLBC-Search.cmd (install.cmd deleted 2026-08-25, spec S1),
    # because it must be absolute and the install location is not known at
    # build time.
    (out / "models" / "mineru.json").write_text(json.dumps({
        "models-dir": {"pipeline": "__INSTALL_DIR__/models/mineru", "vlm": ""},
        "model-source": "local",
        "config_version": "1.3.2",
    }, indent=2))
    _log("models  MinerU pipeline weights copied")

    tk = out / "models" / "tiktoken"
    tk.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(TIKTOKEN_URL.encode()).hexdigest()
    blob = _download(TIKTOKEN_URL, cache / "cl100k_base.tiktoken")
    shutil.copy2(blob, tk / key)
    _log(f"models  tiktoken cl100k_base seeded as {key}")


def step_launcher(out: Path, version: str) -> None:
    here = Path(__file__).resolve().parent
    # install.cmd (the unzip-it-yourself path) was deleted 2026-08-25 (spec S1):
    # the one-click Install-JLBC-Search.cmd on the USB is the only installer.
    shutil.copy2(here / "launcher.pyw", out / "launcher.pyw")
    quickstart = REPO_ROOT / "docs" / "QUICKSTART.md"
    if quickstart.exists():
        shutil.copy2(quickstart, out / "QUICKSTART.md")
    else:
        (out / "QUICKSTART.md").write_text("# JLBC Search — Quick Start\n\n(not yet written)\n")
    (out / "VERSION").write_text(version + "\n")


def step_manifest(out: Path, version: str) -> list[str]:
    entries = []
    for p in sorted(out.rglob("*")):
        if p.is_file():
            entries.append(p.relative_to(out).as_posix())
    problems = validate_manifest(entries)
    if problems:
        for prob in problems[:20]:
            print(f"  MANIFEST PROBLEM: {prob}", file=sys.stderr)
        raise SystemExit(f"{len(problems)} manifest problem(s) — refusing to ship")
    total = sum((out / e).stat().st_size for e in entries)
    (out / "MANIFEST.json").write_text(json.dumps({
        "version": version,
        "file_count": len(entries),
        "total_bytes": total,
        "files": entries,
    }, indent=1))
    _log(f"manifest {len(entries)} files, {total / 1024**3:.2f} GB unzipped")
    return entries


def step_zip(out: Path, version: str) -> Path:
    dist = REPO_ROOT / "dist"
    dist.mkdir(exist_ok=True)
    zpath = dist / f"JLBC-Search-{version}.zip"
    root_name = out.name
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for p in sorted(out.rglob("*")):
            if p.is_file():
                zf.write(p, f"{root_name}/{p.relative_to(out).as_posix()}")
    _log(f"zip     {zpath} ({zpath.stat().st_size / 1024**3:.2f} GB)")

    # The one-click installer sits NEXT TO the zip on the USB and is the file
    # that flashed-and-closed on 2026-08-18. Copying it here means the USB is
    # assembled from one place, and the CRLF guard covers the copy.
    installer = Path(__file__).resolve().parent / "Install-JLBC-Search.cmd"
    shutil.copy2(installer, dist / installer.name)
    if b"\r\n" not in (dist / installer.name).read_bytes():
        raise SystemExit(f"{installer.name} is not CRLF — see tests/test_cmd_line_endings.py")
    _log(f"copied  {installer.name} beside the zip")
    return zpath


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--version", default="0.0.0-dev")
    ap.add_argument("--out", default=None, help="build directory (default: build/)")
    ap.add_argument("--cache", default=None, help="download cache (default: build/.cache)")
    ap.add_argument("--skip-zip", action="store_true")
    ap.add_argument("--plan", action="store_true", help="print the plan and exit")
    args = ap.parse_args()

    build_root = Path(args.out) if args.out else REPO_ROOT / "build"
    cache = Path(args.cache) if args.cache else build_root / ".cache"
    out = build_root / f"JLBC-Search-{args.version}"

    if args.plan:
        files = source_files()
        print(f"version      {args.version}")
        print(f"output       {out}")
        print(f"source files {len(files)} (from git ls-files, minus {len(EXCLUDED_PREFIXES)} trees)")
        print(f"requirements {len(REQUIREMENTS)} direct, resolved for {WINDOWS_PLATFORM}")
        print(f"prebuilt     {', '.join(PREBUILT_SDISTS)}")
        print(f"required     {len(REQUIRED_ENTRIES)} manifest entries asserted")
        return 0

    if shutil.which("uv") is None:
        print("uv not found on PATH", file=sys.stderr)
        return 2

    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    cache.mkdir(parents=True, exist_ok=True)

    print(f"building JLBC-Search-{args.version} -> {out}")
    step_python(out, cache)
    step_wheels(out, cache)
    step_jre(out, cache)
    step_source(out)
    step_webapp(out)
    step_models(out, cache)
    step_launcher(out, args.version)
    step_manifest(out, args.version)
    if not args.skip_zip:
        step_zip(out, args.version)
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
