# Bundle size — measurement spike and distribution-shape decision

**Date:** 2026-08-01
**Plan:** `docs/superpowers/plans/2026-08-01-standalone-plan-5-admin-packaging.md`, Track 3 Task 14
**Spec:** S7 (unzip to `%LOCALAPPDATA%`, embeddable Python, all model weights pre-bundled, first run downloads nothing), S8 (launcher → Chrome `--app`)
**Status:** measured; decision pending Destin
**Reproduce:** `python packaging/measure.py --profile both --find-links <dir with the antlr4 wheel>`

---

## What was measured, and where

Every size below is a **Windows** closure — real `x86_64-pc-windows-msvc` wheels for
CPython 3.12, resolved and downloaded by `uv pip install --target --python-platform`,
then unpacked and byte-counted. The *machine* doing the resolving was the Z13 (Linux);
uv resolves for a foreign platform, so these are Windows sizes measured from Linux.

**Nothing here was executed on Windows.** No Python ran, no server started, no import
was attempted. The size numbers are hard; every claim about *behaviour* on a JLBC PC is
marked as such in [Not verified](#not-verified--this-is-what-task-15-is-for) below.

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

## Recommendation: split — a client bundle everywhere, an ingest bundle on two machines

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

**What Destin needs to decide** (Task 15 does not start until he does):

- One bundle everywhere at 3.18 GB, or the split at 1.01 / 3.18 GB?
- If split: is Java already on the machines that would do ingest, or does the builder
  need to vendor a headless JRE?
- Are 30-ish office PCs really the scale, or is it closer to 5? At 5 machines the disk
  argument for splitting mostly evaporates and only the Java and blast-radius arguments
  remain — they still hold, but it is a closer call.

---

## Not verified — this is what Task 15 is for

Everything in this section is **inferred from Linux** and could be wrong.

- **That any of this imports on Windows.** Zero Windows execution happened. `lancedb`,
  `onnxruntime`, `torch`, `pymupdf`, and `tokenizers` all ship compiled extensions.
- **That the embeddable runtime can load a `--target` site-packages at all.** The
  shipped `python312._pth` is two lines (`python312.zip`, `.`) with `import site`
  commented out, so the builder must edit it. This is a well-known, well-documented
  step — but "well-known" is not "tested", and it is the single thing most likely to
  turn a clean build into a bundle that does not start.
- **That `uv pip install --target`'s layout is right for Windows.** It wrote console
  scripts to `bin/`, not `Scripts/`. Probably irrelevant — the launcher calls uvicorn
  programmatically rather than through a console script — but unproven.
- **Whether Java is present on JLBC machines.**
- **First-run offline behaviour** beyond the four traced levers.
- **Zip and unzip times over the office SMB share.** 2.06 GB compressed on hardware and
  a network I have not touched.

The acceptance criterion for Task 15 stands as the plan wrote it: **the server starting
with the network cable unplugged, on a machine that has never had Python.** A successful
build is not evidence of anything.
