#!/usr/bin/env python3
"""
Correlates youtube_videos.tsv and youtube_playlists.tsv against show history files.

Naming conventions on @dan2bit channel:
  Videos:    "Sue Foley LIVE - Nothin' In Ramblin' (bootleg)"
             description: "(Memphis Minnie cover) from Hamilton Live (DC) on 03/11/26"
  Playlists: "Keb' Mo' LIVE solo - Maryland Hall, Annapolis 11/21/25"

Logic per show:
  1. PLAYLIST MATCH: Look for a playlist whose title contains the HEADLINER name + "LIVE"
     AND whose title contains a DATE VARIANT matching the show date (required).
     Venue-only matches are intentionally excluded to prevent wrong-year false positives.
     If found → use the playlist URL as the Playlist URL.
  2. VIDEO MATCH: If no playlist found, search for ANY video whose description contains
     a date string matching the show date (MM/DD/YY or MM/DD/YYYY). No artist filter —
     this covers multi-bill shows where supporting acts were filmed instead of the headliner.
  3. Output one row per show with: playlist URL (if found) OR video count.

Key improvements over v1:
  - Playlist matching requires DATE match (venue-only removed — caused year mismatches)
  - artist_in_title uses NOISE_WORDS to avoid generic false positives
  - find_videos uses date-only matching (no artist filter) to catch support act footage

Usage:
    python3 youtube_correlate.py [--merge] [--sync-artists]

    --merge         After writing correlation TSVs, also patch any newly found playlist URLs
                    back into history/*.tsv (per-year archive files) and live_shows_current.tsv.
                    Only fills blank Playlist URL cells — never overwrites an existing URL.

                    NOTE: history/*.tsv write-back is legacy/backfill-only. Once you are
                    current on playlist creation for live_shows_current.tsv, history files
                    will rarely if ever need updating via --merge.

    --sync-artists  After processing attended shows, update artists.tsv:
                      - If an artist is not yet in artists.tsv, add a new row.
                      - If already present, increment Times Seen and update Most Recent Seen
                        if the show date is newer.
                    Can be used with or without --merge. Always does a dry-run preview
                    first and asks for confirmation before writing.

    --dry-run       Preview all changes without writing anything (applies to both
                    --merge and --sync-artists).

Input files (must be in same directory):
    youtube_videos.tsv
    youtube_playlists.tsv
    history/*.tsv              — per-year archive files (2021.tsv, 2022.tsv, ...)
    live_shows_current.tsv     — current year attended + upcoming shows

Output:
    history_youtube_correlation.tsv     — all history years combined
    shows_current_youtube_correlation.tsv — current year attended shows only
    (with --merge) history/*.tsv and live_shows_current.tsv are patched in-place
    (with --sync-artists) artists.tsv is updated in-place

─────────────────────────────────────────────────────────────────────────────
TROUBLESHOOTING — "No match" for a show you know has a playlist or videos
─────────────────────────────────────────────────────────────────────────────

If a show comes back "No match" and you're sure the playlist or videos exist
on the channel, work through these checks in order:

1. PLAYLIST TITLE MISSING "LIVE"
   find_playlist() requires the word "LIVE" (case-insensitive) in the playlist
   title. This is the most common cause of a silent miss — the playlist is
   found by artist and date, but filtered out before it can match.
   Fix: edit the playlist title on YouTube to include "LIVE", then re-run
   youtube_fetch.py --force --since <show-date - a few days> to pull the
   updated title, then re-run --merge.
   Example: "Lucky Chops @ Union Stage (DC) 3/5/23" failed until renamed to
   "Lucky Chops LIVE @ Union Stage (DC) 3/5/23".

2. DATE FORMAT MISMATCH
   find_playlist() looks for date strings like "3/5/23", "3/5/2023",
   "03/05/23", "03/05/2023" anywhere in the playlist title.
   find_videos() looks for the same variants in the video description field.
   If your title or description uses a different format (e.g. "March 5, 2023"
   or "2023-03-05"), neither function will match it.
   Fix: edit the title/description to use the M/D/YY or MM/DD/YY pattern,
   then re-fetch.

3. SHOW DATE WRONG IN HISTORY FILE
   The correlator keys on the Show Date column in history/*.tsv /
   live_shows_current.tsv. If that date is wrong (e.g. set to the YouTube
   publish date rather than the actual show date), the date variants generated
   won't match the title/description.
   Fix: correct the date in the appropriate year file, re-sort, then
   re-run --merge. No re-fetch needed if the playlist title has the right date.
   Sort one-liner (example for 2023):
     (head -1 history/2023.tsv; tail -n +2 history/2023.tsv | \\
       tr -d '\\r' | sort -k1,1) > sorted.tsv && mv sorted.tsv history/2023.tsv

4. ARTIST NAME MISMATCH
   find_playlist() normalizes both the history artist name and the playlist
   title (strips punctuation, lowercases), then checks for the full normalized
   name OR all "distinctive" words (>4 chars, not in NOISE_WORDS).
   If the playlist title spells the artist differently (e.g. "Cris Kingfish
   Ingram" vs "Christone 'Kingfish' Ingram"), it may fail the artist check.
   Check: run normalize() on both strings manually and compare.
   Fix: either update ARTIST_NAME_ALIASES at the top of this file, or rename
   the playlist title to match the canonical artist name.

5. PLAYLIST NOT YET FETCHED / STALE WORKFILE
   youtube_playlists.tsv is only as current as the last youtube_fetch.py run.
   If you created or renamed a playlist after the last fetch, it won't appear.
   Fix: youtube_fetch.py --force --since <show-date - a few days>

6. VIDEO DESCRIPTIONS DON'T CONTAIN THE DATE
   find_videos() searches video descriptions (not titles) for the date string.
   If your video descriptions don't include the show date, video-only matches
   won't work. Playlist matches (which search the playlist title) are unaffected.
   This is informational — no fix needed unless you want video-only fallback.

Quick diagnostic — paste into a python3 REPL in the live-shows/ directory:
    import csv
    from youtube_correlate import date_variants, find_playlist, find_videos, load_tsv
    playlists = load_tsv("youtube_playlists.tsv")
    videos    = load_tsv("youtube_videos.tsv")
    date      = "2023-03-05"       # show date to debug
    artist    = "Lucky Chops"      # headliner name as it appears in history
    print("Date variants:", date_variants(date))
    pl = find_playlist(artist, date, playlists)
    print("Playlist match:", pl["title"] if pl else "None")
    vids = find_videos(date, videos)
    print("Video matches:", len(vids), [v["title"][:60] for v in vids])
"""

import argparse
import csv
import glob
import os
import re
from datetime import datetime


# ── Artist name normalization ─────────────────────────────────────────────────
ARTIST_NAME_ALIASES = {
    'Christone "Kingfish" Ingram':     "Christone 'Kingfish' Ingram",
    'Christone ""Kingfish"" Ingram':   "Christone 'Kingfish' Ingram",
    "Christone Ingram":                "Christone 'Kingfish' Ingram",
    "Kingfish Ingram":                 "Christone 'Kingfish' Ingram",
    "Kingfish":                        "Christone 'Kingfish' Ingram",
}


def normalize_artist_name(name: str) -> str:
    return ARTIST_NAME_ALIASES.get(name, name)


# ── TSV helpers ───────────────────────────────────────────────────────────────

def load_tsv(filename):
    with open(filename, encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def load_history_glob(pattern="history/*.tsv"):
    """
    Load and concatenate all per-year archive files matching pattern.
    Each row gets a '_source_file' key so merge_into_history knows which
    year file to write back to.
    Returns list of rows sorted by Show Date.
    """
    rows = []
    for path in sorted(glob.glob(pattern)):
        for row in load_tsv(path):
            row["_source_file"] = path
            rows.append(row)
    return rows


def write_tsv(rows, fieldnames, filename):
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t",
                                lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _cell(row, key):
    return (row.get(key) or "").strip()


# ── Matching helpers ──────────────────────────────────────────────────────────

def normalize(s):
    return re.sub(r"[^\w\s]", "", s.lower()).strip()


NOISE_WORDS = {"band", "the", "and", "live", "feat", "featuring", "with"}


def artist_in_title(artist, title):
    artist_norm = normalize(artist)
    title_norm = normalize(title)
    if artist_norm in title_norm:
        return True
    words = [w for w in artist_norm.split() if len(w) > 4 and w not in NOISE_WORDS]
    if not words:
        return False
    return all(w in title_norm for w in words)


def date_variants(date_str):
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return []
    yy = d.strftime("%y")
    yyyy = d.strftime("%Y")
    return [
        f"{d.month}/{d.day}/{yy}",
        f"{d.month}/{d.day}/{yyyy}",
        f"{d.strftime('%m')}/{d.strftime('%d')}/{yy}",
        f"{d.strftime('%m')}/{d.strftime('%d')}/{yyyy}",
    ]


def find_playlist(headliner, date_str, playlists):
    date_vars = date_variants(date_str)
    if not date_vars:
        return None
    for pl in playlists:
        title = pl["title"]
        title_norm = normalize(title)
        if "live" not in title_norm:
            continue
        if not artist_in_title(headliner, title):
            continue
        if any(dv in title for dv in date_vars):
            return pl
    return None


def find_videos(date_str, videos):
    date_vars = date_variants(date_str)
    if not date_vars:
        return []
    matches = []
    for v in videos:
        desc = v.get("description", "") or ""
        if any(dv in desc for dv in date_vars):
            matches.append(v)
    return matches


# ── Show normalisation ────────────────────────────────────────────────────────

def normalize_shows(shows, artist_col, venue_col, date_col):
    out = []
    for s in shows:
        out.append({
            "Show Date":        s.get(date_col, ""),
            "Artist":           normalize_artist_name(s.get(artist_col, "")),
            "Supporting Acts":  s.get("Supporting Acts", s.get("Supporting Artist", "")),
            "Venue":            s.get(venue_col, ""),
            "Setlist.fm URL":   s.get("Setlist.fm URL", ""),
            "Playlist URL":     s.get("Playlist URL", ""),
            "Notes / Memories": s.get("Notes / Memories", s.get("Notes", "")),
            "_source_file":     s.get("_source_file", ""),
        })
    return out


# ── Core correlate ────────────────────────────────────────────────────────────

def correlate(shows, videos, playlists):
    results = []
    playlist_hits = 0
    video_hits = 0
    for show in shows:
        headliner = show["Artist"]
        date_str  = show["Show Date"]
        venue     = show["Venue"]
        setlist   = show.get("Setlist.fm URL", "")

        playlist = find_playlist(headliner, date_str, playlists)
        vids = []
        if not playlist:
            vids = find_videos(date_str, videos)

        if playlist:
            playlist_hits += 1
            yt_url     = playlist["url"]
            match_type = f"Playlist ({playlist['item_count']} videos)"
            yt_title   = playlist["title"]
        elif vids:
            video_hits += 1
            yt_url     = ""
            match_type = f"{len(vids)} video(s) found"
            yt_title   = " | ".join(v["title"] for v in vids[:3])
            if len(vids) > 3:
                yt_title += f" ... (+{len(vids)-3} more)"
        else:
            yt_url     = ""
            match_type = "No match"
            yt_title   = ""

        results.append({
            "Show Date":        date_str,
            "Artist":           headliner,
            "Supporting Acts":  show.get("Supporting Acts", ""),
            "Venue":            venue,
            "Setlist.fm URL":   setlist,
            "Playlist URL":     yt_url,
            "Match Type":       match_type,
            "YT Title":         yt_title,
            "Notes / Memories": show.get("Notes / Memories", ""),
            "_source_file":     show.get("_source_file", ""),
        })
    return results, playlist_hits, video_hits


# ── Output helpers ────────────────────────────────────────────────────────────

def write_results(results, filename):
    fieldnames = [
        "Show Date", "Artist", "Supporting Acts", "Venue",
        "Setlist.fm URL", "Playlist URL", "Match Type", "YT Title", "Notes / Memories"
    ]
    write_tsv(results, fieldnames, filename)
    print(f"  Output: {filename}")


def print_summary(label, results, playlist_hits, video_hits):
    total = len(results)
    print(f"\n{label} ({total} shows):")
    print(f"  Playlist matches:   {playlist_hits}")
    print(f"  Video-only matches: {video_hits}")
    print(f"  No match:           {total - playlist_hits - video_hits}")
    for r in results:
        if r["Match Type"] != "No match":
            print(f"  {r['Show Date']} | {r['Artist']}")
            print(f"    → {r['Match Type']}: {r['YT Title'][:80]}")


# ── Merge back into source files ──────────────────────────────────────────────

def merge_into_history(corr_results, source_file):
    """
    Patch playlist URLs found by the correlator back into a source show file.

    Rules:
      - Only writes a URL when the correlation result has a playlist URL.
      - Never overwrites a cell that already has a URL.
      - Matches rows by (Show Date, Artist) — case-sensitive.
      - Writes the file back in-place, preserving all columns.

    For history/*.tsv files this is LEGACY/BACKFILL-ONLY behaviour. Once you
    are current on playlist creation via live_shows_current.tsv, history year
    files will rarely need updating here.

    Returns the number of rows updated.
    """
    if not os.path.exists(source_file):
        return 0

    corr_map = {}
    for r in corr_results:
        url = _cell(r, "Playlist URL")
        if url and _cell(r, "_source_file") == source_file:
            corr_map[(_cell(r, "Show Date"), _cell(r, "Artist"))] = url

    if not corr_map:
        return 0

    with open(source_file, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    if "Playlist URL" not in fieldnames:
        print(f"  WARNING: 'Playlist URL' column not found in {source_file} — skipping merge")
        return 0

    updated = 0
    for row in rows:
        date         = _cell(row, "Show Date")
        artist       = normalize_artist_name(_cell(row, "Artist"))
        existing_url = _cell(row, "Playlist URL")
        new_url      = corr_map.get((date, artist), "")

        if new_url and not existing_url:
            row["Playlist URL"] = new_url
            updated += 1
            print(f"    + {date} | {artist}")
            print(f"        {new_url}")

    if updated:
        write_tsv(rows, fieldnames, source_file)
        print(f"  Wrote {updated} URL(s) → {source_file}")
    else:
        print(f"  No new URLs to write → {source_file}")

    return updated


# ── artists.tsv sync ──────────────────────────────────────────────────────────

ARTISTS_TSV = "artists.tsv"
ARTISTS_FIELDNAMES = [
    "Artist", "Times Seen", "First Seen", "Most Recent Seen",
    "YouTube Channel", "Spotify URL", "Photo", "Book Autograph",
    "Hat Autograph", "VIP Ticket",
]


def sync_artists(all_attended_shows, dry_run=False):
    if not os.path.exists(ARTISTS_TSV):
        print(f"  WARNING: {ARTISTS_TSV} not found — skipping artist sync")
        return 0

    with open(ARTISTS_TSV, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        fieldnames = list(reader.fieldnames or ARTISTS_FIELDNAMES)
        artists = list(reader)

    artist_index = {normalize_artist_name(r["Artist"]): r for r in artists}

    from collections import defaultdict
    show_dates_by_artist = defaultdict(set)
    for show in all_attended_shows:
        artist = normalize_artist_name(show["Artist"])
        date   = show["Show Date"]
        if artist and date:
            show_dates_by_artist[artist].add(date)

    new_rows = []
    updated_rows = []

    for artist, dates in sorted(show_dates_by_artist.items()):
        dates = sorted(dates)
        first_seen  = dates[0]
        most_recent = dates[-1]
        times_seen  = len(dates)

        if artist not in artist_index:
            new_row = {fn: "" for fn in fieldnames}
            new_row["Artist"]          = artist
            new_row["Times Seen"]      = str(times_seen)
            new_row["First Seen"]      = first_seen
            new_row["Most Recent Seen"] = most_recent
            new_rows.append(new_row)
            print(f"  ADD  {artist}  (Times Seen={times_seen}, First={first_seen}, Recent={most_recent})")
        else:
            row = artist_index[artist]
            current_seen      = int(row.get("Times Seen", "0") or "0")
            current_first     = row.get("First Seen", "").strip()
            current_recent    = row.get("Most Recent Seen", "").strip()

            new_first  = min(filter(None, [first_seen, current_first])) if current_first else first_seen
            new_recent = max(filter(None, [most_recent, current_recent])) if current_recent else most_recent
            new_seen   = times_seen

            changes = []
            if new_seen != current_seen:
                changes.append(f"Times Seen {current_seen}→{new_seen}")
            if new_first != current_first:
                changes.append(f"First Seen {current_first!r}→{new_first!r}")
            if new_recent != current_recent:
                changes.append(f"Most Recent Seen {current_recent!r}→{new_recent!r}")

            if changes:
                row["Times Seen"]       = str(new_seen)
                row["First Seen"]       = new_first
                row["Most Recent Seen"] = new_recent
                updated_rows.append(artist)
                print(f"  UPD  {artist}  ({', '.join(changes)})")

    total_changes = len(new_rows) + len(updated_rows)
    if total_changes == 0:
        print("  artists.tsv is already up to date — no changes needed.")
        return 0

    print(f"\n  {len(new_rows)} new artist(s), {len(updated_rows)} updated.")

    if dry_run:
        print("  [dry-run] No changes written.")
        return total_changes

    artists.extend(new_rows)
    artists.sort(key=lambda r: r.get("Artist", "").lower())
    write_tsv(artists, fieldnames, ARTISTS_TSV)
    print(f"  Written → {ARTISTS_TSV}")
    return total_changes


# ── Main ──────────────────────────────────────────────────────────────────────

SHOWS_CURRENT_TSV = "live_shows_current.tsv"


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--merge",
        action="store_true",
        help=(
            "After writing correlation TSVs, patch newly found playlist URLs back into "
            "history/*.tsv (legacy/backfill) and live_shows_current.tsv. "
            "Only fills blank Playlist URL cells — never overwrites an existing URL."
        ),
    )
    parser.add_argument(
        "--sync-artists",
        action="store_true",
        help=(
            "Update artists.tsv from attended shows: add new artist rows and update "
            "Times Seen / First Seen / Most Recent Seen for existing ones."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview all changes without writing anything.",
    )
    args = parser.parse_args()

    videos    = load_tsv("youtube_videos.tsv")
    playlists = load_tsv("youtube_playlists.tsv")
    print(f"Loaded {len(videos)} videos, {len(playlists)} playlists")

    all_results_history  = []
    all_results_current  = []
    all_attended_shows   = []

    # ── History files (per-year glob) ─────────────────────────────────────────
    history_raw = load_history_glob("history/*.tsv")
    if history_raw:
        history = normalize_shows(history_raw, "Artist", "Venue", "Show Date")
        print(f"Loaded {len(history)} history shows from history/*.tsv")
        results_h, ph, vh = correlate(history, videos, playlists)
        write_results(results_h, "history_youtube_correlation.tsv")
        print_summary("History (all years)", results_h, ph, vh)
        all_results_history = results_h
        all_attended_shows.extend(history)
    else:
        print("No files found in history/ — skipping")

    # ── Current year file ─────────────────────────────────────────────────────
    if os.path.exists(SHOWS_CURRENT_TSV):
        shows_current_raw = load_tsv(SHOWS_CURRENT_TSV)
        attended = [s for s in shows_current_raw if s.get("Status", "") == "attended"]
        for s in attended:
            s["_source_file"] = SHOWS_CURRENT_TSV
        shows_current = normalize_shows(attended, "Artist", "Venue Name", "Show Date")
        print(f"\nLoaded {len(shows_current)} attended shows from {SHOWS_CURRENT_TSV}")
        results_cur, ph, vh = correlate(shows_current, videos, playlists)
        write_results(results_cur, "shows_current_youtube_correlation.tsv")
        print_summary("Current year attended shows", results_cur, ph, vh)
        all_results_current = results_cur
        all_attended_shows.extend(shows_current)
    else:
        print(f"{SHOWS_CURRENT_TSV} not found — skipping")

    # ── Optional merge ────────────────────────────────────────────────────────
    if args.merge:
        print("\n── Merging playlist URLs into source files ──────────────────────────────────")

        if all_results_history:
            # Group by source file and patch each year file separately
            source_files = sorted({r["_source_file"] for r in all_results_history if r["_source_file"]})
            for sf in source_files:
                print(f"\n{sf}: (legacy/backfill — history files rarely need updating once current)")
                if not args.dry_run:
                    merge_into_history(all_results_history, sf)
                else:
                    print("  [dry-run] skipping write")

        if all_results_current:
            print(f"\n{SHOWS_CURRENT_TSV}:")
            if not args.dry_run:
                merge_into_history(all_results_current, SHOWS_CURRENT_TSV)
            else:
                print("  [dry-run] skipping write")

        if not args.dry_run:
            print(f"\nMerge complete. Review changes with: git diff history/ {SHOWS_CURRENT_TSV}")

    # ── Optional artists sync ─────────────────────────────────────────────────
    if args.sync_artists:
        print("\n── Syncing artists.tsv ──────────────────────────────────────────────────────")
        sync_artists(all_attended_shows, dry_run=args.dry_run)
        if not args.dry_run:
            print("Review changes with: git diff artists.tsv")


if __name__ == "__main__":
    main()
