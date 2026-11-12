import pytest

from score_pilot import (anchoring, answer, gold_sets, kappa, label_kappas, pick_winner,
                         predicted, score, tally)


def labels(*pairs):
    return [{"id": i, "level": lv} for i, lv in pairs]


def work(gold, wikidata=None, metadata=None, plot=None):
    return {"gold": gold, "methods": {"wikidata": wikidata, "metadata": metadata, "plot": plot or []}}


def test_gold_subgenres_count_as_their_parent_genre_and_core_wins_over_borderline():
    gold = labels(("noir/neo-noir", "core"), ("noir", "borderline"), ("western", "borderline"))
    assert gold_sets(gold, "genre") == ({"noir"}, {"western"})
    assert gold_sets(gold, "id") == ({"noir/neo-noir"}, {"noir", "western"})


def test_a_borderline_gold_label_neither_helps_nor_hurts():
    core, borderline = {"noir"}, {"western"}
    assert tally({"noir", "western"}, core, borderline) == (1, 0, 0)
    assert tally({"noir"}, core, borderline) == (1, 0, 0)
    assert tally({"western", "horror"}, core, borderline) == (0, 1, 1)


def test_predicted_can_keep_only_the_labels_a_method_called_core():
    given = labels(("noir/neo-noir", "core"), ("western", "borderline"))
    assert predicted(given, "genre") == {"noir", "western"}
    assert predicted(given, "genre", core_only=True) == {"noir"}


def test_a_hybrid_takes_the_first_source_that_gives_any_label():
    methods = {"wikidata": None, "metadata": [], "plot": labels(("noir", "core"))}
    assert answer(methods, ("wikidata", "metadata", "plot")) == ("plot", labels(("noir", "core")))
    assert answer(methods, ("wikidata", "metadata")) == (None, [])


def test_a_work_with_no_label_is_not_covered_and_its_core_labels_are_missed():
    works = [work(labels(("noir", "core")), wikidata=labels(("noir", "core"))),
             work(labels(("western", "core"), ("war", "core")), wikidata=None)]
    s = score(works, ("wikidata",))
    assert (s["covered"], s["coverage"]) == (1, 0.5)
    assert (s["tp"], s["fp"], s["fn"]) == (1, 0, 2)
    assert s["precision"] == 1.0 and s["recall"] == pytest.approx(1 / 3)
    assert s["f1"] == pytest.approx(0.5)


def test_score_records_how_much_of_a_hybrid_comes_from_each_source():
    works = [work(labels(("noir", "core")), wikidata=labels(("noir", "core")), plot=labels(("noir", "core"))),
             work(labels(("noir", "core")), plot=labels(("noir", "core")))]
    s = score(works, ("wikidata", "plot"))
    assert s["share"] == {"wikidata": 0.5, "plot": 0.5}


def test_winner_must_cover_ninety_percent():
    scores = {"wikidata": {"coverage": 0.80, "f1": 0.90, "share": {"wikidata": 0.8}},
              "plot": {"coverage": 1.00, "f1": 0.70, "share": {"plot": 1.0}}}
    assert pick_winner(scores) == "plot"


def test_within_two_points_the_candidate_using_less_plot_text_wins():
    scores = {"plot": {"coverage": 1.0, "f1": 0.800, "share": {"plot": 1.0}},
              "metadata": {"coverage": 0.95, "f1": 0.785, "share": {"metadata": 0.95}},
              "wikidata+metadata": {"coverage": 0.97, "f1": 0.790, "share": {"wikidata": 0.7, "metadata": 0.27}}}
    assert pick_winner(scores) == "wikidata+metadata"
    scores["metadata"]["f1"] = 0.70
    scores["wikidata+metadata"]["f1"] = 0.70
    assert pick_winner(scores) == "plot"


def test_no_winner_when_nothing_covers_enough():
    assert pick_winner({"wikidata": {"coverage": 0.5, "f1": 0.9, "share": {}}}) is None


def test_kappa_is_one_for_agreement_zero_for_chance_and_none_when_undefined():
    assert kappa([1, 1, 0, 0], [1, 1, 0, 0]) == 1.0
    assert kappa([1, 1, 0, 0], [1, 0, 1, 0]) == 0.0
    assert kappa([0, 0, 0], [0, 0, 0]) is None


def test_label_kappas_leave_out_works_where_the_gold_label_is_borderline():
    works = [work(labels(("noir", "core")), plot=labels(("noir", "core"))),
             work(labels(("noir", "borderline")), plot=[]),
             work(labels(("western", "core")), plot=labels(("western", "core"))),
             work(labels(("western", "core")), plot=labels(("western", "core")))]
    out = label_kappas(works, ("plot",), "genre")
    assert out["noir"] == {"kappa": 1.0, "gold": 1, "works": 3}
    assert out["western"] == {"kappa": 1.0, "gold": 2, "works": 4}


def test_anchoring_counts_what_became_of_each_suggestion():
    drafts = [{"draft": ["noir", "western", "war"],
               "gold": labels(("noir", "core"), ("western", "borderline"), ("horror", "core"))}]
    assert anchoring(drafts) == {"suggested": 3, "kept core": 1, "kept borderline": 1,
                                 "removed": 1, "added": 1}
