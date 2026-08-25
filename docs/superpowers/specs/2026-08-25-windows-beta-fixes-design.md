# Windows beta fixes — design

**Date:** 2026-08-25 · **Status:** approved by Destin 2026-08-25 (chat), revised after an
independent review the same day; §S lists what still needs his word · **Branch:** `windows-beta-fixes`

**Supersedes:** the discarded `2026-08-21-windows-repair-robustness` branch and
`PROMPT-windows-launch-repair.md` (both deleted 2026-08-25). **Builds on:**
`docs/superpowers/investigations/2026-08-25-windows-launch-failure.md` (the laptop
incident) and the 2026-08-25 five-lane Windows portability audit summarised in §W.

## Why

The app has only ever been tested on a Linux dev box against a local corpus. The one
real Windows beta install (2026-08-18) failed three ways in fourteen minutes and
served fake search rows the whole time. A read-only audit of the bundle and the
runtime then found that even with a correct pointer the beta bundle could not have
worked: MinerU cannot be launched, and Budget Documents loses every title and link.

**Principles.**
1. Anything that can go wrong with the *pointer or the share* is fixable on the screen
   the user is already looking at, without restarting anything.
2. The bundle is checked against what the code actually reads, never against a list
   someone typed.
3. **No probe, health check or validation may create a directory at the pointer
   location.** A check that manufactures the folder it is checking for can only
   report "fine" — this is why the laptop's wrong pointer read as "index can't be
   opened, can't repair" instead of "wrong folder".

## Scope

Decisions D1–D4 were Destin's, 2026-08-25:

- **D1** Delete the USB diagnostic tool (`packaging/diag/`, `RUN-DIAGNOSTIC.cmd`).
  The in-app repair screen is the one recovery path.
- **D2** Program files move to a subfolder of `%LOCALAPPDATA%\JLBC-Search\`;
  per-person data stays at `%LOCALAPPDATA%\JLBC-Search\`.
- **D3** The launcher tries port 9300 first, random only if taken.
- **D4** This batch = Tier 1 (bundle-breakers) + the launch/repair chain + Tier 2
  (three app bugs) + the one-line share-locking retries. Tier 3/4 is recorded in
  STATUS.md as the next batch (§W).

One worktree, one branch, one merge — the file sets are mostly disjoint but this repo
has recorded three cross-branch defects from parallel lanes, and the batch is ~12
tasks.

## §S — decisions the review flagged as mine, not Destin's

Each is implemented as written unless he says otherwise at the spec review.

- **S1** `install.cmd` (the unzip-it-yourself path) is deleted; the one-click
  `Install-JLBC-Search.cmd` is the only installer (§1.4).
- **S2** The program subfolder is named **`program\`**, not `app\` — the bundle
  already has a Python package called `app/`, so `app\app\main.py` and an error text
  saying "delete the app folder" invite the wrong deletion (§1.4).
- **S3** Launcher start-up timeout 180 s, and its box says "still starting" rather
  than "failed" (§1.7).
- **S4** Every new sentence on the repair screen, the launcher box and the installer
  (§1.4, §1.7, §2.3, §2.4) — shown rendered at the checkpoint in §4 before merge.
- **S5** While the app is on the stub provider, it re-probes the corpus at most once
  every 30 s, triggered by a search or a health poll (§3.3).

---

## 1. The bundle and installer (`packaging/`)

### 1.1 MinerU launches (P1)

`ingest/mineru_runner.py::resolve_mineru_exe` gains a rung between the
`JLBC_MINERU_EXE` override and `shutil.which("mineru")`:

> if `importlib.util.find_spec("mineru")` succeeds → `[sys.executable, "-m", "mineru.cli.client"]`

`mineru.cli.client:main` is what the `mineru` console script wraps
(`mineru-3.1.6.dist-info/entry_points.txt`; `client.py` ends in
`if __name__ == "__main__": main()`). The `uv run mineru` rung stays LAST, for dev
boxes without the package importable. The function returns an argv **list** and every
caller already treats it as one. The bundle's `python312._pth` lists `../site-packages`,
so the child resolves the package.

Under the launcher `sys.executable` is `pythonw.exe`, so the MinerU child is already
windowless. `_stream` still passes `creationflags=subprocess.CREATE_NO_WINDOW` on
`os.name == "nt"` — belt-and-braces for a dev who runs the app from `python.exe` —
with a comment saying it does nothing for OpenDataLoader's Java child, whose runner
hardcodes its own `Popen` (§W).

`packaging/build_bundle.py` drops `site-packages/bin/` from the staged tree: 62
POSIX shell scripts whose shebang is the dev machine's venv path.

**Tests:** `resolve_mineru_exe()` with `JLBC_MINERU_EXE` unset, `shutil.which`
patched to `None`, `find_spec` patched truthy → `[sys.executable, "-m",
"mineru.cli.client"]`; `find_spec` → `None` → `["uv", "run", "mineru"]`. A manifest
test asserts no `site-packages/bin/` entry.

### 1.2 Titles and links come back (P2)

`webapp/reference/assets/search/index-lite.js` ships. `EXCLUDED_PREFIXES` keeps
`webapp/reference/`; a new `INCLUDED_FILES` allowlist re-admits that one path, with
the reason at the constant (the search provider reads it at runtime for the meta
line and the exact-URL join).

**Test:** `tests/test_packaging_manifest.py` imports
`app.search_provider.MOCKUP_INDEX_PATH`, makes it repo-relative, and asserts it is in
`source_files()`. Reader and bundle cannot drift apart silently again.

### 1.3 Installers stop flashing (P3)

A repo-root `.gitattributes` with `*.cmd text eol=crlf` and a renormalising commit.
A pytest reads every `packaging/**/*.cmd` as bytes and asserts CRLF. The build gains a
step that copies `packaging/Install-JLBC-Search.cmd` next to the zip in `dist/` (it is
the file that flashed, and today it reaches the USB by hand), asserting CRLF on the
copy.

### 1.4 Layout: a `program\` subfolder, upgrades that replace it (P4, D2, S1, S2)

| | before | after |
|---|---|---|
| program | `%LOCALAPPDATA%\JLBC-Search\` | `%LOCALAPPDATA%\JLBC-Search\program\` |
| pointer, chats, memos, logs, `running.json`, `mineru.json` | `%LOCALAPPDATA%\JLBC-Search\` | unchanged |
| upgrade | extract over a running install | stop the server, delete `program\`, extract |

`Install-JLBC-Search.cmd`:

- `INSTALL_DEFAULT=%LOCALAPPDATA%\JLBC-Search\program`; a typed install folder is
  stripped of a trailing `\` (as `install.cmd:16` already did).
- **Stop a running server first.** If `%LOCALAPPDATA%\JLBC-Search\running.json`
  exists, an installed Python is still on disk (old layout `JLBC-Search\python\` or new
  `…\program\python\`), so a `python -c` one-liner reads the `pid`; the installer
  then `taskkill /PID <pid> /T /F` **only if** `tasklist /FI "PID eq N" /FI
  "IMAGENAME eq pythonw.exe"` lists it (a reused pid never kills a stranger).
- **`rmdir /s /q "%INSTALL_DIR%"` runs only when `%INSTALL_DIR%\launcher.pyw` and
  `%INSTALL_DIR%\VERSION` both exist.** A typed folder that is not a JLBC Search
  install is never deleted.
- **One-time cleanup of the old layout:** if `%LOCALAPPDATA%\JLBC-Search\python\pythonw.exe`
  exists (the 0.9.1 layout), the installer removes the known program subfolders
  at that level — `python\ site-packages\ jre\ models\ app\ harness\ store\ retrieval\
  chunking\ citation\ identity\ memo\ ingest\ webapp\ data\ samples\ scripts\
  funds\ primer\` plus `launcher.pyw install.cmd QUICKSTART.md VERSION MANIFEST.json` —
  and nothing else, so `conversations\ documents\ logs\ machine.json running.json`
  survive. Without this the three beta laptops keep 3.3 GB of dead files.
- The `:incomplete` text says *"delete the `program` folder inside JLBC-Search"*,
  never the parent.
- `--set-ingest-enabled false` becomes `--default-ingest-enabled false` (§1.5).
- The `mineru.json` rewrite step is removed (§1.6).

`install.cmd` is **deleted** (S1): `REQUIRED_ENTRIES` loses it, `step_launcher`
stops copying it, `packaging/README.md` and `docs/QUICKSTART.md` drop the manual
path. Two installers is how the LF bug reached both.

`launcher.pyw`: `INSTALL_DIR` is still `Path(__file__).parent` (now `…\program`);
`STATE_DIR` stays `%LOCALAPPDATA%\JLBC-Search` — per-machine data is independent of
where the program lives, and the docstring that claimed the two were separate becomes
true.

*User-visible consequence:* the three beta laptops reinstall once; nothing personal is
lost because the installer never touches the parent folder except to remove the
known old program subfolders.

### 1.5 Ingest survives an upgrade (P5)

`app/machine_config.py` CLI gains `--default-ingest-enabled {true,false}`: writes the
key only when `machine.json` has no `ingest_enabled` key. The installer calls that
instead of `--set-ingest-enabled false`. **Test:** an existing `true` survives the
default call; an absent key becomes `false`.

### 1.6 `mineru.json` is the launcher's job

`launcher.pyw::prepare_environment` writes `%LOCALAPPDATA%\JLBC-Search\mineru.json`
from `INSTALL_DIR` on every start (`models-dir.pipeline = <INSTALL_DIR>/models/mineru`,
`model-source: local`) and points `MINERU_TOOLS_CONFIG_JSON` at it. Program files
stay read-only; a moved or renamed folder can no longer strand MinerU on a stale
absolute path. `build_bundle.py` still ships the `__INSTALL_DIR__` template under
`models/` so the manifest and MinerU's own config reader find a file; the launcher's
env var wins.

### 1.7 Launcher behaviour (D3, S3 + audit)

- **Port:** try to bind `9300`. **The bind is the single-instance lock:** if it is
  held, poll `http://127.0.0.1:9300/health` for the timeout — a second click during
  start-up waits for the first instead of starting a second server. If the port
  answers but not with `{"ok": true}` (a foreign service), fall back to a free port
  and log why. `running.json` keeps `port` and `pid` (the installer reads the pid);
  no other state.
- **Timeout:** `HEALTH_TIMEOUT_S = 180`. The box says *"JLBC Search is still
  starting. Wait a minute, then click the icon again. If it still does not open,
  send this file: …"*.
- **Nothing dies silently:** `main()` runs inside a top-level `try/except` that calls
  `message_box` with the exception's one-line form; the pre-log `write_text` passes
  `encoding="utf-8"`.
- `/health`'s `provider` value is written to the log line at start-up — the one
  Windows signal the investigation says nobody could see.

### 1.8 Deletions and cruft (D1)

Delete `packaging/diag/` and `packaging/RUN-DIAGNOSTIC.cmd`, `tests/test_diag_tool.py`,
and rewrite the STATUS.md row that says the tool ships ("deleted 2026-08-25, D1").
`EXCLUDED_PREFIXES` gains `mockups/`; the source filter drops any root-level
`PROMPT-*.md` by prefix instead of listing names.

---

## 2. The launch/repair chain

### 2.1 The pointer is normalised before it is checked or stored

`app/machine_config.py::normalize_data_dir(path) -> str`:

1. `str(path).strip()`, strip surrounding `"` and `'`, then `.rstrip("\\/")` —
   and a remainder ending in `:` gets ONE separator back (`E:\` stays `E:\`, bare
   `E:` becomes `E:\`; `E:` alone means "current directory on E:" and
   `Path("E:").exists()` is True, so it would validate and then open LanceDB
   relative to the process cwd).
2. On `os.name == "nt"`: replace every `/` with `\`; a result beginning with one `\`
   followed by a non-`\` gains a second leading `\` (the `/host/share` form). That
   last rule is a guess — `\JLBCSearch` can also mean `C:\JLBCSearch` — and is
   harmless only because §2.2 then refuses anything that does not open.
3. Elsewhere: unchanged beyond step 1.

| input (nt) | output |
|---|---|
| `//bcpool/JLBCSearch` | `\\bcpool\JLBCSearch` |
| `/bcpool/JLBCSearch` | `\\bcpool\JLBCSearch` |
| `E:/JLBCSearch/` | `E:\JLBCSearch` |
| `"E:\JLBCSearch\"` | `E:\JLBCSearch` |
| `E:\` | `E:\` |
| `\\bcpool\JLBCSearch` | unchanged |

`validate_data_dir` and `set_data_dir` both go through it first; what lands in
`machine.json` is the normalised form. The WHY comment cites the investigation doc.

**Tests:** the table above with `os.name` monkeypatched to `"nt"`, so the Windows
branch runs on Linux. The **five** assertions in `tests/test_machine_ingest_enabled.py`
(lines 57, 127–138) that pin `//server/share/JLBC-Search-Data` keep passing on Linux
(no `nt` rewrite) and gain a comment saying the stored form on Windows is
`\\server\share\…`. The two literals in `tests/test_pdf_route.py:303,308` belong to
`_safe_relative`'s path-poisoning test and are **not touched**.

### 2.2 Validation opens the folder the way LanceDB does

`validate_data_dir` keeps its `Path` checks (they produce the best sentences for the
common mistakes) and then, if `<path>/lancedb` is a directory, does what
`store/chunk_store.py` does — **without creating anything** (principle 3):
`ChunkStore(root=path, create=False)`, `table_names()`, and
`open_table("budget_chunks").count_rows() > 0`.

| failure | sentence |
|---|---|
| connect / list raises | "That folder is there, but the search index inside it can't be opened. Copy the folder's address from File Explorer's address bar and try again." |
| no `budget_chunks` table, or 0 rows | existing `MSG_NO_CORPUS` |

Measured: `lancedb.connect()` on an **empty** directory succeeds and `table_names()`
is `[]` (lancedb 0.36), so an empty `lancedb/` lands on the second row; only a real
connect failure (the laptop's `InvalidUrl`, a half-copied manifest) reaches the
first. This runs only on the repair path, never on a hot path.

`ChunkStore.__init__` gains `create: bool = True`; `create=False` skips the `mkdir`
and is used by `_default_provider`, the re-probe (§3.3), `app/health.py::_check_corpus`
and `validate_data_dir`. Ingest and the retrieval pipeline keep the default.

**Tests:** empty `lancedb/` temp dir → `MSG_NO_CORPUS`; a `lancedb.connect` patched
to raise → the first sentence; `ChunkStore(create=False)` on a missing dir does not
create it (asserted by `exists()` after).

### 2.3 A bundle with no pointer says so; the repair box appears for every failure the pointer can cause

**Detecting the bundle.** `store/config.py::resolve_data_dir()` treats the repo
default (`<root>/data/insight-data`) as available **only when the root is a dev
checkout**. The bundle root carries a `VERSION` file that `build_bundle.py` writes and
`REQUIRED_ENTRIES` demands; no dev checkout has one (`VERSION` is untracked and absent).
So: env var → pointer → (if no `VERSION` at the root) repo default → otherwise raise
`DataDirNotConfigured(OSError)`. `data_dir()` lets that propagate — there is no folder
to create. This replaces the earlier idea of a launcher-set env var: it is a fact the
code can already see, it needs no new contract, and it cannot be undone by a stray
`mkdir`.

`app/health.py::_check_machine_config`:

| state | ok | detail / fix |
|---|---|---|
| file absent, bundle (`resolve_data_dir` raises `DataDirNotConfigured`) | ✗ | "This computer hasn't been told where the shared budget folder is." / "Type the folder's location below — it's the one that contains the 'lancedb' folder." |
| file absent, dev checkout | ✓ | unchanged today's sentence |
| unreadable JSON | ✗ | fix: "You don't need to edit anything by hand — type the folder's location below and the app will rewrite this file correctly." |
| not an object | ✗ | same fix sentence |
| file present but with no `data_dir` (only `ingest_enabled` / `display_names`) | ✓ if anything resolves (env var, or a dev checkout's default); ✗ "hasn't been told" only when `resolve_data_dir` raises | — the installer and the Settings page both write such files; on the Z13 and every dev box a folder resolves anyway |

`health_detail`: `"can_repair": first_failure in ("machine_config", "share")`. The
`corpus` rung stays non-repairable (a damaged index is not fixed by typing a folder;
`Repair.tsx`'s comment already says why).

**Tests:** `tests/test_health_ladder.py` gains the bundle/absent case (a `VERSION`
file at a temp root, `store.config` pointed at it → rung fails, `can_repair` true,
later rungs `NOT_CHECKED`); the corrupt-JSON case asserts the new fix sentence; the
dev/absent case stays green. `HealthGate`/`Repair` vitest: the form renders when the
first failure is `machine_config`.

### 2.4 A repair takes effect without restarting

`launcher.pyw` reuses any server answering `/health`, so "close and reopen the app"
never restarts the server — the current `restart_required: True` and the Repair
screen's *"open JLBC Search again to finish"* copy describe an action that does
nothing. Replaced:

- `POST /api/config/data-dir`: validate (§2.2) → store → `app.state.reprobe(force=True)`
  (§3.3), which re-runs the probe **regardless of the current provider** — the
  repair screen can appear on a machine that booted with a real corpus whose
  handles are now dead — swaps it in on success, and always calls
  `retrieval.pipeline.reset_default_collaborators()` so AI Mode's cached handle is
  rebuilt against the new folder. Response: `{"path": …}`; `restart_required` is
  gone.
- `Repair.tsx` "Saved" copy: *"Saved. Click **Try again** to check."* — the button
  already exists (`Repair.tsx:114`).
- Placeholder → `\\server\share\jlbc-search-data`.
- `app/main.py::_default_provider`'s stderr line drops *"Set JLBC_DATA_DIR to a
  migrated data dir for real retrieval."* for *"Open the app: the start-up screen
  will ask for the shared folder."*

**Tests:** route test — a stub app, save a valid folder, assert the provider is Lance
on the next search and the store reset was called; `Repair.test.tsx` asserts the new
copy and the retry button.

---

## 3. The three app bugs (Tier 2)

### 3.1 Locate cache (`app/routes/pdf.py`)

`_locate_doc_cache` becomes `collections.OrderedDict`; `popitem(last=False)` is then
valid. `app/main.py`'s lifespan shutdown closes every cached document. **Test:** open
9 distinct paths through `_locate_open_doc` with a fake `fitz`; the first is evicted
and `close()`d, no exception. Mutating the type back to `dict` turns it red.

### 3.2 Cache-on-error (`store/documents.py`, `harness/settings.py`)

On `OSError` from the read, the cache keeps its previous good value and the stamp is
set to `None`, so the next call re-reads. (`app/search_provider.py` was listed here
originally; the plan review showed it already clears its stamp on error and
re-reads next call — no change.) A `ValueError` on a fully read file
(genuinely corrupt content) still caches `{}` under the stamp — re-reading a corrupt
file every call buys nothing. **Test:** stat succeeds, `read_text` raises
`PermissionError` once → second call returns the real content.

### 3.3 Fake results cannot hide

- `webapp/src/pages/Search.tsx` renders the same "These are sample results, not a
  real search" banner `FiscalNotes.tsx:909-911` already has when the response's
  `provider` is `"stub"`. **Test:** vitest — banner present for `provider: "stub"`,
  absent for `"lance"`.
- `app/main.py`: `app.state.reprobe()` re-runs the corpus probe (`ChunkStore(create=False).count`)
  and swaps to `LanceSearchProvider` on success. While the provider is the stub, it
  is called from `POST /api/search` and from `/api/health/detail`, **rate-limited to
  once per 30 s** (S5) — `lancedb.connect` on an unreachable UNC path can block for
  the SMB timeout, and a search page polling every keystroke must not pay that. A real
  provider never swaps back to stub (today's "an honest 503 beats fake rows" rule
  stands). **Test:** first probe raises → stub; probe patched to succeed → the next
  search (after the window, clock patched) is served by the Lance provider; two
  searches inside the window call the probe once.
- `app/health.py::_check_corpus`: **no `budget_chunks` table** fails the rung —
  *"The shared folder is there but holds no search index."* / *"Check you typed the
  folder that contains 'lancedb', or ask whoever set up the shared drive."*
  **0 rows stays OK** — the recorded reasoning at `health.py:174-182` holds (a fresh
  admin install must reach the Upload page). `can_repair` stays false for `corpus`.

### 3.4 The one-line share-locking retries

- `ingest/jobs.py::_replace_with_retry` and `unlink_with_retry` move to a small
  shared helper (`store/fs.py`), catching `PermissionError` **and** `OSError` with
  `winerror in (5, 32)` (sharing violation), budget raised to ~3 s.
  `store/config.py::write_documents_sidecar` and `ingest/fiscal_notes_refresh.py`'s
  directory write use it.
- `ingest/lock.py::_unlink_quietly` uses `unlink_with_retry`.

**Tests:** `os.replace` patched to raise `PermissionError` twice then succeed →
write lands; lock release with `unlink` raising `PermissionError` does not raise.

---

## 4. UI checkpoint, docs and record

**Checkpoint before merge (S4).** The repair screen is the only thing a beta user
sees when it goes wrong, and none of its new states has been rendered. Before the
merge task, run the dev server against three deliberately broken states — a corrupt
`machine.json`, a bundle root with no pointer (a temp `VERSION` file), a folder with
an empty `lancedb/` — plus Budget Documents on the stub provider, and put the four
screenshots in front of Destin. Wording changes from that pass land in the same
branch; nothing merges until he has seen them.

- `docs/superpowers/investigations/2026-08-25-windows-launch-failure.md` — written.
- `docs/QUICKSTART.md`: one-click installer only; the `program\` folder; where saved
  chats and generated memos live and that they stay on this PC; "start it from the
  icon". `README.md` gets a first line marking it developer-only.
- `packaging/README.md`: `install.cmd` row removed, layout table updated, diag rows
  removed.
- `STATUS.md`: a phase row + one section — what shipped, D1–D4 and §S, the bundle
  marker rule (§2.3), what remains unwitnessed, and §W as the next batch.

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
  Destin's laptop: install (confirm the `program\` layout, the old files gone, the
  shortcuts); Budget Documents shows titles and Open links **and real rows through
  the normalised UNC pointer** — if LanceDB refuses `\\bcpool\…`, the fallback is a
  mapped drive letter and that must be recorded; upload one JLBC agency page and
  watch it reach `live` with no console window; corrupt `machine.json` on purpose
  and confirm the folder box appears; type `//bcpool/…` and confirm it is stored as
  `\\bcpool\…` and search works after **Try again** without relaunching; type a
  folder with an empty `lancedb/` and confirm the refusal sentence.

---

## W. The rest of the 2026-08-25 audit — next batch, not this one

Recorded so it is not re-derived. Tier 3 needs a Windows box to confirm; Tier 4 is
small unrelated edits.

**Tier 3 — share file-locking (likely, unproven on Windows).** Admin restore
`rmtree`s the live corpus (`store/backup.py:104`, route catches only
`FileNotFoundError`) **and still returns `restart_required: True` with the
same "reopen the app" semantics §2.4 retires** (`app/routes/admin.py:1213`); cancel/timeout orphans MinerU's model-server process and
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
