"""The diagnostic's verification core (packaging/diag/diag.pyw).

Mechanism tests, not quality tests — no real LanceDB, no ONNX, no network.
The manifest/compare/copy functions are pure path+size logic; the guarded
open_check is exercised against a synthetic lancedb/ folder whose only
claim is that it exists. This mirrors the testing convention: the legacy
tests/ suite runs on a fresh clone with no corpus, and the diagnostic's
verification must work the same way.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

# diag.pyw cannot be imported by name or by spec (a .pyw file is not
# importable — even spec_from_file_location returns None for it), so execute
# its code in a private module namespace. It has no side effects at import
# time, so this is equivalent to importing the same module body.
_DIAG = Path(__file__).resolve().parents[1] / "packaging" / "diag" / "diag.pyw"
_ns: dict = {"__file__": str(_DIAG), "__name__": "jlbc_diag"}
exec(_DIAG.read_text(encoding="utf-8"), _ns)
diag = type("diag", (), _ns)  # namespace object with attribute access


@pytest.fixture
def tree(tmp_path: Path) -> tuple[Path, Path]:
    """A USB seed (tmp/usb) and a network copy (tmp/net) with known content."""
    usb = tmp_path / "usb"
    net = tmp_path / "net"
    for root, files in (
        (usb / "lancedb", {"a.lance": b"x" * 100, "b.lance": b"y" * 200}),
        (usb / "pdfs", {"one.pdf": b"z" * 50}),
        (usb, {"documents.json": b"{}"}),
    ):
        for name, body in files.items():
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_bytes(body)
    # network copy: same files, but b.lance is HALF-copied and one.pdf missing
    shutil.copytree(usb, net)
    (net / "lancedb" / "b.lance").write_bytes(b"y" * 100)
    (net / "pdfs" / "one.pdf").unlink()
    net.mkdir(parents=True, exist_ok=True)
    return usb, net


def test_manifest_records_relpaths_and_sizes(tree: tuple[Path, Path]) -> None:
    usb, _net = tree
    mf, nfiles, nbytes = diag.manifest(usb)
    assert mf["lancedb/a.lance"] == 100
    assert mf["lancedb/b.lance"] == 200
    assert mf["pdfs/one.pdf"] == 50
    assert mf["documents.json"] == 2
    assert nfiles == 4
    assert nbytes == 352


def test_compare_finds_missing_and_half_copied(tree: tuple[Path, Path]) -> None:
    usb, net = tree
    usb_mf, _f, _b = diag.manifest(usb)
    net_mf, _f, _b = diag.manifest(net)

    diff = diag.compare(usb_mf, net_mf)
    missing = {r for r, _ in diff["missing"]}
    mismatch = {(r, s, n) for r, s, n in diff["mismatch"]}

    assert missing == {"pdfs/one.pdf"}
    assert mismatch == {("lancedb/b.lance", 200, 100)}
    assert diff["ok"] == 2  # a.lance + documents.json
    # 50 bytes missing + 100 bytes short = 150
    assert diff["bytes_missing"] == 150


def test_repair_copies_missing_then_compare_is_clean(tree: tuple[Path, Path]) -> None:
    usb, net = tree
    usb_mf, _f, _b = diag.manifest(usb)
    net_mf, _f, _b = diag.manifest(net)
    diff = diag.compare(usb_mf, net_mf)

    items: list[tuple[str, int, int | None]] = (
        [(r, s, None) for r, s in diff["missing"]]
        + [(r, s, n) for r, s, n in diff["mismatch"]]
    )
    copied, failures = diag.copy_missing(usb, net, items)
    assert copied == 2
    assert failures == []

    net_mf, _f, _b = diag.manifest(net)
    after = diag.compare(usb_mf, net_mf)
    assert after["missing"] == []
    assert after["mismatch"] == []
    assert after["ok"] == 4


def test_open_check_does_not_create_lancedb(tmp_path: Path) -> None:
    """The health-ladder rule: never manufacture the thing you're checking."""
    empty = tmp_path / "empty"
    empty.mkdir()
    ok, _msg = diag.open_check(empty)
    assert ok is False
    assert not (empty / "lancedb").exists()


def test_redact_drops_secret_lines() -> None:
    text = (
        "healthy startup\n"
        "provider api_key sk-or-v1-abc123\n"
        "normal line\n"
    )
    out = diag.redact_text(text)
    assert "sk-or-v1" not in out
    assert out.count(diag.REDACTED_VALUE) == 1
    assert "normal line" in out