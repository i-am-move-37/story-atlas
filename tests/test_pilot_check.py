import random

from pilot_check import adjudicated_gold, build_items, kind_rates

FAMILIES = {"noir": "Crime", "heist": "Crime", "prison": "Crime", "legal": "Crime",
            "western": "Frontier", "war": "Conflict", "spy": "Conflict", "musical": "Stage"}


def labels(*pairs):
    return [{"id": i, "level": lv} for i, lv in pairs]


def test_items_hold_his_genres_the_methods_extras_and_decoys_nobody_gave():
    gold = labels(("noir/neo-noir", "core"), ("western", "borderline"))
    methods = {"wikidata": None, "metadata": labels(("noir", "core"), ("heist/caper", "core")), "plot": []}
    kinds = build_items(gold, methods, FAMILIES, random.Random(1))
    assert {g for g, k in kinds.items() if k == "his"} == {"noir", "western"}
    assert {g for g, k in kinds.items() if k == "method"} == {"heist"}
    near = {g for g, k in kinds.items() if k == "near decoy"}
    far = {g for g, k in kinds.items() if k == "far decoy"}
    assert len(near) == 2 and near <= {"prison", "legal"}
    assert len(far) == 1 and far <= {"war", "spy", "musical"}


def test_items_are_the_same_for_the_same_seed():
    gold = labels(("noir", "core"))
    methods = {"wikidata": None, "metadata": None, "plot": labels(("war", "core"))}
    a = build_items(gold, methods, FAMILIES, random.Random(7))
    b = build_items(gold, methods, FAMILIES, random.Random(7))
    assert list(a.items()) == list(b.items())


def test_adjudicated_gold_makes_stars_core_and_unmarked_items_neutral_and_drops_wrong_ones():
    gold = adjudicated_gold(["noir", "western", "heist", "prison"], wrong=["prison", "heist"], stars=["noir"])
    assert gold == labels(("noir", "core"), ("western", "borderline"))


def test_kind_rates_count_wrong_and_starred_by_where_the_item_came_from():
    checks = [{"kinds": {"noir": "his", "heist": "method", "prison": "near decoy", "war": "far decoy"},
               "wrong": ["prison", "war"], "stars": ["noir"]},
              {"kinds": {"western": "his", "legal": "near decoy"}, "wrong": [], "stars": ["western"]}]
    rates = kind_rates(checks)
    assert rates["his"] == {"items": 2, "wrong": 0, "starred": 2}
    assert rates["method"] == {"items": 1, "wrong": 0, "starred": 0}
    assert rates["near decoy"] == {"items": 2, "wrong": 1, "starred": 0}
    assert rates["far decoy"] == {"items": 1, "wrong": 1, "starred": 0}
