import json

from label_corpus import (CHECK_WORDS, batch_payload, check_prompt, estimate_cost, parse_result,
                          request_body, split_batches, unanswered)

WORK = {"title": "Metro", "medium": "film", "year": 1997, "creators": ["Thomas Carter"],
        "text": "word " * (CHECK_WORDS + 50)}


def result(custom_id, content=None, error=None):
    if error:
        return {"custom_id": custom_id, "response": None, "error": error}
    return {"custom_id": custom_id, "error": None,
            "response": {"status_code": 200, "body": {"choices": [{"message": {"content": content}}],
                                                      "usage": {"prompt_tokens": 10}}}}


def test_request_marks_the_shared_instructions_as_cacheable_and_asks_for_the_schema():
    body = request_body("RULES AND LIST", "Label this film.", {"type": "object"}, "labels")
    system, user = body["messages"]
    assert system["content"][0]["text"] == "RULES AND LIST"
    assert system["content"][0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert user == {"role": "user", "content": "Label this film."}
    assert body["response_format"]["json_schema"]["schema"] == {"type": "object"}


def test_batch_payload_puts_the_requests_last():
    payload = batch_payload("some/model", [{"custom_id": "plot:1", "body": {}}])
    assert list(payload)[-1] == "requests"
    assert payload["endpoint"] == "/v1/chat/completions" and payload["model"] == "some/model"


def test_split_batches_keeps_every_request_in_order_within_both_limits():
    requests = [{"custom_id": f"plot:{i}", "body": {"text": "x" * 100}} for i in range(10)]
    by_count = split_batches(requests, max_bytes=10**9, max_requests=4)
    assert [len(g) for g in by_count] == [4, 4, 2]
    by_size = split_batches(requests, max_bytes=300, max_requests=100)
    assert all(sum(len(json.dumps(r)) for r in g) <= 300 for g in by_size)
    assert [r for g in by_size for r in g] == requests


def test_split_batches_sends_an_oversized_request_alone_instead_of_dropping_it():
    requests = [{"custom_id": "plot:1", "body": {"text": "x" * 1000}}]
    assert split_batches(requests, max_bytes=10, max_requests=5) == [requests]


def test_parse_result_keeps_only_labels_from_the_list():
    content = json.dumps({"recognized": True, "labels": [{"id": "action", "level": "core"},
                                                        {"id": "made-up", "level": "core"}]})
    row = parse_result(result("metadata:w7", content), "metadata", {"action", "comedy"})
    assert row == {"work_id": "w7", "ok": True, "usage": {"prompt_tokens": 10},
                   "answer": {"recognized": True, "labels": [{"id": "action", "level": "core"}]}}


def test_parse_result_reports_a_failed_or_unreadable_reply_without_raising():
    failed = parse_result(result("plot:w1", error={"message": "overloaded"}), "plot", set())
    assert failed["ok"] is False and "overloaded" in failed["error"]
    garbled = parse_result(result("plot:w2", "not json"), "plot", set())
    assert garbled["ok"] is False and garbled["work_id"] == "w2"


def test_parse_result_passes_a_check_answer_through():
    content = json.dumps({"narrative_fiction": False, "form": "non-fiction", "matches_metadata": "yes", "note": ""})
    assert parse_result(result("check:w3", content), "check", set())["answer"]["form"] == "non-fiction"


def test_unanswered_skips_works_already_done_and_keeps_order():
    assert unanswered(["a", "b", "c", "d"], {"b", "d"}) == ["a", "c"]


def test_check_prompt_shows_the_metadata_and_only_the_start_of_a_long_summary():
    prompt = check_prompt(WORK)
    assert '"Metro"' in prompt and "1997" in prompt and "Thomas Carter" in prompt
    assert prompt.count("word") == CHECK_WORDS and prompt.endswith("[...]")


def test_estimated_cost_falls_with_each_discount():
    args = (1000, 16000, 400000)
    plain = estimate_cost(*args, cached=False, batch=False)
    cached = estimate_cost(*args, cached=True, batch=False)
    both = estimate_cost(*args, cached=True, batch=True)
    assert plain > cached > both > 0
    assert both == cached / 2
