#!/usr/bin/env python3
"""
rollover.py — Migrate attended shows from live_shows_current.tsv to history/<year>.tsv

Usage:
    python3 scripts/rollover.py --terminal [--private-repo PATH] [--dry-run] [--force]
    python3 scripts/rollover.py --show YYYY-MM-DD [--private-repo PATH] [--dry-run] [--force]
    python3 scripts/rollover.py --year 2026 [--private-repo PATH] [--dry-run] [--force]

Three selection modes (exactly one required):

  --terminal   The standing mode. Migrates every attended row that has reached
               terminal state — nothing that writes to the row is still pending:
                 - Status is 'attended'
                 - Setlist.fm URL is non-blank (not empty, not "-")
                 - Playlist URL is non-blank (not empty, not "-")
                 - no OPEN playlist/photo issue mentions the show date
               Notes / Memories never blocks: roughly a quarter of the rows
               already in history/ have blank notes, and a row still blank after
               the post-show status flip will stay blank. Photos block only via
               an open photo issue, never via the Artist Interaction flag — some
               photos are deliberately never linked to the show row, and those
               must not block or nag. Run monthly, or whenever curation settles.

  --show DATE  Single-show override: migrates the attended row for that date,
               bypassing the terminal checks (but never the 'attended' check).

  --year YYYY  The original whole-year batch (backfill / year-end catch-all).

For each selected row:
  1. Converts it to the abbreviated public history format
  2. Appends it to history/<year>.tsv (creates the file with a header if needed)
  3. Removes the row from live_shows_current.tsv

Privacy-split architecture:
  Sensitive per-show data (seat info, ticket quantity, cost breakdown, private notes)
  lives in a SEPARATE private repo: live-shows-private/current_private.tsv, keyed by
  Show Date + Artist. The public files carry only denormalized flags (Seat Type / VIP /
  Group). When --private-repo PATH is supplied, this script also:
  4. Archives each migrated show's private row into
     <PATH>/history_private/<year>.tsv (preserves seat info + private notes for posterity)
  5. Prunes that row from <PATH>/current_private.tsv so it doesn't accumulate orphans

  Per-show spend is NOT re-archived here — live-shows-private/spending.tsv is the authority for money and
  already holds it once a show moves to 'attended'. The full private row (cost columns
  included) is archived as-is purely because it's the cheapest lossless thing to keep.

  A REAL run requires --private-repo (or the explicit --public-only escape
  hatch, for forks that keep no private repo). A public-only migration removes
  the row from current while its private twin stays behind — and because
  selection is driven by current, no later run can ever find that show again
  to archive the twin: a permanent orphan requiring manual repair. --dry-run
  may omit --private-repo freely (preview only, nothing is written).

TSV handling:
  Reads and writes are plain tab-split / tab-join with LF line endings — never the
  csv module. csv.DictWriter's default quoting wraps any field containing a literal
  quote character, silently corrupting notes on rewrite (this bit two other scripts
  in this repo before it was noticed; details in docs/ISSUE_LOG.md). Short rows are
  padded on read, matching the parseTsv() convention in index.html.

Open-issue check (--terminal only):
  Asks the GitHub API for open issues labeled 'playlist' or 'photo' and blocks any
  show whose ISO date appears in an open issue title. Anonymous read of a public
  repo; the repo slug comes from the git remote (override with GITHUB_REPOSITORY).
  If the API is unreachable the run aborts rather than guessing — pass
  --skip-issue-check to proceed without it (e.g. offline).

Edge cases handled:
  - No rows selected → prints summary, exits cleanly
  - history/<year>.tsv already exists with some of the same rows → skips duplicates
    (dedup key: Show Date + Artist), and still prunes the stale row from current
  - Row status is not 'attended' → skipped with a warning
  - Partial runs → safe to re-run; duplicates are detected and skipped (public + private)
  - --dry-run → prints what would happen without writing any files
  - --force → suppresses the confirmation prompt
  - --private-repo given but current_private.tsv missing → aborts before any writes
    (prevents a public-only migration that silently skips the private side)
  - real run without --private-repo → aborts unless --public-only is passed

The issue history behind these designs is logged in docs/ISSUE_LOG.md.
"""

import argparse
import json
import os
import re
import ssl
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

# Columns in live_shows_current.tsv (public, post-privacy-split) — fallback only;
# the actual file header is preferred when rewriting current.
CURRENT_COLS = [
    "Show ID",
    "Artist",
    "Supporting Artist",
    "Show Date",
    "Doors Time",
    "Start Time",
    "Venue Name",
    "Venue Address",
    "Venue Event URL",
    "Seat Type",
    "VIP",
    "Group",
    "Ticket Access",
    "Setlist.fm URL",
    "Status",
    "Artist Interaction",
    "Playlist URL",
    "Notes / Memories",
    "Photo URL",
]

# Columns in history/<year>.tsv (public, in order). NOTE: Photo URL sits between
# Playlist URL and Match Type — must match the real files or appends corrupt them.
HISTORY_COLS = [
    "Show Date",
    "Artist",
    "Supporting Acts",
    "Venue",
    "Setlist.fm URL",
    "Playlist URL",
    "Photo URL",
    "Match Type",
    "YT Title",
    "Notes / Memories",
]

# Columns in current_private.tsv / history_private/<year>.tsv (private repo, in order).
PRIVATE_COLS = [
    "Show Date",
    "Artist",
    "Seat Info / GA",
    "Ticket Quantity",
    "Face Value (per ticket)",
    "Fees",
    "Total Cost",
    "Purchase Date",
    "Food & Bev",
    "Parking",
    "Merch",
    "Private Notes",
]

BLANK_VALUES = {"", "-"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def resolve_paths(private_repo: str = None) -> tuple:
    """Return (current_path, history_dir, private_current, private_dir).

    private_current / private_dir are None when --private-repo is not given.
    """
    script_dir = Path(__file__).parent.parent  # repo root (script is in scripts/)
    current_path = script_dir / "data" / "live_shows_current.tsv"
    history_dir = script_dir / "data" / "history"

    private_current = private_dir = None
    if private_repo:
        priv = Path(private_repo).expanduser()
        private_current = priv / "current_private.tsv"
        private_dir = priv / "history_private"

    return current_path, history_dir, private_current, private_dir


def read_tsv(path: Path) -> list:
    """Read a TSV file into a list of dicts. Returns [] if the file doesn't exist.

    Plain tab-split, no csv module (see module docstring). Short rows are padded
    with blanks so a stripped trailing tab never shifts a column.
    """
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        lines = [ln.rstrip("\n").rstrip("\r") for ln in f]
    lines = [ln for ln in lines if ln.strip()]
    if not lines:
        return []
    header = lines[0].split("\t")
    rows = []
    for ln in lines[1:]:
        vals = ln.split("\t")
        if len(vals) < len(header):
            vals += [""] * (len(header) - len(vals))
        rows.append(dict(zip(header, vals)))
    return rows


def read_header(path: Path, fallback: list) -> list:
    """The actual column order of an existing TSV, or the fallback schema."""
    if not path.exists():
        return list(fallback)
    with open(path, encoding="utf-8") as f:
        first = f.readline().rstrip("\n").rstrip("\r")
    return first.split("\t") if first.strip() else list(fallback)


def _format_row(row: dict, fieldnames: list) -> str:
    return "\t".join((row.get(col) or "") for col in fieldnames)


def write_tsv(path: Path, rows: list, fieldnames: list) -> None:
    """Write rows to a TSV file (plain tabs, LF), creating parent dirs as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write("\t".join(fieldnames) + "\n")
        for row in rows:
            f.write(_format_row(row, fieldnames) + "\n")


def append_tsv(path: Path, rows: list, fieldnames: list) -> None:
    """Append rows to an existing TSV file (no header written)."""
    with open(path, "a", encoding="utf-8", newline="") as f:
        for row in rows:
            f.write(_format_row(row, fieldnames) + "\n")


def dedup_key(row: dict) -> tuple:
    return (row.get("Show Date", "").strip(), row.get("Artist", "").strip())


def is_blank(value: str) -> bool:
    return (value or "").strip() in BLANK_VALUES


def current_to_history(row: dict) -> dict:
    """
    Convert a public live_shows_current.tsv row to the abbreviated history format.

    Money, seat, quantity and private-notes columns no longer exist in the public
    source (they live in the private sidecar / live-shows-private/spending.tsv), so there is nothing to
    drop here — only public fields are read.

    Venue is the bare Venue Name; the app keys display off the substring before the
    first comma, so the city/state suffix on older reverse-engineered rows is cosmetic.

    Match Type and YT Title are left blank — youtube_correlate.py fills them when the
    pipeline runs after video upload.
    """
    return {
        "Show Date":       row.get("Show Date", "").strip(),
        "Artist":          row.get("Artist", "").strip(),
        "Supporting Acts": row.get("Supporting Artist", "").strip(),
        "Venue":           row.get("Venue Name", "").strip(),
        "Setlist.fm URL":  row.get("Setlist.fm URL", "").strip(),
        "Playlist URL":    row.get("Playlist URL", "").strip(),
        "Photo URL":       row.get("Photo URL", "").strip(),
        "Match Type":      "",   # filled by youtube_correlate.py
        "YT Title":        "",   # filled by youtube_correlate.py
        "Notes / Memories": row.get("Notes / Memories", "").strip(),
    }


def validate_date(date_str: str):
    """Parse YYYY-MM-DD; return datetime or None if invalid."""
    try:
        return datetime.strptime(date_str.strip(), "%Y-%m-%d")
    except ValueError:
        return None


def terminal_gaps(row: dict) -> list:
    """The still-pending fields that keep a row out of terminal state."""
    gaps = []
    if is_blank(row.get("Setlist.fm URL")):
        gaps.append("Setlist.fm URL")
    if is_blank(row.get("Playlist URL")):
        gaps.append("Playlist URL")
    return gaps


# ---------------------------------------------------------------------------
# Open-issue check (terminal mode)
# ---------------------------------------------------------------------------

def detect_repo_slug() -> str:
    """owner/repo, from GITHUB_REPOSITORY or the git remote."""
    env = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if env:
        return env
    try:
        url = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            capture_output=True, text=True, timeout=10,
            cwd=Path(__file__).parent,
        ).stdout.strip()
    except Exception:
        url = ""
    match = re.search(r"github\.com[:/]([^/]+/[^/.]+)", url)
    if match:
        return match.group(1)
    return ""


def _tls_context() -> ssl.SSLContext:
    """A TLS context that also works on python.org macOS builds.

    Those Python builds do not read the system keychain, so the stdlib's
    default context fails certificate verification out of the box. certifi
    (bundled with requests, so usually already installed in this repo's venv)
    supplies a CA bundle; fall back to the default context elsewhere. If both
    fail, either `pip install certifi` or run macOS Python's
    "Install Certificates.command" once.
    """
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def open_issue_dates(repo_slug: str) -> dict:
    """{iso_date: [issue descriptions]} for open playlist/photo issues.

    An ISO date anywhere in an open issue's title marks that show as still
    receiving writes (the close workflows write back into current on close),
    so migration waits.
    """
    blocked: dict = {}
    for label in ("playlist", "photo"):
        url = (f"https://api.github.com/repos/{repo_slug}/issues"
               f"?state=open&labels={label}&per_page=100")
        request = urllib.request.Request(
            url, headers={"Accept": "application/vnd.github+json",
                          "User-Agent": "live-shows-rollover"})
        with urllib.request.urlopen(request, timeout=20,
                                    context=_tls_context()) as response:
            payload = json.load(response)
        for issue in payload:
            title = issue.get("title", "")
            for iso in re.findall(r"\d{4}-\d{2}-\d{2}", title):
                blocked.setdefault(iso, []).append(
                    "issue " + str(issue.get("number", "?"))
                    + " [" + label + "] " + title)
    return blocked


# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------

def run(mode: str, mode_arg, dry_run: bool, force: bool,
        private_repo: str = None, skip_issue_check: bool = False,
        public_only: bool = False) -> int:
    """Execute the rollover. Returns 0 on success, 1 on error.

    mode is 'year' (mode_arg: int year), 'terminal' (mode_arg unused), or
    'show' (mode_arg: ISO date string).
    """
    current_path, history_dir, private_current_path, private_dir = \
        resolve_paths(private_repo)

    if not current_path.exists():
        print(f"ERROR: {current_path} not found.", file=sys.stderr)
        return 1

    # Fail fast: if the private side was requested, its source must exist BEFORE we
    # write anything, so we never do a public-only migration that skips the sidecar.
    if private_repo and not private_current_path.exists():
        print(f"ERROR: --private-repo given but {private_current_path} not found.",
              file=sys.stderr)
        print("       Check the path; no files were modified.", file=sys.stderr)
        return 1

    # A real run must handle both repos, or say out loud that it never will:
    # the public row's removal is what makes the private twin unreachable, so
    # skipping the private side is not a smaller run — it is a desync.
    if not dry_run and not private_repo and not public_only:
        print("ERROR: a real run without --private-repo permanently orphans the "
              "migrated shows' private rows", file=sys.stderr)
        print("       (selection is driven by current, so no later run can find "
              "them to archive).", file=sys.stderr)
        print("       Pass --private-repo PATH, or --public-only if this fork "
              "keeps no private repo.", file=sys.stderr)
        return 1

    # Terminal mode consults the open playlist/photo issues before selecting.
    blocked_dates: dict = {}
    if mode == "terminal" and not skip_issue_check:
        repo_slug = detect_repo_slug()
        if not repo_slug:
            print("ERROR: could not determine the GitHub repo for the open-issue "
                  "check (no GITHUB_REPOSITORY, no recognizable git remote).",
                  file=sys.stderr)
            print("       Pass --skip-issue-check to proceed without it.",
                  file=sys.stderr)
            return 1
        try:
            blocked_dates = open_issue_dates(repo_slug)
        except Exception as error:
            print(f"ERROR: open-issue check against {repo_slug} failed: {error}",
                  file=sys.stderr)
            if "CERTIFICATE_VERIFY_FAILED" in str(error):
                print("       (macOS python.org builds need a CA bundle: "
                      "`pip install certifi`, or run the bundled "
                      "\"Install Certificates.command\" once.)", file=sys.stderr)
            print("       Pass --skip-issue-check to proceed without it.",
                  file=sys.stderr)
            return 1

    current_rows = read_tsv(current_path)
    print(f"Read {len(current_rows)} rows from {current_path.name}")

    # ── Selection ──────────────────────────────────────────────────────────
    to_migrate = []          # rows leaving current for history
    to_keep = []             # rows staying in current
    skipped_status = []      # right date/mode but not attended
    skipped_not_terminal = []  # terminal mode: attended but fields pending
    skipped_blocked = []     # terminal mode: open playlist/photo issue
    skipped_out_of_scope = []  # year/show mode: row outside the selection
    skipped_bad_date = []

    for row in current_rows:
        date_str = row.get("Show Date", "").strip()
        status = row.get("Status", "").strip().lower()

        dt = validate_date(date_str)
        if dt is None:
            skipped_bad_date.append(row)
            to_keep.append(row)
            continue

        if mode == "year" and dt.year != mode_arg:
            skipped_out_of_scope.append(row)
            to_keep.append(row)
            continue
        if mode == "show" and date_str != mode_arg:
            skipped_out_of_scope.append(row)
            to_keep.append(row)
            continue

        if status != "attended":
            if mode != "terminal":
                skipped_status.append(row)
            to_keep.append(row)
            continue

        if mode == "terminal":
            gaps = terminal_gaps(row)
            if gaps:
                skipped_not_terminal.append((row, gaps))
                to_keep.append(row)
                continue
            if date_str in blocked_dates:
                skipped_blocked.append((row, blocked_dates[date_str]))
                to_keep.append(row)
                continue

        to_migrate.append(row)

    # ── Per-year history classification (fresh vs already-migrated) ────────
    by_year: dict = {}
    for row in to_migrate:
        by_year.setdefault(validate_date(row["Show Date"]).year, []).append(row)

    plans = []               # (year, history_path, fresh_rows, duplicate_rows)
    for year in sorted(by_year):
        history_path = history_dir / f"{year}.tsv"
        existing_keys = {dedup_key(r) for r in read_tsv(history_path)}
        fresh = [r for r in by_year[year] if dedup_key(r) not in existing_keys]
        dupes = [r for r in by_year[year] if dedup_key(r) in existing_keys]
        plans.append((year, history_path, fresh, dupes))

    # Every row leaving current (fresh migrations + already-in-history dupes) is a
    # candidate for private archive + prune, so the sidecar stays in sync with current.
    removed_keys = {dedup_key(r) for r in to_migrate}

    # ── Private side: classify (read-only here; writes happen after confirm) ──
    priv_rows = []
    priv_plans = []          # (year, archive_path, rows_to_archive)
    priv_to_prune = []
    priv_missing = []
    if private_repo:
        priv_rows = read_tsv(private_current_path)
        priv_by_key = {dedup_key(r): r for r in priv_rows}
        priv_archive_by_year: dict = {}
        for key in sorted(removed_keys):
            pr = priv_by_key.get(key)
            if pr is None:
                priv_missing.append(key)
                continue
            priv_to_prune.append(pr)
            year = validate_date(pr.get("Show Date", ""))
            year = year.year if year else 0
            priv_archive_by_year.setdefault(year, []).append(pr)
        for year in sorted(priv_archive_by_year):
            archive_path = private_dir / f"{year}.tsv"
            existing = {dedup_key(r) for r in read_tsv(archive_path)}
            rows = [r for r in priv_archive_by_year[year]
                    if dedup_key(r) not in existing]
            if rows:
                priv_plans.append((year, archive_path, rows))

    # ── Summary ────────────────────────────────────────────────────────────
    mode_desc = {"year": f"year {mode_arg}", "show": f"show {mode_arg}",
                 "terminal": "terminal-state"}[mode]
    total_fresh = sum(len(fresh) for _, _, fresh, _ in plans)
    total_dupes = sum(len(dupes) for _, _, _, dupes in plans)

    print()
    print(f"{mode_desc} summary:")
    for year, history_path, fresh, dupes in plans:
        print(f"  {len(fresh):3d}  rows to migrate to history/{year}.tsv"
              + (f"  (+{len(dupes)} already there, removed from current only)"
                 if dupes else ""))
    if not plans:
        print("    0  rows selected")
    if skipped_status:
        print(f"  {len(skipped_status):3d}  in scope but not 'attended' (kept in current)")
    if skipped_not_terminal:
        print(f"  {len(skipped_not_terminal):3d}  attended but not yet terminal (kept in current)")
    if skipped_blocked:
        print(f"  {len(skipped_blocked):3d}  terminal but blocked by an open issue (kept in current)")
    if skipped_bad_date:
        print(f"  {len(skipped_bad_date):3d}  rows with unparseable dates (kept in current) ⚠️")

    if private_repo:
        print()
        print("  Private archive (--private-repo):")
        for year, archive_path, rows in priv_plans:
            print(f"    {len(rows):3d}  rows to archive to history_private/{year}.tsv")
        print(f"    {len(priv_to_prune):3d}  rows to prune from current_private.tsv")
        if priv_missing:
            print(f"    {len(priv_missing):3d}  migrated shows with NO matching private row "
                  f"(nothing to archive) ⚠️")
            for (d, a) in priv_missing:
                print(f"         {d}  {a}")
    else:
        print()
        print("  --private-repo not given: current_private.tsv left untouched "
              "(orphan rows will remain).")

    if skipped_not_terminal:
        print()
        print("  Not yet terminal (the curation-debt list):")
        for row, gaps in skipped_not_terminal:
            print(f"    {row.get('Show Date', '?')}  {row.get('Artist', '?')}"
                  f" — pending: {', '.join(gaps)}")

    if skipped_blocked:
        print()
        print("  Blocked by open issues:")
        for row, reasons in skipped_blocked:
            print(f"    {row.get('Show Date', '?')}  {row.get('Artist', '?')}")
            for reason in reasons:
                print(f"         {reason}")

    if skipped_status and mode != "terminal":
        print()
        print("  Non-attended rows in scope (kept in current):")
        for r in skipped_status:
            print(f"    [{r.get('Status', '?')}] {r.get('Show Date', '?')}  {r.get('Artist', '?')}")

    if total_dupes:
        print()
        print("  Already-migrated rows (removed from current):")
        for _, _, _, dupes in plans:
            for r in dupes:
                print(f"    {r.get('Show Date', '?')}  {r.get('Artist', '?')}")

    if total_fresh:
        print()
        print("  Rows to migrate:")
        for _, _, fresh, _ in plans:
            for r in fresh:
                print(f"    {r.get('Show Date', '?')}  {r.get('Artist', '?')}")

    if not to_migrate:
        print()
        print("Nothing to do — no rows selected for migration.")
        return 0

    if dry_run:
        print()
        print("DRY RUN — no files written.")
        return 0

    if not force:
        print()
        try:
            answer = input("Proceed? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            return 0
        if answer != "y":
            print("Aborted.")
            return 0

    # ── Write public history (copy before delete) ──────────────────────────
    for year, history_path, fresh, _dupes in plans:
        if not fresh:
            continue
        history_rows = [current_to_history(r) for r in fresh]
        if not history_path.exists():
            write_tsv(history_path, history_rows, HISTORY_COLS)
            print(f"Created {history_path} with {len(history_rows)} rows.")
        else:
            append_tsv(history_path, history_rows,
                       read_header(history_path, HISTORY_COLS))
            print(f"Appended {len(history_rows)} rows to {history_path}.")

    # ── Archive private rows (copy before prune) ───────────────────────────
    if private_repo:
        for year, archive_path, rows in priv_plans:
            if not archive_path.exists():
                write_tsv(archive_path, rows, PRIVATE_COLS)
                print(f"Created {archive_path} with {len(rows)} rows.")
            else:
                append_tsv(archive_path, rows,
                           read_header(archive_path, PRIVATE_COLS))
                print(f"Appended {len(rows)} rows to {archive_path}.")
        if not priv_plans:
            print("No new private rows to archive.")

    # ── Rewrite current (keeping only to_keep rows) ────────────────────────
    actual_cols = read_header(current_path, CURRENT_COLS)
    write_tsv(current_path, to_keep, actual_cols)
    print(f"Removed {len(to_migrate)} rows from {current_path.name} "
          f"({len(to_keep)} rows remaining).")

    # ── Prune current_private (remove migrated keys) ───────────────────────
    if private_repo:
        prune_keys = {dedup_key(r) for r in priv_to_prune}
        kept_priv = [r for r in priv_rows if dedup_key(r) not in prune_keys]
        priv_actual_cols = read_header(private_current_path, PRIVATE_COLS)
        write_tsv(private_current_path, kept_priv, priv_actual_cols)
        print(f"Pruned {len(priv_to_prune)} rows from {private_current_path.name} "
              f"({len(kept_priv)} rows remaining).")

    print()
    print("Done.")
    if private_repo:
        print("Remember to commit BOTH repos (live-shows and live-shows-private).")
    if to_migrate and mode == "terminal":
        print("If this created a new history/<year>.tsv, add that year to "
              "config.yaml history_years so the site renders it.")
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate attended shows from live_shows_current.tsv to history/<year>.tsv"
    )
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "--terminal",
        action="store_true",
        help="Migrate every attended row at terminal state (setlist + playlist "
             "present, no open playlist/photo issue). The standing mode.",
    )
    mode_group.add_argument(
        "--show",
        type=str,
        metavar="YYYY-MM-DD",
        help="Migrate the attended row for one show date, bypassing the "
             "terminal checks.",
    )
    mode_group.add_argument(
        "--year",
        type=int,
        help="Migrate every attended row in a calendar year (backfill / "
             "year-end catch-all).",
    )
    parser.add_argument(
        "--private-repo",
        type=str,
        default=None,
        metavar="PATH",
        help="Path to the live-shows-private repo clone. When given, archives each "
             "migrated show's private row to history_private/<year>.tsv and prunes it "
             "from current_private.tsv. When omitted, the private repo is left untouched.",
    )
    parser.add_argument(
        "--public-only",
        action="store_true",
        help="Allow a REAL run without --private-repo. Only for forks that "
             "keep no private repo — on this repo it permanently orphans "
             "private rows.",
    )
    parser.add_argument(
        "--skip-issue-check",
        action="store_true",
        help="Terminal mode only: skip the open playlist/photo issue check "
             "(e.g. offline).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would happen without writing any files",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip the confirmation prompt",
    )
    args = parser.parse_args()

    if args.year is not None and (args.year < 2021 or args.year > datetime.now().year + 1):
        print(f"ERROR: --year {args.year} looks wrong. "
              f"Expected between 2021 and {datetime.now().year + 1}.", file=sys.stderr)
        sys.exit(1)
    if args.show is not None and validate_date(args.show) is None:
        print(f"ERROR: --show {args.show} is not a YYYY-MM-DD date.", file=sys.stderr)
        sys.exit(1)

    if args.terminal:
        mode, mode_arg = "terminal", None
    elif args.show:
        mode, mode_arg = "show", args.show
    else:
        mode, mode_arg = "year", args.year

    sys.exit(run(mode, mode_arg, args.dry_run, args.force,
                 args.private_repo, args.skip_issue_check, args.public_only))


if __name__ == "__main__":
    main()
