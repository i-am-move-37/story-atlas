from scope import film_scope, has_fiction_sign, novel_scope


def test_a_film_typed_as_a_short_is_out():
    assert film_scope(["animated short film"], None) == "short film"
    assert film_scope(["silent short film"], 95) == "short film"


def test_a_film_under_forty_minutes_is_out_and_forty_is_in():
    assert film_scope(["film"], 7) == "short film"
    assert film_scope(["film"], 40) == "in"


def test_a_film_with_no_runtime_is_kept():
    assert film_scope(["film"], None) == "in"
    assert film_scope([], float("nan")) == "in"


def test_scripture_plays_and_comics_are_out_by_type():
    assert novel_scope(["book of the Bible", "literary work"], [], [], []) == "scripture"
    assert novel_scope(["dramatic work"], [], [], []) == "play"
    assert novel_scope(["graphic novel"], [], [], []) == "comics"
    assert novel_scope(["novel series"], [], [], []) == "series"


def test_a_play_is_out_by_form_unless_the_form_also_says_novel():
    assert novel_scope(["literary work"], ["play"], ["history play"], []) == "play"
    assert novel_scope(["literary work"], ["novel", "play"], [], []) == "in"


def test_non_fiction_genre_puts_a_work_out_only_without_a_sign_of_fiction():
    assert novel_scope(["literary work"], [], ["essay"], ["Psychology", "Non-fiction"]) == "non-fiction"
    assert novel_scope(["literary work"], [], [], ["Philosophy", "Novel"]) == "in"
    assert novel_scope(["literary work"], [], ["autobiographical novel"], ["Autobiography"]) == "in"


def test_a_work_with_no_information_is_kept():
    assert novel_scope([], [], [], []) == "in"
    assert novel_scope(["literary work"], None, None, None) == "in"


def test_non_fiction_is_not_a_sign_of_fiction():
    assert not has_fiction_sign(["Non-fiction"])
    assert has_fiction_sign(["Science Fiction"])
    assert has_fiction_sign(["children's literature"])
