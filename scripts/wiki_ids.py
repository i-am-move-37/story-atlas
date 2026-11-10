"""Match every long plot summary to its Wikipedia page and Wikidata item.

Step 1 of the study (research plan 2.1). Two passes, both resumable:

  pages     Wikipedia API: source page IDs / titles -> final page title + Wikidata ID
  wikidata  Wikidata query service: type, dates, genres, source/sequel links, fame

Output (data/wiki/):
  pages.jsonl     one record per lookup key ("pageid:123" or "title:Alien (1979 film)")
  wikidata.jsonl  one record per Wikidata item
  rows.parquet    uid -> lookup key, for every candidate row

Usage: uv run scripts/wiki_ids.py pages | wikidata
"""

import argparse
import json
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SUMMARIES = ROOT / "data" / "summaries.parquet"
OUT = ROOT / "data" / "wiki"
DATASETS = Path("C:/Users/Owner/Home/dat/datasets")

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
SPARQL_URL = "https://query.wikidata.org/sparql"
USER_AGENT = "StoryAtlas/0.1 (https://github.com/i-am-move-37/story-atlas) python-urllib"
# Wikimedia allows 10 requests a minute to a client whose User-Agent has no contact
# details and 200 a minute to one that has (mediawiki.org/wiki/Wikimedia_APIs/Rate_limits).
# This User-Agent names the project's public repository, so we stay well under 200.
REQUESTS_PER_MINUTE = 150
MIN_WORDS = 300
PAGE_BATCH = 50      # Wikipedia API limit per request
SPARQL_BATCH = 150
WORKERS = 3
MAX_TRIES = 6

_pace_lock = threading.Lock()
_next_slot = [0.0]


def wait_for_slot():
    """Space requests evenly so every thread together stays under the rate limit."""
    with _pace_lock:
        now = time.monotonic()
        start = max(now, _next_slot[0])
        _next_slot[0] = start + 60.0 / REQUESTS_PER_MINUTE
    time.sleep(max(0.0, start - now))

# Wikidata properties we keep: type, publication date, inception, genre, based on,
# series, follows, followed by, derivative work, IMDb ID, country, original language.
PROPS = ["P31", "P577", "P571", "P136", "P144", "P179", "P155", "P156", "P4969",
         "P345", "P495", "P364"]

FILM_WORD = re.compile(r"\bfilm\b")
NOT_A_FILM = re.compile(r"film (series|franchise|trilogy|festival|award|genre|score|studio)")
BOOK_WORDS = re.compile(r"\b(novel|novella|literary work|written work|book)\b")
NOT_A_BOOK = re.compile(r"(book series|novel series|comic book|short story|trilogy|"
                        r"graphic novel|light novel series)")


# ---------- pure helpers ----------

def title_from_url(url):
    """'https://en.wikipedia.org/wiki/Alien_(film)#Plot' -> 'Alien (film)'."""
    if not isinstance(url, str) or "/wiki/" not in url:
        return None
    name = url.split("/wiki/", 1)[1].split("#", 1)[0]
    return urllib.parse.unquote(name).replace("_", " ").strip() or None


def parse_pages(response, asked, by):
    """Wikipedia API response -> {asked key: {pageid, title, qid, missing, redirect}}."""
    query = response.get("query", {})
    hop = {}
    for kind in ("normalized", "redirects"):
        for step in query.get(kind, []):
            hop[step["from"]] = step["to"]
    by_title, by_id = {}, {}
    for page in query.get("pages", []):
        record = {
            "pageid": page.get("pageid"), "title": page.get("title"),
            "qid": page.get("pageprops", {}).get("wikibase_item"),
            "missing": bool(page.get("missing") or page.get("invalid")),
            "redirect": bool(page.get("redirect")),
        }
        by_title[page.get("title")] = record
        by_id[str(page.get("pageid"))] = record
    empty = {"pageid": None, "title": None, "qid": None, "missing": True, "redirect": False}
    found = {}
    for key in asked:
        if by == "pageids":
            found[key] = by_id.get(str(key), dict(empty))
            continue
        title = key
        for _ in range(4):  # normalization, then redirects
            if title in hop:
                title = hop[title]
        found[key] = by_title.get(title, dict(empty, title=title))
    return found


def classify_type(labels):
    """Wikidata 'instance of' labels -> 'film', 'novel', 'other', or None if unlabeled."""
    labels = [label.lower() for label in labels if label]
    if not labels:
        return None
    if any(FILM_WORD.search(x) and not NOT_A_FILM.search(x) for x in labels):
        return "film"
    if any(BOOK_WORDS.search(x) and not NOT_A_BOOK.search(x) for x in labels):
        return "novel"
    return "other"


def earliest_year(dates):
    """Earliest year among Wikidata date strings; None if none parse."""
    years = []
    for date in dates:
        m = re.match(r"^(-?\d{4})-", str(date))
        if m:
            years.append(int(m.group(1)))
    return min(years) if years else None


def facts_from_bindings(bindings):
    """SPARQL rows (item, property, value, label) -> {qid: {property: [values]}}."""
    facts = {}
    for row in bindings:
        qid = row["item"]["value"].rsplit("/", 1)[1]
        prop = row["p"]["value"].rsplit("/", 1)[1]
        value = row["v"]["value"]
        if "/entity/Q" in value:
            value = {"id": value.rsplit("/", 1)[1], "label": row.get("vLabel", {}).get("value")}
        values = facts.setdefault(qid, {}).setdefault(prop, [])
        if value not in values:
            values.append(value)
    return facts


# ---------- network ----------

def fetch_json(url, data=None, accept="application/json"):
    """GET (or POST when data is given) with retries; returns parsed JSON."""
    headers = {"User-Agent": USER_AGENT, "Accept": accept}
    body = urllib.parse.urlencode(data).encode() if data else None
    for attempt in range(MAX_TRIES):
        wait_for_slot()
        try:
            request = urllib.request.Request(url, data=body, headers=headers)
            with urllib.request.urlopen(request, timeout=90) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            wait = float(e.headers.get("Retry-After") or 0) or 5 * (attempt + 1)
            if e.code not in (429, 500, 502, 503, 504) or attempt == MAX_TRIES - 1:
                raise
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            wait = 5 * (attempt + 1)
            if attempt == MAX_TRIES - 1:
                raise
        time.sleep(wait)
    raise RuntimeError("unreachable")


def lookup_pages(batch, by):
    """One Wikipedia API call for up to 50 page IDs or titles."""
    params = {"action": "query", "format": "json", "formatversion": "2",
              "prop": "pageprops|info", "ppprop": "wikibase_item", by: "|".join(batch)}
    if by == "titles":
        params["redirects"] = "1"
    return parse_pages(fetch_json(WIKIPEDIA_API, data=params), batch, by)


def lookup_wikidata(qids):
    """Facts and sitelink counts for a batch of Wikidata items."""
    values = " ".join(f"wd:{q}" for q in qids)
    props = " ".join(f"wdt:{p}" for p in PROPS)
    facts_query = f"""SELECT ?item ?p ?v ?vLabel WHERE {{
      VALUES ?item {{ {values} }} VALUES ?p {{ {props} }}
      ?item ?p ?v .
      OPTIONAL {{ ?v rdfs:label ?vLabel . FILTER(LANG(?vLabel) = "en") }} }}"""
    links_query = f"""SELECT ?item ?n WHERE {{
      VALUES ?item {{ {values} }} ?item wikibase:sitelinks ?n }}"""
    accept = "application/sparql-results+json"
    facts = facts_from_bindings(
        fetch_json(SPARQL_URL, {"query": facts_query}, accept)["results"]["bindings"])
    for row in fetch_json(SPARQL_URL, {"query": links_query}, accept)["results"]["bindings"]:
        qid = row["item"]["value"].rsplit("/", 1)[1]
        facts.setdefault(qid, {})["sitelinks"] = int(row["n"]["value"])
    return {q: facts.get(q, {}) for q in qids}


# ---------- passes ----------

def candidate_rows():
    """Every long summary from the Wikipedia-based sources, with its lookup key."""
    df = duckdb.sql(f"""select uid, source, medium, title, wiki_id from '{SUMMARIES}'
        where source in ('cmu_book','cmu_movie','wiki_movie_plots','wikiplots')
          and words >= {MIN_WORDS} and medium in ('film','novel','unknown')""").df()
    wmp = pd.read_csv(DATASETS / "wiki-movie-plots/raw/wiki_movie_plots_deduped_with_summaries.csv",
                      dtype=str, usecols=["Wiki Page"])["Wiki Page"].tolist()
    wikiplots = (DATASETS / "wikiplots/titles").read_text(encoding="utf-8").splitlines()

    def key(row):
        index = row.uid.split(":", 1)[1]
        if row.source in ("cmu_book", "cmu_movie"):
            return f"pageid:{row.wiki_id}"
        raw = title_from_url(wmp[int(index)]) if row.source == "wiki_movie_plots" \
            else wikiplots[int(index)].strip()
        return f"title:{raw}" if raw else None

    df["key"] = [key(r) for r in df.itertuples()]
    return df


def load_jsonl(path, field):
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return {r[field]: r for r in map(json.loads, f)}


def run_batches(batches, work, out_path, describe):
    """Run `work` over batches in a small thread pool, appending records as they finish."""
    done = 0
    with out_path.open("a", encoding="utf-8") as out, ThreadPoolExecutor(WORKERS) as pool:
        for records in pool.map(work, batches):
            for record in records:
                out.write(json.dumps(record, ensure_ascii=False) + "\n")
            out.flush()
            done += 1
            if done % 50 == 0 or done == len(batches):
                print(f"{describe}: {done}/{len(batches)} batches", flush=True)


def chunks(items, size):
    return [items[i:i + size] for i in range(0, len(items), size)]


def pages_pass():
    OUT.mkdir(parents=True, exist_ok=True)
    rows = candidate_rows()
    rows.to_parquet(OUT / "rows.parquet")
    path = OUT / "pages.jsonl"

    def todo(prefix):
        done = load_jsonl(path, "key")
        keys = sorted({k for k in rows.key.dropna() if k.startswith(prefix) and k not in done})
        return [k.split(":", 1)[1] for k in keys]

    def worker(by, prefix):
        def work(batch):
            found = lookup_pages(batch, by)
            return [{"key": f"{prefix}{k}", **v} for k, v in found.items()]
        return work

    run_batches(chunks(todo("pageid:"), PAGE_BATCH), worker("pageids", "pageid:"), path, "page IDs")
    run_batches(chunks(todo("title:"), PAGE_BATCH), worker("titles", "title:"), path, "titles")

    # Page IDs that turned out to be redirects: follow them by title.
    pages = load_jsonl(path, "key")
    followed = load_jsonl(path, "key")
    redirects = sorted({p["title"] for p in pages.values()
                        if p.get("redirect") and p.get("title") and f"title:{p['title']}" not in followed})
    run_batches(chunks(redirects, PAGE_BATCH), worker("titles", "title:"), path, "redirects")


def wikidata_pass():
    pages = load_jsonl(OUT / "pages.jsonl", "key")
    path = OUT / "wikidata.jsonl"
    done = load_jsonl(path, "qid")
    qids = sorted({p["qid"] for p in pages.values() if p.get("qid")} - set(done))

    def work(batch):
        return [{"qid": q, **facts} for q, facts in lookup_wikidata(batch).items()]

    run_batches(chunks(qids, SPARQL_BATCH), work, path, "wikidata")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("step", choices=["pages", "wikidata"])
    step = parser.parse_args().step
    sys.exit(pages_pass() if step == "pages" else wikidata_pass())
