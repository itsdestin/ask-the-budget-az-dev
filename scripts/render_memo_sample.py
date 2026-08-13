"""Render a sample memo and, if LibreOffice is present, a PNG of page 1.

EXISTS BECAUSE THE TEST SUITE CANNOT SEE THE PAGE. Every assertion in
`tests/test_jlbc_memo.py` measures a property — margins, font sizes,
column widths — and all 30 of them were green while the document looked
plainly wrong: an accent-blue masthead, unboxed section headings, and
roughly double the intended spacing throughout. The differences were only
found by rendering both files to images and comparing them.

    .venv/bin/python scripts/render_memo_sample.py

Writes /tmp/memo-sample.docx (+ .png), and copies the reference beside it
so the two can be opened together.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

# Run as a plain script from anywhere in the repo, the way every other
# tool in scripts/ is invoked; without this `import memo` fails.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import memo  # noqa: E402

REFERENCE = (
    Path(__file__).resolve().parents[1]
    / "samples" / "raw-docx" / "jlbc-staff-memorandum-style-reference.docx"
)
OUT = Path("/tmp/memo-sample.docx")

BODY = """## Highlights

- Start with documents saved in e:/27app, which reflect each agency's Baseline narrative.
- As always, change "The Baseline includes" to "The budget includes" and update the footer.
- Remember to label issues as one-time where appropriate.

## Data Entry

Please see the attached email from me for more detailed BUDS instructions.

### Policy Issues

Use the Detailed Policy Issue Lists in the June 11 summary packet.

| Fund | FY 2026 | FY 2027 |
|---|---|---|
| General Fund | $12,400,000 | $14,200,000 |

## Submission

Please review the attached Agency Sample and Analyst Checklist prior to submitting.
"""


def main() -> None:
    memo.render(
        BODY,
        subject="FY 2027 AHCCCS Appropriations Summary",
        sender="A. Analyst",
        recipient="",
    ).save(str(OUT))
    print(f"wrote {OUT}")

    if REFERENCE.exists():
        shutil.copy(REFERENCE, "/tmp/memo-reference.docx")
        print("wrote /tmp/memo-reference.docx (the real JLBC memo, for comparison)")

    if shutil.which("libreoffice"):
        subprocess.run(
            ["libreoffice", "--headless", "--convert-to", "pdf",
             "--outdir", "/tmp", str(OUT)],
            check=False, capture_output=True, timeout=300,
        )
        if shutil.which("pdftoppm"):
            subprocess.run(
                ["pdftoppm", "-png", "-r", "80", "-f", "1", "-l", "1",
                 "/tmp/memo-sample.pdf", "/tmp/memo-sample-page"],
                check=False, capture_output=True, timeout=120,
            )
            print("wrote /tmp/memo-sample-page-1.png — LOOK AT THIS ONE")
    else:
        print("LibreOffice not found; open the .docx by hand to check it")


if __name__ == "__main__":
    main()
