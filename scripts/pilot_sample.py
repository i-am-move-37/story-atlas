"""Draw the 200 works for the genre labeling pilot (research plan 2.3).

Stratified by medium, era and fame, with a fixed seed. The first 50 (a quarter
of every stratum) are labeled from a blank page; the other 150 get a draft.

Output: data/pilot/sample.parquet and data/pilot/works.json (for the labeling page).
Usage: uv run scripts/pilot_sample.py
"""

import json
import random
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
WORKS = ROOT / "data" / "works.parquet"
SUMMARIES = ROOT / "data" / "summaries.parquet"
OUT = ROOT / "data" / "pilot"

SEED = 20261110
PER_MEDIUM = {"film": 130, "novel": 70}
BLANK_EVERY = 4  # one work in four is labeled from a blank page
ERAS = [(None, 1949, "before 1950"), (1950, 1979, "1950-79"), (1980, 1999, "1980-99"),
        (2000, 2004, "2000-04"), (2005, None, "2005 on")]


def era_of(year):
    if year is None or pd.isna(year):
        return "undated"
    for start, end, name in ERAS:
        if (start is None or year >= start) and (end is None or year <= end):
            return name
    return "undated"


def fame_tiers(sitelinks):
    """Low / mid / high thirds by Wikipedia language count; unmatched works are low."""
    filled = sitelinks.fillna(0)
    low, high = filled.quantile([1 / 3, 2 / 3])
    return filled.map(lambda n: "low" if n <= low else ("mid" if n <= high else "high"))


def allocate(sizes, total):
    """Split `total` across strata: equal shares first, the remainder to the largest.

    `sizes` is {stratum: number available}. No stratum gets more than it has.
    """
    counts = dict.fromkeys(sizes, 0)
    left = min(total, sum(sizes.values()))
    while left:
        open_strata = sorted((s for s in sizes if counts[s] < sizes[s]),
                             key=lambda s: (-sizes[s], str(s)))
        share = max(1, left // len(open_strata))
        for s in open_strata:
            take = min(share, sizes[s] - counts[s], left)
            counts[s] += take
            left -= take
            if not left:
                break
    return counts


def draw(works, rng):
    picked = []
    for medium, total in PER_MEDIUM.items():
        pool = works[works.medium == medium].copy()
        pool["fame"] = fame_tiers(pool.sitelinks)
        pool["stratum"] = pool.era + " | " + pool.fame
        counts = allocate(pool.stratum.value_counts().to_dict(), total)
        for stratum, n in sorted(counts.items()):
            ids = sorted(pool[pool.stratum == stratum].work_id)
            chosen = set(rng.sample(ids, n))
            picked.append(pool[pool.work_id.isin(chosen)])
    sample = pd.concat(picked).sort_values(["medium", "stratum", "work_id"]).reset_index(drop=True)
    offset = rng.randrange(BLANK_EVERY)
    sample["mode"] = ["blank" if (i + offset) % BLANK_EVERY == 0 else "draft" for i in range(len(sample))]
    sample["shuffle"] = [rng.random() for _ in range(len(sample))]
    sample = sample.sort_values(["mode", "shuffle"]).reset_index(drop=True)  # blank first
    sample["pilot_id"] = [f"p{i + 1:03d}" for i in range(len(sample))]
    return sample.drop(columns="shuffle")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    works = pd.read_parquet(WORKS)
    works["era"] = works.year.map(era_of)
    sample = draw(works, random.Random(SEED))
    texts = duckdb.sql(f"select uid, text from '{SUMMARIES}'").df().set_index("uid").text
    sample["text"] = sample.text_uid.map(texts)
    sample.to_parquet(OUT / "sample.parquet")

    docs = []
    for i, w in enumerate(sample.itertuples()):
        page = w.page_title if isinstance(w.page_title, str) else None
        docs.append({
            "id": w.pilot_id, "order": i, "mode": w.mode, "work_id": w.work_id,
            "title": w.title, "year": None if pd.isna(w.year) else int(w.year),
            "medium": w.medium, "creators": list(w.creators)[:6],
            "wikipedia": f"https://en.wikipedia.org/wiki/{page.replace(' ', '_')}" if page else None,
            "words": int(w.words), "text": w.text,
        })
    (OUT / "works.json").write_text(json.dumps(docs, ensure_ascii=False, indent=1), encoding="utf-8")
    # One file per work, for loading into the labeling page's database.
    (OUT / "docs").mkdir(exist_ok=True)
    for doc in docs:
        body = {k: v for k, v in doc.items() if k != "id"}
        (OUT / "docs" / f"{doc['id']}.json").write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")

    print(f"{len(sample)} works; blank-page: {(sample['mode'] == 'blank').sum()}")
    print(sample.groupby(["medium", "era"]).size().unstack(fill_value=0).to_string())
    print(sample.groupby(["medium", "fame"]).size().unstack(fill_value=0).to_string())
    print("sources:", sample.sources.map(lambda s: "+".join(s)).value_counts().head(8).to_dict())


if __name__ == "__main__":
    main()
