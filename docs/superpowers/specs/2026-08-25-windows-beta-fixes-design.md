# Windows beta fixes — design

**Date:** 2026-08-25 · **Status:** approved by Destin 2026-08-25 · **Branch:** `windows-beta-fixes`

**Supersedes:** the discarded `2026-08-21-windows-repair-robustness` branch and
`PROMPT-windows-launch-repair.md` (both deleted 2026-08-25). **Builds on:**
`docs/superpowers/investigations/2026-08-25-windows-launch-failure.md` (the laptop
incident) and the 2026-08-25 five-lane Windows portability audit summarised in §W
below.

## Why

The app has only ever been tested on a Linux dev box against a local corpus. The one
real Windows beta install (2026-08-18) failed three ways in fourteen minutes and
served fake search rows the whole time. A read-only audit of the bundle and the
runtime then found that even with a correct pointer the beta bundle could not have
worked: MinerU cannot be launched, and Budget Documents loses every title and link.

**Principle:** anything that can go wrong with the *pointer or the share* must be
fixable on the screen the user is already looking at; and the bundle is checked
against what the code actually reads, never against a list someone typed.

## Scope

Decisions D1–D4 were Destin's, 2026-08-25:

- **D1** Delete the USB diagnostic tool (`packaging/diag/`, `RUN-DIAGNOSTIC.cmd`).
  The in-app repair screen is the one recovery path.
- **D2** Program files move to `%LOCALAPPDATA%\JLBC-Search\app\`; per-person data
  stays at `%LOCALAPPDATA%\JLBC-Search\`.
- **D3** The launcher tries port 9300 first, random only if taken.
- **D4** This batch = Tier 1 (bundle-breakers) + the launch/repair chain + Tier 2
  (three app bugs) + the one-line share-locking retries. Tier 3/4 is recorded in
  STATUS.md as the next batch (§W).

One worktree, one branch, one merge — the file sets are mostly disjoint but this repo
has recorded three cross-branch defects from parallel lanes, and the batch is ~12
tasks.

---

## 1. The bundle and installer (`packaging/`)

### 1.1 MinerU launches (P1)

`ingest/mineru_runner.py::resolve_mineru_exe` gains a rung between the
`JLBC_MINERU_EXE` override and `shutil.which("mineru")`:

> if `importlib.util.find_spec("mineru")` succeeds → `[sys.executable, "-m", "mineru.cli.client"]`

`mineru.cli.client:main` is what the `mineru` console script wraps
(`mineru-3.1.6.dist-info/entry_points.txt`). The `uv run mineru` rung stays LAST, for
dev boxes without the package importable. The function returns an argv **list** and
every caller already treats it as one.

`_stream` passes `creationflags=subprocess.CREATE_NO_WINDOW` on `os.name == "nt"` so a
console-subsystem child spawned from `pythonw.exe` does not open a black window on
the desktop. (The OpenDataLoader Java runner hardcodes its own `Popen` and cannot
take the flag — recorded in §W as next-batch.)

`packaging/build_bundle.py` drops `site-packages/bin/` from the staged tree: 62
POSIX shell scripts whose shebang is the dev machine's venv path.

**Test:** `resolve_mineru_exe()` with `JLBC_MINERU_EXE` unset, `shutil.which`
monkeypatched to `None`, and `mineru` importable returns
`[sys.executable, "-m", "mineru.cli.client"]`; with `find_spec` → `None` it returns
`["uv", "run", "mineru"]`. A manifest test asserts no `site-packages/bin/` entry.

### 1.2 Titles and links come back (P2)

`webapp/reference/assets/search/index-lite.js` ships. `EXCLUDED_PREFIXES` keeps
`webapp/reference/` and an explicit `INCLUDED_FILES` allowlist re-admits that one
path; the reason is stated at the constant (the search provider reads it at
runtime for the meta line and the exact-URL join).

**Test:** `tests/test_packaging_manifest.py` imports
`app.search_provider.MOCKUP_INDEX_PATH`, makes it repo-relative, and asserts it is in
`source_files()`. Reader and bundle cannot drift apart silently again.

### 1.3 Installers stop flashing (P3)

A repo-root `.gitattributes` with `*.cmd text eol=crlf` and a renormalising commit.
`build_bundle.py::step_launcher` (or wherever `.cmd` files are copied) asserts
`b"\r\n" in data` and raises otherwise. Pinned by a test that runs the assertion
over every `.cmd` in `packaging/`.

### 1.4 Layout: `app\` subfolder, upgrades that replace it (P4, D2)

| | before | after |
|---|---|---|
| program | `%LOCALAPPDATA%\JLBC-Search\` | `%LOCALAPPDATA%\JLBC-Search\app\` |
| pointer, chats, memos, logs, `running.json` | `%LOCALAPPDATA%\JLBC-Search\` | unchanged |
| upgrade | extract over a running install | stop the server, delete `app\`, extract |

`Install-JLBC-Search.cmd`:

- `INSTALL_DEFAULT=%LOCALAPPDATA%\JLBC-Search\app`. A typed install folder is
  stripped of a trailing `\` (the bug `install.cmd:16` already guarded against).
- Before extracting: if `%LOCALAPPDATA%\JLBC-Search\running.json` exists, read its
  `pid` (a `python -c` one-liner using the bundle being *replaced* is unavailable
  before extraction — use `findstr`/`for /f` on the JSON line) and
  `taskkill /PID <pid> /T /F`; then `rmdir /s /q "%INSTALL_DIR%"`.
- The `:incomplete` text says *"delete the `app` folder inside JLBC-Search"*, never
  the parent.
- The `mineru.json` rewrite step is removed (§1.6).
- `--set-ingest-enabled false` becomes `--default-ingest-enabled false` (§1.5).

`install.cmd` (the unzip-it-yourself path) is **deleted**. Two installers is how the
LF bug reached both; the one-click installer is the only supported path.
`docs/QUICKSTART.md`'s manual-unzip section is replaced by "run
`Install-JLBC-Search.cmd` from the USB".

`launcher.pyw`: `INSTALL_DIR` is still `Path(__file__).parent` (now `…\app`);
`STATE_DIR` stays `%LOCALAPPDATA%\JLBC-Search` — per-machine data is independent
of where the program lives, and the docstring that claimed the two were separate
becomes true.

*User-visible consequence:* the three beta laptops reinstall once; nothing personal
is lost because the installer never touches the parent folder.

### 1.5 Ingest survives an upgrade (P5)

`app/machine_config.py` CLI gains `--default-ingest-enabled {true,false}`: writes
the key only when `machine.json` has no `ingest_enabled` key. The installer calls
that instead of `--set-ingest-enabled false`. **Test:** an existing `true` survives
the default call; an absent key becomes `false`.

### 1.6 `mineru.json` is the launcher's job

`launcher.pyw::prepare_environment` writes `models/mineru.json` from `INSTALL_DIR`
on every start (`models-dir.pipeline = <INSTALL_DIR>/models/mineru`,
`model-source: local`). `build_bundle.py` still ships the `__INSTALL_DIR__`
template so the manifest test is unchanged; the launcher overwrites it. A moved or
renamed folder can no longer strand MinerU on a stale absolute path.

### 1.7 Launcher behaviour (D3 + audit)

- **Port:** try `9300`; if the bind fails, a free port, and the log line says so.
- **Second click during startup:** `running.json` gains `"starting": true` and the
  pid. A launcher that finds a recorded port not yet answering `/health` checks the
  pid is alive (`ctypes` `OpenProcess`, or `tasklist`); if alive it polls `/health`
  for the timeout and opens the window — it never starts a second server. A dead pid
  is treated as no server.
- **Timeout:** `HEALTH_TIMEOUT_S = 180`. The box says *"JLBC Search is still
  starting. Wait a minute, then click the icon again. If it still does not open,
  send this file: …"*.
- **Nothing dies silently:** `main()` runs inside a top-level `try/except` that calls
  `message_box` with the exception's one-line form; the pre-log `write_text` passes
  `encoding="utf-8"`.
- `/health` is accepted only when its JSON body carries `"ok": true` — an arbitrary
  service on the port no longer counts as us.

### 1.8 Deletions and cruft (D1)

Delete `packaging/diag/` and `packaging/RUN-DIAGNOSTIC.cmd`, `tests/test_diag_tool.py`,
and the STATUS.md row's claim that the tool ships (the row is rewritten as
"deleted 2026-08-25, D1"). `EXCLUDED_PREFIXES` gains `mockups/`; `EXCLUDED_NAMES`
gains every `PROMPT-*.md` (matched by prefix in the filter, not listed by name).

---

## 2. The launch/repair chain

### 2.1 The pointer is normalised before it is checked or stored

`app/machine_config.py::normalize_data_dir(path) -> str`:

1. `str(path).strip()`, strip surrounding `"` and `'`, `.rstrip("\\/")`.
2. On `os.name == "nt"`: replace every `/` with `\`; a result beginning with a
   single `\` followed by a non-`\` (the `/host/share` form) gets a second leading
   `\`.
3. Elsewhere: unchanged beyond step 1.

| input (nt) | output |
|---|---|
| `//bcpool/JLBCSearch` | `\\bcpool\JLBCSearch` |
| `/bcpool/JLBCSearch` | `\\bcpool\JLBCSearch` |
| `E:/JLBCSearch/` | `E:\JLBCSearch` |
| `"E:\JLBCSearch\"` | `E:\JLBCSearch` |
| `\\bcpool\JLBCSearch` | unchanged |

`validate_data_dir` and `set_data_dir` both go through it first; what lands in
`machine.json` is the normalised form. The WHY comment cites the investigation doc.

**Tests:** the table above, run with `os.name` monkeypatched to `"nt"` so the
Windows branch is exercised on Linux. The six assertions in
`tests/test_machine_ingest_enabled.py` and `tests/test_pdf_route.py` that pin the
literal `//server/share/JLBC-Search-Data` are re-pointed to a form that survives
normalisation on Linux (they run with `os.name == "posix"`, so `//server/share/…`
is unchanged there — the tests keep passing; a comment records that on Windows the
stored form is `\\server\share\…`).

### 2.2 Validation opens the folder the way LanceDB does

`validate_data_dir` keeps its `Path` checks (they produce the best sentences for
the common mistakes) and then, if `<path>/lancedb` is a directory, does what
`store/chunk_store.py` does: `lancedb.connect(str(root))`, `table_names()`, and
`open_table("budget_chunks").count_rows() > 0`. Failures map to:

| failure | sentence |
|---|---|
| connect / list raises | "That folder is there, but the search index inside it can't be opened. Copy the folder's address from File Explorer's address bar and try again." |
| no `budget_chunks` table or 0 rows | existing `MSG_NO_CORPUS` |

This runs only on the repair path (`POST /api/config/data-dir` and the CLI), never
on a hot path. **Test:** a temp dir with an empty `lancedb/` subfolder is refused
with the first sentence; a real empty Lance dir (created by `lancedb.connect` in the
test) is refused with `MSG_NO_CORPUS`; a `MagicMock`-patched connect that raises is
refused with the first sentence.

### 2.3 The repair box appears for every failure the pointer can cause

`app/health.py::_check_machine_config`:

| state | ok | detail / fix |
|---|---|---|
| file absent, **packaged** | ✗ | "This computer hasn't been told where the shared budget folder is." / "Type the folder's location below — it's the one that contains the 'lancedb' folder." |
| file absent, dev checkout | ✓ | unchanged today's sentence |
| unreadable JSON | ✗ | fix: "You don't need to edit anything by hand — type the folder's location below and the app will rewrite this file correctly." |
| not an object / no usable `data_dir` | ✗ | same fix sentence |

**"Packaged"** = `JLBC_PACKAGED=1` in the environment, which `launcher.pyw` sets in
`prepare_environment`. A dev checkout never sets it and keeps today's behaviour;
`JLBC_DATA_DIR` still wins everywhere. This is the deliberate split the prior
session's comment claimed and its tests disproved — recorded at the code and in
STATUS.

`health_detail`: `"can_repair": first_failure in ("machine_config", "share")`. The
`corpus` rung stays non-repairable (its failures — a damaged index — are not fixed
by typing a folder; `Repair.tsx`'s comment already says why).

**Tests:** `tests/test_health_ladder.py` gains the packaged/absent case (env set →
rung fails, `can_repair` true, later rungs `NOT_CHECKED`), the corrupt-JSON case
asserts the new fix sentence, and the dev/absent case stays green. `HealthGate` /
`Repair` vitest: the form renders when the first failure is `machine_config`.

### 2.4 Copy

- `webapp/src/pages/Repair.tsx` placeholder → `\\server\share\jlbc-search-data`.
- `app/main.py::_default_provider`'s stderr line drops *"Set JLBC_DATA_DIR to a
  migrated data dir for real retrieval."* for *"Open the app: the start-up screen
  will ask for the shared folder."*

---

## 3. The three app bugs (Tier 2)

### 3.1 Locate cache (`app/routes/pdf.py`)

`_locate_doc_cache` becomes `collections.OrderedDict`; `popitem(last=False)` is
then valid. `app/main.py`'s lifespan shutdown closes every cached document. **Test:**
open 9 distinct paths through `_locate_open_doc` with a fake `fitz`; the first is
evicted and `close()`d, no exception. Mutating the type back to `dict` turns it red.

### 3.2 Cache-on-error (`store/documents.py`, `harness/settings.py`, `app/search_provider.py`)

On `OSError` from the read, the cache is left holding the previous good value and
the stamp is set to `None`, so the next call re-reads. A `ValueError` on a fully
read file (genuinely corrupt content) still caches `{}` under the stamp — re-reading
a corrupt file every call buys nothing. **Test:** stat succeeds, `read_text` raises
`PermissionError` once → second call returns the real content.

### 3.3 Fake results cannot hide

- `webapp/src/pages/Search.tsx` renders the same "These are sample results, not a
  real search" banner `FiscalNotes.tsx` already has when the response's `provider`
  is `"stub"`. **Test:** vitest, banner present for `provider: "stub"`, absent for
  `"lance"`.
- `app/main.py`: while the app holds a `StubSearchProvider`, each `POST /api/search`
  re-runs the corpus probe first (one `count` — cheap); on success the app swaps to
  `LanceSearchProvider` for the process lifetime. A share that comes back after a
  bad start is picked up without a restart. A real provider never swaps back to
  stub (today's "an honest 503 beats fake rows" rule stands). **Test:** first probe
  raises → stub; probe patched to succeed → next search is served by the Lance
  provider.
- `app/health.py::_check_corpus`: a `lancedb/` that lists no `budget_chunks` table,
  or one with 0 rows, fails the rung: *"The shared folder is there but holds no
  search index."* / *"Check you typed the folder that contains 'lancedb', or ask
  whoever set up the shared drive."* — still `can_repair: false` for `corpus`, but
  the analyst is no longer told everything is fine.

### 3.4 The one-line share-locking retries

- `store/config.py::write_documents_sidecar` and
  `ingest/fiscal_notes_refresh.py`'s directory write use `ingest/jobs.py::_replace_with_retry`
  (moved to a small shared helper, budget raised to ~3 s for the multi-MB sidecar).
- `ingest/lock.py::_unlink_quietly` catches `OSError`, not only `FileNotFoundError`.

**Tests:** `os.replace` patched to raise `PermissionError` twice then succeed →
write lands; lock release with `unlink` raising `PermissionError` does not raise.

---

## 4. Docs and record

- `docs/superpowers/investigations/2026-08-25-windows-launch-failure.md` — written
  (this spec's companion).
- `docs/QUICKSTART.md`: "always start from the icon; a bookmark stops working after
  a restart" (the port is fixed now, so this is belt-and-braces — keep it one
  line); the `app\` folder; where saved chats and generated memos live and that
  they stay on this PC. `README.md` gets a first line marking it developer-only.
- `STATUS.md`: a phase row + one section — what shipped, the D1–D4 decisions, the
  deliberate packaged/dev split (§2.3), what remains unwitnessed, and §W as the
  next batch.
- `CLAUDE.md` handoff list: nothing to add (the handoff file is gone).

---

## 5. Gates and acceptance

- `uv run pytest -q` — baseline on master `7329973` is **3342 passed / 5 skipped**.
- `cd webapp && npx tsc -b && npm run test -- --run` — baseline **1149 passed**;
  `npm run build` clean.
- `tests/test_packaging_manifest.py` green with the new assertions.
- `uv run python -m eval.run_eval` — `ingest/mineru_runner.py` changes, so the rule
  applies; the change is argv resolution and a `creationflags`, so the numbers are
  expected identical to the 2026-08-18 baseline (recall@5 85.71%, @15 97.62%, @20
  100%, refusal 60%). Results committed.
- **Nothing here can prove Windows behaviour.** Acceptance is a rebuilt bundle on
  Destin's laptop: install (confirm `app\` layout and shortcuts); Budget Documents
  shows titles and Open links; upload one JLBC agency page and watch it reach
  `live` with no console window; corrupt `machine.json` on purpose and confirm the
  folder box appears; type `//bcpool/…` and confirm it is stored as `\\bcpool\…`;
  type a folder with an empty `lancedb/` and confirm the refusal sentence.

---

## W. The rest of the 2026-08-25 audit — next batch, not this one

Recorded so it is not re-derived. Tier 3 needs a Windows box to confirm; Tier 4 is
small unrelated edits.

**Tier 3 — share file-locking (likely, unproven on Windows).** Admin restore
`rmtree`s the live corpus (`store/backup.py:104`, route catches only
`FileNotFoundError`); cancel/timeout orphans MinerU's model-server process and
blocks the worker on its stdout pipe (`mineru_runner.py:696`); OpenDataLoader's Java
child has no `CREATE_NO_WINDOW` and decodes output as cp1252; per-upload snapshot
zips the whole corpus over SMB with only an env-var off-switch; lock stale-steal
compares the holder's clock to the contender's; no laptop-sleep detection;
office-guidance save is a two-step rename; issue-report/alias/report-format writers
have no retry; `harness/history.py` list/search read without the per-id lock.

**Tier 4 — annoyances.** Admin username match is case-sensitive
(`app/identity.py:261`); `RESET-ADMIN.txt` → `.txt.txt` on default Explorer;
corporate proxy/TLS failures render raw `httpx` text; Chrome Memory Saver / Edge
sleeping tabs can discard a Deep Research turn (no `beforeunload` guard);
`MarkdownContent.tsx:22` reports "Copied" without awaiting the clipboard; shortcut
creation fails on OneDrive-redirected Desktops and apostrophe usernames; the
installer picks the last zip in directory order; the icon is the Python snake;
longest bundle path is 28 chars under 260; logs never rotate; generated memos are
saved twice (AppData + Downloads); `harness/documents.py` AppData copies are never
swept; `README.md` names port 9300 and `uv run` (partly fixed here by the
developer-only banner); `PREVIEW-BRIEFING.md` references a Handbook that does not
exist; `Path.home()` fallbacks disagree when `LOCALAPPDATA` is unset;
`worker.py:194`'s 8-CPU clamp assumes 4-core PCs; hand-upload doc_ids reach
`extractor-output/<id>/` unslugified (length only — no illegal characters exist in
the corpus today).

**Verified clean, do not re-audit:** every text read/write in shipped code passes
`encoding="utf-8"` (73 sites); no POSIX-only imports or calls; no `shell=True`; all
persisted paths are POSIX-relative and readers normalise; no filename anywhere uses
characters Windows forbids; no reserved device names among 7,574 doc_ids or the
agency catalog; every timestamp used in a filename is colon-free; every client
route `encodeURIComponent`s ids; "Open document" is same-origin, never `file://`;
the PDF route closes its handle on both normal and disconnect paths; `python312._pth`
lists `..` so `python -m app.machine_config` resolves from any cwd; the fastembed
and tiktoken cache layouts match what the libraries look for; `HF_HUB_OFFLINE` and
`MINERU_MODEL_SOURCE=local` are honoured by the vendored sources.
