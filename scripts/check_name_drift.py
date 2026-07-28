#!/usr/bin/env python3
"""check_name_drift.py — warn-only artist-name drift / alias-coverage scan.

Applies the shared surface-form vocabulary (name_forms.py + recommend_aliases.tsv)
across every artist-bearing column and warns on the drift classes that silently
orphan joins (sidecar keys, goal-badge matches, modal/recommend lookups):

  1. NEAR-COLLISION: two distinct tracked canonical keys within Levenshtein
     distance 2 — usually a typo or an accidental duplicate row.
  2. NEAR-MISS DRIFT: a surface name (or bill component) that resolves to no
     tracked entity but sits within Levenshtein distance 2 of one — the
     "Bethesda Theatre for Bethesda Theater" class, where the entity IS tracked
     and a spelling slip silently misses the join. Genuinely untracked one-off
     support acts are normal, resolve nowhere near a tracked key, and are only
     counted, not warned.
  3. ALIAS HEALTH: duplicate alias keys (silent overwrite), plus an
     informational split of exercised vs defensive aliases. Alias TARGETS are
     canonical short join forms by design (e.g. a long bill name -> its
     headline name) and are deliberately not required to be tracked rows.

Legitimately-distinct near-pairs (e.g. Eric Johanson / Eric Johnson) live in
the allowlist below and are exempt from checks 1 and 2.

Always exits 0 — read-only, warn-only, and deliberately kept that way. Near-miss
matching has intrinsic false positives, and a fuzzy check that can block a
promotion is how a guard ends up switched off. Findings are delivered as
annotations and as a job-summary section; they never gate anything.

The issue history behind these designs is logged in docs/ISSUE_LOG.md.
"""

import csv
import glob
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from name_forms import goal_norm, variant_keys, bill_components  # noqa: E402
from hygiene_report import Report  # noqa: E402

ALIASES_PATH = "data/recommend_aliases.tsv"

# Sorted (key_a, key_b) pairs that are close in spelling but genuinely
# different artists.
NEAR_COLLISION_ALLOWLIST = {
    tuple(sorted(("eric johanson", "eric johnson"))),
    tuple(sorted(("blood brothers", "wood brothers"))),
}


def max_distance(a, b):
    """Edit-distance tolerance scaled to key length: 2 edits in a long name is
    a typo; 2 edits in a 4-letter name is a different word."""
    n = min(len(a), len(b))
    if n >= 7:
        return 2
    if n >= 4:
        return 1
    return 0

report = Report("check_name_drift")


def warn(msg):
    report.warn(msg)


def read_col(path, *cols):
    p = Path(path)
    if not p.exists():
        return []
    rows = list(csv.DictReader(p.open(encoding="utf-8"), delimiter="\t"))
    out = []
    for r in rows:
        for c in cols:
            v = (r.get(c) or "").strip()
            if v and v != "-":
                out.append(v)
    return out


def levenshtein(a, b, cap=3):
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        if min(cur) > cap:
            return cap + 1
        prev = cur
    return prev[-1]


def allowlisted(a, b):
    return tuple(sorted((a, b))) in NEAR_COLLISION_ALLOWLIST


def main() -> int:
    # ── the tracked universe (entities with a home row somewhere) ──
    tracked_raw = set()
    tracked_raw.update(read_col("data/artists.tsv", "Artist"))
    tracked_raw.update(read_col("data/fast_track.tsv", "Artist"))
    tracked_raw.update(read_col("tools/research/follows/follows_master.tsv", "Artist"))
    tracked_raw.update(read_col("data/seen_with.tsv", "Headliner", "Seen With"))

    tracked_keys = set()
    for r in tracked_raw:
        tracked_keys.update(variant_keys(r))
        tracked_keys.add(goal_norm(r))
    tracked_keys.discard("")

    # ── aliases ──
    aliases = {}
    p = Path(ALIASES_PATH)
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.startswith("Alias\t"):
                continue
            parts = line.split("\t")
            if len(parts) >= 2 and parts[0] and parts[1]:
                k = goal_norm(parts[0])
                if k in aliases and aliases[k] != parts[1].strip():
                    warn(f"duplicate alias key {k!r}: {aliases[k]!r} vs "
                         f"{parts[1].strip()!r} — later row silently wins")
                aliases[k] = parts[1].strip()
    resolvable = tracked_keys | set(aliases)

    # ── every artist-bearing surface, '/'-pre-split, plus bill components ──
    surfaces = set(tracked_raw)
    surfaces.update(read_col("data/live_shows_current.tsv", "Artist", "Supporting Artist"))
    surfaces.update(read_col("data/live_shows_potential.tsv", "Artist"))
    for f in sorted(glob.glob("data/history/*.tsv")):
        surfaces.update(read_col(f, "Artist", "Supporting Acts"))
    names = set()
    for s in surfaces:
        parts = [x.strip() for x in s.split("/") if x.strip()] if "/" in s else [s]
        for part in parts:
            names.add(part)
            names.update(bill_components(part))

    # ── check 1: near-collisions inside the tracked universe ──
    keys = sorted(tracked_keys)
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            if abs(len(a) - len(b)) > 2 or allowlisted(a, b):
                continue
            d = levenshtein(a, b, cap=2)
            if 0 < d <= max_distance(a, b):
                warn(f"near-collision tracked keys (distance {d}): {a!r} vs {b!r} — "
                     f"typo/duplicate, or add to the allowlist if genuinely distinct")

    # ── check 2: near-miss drift from unresolved surfaces ──
    unresolved = set()
    for s in sorted(names):
        k = goal_norm(s)
        if not k or k in resolvable:
            continue
        unresolved.add(k)
        for t in keys:
            if abs(len(k) - len(t)) > 2 or allowlisted(k, t):
                continue
            d = levenshtein(k, t, cap=2)
            if 0 < d <= max_distance(k, t):
                warn(f"near-miss drift (distance {d}): surface {s!r} almost "
                     f"matches tracked {t!r} — typo orphaning the join, or a "
                     f"genuinely distinct artist for the allowlist")

    # ── check 3: alias health ──
    surface_keys = {goal_norm(s) for s in names}
    exercised, defensive = [], []
    for akey in sorted(aliases):
        (exercised if akey in surface_keys else defensive).append(akey)
    load_bearing = [a for a in exercised if a not in tracked_keys]
    print(f"alias health: {len(aliases)} aliases — {len(exercised)} exercised "
          f"({len(load_bearing)} load-bearing), {len(defensive)} defensive")
    print(f"surface census: {len(names)} distinct names, "
          f"{len(unresolved)} untracked (one-off support acts are normal)")

    return report.finish()


if __name__ == "__main__":
    sys.exit(main())
