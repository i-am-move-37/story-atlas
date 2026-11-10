# Story Atlas

A personal, non-commercial corpus of story summaries (TV, film and novels) for studying story structure and generating new story ideas, along the lines of "The Alien Space of Science" (arXiv 2603.01092).

## The combined table
`data/summaries.parquet` has one row per summary from every source below, about 1.85M rows (386 MB). Columns: `uid, source, medium, title, series_title, season, episode, year, language, genres, creators, words, text, imdb_id, wikidata_id, wiki_id`.

```bash
uv run scripts/search.py "white house" hitman                # every word must appear; longest matches first
uv run scripts/search.py heist --medium film --min-words 300
uv run scripts/search.py --sample 5 --medium novel            # random rows
uv run scripts/search.py --counts                             # rows per source and medium
uv run scripts/build_summaries.py                             # rebuild the table (~1 min)
```

From Python or any DuckDB client: `SELECT * FROM 'data/summaries.parquet' WHERE ...`.

The same story can appear in several sources (e.g. a film in TMDB, CMU and both Wikipedia sets). `medium` for WikiPlots comes from the title's tag ("(novel)", "(1979 film)", "(The X-Files)"); untagged titles are matched against the other sources' titles, and about 40k remain `unknown`.

## TMDB pull
`scripts/tmdb_pull.py` uses the TMDB API (key in `.env`, which is git-ignored) and the daily ID exports in `data/exports/`.

```bash
uv run scripts/tmdb_pull.py tv                          # every series: overview, genres, creators, keywords, IMDb/Wikidata IDs
uv run scripts/tmdb_pull.py seasons                     # episode overviews (+ writers, directors) for scripted series and miniseries
uv run scripts/tmdb_pull.py movies --min-popularity 1   # films: overview, genres, keywords, directors, writers
uv run --group dev pytest                               # parsing tests
```

Output goes to `data/raw/{tv,seasons,movies}.jsonl`, one record per line. Rerunning skips what's saved, so an interrupted run resumes. IDs that no longer exist are saved as `{"id": ..., "missing": true}`. The log is `logs/pull.log`.

Data from TMDB (https://www.themoviedb.org). This product uses the TMDB API but is not endorsed or certified by TMDB.

## Other plot datasets
Downloaded to `C:\Users\Owner\Home\dat\datasets\`, each with its own README:

| Folder | What | Count |
|---|---|---|
| `cmu-book-summaries` | Wikipedia novel plots with author and genres | 16,559 |
| `cmu-movie-summaries` | Wikipedia film plots with Freebase genres | 42,306 |
| `wiki-movie-plots` | Wikipedia film plots with director and genre | 34,886 |
| `wikiplots` | Every Wikipedia "Plot" section (2017), all media mixed | 112,934 |
| `tvtropes-gala` | TV Tropes trope examples per work (no plots) | 7,921 TV works |
