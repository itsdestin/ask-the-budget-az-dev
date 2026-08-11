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
