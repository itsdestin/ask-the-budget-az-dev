"""Build data/fund-catalog.yaml from one or more s18-style cross-cut PDFs.

Usage:
    uv run python scripts/build_fund_catalog.py \
        --source jlbc-s18-fy2027:samples/extractor-output/jlbc-baseline-fy27/s18 \
        --source jlbc-bd2-fy2026:samples/extractor-output/jlbc-approps-fy26/bd2 \
        --out data/fund-catalog.yaml

Each `--source` is `<source-id>:<extractor-output-path>`. The extractor
output is whatever `chunking.readers.MinerUReader` knows how to read —
either a single page-N.json or a directory of page-*.json.

Source ids carry weight: they're recorded verbatim in `present_in` per
plan §4.1 step 5 (`[jlbc-s18, jlbc-bd2, agao-afr]`-style). Use stable
short ids that downstream consumers can recognize.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make the project root importable so `chunking.*` and `funds.*` resolve when
# this script is invoked directly (`uv run python scripts/build_fund_catalog.py ...`).
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from chunking.readers.mineru_reader import MinerUReader  # noqa: E402
from funds.catalog import build_fund_catalog, write_catalog_yaml  # noqa: E402
from funds.parser import FundAgencyRow, parse_s18_table  # noqa: E402


def parse_source_arg(s: str) -> tuple[str, Path]:
    if ":" not in s:
        raise argparse.ArgumentTypeError(
            f"--source expects '<source-id>:<path>', got: {s!r}"
        )
    src_id, _, raw_path = s.partition(":")
    src_id = src_id.strip()
    path = Path(raw_path.strip())
    if not src_id:
        raise argparse.ArgumentTypeError(f"--source id is empty in: {s!r}")
    if not path.exists():
        raise argparse.ArgumentTypeError(f"--source path does not exist: {path}")
    return src_id, path


def collect_rows(source_id: str, path: Path) -> list[FundAgencyRow]:
    """Read the extractor output at `path` and parse its table(s) into rows."""
    doc = MinerUReader().read(path)
    rows = parse_s18_table(doc)
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build data/fund-catalog.yaml from s18-style cross-cut PDFs.",
    )
    parser.add_argument(
        "--source",
        action="append",
        required=True,
        type=parse_source_arg,
        help="Source spec '<source-id>:<extractor-output-path>'. Repeatable.",
    )
    parser.add_argument(
        "--out",
        default="data/fund-catalog.yaml",
        type=Path,
        help="Output YAML path (default: data/fund-catalog.yaml)",
    )
    args = parser.parse_args(argv)

    sources_spec: list[tuple[str, list[FundAgencyRow]]] = []
    for src_id, path in args.source:
        rows = collect_rows(src_id, path)
        print(
            f"[{src_id}] parsed {len(rows)} fund-agency rows from {path}",
            file=sys.stderr,
        )
        sources_spec.append((src_id, rows))

    catalog = build_fund_catalog(sources=sources_spec)
    sources_ids = [src_id for src_id, _ in sources_spec]
    write_catalog_yaml(args.out, catalog, sources=sources_ids)

    print(
        f"Wrote {len(catalog)} fund entries to {args.out} "
        f"from {len(sources_spec)} source(s).",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
