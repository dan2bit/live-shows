#!/usr/bin/env python3
"""fork_reset.py — reset a fresh fork of live-shows to a clean, working, empty
tracker (the "Level 0" fork bootstrap).

What it does (see --dry-run for the exact file list):
  1. Copies every sample-files/*-sample.tsv over its canonical data/ file
     (header + one synthetic row you delete via the in-page editor).
  2. Rewrites the derived JSON caches as empty-but-valid structures so the
     site loads with zero artists and zero console errors.
  3. Deletes data/history/*.tsv and data/setlists/*.json, and sets
     `history_years: []` in config.yaml so nothing 404s.
  4. Optionally (--patch-meta) applies config.yaml site/meta values to the
     hand-maintained static <head> block in index.html — a ONE-SHOT bootstrap;
     the block stays hand-maintained afterward, by design.
  5. Optionally (--private-dir PATH) seeds the private-repo files
     (current_private.tsv, potential_private.tsv, fast_track_caps.tsv,
     spending.tsv, taste_profile.md) into a directory that MUST be outside
     this repo — your clone of the separate private repo.
  6. Prints the manual next-steps checklist (secrets, Pages, images).

Safety:
  * Refuses to run when `git remote origin` points at dan2bit/live-shows
    (the origin repo) unless --force-origin is given.
  * Refuses --private-dir paths that resolve inside this repo's working tree
    (private sidecars must never exist as paths inside the public repo).
  * --dry-run prints the plan and touches nothing.

Run from anywhere inside your fork's clone:  python3 scripts/fork_reset.py --dry-run
"""

import argparse
import datetime
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ORIGIN_BLOCK = "dan2bit/live-shows"  # refuse to reset the original repo

# sample -> canonical (paths relative to repo root)
SAMPLE_MAP = {
    "sample-files/live_shows_current-sample.tsv": "data/live_shows_current.tsv",
    "sample-files/live_shows_potential-sample.tsv": "data/live_shows_potential.tsv",
    "sample-files/fast_track-sample.tsv": "data/fast_track.tsv",
    "sample-files/artists-sample.tsv": "data/artists.tsv",
    "sample-files/venues-sample.tsv": "data/venues.tsv",
    "sample-files/venue_aliases-sample.tsv": "data/venue_aliases.tsv",
    "sample-files/recommend_aliases-sample.tsv": "data/recommend_aliases.tsv",
    "sample-files/related_acts-sample.tsv": "data/related_acts.tsv",
    "sample-files/seen_with-sample.tsv": "data/seen_with.tsv",
    "sample-files/show_goals/hat_eligibility-sample.tsv": "data/show_goals/hat_eligibility.tsv",
    "sample-files/show_goals/autograph_books_eligibility-sample.tsv": "data/show_goals/autograph_books_eligibility.tsv",
    "sample-files/show_goals/artist-albums-sample.tsv": "data/show_goals/artist-albums.tsv",
    "sample-files/show_goals/artist-photos-sample.tsv": "data/show_goals/artist-photos.tsv",
    "sample-files/show_goals/book_signatures-sample.tsv": "data/show_goals/book_signatures.tsv",
    "sample-files/show_goals/hat_signatures-sample.tsv": "data/show_goals/hat_signatures.tsv",
}

# private seeds: sample -> filename at the PRIVATE repo root
PRIVATE_MAP = {
    "sample-files/private/current_private-sample.tsv": "current_private.tsv",
    "sample-files/private/potential_private-sample.tsv": "potential_private.tsv",
    "sample-files/private/fast_track_caps-sample.tsv": "fast_track_caps.tsv",
    "sample-files/private/spending-sample.tsv": "spending.tsv",
    "sample-files/private/taste_profile-sample.md": "taste_profile.md",
}


def empty_caches(now_iso: str, today: str) -> dict:
    """Each derived JSON cache's empty-but-parseable form. Shapes are verified
    against the live builders' output; re-verify if a builder's schema changes."""
    return {
        "data/artist_spotify.json": {},
        "data/artist_modal_index.json": {
            "schema_version": 1,
            "generated_at": now_iso,
            "aliases": {},
            "artists": {},
        },
        "data/recommend_index.json": {
            "generated": today,
            "counts": {"records": 0, "variants": 0},
            "records": [],
            "variants": {},
        },
    }


def repo_root() -> Path:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"], text=True, stderr=subprocess.DEVNULL
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        sys.exit("error: run this from inside your fork's git clone.")
    return Path(out.strip()).resolve()


def origin_url(root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(root), "remote", "get-url", "origin"],
            text=True, stderr=subprocess.DEVNULL,
        ).strip()
    except subprocess.CalledProcessError:
        return ""


def cfg_get(cfg: str, key: str) -> str | None:
    """Pull a scalar value for `key:` from config.yaml text (flat regex — the
    config is hand-written YAML with unique key names for everything we need)."""
    m = re.search(rf"^\s*{re.escape(key)}:\s*(.+?)\s*(?:#.*)?$", cfg, re.M)
    if not m:
        return None
    return m.group(1).strip().strip('"').strip("'")


def patch_meta(root: Path, plan_only: bool) -> list[str]:
    """One-shot: apply config site/meta values to index.html's static head.
    Conservative line-anchored replaces; any tag whose source key is missing
    is left untouched and reported."""
    cfg = (root / "config.yaml").read_text(encoding="utf-8")
    idx_path = root / "index.html"
    idx = idx_path.read_text(encoding="utf-8")

    title = cfg_get(cfg, "title")
    owner = cfg_get(cfg, "owner")
    repo = cfg_get(cfg, "repo")
    desc = cfg_get(cfg, "description")
    canonical = cfg_get(cfg, "canonical")
    theme = cfg_get(cfg, "theme_color")
    hero = cfg_get(cfg, "about_hero_image")
    ogw = cfg_get(cfg, "og_image_width")
    ogh = cfg_get(cfg, "og_image_height")

    if owner and repo and not canonical:
        canonical = f"https://{owner}.github.io/{repo}/"
    hero_url = None
    if canonical and hero:
        hero_url = canonical.rstrip("/") + "/" + hero.lstrip("/")
    combo_title = f"{title} — @{owner}" if (title and owner) else title

    subs: list[tuple[str, str, str | None]] = [
        (r"(<title>)[^<]*(</title>)", r"\g<1>{}\g<2>", title),
        (r'(<link rel="canonical" href=")[^"]*(")', r"\g<1>{}\g<2>", canonical),
        (r'(<meta name="description" content=")[^"]*(")', r"\g<1>{}\g<2>", desc),
        (r'(<meta name="theme-color" content=")[^"]*(")', r"\g<1>{}\g<2>", theme),
        (r'(<meta property="og:site_name" content=")[^"]*(")', r"\g<1>{}\g<2>", title),
        (r'(<meta property="og:title" content=")[^"]*(")', r"\g<1>{}\g<2>", combo_title),
        (r'(<meta property="og:description" content=")[^"]*(")', r"\g<1>{}\g<2>", desc),
        (r'(<meta property="og:url" content=")[^"]*(")', r"\g<1>{}\g<2>", canonical),
        (r'(<meta property="og:image" content=")[^"]*(")', r"\g<1>{}\g<2>", hero_url),
        (r'(<meta property="og:image:width" content=")[^"]*(")', r"\g<1>{}\g<2>", ogw),
        (r'(<meta property="og:image:height" content=")[^"]*(")', r"\g<1>{}\g<2>", ogh),
        (r'(<meta name="twitter:title" content=")[^"]*(")', r"\g<1>{}\g<2>", combo_title),
        (r'(<meta name="twitter:description" content=")[^"]*(")', r"\g<1>{}\g<2>", desc),
        (r'(<meta name="twitter:image" content=")[^"]*(")', r"\g<1>{}\g<2>", hero_url),
    ]

    notes, patched = [], 0
    for pat, repl, val in subs:
        if val is None:
            notes.append(f"  skipped (no config value): {pat[:48]}…")
            continue
        idx, n = re.subn(pat, repl.format(val), idx, count=1)
        patched += n
    notes.insert(0, f"  {patched} head tag(s) patched from config.yaml")
    notes.append("  NOT patched (no config key yet — edit by hand): og:image:alt")
    if not plan_only:
        idx_path.write_text(idx, encoding="utf-8")
    return notes


NEXT_STEPS = """
── Manual next steps (nothing below is automated on purpose) ─────────────────
 1. Commit this reset and push. Enable Pages: Settings → Pages → Deploy from
    a branch → main / root. Your empty tracker should render with no console
    errors — that is the Level 0 acceptance test.
 2. Edit config.yaml site.* (title, owner, repo, about_* text and links) —
    every key is annotated in-file. Re-run with --patch-meta afterward, or
    hand-edit the <!-- config: --> flagged tags in index.html's <head>.
 3. Replace the three static images (KEEP the same file names; their URLs in
    index.html are absolute BY DESIGN — do not relativize them):
      static/favicon.png   32x32 or 48x48 PNG. (Original: 32x32, 3 KB — right-sized.)
      static/brand-hat.png transparent PNG, ~256x256 is plenty — the largest
                           render is ~104 px. (Original: 800x800, 52 KB — provably
                           larger than necessary; don't copy that.)
      static/hero.jpg      16:9 JPEG, 960x540, target <= 150 KB at ~q75-80.
                           (Original: 509 KB — too heavy.) Layout constraints from
                           the About modal: the image displays as a 480x200 crop,
                           object-fit: cover anchored CENTER-BOTTOM — keep your
                           subject in the center/bottom third; keep the UPPER-LEFT
                           quiet (the handle text + a dark gradient sit there);
                           keep the LOWER-RIGHT simple (the tagline overhangs it).
                           After swapping: update meta.og_image_width/height in
                           config.yaml and re-run --patch-meta, and hand-edit
                           og:image:alt in index.html.
 4. In-browser editing token: fine-grained PAT (Contents + Issues, read/write,
    your public repo only) pasted into the site's auth modal. See
    docs/FORK_SETUP.md §"The site-editing token".
 5. Level 1 (private sidecar): create a SEPARATE private repo; run this tool
    again with --private-dir <path-to-that-clone>; commit there to its main.
    (gh repo create <you>/<repo>-private --private)
 6. Level 2 (CI): auto-promote needs a deploy key + secret; the in-page
    recommendations feature needs its own throwaway token — and note that
    RECOMMEND_PAT is split across two concatenated string literals in
    recommend.js to pass push protection; do NOT "fix" it into one string.
    Spotify cache workflows need Spotify API credentials. Details:
    docs/FORK_SETUP.md Level 2.
 7. Cosmetic leftovers: the four About-modal link labels and the hero alt text
    are still hardcoded in index.html - edit them there.
──────────────────────────────────────────────────────────────────────────────
"""


def main() -> None:
    ap = argparse.ArgumentParser(description="Reset a fresh live-shows fork to a clean empty tracker.")
    ap.add_argument("--dry-run", action="store_true", help="print the plan; change nothing")
    ap.add_argument("--private-dir", metavar="PATH", help="also seed private-repo files into PATH (must be outside this repo)")
    ap.add_argument("--patch-meta", action="store_true", help="one-shot: apply config.yaml site/meta values to index.html's static <head>")
    ap.add_argument("--force-origin", action="store_true", help="allow running even when origin is the original dan2bit repo")
    ap.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    args = ap.parse_args()

    root = repo_root()
    origin = origin_url(root)
    if ORIGIN_BLOCK in origin and not args.force_origin:
        sys.exit(
            f"error: origin is {origin!r} — this looks like the ORIGINAL repo, not a fork.\n"
            "Refusing to reset it. (If you really mean it: --force-origin.)"
        )

    private_dir = None
    if args.private_dir:
        private_dir = Path(args.private_dir).expanduser().resolve()
        if private_dir == root or root in private_dir.parents or private_dir in (root,):
            sys.exit(
                f"error: --private-dir {private_dir} resolves INSIDE this repo's working tree.\n"
                "Private sidecar files must live in a separate private repo — never as paths\n"
                "inside the public repo. Point --private-dir at your private repo's clone."
            )

    now = datetime.datetime.now(datetime.timezone.utc)
    caches = empty_caches(now.strftime("%Y-%m-%dT%H:%M:%SZ"), now.strftime("%Y-%m-%d"))

    # ---- build the plan ----
    plan: list[tuple[str, str]] = []
    for sample, canon in SAMPLE_MAP.items():
        if not (root / sample).exists():
            sys.exit(f"error: missing {sample} — is this checkout complete?")
        plan.append(("copy ", f"{sample}  ->  {canon}"))
    for path in caches:
        plan.append(("write", f"{path}  (empty valid structure)"))
    hist = sorted((root / "data/history").glob("*.tsv")) if (root / "data/history").is_dir() else []
    sets = sorted((root / "data/setlists").glob("*.json")) if (root / "data/setlists").is_dir() else []
    for p in hist + sets:
        plan.append(("rm   ", str(p.relative_to(root))))
    plan.append(("edit ", "config.yaml  (history_years: [])"))
    if args.patch_meta:
        plan.append(("patch", "index.html  (static <head> from config site/meta values)"))
    if private_dir:
        for sample, name in PRIVATE_MAP.items():
            plan.append(("seed ", f"{sample}  ->  {private_dir / name}"))

    print(f"fork_reset plan for {root}  (origin: {origin or 'none'})")
    for verb, desc in plan:
        print(f"  {verb} {desc}")
    if args.dry_run:
        print("\n--dry-run: nothing was changed.")
        return
    if not args.yes:
        resp = input(f"\nThis rewrites {len(plan)} target(s) in place. Proceed? [y/N] ")
        if resp.strip().lower() not in ("y", "yes"):
            sys.exit("aborted.")

    # ---- execute ----
    for sample, canon in SAMPLE_MAP.items():
        dest = root / canon
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / sample, dest)
    for path, obj in caches.items():
        (root / path).write_text(json.dumps(obj, indent=1) + "\n", encoding="utf-8")
    for p in hist + sets:
        p.unlink()
    cfg_path = root / "config.yaml"
    cfg = cfg_path.read_text(encoding="utf-8")
    cfg, n = re.subn(r"^history_years:\s*\[[^\]]*\]", "history_years: []", cfg, count=1, flags=re.M)
    cfg_path.write_text(cfg, encoding="utf-8")
    if n == 0:
        print("warning: history_years key not found in config.yaml — set it to [] by hand.")
    if args.patch_meta:
        for line in patch_meta(root, plan_only=False):
            print(line)
    if private_dir:
        private_dir.mkdir(parents=True, exist_ok=True)
        for sample, name in PRIVATE_MAP.items():
            shutil.copyfile(root / sample, private_dir / name)
        print(f"\nPrivate seeds written to {private_dir} — commit them to your PRIVATE repo's main.")
        print("Reminder: separate repo, files at its root; they must never appear in the public repo.")

    print(NEXT_STEPS)


if __name__ == "__main__":
    main()
