# MinerU 2.5 Extractor Setup

## Version
- mineru: 3.1.6 (with `[pipeline]` extra)
- torch: 2.11.0+cpu
- torchvision: 0.26.0
- transformers: 4.57.6
- shapely: 2.x (transitively via `mineru[pipeline]`)
- Python: 3.12.13
- Hardware: CPU only (CUDA unavailable on this machine)
- OS: Windows 11

## Real-world install findings (Phase 0 — costly to discover, document so others don't repeat)

1. **MinerU 3.1.6 has no stable Python API.** The plan's baseline `from mineru import parse_pdf` does NOT work — that symbol doesn't exist. The only public interface is the `mineru` CLI tool, which spawns a temporary local FastAPI server and submits work to it. Our wrapper invokes the CLI via `subprocess.run` and translates its output (one `.md` + one `_content_list.json` per document) into our per-page contract.

2. **Bare `mineru` does NOT install the pipeline backend's deps.** The package's published `Requires-Dist` only covers infrastructure (boto3, fastapi, openai, etc.). The actual extraction backends are gated behind extras:
   - `mineru[pipeline]` — torch, torchvision, shapely, pyclipper, ftfy, dill, omegaconf, onnxruntime, transformers
   - `mineru[vlm]` — transformers + accelerate (vision-language model backend)
   - `mineru[vllm]`, `mineru[lmdeploy]`, `mineru[mlx]` — alternative inference backends

   Installing bare `mineru` and then running it gets you a `ModuleNotFoundError: No module named 'torch'`, then `'shapely'` after you fix torch, then more. Fix: install the extra you intend to use. For our CPU-only Windows setup, `mineru[pipeline]` is correct.

3. **Resolution conflict pitfall.** During iteration, `transformers>=5.7.0` got stuck in `pyproject.toml` as a direct dep. `mineru[pipeline]` requires `transformers>=4.57.3,<5.0.0`. Removing the stray direct dep resolved it. If you see "your project depends on mineru[pipeline] and transformers>=5.x.x... unsatisfiable," check `[project] dependencies` in `pyproject.toml` for an unintended `transformers` line.

## CLI reference
- Default backend is `hybrid-auto-engine` (wants GPU). Use `-b pipeline` for CPU-only runs — that's the "more general" backend per `mineru --help`.
- Page bounds (`-s` / `-e`) are 0-indexed and inclusive.
- Output goes to `<output-dir>/<pdf-stem>/<parse_method>/`. The `parse_method` subdirectory name varies; the wrapper discovers it by scanning for the only directory inside `<pdf-stem>/`.

## Output structure observed
For one document, MinerU's pipeline backend writes (under `<out>/<pdf-stem>/<method>/`):
- `<stem>.md` — Markdown rendering of all parsed pages, concatenated
- `<stem>_content_list.json` — array of structured blocks. Each block carries `type`, `text` (or alternatives), `bbox` (PDF points: `[x1, y1, x2, y2]`), `page_idx` (0-indexed; we normalize to 1-indexed)
- `<stem>_content_list_v2.json` — newer block format
- `<stem>_middle.json`, `<stem>_model.json` — internal layout/model debug data
- (image files in an `images/` sibling)

Our wrapper reads `<stem>_content_list.json` and `<stem>.md`, buckets blocks by 1-indexed page, and emits per-page JSON + Markdown.

## Smoke test
- PDF: `samples/raw-pdfs/agao-afr-fy25.pdf`, page 1 (1-indexed) → `-s 0 -e 0`
- Wall-clock: 2m 26s (includes one-time model load on first real run; subsequent runs reuse the loaded models within the same Python process)
- Output: `page-1.json` (3.6 KB, 9 blocks with bbox coords), `page-1.md` (1.1 KB)
- Result: PASS — extracted text matches the AFR's Dec 5 2025 cover letter (Katie Hobbs / Elizabeth Alvarado-Thorson signatures, ARS § 35-131 citation, Department of Administration footer)
- Heading detection works: `Dear Governor Hobbs:` carries `text_level: 2`

## Known footguns observed
- The CLI exits with code 0 even when the inner parse task fails (the API server itself ran fine). Check stderr output for `Error: 1 task(s) failed` — our wrapper raises if it can't read the expected output files, which catches this.
- Each CLI invocation reloads models, so per-page invocation in a long page list is wasteful. The wrapper collapses contiguous page ranges into single CLI invocations (see `_contiguous_ranges`) to amortize this.

## Reproduction
From the worktree root:

```
uv run python scripts/run_mineru.py --pdf <pdf> --out <dir> --pages <range>
```

where `<range>` is 1-indexed (e.g., `1`, `1-5`, `1,3,5-7`).
