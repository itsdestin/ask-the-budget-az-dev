"""Search across titles and message text in the history store (Plan: H4)."""
import pytest

from harness import history


@pytest.fixture(autouse=True)
def _tmp(tmp_path, monkeypatch):
    monkeypatch.setenv("JLBC_HISTORY_DIR", str(tmp_path / "conversations"))


def _seed(cid, title, texts):
    history.save(history.Transcript(
        id=cid, title=title, corpus="budget",
        created_at="2026-08-02T10:00:00+00:00",
        updated_at=f"2026-08-02T10:0{len(cid)}:00+00:00",
        messages=[{"role": "assistant", "content": t} for t in texts],
    ))


def test_matches_message_text_not_just_the_title():
    _seed("a", "Budget question", ["The Florence prison closure saved $12.4 M."])
    hits = history.search("Florence")
    assert [t.id for t, _ in hits] == ["a"]


def test_matches_the_title_too():
    _seed("a", "Florence closure", ["unrelated body"])
    assert [t.id for t, _ in history.search("Florence")] == ["a"]


def test_the_snippet_contains_the_matching_line():
    _seed("a", "Budget question", ["line one", "The Florence prison closure saved money."])
    _t, snippet = history.search("Florence")[0]
    assert "Florence" in snippet
    assert "line one" not in snippet


def test_search_is_case_insensitive():
    _seed("a", "Budget question", ["FLORENCE prison"])
    assert history.search("florence")


def test_no_match_returns_nothing():
    _seed("a", "Budget question", ["something else"])
    assert history.search("Florence") == []


def test_results_omit_message_bodies():
    _seed("a", "Budget question", ["Florence prison"])
    t, _ = history.search("Florence")[0]
    assert t.messages == []


def test_a_corrupt_file_does_not_break_search():
    _seed("good", "Budget question", ["Florence prison"])
    (history.conversations_dir() / "bad.json").write_text("{oops", encoding="utf-8")
    assert [t.id for t, _ in history.search("Florence")] == ["good"]


def test_an_empty_query_returns_nothing_rather_than_everything():
    _seed("a", "Budget question", ["Florence"])
    assert history.search("   ") == []


def test_retrieved_corpus_text_is_not_searched():
    """H4 as amended: search the CONVERSATION, not what retrieve() returned.

    A tool result's `content` is a JSON string, so a plain isinstance(str)
    filter does not exclude it. Without this, "Florence" matches every chat
    where some retrieved passage happened to mention Florence, and the
    snippet is a slice of a JSON payload.
    """
    history.save(history.Transcript(
        id="a", title="Budget question", corpus="budget",
        created_at="2026-08-02T10:00:00+00:00",
        updated_at="2026-08-02T10:00:00+00:00",
        messages=[
            {"role": "user", "content": "what did ADC spend?"},
            {"role": "tool", "tool_call_id": "t1", "name": "retrieve",
             "content": '{"chunks": [{"text": "Florence prison closure"}]}'},
            {"role": "assistant", "content": "ADC spent $1.2 billion."},
        ],
    ))
    assert history.search("Florence") == []
    assert [t.id for t, _ in history.search("ADC")] == ["a"]
