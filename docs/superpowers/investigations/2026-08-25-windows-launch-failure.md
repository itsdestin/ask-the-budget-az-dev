# The work laptop would not open the corpus — the verified failure chain

**Date:** 2026-08-25 (incident 2026-08-18) · **Status:** root causes verified, fixes specced in
`docs/superpowers/specs/2026-08-25-windows-beta-fixes-design.md`.

This is the only defect a real beta user has hit. Everything else on the Windows list
was found by audit. It is recorded here because the reasoning behind three of the
repair-chain fixes lived only in a stalled session transcript and a handoff file
(`PROMPT-windows-launch-repair.md`, deleted 2026-08-25 when its work was discarded).

## What happened

Destin installed JLBC Search 0.9.1 from the USB on his work laptop
(`C:\Users\bclaptop`) by following the one-click installer. The app booted every
time, silently served **stub fixture rows** instead of the real corpus, and then
showed the *"JLBC Search can't start"* screen with no control on it. Four server
starts between 16:56 and 17:10; three distinct failures.

The chain below comes from the laptop's own log (`server-2026-08-18.log`, 87 lines)
plus a read of the repo, re-confirmed against master `7329973`.

## Failure A — `machine.json` was corrupt JSON (16:56 and 17:02)

```
app.machine_config: C:\Users\bclaptop\AppData\Local\JLBC-Search\machine.json
is unreadable (Invalid \escape: line 2 column 19 (char 20)) — falling back to
the default data folder. Use the repair screen, or delete this file, to fix it.
```

Repeated ~55 times, once per data-dir resolution. `Invalid \escape` at line 2,
column 19 is exactly the position of `\J` in

```
{
  "data_dir": "E:\JLBCSearch..."
```

— a Windows path with a **raw single backslash**, which `json.dump` cannot produce
(it always writes `\\`). So something other than the app's own writer produced the
file. The writer was never identified: the historical `install.cmd` at `eb64561`
hand-wrote the file with a batch `echo`, but that code was replaced by
`python -m app.machine_config` in `e728ef4` (2026-08-01); `packaging/diag/diag.pyw`
only reads it. The 08-25 handoff believed the USB's `Install-JLBC-Search.cmd` was an
uncommitted edit (6,535 bytes vs 5,615) — it was not: the repo's copy is 6,535 bytes,
committed in `505a1df` on 08-18.

**The identity of the writer does not change the fix.** A pointer file can be
corrupted by a hand edit, a stray installer, or a half-written file; the app must
recover from any of them on screen.

## Failure B — the pointer was rewritten into a form LanceDB refuses (17:10)

```
no usable corpus (ValueError: Invalid input, Failed to connect to namespace:
IO { … InvalidUrl { url: Url { scheme: "file", … host: None, …
path: "/bcpool/JLBCSearch/lancedb/__manifest/_versions" } } … })
```

The share host is `bcpool`. That URL is what a **forward-slash** path
(`//bcpool/JLBCSearch`) produces, not a proper UNC `\\bcpool\JLBCSearch`.

This is the shape that matters: Python tolerates forward slashes everywhere —
`Path.exists()`, `is_dir()`, `iterdir()` all pass — so `validate_data_dir` accepted the
path and the repair reported **success**. LanceDB's Rust object store then built a
`file://` URL from the same string and rejected it. The user was told the repair
worked while the app kept serving fake data.

Consequence for the design: validation must attempt the same open LanceDB performs.
No amount of `Path` checking can catch this class.

## Failure C — the repair screen was structurally unreachable

Destin: *"there is no in-app repair screen, at least not one that is
accessible/functional."* Verified mechanism on master:

| Where | What it does |
|---|---|
| `webapp/src/HealthGate.tsx:48` | renders `<Repair>` whenever health is not ok — the "can't start" screen IS the repair page |
| `webapp/src/pages/Repair.tsx:72` | renders the folder input **only** `if (report.can_repair)` |
| `app/health.py:256` | `"can_repair": first_failure == "share"` |

The laptop's first failing rung was `machine_config`, not `share`. So `can_repair`
was false, the input never rendered, and the only advice on screen was *"delete this
file by hand"* — which is what produced Failure B.

## Why an audit did not find A–C first

- The stub-provider fallback (`app/main.py::_default_provider`) degrades to
  realistic fake rows on **any** exception with one stderr line. Under `pythonw.exe`
  that line lands in a log nobody reads. The Budget Documents page carried no
  "sample results" label (Fiscal Notes did).
- The health ladder passed a present-but-empty `lancedb/` as OK.
- `packaging/README.md` recorded that real retrieval had never been exercised on
  Windows — every prior Windows run used an empty data dir, i.e. the stub.

## What the prior session built, and why it was discarded

Branch `2026-08-21-windows-repair-robustness` (deleted 2026-08-25): zero commits, two
files with uncommitted edits, 6 of 13 health tests red. Its `normalize_data_dir`
converted `E:/x` → `E:\x` but passed `//bcpool/JLBCSearch` — the exact string from
the log — through untouched, because its guard matched only drive-letter paths. Its
`can_repair` widening was issued twice in the transcript and never reached disk.

The one idea carried forward: the `machine_config` rung fails with *"type the folder
below"* rather than *"delete this file"*, so the repair box is on screen for the
failure the pointer itself causes.

## Related findings from the 2026-08-25 Windows audit

The same audit that absorbed this incident found two independent reasons the beta
bundle could not have worked even with a correct pointer: MinerU is unlaunchable on
the bundle (`resolve_mineru_exe` falls back to `uv run mineru`), and the bundle
excludes `webapp/reference/assets/search/index-lite.js` while
`app/search_provider.py` reads it at runtime. Both are in the spec above.
