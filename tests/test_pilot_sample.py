from genres import counts, load_scheme, split_outside_parens
from pilot_sample import allocate, era_of


def test_allocate_gives_equal_shares_and_the_remainder_to_the_largest():
    assert allocate({"a": 100, "b": 50, "c": 10}, 10) == {"a": 4, "b": 3, "c": 3}


def test_allocate_never_takes_more_than_a_stratum_has():
    counts_ = allocate({"a": 100, "b": 2}, 10)
    assert counts_ == {"a": 8, "b": 2}


def test_allocate_stops_when_everything_is_taken():
    assert allocate({"a": 2, "b": 1}, 10) == {"a": 2, "b": 1}


def test_era_of_bins_years_and_handles_missing():
    assert era_of(1931) == "before 1950"
    assert era_of(1979) == "1950-79"
    assert era_of(2004) == "2000-04"
    assert era_of(2005) == "2005 on"
    assert era_of(None) == "undated"


def test_split_outside_parens_keeps_parenthetical_lists_whole():
    assert split_outside_parens("cyberpunk, retro-punk (steampunk, dieselpunk), biopunk") == [
        "cyberpunk", "retro-punk (steampunk, dieselpunk)", "biopunk"]


def test_genre_scheme_has_the_agreed_counts():
    assert counts(load_scheme()) == (7, 44, 217)
