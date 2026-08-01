# packaging/ — how the Windows bundle is built

Everything in this folder produces one artefact: `dist/JLBC-Insight-<version>.zip`.
Unzipping it into `%LOCALAPPDATA%\JLBC-Insight` and double-clicking `install.cmd`
is the entire install — no admin rights, no Python on the machine, no Java on the
machine, and no downloads the first time it runs.

| File | What it is |
|---|---|
| `build_bundle.py` | Builds the bundle. Runs on Linux or Windows. |
| `launcher.pyw` | What the shortcut runs. Starts the server, opens the window. |
| `install.cmd` | Creates the shortcuts, records the shared folder. Run once, by the user. |
| `measure.py` | The Task 14 size spike. Kept because it is how you re-check the size after a dependency change. |

## Rebuilding

```bash
cd webapp && npm ci && npm run build && cd ..    # the bundle refuses to ship an unbuilt UI
python packaging/build_bundle.py --version 1.0.0
```

Takes roughly 10–15 minutes cold, most of it downloading ~1.5 GB of Windows
wheels; a second run reuses `build/.cache`. Output lands in
`dist/JLBC-Insight-1.0.0.zip` (~2.1 GB) with the staged tree left in
`build/JLBC-Insight-1.0.0/` (~3.3 GB) for inspection. Both are gitignored.

`--plan` prints what would be built without building it. `--skip-zip` stops after
staging, which is what you want while iterating.

**You can build the Windows bundle from Linux.** `uv` resolves and downloads real
Windows wheels for a foreign platform, and every other Windows artefact (the
embeddable runtime, the JRE) is a download rather than a compile. The build
verifies this held: it fails if a pre-built wheel is not platform-independent, and
`tests/test_packaging_manifest.py` plus a `find -name '*.so'` over `site-packages`
will tell you if a Linux binary ever sneaks in (there should be exactly zero).

## What goes in, and why it is safe

The application file list comes from **`git ls-files`**, not a directory walk.
That is deliberate and load-bearing: anything gitignored — `.env`, the corpus at
`data/insight-data/`, `samples/raw-pdfs/`, `.venv/` — *cannot* reach the bundle,
even if someone adds a new secret file next year. Invariant 8 ("the distributable
never contains corpus content") holds by construction rather than by vigilance.

On top of that, `EXCLUDED_PREFIXES` drops trees that are tracked but not runtime
(docs, tests, eval), and `EXCLUDED_NAMES`
drops individual files — including the retired Postgres-era modules that still
`import db.connection` and would ship as dead code that crashes if touched.

`tests/test_packaging_manifest.py` pins all of it and runs in under a second
without building anything.

## Bumping the version

`--version` is the only input; it names the zip, writes `VERSION` into the bundle,
and is recorded in `MANIFEST.json`. There is no version constant to edit.

## The four environment variables that make first run offline

`launcher.pyw::prepare_environment()` sets these before importing the app. Each was
verified against the shipped library source — details and line numbers in
`docs/superpowers/investigations/2026-08-01-bundle-size.md`.

| Variable | Without it |
|---|---|
| `FASTEMBED_CACHE_PATH` | models default to `%TEMP%`, which Windows eventually deletes |
| `HF_HUB_OFFLINE=1` | fastembed calls huggingface.co on every model construction, cache or no cache |
| `MINERU_MODEL_SOURCE` + `MINERU_TOOLS_CONFIG_JSON` | MinerU downloads 1.15 GB of weights |
| `TIKTOKEN_CACHE_DIR` | tiktoken downloads its encoding, and **fails soft** — chunk boundaries silently change |

The launcher also prepends `jre/bin` to `PATH`, because `opendataloader-pdf` shells
out to bare `java`. Nothing outside the install folder is touched and any Java
already on the machine is unaffected.

## Known couplings

These are places where this folder duplicates knowledge that lives elsewhere. Each
needs updating if the other side moves.

- ~~**`install.cmd` writes `machine.json` directly.**~~ **RESOLVED, Track 4.**
  It now calls `python -m app.machine_config --set-data-dir "…"`, so
  `app/machine_config.py` is the only thing that knows that file's schema. The
  entry point starts no server, and it exits 0 even when the folder is
  unreachable — a network drive that is not connected during setup is normal,
  and refusing to record the path would strand the user. `install.cmd` also
  calls `--set-ingest-enabled false`, which is deliberate rather than
  redundant: it is the same default the app applies, written down where the
  installer's reader can see it.
- **`REQUIREMENTS` in `build_bundle.py` mirrors `measure.py`**, and both are derived
  from the app's imports rather than from `pyproject.toml`. Track 4 deleted the
  retired Postgres/Voyage stack from the tree, but `pyproject.toml` still
  DECLARES `psycopg`, `pgvector`, `voyageai` and `python-dotenv` — see STATUS's
  follow-ups. Once those are dropped, consider generating both from
  `pyproject.toml` instead.
- **`mineru[pipeline]==3.1.6` is pinned, not floored.** The live corpus was
  extracted with 3.1.6 and the plan declines the 3.4.4 upgrade because it changes
  chunk text corpus-wide. `>=3.1.6` resolves to 3.4.4 and builds cleanly — the
  regression would be invisible until answers stopped matching citations.
- **`packaging/` must never gain an `__init__.py`.** `packaging` is also a real PyPI
  library that half the dependency tree imports; making this directory a regular
  package would shadow it. Pinned by a test.

## What has been verified on Windows

**2026-08-01** — a Linux-built bundle, transferred by USB and extracted with `tar -xf`
into `%LOCALAPPDATA%` on a Windows laptop that had never had Python, under a standard
user account with no admin rights:

- all 36102 files extracted (exact match for the archive's entry count)
- the whole core closure imports — fastapi, uvicorn, lancedb, pyarrow, fastembed,
  pymupdf, python-docx, beautifulsoup4, rapidfuzz
- the ingest closure imports — mineru, torch, transformers, tiktoken
- `from app.main import create_app` works, so the repo-mirroring layout is right
- `jre\bin\java.exe -version` reports Temurin 21.0.12, 64-bit Server VM

That settles the `python312._pth` edit in `step_python()`, which was the highest-risk
line in this whole folder: without it the embeddable interpreter cannot see
`site-packages` at all, and a wrong edit yields a bundle that builds perfectly and dies
on the first `import fastapi`. It also settles the cross-platform premise — Windows
wheels resolved on Linux really do run on Windows, compiled extensions included.

Full transcript: `docs/superpowers/investigations/2026-08-01-bundle-size.md`.

Also verified in the same session:

- `install.cmd` completed with no admin elevation and no endpoint-security prompt
- the shortcut starts the server and serves the SPA
- several clicks leave exactly **one** `pythonw.exe` — S8's relaunch-reuse, confirmed by
  process count rather than by how fast the window felt
- **the acceptance criterion: an offline cold start.** WiFi off, server killed so the
  launch could not be a warm reuse, shortcut clicked — it started and served normally.
  The cold start was confirmed against the launcher's own `=== ... starting on port N ===`
  log line rather than assumed from how long it took.

That last one is what makes S7 real. The four environment variables above were each
traced through library source but none had been *exercised* until the network went away;
had `HF_HUB_OFFLINE` been wrong, the run would have hung on a timeout instead of starting.

## What has still NOT been verified

- **Real retrieval against a corpus.** Every run so far had an empty data dir, where
  `create_app()` falls back to stub search fixtures — so the interface was exercised
  without the retrieval path.
- **`java` found through the launcher's `PATH` prepend.** `jre\bin\java.exe` ran when
  invoked by explicit path; the indirection opendataloader-pdf actually uses has not been.
- **opendataloader-pdf extracting a real document**, and MinerU doing the same.
- **A stricter endpoint-security policy.** One laptop's policy is not the estate's.
- **Zip and unzip times over the office SMB share.** Transfer here was USB.
