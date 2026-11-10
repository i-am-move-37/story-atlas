from wiki_ids import (classify_type, earliest_year, facts_from_bindings, parse_pages,
                      title_from_url)


def test_title_from_url_decodes_and_strips_fragment():
    url = "https://en.wikipedia.org/wiki/Am%C3%A9lie_(2001_film)#Plot"
    assert title_from_url(url) == "Amélie (2001 film)"


def test_title_from_url_returns_none_for_non_wikipedia_values():
    assert title_from_url(None) is None
    assert title_from_url("unknown") is None


def test_parse_pages_follows_normalization_and_redirects():
    response = {"query": {
        "normalized": [{"from": "alien (film)", "to": "Alien (film)"}],
        "redirects": [{"from": "Alien (film)", "to": "Alien (1979 film)"}],
        "pages": [{"pageid": 23487440, "title": "Alien (1979 film)",
                   "pageprops": {"wikibase_item": "Q103569"}}],
    }}
    found = parse_pages(response, ["alien (film)"], by="titles")
    assert found["alien (film)"] == {"pageid": 23487440, "title": "Alien (1979 film)",
                                     "qid": "Q103569", "missing": False, "redirect": False}


def test_parse_pages_marks_missing_titles():
    response = {"query": {"pages": [{"title": "No Such Film", "missing": True}]}}
    found = parse_pages(response, ["No Such Film"], by="titles")
    assert found["No Such Film"]["missing"] is True
    assert found["No Such Film"]["qid"] is None


def test_parse_pages_by_pageid_flags_redirect_pages():
    response = {"query": {"pages": [{"pageid": 5, "title": "Old Name", "redirect": True}]}}
    found = parse_pages(response, ["5"], by="pageids")
    assert found["5"]["redirect"] is True
    assert found["5"]["title"] == "Old Name"


def test_classify_type_recognises_films_and_novels():
    assert classify_type(["silent film"]) == "film"
    assert classify_type(["animated feature film", "3D film"]) == "film"
    assert classify_type(["literary work"]) == "novel"
    assert classify_type(["novella"]) == "novel"


def test_classify_type_rejects_series_and_other_media():
    assert classify_type(["film series"]) == "other"
    assert classify_type(["book series"]) == "other"
    assert classify_type(["short story"]) == "other"
    assert classify_type(["television series episode"]) == "other"
    assert classify_type([]) is None


def test_classify_type_prefers_film_when_both_match():
    # A Wikidata item typed as both is almost always a film article in our sources.
    assert classify_type(["film", "literary work"]) == "film"


def test_earliest_year_ignores_bad_dates():
    assert earliest_year(["1979-05-25T00:00:00Z", "1979-09-06T00:00:00Z"]) == 1979
    assert earliest_year(["http://www.wikidata.org/.well-known/genid/abc"]) is None
    assert earliest_year([]) is None


def test_facts_from_bindings_groups_values_by_property():
    def b(item, prop, value, label=None):
        row = {"item": {"value": f"http://www.wikidata.org/entity/{item}"},
               "p": {"value": f"http://www.wikidata.org/prop/direct/{prop}"},
               "v": {"value": value}}
        if label:
            row["vLabel"] = {"value": label}
        return row

    facts = facts_from_bindings([
        b("Q1", "P31", "http://www.wikidata.org/entity/Q11424", "film"),
        b("Q1", "P136", "http://www.wikidata.org/entity/Q185867", "film noir"),
        b("Q1", "P136", "http://www.wikidata.org/entity/Q185867", "film noir"),
        b("Q1", "P577", "2005-01-21T00:00:00Z"),
    ])
    assert facts["Q1"]["P31"] == [{"id": "Q11424", "label": "film"}]
    assert facts["Q1"]["P136"] == [{"id": "Q185867", "label": "film noir"}]
    assert facts["Q1"]["P577"] == ["2005-01-21T00:00:00Z"]
