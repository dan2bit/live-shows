#!/usr/bin/env python3
"""
prune_potentials.py

Removes past-dated rows from live_shows_potential.tsv and appends pruned
artists to follows/new_artist_research.tsv as pending-review rows.

Run by GitHub Actions on push to main, or manually.

All decisions are pruned when past-dated. Pass rows are the normal case.
Buy/Choose rows pruned without being downgraded first are flagged in the
NAR Source field as 'pruned-potentials-buy' or 'pruned-potentials-choose'
for future triage. Sell rows are also pruned but not added to NAR.
"""

import re
import sys
from datetime import date
from pathlib import Path

TODAY = date.today()
POTENTIALS_PATH = Path("data/live_shows_potential.tsv")
NAR_PATH = Path("tools/research/follows/new_artist_research.tsv")


def extract_last_date(date_str: str) -> date | None:
    """Handle single dates ('2026-06-14 Sun') and ranges ('2026-06-13 Sat - 2026-06-14 Sun')."""
    parts = date_str.split(" - ")
    last = parts[-1].strip()
    m = re.match(r"(\d{4}-\d{2}-\d{2})", last)
    if not m:
        return None
    try:
        return date.fromisoformat(m.group(1))
    except ValueError:
        return None


def read_tsv(path: Path) -> tuple[list[str], list[dict]]:
    text = path.read_text(encoding="utf-8")
    lines = text.strip().splitlines()
    headers = lines[0].split("\t")
    rows = []
    for line in lines[1:]:
        cols = line.split("\t")
        while len(cols) < len(headers):
            cols.append("")
        rows.append(dict(zip(headers, cols)))
    return headers, rows


def write_tsv(path: Path, headers: list[str], rows: list[dict]) -> None:
    lines = ["\t".join(headers)]
    for row in rows:
        lines.append("\t".join(row.get(h, "") for h in headers))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def nar_source_for(decision: str) -> str:
    d = decision.lower()
    if d == "buy":
        return "pruned-potentials-buy"
    if d == "choose":
        return "pruned-potentials-choose"
    return "pruned-potentials"


def nar_row_for(pruned: dict, nar_headers: list[str]) -> dict:
    """Build a minimal pending-review NAR row from a pruned potentials row."""
    artist = pruned.get("Artist", "")
    tier = pruned.get("Tier", "")
    decision = pruned.get("Decision", "")
    notes = pruned.get("Notes", "")
    note_str = f" — {notes[:120]}" if notes and notes != "-" else ""
    overview = f"Pruned {TODAY.strftime('%b %Y')} ({decision}){note_str}"
    row = {h: "" for h in nar_headers}
    row["Artist"] = artist
    row["Signal"] = f"pruned-potentials {TODAY.isoformat()}"
    row["Category"] = tier
    row["Overview & Niche"] = overview
    row["Status"] = "pending-review"
    row["Source"] = nar_source_for(decision)
    return row


def main() -> int:
    if not POTENTIALS_PATH.exists():
        print(f"ERROR: {POTENTIALS_PATH} not found", file=sys.stderr)
        return 1

    pot_headers, pot_rows = read_tsv(POTENTIALS_PATH)
    nar_headers, nar_rows = read_tsv(NAR_PATH) if NAR_PATH.exists() else ([], [])

    existing_nar_artists = {r.get("Artist", "").lower() for r in nar_rows}

    kept = []
    pruned_rows = []

    for row in pot_rows:
        show_date = extract_last_date(row.get("Date", ""))
        if show_date is None:
            kept.append(row)
            continue
        if show_date < TODAY:
            pruned_rows.append(row)
        else:
            kept.append(row)

    if not pruned_rows:
        print("No past-dated rows found. Nothing to do.")
        return 0

    write_tsv(POTENTIALS_PATH, pot_headers, kept)
    print(f"Pruned {len(pruned_rows)} row(s) from {POTENTIALS_PATH}:")
    for r in pruned_rows:
        d = r.get("Decision", "")
        print(f"  - {r.get('Artist')} ({r.get('Date')}, {d})")

    # Append to NAR — skip Sell rows and already-present artists
    if nar_headers:
        added = 0
        for r in pruned_rows:
            if r.get("Decision", "").lower() == "sell":
                continue
            artist = r.get("Artist", "").lower()
            if artist and artist not in existing_nar_artists:
                nar_rows.append(nar_row_for(r, nar_headers))
                existing_nar_artists.add(artist)
                added += 1
                print(f"  + Added to NAR as pending-review: {r.get('Artist')} [{nar_source_for(r.get('Decision',''))}]")
        if added:
            write_tsv(NAR_PATH, nar_headers, nar_rows)

    return 0


if __name__ == "__main__":
    sys.exit(main())
