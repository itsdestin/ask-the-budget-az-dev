"""The bundle ships what the launcher needs and nothing it must never carry.

Plan 5 Task 15, Step 1. These run on Linux in milliseconds and build nothing —
that is the point. A 3.3 GB bundle takes a long while to produce, and the two
failures worth catching (a shipped API key, a shipped corpus) are both silent:
nobody notices a leaked `settings.json` until it is in a screenshot, and nobody
notices corpus content in the zip until Invariant 8 has already been broken.

The unit under test is `validate_manifest()` — a pure function over a list of
bundle-relative paths — plus `source_files()`, which is checked against the
real repository.
"""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# Loaded by path, NOT as `from packaging.build_bundle import ...`.
#
# `packaging` is also a real PyPI distribution — a transitive dependency of
# half the closure — and the repo has a top-level `packaging/` directory.
# Python resolves the name to the installed regular package rather than to our
# directory (a namespace-package portion loses to a regular package found
# anywhere on sys.path), so the dotted import would silently pick up the wrong
# `packaging` and fail. Loading by file path sidesteps the ambiguity entirely.
#
# The corollary is a live invariant, pinned by
# test_packaging_dir_must_not_become_a_real_package below: **never add
# `packaging/__init__.py`**. That would turn the directory into a regular
# package, which WOULD win the name, and every library that does
# `from packaging.version import Version` would break at import.
_spec = importlib.util.spec_from_file_location(
    "_jlbc_build_bundle", REPO_ROOT / "packaging" / "build_bundle.py"
)
build_bundle = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_bundle)

EXCLUDED_PREFIXES = build_bundle.EXCLUDED_PREFIXES
REQUIRED_ENTRIES = build_bundle.REQUIRED_ENTRIES
source_files = build_bundle.source_files
validate_manifest = build_bundle.validate_manifest


def test_packaging_dir_must_not_become_a_real_package():
    """Adding packaging/__init__.py would shadow the `packaging` PyPI library.

    Failure mode if this ever regresses: `from packaging.version import Version`
    starts raising ModuleNotFoundError across the whole dependency tree, and the
    traceback points at someone else's library rather than at the directory that
    caused it.
    """
    assert not (REPO_ROOT / "packaging" / "__init__.py").exists()


def _complete_manifest() -> list[str]:
    """A minimal file list that should validate clean."""
    out = []
    for entry in REQUIRED_ENTRIES:
        # Directory requirements are satisfied by a file beneath them.
        if entry.endswith((".exe", ".py", ".md", ".html", ".json", ".pyw", ".cmd")) or entry == "VERSION":
            out.append(entry)
        else:
            out.append(f"{entry}/some-file.onnx")
    return out


# ---------------------------------------------------------------------------
# Required entries
# ---------------------------------------------------------------------------
def test_a_complete_manifest_validates_clean():
    assert validate_manifest(_complete_manifest()) == []


@pytest.mark.parametrize("dropped", REQUIRED_ENTRIES)
def test_every_required_entry_is_actually_required(dropped):
    """Parametrized over the table so adding a requirement adds a test.

    WHY each of these matters is worth one line: without python.exe there is no
    interpreter, without jre/bin/java.exe the AFR extractor dies at the moment
    somebody uploads the annual financial report, and without the fastembed
    model directories the app starts and then cannot answer a single query.
    """
    manifest = [p for p in _complete_manifest() if not p.startswith(dropped)]
    problems = validate_manifest(manifest)
    assert any(dropped in p for p in problems), f"dropping {dropped} was not caught"


def test_a_directory_requirement_is_met_by_a_file_beneath_it():
    manifest = _complete_manifest()
    assert "models/tiktoken/deadbeef" not in manifest
    manifest = [p for p in manifest if not p.startswith("models/tiktoken")]
    manifest.append("models/tiktoken/9b5ad71b2ce5302211f9c61530b329a4922fc6a4")
    assert validate_manifest(manifest) == []


# ---------------------------------------------------------------------------
# Forbidden content — the two silent failures
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "smuggled",
    [
        # The OpenRouter key lives in settings.json. Shipping it hands every
        # machine in the office an admin's credentials, and the bundle is a
        # file people email around.
        "data/settings.json",
        "settings.json",
        # Invariant 8: the distributable never contains corpus content.
        "data/insight-data/lancedb/budget_chunks.lance/data.lance",
        "data/insight-data/documents.json",
        "samples/raw-pdfs/jlbc-approps-fy26.pdf",
        "app/static/some-report.pdf",
        # Impossible via git ls-files today. Asserted anyway, because the day
        # someone rewrites the file list as an os.walk is the day it stops
        # being impossible.
        ".env",
        "webapp/.env.local",
        ".git/config",
        ".gitignore",
        "site-packages/.venv/pyvenv.cfg",
        "app/__pycache__/main.cpython-312.pyc",
        "webapp/node_modules/react/index.js",
    ],
)
def test_forbidden_content_is_rejected(smuggled):
    problems = validate_manifest(_complete_manifest() + [smuggled])
    assert any(smuggled in p for p in problems), f"{smuggled} was not caught"


def test_windows_path_separators_do_not_evade_the_check():
    """A manifest built on Windows uses backslashes; the rules must still bite."""
    problems = validate_manifest(
        _complete_manifest() + [r"data\insight-data\documents.json"]
    )
    assert problems, "backslash-separated corpus path slipped through"


# ---------------------------------------------------------------------------
# The real repository
# ---------------------------------------------------------------------------
def test_source_files_ships_the_live_application():
    files = set(source_files())
    for needed in (
        "app/main.py",
        "harness/system-prompt.md",
        "harness/settings.py",
        "store/config.py",
        "ingest/dispatcher.py",
        "chunking/builder.py",
        "retrieval/pipeline.py",
        "scripts/run_mineru.py",
        "samples/entity-catalog.yaml",
        "samples/agency-slug-aliases.yaml",
        "data/fund-catalog.yaml",
        "app/data/fiscal-notes-snapshot.json",
    ):
        assert needed in files, f"{needed} is loaded at runtime but would not ship"


def test_source_files_excludes_the_retired_and_dev_only_trees():
    files = source_files()
    for rel in files:
        assert not rel.startswith(EXCLUDED_PREFIXES), f"{rel} should not ship"


def test_source_files_is_a_subset_of_what_git_tracks():
    """The structural guarantee: nothing untracked can reach the bundle.

    This is what makes "no secrets, no corpus" hold by construction rather than
    by remembering to add each new secret to a denylist.
    """
    tracked = set(
        subprocess.run(
            ["git", "ls-files"], capture_output=True, text=True, check=True
        ).stdout.splitlines()
    )
    assert set(source_files()) <= tracked


def test_the_real_source_list_has_no_forbidden_content():
    """End-to-end over the actual repo, not a synthetic list."""
    assert validate_manifest(_complete_manifest() + source_files()) == []


FIRST_PARTY = {"app", "harness", "store", "ingest", "chunking", "retrieval",
               "scripts", "eval", "db", "web"}


def test_every_first_party_import_resolves():
    """No shipped module may import a module the bundle does not contain.

    The office machine has no repo to fall back on and no pip to fix it with, so
    a module that raises ModuleNotFoundError on the target is a dead end for
    whoever hits it. This caught seven retired Postgres-era files
    (retrieval/bm25.py and friends, still importing `db.connection`) that would
    otherwise have shipped as booby-trapped dead code.

    Runs against the shipping file list, so it needs no built bundle.
    """
    import ast

    shipped = set(source_files())
    problems: list[str] = []
    for rel in sorted(shipped):
        if not rel.endswith(".py"):
            continue
        try:
            tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:  # pragma: no cover — would be a broken checkout
            continue
        modules: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules.append(node.module)
        for mod in modules:
            if mod.split(".")[0] not in FIRST_PARTY:
                continue
            base = mod.replace(".", "/")
            if (f"{base}.py" in shipped
                    or f"{base}/__init__.py" in shipped
                    or any(s.startswith(base + "/") for s in shipped)):
                continue
            problems.append(f"{rel} imports {mod}, which does not ship")
    assert problems == [], "\n".join(problems)
