import json

from tmdb_pull import done_ids, trim_movie, trim_season, trim_tv


def test_trim_tv_keeps_story_fields_and_skips_specials():
    d = {
        "id": 688, "name": "The West Wing", "type": "Scripted", "overview": "Inside the White House.",
        "genres": [{"name": "Drama"}], "created_by": [{"name": "Aaron Sorkin"}],
        "keywords": {"results": [{"name": "white house"}]},
        "external_ids": {"imdb_id": "tt0200276", "wikidata_id": "Q3577037"},
        "seasons": [{"season_number": 0}, {"season_number": 1}, {"season_number": 2}],
    }
    t = trim_tv(d)
    assert t["created_by"] == ["Aaron Sorkin"] and t["keywords"] == ["white house"]
    assert t["imdb_id"] == "tt0200276" and t["seasons"] == [1, 2]


def test_trim_season_collects_episode_writers():
    d = {"season_number": 1, "episodes": [{
        "episode_number": 1, "overview": "Josh is in trouble.",
        "crew": [{"job": "Writer", "name": "Aaron Sorkin"}, {"job": "Director", "name": "Thomas Schlamme"},
                 {"job": "Editor", "name": "Someone"}],
    }]}
    t = trim_season(688, d)
    ep = t["episodes"][0]
    assert t["id"] == "688/1" and ep["writers"] == ["Aaron Sorkin"] and ep["directors"] == ["Thomas Schlamme"]


def test_trim_movie_uses_keyword_list_and_crew():
    d = {"id": 1, "title": "X", "keywords": {"keywords": [{"name": "heist"}]},
         "credits": {"crew": [{"job": "Screenplay", "name": "A"}, {"job": "Director", "name": "B"}]}}
    t = trim_movie(d)
    assert t["keywords"] == ["heist"] and t["writers"] == ["A"] and t["directors"] == ["B"]


def test_done_ids_ignores_a_truncated_last_line(tmp_path):
    p = tmp_path / "tv.jsonl"
    p.write_text(json.dumps({"id": 1}) + "\n" + json.dumps({"id": 2, "missing": True}) + '\n{"id": 3, "na', encoding="utf-8")
    assert done_ids(p) == {1, 2}
