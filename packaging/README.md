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
(docs, tests, eval, the retired `web/` `mcp-server/` `db/`), and `EXCLUDED_NAMES`
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

- **`install.cmd` writes `%LOCALAPPDATA%\JLBC-Insight\machine.json` directly.**
  `app/machine_config.py` (Plan 5 Task 10) is the canonical reader/writer of that
  file; the installer writes it by hand only because the app is not running yet.
  *Task 17 should replace this with a call into the app* — see the note in
  `docs/superpowers/investigations/2026-08-01-bundle-size.md`.
- **`REQUIREMENTS` in `build_bundle.py` mirrors `measure.py`**, and both are derived
  from the app's imports rather than from `pyproject.toml` (which still carries the
  retired Postgres/Voyage/Anthropic stack). After Task 18 deletes that stack,
  consider generating both from `pyproject.toml` instead.
- **`mineru[pipeline]==3.1.6` is pinned, not floored.** The live corpus was
  extracted with 3.1.6 and the plan declines the 3.4.4 upgrade because it changes
  chunk text corpus-wide. `>=3.1.6` resolves to 3.4.4 and builds cleanly — the
  regression would be invisible until answers stopped matching citations.
- **`packaging/` must never gain an `__init__.py`.** `packaging` is also a real PyPI
  library that half the dependency tree imports; making this directory a regular
  package would shadow it. Pinned by a test.

## What has NOT been verified

As of 2026-08-01 the bundle has been **built** but never **run**. No Windows
machine has executed any of it. The acceptance criterion is unchanged and is not
"the build succeeded":

> The server starts, and answers a query, **with the network cable unplugged**, on
> a machine that has never had Python installed.

The most likely failure is the `python312._pth` edit in `step_python()` — it is what
lets the embeddable interpreter see `site-packages` at all, and if it is wrong the
bundle builds perfectly and dies on the first `import fastapi`.
