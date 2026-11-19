"""Label the whole corpus with genres (research plan 2.3, after the pilot).

Three jobs, each one LLM call per in-scope work, sent through OpenRouter's Batch API:
  check     is this narrative fiction, what form is it, does the summary match its metadata?
  metadata  genres from title, year, medium and creators only
  plot      genres from the plot summary (no title)

Steps:
  plan      FREE. Counts the works and estimates tokens, batches and cost for a job.
  run       PAID. Sends ONE batch, waits for it, saves the answers, compares what it cost with
            the estimate, and only then sends the next. Needs --spend-ceiling. It stops when the
            total charged plus the next batch's worst case would pass the ceiling, when a batch
            costs more than COST_TOLERANCE times its estimate, or when no cost is reported.
  collect   Free to call. Fetches finished batches and appends answers to data/labels/<job>.jsonl.

A submitted batch cannot be cancelled, so the batch is the unit of risk: keep --batch-size small.

The genre list and rules go in a cached system block, so repeat calls pay a tenth for it.
Answers are appended as they arrive; a rerun skips works already answered.

Usage: uv run scripts/label_corpus.py plan --job metadata [--limit 200]
       uv run scripts/label_corpus.py run --job metadata --limit 200 --spend-ceiling 20
       uv run scripts/label_corpus.py collect --job metadata
"""

import argparse
import json
import time
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
BATCH_SIZE = 1000              # works per batch when running in stages
COST_TOLERANCE = 1.5           # stop if a batch costs more than this times its estimate
POLL_SECONDS = 60

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


def stop_reason(spent, ceiling, next_worst_case, last_cost=None, last_estimate=None,
                tolerance=COST_TOLERANCE):
    """Why the staged run must stop before sending another batch, or None to go on.

    `spent` is what the provider says it has charged so far; None means it didn't say.
    """
    if spent is None:
        return "the provider reported no cost for a finished batch, so spending can't be tracked"
    if last_cost is not None and last_estimate and last_cost > tolerance * last_estimate:
        return (f"the last batch cost ${last_cost:,.2f}, more than {tolerance} times "
                f"its estimate of ${last_estimate:,.2f}")
    if spent + next_worst_case > ceiling:
        return (f"${spent:,.2f} charged so far plus up to ${next_worst_case:,.2f} for the next batch "
                f"would pass the ceiling of ${ceiling:,.2f}")
    return None


def progress_line(done, total, spent):
    """One line of status, with the cost of the rest projected from the cost so far."""
    rest = spent / done * (total - done) if done else 0.0
    return (f"{done:,} of {total:,} works answered; ${spent:,.2f} charged; "
            f"about ${rest:,.2f} more at this rate")


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


def read_log(job):
    path = OUT / f"{job}.batches.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def write_log(job, batches):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{job}.batches.jsonl").write_text("".join(json.dumps(b) + "\n" for b in batches), encoding="utf-8")


def step_collect(job):
    """Fetch every finished batch not yet saved. Returns True while any batch is still running."""
    batches, valid, running = read_log(job), set(scheme_order(load_scheme())), False
    for b in batches:
        if b["collected"]:
            continue
        reply = call("GET", f"{BATCHES_URL}/{b['id']}")
        if reply["status"] in ("validating", "in_progress", "finalizing"):
            running = True
            continue
        rows = [parse_result(e, job, valid) for e in reply.get("results") or []]
        with answers_path(job).open("a", encoding="utf-8") as out:
            for row in rows:
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
        b |= {"collected": True, "status": reply["status"], "cost": (reply.get("usage") or {}).get("cost"),
              "failed": sum(not r["ok"] for r in rows)}
        print(f"batch {b['id']}: {reply['status']}, {len(rows):,} answers saved, {b['failed']} failed, "
              f"charged {b['cost']} (estimated ${b['estimate']:,.2f})")
    write_log(job, batches)
    return running


def step_run(job, limit, ceiling, batch_size):
    """Send one batch at a time, checking what each cost before sending the next."""
    works = load_works(limit)
    total = len(works)
    while True:
        if step_collect(job):
            time.sleep(POLL_SECONDS)
            continue
        batches, done = read_log(job), done_ids(job)
        finished = [b for b in batches if b["collected"]]
        spent = None if any(b["cost"] is None for b in finished) else sum(b["cost"] for b in finished)
        if spent is not None:
            print(progress_line(sum(w["work_id"] in done for w in works), total, spent))
        tried = {i for b in finished for i in b["work_ids"]}
        todo = [w for w in works if w["work_id"] not in done and w["work_id"] not in tried][:batch_size]
        if not todo:
            print(f"nothing left to send; {len(tried - done)} works failed and were not retried")
            return
        system, requests = build_requests(job, todo)
        user_chars = sum(len(r["body"]["messages"][1]["content"]) for r in requests)
        worst = estimate_cost(len(todo), len(system), user_chars, cached=False, batch=False)
        last = finished[-1] if finished else {}
        reason = stop_reason(spent, ceiling, worst, last.get("cost"), last.get("estimate"))
        if reason:
            print(f"STOPPED before sending the next batch: {reason}.")
            return
        reply = call("POST", BATCHES_URL, batch_payload(MODEL, requests))
        batches.append({"id": reply["id"], "work_ids": [w["work_id"] for w in todo], "collected": False,
                        "estimate": estimate_cost(len(todo), len(system), user_chars), "worst_case": worst})
        write_log(job, batches)
        print(f"sent batch {reply['id']}: {len(todo):,} works, estimated ${batches[-1]['estimate']:,.2f}, "
              f"at most ${worst:,.2f}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("step", choices=["plan", "run", "collect"])
    parser.add_argument("--job", choices=["check", "metadata", "plot"], required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--spend-ceiling", type=float)
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    args = parser.parse_args()
    if args.step == "plan":
        step_plan(args.job, args.limit)
    elif args.step == "run":
        if args.spend_ceiling is None:
            raise SystemExit("run spends money: pass --spend-ceiling DOLLARS.")
        step_run(args.job, args.limit, args.spend_ceiling, args.batch_size)
    else:
        step_collect(args.job)
