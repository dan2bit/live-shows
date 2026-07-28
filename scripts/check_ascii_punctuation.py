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

Modes:
  (default)  warn only, exit 0 — annotations plus a job-summary section.
  --strict   exit 1 if anything is found. Optionally scoped: --strict FILE...
             judges only those files, so a push is blocked by what it touched
             rather than by unrelated pre-existing values.
  --fix      rewrite the offenders to their ASCII equivalents, TSVs only.
             config.yaml and the setlists JSON are never auto-fixed: their
             prose-bearing values are where a long dash can be legitimate, so
             a blind rewrite there would be a content change, not a repair.

The offender set is eight fixed characters and the repair is mechanical, which
is why this check is safe to make blocking: there is no heuristic to produce a
false positive and nothing for a reviewer to adjudicate.

The issue history behind these designs is logged in docs/ISSUE_LOG.md.
"""

import argparse
import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hygiene_report import Report, scope_from_args  # noqa: E402

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

report = Report("check_ascii_punctuation")


def warn(where, line, text):
    report.warn(text, path=where, line=line)


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


def fix_tsvs(paths):
    """Rewrite BAD characters to their ASCII equivalents in the given TSVs.

    TSV values are all in scope for the rule, so a whole-file character swap is
    exactly the repair the check is asking for. Returns (files_changed,
    replacements).
    """
    files, swaps = 0, 0
    for path in paths:
        p = Path(path)
        if not p.exists():
            continue
        original = p.read_text(encoding="utf-8")
        fixed = original
        for ch, repl in BAD.items():
            if ch in fixed:
                swaps += fixed.count(ch)
                fixed = fixed.replace(ch, repl)
        if fixed != original:
            p.write_text(fixed, encoding="utf-8")
            files += 1
            print(f"fixed: {path}")
    return files, swaps


def scan_all():
    for f in TSV_FILES:
        scan_tsv(f)
    scan_config("config.yaml")
    for f in sorted(glob.glob("data/setlists/*.json")):
        scan_json(f)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--strict", nargs="*", metavar="FILE", default=None,
                    help="exit 1 on findings; with FILEs, only those files block")
    ap.add_argument("--fix", action="store_true",
                    help="rewrite offenders to ASCII in the public TSVs, then re-scan")
    args = ap.parse_args(argv)

    if args.fix:
        files, swaps = fix_tsvs(TSV_FILES)
        print(f"check_ascii_punctuation --fix: {swaps} replacement(s) "
              f"across {files} file(s).")

    scan_all()
    return report.finish(strict=args.strict is not None,
                         scope=scope_from_args(args.strict))


if __name__ == "__main__":
    sys.exit(main())
