"""Deduplicate long plot summaries into one row per work: data/works.parquet.

Step 1 of the study (research plan 2.1). Rows that point to the same Wikidata
item (and are the same medium) are one work. Rows with no Wikidata match fall
back to title and year. The longest summary becomes the work's text; every
version's uid is kept for the summary-stability check (plan 6.2).

Needs data/wiki/{rows.parquet,pages.jsonl,wikidata.jsonl} from wiki_ids.py.
Usage: uv run scripts/build_works.py
"""

import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import duckdb
import pandas as pd

from scope import film_scope, novel_scope
from wiki_ids import classify_type, earliest_year

ROOT = Path(__file__).resolve().parent.parent
SUMMARIES = ROOT / "data" / "summaries.parquet"
WIKI = ROOT / "data" / "wiki"
OUT = ROOT / "data" / "works.parquet"
DATASETS = Path("C:/Users/Owner/Home/dat/datasets")

TAG_RE = re.compile(r"^(.*?)\s*\(([^()]*)\)$")
YEAR_TOLERANCE = 1
FIRST_YEAR, LAST_YEAR = 1000, 2017  # the sources end in 2017; other Wikidata years are errors
LINK_PROPS = {"P144": "based_on", "P179": "series", "P155": "follows",
              "P156": "followed_by", "P4969": "derivatives"}


# ---------- pure helpers ----------

def normalize_title(title):
    """Lowercase, strip accents and punctuation, drop a leading article."""
    text = title if isinstance(title, str) else ""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    text = " ".join(re.sub(r"[^a-z0-9 ]", " ", text).split())
    return re.sub(r"^(the|a|an) ", "", text)


def tag_year(raw_title):
    """Year in a Wikipedia title tag: 'Alien (1979 film)' -> 1979."""
    m = TAG_RE.match(raw_title or "")
    y = re.match(r"(\d{4})\s", m.group(2) + " ") if m else None
    return int(y.group(1)) if y else None


def strip_tag(page_title):
    """'Alien (1979 film)' -> 'Alien'; None stays None."""
    if not isinstance(page_title, str):
        return None
    m = TAG_RE.match(page_title)
    return m.group(1) if m else page_title


def pick_year(wikidata_year, source_years):
    """(year, where it came from): Wikidata first, else the earliest source year."""
    years = [int(y) for y in source_years if y is not None and not pd.isna(y)]
    if wikidata_year and FIRST_YEAR <= wikidata_year <= LAST_YEAR:
        return wikidata_year, "wikidata"
    return (min(years), "source") if years else (None, None)


def years_agree(a, b):
    return a is None or b is None or abs(a - b) <= YEAR_TOLERANCE


def assign_works(rows):
    """{uid: work id} for rows of {uid, medium, qid, key, year, source}.

    `key` is the normalized title; `year` may be None.
    """
    works = {r["uid"]: f"{r['qid']}:{r['medium']}" for r in rows if r["qid"]}

    # Matched works by (medium, title): candidates for unmatched rows to join.
    titled = defaultdict(dict)
    for r in rows:
        if r["qid"]:
            known = titled[(r["medium"], r["key"])].setdefault(works[r["uid"]], [])
            if r["year"] is not None:
                known.append(r["year"])

    leftover = defaultdict(list)
    for r in rows:
        if r["qid"]:
            continue
        if not r["key"]:  # no usable title: never merge by title
            works[r["uid"]] = f"u:{r['uid']}:{r['medium']}"
            continue
        candidates = titled.get((r["medium"], r["key"]), {})
        if len(candidates) == 1:
            work, years = next(iter(candidates.items()))
            if all(years_agree(r["year"], y) for y in years):
                works[r["uid"]] = work
                continue
        leftover[(r["medium"], r["key"])].append(r)

    for (medium, key), group in leftover.items():
        works.update(_cluster_unmatched(medium, key, group))
    return works


def _cluster_unmatched(medium, key, group):
    """Group rows that have no Wikidata item: by year when dated, else one per source row."""
    works = {}
    dated = sorted((r for r in group if r["year"] is not None), key=lambda r: r["year"])
    clusters = []
    for r in dated:
        if clusters and r["year"] - clusters[-1][0]["year"] <= YEAR_TOLERANCE:
            clusters[-1].append(r)
        else:
            clusters.append([r])
    undated = [r for r in group if r["year"] is None]
    if len(clusters) == 1:
        clusters[0].extend(undated)
        undated = []
    for cluster in clusters:
        year = cluster[0]["year"]
        for r in cluster:
            works[r["uid"]] = f"t:{key}:{year}:{medium}"
    # Undated rows that couldn't join a dated cluster: merge across sources only.
    seen = Counter()
    for r in undated:
        works[r["uid"]] = f"t:{key}:u{seen[r['source']]}:{medium}"
        seen[r["source"]] += 1
    return works


# ---------- assembly ----------

def load_jsonl(path, field):
    with path.open(encoding="utf-8") as f:
        return {r[field]: r for r in map(json.loads, f)}


def cmu_runtimes():
    """{uid: runtime in minutes} for CMU film rows that record one."""
    meta = pd.read_csv(DATASETS / "cmu-movie-summaries/MovieSummaries/movie.metadata.tsv", sep="	",
                       header=None, usecols=[0, 5], names=["wiki_id", "runtime"], dtype=str)
    meta["runtime"] = pd.to_numeric(meta.runtime, errors="coerce")
    meta = meta.dropna().drop_duplicates("wiki_id")
    return {f"cmu_movie:{w}": r for w, r in zip(meta.wiki_id, meta.runtime)}


def shortest_runtime(source_runtimes, wikidata_durations):
    """Shortest plausible runtime in minutes from the sources and Wikidata, or None."""
    values = [float(v) for v in source_runtimes if v is not None and not pd.isna(v)]
    for v in wikidata_durations:
        try:
            values.append(float(v))
        except (TypeError, ValueError):
            continue
    values = [v for v in values if 1 <= v <= 600]
    return min(values) if values else None


def resolve_rows():
    """Candidate rows joined to their page, Wikidata facts, text and source year."""
    rows = pd.read_parquet(WIKI / "rows.parquet")
    pages = load_jsonl(WIKI / "pages.jsonl", "key")
    facts = load_jsonl(WIKI / "wikidata.jsonl", "qid")
    for name in ("creators", "forms"):  # properties fetched in separate passes
        if (WIKI / f"{name}.jsonl").exists():
            for qid, extra in load_jsonl(WIKI / f"{name}.jsonl", "qid").items():
                facts.setdefault(qid, {}).update({k: v for k, v in extra.items() if k != "qid"})
    wikiplots = (DATASETS / "wikiplots/titles").read_text(encoding="utf-8").splitlines()

    def page_of(key):
        page = pages.get(key) or {}
        if page.get("redirect") and page.get("title"):
            page = pages.get(f"title:{page['title']}") or page
        return page

    page = rows.key.map(page_of)
    rows["qid"] = page.map(lambda p: p.get("qid"))
    rows["page_title"] = page.map(lambda p: p.get("title"))
    rows["wd_type"] = rows.qid.map(
        lambda q: classify_type([v.get("label") for v in facts.get(q, {}).get("P31", [])]) if q else None)
    extra = duckdb.sql(f"select uid, year, words, genres, creators from '{SUMMARIES}'").df()
    rows = rows.merge(extra, on="uid", how="left")
    rows["runtime"] = rows.uid.map(cmu_runtimes())
    is_wp = rows.source == "wikiplots"
    rows.loc[is_wp, "year"] = rows[is_wp].uid.map(lambda u: tag_year(wikiplots[int(u.split(":")[1])].strip()))
    # A WikiPlots title with no tag ("Brick", not "Brick (film)") had its medium guessed
    # from other sources' titles, or left unknown. The plot comes from that page, so
    # Wikidata's type for the page decides: The Iceman Cometh is the play, though a film
    # shares its title. With no Wikidata type, a guess is kept and an unknown is dropped.
    raw_title = rows.uid.map(lambda u: wikiplots[int(u.split(":")[1])].strip() if u.startswith("wikiplots:") else "")
    rows["untagged"] = is_wp & ~raw_title.map(lambda t: bool(TAG_RE.match(t)))
    typed = rows.untagged & rows.wd_type.isin(["film", "novel"])
    rows.loc[typed, "medium"] = rows.loc[typed, "wd_type"]
    rows = rows[rows.medium.isin(["film", "novel"])].copy()
    rows["type_conflict"] = rows.wd_type.isin(["film", "novel"]) & (rows.wd_type != rows.medium)
    rows["page_qid"] = rows.qid
    rows["qid"] = [q if isinstance(q, str) and t == m else None
                   for q, t, m in zip(rows.qid, rows.wd_type, rows.medium)]
    rows["title"] = [t if isinstance(t, str) and t.strip() else strip_tag(p)
                     for t, p in zip(rows.title, rows.page_title)]
    rows["key"] = rows.title.map(normalize_title)
    rows = drop_collection_matches(rows)
    return rows, facts


def collection_mismatches(keys, sources, page_key):
    """Which rows of one Wikidata item were only redirected to it.

    `keys` are the rows' normalized titles, `sources` where each row came from.
    Different titles from different sources are normal (alternate titles), so those
    rows stay. But one source never lists a single work under two titles: when it
    does here, the page is a series or collection, and the rows whose title differs
    from the page's don't belong to it.
    """
    per_source = {}
    for key, source in zip(keys, sources):
        per_source.setdefault(source, set()).add(key)
    if all(len(titles) <= 1 for titles in per_source.values()):
        return [False] * len(keys)
    return [k != page_key for k in keys]


def drop_collection_matches(rows):
    rows = rows.copy()
    rows["page_key"] = rows.page_title.map(lambda t: normalize_title(strip_tag(t)))
    stray = pd.Series(False, index=rows.index)
    for _, group in rows[rows.qid.notna()].groupby(["qid", "medium"]):
        stray.loc[group.index] = collection_mismatches(list(group.key), list(group.source), group.page_key.iloc[0])
    rows.loc[stray, "qid"] = None
    # An untagged WikiPlots row took its medium from the page; without the page it has none.
    return rows[~(stray & rows.untagged)].copy()


def build_work(work_id, group, facts):
    """One works.parquet record from the rows of one work."""
    qid = group.qid.dropna().iloc[0] if group.qid.notna().any() else None
    wd = facts.get(qid, {})
    best = group.sort_values("words", ascending=False).iloc[0]
    year, year_source = pick_year(earliest_year(wd.get("P577", []) or wd.get("P571", [])), group.year)
    labels = lambda prop: [v["label"] for v in wd.get(prop, []) if isinstance(v, dict) and v.get("label")]
    page = own_page_facts(group, facts) if qid is None else {}
    page_labels = lambda prop: [v["label"] for v in page.get(prop, []) if isinstance(v, dict) and v.get("label")]
    record = {
        "work_id": work_id, "qid": qid, "medium": best.medium, "title": best.title,
        "page_title": best.page_title, "year": year, "year_source": year_source,
        "source_years": sorted({int(y) for y in group.year.dropna()}),
        "words": int(best.words), "text_uid": best.uid, "uids": list(group.uid),
        "sources": sorted(set(group.source)), "n_versions": len(group),
        "creators": sorted({c for cs in group.creators for c in cs} |
                           {v["label"] for prop in ("P57", "P50") for v in wd.get(prop, [])
                            if isinstance(v, dict) and v.get("label")}),
        "source_genres": sorted({g for gs in group.genres for g in gs}),
        "wd_genres": labels("P136"), "wd_types": labels("P31"), "wd_forms": labels("P7937"),
        "runtime": shortest_runtime(group.runtime, wd.get("P2047", []) + page.get("P2047", [])),
        "page_types": page_labels("P31"),
        "sitelinks": wd.get("sitelinks"), "imdb_id": next(iter(wd.get("P345", [])), None),
        "type_conflict": bool(group.type_conflict.any()),
    }
    for prop, name in LINK_PROPS.items():
        record[name] = [v["id"] for v in wd.get(prop, []) if isinstance(v, dict)]
    # A work with no usable Wikidata item can still have a page of its own that says what
    # it is (a play, a poem). Those facts are used for scope only.
    types = record["wd_types"] + record["page_types"]
    record["scope"] = (film_scope(types, record["runtime"]) if record["medium"] == "film"
                       else novel_scope(types, record["wd_forms"] + page_labels("P7937"),
                                        record["wd_genres"] + page_labels("P136"),
                                        record["source_genres"]))
    return record


def own_page_facts(group, facts):
    """Wikidata facts of the page a row points to, when that page is about this work.

    Rows redirected to a series or collection page (their title differs from the
    page's) don't count: the page describes the collection, not the work.
    """
    own = group[group.page_qid.notna() & (group.key == group.page_key)]
    return facts.get(own.page_qid.iloc[0], {}) if len(own) else {}


def main():
    rows, facts = resolve_rows()
    # pandas stores a missing string or year as NaN, which is truthy; pass real None instead.
    records = [{"uid": r.uid, "medium": r.medium, "source": r.source, "key": r.key,
                "qid": r.qid if isinstance(r.qid, str) else None,
                "year": None if pd.isna(r.year) else int(r.year)} for r in rows.itertuples()]
    work_of = assign_works(records)
    rows["work_id"] = rows.uid.map(work_of)
    works = pd.DataFrame([build_work(w, g, facts) for w, g in rows.groupby("work_id", sort=False)])
    works["year"] = works.year.astype("Int64")
    works.to_parquet(OUT)
    rows[["uid", "work_id", "source", "words"]].to_parquet(WIKI / "work_rows.parquet")
    report(rows, works)


def report(rows, works):
    print(f"rows: {len(rows):,}  ->  works: {len(works):,}")
    for medium in ("film", "novel"):
        w = works[works.medium == medium]
        r = rows[rows.medium == medium]
        print(f"\n{medium}: {len(r):,} rows -> {len(w):,} works")
        print(f"  with a Wikidata item: {w.qid.notna().sum():,} ({w.qid.notna().mean():.0%})")
        print(f"  dated: {w.year.notna().sum():,} ({w.year.notna().mean():.0%});"
              f" year from Wikidata: {(w.year_source == 'wikidata').sum():,}")
        print(f"  versions per work: {dict(sorted(Counter(w.n_versions).items()))}")
        print(f"  Wikidata genre present: {(w.wd_genres.map(len) > 0).sum():,}")
        print(f"  rows whose page is the other medium's item: {int(r.type_conflict.sum()):,};"
              f" rows whose page is a list, series, author or missing: "
              f"{int((r.qid.isna() & ~r.type_conflict).sum()):,}")
    far = works[works.apply(lambda w: w.year_source == "wikidata" and
                            any(abs(y - w.year) > YEAR_TOLERANCE for y in w.source_years), axis=1)]
    print(f"\nworks whose source year differs from Wikidata's by more than 1: {len(far):,}")


if __name__ == "__main__":
    main()
