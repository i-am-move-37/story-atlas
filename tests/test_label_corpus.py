import json

from label_corpus import (CHECK_WORDS, batch_payload, check_prompt, custom_id, estimate_cost, parse_result,
                          progress_line, request_body, run_name, split_batches, stop_reason, unanswered,
                          worst_case)

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
    row = parse_result(result("metadata-1", content), "metadata", {"action", "comedy"}, ["w6", "w7"])
    assert row == {"work_id": "w7", "ok": True, "usage": {"prompt_tokens": 10},
                   "answer": {"recognized": True, "labels": [{"id": "action", "level": "core"}]}}


def test_parse_result_reports_a_failed_or_unreadable_reply_without_raising():
    failed = parse_result(result("plot-0", error={"message": "overloaded"}), "plot", set(), ["w1", "w2"])
    assert failed["ok"] is False and "overloaded" in failed["error"]
    garbled = parse_result(result("plot-1", "not json"), "plot", set(), ["w1", "w2"])
    assert garbled["ok"] is False and garbled["work_id"] == "w2"


def test_parse_result_passes_a_check_answer_through():
    content = json.dumps({"narrative_fiction": False, "form": "non-fiction", "matches_metadata": "yes", "note": ""})
    assert parse_result(result("check-0", content), "check", set(), ["Q1:film"])["answer"]["form"] == "non-fiction"


def test_unanswered_skips_works_already_done_and_keeps_order():
    assert unanswered(["a", "b", "c", "d"], {"b", "d"}) == ["a", "c"]


def test_check_prompt_shows_the_metadata_and_only_the_start_of_a_long_summary():
    prompt = check_prompt(WORK)
    assert '"Metro"' in prompt and "1997" in prompt and "Thomas Carter" in prompt
    assert prompt.count("word") == CHECK_WORDS and prompt.endswith("[...]")


def test_estimated_cost_is_lowest_when_the_instructions_are_read_from_the_cache():
    price = {"in": 4.0, "out": 20.0, "read": 0.10, "write": 8.0}
    args = (1000, 16000, 400000, price)
    read, none, write = (estimate_cost(*args, cache=c) for c in ("read", "none", "write"))
    assert 0 < read < none < write
    assert worst_case(*args) == write
    # 1000 calls x 4000 instruction tokens at $0.10 per million, 100,000 text tokens at $4, 120,000 answer tokens at $20
    assert round(read, 4) == round(0.4 + 0.4 + 2.4, 4)


def test_run_name_keeps_runs_with_different_models_apart():
    assert run_name("plot", "anthropic/claude-fable-5.2") == "plot--claude-fable-5.2"


def test_run_goes_on_while_spending_is_within_the_ceiling_and_the_estimate():
    assert stop_reason(spent=10.0, ceiling=50.0, next_worst_case=20.0, last_cost=4.0, last_estimate=4.0) is None
    assert stop_reason(spent=0.0, ceiling=50.0, next_worst_case=20.0) is None


def test_run_stops_when_the_next_batch_could_pass_the_ceiling():
    assert "ceiling" in stop_reason(spent=40.0, ceiling=50.0, next_worst_case=20.0)


def test_run_stops_when_a_batch_cost_far_more_than_estimated():
    reason = stop_reason(spent=10.0, ceiling=500.0, next_worst_case=20.0, last_cost=9.0, last_estimate=4.0)
    assert "more than 1.5 times" in reason


def test_run_stops_when_the_provider_reports_no_cost():
    assert "no cost" in stop_reason(spent=None, ceiling=500.0, next_worst_case=20.0)


def test_progress_line_projects_the_rest_from_the_cost_so_far():
    assert progress_line(1000, 4000, 8.0) == "1,000 of 4,000 works answered; $8.00 charged; about $24.00 more at this rate"
    assert "about $0.00 more" in progress_line(0, 4000, 0.0)


def test_request_ids_use_only_characters_the_provider_allows():
    import re
    assert re.fullmatch(r"[A-Za-z0-9_-]+", custom_id("metadata", 17))
    assert parse_result(result(custom_id("plot", 1), "{}"), "plot", set(), ["Q1:film", "Q2:novel"])["work_id"] == "Q2:novel"
