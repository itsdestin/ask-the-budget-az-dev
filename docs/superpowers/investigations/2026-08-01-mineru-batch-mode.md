# MinerU batch-mode behaviour and batch-size curve

**Date:** 2026-08-01
**Plan:** [Standalone Plan 7 — batch extraction](../plans/2026-08-01-standalone-plan-7-batch-extraction.md), Task 1
**Status:** measurement spike. No production code was written.
**Machine:** Z13 — Ryzen AI MAX+ 395, `nproc` = 32, 121 GB RAM, Linux. `mineru==3.1.6` (pinned; not upgraded).

---

## Headline

> ### ⚠ Ground truth 2 is FALSE as written. One bad PDF CAN kill its entire batch.
>
> A **truncated** PDF aborts the whole `mineru -p <dir>` invocation with **zero
> output for every one of its batch-mates**. It is not per-file tolerant in that
> case. The design needs a guard — but the guard is cheap and the failure is
> benign in shape, for reasons below. **This does not sink the plan; it adds one
> preflight step.**
>
> Two further surprises in the same area:
> - a **zero-byte** and a **garbage** PDF are *silently dropped* — `rc=0`, no
>   warning anywhere in the log, batch completes. A document can vanish with no
>   error at all.
> - the abort happens in MinerU's **input-collection preflight**, before any
>   extraction. It costs 3.3 s, not a wasted batch.

Everything else the plan assumes holds. Batch mode is real, supported, and
substantially faster: **3.6×–6.9× depending on batch size**, and the
amortization was still improving at the largest size tested.

**One correction to the plan's numbers:** Task 4 proposes
`JLBC_INGEST_BATCH=20 JLBC_INGEST_WORKERS=12`. That pairing is **not memory-feasible
on this machine** — 12 × 8.1 GB ≈ 97 GB of peak RSS on a 121 GB box that already
has ~24 GB in use. See [Memory](#memory--the-actionable-part).

---

## What was measured, and how to reproduce it

**Sample.** 40 real per-agency JLBC book pages drawn from the live corpus at
`<data_dir>/pdfs/` (content-hash sharded), selected as
`doc_type in {baseline-per-agency, approps-per-agency}` with `2 ≤ page_count ≤ 6`
— the shape that carries essentially all of the remaining backfill volume.
Selection was `random.seed(7)` over the sorted candidate list, so it is
reproducible. Distribution: 149 pages total; 14 docs × 2pp, 4 × 3pp, 8 × 4pp,
7 × 5pp, 7 × 6pp; fiscal years 2022–2026.

**Every PDF was staged under its `doc_id`**, never its original filename
(Ground truth 4). Confirmed necessary: the pool contains distinct documents that
would otherwise collide on stem.

```bash
# batch path (what the plan proposes)
mineru -p <staging_dir> -o <out_dir> -b pipeline

# one-at-a-time path (production shape today — _run_range in ingest/mineru_runner.py)
mineru -p <one.pdf> -o <out_dir> -s 0 -e <pages-1> -b pipeline
```

Wall clock, peak RSS of the whole process tree (sampled from `/proc/<pid>/stat`
every 0.4 s), and `/proc/loadavg` before and after were recorded for every run.
Driver scripts and raw `results.jsonl` / `results2.jsonl` are in the session
scratchpad; the numbers below are copied from those records, not from file
timestamps.

### Machine contention — stated plainly

The machine was **shared** for the first half of this work: sibling agents were
running pytest suites and an idle app server sat on port 9300. External load was
roughly 1–2 cores of 32 (one sibling pegged at ~95% of a core).

The measurements are protected two ways rather than asserted to be clean:

1. **A-B-A ordering.** `batch20` → `serial20` → `batch20 again`. The two batch
   runs bracket the serial run, so a load shift shows up as disagreement between
   them instead of as a clean-looking wrong ratio. They disagree by **23.5%**
   (234.45 s vs 179.41 s) — which is exactly why the speedup is reported below
   as a range and not as one number. The most likely cause is page-cache warmth
   on the ~5.5 GB of model weights: the second run was faster *despite* starting
   at a higher load average (11.1 vs 5.2).
2. **An external cross-check on the serial half.** Serial measured **41.6 s/doc
   mean, 36.0 s median → 87 docs/hr**. STATUS.md independently records ~40 s/doc
   and 93 docs/hr serial on this same machine. The serial baseline is therefore
   *at* its known value and is not inflated by contention — so the speedup is
   not an artifact of a slowed-down denominator.

The batch-size curve (5/10/40) was run later, on a quiet machine.

---

## The batch-size curve

Documents vary 2–6 pages, so **s/page is the honest normalizer** and s/doc is
included only because it is what the plan speaks in.

| N per batch | pages | wall s | s/doc | **s/page** | docs/hr | peak tree RSS | peak single proc |
|---|---|---|---|---|---|---|---|
| 1 (serial, ×20) | 78 | 832.03 | 41.60 | **10.67** | 87 | 3.94 GB | 2.39 GB |
| 5 | 20 | 63.80 | 12.76 | **3.19** | 282 | 4.47 GB | 3.05 GB |
| 10 | 40 | 95.33 | 9.53 | **2.38** | 378 | 5.09 GB | 3.67 GB |
| 20 (cold cache) | 78 | 234.45 | 11.72 | **3.01** | 307 | 8.08 GB | 5.58 GB |
| 20 (warm cache) | 78 | 179.41 | 8.97 | **2.30** | 401 | 7.89 GB | 5.39 GB |
| 40 | 149 | 230.34 | 5.76 | **1.55** | 625 | 11.69 GB | 8.41 GB |

**Speedup vs one-at-a-time, per page:** 3.3× at B=5, 4.5× at B=10, 3.5×–4.6× at
B=20 (the cold/warm spread), **6.9× at B=40**.

**For the 20-document comparison the plan asks for specifically:**
832.03 s serial vs 234.45 s / 179.41 s batch = **3.55× (pessimistic, cold batch)
to 4.64× (warm batch)**; ~**4.0×** at the mean of the two batch runs. Report the
range. The 23.5% spread between two identical runs is larger than any precision
a single number would imply.

**No knee was found.** Amortization was still improving at B=40, the largest size
tested. B=40 was not a plateau — it was the edge of the measurement. If wall
clock matters more than memory, B is worth pushing past 40 in Task 4.

### Why it works — confirmed, not assumed

Every `mineru` invocation logs `Started local mineru-api at http://127.0.0.1:<port>`
and stands up its own Uvicorn service before doing any work. This appears in
**both** the batch and the one-at-a-time logs. So the CLI already uses the
client/server shape internally; batch mode simply pays for it once per *batch*
instead of once per *document*. This is the same ~33 s model load the plan
identifies — reclaimed **without** the shared long-lived server that corrupted
the heap and failed 101 documents (Ground truth 8). `JLBC_MINERU_API_URL` was
left unset throughout.

---

## The three properties

### (a) Output is per-input-file and mappable by stem — ✅ TRUE

MinerU writes `<out>/<stem>/auto/<stem>_content_list.json` plus `<stem>.md`,
`images/`, and the debug PDFs — **one directory per input file, named by input
stem**. 20 inputs → 20 output directories; 40 → 40.

This is exactly the layout `_read_mineru_output(mineru_out, pdf_stem)` in
`scripts/run_mineru.py` already expects (it resolves `<root>/<stem>/<method>/`
by discovering the single method subdirectory). **Demux needs no new parsing** —
point the existing reader at `<batch_out>/<doc_id>` and it works unchanged.

**Caveat that matters:** see (b) — a missing output directory is a *silent*
outcome, so the demux must assert one directory per staged doc_id rather than
iterating whatever it finds.

### (b) One corrupt PDF fails alone and the batch completes — ❌ FALSE (with a cheap fix)

Three malformed shapes were tested, each in a batch with 2 healthy documents:

| bad input | rc | wall | outputs | verdict |
|---|---|---|---|---|
| zero-byte (the real orphan blob `e3b0c44…pdf` in the corpus's own pdf store) | 0 | 37 s | **2 of 3** | tolerated — but **silently dropped** |
| garbage (`%PDF-1.7` header + 5 KB random) | 0 | 36 s | **2 of 3** | tolerated — but **silently dropped** |
| **truncated (first 40% of a real PDF)** | **1** | **3 s** | **0 of 3** | **FATAL — kills every batch-mate** |

And the combined batch (5 healthy + all 3 bad) produced **zero output in 3.3 s**.

**Exact failure**, from `mineru`'s traceback:

```
mineru/cli/client.py:511  collect_input_documents
  → mineru/cli/client.py:475  probe_pdf_effective_pages
    → mineru/utils/pdfium_guard.py:27  open_pdfium_document
      → pypdfium2._helpers.misc.PdfiumError:
          Failed to load document (PDFium: Data format error).
```

Two facts change how bad this is:

1. **It is a preflight failure, not a mid-run one.** `collect_input_documents`
   opens every input up front to count pages, *before any extraction begins*.
   The uncaught `PdfiumError` kills the CLI at that point. So the blast radius
   is "the batch produced nothing", not "the batch died halfway and left partial
   state" — and it costs **3.3 seconds**, not a wasted batch of extraction.
2. **The plan's Z13 observation was probably about a different failure class.**
   Ground truth 2 cites `Error: 1 task(s) failed while processing documents` and
   the batch continuing. That is a failure *during processing* — a PDF that
   opens but does not extract. This spike shows MinerU is tolerant there and
   intolerant at *load* time. Both statements can be true; the plan generalized
   from the wrong one.

**Recommended fix (for Task 2, ~10 lines).** Before staging, open each candidate
with `pypdfium2` — already a MinerU dependency, so no new package — and count
its pages. Exclude any that raise, and fail those documents individually with
the real `PdfiumError` message. This converts the batch-killing case into the
per-document failure the design wants, and it is nearly free: the same probe
MinerU itself does, at milliseconds per file. It also gives `run_batch` the page
counts it needs for the `BATCH_MAX_PAGES` eligibility rule in Task 3 anyway.

**Second, independent guard — do not skip this one.** The zero-byte and garbage
cases returned **`rc=0` with no warning of any kind** (46 log lines, the
filename never mentioned). A document that MinerU silently declines to process
is indistinguishable from success at the CLI level. `run_batch` must therefore
**assert that every staged doc_id produced an output directory** and quarantine
the missing ones with an explicit reason. Without that check a document silently
disappears from the corpus while its job reports `live` — the exact failure
shape as the FY2024 AFR, which STATUS.md already flags as the case where
"nothing flagged it".

### (c) Per-document text is byte-identical batch vs one-at-a-time — ⚠ NO, but harmlessly

**17 of 20 documents are byte-identical.** The other 3 differ by **exactly one
character each**, always inside a `table_body` HTML string:

| document | delta | size of table | numeric tokens |
|---|---|---|---|
| `jlbc-approps-fy2022-azh` | insert `' '` | 1 char of 1,513 (0.07%) | 43 vs 43 — **identical** |
| `jlbc-baseline-fy2023-lot` | delete `'/'` (a `1/` footnote marker) | 1 char of 5,228 (0.02%) | 138 vs 138 — **identical** |
| `jlbc-baseline-fy2024-lan` | `'o'` → `'O'` | 1 char of 2,512 (0.04%) | 81 vs 81 — **identical** |

**Every numeric token is identical in all three.** No dollar figure moves, no row
or column restructures, no block-count change, and the narrative (`type: text`)
blocks are identical across all 20 documents. This is the specific thing that
got the ROCm path rejected — "device-dependent table extraction that put a real
dollar figure on the wrong budget line" — and it is **not** happening here.

**What actually causes it — isolated, not guessed.** Four variants of the same 3
documents were compared:

| comparison | result |
|---|---|
| batch-20 vs batch-20 again (same composition) | **20/20 identical** — MinerU is deterministic run-to-run |
| batch-20 vs batch-**3** | 3/3 differ |
| batch-20 vs single doc, **no** `-s/-e` | 3/3 differ |
| batch-20 vs single doc, **with** `-s/-e` (production shape) | 3/3 differ |
| batch-3 vs single-no-range vs single-with-range | **all three identical to each other** |

So it is **not** run-to-run nondeterminism, and **not** the `-s/-e` page-range
flags. Output depends on **batch composition** — almost certainly padding inside
the table-recognition model's batched inference. A batch of 3 gives byte-identical
output to a single document; only the larger batch shifts.

**The consequence worth recording:** under batching, a document's extracted table
text stops being a pure function of the document and becomes a function of
`(document, batch-mates)`. Re-ingesting the same PDF in a different batch can
change one character of one table. Given the magnitude measured — single
characters, zero numbers — this is acceptable, but it should be a *known*
property rather than a surprise the first time someone diffs a re-ingest.

---

## Memory — the actionable part

Peak RSS of the whole invocation tree, measured:

| batch size | peak tree RSS | peak single process |
|---|---|---|
| 1 (serial) | 3.94 GB | 2.39 GB |
| 5 | 4.47 GB | 3.05 GB |
| 10 | 5.09 GB | 3.67 GB |
| 20 | 7.89–8.08 GB | 5.39–5.58 GB |
| 40 | 11.69 GB | 8.41 GB |

Fitted on the two least-contended points: **≈ 2.9 GB fixed + ~0.22 GB per document
in the batch.** The fit under-predicts the middle of the range by up to ~0.8 GB
(it says 7.29 GB at B=20 where 7.89–8.08 GB was measured), so **size from the
measured rows, not the fit**.

The plan's Risk 3 asks whether batching raises the per-process peak. **It does,
substantially** — from 2.4 GB per document serial to 8.4 GB for a single
batch-40 process. The existing ~2.1 GB/concurrent-document figure does not
transfer to batching.

### Recommended pairing for this 121 GB / 32-thread machine

Peak memory is `WORKERS × (per-invocation peak at that batch size)`, because each
worker runs its own `mineru` process with its own model set.

| `WORKERS` × `BATCH` | peak RSS | verdict |
|---|---|---|
| **12 × 20 — what Task 4 proposes** | **~97 GB** | ❌ **infeasible.** ~24 GB is already in use; this leaves nothing and will swap or OOM |
| 12 × 10 | ~61 GB | feasible on memory, but CPU-oversubscribed (see below) |
| 8 × 20 | ~65 GB | feasible; likely CPU-bound |
| **4 × 20** | **~32 GB** | ✅ **recommended starting point** |
| 4 × 40 | ~47 GB | ✅ stretch target if Task 4 shows CPU headroom |

**Recommendation: `JLBC_INGEST_WORKERS=4 JLBC_INGEST_BATCH=20`, moving to
`BATCH=40` if the live run shows headroom.**

The reason to drop workers from 12 to 4 is not only memory. **Batch mode already
parallelizes internally** — a 2-document batch was observed at 431% CPU, and the
recorded serial knee of ~8 workers was measured against invocations that were
*not* internally parallel. Stacking 12 batch workers on 32 threads oversubscribes
the CPU on top of the memory problem.

### The honest limit of this recommendation

**Concurrent batch throughput was not measured.** Every run here was a single
`mineru` invocation at a time. The pairing above is derived from measured
per-invocation memory and CPU behaviour, not from a measured multi-worker run.
Task 4 should treat it as a starting point to verify, not a tuned optimum.

---

## What this implies for the plan's headline claim

The plan promises the remaining backfill goes from **~3.7 h to roughly one hour**.
Measured single-process rates:

- one-at-a-time, 1 process: **87 docs/hr**
- batch-40, 1 process: **625 docs/hr**
- current production, 12 serial workers: **945 docs/hr** (recorded in STATUS.md)

So **a single batch-40 process reaches 66% of the throughput of twelve serial
workers**, using roughly a third of the memory and far less CPU. That efficiency
gain is real and is the strongest result here.

But for *wall clock*, batching alone is not enough — it has to compose with
workers. ~3,500 documents in one hour needs ~3,500 docs/hr, i.e. **5.6× scaling
over one batch-40 process**. At the recommended 4 workers that requires near-linear
scaling, which the serial curve (7.5× at 8 workers, then flat) suggests is
unlikely once MinerU's own serial phases and the serialized write dominate.

**A defensible projection is ~2 hours, not ~1.** 4 × 20 at even 2.5× scaling
efficiency gives ~1,000 docs/hr; 4 × 40 at 2.5× gives ~1,560 docs/hr → ~2.2 h.
Better than today, and worth doing — but the plan's "roughly one" should be
restated before it becomes an expectation someone plans a day around.

---

## Verdicts

| Property | Verdict |
|---|---|
| (a) per-file output, mappable by stem | ✅ **TRUE.** `<out>/<stem>/auto/<stem>_content_list.json`; the existing reader works unchanged |
| (b) one corrupt PDF fails alone | ❌ **FALSE.** A truncated PDF aborts the whole batch, 0 outputs, in preflight. Zero-byte and garbage are tolerated but **silently dropped**. Needs a pypdfium2 preflight **and** an every-doc_id-produced-output assertion |
| (c) byte-identical to one-at-a-time | ⚠ **NO — 17/20.** 3 documents differ by one character each in table HTML; **all numeric tokens identical**. Caused by batch composition, not nondeterminism or `-s/-e` |
| speedup at 20 documents | **3.55×–4.64×**, ~4.0× at the batch mean |
| best measured | **6.9×/page at B=40**, 625 docs/hr single-process; no knee found yet |
| peak RSS | 4.5 GB @ B=5 → 8.1 GB @ B=20 → **11.7 GB @ B=40** |

## Does anything contradict the plan's design?

Three things, in descending order of consequence:

1. **Ground truth 2 is wrong as stated** — batch mode is not per-file tolerant at
   PDF-load time. The plan's own Risk 1 anticipated this possibility and asked
   the spike to find out; it did. **The design survives** with one preflight
   validation step added to Task 2, because the abort is in preflight and costs
   3.3 s. Batch size does not become a blast radius *provided* the guard exists.
2. **Task 4's `WORKERS=12 BATCH=20` is not runnable on this machine** (~97 GB).
   Use 4 × 20.
3. **"3.7 h → roughly one hour" is optimistic**; ~2 h is the defensible figure.

Nothing contradicts the core architecture: `-p <directory>` is a supported path,
output demux is trivial and needs no new parsing, staging by `doc_id` is
necessary and sufficient for the collision problem, and the model-load
amortization the plan is built on is real and larger than its 2.85× estimate.

**One addition to Task 2's test list**, beyond what the plan already specifies:
a test that a staged document producing **no** output directory is reported as a
per-document failure. The plan lists "one input producing no output leaves the
others complete" — the silent-drop finding makes that test the one guarding
against a document vanishing from the corpus without an error, so it should
assert the *reason* surfaces, not merely that the others survived.
