"""Run the three genre-labeling methods on the 200 pilot works (research plan 2.3).

  wikidata  Wikidata's genre field, mapped onto our scheme by a fixed crosswalk
  metadata  an LLM that sees only title, year, medium and creators
  plot      an LLM that sees the plot summary, medium and year (no title)

Output: data/pilot/methods.json  {pilot_id: {method: [{id, level}] or None}}
        docs/wikidata-genre-crosswalk.json  {Wikidata genre label: [our ids]}
Usage: uv run scripts/label_pilot.py crosswalk | methods
"""

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

from genres import load_scheme

ROOT = Path(__file__).resolve().parent.parent
PILOT = ROOT / "data" / "pilot"
CROSSWALK = ROOT / "docs" / "wikidata-genre-crosswalk.json"
OPENROUTER = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "anthropic/claude-fable-5.2"
WORKERS = 4
MAX_TRIES = 5
CROSSWALK_BATCH = 80

RULES = """You are labeling works of fiction (films and novels) with genres from a fixed scheme.

A genre here is a set of inherited conventions a writer works inside: who the characters are,
what situation they're in, how the story moves, how it ends. It is not a shelf, a format or
an audience bracket.

Rules:
- Use only ids from the scheme below. Give the finest label that applies: a subgenre id
  (like "noir/neo-noir") when one fits, otherwise the genre id (like "noir").
  A subgenre counts for its parent genre, so don't give both.
- A mix of two genres is two labels. A science fiction western gets "science-fiction" and
  "western". Romantic comedy is the one mix with its own label.
- level "core": the work plainly belongs to that tradition.
  level "borderline": a defensible stretch.
- Plain dramas and plain comedies may fit nothing. An empty list is a correct answer.
- Most works have one to three labels. Don't pad.

The scheme (family in brackets; each line is `genre-id (Genre name)` then its subgenres):
"""

LABELS_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["recognized", "labels"],
    "properties": {
        "recognized": {"type": "boolean"},
        "labels": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["id", "level"],
            "properties": {"id": {"type": "string"},
                           "level": {"type": "string", "enum": ["core", "borderline"]}}}},
    },
}


# ---------- pure helpers ----------

def scheme_text(scheme):
    lines = []
    for family in scheme:
        lines.append(f"\n[{family['family']}]")
        for g in family["genres"]:
            subs = "; ".join(f"{s['id']} ({s['name']})" for s in g["subgenres"])
            lines.append(f"{g['id']} ({g['name']})" + (f": {subs}" if subs else ""))
    return "\n".join(lines)


def valid_ids(scheme):
    return {g["id"] for f in scheme for g in f["genres"]} | \
           {s["id"] for f in scheme for g in f["genres"] for s in g["subgenres"]}


def clean_labels(labels, valid):
    """Keep well-formed labels with known ids; one entry per id, core winning over borderline."""
    best = {}
    for label in labels or []:
        if not isinstance(label, dict) or label.get("id") not in valid:
            continue
        level = "core" if label.get("level") == "core" else "borderline"
        if best.get(label["id"]) != "core":
            best[label["id"]] = level
    return [{"id": i, "level": lv} for i, lv in best.items()]


def labels_from_wikidata(wd_genres, crosswalk):
    """Wikidata genre labels -> our ids (all core). None when the work has no genre field."""
    if wd_genres is None or len(wd_genres) == 0:
        return None
    ids = []
    for name in wd_genres:
        for i in crosswalk.get(name, []):
            if i not in ids:
                ids.append(i)
    return [{"id": i, "level": "core"} for i in ids]


def metadata_prompt(work):
    creators = ", ".join(work["creators"]) or "unknown"
    return (f"Label this {work['medium']} from what you know of it.\n"
            f"Title: {work['title']}\nYear: {work['year'] or 'unknown'}\nCreators: {creators}\n\n"
            "Set recognized to false, with an empty list, if you don't know this work well "
            "enough to label it. Don't guess from the title.")


def plot_prompt(work):
    return (f"Label this {work['medium']} ({work['year'] or 'year unknown'}) from its plot summary. "
            "Set recognized to true.\n\n" + work["text"])


# ---------- network ----------

def ask(system, user, schema, name):
    """One structured-output call; returns the parsed JSON object."""
    body = json.dumps({
        "model": MODEL, "temperature": 0,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": name, "strict": True, "schema": schema}},
    }).encode()
    headers = {"Authorization": f"Bearer {api_key()}", "Content-Type": "application/json"}
    for attempt in range(MAX_TRIES):
        try:
            request = urllib.request.Request(OPENROUTER, data=body, headers=headers)
            with urllib.request.urlopen(request, timeout=180) as r:
                reply = json.loads(r.read().decode("utf-8"))
            return json.loads(reply["choices"][0]["message"]["content"])
        except (urllib.error.URLError, TimeoutError, KeyError, IndexError, json.JSONDecodeError) as e:
            if attempt == MAX_TRIES - 1:
                raise RuntimeError(f"LLM call failed after {MAX_TRIES} tries: {e}") from e
            time.sleep(4 * (attempt + 1))


def api_key():
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
            if line.startswith("OPENROUTER_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"')
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is not set in the environment or in .env")
    return key


# ---------- steps ----------

def build_crosswalk():
    """Map every Wikidata genre label in the corpus onto our scheme, once."""
    scheme = load_scheme()
    valid = valid_ids(scheme)
    works = pd.read_parquet(ROOT / "data" / "works.parquet", columns=["wd_genres"])
    names = sorted({g for gs in works.wd_genres for g in gs})
    done = json.loads(CROSSWALK.read_text(encoding="utf-8")) if CROSSWALK.exists() else {}
    todo = [n for n in names if n not in done]
    system = RULES + scheme_text(scheme) + """

Task: you'll get genre names from Wikidata. Map each onto the scheme, as a table.
- A name for a mix ("science fiction horror film") maps to both ids.
- A name that is a shelf, format, technique, audience or source ("drama film",
  "comedy film", "animated film", "silent film", "film based on a novel", "LGBT-related film")
  maps to an empty list.
- Map to a subgenre only when the name means that subgenre; otherwise to the genre."""
    schema = {"type": "object", "additionalProperties": False, "required": ["rows"],
              "properties": {"rows": {"type": "array", "items": {
                  "type": "object", "additionalProperties": False, "required": ["name", "ids"],
                  "properties": {"name": {"type": "string"},
                                 "ids": {"type": "array", "items": {"type": "string"}}}}}}}
    batches = [todo[i:i + CROSSWALK_BATCH] for i in range(0, len(todo), CROSSWALK_BATCH)]

    def work(batch):
        rows = ask(system, "Wikidata genre names:\n" + "\n".join(batch), schema, "crosswalk")["rows"]
        got = {r["name"]: [i for i in r["ids"] if i in valid] for r in rows}
        return {name: got.get(name, []) for name in batch}

    with ThreadPoolExecutor(WORKERS) as pool:
        for i, mapped in enumerate(pool.map(work, batches), 1):
            done.update(mapped)
            CROSSWALK.write_text(json.dumps(dict(sorted(done.items())), indent=1, ensure_ascii=False),
                                 encoding="utf-8")
            print(f"crosswalk: {i}/{len(batches)} batches", flush=True)
    used = sum(1 for v in done.values() if v)
    print(f"{len(done)} Wikidata genre names; {used} map to our scheme, {len(done) - used} to nothing")


def run_methods():
    scheme = load_scheme()
    valid = valid_ids(scheme)
    system = RULES + scheme_text(scheme)
    crosswalk = json.loads(CROSSWALK.read_text(encoding="utf-8"))
    sample = pd.read_parquet(PILOT / "sample.parquet")
    out_path = PILOT / "methods.json"
    results = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {}

    def label(row):
        work = {"title": row.title, "year": None if pd.isna(row.year) else int(row.year),
                "medium": row.medium, "creators": list(row.creators)[:6], "text": row.text}
        meta = ask(system, metadata_prompt(work), LABELS_SCHEMA, "labels")
        plot = ask(system, plot_prompt(work), LABELS_SCHEMA, "labels")
        return row.pilot_id, {
            "wikidata": labels_from_wikidata(row.wd_genres, crosswalk),
            "metadata": clean_labels(meta["labels"], valid) if meta["recognized"] else None,
            "plot": clean_labels(plot["labels"], valid),
        }

    todo = [r for r in sample.itertuples() if r.pilot_id not in results]
    with ThreadPoolExecutor(WORKERS) as pool:
        for i, (pilot_id, labels) in enumerate(pool.map(label, todo), 1):
            results[pilot_id] = labels
            if i % 10 == 0 or i == len(todo):
                out_path.write_text(json.dumps(results, indent=1), encoding="utf-8")
                print(f"methods: {i}/{len(todo)} works", flush=True)
    for method in ("wikidata", "metadata", "plot"):
        covered = sum(1 for r in results.values() if r[method] is not None)
        print(f"{method}: gives an answer for {covered}/{len(results)} works")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("step", choices=["crosswalk", "methods"])
    {"crosswalk": build_crosswalk, "methods": run_methods}[parser.parse_args().step]()
