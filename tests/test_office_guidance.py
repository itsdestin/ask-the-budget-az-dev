"""Office guidance file + its prompt slot (spec E2).

THE PROPERTY THAT MATTERS MOST: with no guidance file, the rendered
prompt is byte-identical to the template with the slot removed — this
feature invisible is this feature safe.
"""
import pytest

import harness.office_guidance as og
from harness.prompt import build_system_prompt, reset_template_cache


@pytest.fixture(autouse=True)
def _guidance_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(og, "guidance_path", lambda: tmp_path / "office-guidance.md")
    monkeypatch.setattr(og, "meta_path", lambda: tmp_path / "office-guidance.meta.json")
    og.reset_guidance_cache()
    yield
    og.reset_guidance_cache()


def test_missing_file_renders_nothing():
    assert og.office_guidance_block() == ""


def test_a_normal_missing_file_stays_silent(capsys):
    # The fixture's tmp_path (the ROOT) exists; only office-guidance.md is
    # missing — most offices never write one, and that must not log.
    assert og.office_guidance_block() == ""
    assert capsys.readouterr().err == ""


def test_a_vanished_share_still_renders_empty_but_logs_why(monkeypatch, tmp_path, capsys):
    # IMPORTANT 2 (review): a gone share used to remove the office's
    # guidance from every prompt with no trace in this module at all — the
    # ROOT ("gone-share") itself was never created, unlike the fixture
    # above where only the guidance file is missing. This module must
    # NEVER raise (its own module docstring), so the prompt still renders
    # with no guidance either way; only the stderr trail differs.
    monkeypatch.setattr(og, "guidance_path", lambda: tmp_path / "gone-share" / "office-guidance.md")
    og.reset_guidance_cache()
    assert og.office_guidance_block() == ""
    assert "cannot read" in capsys.readouterr().err


def test_block_carries_the_conflicts_lose_preamble():
    og.save_office_guidance("Prefer the AFR for fund balances.", "destin")
    block = og.office_guidance_block()
    assert "Prefer the AFR for fund balances." in block
    assert "those rules win" in block  # the fixed preamble


def test_cap_is_enforced_at_save():
    with pytest.raises(ValueError):
        og.save_office_guidance("x" * (og.MAX_GUIDANCE_BYTES + 1), "destin")


def test_save_keeps_a_bak_of_the_previous_version():
    og.save_office_guidance("first", "destin")
    og.save_office_guidance("second", "destin")
    assert og.guidance_path().with_suffix(".md.bak").read_text(encoding="utf-8") == "first"


def test_meta_records_who_and_when():
    og.save_office_guidance("text", "destin")
    meta = og.load_guidance_meta()
    assert meta["edited_by"] == "destin" and meta["edited_at"]


def test_prompt_is_byte_identical_when_guidance_absent():
    # Render with no file, then with an EMPTY file — both must equal each
    # other; and rendering with real text must differ only by the block.
    reset_template_cache()
    empty = build_system_prompt(corpus="budget", tier="standard")
    og.save_office_guidance("", "destin")
    og.reset_guidance_cache()
    assert build_system_prompt(corpus="budget", tier="standard") == empty
    og.save_office_guidance("OFFICE-MARKER-XYZ", "destin")
    og.reset_guidance_cache()
    with_text = build_system_prompt(corpus="budget", tier="standard")
    assert "OFFICE-MARKER-XYZ" in with_text
    assert with_text.replace(og.office_guidance_block(), "") == empty


def test_both_corpora_receive_the_block():
    og.save_office_guidance("OFFICE-MARKER-XYZ", "destin")
    og.reset_guidance_cache()
    for corpus in ("budget", "fiscal_notes"):
        assert "OFFICE-MARKER-XYZ" in build_system_prompt(corpus=corpus, tier="standard")


def test_building_a_prompt_never_loads_lancedb():
    """Global constraint (spec E2 plan): harness/prompt.py -> office_guidance
    -> store.config must stay stdlib + store.config only. store/__init__.py
    used to import store.chunk_store eagerly, which imports lancedb — that
    would make every prompt build (including the hot per-step path) pull
    LanceDB, onnxruntime, and retrieval into the process. Guard it directly
    rather than trust the AST import-allowlist test
    (test_harness_prompt.py::test_prompt_py_does_not_import_the_map_builder_or_the_store),
    which only inspects harness/prompt.py's own import statements and
    cannot see this transitive path. All three roots are checked, not just
    LanceDB, because that's what the constraint actually names."""
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import harness.prompt; "
            "roots = ('lancedb', 'onnxruntime', 'retrieval'); "
            "hits = [r for r in roots if r in sys.modules "
            "or any(m.startswith(r + '.') for m in sys.modules)]; "
            "print(hits)",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "[]", result.stdout + result.stderr


def test_guidance_containing_placeholder_syntax_does_not_raise():
    # Ordering guard (review finding, Task 5 Minor 5): the splice runs
    # AFTER `_substitute`, so admin prose that happens to contain a
    # `{{...}}`-shaped string must render, not be mistaken for a real
    # template placeholder and raise PromptTemplateError office-wide.
    reset_template_cache()
    og.save_office_guidance("Use the {{FOO}} format for citations.", "destin")
    og.reset_guidance_cache()
    out = build_system_prompt(corpus="budget", tier="standard")
    assert "{{FOO}}" in out


def test_guidance_with_backslash_escapes_survives_the_splice():
    # re.sub replacement-form guard (review finding, Task 5 Minor 5): a
    # STRING replacement interprets `\1` as a backreference and a
    # trailing backslash raises re.error outright. The splice uses a
    # callable replacement (`lambda _match: block`) specifically so
    # admin prose containing either is spliced in literally.
    reset_template_cache()
    text = "See item \\1 in the packet.\\"
    og.save_office_guidance(text, "destin")
    og.reset_guidance_cache()
    out = build_system_prompt(corpus="budget", tier="standard")
    assert text in out
