#!/usr/bin/env python3
"""
audit_times_seen.py

Audits data/artists.tsv "Times Seen" against the canonical ledger count computed by
build_artist_index.py (history/*.tsv + live_shows_current.tsv attended rows + seen_with.tsv,
deduped by date, with combined-bill components attributed via the Via column). The builder
is the single source of truth for the count; this script just diffs artists.tsv against it.

CI half of issue #119; the at-write-time half is the blocking Step 5b in
tools/playbooks/EMAIL_WORKFLOWS.md (Routine 2), which reconciles Times Seen the moment a
show is recorded so this check stays green.

Times Seen must equal the ledger count for every artist, EXCEPT the notes-only allowlist
below: artists whose Times Seen legitimately exceeds the structured ledger because a show
exists only in a prose Notes field the builder can't parse. For an allowlisted artist,
Times Seen in [ledger, ledger + extra] is OK (so it also survives the day that prose-only
show becomes a structured row); an undercount, or an overcount beyond the allowed extra, is
still flagged.

Exits non-zero on any mismatch so the GitHub Actions workflow fails visibly.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_artist_index as bai  # noqa: E402  (sibling script in scripts/)

ARTISTS_PATH = Path("data/artists.tsv")

# Display name -> extra Times Seen allowed above the structured ledger count, because of a
# notes-only sighting the builder can't count. Keys are normalized the same way the builder
# keys artists, so spelling/case/punctuation here don't have to be exact. See #119.
NOTES_ONLY_OK_RAW = {
    "New York's Finest": 1,  # 2026-04-18 State Theatre — prose-only Notes mention, not a structured row
}


def main() -> int:
    root = "."
    if not ARTISTS_PATH.exists():
        print(f"ERROR: {ARTISTS_PATH} not found", file=sys.stderr)
        return 1

    # Canonical ledger seen counts, straight from the modal-index builder.
    index = bai.build(root)["artists"]
    aliases = bai.load_aliases(root)

    def canon(name):
        n = bai.norm(name)
        return aliases.get(n, n)

    notes_ok = {canon(name): extra for name, extra in NOTES_ONLY_OK_RAW.items()}

    rows = ARTISTS_PATH.read_text(encoding="utf-8").strip().splitlines()
    header = rows[0].split("\t")
    try:
        ci_artist = header.index("Artist")
        ci_seen = header.index("Times Seen")
    except ValueError as exc:
        print(f"ERROR: artists.tsv missing an expected column: {exc}", file=sys.stderr)
        return 1

    errors = []
    checked = 0
    for i, line in enumerate(rows[1:], start=2):
        cols = line.split("\t")
        artist = cols[ci_artist].strip() if len(cols) > ci_artist else ""
        raw_seen = cols[ci_seen].strip() if len(cols) > ci_seen else ""
        if not artist or not raw_seen.isdigit():
            continue

        key = canon(artist)
        entry = index.get(key)
        if entry is None:
            errors.append(f"Row {i} ({artist}): not present in the ledger index (key {key!r})")
            continue

        checked += 1
        tsv_seen = int(raw_seen)
        ledger = entry["seen"]["count"]
        extra = notes_ok.get(key, 0)

        if ledger <= tsv_seen <= ledger + extra:
            continue

        if tsv_seen < ledger:
            errors.append(f"Row {i} ({artist}): Times Seen {tsv_seen} < ledger {ledger} (undercount)")
        elif extra:
            errors.append(
                f"Row {i} ({artist}): Times Seen {tsv_seen} > ledger {ledger} + allowlisted {extra} "
                f"(expected at most {ledger + extra})"
            )
        else:
            errors.append(f"Row {i} ({artist}): Times Seen {tsv_seen} > ledger {ledger} (overcount)")

    if errors:
        print(f"{len(errors)} Times Seen mismatch(es) vs ledger in {ARTISTS_PATH}:\n")
        for e in errors:
            print(f"  {e}")
        print(
            "\nReconcile artists.tsv Times Seen against `python scripts/build_artist_index.py`,\n"
            "or, if the extra show is prose-only, add the artist to NOTES_ONLY_OK_RAW."
        )
        return 1

    tail = f" ({len(notes_ok)} notes-only allowlisted)" if notes_ok else ""
    print(f"OK — {checked} artists checked, Times Seen matches the ledger{tail}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
