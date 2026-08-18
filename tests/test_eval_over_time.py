"""Archive mechanics. tmp_path only — never eval/results itself."""
import json
from eval.over_time import append_run, segments, render_trend_md


def _run(tmp_path, name, sha, corpus_n, kf_rate):
    d = tmp_path / name; d.mkdir()
    (d / "manifest.json").write_text(json.dumps({
        "git_sha": "abc", "queries_sha256": sha,
        "corpus_counts": {"budget_chunks": corpus_n},
        "tier_models": {"standard": "m"}, "timestamp": "2026-08-16T0000Z"}))
    (d / "scores.json").write_text(json.dumps({
        "summary": {"key_fact_rate": kf_rate, "tokens_to_accurate_mean": 100,
                    "turns_to_accurate_mean": 3, "accurate_n": 2,
                    "document_correctness_mean": 0.8, "total_cost_usd": 0.4,
                    "n": 3, "errors": 0}, "per_query": [], "skipped": []}))
    return d


def test_append_writes_index_and_jsonl(tmp_path):
    append_run(tmp_path, _run(tmp_path, "r1", "aaa", 100, 0.9), {"sets": ["quick"], "workers": 1, "model": "m"})
    append_run(tmp_path, _run(tmp_path, "r2", "aaa", 100, 0.8), {"sets": ["quick"], "workers": 1, "model": "m"})
    lines = (tmp_path / "over-time" / "metrics.jsonl").read_text().strip().split("\n")
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["queries_sha256"] == "aaa" and first["profile"]["sets"] == ["quick"]
    index = json.loads((tmp_path / "over-time" / "index.json").read_text())
    assert len(index) == 2


def test_segments_split_on_sha_or_corpus_change(tmp_path):
    rows = [
        {"run": "r1", "queries_sha256": "aaa", "corpus_counts": {"budget_chunks": 100}},
        {"run": "r2", "queries_sha256": "aaa", "corpus_counts": {"budget_chunks": 100}},
        {"run": "r3", "queries_sha256": "bbb", "corpus_counts": {"budget_chunks": 100}},  # query edit
        {"run": "r4", "queries_sha256": "bbb", "corpus_counts": {"budget_chunks": 101}},  # re-ingest
    ]
    segs = segments(rows)
    assert [len(s) for s in segs] == [2, 1, 1]


def test_append_is_refused_without_a_manifest(tmp_path):
    d = tmp_path / "nomanifest"; d.mkdir()
    import pytest
    with pytest.raises(FileNotFoundError):
        append_run(tmp_path, d, {})


def test_append_is_idempotent_per_run(tmp_path):
    r = _run(tmp_path, "r1", "aaa", 100, 0.9)
    append_run(tmp_path, r, {})
    append_run(tmp_path, r, {})  # re-score of the same run
    lines = (tmp_path / "over-time" / "metrics.jsonl").read_text().strip().split("\n")
    assert len(lines) == 1
