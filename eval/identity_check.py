"""The identity ERROR-RATE instrument's CLI (spec I13, gate G-I2).

The check itself — the `IdentityReport` shape and the pure `check_corpus`
logic — moved to `identity/check.py` on 2026-08-16 (see that module's
docstring for why: `ingest/worker.py` ships to office PCs and `eval/` does
not, so shipped code may never import from here). This module is now only
the command-line wrapper: parse arguments, run the check, write the JSON
report, print the human-readable summary.

The names below are re-exported from `identity.check` so any existing
`from eval.identity_check import ...` keeps working unchanged.

Usage:
    uv run python -m eval.identity_check [--data-dir PATH] [--json PATH]

Writes `<data_dir>/identity-report.json`, which the admin page's
Needs-attention group renders (spec I15).
"""
from __future__ import annotations

import argparse
from pathlib import Path

from identity.check import (  # noqa: F401 — re-exported for backward compat
    IdentityReport,
    _load_live,
    check_corpus,
    write_report,
)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", type=Path, default=None)
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args(argv)

    report, out = write_report(args.data_dir, args.json)
    payload = report.as_dict()

    for k, v in payload.items():
        if k != "findings":
            print(f"{k}: {v}")
    print(f"findings: {len(payload['findings'])}  →  {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
