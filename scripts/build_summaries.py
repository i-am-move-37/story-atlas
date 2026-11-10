"""Combine every plot-summary source into one table: data/summaries.parquet.

One row per summary. Columns:
  uid, source, medium, title, series_title, season, episode, year, language,
  genres, creators, words, text, imdb_id, wikidata_id, wiki_id

Sources: TMDB (series, episodes, films), CMU Book Summaries, CMU Movie Summaries,
Wikipedia Movie Plots, WikiPlots. Rows with no summary text are dropped.
Usage: uv run scripts/build_summaries.py
"""

import json
import re
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "summaries.parquet"
DATASETS = Path("C:/Users/Owner/Home/dat/datasets")

# WikiPlots title tags, e.g. "Dune (novel)", "Alien (1979 film)"
WIKIPLOTS_TAGS = {
    "film": "film", "novel": "novel", "novella": "novel", "book": "novel",
    "short story": "short_story", "play": "play", "musical": "play", "opera": "play",
    "TV series": "tv_series", "miniseries": "tv_series", "telenovela": "tv_series",
    "serial": "tv_series", "video game": "game", "comics": "comics", "manga": "comics",
    "anime": "tv_series", "audio drama": "audio",
}
TAG_RE = re.compile(r"^(.*?)\s*\(([^()]*)\)$")
SEASON_RE = re.compile(r"^season \d+$", re.IGNORECASE)

SCHEMA = pa.schema([
    ("uid", pa.string()), ("source", pa.string()), ("medium", pa.string()),
    ("title", pa.string()), ("series_title", pa.string()),
    ("season", pa.int32()), ("episode", pa.int32()), ("year", pa.int32()),
    ("language", pa.string()), ("genres", pa.list_(pa.string())),
    ("creators", pa.list_(pa.string())), ("words", pa.int32()), ("text", pa.string()),
    ("imdb_id", pa.string()), ("wikidata_id", pa.string()), ("wiki_id", pa.string()),
])


def year_of(date):
    """First four digits of a date string, as an int, or None."""
    m = re.match(r"\s*(\d{4})", str(date or ""))
    return int(m.group(1)) if m else None


def freebase_values(cell):
    """Freebase JSON dict cell -> list of its names."""
    if not isinstance(cell, str) or not cell.strip():
        return []
    try:
        return list(json.loads(cell).values())
    except json.JSONDecodeError:
        return []


def clean(text):
    return " ".join(str(text or "").split())


def row(source, key, medium, title, text, **extra):
    text = clean(text)
    return {
        "uid": f"{source}:{key}", "source": source, "medium": medium, "title": title,
        "series_title": None, "season": None, "episode": None, "year": None, "language": None,
        "genres": [], "creators": [], "imdb_id": None, "wikidata_id": None, "wiki_id": None,
        **extra, "text": text, "words": len(text.split()),
    }


def jsonl(name):
    with (RAW / name).open(encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if not r.get("missing"):
                yield r


def tmdb_rows():
    series = {}
    for s in jsonl("tv.jsonl"):
        series[s["id"]] = s
        yield row("tmdb_tv", s["id"], "tv_series", s["name"], s.get("overview"),
                  year=year_of(s.get("first_air_date")), language=s.get("original_language"),
                  genres=s["genres"], creators=s["created_by"],
                  imdb_id=s.get("imdb_id"), wikidata_id=s.get("wikidata_id"))
    for season in jsonl("seasons.jsonl"):
        s = series.get(season["tv_id"], {})
        for e in season["episodes"]:
            yield row("tmdb_episode", f"{season['id']}/{e.get('episode_number')}", "tv_episode",
                      e.get("name"), e.get("overview"),
                      series_title=s.get("name"), season=season.get("season_number"),
                      episode=e.get("episode_number"), year=year_of(e.get("air_date")),
                      language=s.get("original_language"), genres=s.get("genres", []),
                      creators=e["writers"])
    for m in jsonl("movies.jsonl"):
        yield row("tmdb_movie", m["id"], "film", m.get("title"), m.get("overview"),
                  year=year_of(m.get("release_date")), language=m.get("original_language"),
                  genres=m["genres"], creators=m["directors"] + m["writers"],
                  imdb_id=m.get("imdb_id"), wikidata_id=m.get("wikidata_id"))


def read_tsv(path, names):
    return pd.read_csv(path, sep="\t", header=None, names=names, quoting=3, dtype=str)


def cmu_book_rows():
    books = read_tsv(DATASETS / "cmu-book-summaries/booksummaries/booksummaries.txt",
                     ["wiki_id", "fb_id", "title", "author", "date", "genres", "summary"])
    for b in books.itertuples():
        yield row("cmu_book", b.wiki_id, "novel", b.title, b.summary, year=year_of(b.date),
                  genres=freebase_values(b.genres),
                  creators=[b.author] if isinstance(b.author, str) else [], wiki_id=b.wiki_id)


def cmu_movie_rows():
    base = DATASETS / "cmu-movie-summaries/MovieSummaries"
    plots = read_tsv(base / "plot_summaries.txt", ["wiki_id", "summary"])
    meta = read_tsv(base / "movie.metadata.tsv",
                    ["wiki_id", "fb_id", "title", "release", "revenue", "runtime", "langs", "countries", "genres"])
    meta = meta.drop_duplicates("wiki_id").set_index("wiki_id")
    for p in plots.itertuples():
        m = meta.loc[p.wiki_id] if p.wiki_id in meta.index else None
        yield row("cmu_movie", p.wiki_id, "film", None if m is None else m.title, p.summary,
                  year=None if m is None else year_of(m.release),
                  genres=[] if m is None else freebase_values(m.genres), wiki_id=p.wiki_id)


def wmp_rows():
    wmp = pd.read_csv(DATASETS / "wiki-movie-plots/raw/wiki_movie_plots_deduped_with_summaries.csv", dtype=str)
    for i, m in enumerate(wmp.itertuples(index=False)):
        genre = getattr(m, "Genre")
        director = getattr(m, "Director")
        yield row("wiki_movie_plots", i, "film", m.Title, m.Plot, year=year_of(getattr(m, "_0")),
                  genres=[] if not isinstance(genre, str) or genre == "unknown"
                  else [g.strip() for g in re.split(r"[,/]", genre) if g.strip()],
                  creators=[] if not isinstance(director, str) or director == "Unknown" else [director])


def wikiplots_medium(title, tv_names, known=None):
    """Guess (medium, clean title, series title) from a Wikipedia title's tag.

    Untagged titles are matched against `known` ({medium: set of titles}), in order.
    """
    m = TAG_RE.match(title)
    if not m:
        for medium, titles in (known or {}).items():
            if title in titles:
                return medium, title, None
        return "unknown", title, None
    base, tag = m.group(1), m.group(2)
    kind = re.sub(r"^\d{4}\s+", "", tag)  # "1979 film" -> "film"
    if kind in WIKIPLOTS_TAGS:
        return WIKIPLOTS_TAGS[kind], base, None
    if kind.endswith(" episode") or kind in tv_names:
        return "tv_episode", base, kind.removesuffix(" episode")
    if SEASON_RE.match(kind):
        return "tv_season", base, base
    return "unknown", title, None


def wikiplots_rows(tv_names, known):
    base = DATASETS / "wikiplots"
    titles = (base / "titles").read_text(encoding="utf-8").splitlines()
    stories = (base / "plots").read_text(encoding="utf-8").split("<EOS>")
    for i, (title, story) in enumerate(zip(titles, stories)):
        medium, clean_title, series = wikiplots_medium(title.strip(), tv_names, known)
        yield row("wikiplots", i, medium, clean_title, story, series_title=series)


def main():
    tv_names = set()
    with (RAW / "tv.jsonl").open(encoding="utf-8") as f:
        for line in f:
            s = json.loads(line)
            if s.get("original_language") == "en" and s.get("type") in ("Scripted", "Miniseries"):
                tv_names.add(s["name"])

    # Titles seen in the other sources, used to label untagged WikiPlots entries.
    known = {"novel": set(), "film": set(), "tv_series": set(tv_names)}
    sources = [tmdb_rows(), cmu_book_rows(), cmu_movie_rows(), wmp_rows()]
    writer = pq.ParquetWriter(OUT, SCHEMA, compression="zstd")
    counts = {}
    batch = []
    for source in sources + [wikiplots_rows(tv_names, known)]:
        for r in source:
            if r["source"] in ("cmu_book", "cmu_movie", "wiki_movie_plots") and r["title"]:
                known["novel" if r["medium"] == "novel" else "film"].add(r["title"])
            if not r["words"]:
                continue
            batch.append(r)
            counts[(r["source"], r["medium"])] = counts.get((r["source"], r["medium"]), 0) + 1
            if len(batch) >= 100_000:
                writer.write_table(pa.Table.from_pylist(batch, SCHEMA))
                batch = []
    if batch:
        writer.write_table(pa.Table.from_pylist(batch, SCHEMA))
    writer.close()

    for (source, medium), n in sorted(counts.items()):
        print(f"{source:18} {medium:12} {n:>10,}")
    print(f"{'total':31} {sum(counts.values()):>10,}  -> {OUT}")


if __name__ == "__main__":
    main()
