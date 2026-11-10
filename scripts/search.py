"""Search or sample data/summaries.parquet.

Examples:
  uv run scripts/search.py "white house" "hitman"           # every word must appear
  uv run scripts/search.py heist --medium film --min-words 300
  uv run scripts/search.py --sample 5 --medium novel
  uv run scripts/search.py --counts                         # rows per source and medium
"""

import argparse
import sys
import textwrap
from pathlib import Path

import duckdb

TABLE = Path(__file__).resolve().parent.parent / "data" / "summaries.parquet"


def build_query(words, medium=None, source=None, language=None, min_words=0, sample=0, limit=10):
    """Return (sql, params) for a word search, or a random sample when no words are given."""
    where, params = ["words >= ?"], [min_words]
    for w in words:
        where.append("(text ILIKE ? OR title ILIKE ?)")
        params += [f"%{w}%", f"%{w}%"]
    for column, value in (("medium", medium), ("source", source), ("language", language)):
        if value:
            where.append(f"{column} = ?")
            params.append(value)
    order = "random()" if sample or not words else "words DESC"
    sql = (f"SELECT source, medium, title, series_title, season, episode, year, creators, words, text "
           f"FROM read_parquet('{TABLE.as_posix()}') WHERE {' AND '.join(where)} "
           f"ORDER BY {order} LIMIT {int(sample or limit)}")
    return sql, params


def show(rows, width):
    for source, medium, title, series, season, episode, year, creators, words, text in rows:
        where = f"{series} S{season}E{episode}: " if series and season is not None else (f"{series}: " if series else "")
        by = f" — {', '.join(creators[:3])}" if creators else ""
        print(f"\n[{medium} · {source} · {year or '?'} · {words} words] {where}{title}{by}")
        print(textwrap.indent(textwrap.shorten(text, width, placeholder=" …"), "  "))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    p.add_argument("words", nargs="*")
    p.add_argument("--medium", help="tv_series, tv_episode, film, novel, play, game, …")
    p.add_argument("--source", help="tmdb_tv, tmdb_episode, tmdb_movie, cmu_book, cmu_movie, wiki_movie_plots, wikiplots")
    p.add_argument("--language", help="TMDB language code, e.g. en")
    p.add_argument("--min-words", type=int, default=0)
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--sample", type=int, default=0, help="random rows instead of the longest matches")
    p.add_argument("--width", type=int, default=600, help="characters of text to show")
    p.add_argument("--counts", action="store_true")
    args = p.parse_args()

    con = duckdb.connect()
    if args.counts:
        for r in con.execute(f"SELECT source, medium, count(*) n, median(words)::int FROM read_parquet('{TABLE.as_posix()}') "
                             "GROUP BY ALL ORDER BY source, n DESC").fetchall():
            print(f"{r[0]:18} {r[1]:12} {r[2]:>10,}  median {r[3]} words")
        return
    sql, params = build_query(args.words, args.medium, args.source, args.language,
                              args.min_words, args.sample, args.limit)
    show(con.execute(sql, params).fetchall(), args.width)


if __name__ == "__main__":
    main()
