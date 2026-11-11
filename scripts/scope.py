"""Which works are in scope: feature films and narrative prose fiction (research plan 2.1).

`film_scope` and `novel_scope` return "in" or the reason a work is out. Nothing is
deleted: build_works.py writes the result to the `scope` column of works.parquet.
Usage: uv run scripts/scope.py   (prints what the rules remove)
"""

import re
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
WORKS = ROOT / "data" / "works.parquet"

FEATURE_MINUTES = 40  # the Academy's line between a short and a feature

# Wikidata "instance of" labels that mean the item isn't a single work of prose fiction.
NOT_PROSE_FICTION_TYPES = {
    "book of the bible": "scripture", "religious text": "scripture",
    "platonic dialogue": "philosophy", "apologia": "philosophy",
    "monograph": "non-fiction", "non-fiction literary work": "non-fiction",
    "scientific work": "non-fiction", "article": "non-fiction", "periodical": "non-fiction",
    "document": "non-fiction", "creativity techniques": "non-fiction",
    "dramatic work": "play", "dramatico-musical work": "play", "theatre performance": "play",
    "poetry": "poetry", "narrative poetry": "poetry", "epic poem": "poetry",
    "national epic": "poetry", "oral poetry": "poetry",
    "comic book album": "comics", "graphic novel": "comics", "comic book": "comics",
    "comic book series": "comics", "manga series": "comics", "limited series": "comics",
    "novel series": "series", "book series": "series", "literary trilogy": "series",
    "series of creative works": "series", "novel cycle": "series", "novel sequence": "series",
    "children's book series": "series", "literary dylogy": "series", "multi-volume work": "series",
    "original video animation": "not a book", "computer file": "not a book",
}
# Wikidata "form of creative work" labels.
NOT_PROSE_FICTION_FORMS = {
    "play": "play", "tragedy": "play", "comedy": "play", "poem": "poetry", "epic poem": "poetry",
    "poetry": "poetry", "essay": "non-fiction", "treatise": "non-fiction", "dialogue": "philosophy",
    "comics": "comics", "graphic novel": "comics", "manga": "comics",
    "short story collection": "collection",
}
# Genre labels (Wikidata's or the source's) that point away from prose fiction.
# They only count when the work carries no sign of being fiction.
NON_FICTION_GENRES = {
    "non-fiction": "non-fiction", "essay": "non-fiction", "autobiography": "non-fiction",
    "memoir": "non-fiction", "biography": "non-fiction", "history": "non-fiction",
    "reference": "non-fiction", "sociology": "non-fiction", "travel": "non-fiction",
    "travel literature": "non-fiction", "science": "non-fiction", "popular science": "non-fiction",
    "psychology": "non-fiction", "economics": "non-fiction", "business": "non-fiction",
    "politics": "non-fiction", "inspirational": "non-fiction", "self-help": "non-fiction",
    "mathematics": "non-fiction", "nature": "non-fiction", "true crime": "non-fiction",
    "music": "non-fiction", "role-playing game": "not a book",
    "philosophy": "philosophy", "religion": "scripture", "religious text": "scripture",
    "poetry": "poetry", "epic poem": "poetry", "narrative poetry": "poetry",
    "play": "play", "tragedy": "play", "tragicomedy": "play", "history play": "play",
    "comics": "comics", "comic book": "comics", "graphic novel": "comics",
}
FICTION_SIGN = re.compile(
    r"fiction|novel|novella|fantasy|mystery|thriller|romance|horror|fairy tale|dystopi|"
    r"adventure|suspense|gothic|western|satire|comic|children|young adult|short story|"
    r"bildungsroman|roman à clef|steampunk|cyberpunk|alternate history|wuxia|picaresque")


def _lower(labels):
    return [str(x).strip().lower() for x in (labels if labels is not None else []) if x]


def has_fiction_sign(labels):
    """True if any label marks the work as fiction ('non-fiction' doesn't count)."""
    return any(FICTION_SIGN.search(x.replace("non-fiction", "")) for x in _lower(labels))


def film_scope(wd_types, runtime):
    """'in', or 'short film' for anything typed a short or running under 40 minutes."""
    if any(re.search(r"\bshort\b", t) for t in _lower(wd_types)):
        return "short film"
    if runtime is not None and not pd.isna(runtime) and 0 < runtime < FEATURE_MINUTES:
        return "short film"
    return "in"


def novel_scope(wd_types, wd_forms, wd_genres, source_genres):
    """'in', or why the work isn't narrative prose fiction."""
    for t in _lower(wd_types):
        if t in NOT_PROSE_FICTION_TYPES:
            return NOT_PROSE_FICTION_TYPES[t]
    forms = _lower(wd_forms)
    if "short story collection" in forms:  # one summary covering several stories
        return "collection"
    if not any(f in ("novel", "novella", "short story", "novelette") for f in forms):
        for f in forms:
            if f in NOT_PROSE_FICTION_FORMS:
                return NOT_PROSE_FICTION_FORMS[f]
    genres = _lower(wd_genres) + _lower(source_genres)
    if has_fiction_sign(genres + forms + _lower(wd_types)):
        return "in"
    for g in genres:
        if g in NON_FICTION_GENRES:
            return NON_FICTION_GENRES[g]
    return "in"


def scope_of(work):
    if work.medium == "film":
        return film_scope(work.wd_types, work.runtime)
    return novel_scope(work.wd_types, work.wd_forms, work.wd_genres, work.source_genres)


def main():
    works = pd.read_parquet(WORKS)
    for medium in ("film", "novel"):
        w = works[works.medium == medium]
        out = w[w.scope != "in"]
        print(f"\n{medium}: {len(w):,} works; in scope {len(w) - len(out):,}; out {len(out):,}")
        for reason, n in Counter(out.scope).most_common():
            print(f"  {reason:14s} {n:5,}")
        era = pd.cut(out.year.astype("float"), [0, 1929, 1959, 1989, 2004, 2017],
                     labels=["to 1929", "1930-59", "1960-89", "1990-2004", "2005-17"])
        print("  by era:", era.value_counts(sort=False).to_dict(), "| undated:", int(out.year.isna().sum()))


if __name__ == "__main__":
    main()
