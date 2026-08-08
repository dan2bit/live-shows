#!/usr/bin/env python3
"""
venues_reconcile.py — bring data/venues.tsv in line with the show history

Three independent fixes, each individually gated. Run from the repo root.
Nothing is written without an explicit flag, and every flag prints what it
would do first.

    python3 venues_reconcile.py                    # report everything, change nothing
    python3 venues_reconcile.py --add-state        # State column + pad rows to full width
    python3 venues_reconcile.py --add-aliases      # word-order aliases -> venue_aliases.tsv
    python3 venues_reconcile.py --add-missing      # skeleton rows for venues in history but not venues.tsv
    python3 venues_reconcile.py --all              # all three

    git diff data/                                 # review before committing

WHAT EACH FIX DOES

  --add-state    Derives the two-letter state from the free-text Address and
                 appends it as a new last column, then pads every row to the
                 full column count. Trailing empty columns are currently
                 truncated rather than written, so a short row yields None from
                 DictReader instead of "" and every consumer has had to write
                 (row.get(x) or "") to survive it. Padding retires that.

  --add-aliases  Only adds aliases the folding CANNOT already resolve. A
                 history spelling that differs solely by leading "The",
                 punctuation, or case already matches, because every consumer
                 folds those away — adding a row for it would imply the folding
                 is untrustworthy. What folding cannot do is reorder words, so
                 the rule here is: identical token sets, different string. That
                 catches "Concerts at The Sevareid House" vs "Sevareid House
                 Concerts" and nothing spurious.

  --add-missing  Appends a skeleton row for each venue that appears in the show
                 history but has no venues.tsv entry. Only Venue Name and State
                 are filled, both taken verbatim from the history's own
                 "Venue, City, ST, USA" string, plus a NEEDS DETAILS marker in
                 General Notes. That is deliberately partial: name and state are
                 all the venue lookup needs to resolve correctly, while parking,
                 drive time and the rest are planning fields only a human can
                 fill. The marker makes the unfinished rows greppable.

WHY NOT csv:
  Fields in venues.tsv contain unescaped double quotes (bag policies like
  12"x6"x12"), which the csv module's default quoting mishandles. TSV fields
  cannot contain a tab or a newline, so split/join on tab is both simpler and
  exactly lossless.
"""

import glob
import os
import re
import sys

VENUES_TSV  = os.path.join("data", "venues.tsv")
ALIASES_TSV = os.path.join("data", "venue_aliases.tsv")
CURRENT_TSV = os.path.join("data", "live_shows_current.tsv")
HISTORY_GLOB = os.path.join("data", "history", "*.tsv")

STATE_COL   = "State"
NEEDS_MARK  = "NEEDS DETAILS — added by venues_reconcile"

# Address ends "..., CITY, ST ZIP". The ZIP anchor stops a stray two-letter
# token (a quadrant like NE, a road abbreviation) from matching.
STATE_RE    = re.compile(r",\s*([A-Z]{2})\s+\d{5}")
STATE_LOOSE = re.compile(r",\s*([A-Z]{2})\s*$")

# History venues are setlist.fm style: "Venue Name, City, ST, USA".
TRAILING_GEO = re.compile(r",\s*([^,]+),\s*([A-Z]{2}),\s*[A-Z]{2,3}\s*$")


# ── shared folding ─────────────────────────────────────────────────────────

def venue_key(value: str) -> str:
    """Fold a venue name the way every consumer already does."""
    key = re.sub(r"^the\s+", "", value.strip().lower())
    key = re.sub(r"[^a-z0-9 ]+", " ", key)
    return re.sub(r"\s+", " ", key).strip()


# Dropped before comparing word sets. "Concerts at The Sevareid House" and
# "Sevareid House Concerts" are the same place, and only these words differ.
STOPWORDS = {"the", "at", "of", "and", "a", "in", "on", "for"}


def token_set(value: str) -> frozenset:
    """The folded content words of a venue name, order and stopwords discarded."""
    return frozenset(w for w in venue_key(value).split() if w not in STOPWORDS)


def read_lines(path: str) -> tuple[list[str], bool]:
    """File as a list of lines plus whether it ended with a newline."""
    if not os.path.exists(path):
        return [], True
    raw = open(path, encoding="utf-8").read()
    ends = raw.endswith("\n")
    lines = raw.split("\n")
    if ends:
        lines = lines[:-1]
    return lines, ends


def write_lines(path: str, lines: list[str], ends: bool) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + ("\n" if ends else ""))


def column(lines: list[str], name: str):
    """Yield the value of one named column for every data row."""
    if not lines:
        return
    header = lines[0].split("\t")
    if name not in header:
        return
    at = header.index(name)
    for line in lines[1:]:
        fields = line.split("\t")
        if at < len(fields):
            yield fields[at]


# ── history ────────────────────────────────────────────────────────────────

def split_geo(raw: str) -> tuple[str, str, str]:
    """'Koka Booth Amphitheatre, Cary, NC, USA' -> (name, city, state).

    Falls back to (raw, "", "") for the plain names the current-shows file
    uses, which carry no city or state.
    """
    match = TRAILING_GEO.search(raw)
    if not match:
        return raw.strip(), "", ""
    return raw[:match.start()].strip(), match.group(1).strip(), match.group(2)


def collect_history() -> dict[str, dict]:
    """Every distinct venue string in the show files, with where it came from."""
    seen: dict[str, dict] = {}

    sources = [(CURRENT_TSV, "Venue Name")]
    sources += [(p, "Venue") for p in sorted(glob.glob(HISTORY_GLOB))]

    for path, col in sources:
        lines, _ = read_lines(path)
        for raw in column(lines, col):
            raw = raw.strip()
            if not raw:
                continue
            entry = seen.setdefault(raw, {"count": 0, "files": set()})
            entry["count"] += 1
            entry["files"].add(os.path.basename(path))

    return seen


# ── fixes ──────────────────────────────────────────────────────────────────

def fix_state(lines: list[str]) -> tuple[list[str], list[tuple], dict]:
    """Append the State column and pad every row. Returns (lines, rows, widths)."""
    header = lines[0].split("\t")
    name_at, address_at = header.index("Venue Name"), header.index("Address")
    width = len(header)

    out = ["\t".join(header + [STATE_COL])]
    rows, widths = [], {}

    for line in lines[1:]:
        fields = line.split("\t")
        widths[len(fields)] = widths.get(len(fields), 0) + 1
        if len(fields) > width:
            sys.exit(f"Row has {len(fields)} fields, more than the {width}-column "
                     f"header — refusing to guess:\n  {line[:120]}")
        fields += [""] * (width - len(fields))

        match = (STATE_RE.search(fields[address_at])
                 or STATE_LOOSE.search(fields[address_at].strip()))
        state = match.group(1) if match else ""
        rows.append((fields[name_at], state))
        out.append("\t".join(fields + [state]))

    return out, rows, widths


def find_alias_gaps(history: dict, known: dict, aliases: dict) -> list[tuple]:
    """History spellings that folding cannot resolve but a word reorder can."""
    # known maps folded key -> original spelling; the alias must point at the
    # original, so iterate the values.
    by_tokens = {}
    for name in known.values():
        by_tokens.setdefault(token_set(name), name)

    gaps = []
    for raw in sorted(history):
        name, _, _ = split_geo(raw)
        key = venue_key(name)
        if key in known or key in aliases:
            continue                                   # folding already handles it
        canonical = by_tokens.get(token_set(name))
        if canonical:
            gaps.append((name, canonical, history[raw]["count"]))
    return gaps


def find_missing(history: dict, known: dict, aliases: dict,
                 alias_gaps: list) -> list[tuple]:
    """Venues in the history with no venues.tsv row and no alias candidate."""
    excused = {name for name, _, _ in alias_gaps}
    missing = {}

    for raw in sorted(history):
        name, city, state = split_geo(raw)
        key = venue_key(name)
        if key in known or key in aliases or name in excused:
            continue
        entry = missing.setdefault(key, [name, city, state, 0, set()])
        entry[3] += history[raw]["count"]
        entry[4] |= history[raw]["files"]

    return [tuple(v) for v in missing.values()]


# ── main ───────────────────────────────────────────────────────────────────

def main() -> None:
    flags = set(sys.argv[1:])
    if "--all" in flags:
        flags |= {"--add-state", "--add-aliases", "--add-missing"}

    if not os.path.exists(VENUES_TSV):
        sys.exit(f"Not found: {VENUES_TSV}\nRun this from the repo root.")

    venue_lines, venue_ends = read_lines(VENUES_TSV)
    alias_lines, alias_ends = read_lines(ALIASES_TSV)

    header = venue_lines[0].split("\t")
    known   = {venue_key(n): n for n in column(venue_lines, "Venue Name") if n.strip()}
    aliases = {venue_key(a): a for a in column(alias_lines, "Alias") if a.strip()}
    history = collect_history()

    print(f"{len(known)} venues, {len(aliases)} aliases, "
          f"{len(history)} distinct venue strings in the show files\n")

    # ── 1. state column ──
    print("=" * 64)
    print("STATE COLUMN")
    if STATE_COL in header:
        print(f"  Already present — skipping.")
    else:
        venue_lines, rows, widths = fix_state(venue_lines)
        counts: dict = {}
        for _, state in rows:
            counts[state or "(none)"] = counts.get(state or "(none)", 0) + 1
        print(f"  {len(rows)} venues: " + " · ".join(
            f"{k} {v}" for k, v in sorted(counts.items())))
        print("  widths before: " + ", ".join(
            f"{n}x{c}" for n, c in sorted(widths.items()))
            + f"  ->  all {len(header) + 1}")
        blank = [n for n, s in rows if not s]
        if blank:
            print(f"  WARNING no state parsed for {len(blank)}: {', '.join(blank)}")

        if "--add-state" in flags:
            write_lines(VENUES_TSV, venue_lines, venue_ends)
            print(f"  WROTE {VENUES_TSV}")
        else:
            print("  (--add-state to apply)")

    # ── 2. aliases ──
    print("\n" + "=" * 64)
    print("ALIAS GAPS  (same words, different order — folding cannot fix these)")
    alias_gaps = find_alias_gaps(history, known, aliases)
    if not alias_gaps:
        print("  None.")
    for name, canonical, count in alias_gaps:
        print(f"  {name!r}\n      -> {canonical!r}   ({count} show(s))")

    if alias_gaps and "--add-aliases" in flags:
        if not alias_lines:
            alias_lines = ["Alias\tVenue Name"]
        for name, canonical, _ in alias_gaps:
            alias_lines.append(f"{name}\t{canonical}")
        write_lines(ALIASES_TSV, alias_lines, alias_ends)
        print(f"  WROTE {ALIASES_TSV} (+{len(alias_gaps)})")
    elif alias_gaps:
        print("  (--add-aliases to apply)")

    # ── 3. missing venues ──
    print("\n" + "=" * 64)
    print("MISSING VENUES  (in the show history, absent from venues.tsv)")
    missing = find_missing(history, known, aliases, alias_gaps)
    if not missing:
        print("  None.")
    for name, city, state, count, files in sorted(missing, key=lambda m: -m[3]):
        where = f"{city}, {state}" if city else "location not in the show data"
        print(f"  {name}  —  {where}  ({count} show(s): {', '.join(sorted(files))})")

    out_of_area = [m for m in missing if m[2] and m[2] not in {"DC", "MD", "VA"}]
    if out_of_area:
        print(f"\n  Outside DC/MD/VA: "
              + ", ".join(f"{m[0]} ({m[2]})" for m in out_of_area))

    if missing and "--add-missing" in flags:
        venue_lines, venue_ends = read_lines(VENUES_TSV)
        header = venue_lines[0].split("\t")
        at = {c: i for i, c in enumerate(header)}
        for name, _, state, _, _ in sorted(missing):
            fields = [""] * len(header)
            fields[at["Venue Name"]] = name
            fields[at["General Notes"]] = NEEDS_MARK
            if STATE_COL in at:
                fields[at[STATE_COL]] = state
            venue_lines.append("\t".join(fields))
        write_lines(VENUES_TSV, venue_lines, venue_ends)
        print(f"  WROTE {VENUES_TSV} (+{len(missing)} skeleton row(s))")
        print(f"  Find them later with: grep -n 'NEEDS DETAILS' {VENUES_TSV}")
    elif missing:
        print("  (--add-missing to apply — needs --add-state first, or in the "
              "same run, so the State column exists)")

    if not flags & {"--add-state", "--add-aliases", "--add-missing"}:
        print("\nReport only. Nothing was written.")


if __name__ == "__main__":
    main()
