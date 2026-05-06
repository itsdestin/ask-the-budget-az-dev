# Chunking-layer test fixtures

Hand-crafted, structurally faithful samples of each extractor's output, used
to test `chunking/readers/` without re-running the heavy extractors during
unit tests.

| Fixture | Mirrors | Purpose |
|---------|---------|---------|
| `odl-afr-p163.json` | OpenDataLoader-PDF v2.4.1 per-page output (`<out>/page-N.json`) | Exercises ODLReader: heading hierarchy (Doctitle→H1→H2), paragraph in section, nested-cell table, image block |
| `mineru-jlbc-approps-p513.json` | MinerU 3.x `_content_list.json` | Exercises MinerU reader: text_level→heading, HTML table parsing, multi-page table reassembly |
| `docx-sb1735-sample.json` | python-docx output of `scripts/run_docx_ingest.py` | Exercises DOCX reader: bill heading parsing, SEC 06-* style detection, A.R.S. capture |

**Synthetic ≠ real.** Phase 0 source PDFs and DOCX (in
`samples/raw-pdfs/` / `samples/raw-docx/`) are gitignored and not present in
fresh clones. WS6 (Week-4 validation) regenerates these fixtures from the
real corpus by re-running each extractor on a small page slice and
overwriting the synthetic versions. The shape stays identical — synthetic
fixtures encode the schema contract that real ODL/MinerU/python-docx
produces, so the readers stay valid across both.
