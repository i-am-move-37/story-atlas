"""Score the genre-labeling methods against Scott's gold set (research plan 2.3).

Reads  data/pilot/gold/pilot_labels/pNNN.json  Scott's labels, exported from the labeling page
       data/pilot/methods.json                 the three methods' labels
       data/pilot/upload/pNNN.json             the pooled drafts shown for the draft-mode works
Writes data/pilot/disagreements.md             every scored work where a method and the gold differ

The rules, fixed before any real score was computed:
- Scored at the genre level (the 44): a subgenre counts as its parent.
- A gold label marked borderline neither helps nor hurts.
- A work a method gives no label to is not covered, and its gold core labels count as missed.
- Only works Scott labeled (not skipped) that are in scope are scored.
- Winner: best micro-F1 among candidates covering at least 90%. Candidates within 2 points
  of the best are tied, and the tie goes to the one that leans least on the plot text.

Usage: uv run scripts/score_pilot.py [--allow-unfinished]
"""

import argparse
import json
from collections import Counter
from pathlib import Path

import pandas as pd

from label_pilot import current_scope

ROOT = Path(__file__).resolve().parent.parent
PILOT = ROOT / "data" / "pilot"

MIN_COVERAGE = 0.90
TIE_MARGIN = 0.02
MIN_GOLD_FOR_KAPPA = 5
# Single methods and hybrids by availability: each takes the first source that answers.
CANDIDATES = {
    "wikidata": ("wikidata",), "metadata": ("metadata",), "plot": ("plot",),
    "wikidata+metadata": ("wikidata", "metadata"), "wikidata+plot": ("wikidata", "plot"),
    "metadata+plot": ("metadata", "plot"), "wikidata+metadata+plot": ("wikidata", "metadata", "plot"),
}


# ---------- pure helpers ----------

def at_level(label_id, level):
    return label_id.split("/")[0] if level == "genre" else label_id


def gold_sets(labels, level):
    """(core, borderline) sets of a work's gold labels; a label in both is core."""
    core = {at_level(x["id"], level) for x in labels if x["level"] == "core"}
    borderline = {at_level(x["id"], level) for x in labels if x["level"] != "core"}
    return core, borderline - core


def predicted(labels, level, core_only=False):
    return {at_level(x["id"], level) for x in labels or [] if not core_only or x["level"] == "core"}


def answer(methods, chain):
    """(source, labels) from the first source in the chain that gives any label."""
    for source in chain:
        if methods.get(source):
            return source, methods[source]
    return None, []


def tally(pred, core, borderline):
    """(hits, wrong, missed). Gold borderline labels are in none of the three."""
    return len(pred & core), len(pred - core - borderline), len(core - pred)


def score(works, chain, level="genre", core_only=False):
    """Micro-averaged precision, recall and F1 of one candidate over `works`."""
    tp = fp = fn = 0
    used = Counter()
    for w in works:
        source, given = answer(w["methods"], chain)
        if source:
            used[source] += 1
        hits, wrong, missed = tally(predicted(given, level, core_only), *gold_sets(w["gold"], level))
        tp, fp, fn = tp + hits, fp + wrong, fn + missed
    n = len(works)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {"n": n, "covered": sum(used.values()), "coverage": sum(used.values()) / n if n else 0.0,
            "tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall,
            "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
            "share": {s: used[s] / n for s in chain if used[s]}}


def pick_winner(scores):
    """Name of the winning candidate, or None if none covers enough works."""
    eligible = {name: s for name, s in scores.items() if s["coverage"] >= MIN_COVERAGE}
    if not eligible:
        return None
    best = max(s["f1"] for s in eligible.values())
    tied = [name for name, s in eligible.items() if best - s["f1"] <= TIE_MARGIN + 1e-9]
    return min(tied, key=lambda name: (eligible[name]["share"].get("plot", 0.0),
                                       eligible[name]["share"].get("metadata", 0.0),
                                       -eligible[name]["f1"]))


def kappa(a, b):
    """Cohen's kappa for two lists of 0/1; None when chance agreement is total."""
    n = len(a)
    if not n:
        return None
    observed = sum(x == y for x, y in zip(a, b)) / n
    pa, pb = sum(a) / n, sum(b) / n
    chance = pa * pb + (1 - pa) * (1 - pb)
    return None if chance == 1 else (observed - chance) / (1 - chance)


def label_kappas(works, chain, level):
    """{label: kappa, gold count, works counted} of a candidate against the gold set.

    For each label, works where the gold marks it borderline are left out.
    """
    rows = []
    for w in works:
        core, borderline = gold_sets(w["gold"], level)
        rows.append((core, borderline, predicted(answer(w["methods"], chain)[1], level)))
    out = {}
    for label in sorted(set().union(*(core | pred for core, _, pred in rows)) if rows else []):
        kept = [(label in core, label in pred) for core, borderline, pred in rows if label not in borderline]
        gold, pred = [int(g) for g, _ in kept], [int(p) for _, p in kept]
        out[label] = {"kappa": kappa(gold, pred), "gold": sum(gold), "works": len(kept)}
    return out


def anchoring(drafts):
    """What became of the suggestions on the draft-mode works: [{draft: [ids], gold: labels}]."""
    counts = Counter()
    for d in drafts:
        level = {x["id"]: x["level"] for x in d["gold"]}
        counts["suggested"] += len(d["draft"])
        for i in d["draft"]:
            counts["removed" if i not in level else f"kept {level[i]}"] += 1
        counts["added"] += sum(1 for i in level if i not in d["draft"])
    return {k: counts[k] for k in ("suggested", "kept core", "kept borderline", "removed", "added")}


# ---------- loading and reporting ----------

def load_works(allow_unfinished):
    methods = json.loads((PILOT / "methods.json").read_text(encoding="utf-8"))
    sample = pd.read_parquet(PILOT / "sample.parquet").set_index("pilot_id")
    scope = current_scope(sample.reset_index(), pd.read_parquet(ROOT / "data" / "works.parquet"))
    drafts = {p.stem: json.loads(p.read_text(encoding="utf-8"))["draft"] for p in (PILOT / "upload").glob("p*.json")}
    gold = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in (PILOT / "gold" / "pilot_labels").glob("p*.json")}
    shown = [p for p in sample.index if sample.loc[p, "mode"] == "blank" or p in drafts]
    unfinished = [p for p in shown if gold.get(p, {}).get("status") not in ("done", "skipped")]
    if unfinished and not allow_unfinished:
        raise SystemExit(f"{len(unfinished)} works aren't labeled yet (first: {unfinished[0]}). "
                         "Scores wait until the gold set is finished.")
    works, left_out = [], Counter()
    for p in shown:
        g = gold.get(p, {})
        if g.get("status") != "done" or scope[p] != "in":
            left_out["skipped by Scott" if g.get("status") == "skipped" else
                     "unfinished" if g.get("status") != "done" else f"out of scope ({scope[p]})"] += 1
            continue
        works.append({"id": p, "title": sample.loc[p, "title"], "medium": sample.loc[p, "medium"],
                      "mode": sample.loc[p, "mode"], "gold": g.get("labels", []), "note": g.get("note", ""),
                      "methods": methods[p], "draft": drafts.get(p)})
    return works, left_out


def print_table(title, works, level="genre", core_only=False):
    scores = {name: score(works, chain, level, core_only) for name, chain in CANDIDATES.items()}
    print(f"\n{title}  ({len(works)} works)")
    print(f"  {'candidate':24s} {'coverage':>8s} {'precision':>9s} {'recall':>7s} {'F1':>6s}")
    for name, s in scores.items():
        print(f"  {name:24s} {s['coverage']:8.1%} {s['precision']:9.3f} {s['recall']:7.3f} {s['f1']:6.3f}")
    return scores


def print_kappas(works, chain, name):
    print(f"\nAgreement with the gold set, {name} (kappa; labels with at least {MIN_GOLD_FOR_KAPPA} gold examples)")
    for level in ("genre", "id"):
        rows = [(label, k) for label, k in label_kappas(works, chain, level).items()
                if k["gold"] >= MIN_GOLD_FOR_KAPPA and (level == "genre" or "/" in label)]
        for label, k in sorted(rows, key=lambda r: (r[1]["kappa"] is None, r[1]["kappa"])):
            shown = "  n/a" if k["kappa"] is None else f"{k['kappa']:5.2f}"
            print(f"  {label:44s} {shown}   gold {k['gold']:3d}")


def fmt(labels, level="id"):
    return ", ".join(f"{x['id']}{'' if x['level'] == 'core' else ' (b)'}" for x in labels or []) or "none"


def write_disagreements(works):
    lines = ["# Pilot: where a method and the gold set differ (genre level)", "",
             "(b) marks a borderline label. A method is listed when it missed a gold core genre "
             "or gave a genre the gold doesn't have.", ""]
    for w in works:
        core, borderline = gold_sets(w["gold"], "genre")
        diffs = []
        for source in ("wikidata", "metadata", "plot"):
            given = w["methods"].get(source)
            hits, wrong, missed = tally(predicted(given, "genre"), core, borderline)
            if wrong or missed or not given:
                diffs.append(f"- {source}: {fmt(given) if given else 'no answer'}")
        if diffs:
            lines += [f"## {w['id']} {w['title']} ({w['medium']}, {w['mode']})", f"- gold: {fmt(w['gold'])}"] + diffs
            lines += ([f"- note: {w['note']}"] if w["note"] else []) + [""]
    (PILOT / "disagreements.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-unfinished", action="store_true")
    works, left_out = load_works(parser.parse_args().allow_unfinished)
    print(f"scored works: {len(works)}; left out: {dict(left_out)}")
    print(f"gold labels per work: {sum(len(w['gold']) for w in works) / len(works):.2f}; "
          f"works with no gold label: {sum(1 for w in works if not w['gold'])}")

    scores = print_table("ALL SCORED WORKS, genre level (this table picks the winner)", works)
    winner = pick_winner(scores)
    print(f"\nwinner by the selection rule: {winner}")
    for mode in ("blank", "draft"):
        print_table(f"{mode}-mode works only", [w for w in works if w["mode"] == mode])
    for medium in ("film", "novel"):
        print_table(f"{medium}s only", [w for w in works if w["medium"] == medium])
    print_table("Counting only labels a method called core", works, core_only=True)
    print_table("Exact label (subgenre) level, reported only", works, level="id")

    for name in ("wikidata", "metadata", "plot"):
        print_kappas(works, CANDIDATES[name], name)

    for mode in ("blank", "draft"):
        group = [w for w in works if w["mode"] == mode]
        n = sum(len(w["gold"]) for w in group)
        b = sum(1 for w in group for x in w["gold"] if x["level"] != "core")
        print(f"\n{mode}: {len(group)} works, {n / len(group):.2f} labels per work, {b / n:.0%} borderline")
    print("what became of the suggestions:", anchoring([w for w in works if w["draft"] is not None]))

    print("\nnotes:")
    for w in works:
        if w["note"]:
            print(f"  {w['id']} {w['title']}: {w['note']}")
    write_disagreements(works)
    print(f"\ndisagreements written to {PILOT / 'disagreements.md'}")


if __name__ == "__main__":
    main()
