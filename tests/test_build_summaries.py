from build_summaries import freebase_values, row, wikiplots_medium, year_of

TV = {"The X-Files", "House"}


def test_year_of_reads_leading_year_only():
    assert year_of("2001-08-24") == 2001
    assert year_of("1952") == 1952
    assert year_of(None) is None and year_of("unknown") is None


def test_freebase_values_returns_names_and_tolerates_blanks():
    assert freebase_values('{"/m/1": "Drama", "/m/2": "Satire"}') == ["Drama", "Satire"]
    assert freebase_values(float("nan")) == [] and freebase_values("{bad") == []


def test_row_collapses_whitespace_and_counts_words():
    r = row("cmu_book", 7, "novel", "Dune", "  Paul  goes\n to Arrakis. ")
    assert r["uid"] == "cmu_book:7" and r["text"] == "Paul goes to Arrakis." and r["words"] == 4


def test_wikiplots_medium_reads_title_tags():
    assert wikiplots_medium("Alien (1979 film)", TV) == ("film", "Alien", None)
    assert wikiplots_medium("A Clockwork Orange (novel)", TV) == ("novel", "A Clockwork Orange", None)
    assert wikiplots_medium("Squeeze (The X-Files)", TV) == ("tv_episode", "Squeeze", "The X-Files")
    assert wikiplots_medium("Pilot (Lost episode)", TV) == ("tv_episode", "Pilot", "Lost")
    assert wikiplots_medium("Animal Farm", TV) == ("unknown", "Animal Farm", None)
    assert wikiplots_medium("Mercury (planet)", TV) == ("unknown", "Mercury (planet)", None)


def test_wikiplots_medium_matches_untagged_titles_in_order():
    known = {"novel": {"Animal Farm"}, "film": {"Animal Farm", "Jaws"}, "tv_series": {"Lost"}}
    assert wikiplots_medium("Animal Farm", TV, known)[0] == "novel"
    assert wikiplots_medium("Jaws", TV, known)[0] == "film"
    assert wikiplots_medium("Lost", TV, known)[0] == "tv_series"
    assert wikiplots_medium("Zork", TV, known)[0] == "unknown"


def test_search_query_binds_words_and_filters_as_parameters():
    from search import build_query

    sql, params = build_query(["hit'man"], medium="film", min_words=100)
    assert "hit'man" not in sql and params == [100, "%hit'man%", "%hit'man%", "film"]
    assert "ORDER BY words DESC LIMIT 10" in sql
    sql, _ = build_query([], sample=5)
    assert "ORDER BY random() LIMIT 5" in sql
