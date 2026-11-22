"""Which works the corpus check removes (decided by Scott, 2026-11-20; see DESIGN.md).

The rule-based `scope` column in works.parquet is left as it is. This module reads the check's
answers and says which further works leave, and why. Nothing is deleted.

Stays: feature films, novels and novellas, short stories, dramatized true stories (biopics).
Leaves: everything of another form, summaries that belong to a different work with the same
title, and works that are not an invented or dramatized story (documentaries, recordings,
books written as fact).
Usage: uv run scripts/check_scope.py   (prints what the check removes)
"""

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LABELS = ROOT / "data" / "labels"
CHECK = LABELS / "check--claude-haiku-5.5.jsonl"
RECHECK = LABELS / "recheck-true-stories--claude-haiku-5.5.jsonl"

KEPT_FORMS = {"feature film", "novel or novella", "short story"}
# Second-pass kinds that keep a work the first pass called "not an invented story".
# "summary does not tell the story" is undecided, so those works stay for now.
KEPT_KINDS = {"dramatized story", "summary does not tell the story"}


def removal_reason(answer, recheck_kind=None):
    """None if the work stays, else a short reason. `answer` is the check's answer for the work;
    `recheck_kind` is the second pass's answer, where there was one."""
    if answer["form"] not in KEPT_FORMS:
        return answer["form"]
    if answer["matches_metadata"] == "no":
        return "different work with the same title"
    if not answer["narrative_fiction"] and recheck_kind not in KEPT_KINDS:
        return recheck_kind or "not an invented story"
    return None


def _rows(path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def removed():
    """work_id -> reason, for every checked work that leaves. Empty if the check hasn't run."""
    kinds = {r["work_id"]: r["answer"]["kind"] for r in _rows(RECHECK) if r["ok"]}
    out = {}
    for r in _rows(CHECK):
        if r["ok"]:
            reason = removal_reason(r["answer"], kinds.get(r["work_id"]))
            if reason:
                out[r["work_id"]] = reason
    return out


if __name__ == "__main__":
    gone = removed()
    print(f"{len(gone):,} works leave")
    for reason, n in Counter(gone.values()).most_common():
        print(f"  {n:5,}  {reason}")
