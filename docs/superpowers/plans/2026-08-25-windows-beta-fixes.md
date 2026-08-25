# Windows Beta Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Windows bundle actually work for the 3-person beta — MinerU launches, titles and links render, installers run, upgrades are safe, a bad share pointer is fixable on screen — and fix the three app bugs the audit verified.

**Architecture:** Spec `docs/superpowers/specs/2026-08-25-windows-beta-fixes-design.md` (read it first; §S lists the decisions still awaiting Destin, §W what is deliberately NOT here). Three groups touching mostly disjoint files: `packaging/` (bundle filter, installer, launcher), the pointer/repair chain (`store/config.py`, `store/chunk_store.py`, `app/machine_config.py`, `app/health.py`, `app/main.py`, `Repair.tsx`), and three app bugs (`app/routes/pdf.py`, three cache sites, a retry helper). Tasks are ordered so every commit leaves the suite green; Task 15 is a human checkpoint and nothing merges before it.

**Tech Stack:** Python 3.12 / FastAPI / LanceDB 0.36 / pytest; Vite + React 18 / vitest; Windows batch + PowerShell for the installer; the bundle is built on Linux by `packaging/build_bundle.py`.

## Global Constraints

- Work in the worktree `~/ask-the-budget-az-worktrees/windows-beta-fixes` (branch `windows-beta-fixes`, `.venv` symlinked). Run Python as `uv run ...`; the login shell is fish, so wrap multi-command lines in `bash -c '...'`.
- **No probe, health check or validation may create a directory at the pointer location** (spec principle 3). Every new probe goes through `ChunkStore(create=False)`.
- Every user-facing sentence is plain English: no "traceback", "env var", "JSON", "UNC", "LanceDB". The words the spec gives are the words to use.
- Every non-trivial edit carries a WHY comment recording the evidence (CLAUDE.md).
- Text files are read and written with `encoding="utf-8"` — no exceptions.
- Baselines on master `7329973`: **pytest 3342 passed / 5 skipped**, **vitest 1149**, `tsc -b` 0, `npm run build` 0. Every task ends at or above these (minus tests deliberately deleted in Task 3).
- Commit after every task with the trailer:
  ```
  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01MsDhxY5dM3m3VCEy1ETXin
  ```
- Do NOT touch `retrieval/`, `chunking/`, `citation/`, `harness/system-prompt.md` except the one-line `reset_default_collaborators` call in Task 9. The eval (Task 16) is owed only because `ingest/mineru_runner.py` changes.

---

## File map

| File | Change | Task |
|---|---|---|
| `.gitattributes` | new — `*.cmd text eol=crlf` | 1 |
| `tests/test_cmd_line_endings.py` | new — every `packaging/**/*.cmd` is CRLF | 1 |
| `packaging/build_bundle.py` | `INCLUDED_FILES`, drop `site-packages/bin/`, cruft exclusions, no `install.cmd`, copy installer to `dist/` | 2, 3 |
| `tests/test_packaging_manifest.py` | index-lite pin, no-`bin/` pin, cruft pins | 2, 3 |
| `packaging/diag/*`, `packaging/RUN-DIAGNOSTIC.cmd`, `packaging/install.cmd`, `tests/test_diag_tool.py` | deleted | 3 |
| `ingest/mineru_runner.py` | `-m mineru.cli.client` rung; `CREATE_NO_WINDOW` | 4 |
| `tests/test_mineru_runner.py` | two new resolve tests | 4 |
| `app/machine_config.py` | `normalize_data_dir`, `--default-ingest-enabled`, `validate_data_dir` opens LanceDB | 5, 7 |
| `tests/test_machine_config.py`, `tests/test_machine_config_cli.py`, `tests/test_machine_ingest_enabled.py` | new tests + comments | 5, 7 |
| `store/config.py` | `DataDirNotConfigured`, bundle marker rule | 6 |
| `store/chunk_store.py` | `create=` flag | 6 |
| `tests/test_store_config.py`, `tests/test_chunk_store.py` | new tests | 6 |
| `app/health.py` | machine_config rung states, `can_repair`, corpus no-table, `create=False` | 8 |
| `tests/test_health_ladder.py` | new cases | 8 |
| `app/main.py` | `_probe_provider`, `reprobe`, route swap, stderr copy | 9 |
| `app/routes/search.py` | call `reprobe()` | 9 |
| `tests/test_app_reprobe.py` | new | 9 |
| `webapp/src/api.ts`, `webapp/src/pages/Repair.tsx`, `webapp/src/HealthGate.test.tsx`, `webapp/src/pages/Search.tsx`, `webapp/src/pages/Search.test.tsx` | copy, types, stub banner | 10 |
| `app/routes/pdf.py`, `app/main.py`, `tests/test_chunk_locate.py` | OrderedDict + shutdown close | 11 |
| `store/documents.py`, `harness/settings.py`, `app/search_provider.py` + their tests | cache-on-error | 12 |
| `store/fs.py` (new), `ingest/jobs.py`, `ingest/archive.py`, `store/config.py`, `ingest/fiscal_notes_refresh.py`, `ingest/lock.py`, `tests/test_store_fs.py` | retry helper | 13 |
| `packaging/launcher.pyw`, `tests/test_launcher.py` (new) | port lock, timeout, top-level catch, mineru.json, provider log | 14 |
| `packaging/Install-JLBC-Search.cmd` | new layout, stop server, guarded rmdir, old-layout cleanup, flags | 14 |
| `docs/QUICKSTART.md`, `README.md`, `packaging/README.md`, `STATUS.md` | docs | 15, 17 |

---

### Task 1: `.cmd` files are CRLF, by rule and by test

**Files:**
- Create: `.gitattributes`
- Create: `tests/test_cmd_line_endings.py`
- Modify: `packaging/install.cmd`, `packaging/Install-JLBC-Search.cmd` (renormalised bytes only)

**Interfaces:**
- Produces: the invariant "every tracked `*.cmd` is CRLF", which Task 14's installer edits inherit.

- [ ] **Step 1: Write the failing test**

`tests/test_cmd_line_endings.py`:

```python
"""Every batch file ships with CRLF line endings.

WHY: cmd.exe reads `call :label` / `goto :label` by scanning for the label
with CR-LF semantics; an LF-only file finds the wrong offset and the
installer "flashes and closes" — the exact failure STATUS.md recorded for
the diagnostic tool on 2026-08-18 and that `install.cmd` and
`Install-JLBC-Search.cmd` were STILL carrying on 2026-08-25
(`git ls-files --eol` → i/lf). `.gitattributes` fixes the checkout; this
test fixes the next person who saves the file from an editor that strips CR.
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
CMD_FILES = sorted((REPO / "packaging").rglob("*.cmd"))


def test_there_are_cmd_files_to_check():
    assert CMD_FILES, "packaging/ has no .cmd files — did the installer move?"


@pytest.mark.parametrize("path", CMD_FILES, ids=lambda p: p.name)
def test_every_cmd_file_is_crlf(path: Path):
    data = path.read_bytes()
    assert b"\r\n" in data, f"{path.name} is LF-only; cmd.exe mis-parses labels"
    bare_lf = data.replace(b"\r\n", b"").count(b"\n")
    assert bare_lf == 0, f"{path.name} mixes LF and CRLF ({bare_lf} bare LF)"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_cmd_line_endings.py -v`
Expected: FAIL for `install.cmd` and `Install-JLBC-Search.cmd` ("is LF-only"); PASS for the two `diag` files.

- [ ] **Step 3: Add `.gitattributes` and renormalise**

`.gitattributes`:

```
# cmd.exe needs CRLF to find `call :label` / `goto :label` targets; an LF-only
# batch file "flashes and closes". Tracked in the repo so a checkout on any OS
# yields a file Windows can run. tests/test_cmd_line_endings.py is the guard.
*.cmd text eol=crlf
```

Then: `bash -c 'cd ~/ask-the-budget-az-worktrees/windows-beta-fixes && git add .gitattributes && git add --renormalize packaging/ && git ls-files --eol packaging/*.cmd packaging/diag/*.cmd'`
Expected: every row reads `i/crlf w/crlf attr/text eol=crlf`. If `w/` still says `lf`, run `git checkout -- packaging/install.cmd packaging/Install-JLBC-Search.cmd` to rewrite the working copies.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_cmd_line_endings.py -v`
Expected: 5 passed (4 files + the non-empty check).

- [ ] **Step 5: Commit**

```bash
git add .gitattributes tests/test_cmd_line_endings.py packaging/
git commit -m "packaging: every .cmd is CRLF — .gitattributes + a test

install.cmd and Install-JLBC-Search.cmd were still LF-only (git ls-files
--eol i/lf), the exact cause of the flash-and-close STATUS recorded for
the diag tool. The attribute fixes checkouts; the test fixes editors."
```

---

### Task 2: The bundle ships what the code reads and nothing it can't run

**Files:**
- Modify: `packaging/build_bundle.py:110-260` (source selection), `packaging/build_bundle.py:325-372` (`step_wheels`), `packaging/build_bundle.py:490-500` (`step_zip`)
- Modify: `tests/test_packaging_manifest.py`

**Interfaces:**
- Produces: `INCLUDED_FILES: tuple[str, ...]` (repo-relative paths re-admitted despite an excluded prefix); `source_files()` honours it; `step_zip` also copies `packaging/Install-JLBC-Search.cmd` to `dist/`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_packaging_manifest.py`:

```python
# ---------------------------------------------------------------------------
# What the runtime reads must ship (2026-08-25 Windows audit)
# ---------------------------------------------------------------------------
def test_the_mockup_index_the_search_provider_reads_at_runtime_ships():
    """`webapp/reference/` is excluded as a tree, but app/search_provider.py
    reads ONE file from it at runtime for the meta line and the exact-URL
    join. On the 0.9.1 bundle that file was missing, `_load_mockup_index()`
    raised, the broad except swallowed it, and EVERY Budget Documents row
    lost its title, Open link and meta line on every office PC — with one
    stderr line nobody reads as the only symptom."""
    from app.search_provider import MOCKUP_INDEX_PATH

    rel = MOCKUP_INDEX_PATH.relative_to(REPO_ROOT).as_posix()
    assert rel in set(source_files()), f"{rel} is read at runtime but would not ship"


def test_posix_console_scripts_do_not_ship():
    """site-packages/bin/ holds 62 POSIX shell scripts whose shebang is the
    dev machine's venv path. Useless on Windows and confusing to anyone who
    opens the folder."""
    problems = validate_manifest(_complete_manifest() + ["site-packages/bin/mineru"])
    assert problems, "a POSIX console script slipped into the bundle"


@pytest.mark.parametrize("cruft", ["mockups/index.html", "PROMPT-windows-launch-repair.md",
                                   "PROMPT-anything-at-all.md"])
def test_dev_cruft_does_not_ship(cruft):
    """`mockups/` and every root-level PROMPT-*.md are dev artefacts. The old
    EXCLUDED_NAMES listed twelve PROMPT files by name and seven newer ones
    were shipping; matching the prefix closes that hole for good."""
    problems = validate_manifest(_complete_manifest() + [cruft])
    assert problems, f"{cruft} would ship"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_packaging_manifest.py -v -k "mockup_index or posix_console or dev_cruft"`
Expected: all FAIL (index-lite not in `source_files()`; `validate_manifest` accepts the other paths).

- [ ] **Step 3: Implement**

In `packaging/build_bundle.py`, after `EXCLUDED_NAMES` add:

```python
# Files re-admitted despite an EXCLUDED_PREFIXES hit. Each one is READ AT
# RUNTIME by shipped code — check with `grep -rn "<name>" app store harness`
# before removing an entry. Pinned by tests/test_packaging_manifest.py.
INCLUDED_FILES = (
    # app/search_provider.py::MOCKUP_INDEX_PATH — the vendored site index that
    # supplies the Budget Documents meta line and the exact-URL join. Missing
    # from 0.9.1: every row rendered as a humanised doc_id with no Open link.
    "webapp/reference/assets/search/index-lite.js",
)
```

Add `"mockups/"` to `EXCLUDED_PREFIXES` with the comment `# HTML mockups — design record, not runtime`.

Add to `FORBIDDEN_SUBSTRINGS`:

```python
    "site-packages/bin/",   # POSIX console scripts with the dev venv's shebang
    "mockups/",
```

and a new tuple beside it:

```python
# Root-level handoff prompts, matched by prefix: the by-name list rotted
# (seven newer PROMPT-*.md files were shipping on 0.9.1).
FORBIDDEN_ROOT_PREFIXES = ("PROMPT-",)
```

In `validate_manifest`, after the `FORBIDDEN_SUBSTRINGS` loop:

```python
        if "/" not in p and p.startswith(FORBIDDEN_ROOT_PREFIXES):
            problems.append(f"forbidden content in bundle: {p} (root handoff prompt)")
```

In `source_files`, change the prefix check to:

```python
        if rel.startswith(EXCLUDED_PREFIXES) and rel not in INCLUDED_FILES:
            continue
```

and after the `EXCLUDED_NAMES` check add:

```python
        if "/" not in rel and rel.startswith(FORBIDDEN_ROOT_PREFIXES):
            continue
```

In `step_wheels`, after the wheel closure is laid into `target = out / "site-packages"`, add:

```python
    # uv lays console scripts into site-packages/bin/ with the BUILD machine's
    # venv shebang (`#!/home/destin/.../.venv/bin/python3`). They cannot run
    # on Windows and the bundle's own mineru rung is `-m mineru.cli.client`
    # (ingest/mineru_runner.py), so nothing needs them.
    shutil.rmtree(target / "bin", ignore_errors=True)
```

In `step_zip`, after the zip is written:

```python
    # The one-click installer sits NEXT TO the zip on the USB and is the file
    # that flashed-and-closed on 2026-08-18. Copying it here means the USB is
    # assembled from one place, and the CRLF guard covers the copy.
    installer = Path(__file__).resolve().parent / "Install-JLBC-Search.cmd"
    shutil.copy2(installer, dist / installer.name)
    if b"\r\n" not in (dist / installer.name).read_bytes():
        raise SystemExit(f"{installer.name} is not CRLF — see tests/test_cmd_line_endings.py")
    _log(f"copied  {installer.name} beside the zip")
```

- [ ] **Step 4: Run the manifest suite**

Run: `uv run pytest tests/test_packaging_manifest.py -v`
Expected: all pass, including `test_source_files_is_a_subset_of_what_git_tracks` and `test_the_real_source_list_has_no_forbidden_content`.

- [ ] **Step 5: Commit**

```bash
git add packaging/build_bundle.py tests/test_packaging_manifest.py
git commit -m "packaging: ship index-lite.js, drop POSIX bin/ scripts and dev cruft

app/search_provider.py reads webapp/reference/.../index-lite.js at runtime;
the 0.9.1 bundle excluded it and every Budget Documents row lost its title
and Open link. INCLUDED_FILES re-admits it and a test imports the path
the provider uses so the two cannot drift. Also: site-packages/bin/ (62
Linux shebang scripts), mockups/, and PROMPT-*.md by prefix stop shipping."
```

---

### Task 3: Delete the diagnostic tool and the manual installer

**Files:**
- Delete: `packaging/diag/diag.cmd`, `packaging/diag/diag.pyw`, `packaging/diag/RUN-DIAGNOSTIC.cmd`, `packaging/install.cmd`, `tests/test_diag_tool.py`
- Modify: `packaging/build_bundle.py` (`REQUIRED_ENTRIES`, `step_launcher`, module docstring lines 1-35), `packaging/README.md` (rows 4, 12; the "Known couplings" `install.cmd` bullet; "verified" bullets that name `install.cmd`), `tests/test_packaging_manifest.py::_complete_manifest` (the `.cmd` suffix branch becomes unreachable — leave it; nothing to change)

**Interfaces:**
- Produces: `REQUIRED_ENTRIES` without `"install.cmd"`; `step_launcher` copies only `launcher.pyw`, `QUICKSTART.md`, `VERSION`.

- [ ] **Step 1: Delete**

```bash
git rm -q packaging/diag/diag.cmd packaging/diag/diag.pyw packaging/diag/RUN-DIAGNOSTIC.cmd packaging/install.cmd tests/test_diag_tool.py
```

- [ ] **Step 2: Edit `build_bundle.py`**

Remove `"install.cmd",` from `REQUIRED_ENTRIES`. In `step_launcher` change the loop to:

```python
    # install.cmd (the unzip-it-yourself path) was deleted 2026-08-25 (spec S1):
    # the one-click Install-JLBC-Search.cmd on the USB is the only installer.
    shutil.copy2(here / "launcher.pyw", out / "launcher.pyw")
```

Update the module docstring's layout listing (line ~31) to drop `install.cmd`, and line 4's sentence to *"`Install-JLBC-Search.cmd` on the USB does the entire install"*.

- [ ] **Step 3: Edit `packaging/README.md`**

Line 4: replace the sentence with *"Double-clicking `Install-JLBC-Search.cmd` on the USB, next to the zip, is the entire install — no admin rights, no Python on the machine, no Java on the machine, and no downloads the first time it runs."* Replace the `install.cmd` table row with `| `Install-JLBC-Search.cmd` | The one-click installer. Lives on the USB next to the zip (copied to `dist/` by the build). Asks for two folders, stops any running server, replaces `program\`, creates the shortcuts. |`. Replace every remaining `install.cmd` mention (the Known-couplings bullet, the two "verified" bullets) with `Install-JLBC-Search.cmd`. Add a one-line note under "What has still NOT been verified": *"The `program\` layout and the upgrade path (Task 14 of the 2026-08-25 plan) have not been run on Windows."*

- [ ] **Step 4: Run the suites that touch these**

Run: `uv run pytest tests/test_packaging_manifest.py tests/test_cmd_line_endings.py -v`
Expected: all pass (the CRLF test now parametrises over one file).

Run: `bash -c 'cd ~/ask-the-budget-az-worktrees/windows-beta-fixes && uv run python packaging/build_bundle.py --plan'`
Expected: prints the plan; `required 17 manifest entries asserted`.

- [ ] **Step 5: Commit**

```bash
git add -A packaging/ tests/
git commit -m "packaging: delete the USB diagnostic tool and install.cmd (spec D1, S1)

Destin's call 2026-08-25: the in-app repair screen is the one recovery
path. The rewrite's repair also copied the USB seed's older documents.json
over a newer one on the share. install.cmd goes with it — two installers is
how the LF bug reached both."
```

---

### Task 4: MinerU launches from the bundle

**Files:**
- Modify: `ingest/mineru_runner.py:144-168` (`resolve_mineru_exe`), `ingest/mineru_runner.py:510-530` (`_stream`)
- Test: `tests/test_mineru_runner.py:80-106`

**Interfaces:**
- Produces: `resolve_mineru_exe() -> list[str]` with a new second rung `[sys.executable, "-m", "mineru.cli.client"]`.

- [ ] **Step 1: Write the failing tests**

Insert after `test_resolve_exe_uses_path_when_present` in `tests/test_mineru_runner.py`:

```python
def test_resolve_exe_runs_the_module_when_the_package_is_importable(monkeypatch):
    """The Windows bundle has no `mineru.exe` and no `Scripts/` — only the
    importable package. Found 2026-08-25: with nothing on PATH the old chain
    fell through to `uv run mineru`, which does not exist on office PCs, so
    every MinerU-routed upload failed in under a second."""
    import importlib.util
    import sys

    monkeypatch.delenv("JLBC_MINERU_EXE", raising=False)
    monkeypatch.setattr("shutil.which", lambda _name: None)
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object() if name == "mineru" else None)
    assert resolve_mineru_exe() == [sys.executable, "-m", "mineru.cli.client"]


def test_resolve_exe_env_override_still_beats_the_module(monkeypatch, tmp_path):
    import importlib.util

    fake = tmp_path / "mineru.exe"
    fake.write_text("")
    monkeypatch.setenv("JLBC_MINERU_EXE", str(fake))
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    assert resolve_mineru_exe() == [str(fake)]
```

Also edit the existing `test_resolve_exe_falls_back_to_uv_run_in_dev` to patch `importlib.util.find_spec` to return `None` (otherwise it now returns the module rung on this venv, where mineru IS importable):

```python
def test_resolve_exe_falls_back_to_uv_run_in_dev(monkeypatch):
    """Dev machines without the package importable run it through uv."""
    import importlib.util

    monkeypatch.delenv("JLBC_MINERU_EXE", raising=False)
    monkeypatch.setattr("shutil.which", lambda _name: None)
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    assert resolve_mineru_exe() == ["uv", "run", "mineru"]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_mineru_runner.py -v -k resolve_exe`
Expected: the two new tests FAIL; the edited one passes.

- [ ] **Step 3: Implement**

Replace the tail of `resolve_mineru_exe` (after the env-override block) with:

```python
    found = shutil.which("mineru")
    if found:
        return [found]

    # The Windows bundle (packaging/build_bundle.py) ships the `mineru`
    # PACKAGE but no `mineru.exe` — the embeddable interpreter has no
    # Scripts/ dir and the POSIX console scripts uv lays down are Linux
    # shebangs. `mineru.cli.client:main` is what the console script wraps
    # (mineru-3.1.6.dist-info/entry_points.txt), so run the module with the
    # interpreter we are already inside. Under the launcher that is
    # pythonw.exe, which also means: no console window. Found 2026-08-25 —
    # before this rung the bundle fell through to `uv run mineru`.
    import importlib.util

    if importlib.util.find_spec("mineru") is not None:
        return [sys.executable, "-m", "mineru.cli.client"]
    return ["uv", "run", "mineru"]
```

Update the docstring's rung list to four rungs (env, PATH, module, uv). Ensure `import sys` is present at the top of the module.

In `_stream`, change the `Popen` call to pass creation flags:

```python
        # A console-subsystem child spawned from pythonw.exe gets its own
        # console window — a black box on the analyst's desktop for the length
        # of the extraction, and closing it kills the job. The bundle runs
        # MinerU via pythonw (see resolve_mineru_exe) so this is belt-and-
        # braces for a dev running the server from python.exe; it does NOT
        # reach OpenDataLoader's Java child, whose runner hardcodes its own
        # Popen (spec §W).
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=self.child_env(),
            creationflags=flags,
        )
```

- [ ] **Step 4: Run the runner suite**

Run: `uv run pytest tests/test_mineru_runner.py tests/test_mineru_batch.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add ingest/mineru_runner.py tests/test_mineru_runner.py
git commit -m "ingest: run MinerU as -m mineru.cli.client when no executable exists

The Windows bundle ships the package but no mineru.exe; the old chain fell
through to 'uv run mineru', which office PCs do not have, so every
MinerU-routed upload failed in under a second. Also CREATE_NO_WINDOW on nt."
```

---

### Task 5: The pointer is normalised; the installer's ingest default is a default

**Files:**
- Modify: `app/machine_config.py:191-330`
- Test: `tests/test_machine_config.py`, `tests/test_machine_config_cli.py`, `tests/test_machine_ingest_enabled.py:57,127-138`

**Interfaces:**
- Produces: `normalize_data_dir(path: Path | str) -> str`; `set_data_dir` stores the normalised form; CLI flag `--default-ingest-enabled {true,false}`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_machine_config.py`:

```python
# ---------------------------------------------------------------------------
# Normalisation (2026-08-25, the laptop incident — see
# docs/superpowers/investigations/2026-08-25-windows-launch-failure.md)
# ---------------------------------------------------------------------------
import os

from app.machine_config import normalize_data_dir


@pytest.mark.parametrize(
    "typed, stored",
    [
        ("//bcpool/JLBCSearch", r"\\bcpool\JLBCSearch"),
        ("/bcpool/JLBCSearch", r"\\bcpool\JLBCSearch"),
        ("E:/JLBCSearch/", r"E:\JLBCSearch"),
        ('"E:\\JLBCSearch\\"', r"E:\JLBCSearch"),
        ("E:\\", "E:\\"),
        (r"\\bcpool\JLBCSearch", r"\\bcpool\JLBCSearch"),
        ("  Z:/x/y  ", r"Z:\x\y"),
    ],
)
def test_normalize_on_windows(monkeypatch, typed, stored):
    """The exact strings from the 2026-08-18 laptop log. `//bcpool/JLBCSearch`
    passed every Path check, was saved, and LanceDB refused it (InvalidUrl)."""
    monkeypatch.setattr(os, "name", "nt")
    assert normalize_data_dir(typed) == stored


def test_normalize_on_posix_only_trims(monkeypatch):
    monkeypatch.setattr(os, "name", "posix")
    assert normalize_data_dir(' "/mnt/share/jlbc/" ') == "/mnt/share/jlbc"
    assert normalize_data_dir("//server/share/x") == "//server/share/x"


def test_set_data_dir_stores_the_normalised_form(monkeypatch, tmp_path):
    monkeypatch.setenv("JLBC_MACHINE_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(os, "name", "nt")
    from app.machine_config import machine_config_path, set_data_dir

    set_data_dir("//bcpool/JLBCSearch")
    raw = json.loads(machine_config_path().read_text(encoding="utf-8"))
    assert raw["data_dir"] == r"\\bcpool\JLBCSearch"
```

(Add `import json` at the top of the file if absent.)

Append to `tests/test_machine_config_cli.py`:

```python
def test_default_ingest_enabled_only_writes_when_the_key_is_absent(tmp_path, config_dir):
    """An upgrade re-runs the installer. `--set-ingest-enabled false` there
    switched the ONE ingest machine off every time (found 2026-08-25);
    `--default-ingest-enabled` records the office default without
    overriding a choice already made on this PC."""
    r = run("--default-ingest-enabled", "false", config_dir=config_dir)
    assert r.returncode == 0
    assert json.loads((config_dir / "machine.json").read_text())["ingest_enabled"] is False

    r = run("--set-ingest-enabled", "true", config_dir=config_dir)
    assert r.returncode == 0
    r = run("--default-ingest-enabled", "false", config_dir=config_dir)
    assert r.returncode == 0
    assert json.loads((config_dir / "machine.json").read_text())["ingest_enabled"] is True
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_machine_config.py tests/test_machine_config_cli.py -v -k "normalize or default_ingest"`
Expected: FAIL — `ImportError: normalize_data_dir`; the CLI rejects the unknown flag.

- [ ] **Step 3: Implement**

In `app/machine_config.py`, above `validate_data_dir`:

```python
def normalize_data_dir(path: Path | str) -> str:
    """The stored form of a data-dir path: the spelling the storage engine
    can open.

    WHY this exists (work laptop, 2026-08-18 — see
    docs/superpowers/investigations/2026-08-25-windows-launch-failure.md):
    `//bcpool/JLBCSearch` passes every pathlib check (`exists`, `is_dir`,
    `iterdir`), so the repair screen accepted it and said "saved"; LanceDB's
    Rust object store then built a `file://` URL from it and refused it
    (InvalidUrl) — and the app kept serving stub fixtures. Every writer
    funnels through here first, so what lands in machine.json is the form
    LanceDB opens, not what was typed.

    Rules: trim, strip surrounding quotes, drop trailing separators (but not
    from a bare drive root — `E:` alone means "current directory on E:").
    On Windows every `/` becomes `\\`; a path starting with ONE separator
    (`/host/share`) is read as a UNC root and gains its second one. That
    last rule is a guess — `\\JLBCSearch` can also mean `C:\\JLBCSearch` —
    and is harmless only because validate_data_dir refuses anything that
    does not open.
    """
    cleaned = str(path).strip().strip('"').strip("'").strip()
    stripped = cleaned.rstrip("\\/")
    # `E:\` -> keep the separator; `E:` is not a folder.
    cleaned = cleaned[: len(stripped) + 1] if stripped.endswith(":") else stripped
    if os.name == "nt":
        cleaned = cleaned.replace("/", "\\")
        if len(cleaned) >= 2 and cleaned[0] == "\\" and cleaned[1] != "\\":
            cleaned = "\\" + cleaned
    return cleaned
```

Change `set_data_dir`:

```python
def set_data_dir(path: Path | str) -> Path:
    """Point this machine at `path`. Returns the stored path.

    Does NOT validate — the caller does, so it can report which of the
    failures happened. Writing an unvalidated path deliberately remains
    possible: an admin fixing a pointer while the share is temporarily down
    should not be blocked by the share being down.

    STORED NORMALISED (`normalize_data_dir`): the laptop incident proved a
    pointer can pass every Python check and still be a form the storage
    engine refuses.
    """
    stored = normalize_data_dir(path)
    _update({"data_dir": stored})
    return Path(stored)
```

In `validate_data_dir`, replace the first three lines of the body with:

```python
    candidate_str = normalize_data_dir(path)
    if not candidate_str:
        return "Type the full path to the shared JLBC Search folder."
    candidate = Path(candidate_str)
```

(Task 7 extends this function further.)

In `main()`, add the flag and its handling:

```python
    parser.add_argument(
        "--default-ingest-enabled", metavar="BOOL", choices=("true", "false"),
        help="record the value only if machine.json has no ingest_enabled key",
    )
```

Update the "nothing to do" check to include `args.default_ingest_enabled is None`, and after the `--set-ingest-enabled` block:

```python
    if args.default_ingest_enabled is not None:
        # WHY a separate flag: the installer runs on every upgrade, and
        # `--set-ingest-enabled false` there switched the one ingest machine
        # off each time (2026-08-25). A default must not override a choice.
        if "ingest_enabled" not in _read_all(quiet=True):
            set_ingest_enabled(args.default_ingest_enabled == "true")
```

In `tests/test_machine_ingest_enabled.py`, add one comment above the first `//server/share/JLBC-Search-Data` literal (line 57):

```python
    # The forward-slash UNC form survives on Linux (normalize_data_dir only
    # rewrites separators on nt). On Windows the stored form is
    # \\server\share\... — pinned in tests/test_machine_config.py.
```

- [ ] **Step 4: Run**

Run: `uv run pytest tests/test_machine_config.py tests/test_machine_config_cli.py tests/test_machine_ingest_enabled.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add app/machine_config.py tests/test_machine_config.py tests/test_machine_config_cli.py tests/test_machine_ingest_enabled.py
git commit -m "machine_config: normalise the pointer before storing; --default-ingest-enabled

//bcpool/JLBCSearch passed every pathlib check on the laptop and LanceDB
refused it. Every writer now stores the form the storage engine opens.
The installer's ingest default no longer overrides a choice on upgrade."
```

---

### Task 6: No probe creates directories; a bundle with no pointer says so

**Files:**
- Modify: `store/config.py:36-95`, `store/chunk_store.py:94-99`
- Test: `tests/test_store_config.py`, `tests/test_chunk_store.py`

**Interfaces:**
- Produces: `class DataDirNotConfigured(OSError)` in `store/config.py`; `resolve_data_dir()` raises it when no env var, no pointer, and `<root>/VERSION` exists; `ChunkStore(*, root=None, dim=..., create=True)` — `create=False` raises `FileNotFoundError` if `<root>/lancedb` is not a directory and never calls `mkdir`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_store_config.py`:

```python
from store.config import DataDirNotConfigured, resolve_data_dir
import store.config as config_mod


def test_a_bundle_with_no_pointer_is_not_configured(monkeypatch, tmp_path):
    """The bundle root carries a VERSION file (build_bundle.py writes it,
    REQUIRED_ENTRIES demands it); no dev checkout has one. A bundle with no
    pointer must NOT fall back to <root>/data/insight-data — on the laptop
    that folder was silently created and the app served stub fixtures."""
    monkeypatch.delenv("JLBC_DATA_DIR", raising=False)
    monkeypatch.setenv("JLBC_MACHINE_CONFIG_DIR", str(tmp_path / "machine"))
    root = tmp_path / "bundle"
    (root / "store").mkdir(parents=True)
    (root / "VERSION").write_text("0.9.2\n", encoding="utf-8")
    monkeypatch.setattr(config_mod, "_ROOT", root)
    with pytest.raises(DataDirNotConfigured):
        resolve_data_dir()


def test_a_dev_checkout_with_no_pointer_uses_the_repo_default(monkeypatch, tmp_path):
    monkeypatch.delenv("JLBC_DATA_DIR", raising=False)
    monkeypatch.setenv("JLBC_MACHINE_CONFIG_DIR", str(tmp_path / "machine"))
    root = tmp_path / "checkout"
    (root / "store").mkdir(parents=True)
    monkeypatch.setattr(config_mod, "_ROOT", root)
    assert resolve_data_dir() == root / "data" / "insight-data"


def test_the_pointer_still_wins_inside_a_bundle(monkeypatch, tmp_path):
    monkeypatch.delenv("JLBC_DATA_DIR", raising=False)
    monkeypatch.setenv("JLBC_MACHINE_CONFIG_DIR", str(tmp_path / "machine"))
    root = tmp_path / "bundle"
    root.mkdir()
    (root / "VERSION").write_text("0.9.2\n", encoding="utf-8")
    monkeypatch.setattr(config_mod, "_ROOT", root)
    from app.machine_config import set_data_dir

    set_data_dir(str(tmp_path / "share"))
    assert resolve_data_dir() == tmp_path / "share"
```

Append to `tests/test_chunk_store.py`:

```python
def test_create_false_never_makes_the_lancedb_folder(tmp_path):
    """Spec principle 3: a probe that manufactures the folder it is probing
    can only ever report 'fine'. On the laptop this is why a wrong pointer
    read as 'index can't be opened, can't repair' instead of 'wrong folder'."""
    from store.chunk_store import ChunkStore

    root = tmp_path / "share"
    root.mkdir()
    with pytest.raises(FileNotFoundError):
        ChunkStore(root=root, create=False)
    assert not (root / "lancedb").exists()


def test_create_false_opens_an_existing_folder(tmp_path):
    from store.chunk_store import ChunkStore

    root = tmp_path / "share"
    (root / "lancedb").mkdir(parents=True)
    store = ChunkStore(root=root, create=False)
    assert store.count("budget_chunks") == 0
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_store_config.py tests/test_chunk_store.py -v -k "bundle or dev_checkout or pointer_still or create_false"`
Expected: FAIL (`ImportError`, `TypeError: unexpected keyword 'create'`).

- [ ] **Step 3: Implement**

`store/config.py` — add near the top, after the constants:

```python
# The root of THIS checkout or bundle: `<root>/store/config.py`. Module-level
# so tests can point it at a temp tree.
_ROOT = Path(__file__).resolve().parent.parent

# Written by packaging/build_bundle.py at the bundle root and required by its
# manifest; absent from every dev checkout (untracked, never created). Its
# presence is how the app knows it is a packaged install with no repo-default
# corpus to fall back to.
_BUNDLE_MARKER = "VERSION"


class DataDirNotConfigured(OSError):
    """A packaged install with no pointer and no env override.

    Raised rather than returning a made-up folder: on the 2026-08-18 laptop the
    fallback `<install>/data/insight-data` was silently CREATED, the health
    ladder then passed the 'share' rung (the folder existed) and the app served
    stub fixtures with nothing on screen naming the missing setting.
    """
```

In `resolve_data_dir`, replace the `else:` branch that builds the repo default:

```python
        else:
            if (_ROOT / _BUNDLE_MARKER).is_file():
                raise DataDirNotConfigured(
                    "This computer hasn't been told where the shared budget folder is."
                )
            # WHY repo-relative: dev machines have no share; keeping the dev
            # corpus inside data/ (already gitignored) means zero setup.
            root = _ROOT / "data" / "insight-data"
```

Update the docstring's resolution order line to: *"`JLBC_DATA_DIR` > this machine's `machine.json` pointer > the repo default (dev checkouts only — a bundle, marked by `VERSION` at its root, raises `DataDirNotConfigured` instead)."*

`data_dir()` needs no change: `resolve_data_dir()` raises before the `mkdir`, and the docstring gains one sentence: *"`DataDirNotConfigured` propagates — there is no folder to create; the health ladder reports it and the repair screen fixes it."*

`store/chunk_store.py`:

```python
class ChunkStore:
    def __init__(self, *, root: Path | None = None, dim: int = DEFAULT_DIM,
                 create: bool = True):
        self._root = (root or data_dir()) / "lancedb"
        if create:
            self._root.mkdir(parents=True, exist_ok=True)
        elif not self._root.is_dir():
            # WHY not connect anyway: lancedb.connect() creates a missing
            # local directory itself. A PROBE must never do that — spec
            # principle 3 (2026-08-25); the health ladder, the startup
            # provider probe and validate_data_dir all pass create=False.
            raise FileNotFoundError(f"no lancedb folder at {self._root}")
        self._dim = dim
        self._db = lancedb.connect(str(self._root))
```

- [ ] **Step 4: Run**

Run: `uv run pytest tests/test_store_config.py tests/test_chunk_store.py tests/test_machine_config.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add store/config.py store/chunk_store.py tests/test_store_config.py tests/test_chunk_store.py
git commit -m "store: a bundle with no pointer raises; ChunkStore(create=False) for probes

A probe that creates the folder it probes can only report 'fine' — that
is why the laptop's wrong pointer read as 'index can't be opened'. The
bundle is detected by its VERSION marker; dev checkouts keep the default."
```

---

### Task 7: Validation opens the folder the way LanceDB does

**Files:**
- Modify: `app/machine_config.py::validate_data_dir`
- Test: `tests/test_machine_config.py`

**Interfaces:**
- Consumes: `ChunkStore(root=..., create=False)` from Task 6.
- Produces: `MSG_CANT_OPEN` constant; `validate_data_dir` returns it when connect/list raises.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_machine_config.py`:

```python
from app.machine_config import MSG_CANT_OPEN, MSG_NO_CORPUS, validate_data_dir


def test_validate_refuses_an_empty_index_folder(tmp_path):
    """lancedb.connect() on an empty directory SUCCEEDS and lists no tables
    (measured, lancedb 0.36) — so this lands on MSG_NO_CORPUS, not on
    'can't be opened'."""
    (tmp_path / "lancedb").mkdir()
    assert validate_data_dir(tmp_path) == MSG_NO_CORPUS


def test_validate_refuses_a_folder_the_engine_cannot_open(tmp_path, monkeypatch):
    """The laptop's InvalidUrl shape: pathlib says yes, the storage engine
    says no. Only an actual open can tell."""
    (tmp_path / "lancedb").mkdir()
    import store.chunk_store as cs

    def boom(*a, **k):
        raise ValueError("Invalid input, Failed to connect to namespace")

    monkeypatch.setattr(cs.lancedb, "connect", boom)
    assert validate_data_dir(tmp_path) == MSG_CANT_OPEN


def test_validate_accepts_a_folder_with_rows(tmp_path):
    """One row is enough — the check is 'has budget passages', not 'how many'.
    DEFAULT dim (768): validate opens with ChunkStore's default and `_open`
    checks the table's vector width, so an 8-dim test table would read as
    'can't be opened'."""
    from store.chunk_store import ChunkStore
    from tests.test_chunk_store import _row

    store = ChunkStore(root=tmp_path)
    store.upsert_chunks("budget_chunks", [_row("c1", "ahcccs", [0.0] * 768)])
    assert validate_data_dir(tmp_path) is None
```

(`tests/test_chunk_store.py::_row(cid, text, vec, **over)` already builds a schema-complete row; `tests/` is importable as a package in this suite — if the import fails, copy the 12-line helper into this file.)

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_machine_config.py -v -k "validate_refuses_an_empty or cannot_open or with_rows"`
Expected: `ImportError: MSG_CANT_OPEN`; the empty-index test currently returns `None` (accepts).

- [ ] **Step 3: Implement**

Add beside `MSG_NO_CORPUS`:

```python
MSG_CANT_OPEN = (
    "That folder is there, but the search index inside it can't be opened. "
    "Copy the folder's address from File Explorer's address bar and try again."
)
```

Replace the tail of `validate_data_dir` (after the `lancedb` `is_dir` check) with:

```python
    # Open it the way the app does. The laptop incident (2026-08-18):
    # `//bcpool/JLBCSearch` passed every pathlib check above and the storage
    # engine refused it, so the repair screen reported success over an app
    # still serving fixtures. This is the only check that cannot false-pass.
    # create=False: validation must never manufacture a folder (principle 3).
    # Repair path only — never a hot path — so an open is affordable.
    try:
        from store.chunk_store import ChunkStore

        rows = ChunkStore(root=candidate, create=False).count("budget_chunks")
    except Exception:  # noqa: BLE001 — every engine failure is one sentence
        return MSG_CANT_OPEN
    if rows <= 0:
        return MSG_NO_CORPUS
    return None
```

Update `MSG_NO_CORPUS` text to cover both shapes: *"That folder doesn't contain a JLBC Search corpus (no budget documents in its search index)."* and check `tests/test_machine_config.py::test_validate_rejects_a_folder_with_no_corpus` and the CLI test `test_a_folder_without_a_corpus_still_records` still pass (they compare against the constant, not the literal).

- [ ] **Step 4: Run**

Run: `uv run pytest tests/test_machine_config.py tests/test_machine_config_cli.py -v`
Expected: all pass. Note the existing `test_validate_accepts_a_folder_holding_a_corpus` (line 96) creates only an empty `lancedb/` — it will now FAIL. Rewrite it to build a store with one row (same shape as `test_validate_accepts_a_folder_with_rows`) or delete it in favour of the new one; note in the commit which.

- [ ] **Step 5: Commit**

```bash
git add app/machine_config.py tests/test_machine_config.py
git commit -m "machine_config: validate by opening the index, not by pathlib

The repair screen said 'saved' for //bcpool/JLBCSearch because every Path
check passed; only lancedb.connect refuses it. An empty lancedb/ lands on
MSG_NO_CORPUS (connect succeeds, no tables — measured on 0.36)."
```

---

### Task 8: The health ladder puts the repair box on screen for every pointer failure

**Files:**
- Modify: `app/health.py:82-108` (`_check_machine_config`), `:138-183` (`_check_corpus`), `:200-257` (`health_detail`)
- Test: `tests/test_health_ladder.py`

**Interfaces:**
- Consumes: `DataDirNotConfigured` (Task 6), `ChunkStore(create=False)` (Task 6).
- Produces: `can_repair = first_failure in ("machine_config", "share")`; `_check_corpus` fails on no `budget_chunks` table.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_health_ladder.py`:

```python
def test_a_bundle_with_no_pointer_fails_the_config_rung_and_can_repair(
    client, monkeypatch, tmp_path
):
    """The laptop (2026-08-18): first failing rung was machine_config, so
    can_repair was False, the folder box never rendered, and the only advice
    was 'delete this file by hand'."""
    import store.config as config_mod

    monkeypatch.delenv("JLBC_DATA_DIR")
    root = tmp_path / "bundle"
    root.mkdir()
    (root / "VERSION").write_text("0.9.2\n", encoding="utf-8")
    monkeypatch.setattr(config_mod, "_ROOT", root)

    report = client.get("/api/health/detail").json()

    config = rung(report, "machine_config")
    assert config["ok"] is False
    assert "hasn't been told" in config["detail"]
    assert "below" in config["fix"]
    assert report["can_repair"] is True
    assert rung(report, "share")["ok"] is None


def test_a_corrupt_pointer_offers_the_box_not_a_hand_edit(client, tmp_path):
    machine = tmp_path / "machine"
    machine.mkdir(parents=True, exist_ok=True)
    (machine / "machine.json").write_text("{ not json", encoding="utf-8")
    make_corpus(tmp_path)

    report = client.get("/api/health/detail").json()

    config = rung(report, "machine_config")
    assert "Delete this file" not in config["fix"]
    assert "below" in config["fix"]
    assert report["can_repair"] is True


def test_a_dev_checkout_with_no_pointer_is_still_fine(client, tmp_path):
    """Nothing changes for the dev box: no VERSION marker, no failure."""
    make_corpus(tmp_path)
    report = client.get("/api/health/detail").json()
    assert rung(report, "machine_config")["ok"] is True


def test_a_lancedb_folder_with_no_tables_fails_the_corpus_rung(client, tmp_path):
    """An empty lancedb/ used to read as 'set up, no documents yet' — the
    same sentence a fresh install gets. Zero ROWS stays OK (the Upload page
    must be reachable); zero TABLES is a wrong folder or a half copy."""
    make_corpus(tmp_path)
    report = client.get("/api/health/detail").json()
    corpus = rung(report, "corpus")
    assert corpus["ok"] is False
    assert "holds no search index" in corpus["detail"]
    assert report["can_repair"] is False


def test_the_ladder_creates_nothing(client, tmp_path):
    """Principle 3. Before 2026-08-25 the corpus rung's ChunkStore() mkdir'd
    <share>/lancedb, so a wrong pointer passed 'share' and failed 'corpus'
    with can_repair False."""
    (tmp_path / "share").mkdir(parents=True, exist_ok=True)
    client.get("/api/health/detail")
    assert not (tmp_path / "share" / "lancedb").exists()
```

Also update `make_corpus` so the healthy fixture has a real (empty) table, since an empty `lancedb/` now fails:

```python
def make_corpus(tmp_path) -> None:
    from store.chunk_store import ChunkStore

    ChunkStore(root=tmp_path / "share").ensure_tables()
```

And change `test_a_lancedb_folder_with_no_tables_fails_the_corpus_rung` to create the bare folder itself: replace its `make_corpus(tmp_path)` with `(tmp_path / "share" / "lancedb").mkdir(parents=True)`.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_health_ladder.py -v`
Expected: the five new tests FAIL; existing ones pass (re-check `test_can_repair_is_false_when_the_corpus_is_the_problem` — it creates `share/` only, and `_check_corpus`'s first branch "no lancedb folder" still fails it with `can_repair False`, so it stays green).

- [ ] **Step 3: Implement**

`_check_machine_config`:

```python
def _check_machine_config() -> tuple[bool, str, str | None]:
    from app.machine_config import machine_config_path, read_data_dir
    from store.config import DataDirNotConfigured, resolve_data_dir

    fix_type_below = (
        "You don't need to edit anything by hand — type the folder's location "
        "below and the app will rewrite this file correctly."
    )
    path = machine_config_path()
    if not path.exists():
        # A packaged install with no pointer has NO folder to fall back to
        # (store/config.py raises). A dev checkout has the repo default and
        # this stays OK, as before. The laptop incident sat exactly here.
        try:
            resolve_data_dir()
        except DataDirNotConfigured:
            return (
                False,
                "This computer hasn't been told where the shared budget folder is.",
                "Type the folder's location below — it's the one that contains "
                "the 'lancedb' folder.",
            )
        except OSError:
            pass  # a reachability problem is the share rung's to report
        return True, "Using the standard shared-folder setting.", None
    try:
        import json

        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return (
            False,
            "This computer has a settings file saying where the shared folder "
            "is, and it can't be read.",
            fix_type_below,
        )
    if not isinstance(raw, dict):
        return (
            False,
            "This computer's shared-folder setting is not in the expected form.",
            fix_type_below,
        )
    if read_data_dir() is None:
        return (
            False,
            "This computer's shared-folder setting doesn't name a folder.",
            "Type the shared folder's location below.",
        )
    return True, "This computer's shared-folder setting is readable.", None
```

`_check_corpus` — replace the `try` block:

```python
    try:
        from store.chunk_store import ChunkStore

        # create=False: this is a CHECK. Before 2026-08-25 it mkdir'd
        # <share>/lancedb, so a wrong pointer manufactured its own evidence.
        store = ChunkStore(root=root, create=False)
        if "budget_chunks" not in store.table_names():
            return (
                False,
                "The shared folder is there but holds no search index.",
                "Check you typed the folder that contains 'lancedb', or ask "
                "whoever set up the shared drive.",
            )
        count = store.count("budget_chunks")
    except Exception as err:  # noqa: BLE001
        ... (existing hint logic unchanged)
```

`store.table_names()` — add a one-line public method to `ChunkStore` if none exists: `def table_names(self) -> list[str]: return list(self._db.table_names())`.

`health_detail` — the `resolve_data_dir()` try already swallows the new exception (`root = None`); the `share` lambda then reports "could not be worked out", but the ladder short-circuits at `machine_config` first, so it never renders. Change the last line:

```python
        # The repair box helps exactly when the problem IS where the app is
        # pointed: a missing/corrupt pointer, or a pointer at a folder that is
        # not there. Widened from `== "share"` on 2026-08-25 — the laptop's
        # first failure was machine_config and the box never rendered.
        "can_repair": first_failure in ("machine_config", "share"),
```

Update the module docstring's rung description for `machine_config` and `corpus` accordingly.

- [ ] **Step 4: Run**

Run: `uv run pytest tests/test_health_ladder.py tests/test_machine_config.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add app/health.py tests/test_health_ladder.py store/chunk_store.py
git commit -m "health: the repair box appears for every failure the pointer can cause

machine_config fails on a corrupt, empty, or (on a bundle) absent pointer
with 'type the folder below'; can_repair covers it. The corpus rung no
longer creates lancedb/ and fails on a folder with no tables; zero rows
stays OK so a fresh admin install can reach Upload."
```

---

### Task 9: The provider re-probes; a repair takes effect without a restart

**Files:**
- Modify: `app/main.py:47-75` (`_default_provider`), `:215-230` (`create_app`), `:300-320` (data-dir route)
- Modify: `app/routes/search.py:33-37`
- Create: `tests/test_app_reprobe.py`

**Interfaces:**
- Produces: `app.state.reprobe(*, force: bool = False) -> str` (returns the provider name after the attempt); `REPROBE_INTERVAL_S = 30.0`; `POST /api/config/data-dir` returns `{"path": str}` (no `restart_required`).
- Consumes: `retrieval.pipeline.reset_default_collaborators()`.

- [ ] **Step 1: Write the failing tests**

`tests/test_app_reprobe.py`:

```python
"""While the app is on the stub provider it re-probes the corpus (spec §3.3).

Before 2026-08-25 the provider was chosen ONCE at startup: a share that
hiccupped at 8 AM meant fake fixture rows all day, and a repair from the
health screen told the analyst to 'reopen the app' — which the launcher
turns into a no-op by reusing the running server.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.main as main_mod
from app.main import create_app


class FakeLance:
    name = "lance"

    def search(self, *a, **k):  # pragma: no cover — never called here
        raise AssertionError


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path / "share"))
    monkeypatch.setenv("JLBC_MACHINE_CONFIG_DIR", str(tmp_path / "machine"))


def _app(monkeypatch, probe_results):
    calls = []

    def probe():
        calls.append(1)
        return probe_results.pop(0)

    monkeypatch.setattr(main_mod, "_probe_provider", probe)
    app = create_app(ingest_worker=None)
    return app, calls


def test_startup_falls_to_stub_when_the_probe_fails(monkeypatch):
    app, calls = _app(monkeypatch, [None])
    assert app.state.provider.name == "stub"
    assert calls == [1]


def test_a_search_while_stub_reprobes_and_swaps(monkeypatch):
    app, calls = _app(monkeypatch, [None, FakeLance()])
    now = [1000.0]
    monkeypatch.setattr(main_mod.time, "monotonic", lambda: now[0])
    client = TestClient(app)
    now[0] += 60
    client.post("/api/search", json={"query": "x"})
    assert app.state.provider.name == "lance"
    assert len(calls) == 2


def test_reprobes_are_rate_limited(monkeypatch):
    app, calls = _app(monkeypatch, [None, None, None])
    now = [1000.0]
    monkeypatch.setattr(main_mod.time, "monotonic", lambda: now[0])
    client = TestClient(app)
    now[0] += 60
    client.post("/api/search", json={"query": "x"})
    client.post("/api/search", json={"query": "y"})  # inside the window
    assert len(calls) == 2
    now[0] += 60
    client.post("/api/search", json={"query": "z"})
    assert len(calls) == 3


def test_a_real_provider_never_reprobes(monkeypatch):
    app, calls = _app(monkeypatch, [FakeLance()])
    app.state.reprobe(force=True)
    assert len(calls) == 1


def test_saving_the_folder_swaps_at_once_and_resets_the_pipeline(monkeypatch, tmp_path):
    app, calls = _app(monkeypatch, [None, FakeLance()])
    monkeypatch.setattr("app.machine_config.validate_data_dir", lambda p: None)
    resets = []
    monkeypatch.setattr("retrieval.pipeline.reset_default_collaborators", lambda: resets.append(1))
    client = TestClient(app)
    r = client.post("/api/config/data-dir", json={"path": str(tmp_path / "share")})
    assert r.status_code == 200
    assert "restart_required" not in r.json()
    assert app.state.provider.name == "lance"
    assert resets == [1]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_app_reprobe.py -v`
Expected: FAIL (`_probe_provider` missing; `reprobe` missing; `restart_required` present).

- [ ] **Step 3: Implement**

`app/main.py` — add `import threading, time` at the top. Replace `_default_provider` with:

```python
REPROBE_INTERVAL_S = 30.0


def _probe_provider() -> SearchProvider | None:
    """The real provider if the corpus opens and has rows, else None.

    Prints WHY on stderr (the launcher's log) so a stub is never silent.
    create=False: a probe must not manufacture the folder it probes
    (spec principle 3, 2026-08-25).
    """
    try:
        from store.chunk_store import ChunkStore

        if ChunkStore(create=False).count("budget_chunks") > 0:
            return LanceSearchProvider()
        reason = "budget_chunks table is empty"
    except Exception as e:  # noqa: BLE001 — missing folder, unreadable share, engine error
        reason = f"{type(e).__name__}: {e}"
    print(
        f"jlbc-search: no usable corpus ({reason}) — serving stub search fixtures. "
        "Open the app: the start-up screen will ask for the shared folder.",
        file=sys.stderr,
    )
    return None


def _default_provider() -> SearchProvider:
    """Real corpus present -> real provider; else the fixture stub.

    Chosen at startup and RE-PROBED while stub (see _install_reprobe): a
    share that is down at 8 AM and back at 8:05 must not mean fake rows all
    day. A real provider never swaps back to stub — a share that goes away
    mid-session surfaces as the search route's honest 503, never as fake
    rows.
    """
    return _probe_provider() or StubSearchProvider()


def _install_reprobe(app: FastAPI) -> None:
    lock = threading.Lock()
    last = {"at": float("-inf")}

    def reprobe(*, force: bool = False) -> str:
        current = app.state.provider
        if current.name != "stub":
            return current.name
        with lock:
            now = time.monotonic()
            # Rate-limited: lancedb.connect on an unreachable UNC path can
            # block for the SMB timeout, and the search page must not pay
            # that per keystroke (spec S5).
            if not force and now - last["at"] < REPROBE_INTERVAL_S:
                return current.name
            last["at"] = now
            fresh = _probe_provider()
            if fresh is not None:
                app.state.provider = fresh
                from retrieval.pipeline import reset_default_collaborators

                # AI Mode caches its own ChunkStore; a pointer that changed
                # under it must not keep answering from the old folder.
                reset_default_collaborators()
            return app.state.provider.name

    app.state.reprobe = reprobe
```

In `create_app`, right after `app.state.provider = ...`, add `_install_reprobe(app)`.

Data-dir route:

```python
    @app.post("/api/config/data-dir")
    def set_data_dir_route(body: DataDirBody):
        """Repoint THIS machine at the shared folder (S18). No auth — the
        app is unusable when this fires. Takes effect NOW: the launcher
        reuses a running server, so 'reopen the app' would be a no-op."""
        from app.machine_config import set_data_dir, validate_data_dir

        problem = validate_data_dir(body.path)
        if problem:
            raise HTTPException(status_code=400, detail=problem)
        resolved = set_data_dir(body.path)
        app.state.reprobe(force=True)
        return {"path": str(resolved)}
```

`app/routes/search.py` — before `provider = request.app.state.provider`:

```python
    reprobe = getattr(request.app.state, "reprobe", None)
    if reprobe is not None:
        reprobe()
```

Also in `health_detail_route`, call `reprobe()` the same way before returning.

- [ ] **Step 4: Run**

Run: `uv run pytest tests/test_app_reprobe.py tests/test_search_route.py tests/test_health_ladder.py tests/test_app_server.py -v`
Expected: all pass. (`test_search_route` uses an injected stub; the reprobe hits `ChunkStore(create=False)` on a tmp dir, raises, stays stub.)

- [ ] **Step 5: Commit**

```bash
git add app/main.py app/routes/search.py tests/test_app_reprobe.py
git commit -m "app: re-probe the corpus while on the stub; repair takes effect in place

A share down at 8 AM meant fixture rows all day, and the repair screen's
'reopen the app' is a no-op because the launcher reuses the server.
Rate-limited to 30 s (SMB timeouts); a real provider never swaps back."
```

---

### Task 10: The repair screen and Budget Documents say the truth

**Files:**
- Modify: `webapp/src/api.ts:1093-1104` (`setDataDir` type), `webapp/src/pages/Repair.tsx:16-20, 72-100`, `webapp/src/HealthGate.test.tsx:165-200`, `webapp/src/pages/Search.tsx:86-90, 1019, 1158-1175`, `webapp/src/pages/Search.test.tsx`

**Interfaces:**
- Consumes: `POST /api/config/data-dir` → `{path}` (Task 9); `SearchResponse.provider` (already sent).

- [ ] **Step 1: Write the failing vitest specs**

In `webapp/src/HealthGate.test.tsx`, replace the `"says plainly that a restart is needed, and how"` spec with:

```tsx
  it("after saving, says to check again — never to restart", async () => {
    vi.spyOn(api, "healthDetail").mockResolvedValue(SHARE_GONE);
    vi.spyOn(api, "setDataDir").mockResolvedValue({ path: "\\\\newserver\\share" });
    render(
      <HealthGate>
        <App />
      </HealthGate>,
    );

    fireEvent.change(await screen.findByLabelText(/new location/i), {
      target: { value: "\\\\newserver\\share" },
    });
    fireEvent.click(screen.getByRole("button", { name: /use this folder/i }));

    const done = await screen.findByTestId("repair-done");
    // The launcher reuses a running server, so "reopen the app" did nothing
    // (2026-08-25). The server swaps in place; the button re-runs the ladder.
    expect(done).toHaveTextContent(/Saved/);
    expect(done).toHaveTextContent(/Check again/);
    expect(done).not.toHaveTextContent(/open JLBC Search again/i);
  });

  it("offers the folder box when the pointer file itself is the problem", async () => {
    const POINTER_BROKEN: api.HealthReport = {
      ok: false,
      rungs: [
        rung({ name: "server" }),
        rung({
          name: "machine_config",
          ok: false,
          detail: "This computer hasn't been told where the shared budget folder is.",
          fix: "Type the folder's location below — it's the one that contains the 'lancedb' folder.",
        }),
        rung({ name: "share", ok: null, detail: "Not checked — fix the problem above first." }),
        rung({ name: "corpus", ok: null, detail: "Not checked — fix the problem above first." }),
        rung({ name: "models", ok: null, detail: "Not checked — fix the problem above first." }),
      ],
      data_dir: null,
      can_repair: true,
    };
    vi.spyOn(api, "healthDetail").mockResolvedValue(POINTER_BROKEN);
    render(
      <HealthGate>
        <App />
      </HealthGate>,
    );
    await screen.findByTestId("repair-form");
    expect(screen.getByPlaceholderText(/jlbc-search-data/)).toBeInTheDocument();
  });
```

In `webapp/src/pages/Search.test.tsx`, find the existing content-search spec that mocks `api.search` (search for `spyOn(api, "search")`; if none exists, model the new spec on the nearest content-mode spec) and add:

```tsx
it("labels stub results as samples, like Fiscal Notes does", async () => {
  vi.spyOn(api, "search").mockResolvedValue({
    results: [],
    total: 0,
    provider: "stub",
    inferred_fiscal_years: [],
    inferred_doc_types: [],
    dropped_filters: [],
  });
  // ...render the page in contents mode with a query, as the neighbouring
  // spec does...
  expect(await screen.findByRole("note")).toHaveTextContent(/sample results, not a real search/);
});
```

- [ ] **Step 2: Run to verify failure**

Run: `bash -c 'cd ~/ask-the-budget-az-worktrees/windows-beta-fixes/webapp && npx vitest run src/HealthGate.test.tsx src/pages/Search.test.tsx'`
Expected: the three new/changed specs FAIL.

- [ ] **Step 3: Implement**

`api.ts`: `setDataDir` returns `Promise<{ path: string }>`.

`Repair.tsx`: replace the header comment's last paragraph with: *"A relocation takes effect at once: the server re-probes the folder when it is saved (2026-08-25). The 'Check again' button re-runs the ladder."* Placeholder → `"\\\\server\\share\\jlbc-search-data"`. Replace the `rep-done` block's two paragraphs with:

```tsx
                <p>
                  <strong>Saved.</strong> Click <strong>Check again</strong> below to
                  confirm the app can open that folder.
                </p>
```

`Search.tsx`: `ContentPhase`'s ready arm gains `provider: string`; at line ~1019 set `{ kind: "ready", results: res.results, provider: res.provider }`; in the results area (directly above the passages list rendered when `content.kind === "ready"` — find where `passageDocs` is mapped), add:

```tsx
{content.kind === "ready" && content.provider === "stub" && (
  <p className="fnnote fn-fixture" role="note">
    <strong>These are sample results, not a real search.</strong> This computer
    could not open the shared budget folder, so the same few example passages
    come back for every question. Open the app again from the Start Menu — the
    start-up screen will ask for the folder.
  </p>
)}
```

`webapp/src/styles/app.css:3161-3162` scopes the note under `.page-fiscal-notes`. Add, directly below those two rules, the same two declarations prefixed `.page-docs` (Budget Documents' page class — confirm with `grep -n 'className="page-docs' webapp/src/pages/Search.tsx`) so the note paints identically on both pages:

```css
.page-docs .fn-fixture{margin:0 0 12px;padding:10px 12px;border:1px solid var(--az-gold);border-radius:var(--r-sm);background:var(--az-gold-100);color:var(--ink-2);font-size:12px;line-height:1.5;}
.page-docs .fn-fixture strong{color:var(--az-gold-d);}
```

- [ ] **Step 4: Run**

Run: `bash -c 'cd ~/ask-the-budget-az-worktrees/windows-beta-fixes/webapp && npx tsc -b && npx vitest run'`
Expected: `tsc` 0 errors; vitest 1149 + 2 new − 0 = **1151** (one spec replaced, two added).

- [ ] **Step 5: Commit**

```bash
git add webapp/src
git commit -m "webapp: repair says 'check again' not 'restart'; stub results are labelled

The launcher reuses a running server, so the old 'reopen the app' advice
did nothing. Budget Documents gets the same sample-results note Fiscal
Notes has had — the laptop served fixtures all day with no label."
```

---

### Task 11: The locate cache evicts instead of crashing, and closes on shutdown

**Files:**
- Modify: `app/routes/pdf.py:473`, `app/main.py::_lifespan` (shutdown branch)
- Test: `tests/test_chunk_locate.py`

**Interfaces:**
- Produces: `app.routes.pdf.close_locate_cache() -> int` (documents closed).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_chunk_locate.py`:

```python
def test_the_ninth_document_evicts_the_first_and_closes_it():
    """`_locate_doc_cache` was a plain dict and `popitem(last=False)` is a
    TypeError on dict — the 9th distinct PDF 500'd the route and the first
    8 handles were never closed (on Windows that blocks re-ingest from
    overwriting the cached PDF)."""
    from app.routes import pdf as pdf_mod

    class FakeDoc:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    class FakeFitz:
        def open(self, path):
            return FakeDoc()

    pdf_mod.close_locate_cache()
    docs = [pdf_mod._locate_open_doc(FakeFitz(), Path(f"/x/{i}.pdf")) for i in range(9)]
    assert docs[0].closed is True
    assert all(not d.closed for d in docs[1:])
    assert pdf_mod.close_locate_cache() == 8
```

(Add `from pathlib import Path` to the test imports.)

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_chunk_locate.py -v -k ninth`
Expected: FAIL with `TypeError: dict.popitem() takes no keyword arguments` (or `AttributeError: close_locate_cache`).

- [ ] **Step 3: Implement**

`app/routes/pdf.py`:

```python
from collections import OrderedDict
...
_LOCATE_DOC_CACHE_MAX = 8
# OrderedDict, not dict: eviction uses popitem(last=False) (oldest first),
# which plain dict does not accept — found 2026-08-25, the 9th distinct
# document crashed the route and leaked the first eight handles.
_locate_doc_cache: "OrderedDict[str, Any]" = OrderedDict()


def close_locate_cache() -> int:
    """Close every cached PyMuPDF handle. Called at server shutdown — a
    handle left open on Windows blocks a re-ingest from replacing the file."""
    n = 0
    while _locate_doc_cache:
        _, doc = _locate_doc_cache.popitem(last=False)
        try:
            doc.close()
            n += 1
        except Exception:  # noqa: BLE001
            pass
    return n
```

`app/main.py::_lifespan`, in the shutdown section after the `yield` (both the early-return branches and the final one — put it in a `finally:` around the whole body so every path closes it):

```python
    try:
        ... existing body ...
    finally:
        from app.routes.pdf import close_locate_cache

        close_locate_cache()
```

- [ ] **Step 4: Run**

Run: `uv run pytest tests/test_chunk_locate.py tests/test_app_server.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add app/routes/pdf.py app/main.py tests/test_chunk_locate.py
git commit -m "pdf: locate cache is an OrderedDict; handles close at shutdown

dict.popitem(last=False) is a TypeError — the 9th document crashed
/locate and leaked eight PyMuPDF handles."
```

---

### Task 12: A transient read error is retried, not cached as empty

**Files:**
- Modify: `store/documents.py:137-160`, `harness/settings.py:487-501`, `app/search_provider.py:223-237`
- Test: `tests/test_store_documents.py`, `tests/test_harness_settings.py`, `tests/test_search_provider.py` (or wherever `LanceSearchProvider._info` is tested — grep `_doc_info`)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_store_documents.py`:

```python
def test_a_transient_read_error_is_retried_next_call(data_dir, monkeypatch):
    """A share blip during read_text cached {} under the GOOD file's stamp,
    so titles/links stayed blank until the next ingest changed the file."""
    _write(data_dir, {"d1": {"title": "Real title"}})
    real = Path.read_text
    calls = {"n": 0}

    def flaky(self, *a, **k):
        calls["n"] += 1
        if calls["n"] == 1 and self.name == "documents.json":
            raise PermissionError("sharing violation")
        return real(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", flaky)
    assert load_documents() == {}
    assert load_documents() == {"d1": {"title": "Real title"}}
```

(Add `from pathlib import Path` to the imports.)

Append to `tests/test_harness_settings.py` (same shape, against `load_settings()` and `settings.json` with an `admin_username` key; assert the second call sees it).

For `app/search_provider.py`, add to its test file: write a sidecar + the mockup index path patched to a temp file, make the first `load_documents` raise `OSError` via monkeypatch, assert `_info` returns `{"url": None, ...}` once and the real title on the next call.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_store_documents.py tests/test_harness_settings.py -v -k transient`
Expected: FAIL — second call still returns `{}` / defaults.

- [ ] **Step 3: Implement**

`store/documents.py` — in the `except (OSError, ValueError)` non-strict branch, split:

```python
        except OSError as err:
            # A share blip, a sharing violation, a half-replaced file: keep
            # whatever was cached and FORGET the stamp, so the next call
            # re-reads. Caching {} under the good stamp (the pre-2026-08-25
            # behaviour) blanked every title until the next ingest.
            print(f"store.documents: could not read {path} ({err}) — will retry.",
                  file=sys.stderr)
            _stamp = None
            return _cache
        except ValueError as err:
            print(... existing corrupt-file sentence ...)
            loaded = {}
```

`harness/settings.py` — same split in `load_settings`: on `OSError`, `_settings_stamp = None` and return `_settings_cache`; on `ValueError`, keep today's defaults-under-stamp.

`app/search_provider.py::_info` — in the `except Exception` branch, set `self._doc_info_sig = None` (already) **and** leave `self._doc_info` as it was if it is not `None` (only set `{}` when nothing was ever loaded):

```python
                if self._doc_info is None:
                    self._doc_info = {}
                self._doc_info_sig = None
```

- [ ] **Step 4: Run**

Run: `uv run pytest tests/test_store_documents.py tests/test_harness_settings.py tests/test_search_provider*.py tests/test_lance_provider.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add store/documents.py harness/settings.py app/search_provider.py tests/
git commit -m "caches: a transient read error is retried, not remembered as empty

documents.json, settings.json and the title join cached {} under the
good file's stamp after one OSError — blank titles and 'no API key'
until the next ingest."
```

---

### Task 13: One retry helper for the share's file-locking

**Files:**
- Create: `store/fs.py`, `tests/test_store_fs.py`
- Modify: `ingest/jobs.py:309-327` (delete `_replace_with_retry`, import from `store.fs`), `ingest/archive.py:47-69` (delete `unlink_with_retry`, re-export from `store.fs`), `store/config.py::write_documents_sidecar`, `ingest/fiscal_notes_refresh.py::write_directory`, `ingest/lock.py:401-405`

**Interfaces:**
- Produces: `store.fs.replace_with_retry(tmp: Path, path: Path, *, budget_s: float = 3.0) -> None` (raises on final failure, removes tmp); `store.fs.unlink_with_retry(path: Path, *, budget_s: float = 0.4) -> bool`.

- [ ] **Step 1: Write the failing tests**

`tests/test_store_fs.py`:

```python
"""Windows/SMB refuse to replace or delete a file another handle has open.
One helper, two callers' worth of retries (2026-08-25)."""
from __future__ import annotations

import os

import pytest

from store.fs import replace_with_retry, unlink_with_retry


def test_replace_retries_a_sharing_violation(tmp_path, monkeypatch):
    tmp, target = tmp_path / "a.tmp", tmp_path / "a.json"
    tmp.write_text("new", encoding="utf-8")
    target.write_text("old", encoding="utf-8")
    real = os.replace
    left = {"n": 2}

    def flaky(src, dst):
        if left["n"]:
            left["n"] -= 1
            raise PermissionError(5, "sharing violation")
        real(src, dst)

    monkeypatch.setattr(os, "replace", flaky)
    replace_with_retry(tmp, target, budget_s=1.0)
    assert target.read_text(encoding="utf-8") == "new"
    assert not tmp.exists()


def test_replace_gives_up_and_cleans_the_tmp(tmp_path, monkeypatch):
    tmp, target = tmp_path / "a.tmp", tmp_path / "a.json"
    tmp.write_text("new", encoding="utf-8")
    monkeypatch.setattr(os, "replace", lambda s, d: (_ for _ in ()).throw(PermissionError(5, "x")))
    with pytest.raises(PermissionError):
        replace_with_retry(tmp, target, budget_s=0.05)
    assert not tmp.exists()


def test_replace_does_not_retry_a_real_error(tmp_path, monkeypatch):
    tmp, target = tmp_path / "a.tmp", tmp_path / "a.json"
    tmp.write_text("new", encoding="utf-8")
    calls = []

    def boom(s, d):
        calls.append(1)
        raise FileNotFoundError(2, "gone")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(FileNotFoundError):
        replace_with_retry(tmp, target, budget_s=1.0)
    assert len(calls) == 1


def test_unlink_retries_then_reports(tmp_path, monkeypatch):
    p = tmp_path / "x"
    p.write_text("", encoding="utf-8")
    real = os.unlink
    left = {"n": 1}

    def flaky(path, *a, **k):
        if left["n"]:
            left["n"] -= 1
            raise PermissionError(32, "in use")
        real(path)

    monkeypatch.setattr(os, "unlink", flaky)
    assert unlink_with_retry(p, budget_s=1.0) is True
    assert not p.exists()
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_store_fs.py -v`
Expected: `ModuleNotFoundError: store.fs`.

- [ ] **Step 3: Implement**

`store/fs.py`:

```python
"""Filesystem operations that survive Windows and SMB sharing violations.

POSIX rename/unlink are unconditional. Windows (and SMB shares served to it)
refuse to replace or delete a file another handle has open, and antivirus
holds a freshly written file for a moment. Every writer of a file that other
PCs read live goes through here: job files (polled every couple of seconds by
~20 PCs), documents.json (4.5 MB, read on every search), the fiscal-note
directory, the ingest lock.

Lifted out of ingest/jobs.py and ingest/archive.py on 2026-08-25 because
store/config.py needed the same thing and must not import ingest/.
"""
from __future__ import annotations

import errno
import os
import time
from pathlib import Path

_SLEEP_S = 0.02
# WinError 5 = access denied, 32 = sharing violation. Both are transient here.
_TRANSIENT_WINERRORS = (5, 32)


def _transient(err: OSError) -> bool:
    if isinstance(err, PermissionError):
        return True
    return getattr(err, "winerror", None) in _TRANSIENT_WINERRORS or err.errno == errno.EACCES


def replace_with_retry(tmp: Path, path: Path, *, budget_s: float = 3.0) -> None:
    """os.replace, retried for up to `budget_s` on a transient lock.

    On final failure the tmp file is removed and the error re-raised — a
    stale `.tmp` beside a shared file reads as corruption to the next person.
    3 s by default because documents.json is multi-MB and a reader's handle
    over SMB is open for tens of milliseconds, not microseconds.
    """
    deadline = time.monotonic() + budget_s
    while True:
        try:
            os.replace(tmp, path)
            return
        except OSError as err:
            if not _transient(err) or time.monotonic() >= deadline:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
            time.sleep(_SLEEP_S)


def unlink_with_retry(path: Path, *, budget_s: float = 0.4) -> bool:
    """Remove a file another machine may have open. Never raises; False if it
    could not be removed within the budget (the caller decides whether that
    matters — for an archived job it does not, the new copy already exists)."""
    deadline = time.monotonic() + budget_s
    while True:
        try:
            path.unlink(missing_ok=True)
            return True
        except OSError as err:
            if not _transient(err) or time.monotonic() >= deadline:
                return False
            time.sleep(_SLEEP_S)
```

`ingest/archive.py`: delete `unlink_with_retry`, add `from store.fs import unlink_with_retry  # noqa: F401 — re-exported for ingest/jobs.py` and keep the docstring's WHY as a comment. `ingest/jobs.py`: delete `_replace_with_retry`; `from store.fs import replace_with_retry`; call `replace_with_retry(tmp, path, budget_s=0.4)` at the old site (keeps the 400 ms budget for small job files).

`store/config.py::write_documents_sidecar`: replace `os.replace(tmp, path)` with `replace_with_retry(tmp, path)` (import at top: `from store.fs import replace_with_retry`). `ingest/fiscal_notes_refresh.py::write_directory`: same.

`ingest/lock.py`:

```python
    def _unlink_quietly(self) -> None:
        # A PC reading the lockfile at the instant of release used to escape
        # as PermissionError out of __exit__ — failing a job AFTER a good
        # corpus write and leaving a frozen-heartbeat lock for 120 s.
        from store.fs import unlink_with_retry

        unlink_with_retry(self.path)
```

- [ ] **Step 4: Run**

Run: `uv run pytest tests/test_store_fs.py tests/test_ingest_jobs*.py tests/test_ingest_lock.py tests/test_ingest_lock_heartbeat.py tests/test_archive*.py tests/test_store_config.py tests/test_fiscal_notes_refresh*.py -v`
Expected: all pass. Then `uv run pytest -q -x` for the whole suite.

- [ ] **Step 5: Commit**

```bash
git add store/fs.py tests/test_store_fs.py ingest/jobs.py ingest/archive.py ingest/lock.py store/config.py ingest/fiscal_notes_refresh.py
git commit -m "store/fs: one retry helper; documents.json, the note directory and the lock use it

Windows refuses os.replace/unlink while any PC has the file open. The
sidecar write sat AFTER the LanceDB commit with no retry, so a collision
failed the job over a document that was already searchable."
```

---

### Task 14: Launcher and installer

**Files:**
- Modify: `packaging/launcher.pyw` (whole file — small, rewrite the affected functions), `packaging/Install-JLBC-Search.cmd` (whole file)
- Create: `tests/test_launcher.py`

**Interfaces:**
- Produces (launcher, module-level so the test can exec them): `PREFERRED_PORT = 9300`, `HEALTH_TIMEOUT_S = 180`, `STATE_DIR`, `MINERU_CONFIG = STATE_DIR / "mineru.json"`, `write_mineru_config(install_dir: Path, target: Path) -> None`, `health_json(port, timeout=1.5) -> dict | None`, `try_bind(port) -> socket | None`.
- Produces (installer): `INSTALL_DEFAULT=%LOCALAPPDATA%\JLBC-Search\program`; calls `--default-ingest-enabled false`.

- [ ] **Step 1: Write the failing tests**

`tests/test_launcher.py`:

```python
"""packaging/launcher.pyw — the pure parts, executed the way test_diag_tool.py
used to (a .pyw is not importable by spec)."""
from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "packaging" / "launcher.pyw"


@pytest.fixture
def launcher(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "la"))
    ns: dict = {"__name__": "launcher_under_test", "__file__": str(SRC)}
    exec(compile(SRC.read_text(encoding="utf-8"), str(SRC), "exec"), ns)
    return ns


def test_state_dir_is_the_parent_of_a_program_subfolder(launcher, tmp_path):
    assert launcher["STATE_DIR"] == tmp_path / "la" / "JLBC-Search"


def test_mineru_config_is_written_to_state_from_the_install_dir(launcher, tmp_path):
    target = tmp_path / "mineru.json"
    launcher["write_mineru_config"](Path("C:/x/program"), target)
    cfg = json.loads(target.read_text(encoding="utf-8"))
    assert cfg["models-dir"]["pipeline"] == str(Path("C:/x/program") / "models" / "mineru")
    assert cfg["model-source"] == "local"


def test_the_preferred_port_is_9300_and_a_held_port_is_reported(launcher):
    assert launcher["PREFERRED_PORT"] == 9300
    holder = socket.socket()
    holder.bind(("127.0.0.1", 0))
    port = holder.getsockname()[1]
    try:
        assert launcher["try_bind"](port) is None
    finally:
        holder.close()
    s = launcher["try_bind"](0)
    assert s is not None
    s.close()


def test_health_json_rejects_a_foreign_service(launcher, monkeypatch):
    import urllib.request

    class R:
        status = 200

        def read(self):
            return b"<html>not us</html>"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: R())
    assert launcher["health_json"](1) is None


def test_timeout_is_three_minutes(launcher):
    assert launcher["HEALTH_TIMEOUT_S"] == 180
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_launcher.py -v`
Expected: FAIL (`KeyError: write_mineru_config`, etc.).

- [ ] **Step 3: Rewrite the launcher's affected parts**

Constants:

```python
STATE_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "JLBC-Search"
RUNNING_FILE = STATE_DIR / "running.json"
LOG_DIR = STATE_DIR / "logs"
MINERU_CONFIG = STATE_DIR / "mineru.json"

# Try this first (every document names it; bookmarks and restored tabs keep
# working across restarts). The BIND is the single-instance lock: if 9300 is
# held, the other holder is either us (poll it) or a stranger (fall back).
PREFERRED_PORT = 9300
# 180 s, not 60: a cold laptop imports ~36k files under Defender, then opens
# LanceDB over the share. At 60 s the box said "failed" while the non-daemon
# server thread finished starting a minute later — with no browser window.
HEALTH_TIMEOUT_S = 180
```

`prepare_environment`: replace the `MINERU_TOOLS_CONFIG_JSON` line with:

```python
    # Written HERE, every start, from the real install dir — the installer's
    # rewrite step was silent (2>nul) and a moved folder stranded MinerU on a
    # stale absolute path. Lives in STATE_DIR so program files stay read-only.
    write_mineru_config(INSTALL_DIR, MINERU_CONFIG)
    os.environ["MINERU_MODEL_SOURCE"] = "local"
    os.environ["MINERU_TOOLS_CONFIG_JSON"] = str(MINERU_CONFIG)
```

New functions (module level, above `main`):

```python
def write_mineru_config(install_dir: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({
        "models-dir": {"pipeline": str(install_dir / "models" / "mineru"), "vlm": ""},
        "model-source": "local",
        "config_version": "1.3.2",
    }, indent=2), encoding="utf-8")


def try_bind(port: int) -> socket.socket | None:
    """A bound-but-not-listening socket on `port`, or None if it is held."""
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", port))
        return s
    except OSError:
        s.close()
        return None


def health_json(port: int, timeout: float = 1.5) -> dict | None:
    """/health's body if it is OURS ({"ok": true, ...}), else None."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=timeout) as r:
            if r.status != 200:
                return None
            body = json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None
    return body if isinstance(body, dict) and body.get("ok") is True else None
```

`main()` becomes:

```python
def main() -> int:
    try:
        return _main()
    except Exception as exc:  # noqa: BLE001 — a launcher must never die silently
        message_box(f"{APP_NAME} could not start.\n\n{type(exc).__name__}: {exc}\n\n"
                    f"Send the newest file in\n{LOG_DIR}\nto whoever supports this app.")
        return 1


def _main() -> int:
    prepare_environment()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"server-{datetime.now():%Y-%m-%d}.log"

    # Reuse a running instance before doing anything expensive (S8).
    body = health_json(PREFERRED_PORT)
    if body is not None:
        open_window(PREFERRED_PORT)
        return 0
    sock = try_bind(PREFERRED_PORT)
    if sock is None:
        # Held but not answering: a sibling launcher is mid-start. Wait for it.
        deadline = time.monotonic() + HEALTH_TIMEOUT_S
        while time.monotonic() < deadline:
            body = health_json(PREFERRED_PORT)
            if body is not None:
                open_window(PREFERRED_PORT)
                return 0
            time.sleep(0.5)
        # Still nothing: a stranger owns 9300. Fall back to any free port.
        port = free_port()
    else:
        sock.close()
        port = PREFERRED_PORT
    record_port(port)
    ... (unchanged: import uvicorn/create_app with the message-box-on-failure,
         log redirection, server thread) ...
    deadline = time.monotonic() + HEALTH_TIMEOUT_S
    while time.monotonic() < deadline:
        if server_error:
            break
        body = health_json(port)
        if body is not None:
            print(f"=== serving on {port}; search provider: {body.get('provider')} ===")
            open_window(port)
            t.join()
            return 0
        time.sleep(0.4)

    message_box(
        f"{APP_NAME} is still starting.\n\nWait a minute, then click the icon "
        f"again. If it still does not open, send this file:\n{log_path}\n\n"
        f"to whoever supports this app."
    )
    return 1
```

The pre-log `write_text` in the import-failure branch gains `encoding="utf-8"`. Delete the old `health_ok` and `recorded_port` (nothing else uses them; `record_port` stays for the installer). Update the module docstring's numbered behaviour list to match (port 9300 first; the bind as the lock; 180 s; "still starting").

- [ ] **Step 4: Run the launcher tests**

Run: `uv run pytest tests/test_launcher.py -v`
Expected: 5 passed.

- [ ] **Step 5: Rewrite `Install-JLBC-Search.cmd`**

Keep the header, USB-dir detection and the zip search. Replace from the Q1 block to the end with the following (CRLF — Task 1's attribute handles it on commit; write the file with `\r\n` explicitly if editing via Python):

```bat
rem --- Q1: where to install the program --------------------------------------
set "ROOT_DIR=%LOCALAPPDATA%\JLBC-Search"
set "INSTALL_DEFAULT=%ROOT_DIR%\program"
echo   Where should the program live?
echo     Press Enter for the recommended spot:
echo       %INSTALL_DEFAULT%
echo     (or drag a different empty folder here, then Enter)
set "INSTALL_DIR="
set /p "INSTALL_DIR=  Install folder [%INSTALL_DEFAULT%]: "
if not defined INSTALL_DIR set "INSTALL_DIR=%INSTALL_DEFAULT%"
set "INSTALL_DIR=%INSTALL_DIR:"=%"
if "%INSTALL_DIR:~-1%"=="\" set "INSTALL_DIR=%INSTALL_DIR:~0,-1%"
echo   Installing to: %INSTALL_DIR%
echo.

rem --- Q2: where is the shared data (the corpus)? -----------------------------
echo   Where is the shared budget-data folder?
echo     This is the folder that has the "lancedb" folder inside it
echo     (the search index). You can drag the folder here, then press Enter.
echo     Press Enter alone to decide later - the app asks on first run.
set "DATA_DIR="
set /p "DATA_DIR=  Shared data folder (Enter to skip): "
set "DATA_DIR=%DATA_DIR:"=%"
if defined DATA_DIR if "%DATA_DIR:~-1%"=="\" set "DATA_DIR=%DATA_DIR:~0,-1%"
echo.

rem --- stop a running copy before touching its files ---------------------------
rem  Windows locks python312.dll and every .pyd while pythonw.exe runs, so an
rem  upgrade over a live server fails halfway and leaves a mixed-version tree.
rem  running.json (written by launcher.pyw) carries the pid; an installed
rem  Python is always still on disk when it exists. The image name is checked
rem  so a reused pid never kills a stranger.
set "RUNNING=%ROOT_DIR%\running.json"
if exist "%RUNNING%" (
    set "OLDPY="
    if exist "%INSTALL_DIR%\python\python.exe" set "OLDPY=%INSTALL_DIR%\python\python.exe"
    if exist "%ROOT_DIR%\python\python.exe" set "OLDPY=%ROOT_DIR%\python\python.exe"
    if defined OLDPY (
        for /f %%p in ('"!OLDPY!" -c "import json,sys;print(json.load(open(sys.argv[1],encoding='utf-8')).get('pid',''))" "%RUNNING%"') do set "OLDPID=%%p"
    )
    if defined OLDPID (
        tasklist /FI "PID eq !OLDPID!" /FI "IMAGENAME eq pythonw.exe" | find /I "pythonw.exe" >nul
        if not errorlevel 1 (
            echo   Stopping the running copy of JLBC Search...
            taskkill /PID !OLDPID! /T /F >nul 2>&1
            timeout /t 2 /nobreak >nul
        )
    )
    del /q "%RUNNING%" >nul 2>&1
)

rem --- one-time cleanup of the 0.9.1 layout (program files at the root) -------
if exist "%ROOT_DIR%\python\pythonw.exe" (
    echo   Removing the old program files from %ROOT_DIR% ...
    for %%d in (python site-packages jre models app harness store retrieval chunking citation identity memo ingest webapp data samples scripts funds primer) do (
        if exist "%ROOT_DIR%\%%d" rmdir /s /q "%ROOT_DIR%\%%d"
    )
    for %%f in (launcher.pyw install.cmd QUICKSTART.md VERSION MANIFEST.json) do (
        if exist "%ROOT_DIR%\%%f" del /q "%ROOT_DIR%\%%f"
    )
)

rem --- replace the program folder ---------------------------------------------
rem  Deleted ONLY when it is recognisably ours (launcher.pyw + VERSION inside);
rem  a typed folder that is something else is never touched.
if exist "%INSTALL_DIR%\launcher.pyw" if exist "%INSTALL_DIR%\VERSION" (
    echo   Removing the previous version...
    rmdir /s /q "%INSTALL_DIR%"
)
mkdir "%INSTALL_DIR%" 2>nul
echo   Extracting into the install folder (36,000 files; please wait)...
tar -xf "%ZIP%" -C "%INSTALL_DIR%" --strip-components=1
if errorlevel 1 (
    echo   ERROR: extraction failed. Copy the zip to your Desktop and run this
    echo   script from there instead of off the USB drive.
    pause
    exit /b 1
)

rem --- sanity: refuse to configure a bundle that did not unzip completely ----
if not exist "%INSTALL_DIR%\python\pythonw.exe"      goto :incomplete
if not exist "%INSTALL_DIR%\launcher.pyw"            goto :incomplete
if not exist "%INSTALL_DIR%\webapp\dist\index.html"  goto :incomplete
if not exist "%INSTALL_DIR%\VERSION"                 goto :incomplete
echo   Extracted OK.
echo.

rem --- record the shared data folder ------------------------------------------
if not defined DATA_DIR goto :skip_data
"%INSTALL_DIR%\python\python.exe" -m app.machine_config --set-data-dir "%DATA_DIR%"
if errorlevel 1 (
    echo   WARNING: could not record the shared folder. You can set it from
    echo            inside the app the first time you run it.
) else (
    echo   Recorded shared data folder: %DATA_DIR%
)
:skip_data

rem --- ingest default: recorded only if this PC has never chosen ---------------
"%INSTALL_DIR%\python\python.exe" -m app.machine_config --default-ingest-enabled false >nul 2>&1

rem --- shortcuts ---------------------------------------------------------------
set "SM_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs"
call :mkshortcut "%SM_DIR%\JLBC Search.lnk"
call :mkshortcut "%USERPROFILE%\Desktop\JLBC Search.lnk"

echo.
echo   ============================================================
echo    Setup complete.
echo   ============================================================
echo.
echo    Start it from:  the Start Menu, or the JLBC Search icon on
echo                    your Desktop.
if defined DATA_DIR echo    Data folder:    %DATA_DIR%
echo    Log files:      %ROOT_DIR%\logs
echo.
echo    If it will not start, send the newest file in that logs
echo    folder to whoever supports the app.
echo.
pause
exit /b 0

:mkshortcut
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%~1');" ^
  "$s.TargetPath='%INSTALL_DIR%\python\pythonw.exe';" ^
  "$s.Arguments='\"%INSTALL_DIR%\launcher.pyw\"';" ^
  "$s.WorkingDirectory='%INSTALL_DIR%';" ^
  "$s.IconLocation='%INSTALL_DIR%\python\pythonw.exe,0';" ^
  "$s.Description='JLBC Search';" ^
  "$s.Save()" >nul 2>&1
if errorlevel 1 (
    echo   WARNING: could not create the shortcut at %~1
) else (
    echo   Created shortcut: %~1
)
exit /b 0

:incomplete
echo.
echo   This install is missing files that should have been in the zip.
echo   The most likely cause is that the zip did not finish extracting.
echo   Delete the "program" folder inside %ROOT_DIR% (only that one),
echo   then run this script again.
echo.
pause
exit /b 1
```

Update the header comment (lines 4–12) to describe the new steps and remove the sentence about reusing `install.cmd`. Remove the "make MinerU's model path absolute" block entirely.

- [ ] **Step 6: Run**

Run: `uv run pytest tests/test_cmd_line_endings.py tests/test_launcher.py tests/test_packaging_manifest.py -v`
Expected: all pass. Then `bash -c 'cd ~/ask-the-budget-az-worktrees/windows-beta-fixes && git ls-files --eol packaging/Install-JLBC-Search.cmd'` → `i/crlf w/crlf`.

- [ ] **Step 7: Commit**

```bash
git add packaging/launcher.pyw packaging/Install-JLBC-Search.cmd tests/test_launcher.py
git commit -m "packaging: program\\ subfolder, safe upgrades, port 9300 as the instance lock

Installer: stops the running server (pid + image-name check), deletes the
old program folder only when it is recognisably ours, cleans the 0.9.1
root layout once, records the ingest default without overriding a choice.
Launcher: 9300 first, bind as the lock, 180 s, top-level catch, mineru.json
written to the state dir every start, provider logged at start."
```

---

### Task 15: Docs, then the rendered-UI checkpoint (STOP for Destin)

**Files:**
- Modify: `docs/QUICKSTART.md`, `README.md`, `packaging/README.md`

- [ ] **Step 1: QUICKSTART**

Section 1: delete "The manual way" paragraph. Change the recommended install spot to `%LOCALAPPDATA%\JLBC-Search\program`. Section 2: add after the first paragraph: *"Always start it from the icon. If your browser reopens an old tab and it says the site can't be reached, click the icon — it opens the right address."* "Where things are" table: `The app` → `%LOCALAPPDATA%\JLBC-Search\program`; add rows `Your saved AI chats | %LOCALAPPDATA%\JLBC-Search\conversations — stays on this PC; not backed up` and `Memos you generate | %LOCALAPPDATA%\JLBC-Search\documents (and a copy in your Downloads)`. "If it will not start" item 1: replace with *"If a box says it is still starting, wait a minute and click the icon again."*

- [ ] **Step 2: README banner**

First line of `README.md`: `> **Developer notes.** If you are an analyst installing JLBC Search, read `docs/QUICKSTART.md` instead — everything below assumes a development checkout.`

- [ ] **Step 3: packaging/README**

Layout paragraph: state the `program\` subfolder and that `%LOCALAPPDATA%\JLBC-Search\` holds only per-machine data. Remove any `diag` mention (grep says none remain after Task 3 — confirm).

- [ ] **Step 4: Commit**

```bash
git add docs/QUICKSTART.md README.md packaging/README.md
git commit -m "docs: quickstart for the program\\ layout; README marked developer-only"
```

- [ ] **Step 5: CHECKPOINT — render the four screens for Destin. Do not proceed past this step without his reply.**

Build the SPA and start a dev server against each broken state, screenshot, and send the four PNGs:

```bash
bash -c 'cd ~/ask-the-budget-az-worktrees/windows-beta-fixes/webapp && npm run build'
# 1. corrupt pointer: JLBC_MACHINE_CONFIG_DIR=/tmp/mc1 with machine.json = "{ not json"
# 2. bundle, no pointer: touch <worktree>/VERSION (delete it afterwards!), JLBC_MACHINE_CONFIG_DIR=/tmp/mc2 (empty), JLBC_DATA_DIR unset
# 3. empty index: JLBC_DATA_DIR=/tmp/share3 with an empty lancedb/ inside
# 4. stub Budget Documents: JLBC_DATA_DIR=/tmp/share4 (nothing inside) — search "ahcccs" in contents mode
# each: uv run uvicorn app.main:create_app --factory --port 93NN, then a headless-Chrome screenshot of / (1–3) or /search?q=ahcccs&in=contents (4)
```

Send the screenshots with `SendUserFile` and the sentence: *"These are the four new screens. Say 'ok' or tell me which words to change."* Any wording change lands as a small commit on this branch. **Remove the temporary `VERSION` file before continuing.**

---

### Task 16: Gates, eval, STATUS

**Files:**
- Modify: `STATUS.md` (phase table row for the diag tool; new row + section for this work)
- Create: `eval/results/<stamp>-<sha>.{json,md}`

- [ ] **Step 1: Full suites**

```bash
bash -c 'cd ~/ask-the-budget-az-worktrees/windows-beta-fixes && uv run pytest -q 2>&1 | tail -3'
bash -c 'cd ~/ask-the-budget-az-worktrees/windows-beta-fixes/webapp && npx tsc -b && npx vitest run 2>&1 | tail -4 && npm run build 2>&1 | tail -2'
```

Expected: pytest ≥ 3342 + new − deleted (Task 3 removed `test_diag_tool.py`; count it: `git show 7329973:tests/test_diag_tool.py | grep -c "^def test_"`), 5 skipped; vitest 1151; tsc 0; build 0. **Write the real numbers down** — they go in STATUS.

- [ ] **Step 2: Eval (owed — `ingest/mineru_runner.py` changed)**

```bash
bash -c 'cd ~/ask-the-budget-az-worktrees/windows-beta-fixes && JLBC_DATA_DIR=/home/destin/YouCoded/Projects/ask-the-budget-az-dev/data/insight-data uv run python -m eval.run_eval 2>&1 | tail -8'
```

Expected: recall@5 85.71%, @15 97.62%, @20 100.00%, refusal precision 60% — identical to `eval/results/2026-08-18T1813Z-1423734`. If any number moves, STOP and investigate: nothing on the retrieval path changed and a moved number means something is wrong with the change or the corpus. `git add eval/results/<new files>`.

- [ ] **Step 3: STATUS.md**

Phase table: change the "One-click diagnostic" row's status to `⬛ **Deleted 2026-08-25** (spec D1)` and its note to one sentence. Add a row `**Windows beta fixes** | ✅ **Shipped 2026-08-25**, browser checkpoint passed, NOT yet run on Windows | ...`. Add a section after "Product rename" with: what shipped (one line per spec section), D1–D4 and §S, the bundle-marker rule and the packaged/dev split, the measured gate numbers, the eval result, what remains unwitnessed (everything Windows — copy §5's acceptance list), and §W as "next batch" by reference to the spec.

- [ ] **Step 4: Commit**

```bash
git add STATUS.md eval/results/
git commit -m "status: windows beta fixes shipped; eval unchanged; diag tool row closed"
```

---

### Task 17: Merge and push

- [ ] **Step 1: Sync and re-gate**

```bash
bash -c 'cd ~/ask-the-budget-az-worktrees/windows-beta-fixes && git fetch origin && git merge origin/master'
```

Resolve conflicts if any (likely none — master is idle on these files; check `git log 7329973..origin/master --stat | grep -E "app/(health|main|machine_config)|store/config|packaging/"`). Re-run Step 1 of Task 16 on the merged tree.

- [ ] **Step 2: Merge to master and push**

```bash
bash -c 'cd /home/destin/YouCoded/Projects/ask-the-budget-az-dev && git pull -q origin master && git merge --no-ff windows-beta-fixes -m "merge: windows beta fixes — bundle-breakers, launch/repair chain, three app bugs" && git push origin master'
```

- [ ] **Step 3: Clean up**

```bash
bash -c 'cd /home/destin/YouCoded/Projects/ask-the-budget-az-dev && git worktree remove ~/ask-the-budget-az-worktrees/windows-beta-fixes && git branch -d windows-beta-fixes'
```

- [ ] **Step 4: Tell Destin what to do next**

The acceptance is on his laptop (spec §5): rebuild the bundle (`uv run python packaging/build_bundle.py --version 0.9.2`), copy `dist/JLBC-Search-0.9.2.zip` and `dist/Install-JLBC-Search.cmd` to the USB, run the installer, and walk the §5 list. Report the results in STATUS.
