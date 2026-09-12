#!/usr/bin/env python3
"""follows_reminder.py - "you added someone, go follow them".

Compares the working tree against a git ref and reports every artist row ADDED
to tools/research/follows/follows_master.tsv or data/fast_track.tsv since that
ref, with the platforms still to be followed on:

  - a follows_master add reports whichever of Bandsintown / Seated is not Y
  - a fast_track add reports both unless its follows_master row already says Y;
    a fast_track add with no follows_master row is reported as such (the
    pipeline expects fast_track to be a subset of follows_master)

Songkick is frozen and never reported. Direct Mail is a separate decision and
never reported.

Per artist the line carries what can be linked: the Bandsintown artist page when
a Bandsintown URL is already on file (fast_track Tour URL), and the Seated
notifications page, where the name has to be typed into the in-page search -
neither platform exposes a search-results URL.

Prints NOTHING and exits 0 when no rows were added, so the output can feed
notify_email.py unconditionally. A push that only edits existing rows sends
no mail.

    --base REF     the ref to diff against (default: HEAD~1); in the workflow
                   this is github.event.before
    --footer       append the platform export ages (from git history)
"""

import argparse
import csv
import io
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FOLLOWS_MASTER = "tools/research/follows/follows_master.tsv"
FAST_TRACK = "data/fast_track.tsv"
EXPORTS = ("tools/research/follows/rhbl-bandsintown.tsv",
           "tools/research/follows/rhbl-seated.tsv")
PLATFORMS = ("Bandsintown", "Seated")
SEATED_URL = "https://go.seated.com/notifications"


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                          text=True, check=True).stdout


def rows_at(ref, path):
    """Rows of a TSV at a ref; empty if the file did not exist there."""
    try:
        text = git("show", f"{ref}:{path}")
    except subprocess.CalledProcessError:
        return []
    return list(csv.DictReader(io.StringIO(text), delimiter="\t"))


def rows_now(path):
    p = ROOT / path
    if not p.exists():
        return []
    with open(p, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def added(ref, path):
    before = {r["Artist"] for r in rows_at(ref, path)}
    return [r for r in rows_now(path) if r["Artist"] not in before]


def missing_platforms(fm_row):
    return [p for p in PLATFORMS if (fm_row or {}).get(p, "").strip() != "Y"]


def export_age(path):
    try:
        out = git("log", "-1", "--format=%cs", "--", path).strip()
        return (date.today() - date.fromisoformat(out)).days if out else None
    except (subprocess.CalledProcessError, ValueError):
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base", default="HEAD~1")
    ap.add_argument("--footer", action="store_true")
    args = ap.parse_args()

    fm_now = {r["Artist"]: r for r in rows_now(FOLLOWS_MASTER)}
    ft_now = {r["Artist"]: r for r in rows_now(FAST_TRACK)}
    lines = []
    reported = set()

    for r in added(args.base, FOLLOWS_MASTER):
        need = missing_platforms(r)
        if not need:
            continue
        ft = ft_now.get(r["Artist"])
        tag = " (fast track)" if ft else ""
        lines.append(f"- {r['Artist']}{tag}: add to {', '.join(need)}")
        lines.extend(links(r["Artist"], need, ft))
        reported.add(r["Artist"])

    for r in added(args.base, FAST_TRACK):
        name = r["Artist"]
        if name in reported:
            continue
        fm = fm_now.get(name)
        if fm is None:
            lines.append(f"- {name} (fast track): NO follows_master row - add one, then follow on "
                         f"{', '.join(PLATFORMS)}")
            lines.extend(links(name, list(PLATFORMS), r))
            continue
        need = missing_platforms(fm)
        if need:
            lines.append(f"- {name} (fast track): add to {', '.join(need)}")
            lines.extend(links(name, need, r))

    if not lines:
        return 0

    out = ["Artists added to the follow ledgers that still need platform follows.",
           "Set the flag on the follows_master row once each follow is done.", ""]
    out += lines
    if args.footer:
        out.append("")
        for path in EXPORTS:
            days = export_age(path)
            label = Path(path).stem.replace("rhbl-", "")
            out.append(f"{label} export: {days} days old" if days is not None
                       else f"{label} export: age unknown")
    print("\n".join(out))
    return 0


def links(name, need, ft_row):
    out = []
    if "Bandsintown" in need:
        url = (ft_row or {}).get("Tour URL", "")
        if "bandsintown.com" in url:
            out.append(f"    Bandsintown: {url}")
        else:
            out.append(f"    Bandsintown: search the header box for \"{name}\"")
    if "Seated" in need:
        out.append(f"    Seated: {SEATED_URL} - search \"{name}\"")
    return out


if __name__ == "__main__":
    sys.exit(main())
