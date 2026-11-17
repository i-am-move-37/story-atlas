"""Blind check of the 40 blank-page pilot works (research plan 2.3, added 2026-11-16).

On the works that arrived with suggestions Scott kept 487 of 490, so they can't tell a
valid label from an accepted one. Here each blank-page work gets a short list of genres:
his own, the ones a method gave that he didn't, and decoys nobody gave. He marks the
plainly wrong ones and stars up to three that best describe the work. Nothing shows
where an item came from.

  build   write data/pilot/check/upload/pNNN.json (for the page) and data/pilot/check/key.json
  score   read data/pilot/check/marks/check_marks/pNNN.json and print the adjudicated scores

Usage: uv run scripts/pilot_check.py build | score
"""

import argparse
import json
import random
from collections import Counter
from pathlib import Path

from genres import load_scheme
from score_pilot import CANDIDATES, gold_sets, load_works, pick_winner, predicted, score

ROOT = Path(__file__).resolve().parent.parent
PILOT = ROOT / "data" / "pilot"
CHECK = PILOT / "check"
SEED = 20261116
NEAR_DECOYS, FAR_DECOYS = 2, 1
KINDS = ("his", "method", "near decoy", "far decoy")
BOOTSTRAPS = 4000
# Works whose plot summary belongs to a different work than their metadata, found while reviewing
# the marks and before the key was opened. Neither summary is a feature film, so both are out of scope.
MISMATCHED = {"p012": "summary is the 2001 video game, metadata the unreleased film",
              "p015": "summary is a Yes, Prime Minister episode, metadata the 2019 film"}


# ---------- pure helpers ----------

def build_items(gold, methods, families, rng):
    """{genre: kind} in shuffled order for one work.

    `families` is {genre: family}. A near decoy shares a family with a genre already on
    the list; a far decoy doesn't. Short of one kind, the other fills in.
    """
    core, borderline = gold_sets(gold, "genre")
    his = core | borderline
    extra = set().union(*(predicted(m, "genre") for m in methods.values())) - his
    listed = his | extra
    near_families = {families[g] for g in listed}
    free = sorted(g for g in families if g not in listed)
    picked_near = rng.sample([g for g in free if families[g] in near_families],
                             min(NEAR_DECOYS, sum(families[g] in near_families for g in free)))
    picked_far = rng.sample([g for g in free if families[g] not in near_families],
                            min(FAR_DECOYS, sum(families[g] not in near_families for g in free)))
    spare = [g for g in free if g not in picked_near and g not in picked_far]
    short = NEAR_DECOYS + FAR_DECOYS - len(picked_near) - len(picked_far)
    decoys = picked_near + picked_far + rng.sample(spare, min(short, len(spare)))
    kinds = {g: "his" for g in his} | {g: "method" for g in extra}
    kinds |= {g: "near decoy" if families[g] in near_families else "far decoy" for g in decoys}
    order = sorted(kinds)
    rng.shuffle(order)
    return {g: kinds[g] for g in order}


def adjudicated_gold(items, wrong, stars):
    """Gold labels after the check: starred items are core, unmarked ones neutral, wrong ones gone."""
    return [{"id": g, "level": "core" if g in stars else "borderline"} for g in items if g not in wrong]


def kind_rates(checks):
    """{kind: items, wrong, starred} over [{kinds: {genre: kind}, wrong: [...], stars: [...]}]."""
    out = {k: Counter() for k in KINDS}
    for c in checks:
        for genre, kind in c["kinds"].items():
            out[kind]["items"] += 1
            out[kind]["wrong"] += genre in c["wrong"]
            out[kind]["starred"] += genre in c["stars"]
    return {k: {"items": v["items"], "wrong": v["wrong"], "starred": v["starred"]} for k, v in out.items()}


# ---------- steps ----------

def blank_works():
    works, _ = load_works(allow_unfinished=False)
    return [w for w in works if w["mode"] == "blank"]


def build():
    families = {g["id"]: f["family"] for f in load_scheme() for g in f["genres"]}
    rng = random.Random(SEED)
    (CHECK / "upload").mkdir(parents=True, exist_ok=True)
    key, sizes = {}, Counter()
    for order, w in enumerate(blank_works()):
        kinds = build_items(w["gold"], w["methods"], families, rng)
        key[w["id"]] = kinds
        sizes.update(kinds.values())
        doc = json.loads((PILOT / "docs" / f"{w['id']}.json").read_text(encoding="utf-8"))
        doc = {k: doc[k] for k in ("title", "year", "medium", "creators", "wikipedia", "words", "text")}
        doc |= {"order": order, "items": list(kinds)}
        (CHECK / "upload" / f"{w['id']}.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    (CHECK / "key.json").write_text(json.dumps(key, indent=1), encoding="utf-8")
    print(f"works: {len(key)}; items: {sum(sizes.values())} ({dict(sizes)})")


def print_marks(works, checks):
    print("what he marked, by where the item came from:")
    for kind, r in kind_rates(checks).items():
        print(f"  {kind:11s} {r['items']:4d} items   wrong {r['wrong']:4d} ({r['wrong'] / r['items']:.0%})"
              f"   starred {r['starred']:4d} ({r['starred'] / r['items']:.0%})")
    for name in ("wikidata", "metadata", "plot"):
        given = wrong = 0
        for w, c in zip(works, checks):
            pred = predicted(w["methods"].get(name), "genre")
            given, wrong = given + len(pred), wrong + len(pred & set(c["wrong"]))
        print(f"  {name}: {wrong} of {given} genres it gave were marked wrong ({wrong / given:.0%})")


def print_scores(works, title):
    scores = {name: score(works, chain) for name, chain in CANDIDATES.items()}
    print(f"\n{title}, genre level ({len(works)} works)")
    print(f"  {'candidate':24s} {'coverage':>8s} {'precision':>9s} {'recall':>7s} {'F1':>6s}")
    for name, s in scores.items():
        print(f"  {name:24s} {s['coverage']:8.1%} {s['precision']:9.3f} {s['recall']:7.3f} {s['f1']:6.3f}")
    print(f"\nwinner by the selection rule: {pick_winner(scores)}")
    rng = random.Random(0)
    boots = {name: [] for name in CANDIDATES}
    for _ in range(BOOTSTRAPS):
        sample = [works[rng.randrange(len(works))] for _ in works]
        for name, chain in CANDIDATES.items():
            boots[name].append(score(sample, chain)["f1"])
    best = max(scores, key=lambda n: scores[n]["f1"])
    lo, hi = int(0.025 * BOOTSTRAPS), int(0.975 * BOOTSTRAPS) - 1
    print(f"95% intervals (bootstrap over works); difference is from {best}:")
    for name in CANDIDATES:
        f1 = sorted(boots[name])
        diff = sorted(a - b for a, b in zip(boots[name], boots[best]))
        print(f"  {name:24s} {f1[lo]:.3f} to {f1[hi]:.3f}   difference {diff[lo]:+.3f} to {diff[hi]:+.3f}")


def run_score():
    key = json.loads((CHECK / "key.json").read_text(encoding="utf-8"))
    marks = {p.stem: json.loads(p.read_text(encoding="utf-8"))
             for p in (CHECK / "marks" / "check_marks").glob("p*.json")}
    unfinished = [p for p in key if marks.get(p, {}).get("status") != "done"]
    if unfinished:
        raise SystemExit(f"{len(unfinished)} works aren't checked yet (first: {unfinished[0]}).")
    works, checks = [], []
    for w in blank_works():
        m = marks[w["id"]]
        checks.append({"kinds": key[w["id"]], "wrong": m["wrong"], "stars": m["stars"]})
        works.append(w | {"gold": adjudicated_gold(list(key[w["id"]]), m["wrong"], m["stars"])})
    print_marks(works, checks)
    print(f"\nleft out of the deciding table: {MISMATCHED}")
    print_scores([w for w in works if w["id"] not in MISMATCHED], "ADJUDICATED GOLD (this table picks the winner)")
    print_scores(works, "All 40, mismatched works included (reported only)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("step", choices=["build", "score"])
    {"build": build, "score": run_score}[parser.parse_args().step]()
