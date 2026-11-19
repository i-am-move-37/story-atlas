"""Label the whole corpus with genres (research plan 2.3, after the pilot).

Three jobs, each one LLM call per in-scope work, sent through OpenRouter's Batch API:
  check     is this narrative fiction, what form is it, does the summary match its metadata?
  metadata  genres from title, year, medium and creators only
  plot      genres from the plot summary (no title)

Steps:
  plan      FREE. Counts the works and estimates tokens, batches and cost for a job.
  submit    PAID. Sends the works that have no answer yet, in batches. Needs --spend-ceiling.
  collect   Free to call. Fetches finished batches and appends answers to data/labels/<job>.jsonl.

The genre list and rules go in a cached system block, so repeat calls pay a tenth for it.
Answers are appended as they arrive; a rerun skips works already answered.

Usage: uv run scripts/label_corpus.py plan --job metadata [--limit 200]
       uv run scripts/label_corpus.py submit --job metadata --limit 200 --spend-ceiling 20
       uv run scripts/label_corpus.py collect --job metadata
"""

import argparse
import json
import urllib.request
from pathlib import Path

import pandas as pd

from genres import load_scheme
from label_pilot import (LABELS_SCHEMA, MODEL, RULES, api_key, clean_labels, metadata_prompt,
                         plot_prompt, scheme_order, scheme_text)

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "labels"
BATCHES_URL = "https://openrouter.ai/api/v1/batches"

# Prices in dollars per million tokens, from the pilot. The batch and cache factors are
# OpenRouter's documented typical values; the 200-work trial replaces them with measured cost.
PRICE_IN, PRICE_OUT = 8.0, 40.0
CACHE_WRITE_1H, CACHE_READ, BATCH_FACTOR = 2.0, 0.1, 0.5
CHARS_PER_TOKEN = 4          # rough, for estimates only
MAX_BATCH_BYTES = 150_000_000  # the documented limit is 200 MB per batch
MAX_BATCH_REQUESTS = 10_000    # no documented number; a 413 reply names the real one
CHECK_WORDS = 400              # how much of the summary the check reads

FORMS = ["feature film", "short film", "television episode or series", "novel or novella",
         "short story", "play", "poem", "comic or graphic novel", "video game", "non-fiction",
         "page about a character, a series or a franchise", "other"]
CHECK_RULES = """You are checking entries in a corpus of plot summaries of feature films and prose fiction.
Each entry has metadata (what the corpus believes the work is) and a summary. Answer from the
summary and from what you know of the work.

- narrative_fiction: true if the summary tells an invented story. False for essays, treatises,
  textbooks, biographies of real people written as fact, and pages that describe a character,
  a series or a franchise instead of telling one work's story.
- form: what the summarized thing actually is.
- matches_metadata: "yes" if the summary describes the work the metadata names; "no" if it
  describes a different work that shares the title (a film's entry holding a television
  episode, a video game or another film); "unsure" if you can't tell.
- note: a few words when any answer is surprising, otherwise empty.
"""
CHECK_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["narrative_fiction", "form", "matches_metadata", "note"],
    "properties": {"narrative_fiction": {"type": "boolean"},
                   "form": {"type": "string", "enum": FORMS},
                   "matches_metadata": {"type": "string", "enum": ["yes", "no", "unsure"]},
                   "note": {"type": "string"}},
}


# ---------- pure helpers ----------

def check_prompt(work):
    creators = ", ".join(work["creators"]) or "unknown"
    words = work["text"].split()
    shown = " ".join(words[:CHECK_WORDS]) + (" [...]" if len(words) > CHECK_WORDS else "")
    return (f"Metadata: a {work['medium']} titled \"{work['title']}\", year {work['year'] or 'unknown'}, "
            f"creators: {creators}.\n\nSummary:\n{shown}")


def job_spec(job, scheme):
    """(system text, function work -> user text, schema, schema name) for one job."""
    if job == "check":
        return CHECK_RULES, check_prompt, CHECK_SCHEMA, "check"
    system = RULES + scheme_text(scheme)
    return system, {"metadata": metadata_prompt, "plot": plot_prompt}[job], LABELS_SCHEMA, "labels"


def request_body(system, user, schema, name):
    """One chat request: the shared system text in a block the provider may cache for an hour."""
    return {
        "temperature": 0,
        "messages": [
            {"role": "system", "content": [{"type": "text", "text": system,
                                            "cache_control": {"type": "ephemeral", "ttl": "1h"}}]},
            {"role": "user", "content": user},
        ],
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": name, "strict": True, "schema": schema}},
    }


def batch_payload(model, requests):
    """The body for POST /batches. `requests` must come last or the submit is refused."""
    return {"endpoint": "/v1/chat/completions", "model": model, "completion_window": "24h",
            "requests": requests}


def split_batches(requests, max_bytes=MAX_BATCH_BYTES, max_requests=MAX_BATCH_REQUESTS):
    """Consecutive groups of requests, each within the byte and count limits."""
    groups, current, size = [], [], 0
    for r in requests:
        n = len(json.dumps(r, ensure_ascii=False).encode("utf-8"))
        if current and (size + n > max_bytes or len(current) >= max_requests):
            groups.append(current)
            current, size = [], 0
        current.append(r)
        size += n
    return groups + ([current] if current else [])


def parse_result(entry, job, valid_ids):
    """One batch result -> {work_id, ok, answer | error, usage}. Never raises on a bad reply."""
    work_id = entry["custom_id"].split(":", 1)[1]
    if entry.get("error") or not entry.get("response"):
        return {"work_id": work_id, "ok": False, "error": json.dumps(entry.get("error"))[:300]}
    body = entry["response"].get("body") or {}
    try:
        answer = json.loads(body["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as e:
        return {"work_id": work_id, "ok": False, "error": f"unreadable reply: {e}"[:300]}
    if job != "check":
        answer = {"recognized": bool(answer.get("recognized")),
                  "labels": clean_labels(answer.get("labels"), valid_ids)}
    return {"work_id": work_id, "ok": True, "answer": answer, "usage": body.get("usage")}


def unanswered(work_ids, done):
    """Work ids with no good answer yet, in their original order."""
    return [w for w in work_ids if w not in done]


def estimate_cost(n, system_chars, user_chars, output_tokens=120, cached=True, batch=True):
    """Rough dollars for n calls. One cache write, then reads, when `cached`."""
    system_tokens, user_tokens = system_chars / CHARS_PER_TOKEN, user_chars / CHARS_PER_TOKEN
    if cached:
        system_cost = system_tokens * (CACHE_WRITE_1H + (n - 1) * CACHE_READ)
    else:
        system_cost = system_tokens * n
    dollars = (system_cost + user_tokens) * PRICE_IN / 1e6 + n * output_tokens * PRICE_OUT / 1e6
    return dollars * (BATCH_FACTOR if batch else 1.0)


# ---------- data ----------

def load_works(limit=None, only=None):
    """In-scope works with their summary text, as dicts the prompts understand."""
    works = pd.read_parquet(ROOT / "data" / "works.parquet")
    works = works[works.scope == "in"]
    if only is not None:
        works = works[works.work_id.isin(only)]
    if limit:
        works = works.sample(n=min(limit, len(works)), random_state=20261118)
    text = pd.read_parquet(ROOT / "data" / "summaries.parquet", columns=["uid", "text"],
                           filters=[("uid", "in", list(works.text_uid))]).set_index("uid").text
    return [{"work_id": str(w.work_id), "title": w.title, "medium": w.medium,
             "year": None if pd.isna(w.year) else int(w.year),
             "creators": list(w.creators)[:6], "text": text[w.text_uid]} for w in works.itertuples()]


def answers_path(job):
    return OUT / f"{job}.jsonl"


def done_ids(job):
    path = answers_path(job)
    if not path.exists():
        return set()
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    return {r["work_id"] for r in rows if r.get("ok")}


def build_requests(job, works):
    system, prompt, schema, name = job_spec(job, load_scheme())
    return system, [{"custom_id": f"{job}:{w['work_id']}", "body": request_body(system, prompt(w), schema, name)}
                    for w in works]


# ---------- network ----------

def call(method, url, payload=None):
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {api_key()}", "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=600) as r:
        return json.loads(r.read().decode("utf-8"))


# ---------- steps ----------

def step_plan(job, limit):
    works = load_works(limit)
    todo = [w for w in works if w["work_id"] in set(unanswered([w["work_id"] for w in works], done_ids(job)))]
    system, requests = build_requests(job, todo)
    user_chars = sum(len(r["body"]["messages"][1]["content"]) for r in requests)
    groups = split_batches(requests)
    print(f"job {job}: {len(works):,} works in scope, {len(todo):,} without an answer yet")
    print(f"shared instructions: about {len(system) / CHARS_PER_TOKEN:,.0f} tokens; "
          f"per-work text: about {user_chars / CHARS_PER_TOKEN / max(len(todo), 1):,.0f} tokens on average")
    print(f"batches needed: {len(groups)}")
    for label, cached, batch in (("no discounts", False, False), ("caching only", True, False),
                                 ("batch only", False, True), ("caching and batch", True, True)):
        print(f"  estimated cost, {label:18s} ${estimate_cost(len(todo), len(system), user_chars, cached=cached, batch=batch):,.0f}")
    print("These are estimates from character counts. The trial measures the real cost.")


def step_submit(job, limit, ceiling):
    works = load_works(limit)
    done = done_ids(job)
    todo = [w for w in works if w["work_id"] not in done]
    system, requests = build_requests(job, todo)
    user_chars = sum(len(r["body"]["messages"][1]["content"]) for r in requests)
    worst = estimate_cost(len(todo), len(system), user_chars, cached=False, batch=False)
    if worst > ceiling:
        raise SystemExit(f"Not sent. With no discounts this could cost ${worst:,.0f}, above the ceiling of "
                         f"${ceiling:,.0f}. Lower --limit or raise --spend-ceiling.")
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / f"{job}.batches.jsonl").open("a", encoding="utf-8") as log:
        for group in split_batches(requests):
            reply = call("POST", BATCHES_URL, batch_payload(MODEL, group))
            log.write(json.dumps({"id": reply["id"], "requests": len(group), "collected": False}) + "\n")
            print(f"submitted batch {reply['id']} with {len(group):,} requests")


def step_collect(job):
    log_path = OUT / f"{job}.batches.jsonl"
    batches = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line]
    valid = set(scheme_order(load_scheme()))
    for b in batches:
        if b["collected"]:
            continue
        reply = call("GET", f"{BATCHES_URL}/{b['id']}")
        print(f"batch {b['id']}: {reply['status']}  usage {reply.get('usage')}")
        if reply["status"] != "completed":
            continue
        rows = [parse_result(e, job, valid) for e in reply["results"]]
        with answers_path(job).open("a", encoding="utf-8") as out:
            for row in rows:
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
        b |= {"collected": True, "usage": reply.get("usage"), "failed": sum(not r["ok"] for r in rows)}
        print(f"  saved {len(rows):,} answers, {b['failed']} failed")
    log_path.write_text("".join(json.dumps(b) + "\n" for b in batches), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("step", choices=["plan", "submit", "collect"])
    parser.add_argument("--job", choices=["check", "metadata", "plot"], required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--spend-ceiling", type=float)
    args = parser.parse_args()
    if args.step == "plan":
        step_plan(args.job, args.limit)
    elif args.step == "submit":
        if args.spend_ceiling is None:
            raise SystemExit("submit spends money: pass --spend-ceiling DOLLARS.")
        step_submit(args.job, args.limit, args.spend_ceiling)
    else:
        step_collect(args.job)
