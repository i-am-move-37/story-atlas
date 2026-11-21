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
  collect   Free to call. Fetches finished batches and appends answers to data/labels/.
  direct    PAID. One ordinary request per work, a few at a time, at twice the batch price.
            For the check on the small model: there a batch is screened before it runs, and
            one flagged summary fails the whole batch. Sent one by one, only that work fails.

A submitted batch cannot be cancelled, so the batch is the unit of risk: keep --batch-size small.
The genre list and rules go in a system block cached for an hour. Requests inside one batch may
run at the same moment, before any of them has written the cache, so `run` first sends one
ordinary request to write it. Answers are appended as they arrive; a rerun skips answered works.

Usage: uv run scripts/label_corpus.py plan --job metadata [--limit 200] [--model ...]
       uv run scripts/label_corpus.py run --job metadata --limit 200 --spend-ceiling 5
       uv run scripts/label_corpus.py collect --job metadata
"""

import argparse
import json
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

from genres import load_scheme
from label_pilot import (LABELS_SCHEMA, MODEL, RULES, api_key, clean_labels, metadata_prompt,
                         plot_prompt, scheme_order, scheme_text)

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "labels"
BATCHES_URL = "https://openrouter.ai/api/v1/batches"
CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"

# Batch prices in dollars per million tokens, read from OpenRouter's model list on 2026-11-20
# (the ":batch" variant of each model): input, output, cached-input read, one-hour cache write.
PRICES = {
    "anthropic/claude-fable-5.2": {"in": 4.0, "out": 20.0, "read": 0.10, "write": 8.0},
    "anthropic/claude-opus-5.5": {"in": 2.0, "out": 10.0, "read": 0.10, "write": 4.0},
    "anthropic/claude-sonnet-5.5": {"in": 1.0, "out": 5.0, "read": 0.05, "write": 2.0},
    "anthropic/claude-haiku-5.5": {"in": 0.05, "out": 0.25, "read": 0.005, "write": 0.10},
}
JOB_MODEL = {"check": "anthropic/claude-haiku-5.5", "metadata": MODEL, "plot": MODEL}
CHARS_PER_TOKEN = 4          # rough, for estimates only
# The genre list is dense with ids and slashes: the first paid call measured 5,455 tokens for
# 12,344 characters of rules and list, about 2.3 characters per token.
LIST_CHARS_PER_TOKEN = 2.3
OUTPUT_TOKENS = 240          # measured on the first batch: about 40 of answer and 200 of reasoning
MAX_BATCH_BYTES = 150_000_000  # the documented limit is 200 MB per batch
MAX_BATCH_REQUESTS = 10_000    # no documented number; a 413 reply names the real one
CHECK_WORDS = 400              # how much of the summary the check reads
BATCH_SIZE = 1000              # works per batch when running in stages
COST_TOLERANCE = 1.5           # stop if a batch costs more than this times its estimate
POLL_SECONDS = 60
DIRECT_WORKERS = 16
DIRECT_FACTOR = 2.0            # an ordinary request costs twice the batch price

FORMS = ["feature film", "short film", "television episode or series", "novel or novella",
         "short story", "play", "poem", "comic or graphic novel", "video game", "non-fiction",
         "page about a character, a series or a franchise", "other"]
CHECK_RULES = """You are checking entries in a corpus of plot summaries of feature films and prose fiction.
Each entry has metadata (what the corpus believes the work is) and a summary. Answer from the
summary and from what you know of the work.

The corpus has two media. "film" means a feature-length film, including one made for television.
"novel" means any prose fiction: a novel, a novella or a short story all belong under it.

- narrative_fiction: true if the summary tells an invented story. False for essays, treatises,
  textbooks, memoirs and biographies written as fact, documentaries, and pages that describe a
  character, a series or a franchise instead of telling one work's story.
- form: what the summarized work itself is. A feature-length television film is a
  "feature film". A film adapted from a novel is a "feature film", not a novel. Use
  "television episode or series" only for an episode, a season or a whole series.
- matches_metadata: "yes" if the summary tells the story of the work the metadata names. Still
  "yes" when a short story sits under "novel", and when the summary seems to follow an
  adaptation of the same story in the other medium (say so in the note). "no" only if it is a
  different work that shares the title: a film's entry holding a television series, a video
  game, or another film of the same name. "unsure" if you can't tell.
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


def custom_id(job, position):
    """A batch request's id. The provider allows only letters, digits, '_' and '-'."""
    return f"{job}-{position}"


def system_chars(job, system):
    """Length of the shared instructions, scaled so CHARS_PER_TOKEN gives their real token count."""
    return len(system) if job == "check" else len(system) * CHARS_PER_TOKEN / LIST_CHARS_PER_TOKEN


def parse_result(entry, job, valid_ids, work_ids):
    """One batch result -> {work_id, ok, answer | error, usage}. Never raises on a bad reply.

    `work_ids` are the batch's works in the order sent; the request id holds the position.
    """
    work_id = work_ids[int(entry["custom_id"].rsplit("-", 1)[1])]
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


def estimate_cost(n, system_chars, user_chars, price, cache="read", output_tokens=OUTPUT_TOKENS):
    """Rough dollars for n batch calls at `price`.

    `cache` says what happens to the shared instructions on each call: "read" (found in the
    cache, the cheap case), "none" (not cached, full input price) or "write" (every call
    writes the cache, the dearest case, which happens when calls run before any has written it).
    """
    system_tokens, user_tokens = system_chars / CHARS_PER_TOKEN, user_chars / CHARS_PER_TOKEN
    per_system_token = {"read": price["read"], "none": price["in"], "write": price["write"]}[cache]
    return (n * system_tokens * per_system_token + user_tokens * price["in"]
            + n * output_tokens * price["out"]) / 1e6


def worst_case(n, system_chars, user_chars, price):
    return max(estimate_cost(n, system_chars, user_chars, price, cache=c) for c in ("none", "write"))


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


def run_name(job, model):
    """File stem for one job run with one model, e.g. 'plot--claude-fable-5.2'."""
    return f"{job}--{model.split('/')[-1]}"


# ---------- data ----------

def load_works(limit=None, only=None):
    """In-scope works with their summary text, as dicts the prompts understand."""
    works = pd.read_parquet(ROOT / "data" / "works.parquet")
    works = works[works.scope == "in"]
    if only is not None:
        works = works[works.work_id.astype(str).isin(only)]
    if limit:
        works = works.sample(n=min(limit, len(works)), random_state=20261118)
    text = pd.read_parquet(ROOT / "data" / "summaries.parquet", columns=["uid", "text"],
                           filters=[("uid", "in", list(works.text_uid))]).set_index("uid").text
    return [{"work_id": str(w.work_id), "title": w.title, "medium": w.medium,
             "year": None if pd.isna(w.year) else int(w.year),
             "creators": list(w.creators)[:6], "text": text[w.text_uid]} for w in works.itertuples()]


def answers_path(name):
    return OUT / f"{name}.jsonl"


def done_ids(name):
    path = answers_path(name)
    if not path.exists():
        return set()
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    return {r["work_id"] for r in rows if r.get("ok")}


def build_requests(job, works):
    system, prompt, schema, name = job_spec(job, load_scheme())
    return system, [{"custom_id": custom_id(job, i), "body": request_body(system, prompt(w), schema, name)}
                    for i, w in enumerate(works)]


def read_log(name):
    path = OUT / f"{name}.batches.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def write_log(name, batches):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.batches.jsonl").write_text("".join(json.dumps(b) + "\n" for b in batches), encoding="utf-8")


# ---------- network ----------

class ApiError(Exception):
    def __init__(self, code, text):
        super().__init__(f"{code} {text}")
        self.code = code


def call(method, url, payload=None):
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {api_key()}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=600) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise ApiError(e.code, f"{method} {url}: {e.read().decode('utf-8', 'replace')[:600]}") from e


def warm_cache(model, body):
    """One ordinary request, so the shared instructions are in the cache before a batch runs."""
    reply = call("POST", CHAT_URL, {"model": model} | body)
    usage = reply.get("usage") or {}
    print(f"cache warm-up: {json.dumps(usage)[:400]}")
    return usage


# ---------- steps ----------

def step_plan(job, model, limit):
    name, price = run_name(job, model), PRICES[model]
    works = load_works(limit)
    done = done_ids(name)
    todo = [w for w in works if w["work_id"] not in done]
    system, requests = build_requests(job, todo)
    user_chars = sum(len(r["body"]["messages"][1]["content"]) for r in requests)
    print(f"job {job} on {model}: {len(works):,} works in scope, {len(todo):,} without an answer yet")
    print(f"shared instructions: about {system_chars(job, system) / CHARS_PER_TOKEN:,.0f} tokens; "
          f"per-work text: about {user_chars / CHARS_PER_TOKEN / max(len(todo), 1):,.0f} tokens on average")
    print(f"batches of {BATCH_SIZE:,}: {-(-len(todo) // BATCH_SIZE)}")
    for label, cache in (("instructions read from the cache", "read"), ("instructions not cached", "none"),
                         ("every call writes the cache", "write")):
        print(f"  batch price, {label:34s} ${estimate_cost(len(todo), system_chars(job, system), user_chars, price, cache):,.2f}")
    print("Estimates from character counts and a guessed answer length. The trial measures the real cost.")


def step_collect(name, job):
    """Fetch every finished batch not yet saved. Returns True while any batch is still running."""
    batches, valid, running = read_log(name), set(scheme_order(load_scheme())), False
    for b in batches:
        if b["collected"]:
            continue
        try:
            reply = call("GET", f"{BATCHES_URL}/{b['id']}")
        except ApiError as e:
            if e.code != 404:
                raise
            # A batch can't be fetched for a short while after it is created.
            reply = {"status": "validating"}
        if reply["status"] in ("validating", "in_progress", "finalizing"):
            running = True
            continue
        rows = [parse_result(e, job, valid, b["work_ids"]) for e in reply.get("results") or []]
        with answers_path(name).open("a", encoding="utf-8") as out:
            for row in rows:
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
        b |= {"collected": True, "status": reply["status"], "cost": (reply.get("usage") or {}).get("cost"),
              "usage": reply.get("usage"), "failed": sum(not r["ok"] for r in rows),
              "error": reply.get("error")}
        print(f"batch {b['id']}: {reply['status']}, {len(rows):,} answers saved, {b['failed']} failed, "
              f"charged {b['cost']} (estimated ${b['estimate']:,.2f})")
    write_log(name, batches)
    return running


def step_run(job, model, limit, ceiling, batch_size):
    """Send one batch at a time, checking what each cost before sending the next."""
    name, price = run_name(job, model), PRICES[model]
    works = load_works(limit)
    total = len(works)
    while True:
        if step_collect(name, job):
            time.sleep(POLL_SECONDS)
            continue
        batches, done = read_log(name), done_ids(name)
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
        worst = worst_case(len(todo), system_chars(job, system), user_chars, price)
        last = finished[-1] if finished else {}
        reason = stop_reason(spent, ceiling, worst, last.get("cost"), last.get("estimate"))
        if reason:
            print(f"STOPPED before sending the next batch: {reason}.")
            return
        warm_cache(model, requests[0]["body"])
        reply = call("POST", BATCHES_URL, batch_payload(model, requests))
        batches.append({"id": reply["id"], "work_ids": [w["work_id"] for w in todo], "collected": False,
                        "estimate": estimate_cost(len(todo), system_chars(job, system), user_chars, price),
                        "worst_case": worst})
        write_log(name, batches)
        print(f"sent batch {reply['id']}: {len(todo):,} works, estimated ${batches[-1]['estimate']:,.2f}, "
              f"at most ${worst:,.2f}")


def step_direct(job, model, limit, ceiling):
    """One ordinary request per unanswered work. A work the provider refuses fails alone."""
    name, price = run_name(job, model), PRICES[model]
    done = done_ids(name)
    todo = [w for w in load_works(limit) if w["work_id"] not in done]
    system, requests = build_requests(job, todo)
    user_chars = sum(len(r["body"]["messages"][1]["content"]) for r in requests)
    worst = DIRECT_FACTOR * worst_case(len(todo), system_chars(job, system), user_chars, price)
    if worst > ceiling:
        raise SystemExit(f"Not sent: {len(todo):,} works could cost up to ${worst:,.2f}, above the ceiling of ${ceiling:,.2f}.")
    valid, ids = set(scheme_order(load_scheme())), [w["work_id"] for w in todo]

    def one(request):
        try:
            reply = call("POST", CHAT_URL, {"model": model} | request["body"])
        except ApiError as e:
            return {"work_id": ids[int(request["custom_id"].rsplit("-", 1)[1])], "ok": False, "error": str(e)[:300]}
        return parse_result({"custom_id": request["custom_id"], "response": {"body": reply}}, job, valid, ids)

    OUT.mkdir(parents=True, exist_ok=True)
    spent = failed = 0
    with ThreadPoolExecutor(DIRECT_WORKERS) as pool, answers_path(name).open("a", encoding="utf-8") as out:
        for row in pool.map(one, requests):
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            out.flush()
            spent += (row.get("usage") or {}).get("cost") or 0.0
            failed += not row["ok"]
    print(f"{len(todo):,} works sent one by one: {failed} failed, ${spent:,.4f} charged")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("step", choices=["plan", "run", "collect", "direct"])
    parser.add_argument("--job", choices=["check", "metadata", "plot"], required=True)
    parser.add_argument("--model", choices=sorted(PRICES))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--spend-ceiling", type=float)
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    args = parser.parse_args()
    model = args.model or JOB_MODEL[args.job]
    if args.step == "plan":
        step_plan(args.job, model, args.limit)
    elif args.step in ("run", "direct"):
        if args.spend_ceiling is None:
            raise SystemExit(f"{args.step} spends money: pass --spend-ceiling DOLLARS.")
        if args.step == "run":
            step_run(args.job, model, args.limit, args.spend_ceiling, args.batch_size)
        else:
            step_direct(args.job, model, args.limit, args.spend_ceiling)
    else:
        step_collect(run_name(args.job, model), args.job)
