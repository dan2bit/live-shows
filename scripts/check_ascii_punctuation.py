#!/usr/bin/env python3
"""check_ascii_punctuation.py — warn-only scan for non-ASCII punctuation in
pipeline-consumed data.

Canonical keys and machine-managed columns use ASCII punctuation; a curly quote
or long dash in a data value silently orphans a join (sidecar keys, goal-badge
matches, alias lookups) or gets rewritten by CI. This enforces the data-write
playbook's ASCII rule, which was previously convention-only.

Scanned: the public TSVs (every value), config.yaml (scalar VALUES only —
comments are prose and exempt, as are a small set of display-prose keys where
typographic punctuation is legitimate), and data/setlists/*.json string values.
The Photo:/Playlist: issue-title half of the rule is enforced at issue-close
time, not here. Accented letters (e, o, c with diacritics) always pass — this
is a punctuation check, not an ASCII-only check.

Always exits 0: it warns (GitHub Actions ::warning annotations), never blocks.

The issue history behind these designs is logged in docs/ISSUE_LOG.md.
"""

import glob
import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

# The offenders and their ASCII replacements (for the warning text).
BAD = {
    "‘": "'", "’": "'",          # curly single quotes
    "“": '"', "”": '"',          # curly double quotes
    "–": "-", "—": "-",          # en dash, em dash
    "…": "...",                        # ellipsis
    "×": "x",                          # multiplication sign
}

TSV_FILES = [
    "data/live_shows_current.tsv",
    "data/live_shows_potential.tsv",
    "data/fast_track.tsv",
    "data/artists.tsv",
]

# config.yaml values where typographic punctuation is display prose, not a key.
CONFIG_PROSE_KEYS = {"about_text", "about_tagline", "about_footer", "description",
                     "tagline", "label", "about_hero_alt"}

warned = 0


def warn(where, line, text):
    global warned
    warned += 1
    loc = f"file={where}" + (f",line={line}" if line else "")
    print(f"::warning {loc}::{text}")


def scan_text(where, text, lineno):
    for ch, repl in BAD.items():
        if ch in text:
            warn(where, lineno,
                 f"non-ASCII punctuation {ch!r} (use {repl!r}): {text.strip()[:80]}")


def scan_tsv(path):
    p = Path(path)
    if not p.exists():
        return
    for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        scan_text(path, line, i)


def scan_config(path):
    p = Path(path)
    if not p.exists() or yaml is None:
        return
    def walk(node, keypath):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, keypath + [str(k)])
        elif isinstance(node, list):
            for v in node:
                walk(v, keypath)
        elif isinstance(node, str):
            if keypath and keypath[-1] in CONFIG_PROSE_KEYS:
                return
            for ch, repl in BAD.items():
                if ch in node:
                    warn(path, None,
                         f"non-ASCII punctuation {ch!r} (use {repl!r}) in "
                         f"{'.'.join(keypath)}: {node[:80]}")
    walk(yaml.safe_load(p.read_text(encoding="utf-8")), [])


def scan_json(path):
    def walk(node, keypath):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, keypath + [str(k)])
        elif isinstance(node, list):
            for v in node:
                walk(v, keypath)
        elif isinstance(node, str):
            for ch, repl in BAD.items():
                if ch in node:
                    warn(path, None,
                         f"non-ASCII punctuation {ch!r} (use {repl!r}) at "
                         f"{'.'.join(keypath)}: {node[:80]}")
    walk(json.loads(Path(path).read_text(encoding="utf-8")), [])


def main() -> int:
    for f in TSV_FILES:
        scan_tsv(f)
    scan_config("config.yaml")
    for f in sorted(glob.glob("data/setlists/*.json")):
        scan_json(f)
    print(f"check_ascii_punctuation: {warned} warning(s)." if warned
          else "check_ascii_punctuation: clean.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
