#!/usr/bin/env python3
"""
prune_cache.py — drop stale keys from data/artist_spotify.json.

Removes any cache entry whose canonical name is no longer produced by
spotify_cache.collect_artists() — artists that have left the repo, plus the
duplicate/bogus surface forms a canonicalization or source fix has folded away
(inverted "X, The", accent/spelling variants, "/"-joined support bills, event
names, "X Band" twins, etc.).

Pure set difference against the live repo artist set: NO Spotify or Last.fm
calls, no quota used. Unlike `spotify_cache.py --refresh --prune`, it does not
require (or trigger) a full Spotify re-pull, so it's the cheap way to clean the
cache after a data/canonicalization change — e.g. right after a `--refresh-lastfm`
seed run, whose JSON still carries the now-stale keys.

Safe by default: reports what it WOULD remove and writes nothing. Re-run with
--apply to delete and save.

Two sanity guards abort an --apply (so a mis-fetched/empty source can't wipe the
cache):
  * repo artist set must exceed MIN_REPO_ARTISTS — a near-empty collection means
    a source TSV failed to load (stale working tree, bad cwd, etc.)
  * stale count must stay under MAX_STALE — a huge stale list means the
    collection changed, not the cache; eyeball it first

Run it from tools/spotify/ (it imports spotify_cache, which resolves all repo
paths from its own location, so cwd otherwise doesn't matter).

USAGE
    python3 prune_cache.py            # dry run: report stale keys, write nothing
    python3 prune_cache.py --apply    # delete the stale keys and save
"""

import argparse
import os
import sys

# Allow running from anywhere: ensure this script's dir (tools/spotify) is importable.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import spotify_cache as sc
except ImportError:
    sys.exit("Could not import spotify_cache — run this from tools/spotify/ "
             "(or keep prune_cache.py beside spotify_cache.py).")

MIN_REPO_ARTISTS = 250   # repo collection at/below this => a source TSV didn't load
MAX_STALE        = 40    # stale count at/above this => eyeball before deleting


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Prune stale keys from artist_spotify.json "
                    "(set difference vs. the repo; no API calls).")
    ap.add_argument("--apply", action="store_true",
                    help="Delete the stale keys and save. Without it, dry-run only.")
    args = ap.parse_args()

    cache = sc.load_cache()
    artists, _ = sc.collect_artists(sc.load_aliases())
    stale = sorted(k for k in cache if k not in artists)

    print(f"cache={len(cache)}  repo={len(artists)}  stale={len(stale)}")
    for k in stale:
        print(f"  - {k}")

    if not stale:
        print("\nNothing to prune.")
        return

    problems = []
    if len(artists) <= MIN_REPO_ARTISTS:
        problems.append(f"only {len(artists)} repo artists collected "
                        f"(expected > {MIN_REPO_ARTISTS}) — a source TSV probably "
                        f"failed to load")
    if len(stale) >= MAX_STALE:
        problems.append(f"{len(stale)} stale keys (>= {MAX_STALE}) — that's a lot, "
                        f"eyeball the list above")

    if not args.apply:
        if problems:
            print("\n[DRY RUN] would remove "
                  f"{len(stale)} key(s), but --apply would ABORT: "
                  + "; ".join(problems) + ".")
        else:
            print(f"\n[DRY RUN] would remove {len(stale)} key(s). "
                  f"Re-run with --apply to delete and save.")
        return

    if problems:
        sys.exit("\nABORT (not pruning): " + "; ".join(problems) + ".")

    for k in stale:
        del cache[k]
    sc.save_cache(cache)
    print(f"\nPruned {len(stale)} key(s); saved {sc.OUTPUT_JSON}")


if __name__ == "__main__":
    main()
