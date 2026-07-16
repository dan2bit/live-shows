#!/usr/bin/env python3
"""
reconcile_purchases.py  (#152)

Derived-state reconciler for ticket purchases. A purchase is signaled by an
`upcoming` row in data/live_shows_current.tsv — written by the in-page purchase
modal (client does only appends + private keyed deletes) or by Routine 1 email
processing. This script fans that signal out to the derived state the purchase
invalidates, so neither the browser nor the email workflow ever performs the
remove/re-sort/recompute transaction by hand:

  1. Remove any live_shows_potential.tsv row matching an upcoming current row
     on Artist (exact string) + show day (ISO date; a potentials range matches
     on its first day).
  2. Re-sort potentials: Buy -> Choose -> Sell -> Pass, date ascending within
     each group.
  3. Recompute Prev/Next brackets for every future-dated Buy/Choose row from
     the purchased-upcoming set. This is the CANONICAL bracket implementation;
     check_brackets.py validates the same math — keep the two in step.
     Pass/Sell rows are never touched (they are exempt from bracket checks).
  4. Remove any fast_track.tsv row whose Artist exactly matches an upcoming
     current row's Artist — the first-show wait is over. (The private
     fast_track_caps.tsv twin is deleted client-side / in Routine 1; this
     script never touches the private repo.)

Exact keys only, per the #152 design revision: normalization is a client and
display concern; the reconciler never guesses identity. A non-matching row is
a no-op, never an error — this runs on EVERY current.tsv change (purchases,
Routine 1 commits, notes edits) and must be silent when there is nothing to do.

Idempotent: a second run over the same inputs writes nothing.
Run in CI by .github/workflows/potentials-maintenance.yml (before the prune),
which owns the staging commit and the #142 retry loop.

Exit codes: 0 unless required files are missing (1). The workflow detects
changes via git diff, not via exit code.
"""

import re
import sys
from datetime import date
from pathlib import Path

CURRENT_PATH = Path("data/live_shows_current.tsv")
POTENTIALS_PATH = Path("data/live_shows_potential.tsv")
FAST_TRACK_PATH = Path("data/fast_track.tsv")

DEC_RANK = {"buy": 0, "choose": 1, "sell": 2, "pass": 3}


def extract_first_date(date_str: str) -> date | None:
    m = re.match(r"(\d{4}-\d{2}-\d{2})", (date_str or "").strip())
    if not m:
        return None
    try:
        return date.fromisoformat(m.group(1))
    except ValueError:
        return None


def extract_last_date(date_str: str) -> date | None:
    parts = (date_str or "").split(" - ")
    return extract_first_date(parts[-1].strip())


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


def serialize(headers: list[str], rows: list[dict]) -> str:
    return "\n".join(["\t".join(headers)] + ["\t".join(r.get(h, "") for h in headers) for r in rows])


def dec_rank(row: dict) -> int:
    return DEC_RANK.get((row.get("Decision") or "").strip().lower(), 4)


def main() -> int:
    if not CURRENT_PATH.exists() or not POTENTIALS_PATH.exists():
        print("ERROR: required TSV files not found", file=sys.stderr)
        return 1

    today = date.today()
    _, cur_rows = read_tsv(CURRENT_PATH)

    # Purchase signal: every upcoming current row. Keys are exact Artist string
    # + ISO show day. Also collect the bracket universe (future upcoming shows)
    # exactly as check_brackets.py does, so the two implementations agree.
    purchased_keys = set()      # (artist, date) for potentials removal
    purchased_artists = set()   # artist for fast_track removal
    upcoming = []               # (date, label) for bracket computation
    for r in cur_rows:
        if (r.get("Status") or "").strip().lower() != "upcoming":
            continue
        d = extract_first_date(r.get("Show Date", ""))
        artist = (r.get("Artist") or "").strip()
        if not artist or not d:
            continue
        purchased_keys.add((artist, d))
        purchased_artists.add(artist)
        if d >= today:
            venue = (r.get("Venue Name") or "").split(",")[0].strip()
            upcoming.append((d, f"{r.get('Show Date','')[:10]} {artist} ({venue})"))
    upcoming.sort()

    def expected_brackets(show_date: date) -> tuple[str, str]:
        prev_label = next_label = "-"
        for d, label in upcoming:
            if d < show_date:
                prev_label = label
            elif d > show_date and next_label == "-":
                next_label = label
        return prev_label, next_label

    changed = []

    # --- potentials: remove purchased rows, re-sort, recompute Buy/Choose brackets
    pot_headers, pot_rows = read_tsv(POTENTIALS_PATH)
    before = serialize(pot_headers, pot_rows)

    kept = []
    for row in pot_rows:
        key = ((row.get("Artist") or "").strip(), extract_first_date(row.get("Date", "")))
        if key[1] is not None and key in purchased_keys:
            print(f"purchased -> removing potentials row: {key[0]} ({row.get('Date','')})")
            continue
        kept.append(row)

    kept.sort(key=lambda r: (dec_rank(r), (r.get("Date") or "")))

    for row in kept:
        if (row.get("Decision") or "").strip().lower() not in ("buy", "choose"):
            continue
        show_date = extract_last_date(row.get("Date", ""))
        if not show_date or show_date < today:
            continue
        prev_label, next_label = expected_brackets(show_date)
        if (row.get("Prev Show (2026)") or "").strip() != prev_label:
            row["Prev Show (2026)"] = prev_label
        if (row.get("Next Show (2026)") or "").strip() != next_label:
            row["Next Show (2026)"] = next_label

    if serialize(pot_headers, kept) != before:
        write_tsv(POTENTIALS_PATH, pot_headers, kept)
        changed.append(str(POTENTIALS_PATH))

    # --- fast_track: drop rows for artists with a purchased upcoming show
    if FAST_TRACK_PATH.exists():
        ft_headers, ft_rows = read_tsv(FAST_TRACK_PATH)
        ft_kept = []
        for row in ft_rows:
            artist = (row.get("Artist") or "").strip()
            if artist in purchased_artists:
                print(f"purchased -> removing fast_track row: {artist}")
                continue
            ft_kept.append(row)
        if len(ft_kept) != len(ft_rows):
            write_tsv(FAST_TRACK_PATH, ft_headers, ft_kept)
            changed.append(str(FAST_TRACK_PATH))

    if changed:
        print(f"reconciled: {', '.join(changed)}")
    else:
        print("nothing to reconcile.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
