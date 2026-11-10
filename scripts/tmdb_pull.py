"""Pull TMDB overviews (series, episodes, films) into resumable JSONL files.

Stages:
  tv       details for every series in the daily ID export
  seasons  episode overviews for every scripted series / miniseries season
  movies   details for films with export popularity >= --min-popularity

Usage: uv run scripts/tmdb_pull.py tv|seasons|movies [--min-popularity 1]
Reads TMDB_API_KEY from .env. Rerunning skips records already saved.
"""

import argparse
import gzip
import json
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
API = "https://api.themoviedb.org/3"
REQUESTS_PER_SECOND = 40  # TMDB allows roughly 50/s
WORKERS = 48  # requests take ~1s over the VPN, so concurrency sets the pace
MAX_RETRIES = 6
SCRIPTED_TYPES = {"Scripted", "Miniseries"}


def load_key(env_path=ROOT / ".env"):
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("TMDB_API_KEY="):
            key = line.split("=", 1)[1].strip().strip('"')
            if key:
                return key
    sys.exit("TMDB_API_KEY missing from .env")


def names(items, field="name"):
    return [i[field] for i in items or [] if i.get(field)]


def crew_names(crew, jobs):
    return sorted({c["name"] for c in crew or [] if c.get("job") in jobs and c.get("name")})


def trim_tv(d):
    ext = d.get("external_ids") or {}
    return {
        "id": d["id"],
        "name": d.get("name"),
        "original_name": d.get("original_name"),
        "original_language": d.get("original_language"),
        "origin_country": d.get("origin_country"),
        "type": d.get("type"),
        "status": d.get("status"),
        "first_air_date": d.get("first_air_date"),
        "last_air_date": d.get("last_air_date"),
        "number_of_seasons": d.get("number_of_seasons"),
        "number_of_episodes": d.get("number_of_episodes"),
        "episode_run_time": d.get("episode_run_time"),
        "genres": names(d.get("genres")),
        "networks": names(d.get("networks")),
        "created_by": names(d.get("created_by")),
        "keywords": names((d.get("keywords") or {}).get("results")),
        "tagline": d.get("tagline"),
        "overview": d.get("overview"),
        "popularity": d.get("popularity"),
        "vote_count": d.get("vote_count"),
        "vote_average": d.get("vote_average"),
        "imdb_id": ext.get("imdb_id"),
        "wikidata_id": ext.get("wikidata_id"),
        "tvdb_id": ext.get("tvdb_id"),
        "seasons": [s["season_number"] for s in d.get("seasons") or [] if s.get("season_number")],
    }


def trim_season(tv_id, d):
    return {
        "id": f"{tv_id}/{d.get('season_number')}",
        "tv_id": tv_id,
        "season_number": d.get("season_number"),
        "name": d.get("name"),
        "overview": d.get("overview"),
        "air_date": d.get("air_date"),
        "episodes": [
            {
                "episode_number": e.get("episode_number"),
                "name": e.get("name"),
                "air_date": e.get("air_date"),
                "runtime": e.get("runtime"),
                "overview": e.get("overview"),
                "writers": crew_names(e.get("crew"), {"Writer", "Teleplay", "Story", "Screenplay"}),
                "directors": crew_names(e.get("crew"), {"Director"}),
            }
            for e in d.get("episodes") or []
        ],
    }


def trim_movie(d):
    ext = d.get("external_ids") or {}
    crew = (d.get("credits") or {}).get("crew")
    return {
        "id": d["id"],
        "title": d.get("title"),
        "original_title": d.get("original_title"),
        "original_language": d.get("original_language"),
        "origin_country": d.get("origin_country"),
        "release_date": d.get("release_date"),
        "runtime": d.get("runtime"),
        "genres": names(d.get("genres")),
        "keywords": names((d.get("keywords") or {}).get("keywords")),
        "directors": crew_names(crew, {"Director"}),
        "writers": crew_names(crew, {"Writer", "Screenplay", "Story", "Novel", "Author"}),
        "tagline": d.get("tagline"),
        "overview": d.get("overview"),
        "popularity": d.get("popularity"),
        "vote_count": d.get("vote_count"),
        "vote_average": d.get("vote_average"),
        "imdb_id": d.get("imdb_id") or ext.get("imdb_id"),
        "wikidata_id": ext.get("wikidata_id"),
    }


def done_ids(path):
    if not path.exists():
        return set()
    done = set()
    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                done.add(json.loads(line)["id"])
            except (json.JSONDecodeError, KeyError):
                continue  # a line cut off by a crash; that id is simply fetched again
    return done


def export_ids(kind, min_popularity=0.0):
    path = DATA / "exports" / f"{kind}_ids.json.gz"
    with gzip.open(path, "rt", encoding="utf-8") as f:
        rows = [json.loads(line) for line in f]
    return [r["id"] for r in rows if r.get("popularity", 0) >= min_popularity and not r.get("adult")]


class RateLimiter:
    def __init__(self, per_second):
        self.interval = 1.0 / per_second
        self.next_at = time.monotonic()
        self.lock = threading.Lock()

    def wait(self):
        with self.lock:
            now = time.monotonic()
            self.next_at = max(self.next_at, now) + self.interval
            delay = self.next_at - self.interval - now
        if delay > 0:
            time.sleep(delay)


class Client:
    def __init__(self, key):
        self.key = key
        self.limiter = RateLimiter(REQUESTS_PER_SECOND)

    def get(self, path, **params):
        """Return parsed JSON, or None for a 404."""
        query = urllib.parse.urlencode({"api_key": self.key, **params})
        url = f"{API}{path}?{query}"
        for attempt in range(MAX_RETRIES):
            self.limiter.wait()
            try:
                with urllib.request.urlopen(url, timeout=30) as r:
                    return json.load(r)
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return None
                if e.code not in (429, 500, 502, 503, 504):
                    raise
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                pass
            time.sleep(2**attempt)
        raise RuntimeError(f"gave up on {path}")


def run(jobs, out_path, fetch, label):
    """Fetch each job in parallel and append one JSON line per result."""
    done = done_ids(out_path)
    todo = [j for j in jobs if j[0] not in done]
    print(f"{label}: {len(done):,} saved, {len(todo):,} to fetch", flush=True)
    lock = threading.Lock()
    counts = {"ok": 0, "missing": 0, "error": 0}
    started = time.monotonic()

    def work(job):
        try:
            record = fetch(job) or {"id": job[0], "missing": True}
            kind = "missing" if record.get("missing") else "ok"
        except Exception as e:  # keep going; a rerun retries it
            print(f"  error on {job[0]}: {e}", file=sys.stderr, flush=True)
            with lock:
                counts["error"] += 1
            return
        with lock:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            counts[kind] += 1
            n = counts["ok"] + counts["missing"]
            if n % 2000 == 0:
                f.flush()
                rate = n / (time.monotonic() - started)
                eta = (len(todo) - n) / rate / 60
                print(f"  {n:,}/{len(todo):,}  {rate:.0f}/s  ~{eta:.0f} min left", flush=True)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("a", encoding="utf-8") as f, ThreadPoolExecutor(WORKERS) as pool:
        list(pool.map(work, todo))
    print(f"{label} finished: {counts}", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["tv", "seasons", "movies"])
    parser.add_argument("--min-popularity", type=float, default=1.0, help="films only")
    args = parser.parse_args()
    client = Client(load_key())
    raw = DATA / "raw"

    if args.stage == "tv":
        def fetch(job):
            d = client.get(f"/tv/{job[0]}", append_to_response="keywords,external_ids")
            return d and trim_tv(d)

        run([(i,) for i in export_ids("tv_series")], raw / "tv.jsonl", fetch, "tv")

    elif args.stage == "seasons":
        jobs = []
        with (raw / "tv.jsonl").open(encoding="utf-8") as f:
            for line in f:
                s = json.loads(line)
                if s.get("type") in SCRIPTED_TYPES:
                    jobs += [(f"{s['id']}/{n}", s["id"], n) for n in s["seasons"]]

        def fetch(job):
            d = client.get(f"/tv/{job[1]}/season/{job[2]}")
            return d and trim_season(job[1], d) or {"id": job[0], "missing": True}

        run(jobs, raw / "seasons.jsonl", fetch, "seasons")

    else:
        def fetch(job):
            d = client.get(f"/movie/{job[0]}", append_to_response="keywords,external_ids,credits")
            return d and trim_movie(d)

        ids = export_ids("movie", args.min_popularity)
        run([(i,) for i in ids], raw / "movies.jsonl", fetch, "movies")


if __name__ == "__main__":
    main()
