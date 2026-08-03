from retrieval.query_match import Confidence, Match, is_filterable


def test_all_exact_matches_are_filterable():
    ms = [Match("agency:adc", Confidence.EXACT, "corrections")]
    assert is_filterable(ms) is True


def test_one_weak_match_makes_the_whole_set_boost_only():
    """Mixed confidence must not hard-filter: the weak one could be wrong,
    and a wrong hard filter empties the page."""
    ms = [
        Match("agency:adc", Confidence.EXACT, "corrections"),
        Match("agency:ade", Confidence.WEAK, "ed"),
    ]
    assert is_filterable(ms) is False


def test_no_matches_is_not_filterable():
    assert is_filterable([]) is False
