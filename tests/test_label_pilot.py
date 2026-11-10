from genres import load_scheme
from label_pilot import clean_labels, labels_from_wikidata, scheme_text, valid_ids

VALID = {"noir", "noir/neo-noir", "western"}


def test_clean_labels_drops_unknown_ids_and_malformed_entries():
    labels = [{"id": "noir", "level": "core"}, {"id": "made-up", "level": "core"}, "noir"]
    assert clean_labels(labels, VALID) == [{"id": "noir", "level": "core"}]


def test_clean_labels_keeps_one_entry_per_id_with_core_winning():
    labels = [{"id": "noir", "level": "borderline"}, {"id": "noir", "level": "core"},
              {"id": "noir", "level": "borderline"}]
    assert clean_labels(labels, VALID) == [{"id": "noir", "level": "core"}]


def test_labels_from_wikidata_maps_through_the_crosswalk_without_duplicates():
    crosswalk = {"film noir": ["noir"], "neo-noir western": ["noir", "western"], "drama film": []}
    assert labels_from_wikidata(["film noir", "neo-noir western", "drama film"], crosswalk) == [
        {"id": "noir", "level": "core"}, {"id": "western", "level": "core"}]


def test_labels_from_wikidata_is_none_without_a_genre_field_but_empty_when_nothing_maps():
    assert labels_from_wikidata([], {}) is None
    assert labels_from_wikidata(["drama film"], {"drama film": []}) == []


def test_scheme_text_names_every_id():
    scheme = load_scheme()
    text = scheme_text(scheme)
    assert all(i in text for i in valid_ids(scheme))
