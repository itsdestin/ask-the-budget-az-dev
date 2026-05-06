"""Verify that local files in samples/raw-pdfs/ and samples/raw-docx/ match
the SHA256 checksums declared in samples/manifest.yaml.

Exits 0 if all manifest entries verify, 1 otherwise. Reports missing files,
checksum mismatches, and orphan files (present on disk but not in manifest)
separately to stderr.
"""

import hashlib
import sys
from pathlib import Path

import yaml

MANIFEST = Path("samples/manifest.yaml")
RAW_PDF_DIR = Path("samples/raw-pdfs")
RAW_DOCX_DIR = Path("samples/raw-docx")


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    if not MANIFEST.exists():
        print(f"manifest missing: {MANIFEST}", file=sys.stderr)
        return 1

    # Defensive YAML parse: a hand-edit miscount of indentation should produce
    # a clear "FAIL: ..." line, not a raw Python traceback. Destin (non-dev)
    # may edit the manifest by hand, so each shape failure is enumerated.
    try:
        manifest = yaml.safe_load(MANIFEST.read_text())
    except yaml.YAMLError as e:
        print(f"FAIL: malformed YAML in {MANIFEST}: {e}", file=sys.stderr)
        return 1

    if not isinstance(manifest, dict) or "documents" not in manifest:
        print(f"FAIL: {MANIFEST} missing top-level 'documents' key", file=sys.stderr)
        return 1
    documents = manifest["documents"]
    if not isinstance(documents, list):
        print(f"FAIL: 'documents' in {MANIFEST} is not a list", file=sys.stderr)
        return 1

    failures = []
    declared_paths = set()
    for i, doc in enumerate(documents):
        if not isinstance(doc, dict):
            failures.append(f"entry [{i}] is not a mapping")
            continue
        for required in ("local_path", "sha256"):
            if required not in doc:
                failures.append(f"entry [{i}] (id={doc.get('id', '?')}) missing required key: {required}")
        if "local_path" not in doc or "sha256" not in doc:
            continue  # can't verify this entry; the failure was recorded above
        local = Path(doc["local_path"])
        declared_paths.add(local)

        if not local.exists():
            if doc["sha256"]:
                failures.append(f"missing: {local}")
            continue

        if not doc["sha256"]:
            print(f"NOTE: {local} downloaded but checksum not yet recorded")
            continue

        actual = sha256_of(local)
        if actual != doc["sha256"]:
            failures.append(f"checksum mismatch: {local}\n  expected: {doc['sha256']}\n  actual:   {actual}")

    # Format-aware orphan scan: check both raw-pdfs/ and raw-docx/.
    # Each directory is optional — if missing entirely, skip it (e.g., a fresh
    # run before any downloads, or a test fixture that only stages one format).
    for raw_dir, glob in [(RAW_PDF_DIR, "*.pdf"), (RAW_DOCX_DIR, "*.docx")]:
        if raw_dir.exists():
            for found in raw_dir.glob(glob):
                if found not in declared_paths:
                    failures.append(f"orphan (not in manifest): {found}")

    if failures:
        for msg in failures:
            print(f"FAIL: {msg}", file=sys.stderr)
        return 1

    print("OK: all manifest entries verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
