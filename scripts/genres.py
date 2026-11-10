"""The genre scheme as data, parsed from docs/genre-scheme-draft.md.

The Markdown file is the source of truth. `load_scheme()` returns
[{family, genres: [{id, name, subgenres: [{id, name}]}]}].
Usage: uv run scripts/genres.py   (prints the counts and writes docs/genre-scheme.json)
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEME_MD = ROOT / "docs" / "genre-scheme-draft.md"
SCHEME_JSON = ROOT / "docs" / "genre-scheme.json"

SOURCE_TAG = re.compile(r"\s*\((?:[WBNAC](?: [WBNAC])*|novel)\)")  # "(W B N)", "(C)", "(novel)"
GENRE_LINE = re.compile(r"^- \*\*(.+?)\*\*(.*)$")


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def split_outside_parens(text):
    """Split on commas that aren't inside parentheses."""
    parts, depth, current = [], 0, ""
    for ch in text:
        depth += (ch == "(") - (ch == ")")
        if ch == "," and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += ch
    return [p.strip() for p in parts + [current] if p.strip()]


def parse_scheme(markdown):
    """Parse the '## The draft' section into families, genres and subgenres."""
    body = markdown.split("## The draft", 1)[1].split("\n## ", 1)[0]
    families = []
    for line in body.splitlines():
        if line.startswith("### "):
            name = re.sub(r"\s*\(.*\)$", "", line[4:].strip())
            families.append({"family": name, "genres": []})
            continue
        m = GENRE_LINE.match(line)
        if not m or not families:
            continue
        genre = m.group(1).strip()
        rest = SOURCE_TAG.sub("", m.group(2)).lstrip(": ").strip()
        subs = [SOURCE_TAG.sub("", s).strip() for s in split_outside_parens(rest)]
        families[-1]["genres"].append({
            "id": slug(genre), "name": genre,
            "subgenres": [{"id": f"{slug(genre)}/{slug(s)}", "name": s} for s in subs if s],
        })
    return families


def load_scheme():
    return parse_scheme(SCHEME_MD.read_text(encoding="utf-8"))


def counts(scheme):
    genres = [g for f in scheme for g in f["genres"]]
    return len(scheme), len(genres), sum(len(g["subgenres"]) for g in genres)


if __name__ == "__main__":
    scheme = load_scheme()
    SCHEME_JSON.write_text(json.dumps(scheme, indent=1, ensure_ascii=False), encoding="utf-8")
    print("families, genres, subgenres:", counts(scheme))
    for family in scheme:
        print(f"\n{family['family']}")
        for g in family["genres"]:
            print(f"  {g['name']}: {', '.join(s['name'] for s in g['subgenres']) or '(no subgenres)'}")
