# ROCm vs CPU for MinerU on the Ryzen AI MAX+ 395 — measured

**Date:** 2026-07-31
**Question:** does MinerU extract meaningfully faster on this machine's
Radeon 8060S iGPU (ROCm) than on CPU, and is the output identical?
**Answer:** ROCm works with no fuss, but it is **not worth using for the
backfill**. It is 1.05× on an 8-page agency page and 1.29× on a 28-page
report; extrapolated over the ~6,800-document backfill (median 2 pages)
it is a wash-to-slightly-worse. Its output is also **not byte-identical**
to the CPU path on the MinerU version this repo pins.
**Recommendation: stay on CPU.** The real speed lever found here is a
MinerU version bump (see "The finding that actually matters").

Nothing in this investigation touched `pyproject.toml`, `uv.lock`, or
`.venv/`. The only committed changes are this file and a `.gitignore`
line for the throwaway `.venv-rocm/`.

---

## 1. Does ROCm work at all? Yes, out of the box

| | |
|---|---|
| Host ROCm | 7.2.4 at `/opt/rocm`, `amdgpu` loaded, `/dev/dri/renderD128` world-rw |
| Wheel index | `https://download.pytorch.org/whl/rocm7.2` |
| torch | `2.13.0+rocm7.2` (5.8 GiB wheel) |
| torchvision | `0.28.0+rocm7.2` |
| triton | `triton-rocm==3.7.1` |
| `torch.version.hip` | `7.2.53211` |
| `torch.cuda.is_available()` | `True` |
| `torch.cuda.get_device_name(0)` | `AMD Radeon 8060S` |
| `gcnArchName` | `gfx1151` |
| Visible memory | 81,920 MB (4 GiB VRAM carve-out + 80 GiB GTT — unified memory) |
| `HSA_OVERRIDE_GFX_VERSION` | **not needed.** gfx1151 has native wheel support in this build |

Compute was verified, not just detection: a 4096³ fp32 matmul on device
matched the CPU result to 1.0e-3 (normal fp32 accumulation-order error),
so kernels really run.

**Reproduce the venv:**

```bash
uv venv .venv-rocm --python 3.12
uv pip install --python .venv-rocm \
  --index-strategy unsafe-best-match \
  --extra-index-url https://download.pytorch.org/whl/rocm7.2 \
  "mineru[pipeline]==3.1.6" \
  "torch==2.13.0+rocm7.2" "torchvision==0.28.0+rocm7.2" \
  six
```

Two gotchas:

- **Pin torch on the command line or you download ~4 GB of NVIDIA
  wheels for nothing.** PyPI's default `torch` for linux is the CUDA
  build; installing `mineru[pipeline]` first pulls `nvidia-cuda-nvrtc`,
  `nvidia-cusparse`, `nvidia-nvshmem`, … before you ever get to replace
  it. The first attempt here wasted ~45 minutes doing exactly that.
- **`six` is a missing transitive dependency** of the pipeline backend
  and must be installed explicitly, or every run dies with
  `ModuleNotFoundError: No module named 'six'` *inside* MinerU's task
  worker, which surfaces as a generic "1 task(s) failed".

MinerU needs no flag to use the GPU: `mineru/utils/config_reader.py`
`get_device()` returns `"cuda"` whenever `torch.cuda.is_available()`, and
under a ROCm build that is the HIP device. `MINERU_DEVICE_MODE=cpu`
forces CPU in the same venv — which is what made the controlled
comparison below possible.

---

## 2. What was measured

Two real documents already in `data/cached-pdfs/`, both table-heavy:

| | doc | pages |
|---|---|---|
| **A** | `c3a2c78fdd5f95f30242e57b189ab244bf9fa543f1bcd31588c0ad06938464c3.pdf` — *FY 2027 Baseline Book — University of Arizona - Main Campus* | 8 |
| **B** | `941cc3b3b6e56b1fae20ac77474bb330aebb87a6b3df998f0a07834573423b33.pdf` — *FY 2025 Appropriations Report — Department of Education* | 28 |

Invocation is the one `ingest/mineru_runner.py` uses:
`mineru -p <pdf> -o <out> -s 0 -e <n> -b pipeline`.

Three arms, so the device effect could be separated from the torch-build
effect. All model downloads and MIOpen kernel compilation were warmed out
before timing; reps were interleaved so background load hit all arms alike.

| arm | venv | torch | device |
|---|---|---|---|
| `main-cpu` | `.venv` (repo) | 2.11.0+cu128 | CPU (no NVIDIA GPU present) |
| `rocm-gpu` | `.venv-rocm` | 2.13.0+rocm7.2 | **GPU** |
| `rocm-cpu` | `.venv-rocm` | 2.13.0+rocm7.2 | CPU (`MINERU_DEVICE_MODE=cpu`) |

MinerU pinned to **3.1.6** in both venvs — the version `uv.lock` pins —
except where explicitly noted in §5.

---

## 3. Speed

**Doc A, 8 pages, 3 interleaved reps (ms):**

| arm | reps | mean | sec/page | vs main-cpu |
|---|---|---|---|---|
| `main-cpu` | 37 836 / 38 886 / 38 815 | **38.5 s** | 4.81 | 1.00× |
| `rocm-gpu` | 36 401 / 36 448 / 37 153 | **36.7 s** | 4.58 | **1.05×** |
| `rocm-cpu` | 39 382 / 40 008 / 40 812 | 40.1 s | 5.01 | 0.96× |

**Doc B, 28 pages, 4 reps each:**

| arm | reps | mean | sec/page | vs main-cpu |
|---|---|---|---|---|
| `main-cpu` | 81 798 / 67 588 / 69 107 / 67 672 | **68.1 s** | 2.43 | 1.00× |
| `rocm-gpu` | 52 672 / 53 077 / 52 652 / 52 942 | **52.8 s** | 1.89 | **1.29×** |

Run-to-run spread inside an arm is under 2% except the one `main-cpu`
outlier at 81.8 s, which coincided with a concurrent ingest job (load 20.6).

**Fitting the two page counts gives the shape of the cost:**

```
main-cpu :  T = 26.7 s + 1.48 s/page
rocm-gpu :  T = 30.2 s + 0.81 s/page
```

The GPU is **1.8× faster per page** — and **3.5 s slower to start**,
because the models have to be pushed to the device. Break-even is at
**~5 pages**. Below that the GPU loses; above it, it wins, and the win
grows with document length.

Single-page runs confirm the fixed cost directly: `main-cpu` 31.5 / 32.5 s,
`rocm-cpu` 32.7 / 33.4 s, `rocm-gpu` 33.6 s. Startup dominates a small
document completely.

**Why so modest?** This is an APU. The CPU cores and the 8060S share one
power and thermal budget, so moving work to the iGPU does not add
headroom, it relocates it. Measured during doc B:

| | package temp peak | package power peak | GPU busy peak |
|---|---|---|---|
| GPU run | 79 °C | 64 W | 91% |
| CPU run | 72 °C | 62 W | (idle-desktop baseline ~30%) |

Same watts, 7 °C hotter, 1.29× the throughput. A discrete GPU would be a
different conversation; an iGPU on a shared power budget is not.

### The MIOpen warm-up tax

The **first** GPU run against a new MinerU version or a genuinely new page
shape triggers MIOpen kernel compilation, and it is brutal:

| | first run | settled |
|---|---|---|
| doc A, 1 page | 70.9 s | 33.6 s |
| doc A, 8 pages | 205.2 s | 36.7 s |
| doc B, 28 pages | **468.7 s** (7.8 min) | 52.8 s |

The cache at `~/.cache/miopen` persists, so this amortizes — but across a
heterogeneous 6,800-document backfill it will fire repeatedly, and each
time it does it eats the entire GPU advantage for dozens of documents.
None of the numbers in §3 include it.

---

## 4. Extrapolating the backfill

Page counts of the 386 PDFs currently cached: **median 2 pages**, 56% are
1–2 pages, only 12 documents exceed 20 pages. The backfill is ~4,700
per-agency/summary PDFs (mostly 1–10 pages) plus ~2,126 fiscal notes (2–5).

Applying the fitted models at a 4-page mean for budget PDFs and 3.5 for
fiscal notes:

| | CPU (`main-cpu`) | ROCm GPU |
|---|---|---|
| 4,700 budget PDFs | 32.6 s ea → **42.6 h** | 33.4 s ea → **43.7 h** |
| 2,126 fiscal notes | 31.9 s ea → **18.8 h** | 33.0 s ea → **19.5 h** |
| **total** | **≈ 61 h** | **≈ 63 h** |

The GPU is *slightly worse* over the realistic backfill, because the
workload is thousands of short documents and the per-process startup
penalty outweighs the per-page gain. It only becomes worth it on the long
books:

| document | CPU | ROCm GPU |
|---|---|---|
| 28-page approps report | 68 s | 53 s (1.29×) |
| 181-page Governor's budget | ~4.9 min | ~3.0 min (1.66×) |
| 636-page volume | ~15.9 min | ~8.9 min (1.79×) |

---

## 5. Fidelity — the part that decides it

Comparison is on MinerU's `_content_list.json`, because that array is
copied verbatim into `page-N.json` by `write_range_pages()` in
`scripts/run_mineru.py`. A difference there is a difference in ingested
chunk text and in the bboxes citations highlight against.

**Every arm is internally deterministic** — three reps of `main-cpu`,
two of `rocm-gpu`, and two of `rocm-cpu` each produced byte-identical
output. So the noise floor is zero and every cross-arm difference below
is real.

**On MinerU 3.1.6 (the pinned version), GPU output differs from CPU
output.** Same venv, same MinerU, device is the only variable:

- 155 blocks both sides, same per-page block counts, **0 missing bboxes**,
  max bbox coordinate delta **0.0**
- **4 of 155 blocks differ — all of them tables**

The differences are OCR/table-structure level, and they cut both ways:

| | CPU | GPU |
|---|---|---|
| footnote marker | `21,237,2005/` ✗ (fuses the `5/` into the number) | `21,237,200 5/` ✓ |
| word spacing | `SUMMARY OF FUNDS` ✓ | `SUMMARYOFFUNDS` ✗ (twice) |
| a figure in prose | `$1,125,0,00` ✗ | (garbled differently) |
| **row alignment** | `Personal Services  400,654,500` ✓ | `Employee Related Expenditures  400,654,500` ✗ |

That last row is the disqualifying one. Ground truth from
`pdftotext -layout` is `Personal Services 400,654,500`. Under 3.1.6 the
CPU path lands it on the right line item and the GPU path shifts it down
one row — **a real dollar figure attributed to the wrong budget line**.
(Both paths then mis-align the *next* row, so 3.1.6's FY-2025 column is
partly broken on either device; the GPU is just broken differently.)

Two controls worth recording:

- `rocm-cpu` vs `main-cpu` — same MinerU, same device, different library
  versions — already differ in **2 of 155** blocks. So part of the drift
  is dependency versions, not the GPU.
- On **MinerU 3.4.4** the same GPU-vs-CPU comparison is **byte-identical**
  (160 blocks, 24,057 chars, both sides). The device-sensitivity is a
  3.1.6-era table-model artifact, not something intrinsic to ROCm.

**Verdict: unacceptable at the pinned version.** Not because the GPU is
worse — sometimes it is better — but because running half a corpus on one
device and half on the other means the same document type extracts two
different ways, and one of the differences moves money between line items.

---

## 6. The finding that actually matters

While pinning versions for the controlled comparison, a fresh
`mineru[pipeline]>=3.1.6` resolved to **MinerU 3.4.4**, and it beats the
GPU question on both axes:

| doc A, 8 pages | CPU | GPU |
|---|---|---|
| MinerU 3.1.6 | 38.5 s | 36.7 s |
| **MinerU 3.4.4** | **28.5 s** | 23.9 s |

**MinerU 3.4.4 on plain CPU is 1.35× faster than 3.1.6 on plain CPU** —
a bigger win than ROCm delivers, with no new venv, no HIP, and no
device-dependent output.

And it extracts *better*. The header row that 3.1.6 mangles:

```
3.1.6  Personal Services              (blank)      399,693,400   398,875,200
       Employee Related Expenditures  400,654,500  132,163,100   131,901,300     <- wrong row

3.4.4  Personal Services              400,654,500  399,693,400   398,875,200     <- correct
       Employee Related Expenditures  133,959,300  132,163,100   131,901,300     <- correct
```

3.4.4 also splits `OPERATING BUDGET` from `Full Time Equivalent Positions`
into separate rows, preserves `FY 2025` spacing, and keeps `•` bullets —
160 blocks vs 155 on the same 8 pages. It is not perfect (it still
mis-aligns `Professional and Outside Services` / `Travel - In State`), but
it is strictly closer to the source.

**This deserves its own gated evaluation before the backfill.** A MinerU
bump changes chunk text and therefore chunk boundaries corpus-wide, so it
needs `uv run python -m eval.run_eval` on both sides and a decision about
re-ingesting what is already stored. It is out of scope here; it is
recorded because it is the highest-value thing this benchmark turned up.

---

## 7. If you want to use ROCm anyway

The seam already exists — `resolve_mineru_exe()` in
`ingest/mineru_runner.py` honours `JLBC_MINERU_EXE`:

```bash
JLBC_MINERU_EXE=/home/destin/YouCoded/Projects/ask-the-budget-az-dev/.venv-rocm/bin/mineru \
  uv run uvicorn app.main:create_app --factory --port 9300
```

`MINERU_DEVICE_MODE` is optional (`cuda` is auto-detected under a ROCm
torch); set it to `cpu` to force the CPU path inside the same venv.

Caveats if you do:

- **Only worth it above ~5 pages.** Below that it is slower than CPU.
- **Budget 4–8 minutes of MIOpen compilation** the first time a new page
  shape appears, and expect it to recur across a heterogeneous corpus.
- **Do not mix devices within one corpus** at MinerU 3.1.6 — §5.
- **Stability was fine.** ~30 GPU invocations including one 7.8-minute
  run, zero crashes, zero `amdgpu` faults or resets in `dmesg`, peak
  79 °C / 64 W. Memory is a non-issue: the 4 GiB VRAM carve-out is backed
  by 80 GiB of GTT on unified memory.
- `.venv-rocm/` is **16 GB**. `rm -rf .venv-rocm` when done; it is
  gitignored and reproducible from the command in §1.

---

## 8. Recommendation

**Run the backfill on CPU.** ROCm is real, stable, and correctly detected
on this box, but on this workload it buys 1.05–1.29× — about −2 h to +2 h
across a ~61 h job, inside the noise of one interrupted overnight run —
while introducing device-dependent table extraction at the pinned MinerU
version.

Spend the effort on the MinerU 3.1.6 → 3.4.4 upgrade instead: 1.35× on
CPU, better tables, device-invariant output. Gate it on the eval set.
