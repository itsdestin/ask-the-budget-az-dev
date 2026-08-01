# Bundle size — measurement spike and distribution-shape decision

**Date:** 2026-08-01
**Plan:** `docs/superpowers/plans/2026-08-01-standalone-plan-5-admin-packaging.md`, Track 3 Task 14
**Spec:** S7 (unzip to `%LOCALAPPDATA%`, embeddable Python, all model weights pre-bundled, first run downloads nothing), S8 (launcher → browser window)
**Status:** measured; **decided 2026-08-01 — one bundle everywhere** (see [Decision](#decision-one-bundle-everywhere-decided-2026-08-01))
**Reproduce:** `python packaging/measure.py --profile both --find-links <dir with the antlr4 wheel>`

---

## What was measured, and where

Every size below is a **Windows** closure — real `x86_64-pc-windows-msvc` wheels for
CPython 3.12, resolved and downloaded by `uv pip install --target --python-platform`,
then unpacked and byte-counted. The *machine* doing the resolving was the Z13 (Linux);
uv resolves for a foreign platform, so these are Windows sizes measured from Linux.

**The measurement section below was written before anything ran on Windows** — sizes are
hard numbers, but every behavioural claim was inferred. A bundle has since been built and
its imports exercised on a real Windows laptop; see
[Verified on Windows](#verified-on-windows--2026-08-01-destins-work-laptop) for what that
settled and [Still not verified](#still-not-verified) for what it did not.

The requirement lists were derived from a repo-wide scan of third-party imports under
`app/`, `harness/`, `store/`, `ingest/`, `chunking/`, and the live `retrieval/` modules —
**not** from `pyproject.toml`, which still carries the retired Postgres / Voyage /
Anthropic stack that Task 18 deletes.

Model-weight sizes are measured from the caches this machine actually uses:
`/tmp/fastembed_cache` (the two ONNX models) and
`~/.cache/huggingface/hub/models--opendatalab--PDF-Extract-Kit-1.0` (MinerU 3.1.6's
pipeline weights, the path `~/mineru.json` points at).

---

## The numbers

| Component | Unzipped | Zipped |
|---|---:|---:|
| python.org 3.12.10 embeddable runtime (amd64) | 0.02 GB | 0.01 GB |
| `webapp/dist` (built SPA) | 2.7 MB | ~1 MB |
| client `site-packages` — 55 packages | 0.46 GB | 0.16 GB |
| fastembed ONNX models (arctic-embed-m 416 MB + ms-marco-MiniLM-L-12-v2 128 MB) | 0.53 GB | 0.49 GB |
| ingest-only `site-packages` delta — 73 more packages | 1.01 GB | 0.35 GB |
| MinerU 3.1.6 pipeline models (PDF-Extract-Kit-1.0) | 1.15 GB | 1.05 GB |
| **CLIENT bundle** — search + fiscal notes + AI Mode + upload-to-queue | **1.01 GB** | **0.66 GB** |
| **INGEST bundle** — client + MinerU + opendataloader-pdf | **3.18 GB** | **2.06 GB** |

Top of the client closure: `lancedb` 187 MB, `pyarrow` 82 MB, `pymupdf` 48 MB,
`numpy` 40 MB, `onnxruntime` 39 MB. Top of the ingest-only delta: `torch` 443 MB,
`cv2` 112 MB, `scipy` 103 MB, `av` 66 MB, `transformers` 50 MB, `pandas` 37 MB,
`opendataloader_pdf` 23 MB (a JAR — see below), `magika.exe` 24 MB.

**The plan expected 3–6 GB with MinerU and "well under 1 GB" without.** With comes in
at the bottom of that range (3.18 GB); without comes in slightly *over* the guess
(1.01 GB), because "well under 1 GB" appears not to have counted the 0.53 GB of ONNX
weights that S7 requires to be pre-bundled.

**Why the ceiling is 3.18 GB and not 6 GB:** on Windows, torch is a CPU build at
442.6 MB. Measured both from PyPI and from `download.pytorch.org/whl/cpu` — same
version, same size, same 102-package closure. That is a Windows fact, not a general
one: on Linux, PyPI torch bundles the nvidia CUDA runtime and is several GB, which is
where the 3–6 GB estimate almost certainly came from.

---

## Four things the measurement turned up that the plan did not anticipate

### 1. `opendataloader-pdf` needs a Java runtime on `PATH` — it is not bundled

The wheel is a 23 MB JAR plus a thin Python wrapper that shells out to
`java -Djava.awt.headless=true` and, if that fails, prints
`"Error: 'java' command not found. Please ensure Java is installed and in your
system's PATH."` (`opendataloader_pdf/runner.py:24,85`, read from the Windows wheel.)

It is one of the **two** extractors — `ingest/dispatcher.py` routes AFRs and the
Governor's Executive Budget to it, MinerU handles the JLBC Appropriations Reports and
Baseline Books. So a full-ingest machine needs Java, and S7's "no admin rights" rules
out installing a JRE on a locked-down PC. Options: bundle a headless JRE (~45 MB
jlink'd, adds a Java toolchain step to the builder and a redistribution question), or
make Java an IT prerequisite. **Whether Java is already on JLBC machines is unknown and
is a question for Destin, not something I can measure from here.**

### 2. MinerU 3.1.6 cannot be resolved wheel-only — one dependency ships sdist-only

The live corpus was extracted with **mineru 3.1.6** (confirmed:
`.venv/.../mineru-3.1.6.dist-info`, and `uv.lock` floors it at `>=3.1.6`). The plan
explicitly declines the 3.4.4 upgrade because it changes chunk text corpus-wide.

`mineru==3.1.6` → `omegaconf>=2.3.0` → `antlr4-python3-runtime==4.9.*`, and antlr4
4.9.x publishes **no wheel, only an sdist**. A `--only-binary=:all:` closure — which is
what S7's "prebuilt site-packages" means — therefore fails outright at 3.1.6.

Solvable, and cheaply: antlr4-python3-runtime is pure Python and builds to a
`py3-none-any` wheel (144 KB, built and verified), so one wheel built anywhere is valid
on Windows. The bundle builder pre-builds it into a local wheel dir and passes
`--find-links`. That is how the 3.1.6 number above was obtained.

**The trap to avoid:** `mineru[pipeline]>=3.1.6` resolves to **3.4.4**, which dropped
omegaconf and needs no help — so the naive spelling builds cleanly and silently
un-declines the decision the plan made. `packaging/measure.py` pins `==3.1.6` with that
reason written next to it. Note also that 3.1.6 is the *fatter* tree: 128 packages /
1.5 GB versus 3.4.4's 102 / 1.2 GB (3.1.6 pulls scipy, av, pandas, skimage, botocore).

### 3. `tiktoken` downloads its encoding at runtime, and fails **soft**

`chunking/builders/_tokens.py` wraps `tiktoken.get_encoding("cl100k_base")` in
`except Exception` and falls back to a 4-chars-per-token heuristic. tiktoken fetches
that encoding from `openaipublic.blob.core.windows.net` on first use unless
`TIKTOKEN_CACHE_DIR` is pre-populated (`tiktoken/load.py:37`).

So an offline ingest machine with an unprimed cache does not error — it quietly chunks
on different boundaries than every chunk already in LanceDB. Same class of harm as the
declined MinerU upgrade, arriving silently instead of loudly. The builder must
pre-populate `TIKTOKEN_CACHE_DIR` inside the bundle and the launcher must set it.

tiktoken's only consumers are `chunking/builder.py` and
`chunking/builders/table_chunk.py`, so it is ingest-only and off client machines
entirely — which confines this hazard to the designated ingest machine.

### 4. fastembed's default model cache is the Windows temp directory

`fastembed/common/utils.py:53` defaults `cache_dir` to
`os.path.join(tempfile.gettempdir(), "fastembed_cache")` — i.e. `%TEMP%` on Windows,
which Storage Sense and Disk Cleanup delete. A bundle that pre-seeds the default
location would work for weeks and then re-download 0.53 GB of weights on a machine with
no internet, or with an OpenRouter-only firewall exception. The launcher must set
`FASTEMBED_CACHE_PATH` to a folder inside the install directory.

---

## Is S7's "first run downloads nothing" achievable with MinerU in the bundle?

**Yes, on the evidence available — with four env vars the launcher must set, three of
which I verified by reading the shipped source and one of which is a Task 15 test.**

| Lever | Verified how |
|---|---|
| `FASTEMBED_CACHE_PATH=<install>/models` | `fastembed/common/utils.py:53-54` reads it; default is `%TEMP%/fastembed_cache` |
| `HF_HUB_OFFLINE=1` | `fastembed/common/model_management.py:397-401` flips `local_files_only=True` when it is `1/TRUE/YES/ON`. **This one is load-bearing**: without it, fastembed calls `model_info()` and `list_repo_tree()` against huggingface.co on *every* model construction even when the cache is complete (lines 235-236) |
| `MINERU_MODEL_SOURCE=local` + `MINERU_TOOLS_CONFIG_JSON=<abs path>` | `mineru/utils/models_download_utils.py:288-295` returns the configured local root and never touches the network; `mineru/utils/config_reader.py:17-22` accepts an absolute path for the config file |
| `TIKTOKEN_CACHE_DIR=<install>/tiktoken` | `tiktoken/load.py:37-38`; cache key is `sha1(url).hexdigest()`, so the builder must seed it by fetching once, not by copying a filename |

The honest caveat: those four cover the paths I traced. The ingest closure is 128
packages and includes `modelscope`, `magika`, `transformers`, and `robust-downloader` —
any of which could reach out on a code path I did not walk. **The only way to establish
"downloads nothing" is Task 15's acceptance test: unplug the network cable and watch
the server start and answer a query.** No amount of source reading substitutes for it,
and I am not going to claim the property on source reading alone.

---

## Decision: one bundle everywhere (decided 2026-08-01)

**Shape:** a single bundle, installed on all ~20 office PCs, carrying MinerU,
opendataloader-pdf, and a vendored Java runtime. Which machines actually *process*
uploads is an in-app setting, not a different download.

**Bundle size as decided:** 3.33 GB unzipped / 2.11 GB zipped (the ingest bundle above
plus the 146 MB JRE below).

### How the recommendation changed, and why

The section below this one recommended the **split**, and the load-bearing reason was
Java: asking IT for a JRE on two machines is routine, on twenty it is a project that
gets declined after Destin has left. Destin's constraint is stronger than the plan
assumed — **avoid IT requests entirely, and the machines do not have Java** — which sent
me to check whether Java could be vendored rather than requested.

It can, cheaply and legally: Eclipse Temurin publishes a standalone Windows x64 JRE as a
plain zip — **47 MB compressed, 146 MB unpacked** (downloaded and measured:
`OpenJDK21U-jre_x64_windows_hotspot_21.0.12_8.zip`, contains `bin/java.exe`). No
installer, no admin rights, no registry, and no JDK or `jlink` step on the build side.
It is GPLv2 **with the Classpath Exception** (`legal/java.base/ADDITIONAL_LICENSE_INFO`
in the shipped archive), which is precisely the license grant that permits redistributing
it inside another application.

`opendataloader_pdf/runner.py:24` invokes bare `"java"` through `subprocess.run`, so the
launcher redirects it to the bundled copy by prepending `<install>/jre/bin` to the child
process's `PATH`. Nothing outside the install directory is touched and no other Java on
the machine is affected.

With Java costing 146 MB and zero phone calls, the split's main argument evaporated. What
remained was disk (67 GB office-wide for one bundle vs 27 GB for the split) — and Destin
confirmed ~500 GB free per machine, which makes that a rounding error.

### Why one bundle wins once Java is free

The decisive argument is a failure mode, not a number. **With two artifacts, somebody
eventually installs the search-only one on the machine that was meant to do the
ingesting.** Uploads then queue on the share and are never drained: no error, no crash,
nothing that points at the cause. That is precisely the kind of silent failure that kills
a system a year after the person who built it has gone, and this project's defining
constraint is that it must survive exactly that.

With one bundle every machine is *capable*, and "which machine does the work" degrades
from an install-time decision that requires a reinstall to fix, into a setting that
requires a click.

Secondary: one artifact, one version number, one instruction sheet, and no "which one do
you have?" as the opening question of every future support conversation.

### The two things this decision obliges (hand-off to Session A, Task 17)

1. **An ingest-enabled setting, defaulting to OFF.** The seam already exists —
   `create_app(ingest_worker=None)` (Ground truth 2). Twenty machines with the worker on
   would not corrupt anything (`IngestLock` is single-writer), but one analyst's laptop
   would grind for six hours on a Baseline Book for no reason.
2. **A visible warning when uploads are queued and no machine is set to drain them.**
   Defaulting to OFF re-creates the silent pile-up this decision was made to avoid unless
   the admin page says so out loud.

### Considered and rejected — and S26 closes the door on it

The alternative to vendoring Java was dropping opendataloader-pdf entirely and routing
its doc types to MinerU. On today's `ingest/dispatcher.py` that looked almost free: the
Java extractor is reached by exactly **2 of the corpus's 2,490 documents** — one `afr`
and one `governors-budget` (EXTRACTOR_REGISTRY; counts from the live `documents.json`).
Everything else, all 2,104 fiscal notes included, is MinerU's.

**That framing is already obsolete.** Spec **S26** (added to master 2026-07-31, commit
`3019737`, after this investigation began) changes routing from "look up the doc_type the
user picked" to "inspect the file": *a PDF with a structure tree goes to OpenDataLoader
for cell fidelity, an untagged one to MinerU*, with the registry's declared extractor
demoted to a hint. Once S26 ships, the Java path is reachable by **any tagged PDF anyone
uploads** — including via S29's "Other document" route — not by two named doc types. The
"only 2 documents" number is a fact about the *current* dispatcher and must not be quoted
as a fact about the system.

So the rejection stands and is now firmer than when it was made: AFRs are tagged PDFs and
opendataloader was chosen for cell-level table fidelity on exactly that shape (dispatcher
docstring, chunk-shape D4), and under S26 that shape is no longer rare. **Do not revisit
dropping opendataloader on the strength of the 2-document count.**

Two consequences for the bundle, both already satisfied:

- The vendored JRE is not an edge-case convenience — it is on the main upload path.
  Confirming it actually runs on Windows is therefore part of Task 15's acceptance test,
  not a nice-to-have.
- S24's `data/document-types.yaml` does not yet exist; when it lands it ships
  automatically, because `build_bundle.py` selects files via `git ls-files` and nothing
  excludes `data/*.yaml`. No packaging change needed.

---

## Superseded recommendation: split — a client bundle everywhere, an ingest bundle on two machines

> Kept for the reasoning, not the conclusion. See [Decision](#decision-one-bundle-everywhere-decided-2026-08-01)
> above — vendoring Java removed this section's main premise.

**Size alone does not force the split.** 3.18 GB on disk and a 2.06 GB zip are
unpleasant but not disqualifying; if that were the only consideration, one bundle
everywhere would be the simpler, better answer, and I would say so.

Three non-size facts change it:

1. **Java (finding 1).** Asking IT to put a JRE on two machines is a routine request.
   Asking for it on every analyst's PC is a project, and it is the kind of ask that gets
   declined after Destin has left and nobody is there to push it.
2. **Blast radius (findings 2 and 3).** The pinned-3.1.6 constraint, the hand-built
   antlr4 wheel, and the tiktoken-cache trap are all *ingest* concerns. A client bundle
   that cannot extract cannot silently produce chunks that disagree with the corpus. The
   fussy artifact stays on two machines and the clean one goes everywhere.
3. **It matches how the office will actually work.** An i5-1245U runs MinerU at
   1–3 min/page, so a 210-page book is an overnight job wherever it runs; and
   `IngestLock` is single-writer by construction, so a second machine ingesting
   concurrently gains nothing anyway.

The dependency to state explicitly, as the plan asks: **the split relies on the worker
auto-start fix** (merged `f85b20a`, Ground truth 2). A client machine queues an upload
onto the share; the ingest machine's worker drains it. Without auto-start, a job queued
from machine B waits forever for someone to run a command on machine A.

**Two independent zips, not a base-plus-overlay.** I considered shipping one client
bundle plus an "ingest add-on" that unzips over it — it saves 0.66 GB of duplicated base
on two machines. It also introduces an invariant somebody has to maintain forever: every
file present in both trees must be byte-identical, or the ingest machine ends up running
a different numpy than it was resolved against. For a product whose defining constraint
is that a non-technical successor has to keep it working, two dumb self-contained zips
built from one script and stamped with one version number is the better trade. "Which
one do you have" is then answered by the folder name.

**How the open questions resolved** (2026-08-01): ~18–22 PCs, ~500 GB free on each, no
Java installed anywhere, and a hard preference for avoiding IT requests altogether. The
last of those is what sent me to vendor the JRE, which is what flipped the decision.

---

## VERIFIED ON WINDOWS — 2026-08-01, Destin's work laptop

First real Windows run. A machine that had never had Python, standard user account,
no admin rights. Bundle `0.1.0-test` (built on the Z13, Linux) transferred by USB and
extracted with `tar -xf` into `%LOCALAPPDATA%`.

```
> dir /s /b /a-d "%LOCALAPPDATA%\JLBC-Insight-0.1.0-test" | find /c /v ""
36102

> python\python.exe -c "import fastapi, uvicorn, lancedb, pyarrow, fastembed, fitz, docx, bs4, rapidfuzz; print('1 CORE OK')"
1 CORE OK

> python\python.exe -c "import mineru, torch, transformers, tiktoken; print('2 INGEST OK')"
2 INGEST OK

> python\python.exe -c "from app.main import create_app; print('3 APP OK')"
3 APP OK

> jre\bin\java.exe -version
openjdk version "21.0.12" 2026-07-21 LTS
OpenJDK Runtime Environment Temurin-21.0.12+8 (build 21.0.12+8-LTS)
OpenJDK 64-Bit Server VM Temurin-21.0.12+8 (build 21.0.12+8-LTS, mixed mode, sharing)
```

36102 files is an exact match for the archive's entry count, so the extraction was
complete rather than truncated. What each line settles, against the doubts recorded
below it:

- **The `._pth` edit works.** This was the top-ranked failure candidate — the
  interpreter could not see `site-packages` at all without it, and getting it wrong
  produces a bundle that builds perfectly and dies on the first import. It is right.
- **Windows wheels resolved from Linux genuinely run on Windows.** Every compiled
  extension that worried me — lancedb, onnxruntime (via fastembed), torch, pymupdf,
  tokenizers — imports. The cross-platform build approach is sound.
- **The app's own source imports inside the bundle**, so the layout mirroring the repo
  root is correct and `sys.path` reaches it.
- **The vendored Temurin JRE executes** with nothing installed and no admin rights,
  which is the premise the whole one-bundle decision rests on.

### Stage 2, same session — it runs

`install.cmd` completed (no security prompt, no admin elevation, shortcuts created), and
the Desktop shortcut started the server and opened the UI in a browser "relatively
quickly, without issue". So: uvicorn starts under the embeddable interpreter, the SPA is
served from `webapp/dist`, and the launcher's health-wait-then-open sequence works.

**Instance reuse works.** After clicking the shortcut several times,
`tasklist /FI "IMAGENAME eq pythonw.exe"` reported exactly one process. That is S8's
"relaunch reuses it" confirmed by process count rather than by how fast the window felt —
and it matters at 20 machines, where each analyst clicking the icon a few times a day
must not accumulate servers competing for the same files.

**No endpoint-security objection.** An unsigned interpreter running out of
`%LOCALAPPDATA%`, PowerShell creating two shortcuts, and a process listening on localhost
all passed without a prompt on this laptop. One machine's policy is not the estate's, but
it is the first evidence that this deployment shape survives JLBC's IT environment at
all — which was the largest non-technical risk to the whole no-admin-rights approach.

**One thing the first run changed.** The UI opened in Chrome's `--app` mode, per S8, and
Destin rejected it on sight: this is a reference tool consulted *alongside* a dozen
research tabs, and app mode makes it an island to alt-tab to. S8 is amended and
`open_window()` now passes a bare URL, so the app lands as a tab in the Chrome window the
analyst already has open. Worth recording as a method note — the design was defensible on
paper and wrong in ten seconds of contact with a real user, which is the argument for
getting a rough build in front of someone early rather than polishing first.

### Stage 3 — offline cold start: PASSED

WiFi disconnected, the running server killed so the next launch could not be a warm
reuse, then the shortcut clicked. It started and served exactly as it had online, and
the cold start was confirmed against the launcher's own log — `open_window()` writes a
`=== <timestamp> starting on port N ===` line per genuine start, and the newest one fell
inside the offline window.

**This is the acceptance criterion for Tasks 15 and 16, and it is now met:** the server
starts on a machine that has never had Python, with no network. S7's "first run downloads
nothing" holds in practice and not merely in the source-reading.

It also retroactively validates the four environment levers as a set. Each was traced
individually through the shipped library source; none had been *exercised* until the
network went away. Had any one been wrong — `HF_HUB_OFFLINE` in particular, which is the
difference between a populated cache and a cache fastembed still phones home to
validate — this run would have hung on a timeout rather than started.

## Still not verified

- **Real retrieval.** No corpus was attached; `create_app()` falls back to stub search
  fixtures when `budget_chunks` is empty (confirmed on Linux), so the interface can be
  exercised without proving the retrieval path.
- **opendataloader-pdf extracting a real document** with the bundled JRE.
- **`java` reached through `PATH` rather than by direct path.** `jre\bin\java.exe` ran
  when invoked explicitly; the launcher's `PATH` prepend, which is how
  opendataloader-pdf actually finds it, has not been exercised.
- **That opendataloader-pdf extracts a real document** using that JRE.
- **Corporate endpoint software.** This laptop ran an unsigned interpreter out of
  `%LOCALAPPDATA%` without objection, which is encouraging but is one machine's policy.
- **Zip and unzip times over the office SMB share.** Transfer here was USB.

The acceptance criterion is unchanged and is not yet met: **the server starting with
the network cable unplugged, on a machine that has never had Python.** The first half
of that sentence is still outstanding.
