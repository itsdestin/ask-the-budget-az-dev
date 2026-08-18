"""The marker grammar. Markers are the model's provenance claims; they
must strip cleanly out of every consumer-visible string, including the
malformed shapes a model under load actually produces."""
from __future__ import annotations

from citation.markers import Tag, parse_markers, strip_for_stream


def test_well_formed_marker_is_stripped_and_recorded():
    stripped, tags = parse_markers("grew to $8,287.7 million [[c3]] this year")
    assert stripped == "grew to $8,287.7 million this year"
    assert tags == [Tag(aliases=("c3",), at=25)]
    # The offset indexes the STRIPPED text: position 25 is where the
    # marker used to sit, i.e. right after "million ".
    assert stripped[:tags[0].at].endswith("million ")


def test_multi_alias_marker():
    stripped, tags = parse_markers("fell [[c3, c12]].")
    assert stripped == "fell ."
    assert tags[0].aliases == ("c3", "c12")


def test_bracket_wrapped_multi_alias_marker_does_not_leak():
    # Real models sometimes wrap each alias in its own brackets
    # ([[c3],[c4]]) instead of the documented [[c3,c4]]. The old
    # malformed-marker regex stopped at the FIRST `]`, stripping
    # only "[[c3]" and leaking ", [c4]]" into the rendered answer —
    # a P1 UI bug (report: "revenue of $18.33 billion ,[c4]]").
    stripped, tags = parse_markers(
        "revenue of $18.33 billion [[c3],[c4]]. Here's the next sentence"
    )
    assert stripped == "revenue of $18.33 billion . Here's the next sentence"
    assert stripped.find("[") == -1
    assert stripped.find("]") == -1
    # Aliases are cleaned of their wrapping brackets.
    assert tags[0].aliases == ("c3", "c4")
    # Longer chains and spaces between bracket pairs parse too.
    stripped2, tags2 = parse_markers("x [[c3], [c4], [c12]] y")
    assert stripped2 == "x y"
    assert tags2[0].aliases == ("c3", "c4", "c12")


def test_bracket_wrapped_marker_offset_indexes_stripped_text():
    stripped, tags = parse_markers("grew [[c1],[c2]] fast")
    assert stripped == "grew fast"
    # The marker starts right after "grew ".
    assert stripped[: tags[0].at].endswith("grew ")
    assert tags[0].aliases == ("c1", "c2")


def test_unterminated_bracket_wrapped_chain_strips_without_leak():
    # A final answer cut by max_tokens, or a streaming frame, can end
    # mid-marker. The whole marker-like span must go, tail included.
    for raw in (
        "x [[c3],",        # stopped right after the comma
        "x [[c3],[c4",     # stopped mid-second-alias
        "x [[c3],[c",      # stopped mid-alias-name (no digits yet)
    ):
        stripped, tags = parse_markers(raw)
        assert "[[" not in stripped, raw
        assert "]" not in stripped, raw
        assert stripped == "x "
        assert tags == []


def test_closed_bracket_wrapped_chain_at_eof_is_well_formed():
    # The same shape CLOSED is a legitimate multi-alias marker: it parses
    # into cleaned aliases rather than being treated as malformed junk.
    stripped, tags = parse_markers("x [[c3],[c4]]")
    assert stripped == "x "
    assert tags[0].aliases == ("c3", "c4")


def test_strip_for_stream_holds_back_unterminated_bracket_wrapped_chain():
    # Same hold-back contract as the plain partial: an unterminated
    # bracket-wrapped marker must not flash its tail on screen.
    assert strip_for_stream("grew to $8.2M [[c3],") == "grew to $8.2M "
    assert strip_for_stream("grew to $8.2M [[c3],[c4") == "grew to $8.2M "
    # Once the marker completes, the held-back characters are gone for good.
    assert (
        strip_for_stream("grew to $8.2M [[c3],[c4]] and")
        == "grew to $8.2M and"
    )


def test_multiple_markers_offsets_all_index_stripped_text():
    raw = "A [[c1]] then B [[c2]] end"
    stripped, tags = parse_markers(raw)
    assert stripped == "A then B end"
    assert [t.at for t in tags] == [2, 9]


def test_malformed_markers_are_stripped_but_yield_no_tag():
    # single close bracket / junk after alias / unterminated at EOF —
    # every shape strips, none becomes a Tag.
    for raw in ("x [[c3] y", "x [[c3 oops]] y", "x [[c3"):
        stripped, tags = parse_markers(raw)
        assert "[[" not in stripped
        assert tags == []


def test_double_brackets_that_are_not_markers_are_left_alone():
    raw = "the statute [[A.R.S. 35-142]] says"
    stripped, tags = parse_markers(raw)
    assert stripped == raw  # only [[c<digit>… shapes are marker-like
    assert tags == []


def test_a_marker_with_no_surrounding_space_does_not_fuse_its_neighbours():
    # The space-swallow that keeps "million [[c3]] this" from becoming a
    # double space must not run when there was no space to begin with.
    stripped, _ = parse_markers("$8.2M[[c3]]and rising")
    assert stripped == "$8.2Mand rising"


def test_strip_for_stream_removes_complete_and_holds_back_partial():
    assert strip_for_stream("grew to $8.2M [[c3]] and") == "grew to $8.2M and"
    # A trailing partial marker is HELD BACK, not shown: the next frame
    # carries the full accumulated text again, so nothing is lost.
    assert strip_for_stream("grew to $8.2M [[c") == "grew to $8.2M "
    assert strip_for_stream("grew to $8.2M [[") == "grew to $8.2M "
    assert strip_for_stream("grew to $8.2M [") == "grew to $8.2M "
    # ...but an ordinary markdown link stays intact once complete.
    assert strip_for_stream("see [the report](url)") == "see [the report](url)"
