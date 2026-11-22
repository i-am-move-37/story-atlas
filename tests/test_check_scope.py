import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from check_scope import removal_reason


def answer(form="feature film", fiction=True, matches="yes"):
    return {"form": form, "narrative_fiction": fiction, "matches_metadata": matches, "note": ""}


def test_films_novels_and_short_stories_stay():
    for form in ("feature film", "novel or novella", "short story"):
        assert removal_reason(answer(form)) is None


def test_other_forms_leave_with_the_form_as_reason():
    assert removal_reason(answer("short film")) == "short film"
    assert removal_reason(answer("play")) == "play"


def test_a_different_work_with_the_same_title_leaves():
    assert removal_reason(answer(matches="no")) == "different work with the same title"


def test_unsure_about_the_match_stays():
    assert removal_reason(answer(matches="unsure")) is None


def test_dramatized_true_story_stays():
    assert removal_reason(answer(fiction=False), "dramatized story") is None


def test_documentary_leaves():
    assert removal_reason(answer(fiction=False), "documentary or recording") == "documentary or recording"


def test_not_fiction_without_a_second_pass_leaves():
    assert removal_reason(answer(fiction=False)) == "not an invented story"


def test_undecided_summary_about_the_work_stays():
    assert removal_reason(answer(fiction=False), "summary does not tell the story") is None
