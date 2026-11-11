from build_works import assign_works, shortest_runtime, collection_mismatches, normalize_title, pick_year, strip_tag, tag_year


def row(uid, title, medium="film", qid=None, year=None, source="wikiplots"):
    return {"uid": uid, "medium": medium, "qid": qid, "key": normalize_title(title),
            "year": year, "source": source}


def test_normalize_title_drops_case_accents_punctuation_and_leading_article():
    assert normalize_title("The Amélie!") == "amelie"
    assert normalize_title("A  Bug's Life") == "bug s life"
    assert normalize_title(None) == ""


def test_tag_year_reads_year_from_wikipedia_title_tag():
    assert tag_year("Alien (1979 film)") == 1979
    assert tag_year("Dune (novel)") is None
    assert tag_year("Brick") is None


def test_rows_with_the_same_wikidata_item_merge():
    works = assign_works([row("a", "Brick", qid="Q1", year=2005, source="cmu_movie"),
                          row("b", "Brick (film)", qid="Q1", source="wikiplots")])
    assert works["a"] == works["b"] == "Q1:film"


def test_same_item_in_two_media_stays_two_works():
    works = assign_works([row("a", "Jaws", qid="Q1", medium="film"),
                          row("b", "Jaws", qid="Q1", medium="novel")])
    assert works["a"] != works["b"]


def test_unmatched_row_joins_the_only_work_with_its_title_when_years_agree():
    works = assign_works([row("a", "Brick", qid="Q1", year=2005),
                          row("b", "Brick", year=2006, source="wiki_movie_plots"),
                          row("c", "Brick", source="cmu_movie")])
    assert works["b"] == works["c"] == "Q1:film"


def test_unmatched_row_stays_apart_when_its_year_disagrees():
    works = assign_works([row("a", "Hamlet", qid="Q1", year=1948),
                          row("b", "Hamlet", year=1996, source="cmu_movie")])
    assert works["b"] != works["a"]


def test_unmatched_row_stays_apart_when_several_works_share_the_title():
    works = assign_works([row("a", "Hamlet", qid="Q1", year=1948),
                          row("b", "Hamlet", qid="Q2", year=1996),
                          row("c", "Hamlet", source="cmu_movie")])
    assert works["c"] not in ("Q1:film", "Q2:film")


def test_unmatched_dated_rows_merge_with_each_other_within_a_year():
    works = assign_works([row("a", "Lost Film", year=1931, source="cmu_movie"),
                          row("b", "Lost Film", year=1932, source="wiki_movie_plots"),
                          row("c", "Lost Film", year=1960, source="cmu_movie")])
    assert works["a"] == works["b"]
    assert works["c"] != works["a"]


def test_unmatched_undated_rows_from_one_source_stay_apart():
    works = assign_works([row("a", "Untitled", source="wikiplots"),
                          row("b", "Untitled", source="wikiplots")])
    assert works["a"] != works["b"]


def test_pick_year_prefers_wikidata_then_earliest_source_year():
    assert pick_year(1979, [1979, 1980]) == (1979, "wikidata")
    assert pick_year(None, [1980, None, 1979]) == (1979, "source")
    assert pick_year(None, [None]) == (None, None)


def test_unmatched_rows_do_not_chain_across_consecutive_years():
    works = assign_works([row("a", "Hamlet", year=1990, source="cmu_movie"),
                          row("b", "Hamlet", year=1991, source="wiki_movie_plots"),
                          row("c", "Hamlet", year=1992, source="cmu_movie")])
    assert works["a"] == works["b"]
    assert works["c"] != works["a"]


def test_rows_without_a_title_never_merge():
    works = assign_works([row("a", None, year=1950, source="cmu_movie"),
                          row("b", None, year=1950, source="cmu_movie")])
    assert works["a"] != works["b"]


def test_strip_tag_removes_the_wikipedia_disambiguator():
    assert strip_tag("Alien (1979 film)") == "Alien"
    assert strip_tag("Brick") == "Brick"
    assert strip_tag(None) is None


def test_pick_year_ignores_impossible_wikidata_years():
    assert pick_year(6760, [1999]) == (1999, "source")
    assert pick_year(2021, [None]) == (None, None)


def test_alternate_titles_from_different_sources_stay_together():
    keys, sources = ["amelie", "fabuleux destin d amelie poulain"], ["cmu_movie", "wikiplots"]
    assert collection_mismatches(keys, sources, "amelie") == [False, False]


def test_rows_one_source_redirects_to_a_series_page_are_marked():
    keys = ["judge dredd", "doomsday scenario", "apocalypse war"]
    assert collection_mismatches(keys, ["wikiplots"] * 3, "judge dredd") == [False, True, True]


def test_shortest_runtime_takes_the_minimum_and_ignores_junk():
    assert shortest_runtime([7.0, None], ["8", "abc"]) == 7.0
    assert shortest_runtime([float("nan")], ["5400"]) is None  # seconds, not minutes
    assert shortest_runtime([], []) is None
