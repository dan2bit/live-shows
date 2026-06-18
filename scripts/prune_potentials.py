#!/usr/bin/env python3
"""
prune_potentials.py

Removes past-dated rows from live_shows_potential.tsv and appends pruned
artists to follows/new_artist_research.tsv as pending-review rows.

Run by GitHub Actions on push to main, or manually.
Only prunes Pass rows by default; Buy/Choose/Sell are left for human review
(they should not be past-dated in normal operation, so their presence
is itself a signal worth flagging rather than silently deleting).
"""

import re
import sys
import csv
import io
from datetime import date, timezone
from pathlib import Path

TODAY = date.today()
POTENTIALS_PATH = Path("live_shows_potential.tsv")
NAR_PATH = Path("follows/new_artist_research.tsv")

PASS_ONLY = True  # Only auto-prune Pass rows; flag others as warnings


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


def nar_row_for(pruned: dict, nar_headers: list[str]) -> dict:
    """Build a minimal pending-review NAR row from a pruned potentials row."""
    artist = pruned.get("Artist", "")
    tier = pruned.get("Tier", "")
    notes = pruned.get("Notes", "")
    pass_reason = f"Passed {TODAY.strftime('%b %Y')} — {notes[:120]}" if notes and notes != "-" else f"Passed {TODAY.strftime('%b %Y')}"
    row = {h: "" for h in nar_headers}
    row["Artist"] = artist
    row["Signal"] = f"pruned-potentials {TODAY.isoformat()}"
    row["Category"] = tier
    row["Overview & Niche"] = pass_reason
    row["Status"] = "pending-review"
    row["Source"] = "pruned-potentials"
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
    warnings = []

    for row in pot_rows:
        date_str = row.get("Date", "")
        decision = row.get("Decision", "").lower()
        show_date = extract_last_date(date_str)

        if show_date is None:
            kept.append(row)
            continue

        if show_date < TODAY:
            if PASS_ONLY and decision != "pass":
                warnings.append(
                    f"WARNING: Past-dated non-Pass row not auto-pruned: "
                    f"{row.get('Artist')} ({date_str}, {decision.title()})"
                )
                kept.append(row)
            else:
                pruned_rows.append(row)
        else:
            kept.append(row)

    if not pruned_rows and not warnings:
        print("No past-dated rows found. Nothing to do.")
        return 0

    # Write pruned potentials back
    write_tsv(POTENTIALS_PATH, pot_headers, kept)
    print(f"Pruned {len(pruned_rows)} row(s) from {POTENTIALS_PATH}:")
    for r in pruned_rows:
        print(f"  - {r.get('Artist')} ({r.get('Date')}, {r.get('Decision')})")

    # Append to NAR (skip if already present)
    if nar_headers:
        added = 0
        for r in pruned_rows:
            artist = r.get("Artist", "").lower()
            if artist and artist not in existing_nar_artists:
                nar_rows.append(nar_row_for(r, nar_headers))
                existing_nar_artists.add(artist)
                added += 1
                print(f"  + Added to NAR as pending-review: {r.get('Artist')}")
        if added:
            write_tsv(NAR_PATH, nar_headers, nar_rows)

    for w in warnings:
        print(w)

    return 1 if warnings else 0


if __name__ == "__main__":
    sys.exit(main())
