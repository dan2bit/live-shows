#!/usr/bin/env python3
"""reconcile_follows.py - check the follows pipeline against itself and the platforms.

Three ledgers, one pipeline:

    new_artist_research.tsv  ->  follows_master.tsv  ->  fast_track.tsv
    candidates, unfollowed       approved to follow       strict subset, jumps the queue

Invariants the pipeline is expected to hold:

  1. NAR and follows_master do not overlap (a row leaves NAR on promotion).
  2. NAR and artists.tsv do not overlap (seen live means a follows_master decision,
     not research).
  3. Every fast_track artist has a follows_master row (tier unconstrained).
  4. Every artist followed on a platform has a follows_master row, and every
     follows_master row flagged Y for a platform is actually followed there.

Invariants 1-3 need only the repo. Invariant 4 needs the platform exports in
tools/research/follows/ (rhbl-bandsintown.tsv, rhbl-seated.tsv), refreshed by
hand per web-src/scraping_tasks.md; those sections are skipped when an export
is missing. Songkick is frozen and never checked.

Name matching goes through scripts/name_forms.py plus data/recommend_aliases.tsv,
never a raw string compare, so "Ghalia Volt Band" meets "Ghalia Volt" and a
platform display name that is really a page title can be aliased rather than
hand-edited out of the export.

Output: a plain-text report, one section per finding type, sections omitted when
empty. Prints NOTHING and exits 0 when everything holds, so the output can feed
notify_email.py unconditionally (its empty-body rule suppresses the mail).

    --json        emit the same findings as JSON instead
    --hygiene     invariants 1-3 only, routed through hygiene_report so they
                  land in the data-hygiene job summary (advisory)
    --footer      append the export ages even when the report is otherwise empty
                  (for a mail that should always show how stale the yardstick is)
"""

import argparse
import csv
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from name_forms import lookup_forms, norm, variant_keys  # noqa: E402

FOLLOWS = ROOT / "tools/research/follows"
FOLLOWS_MASTER = FOLLOWS / "follows_master.tsv"
NAR = FOLLOWS / "new_artist_research.tsv"
FAST_TRACK = ROOT / "data/fast_track.tsv"
ARTISTS = ROOT / "data/artists.tsv"
ALIASES = ROOT / "data/recommend_aliases.tsv"
EXPORTS = {
    "Bandsintown": FOLLOWS / "rhbl-bandsintown.tsv",
    "Seated": FOLLOWS / "rhbl-seated.tsv",
}
# A note carrying one of these phrases marks an expected platform gap, not drift.
EXPECTED_GAP = {"Seated": ("not on seated",)}


# ---- loading ---------------------------------------------------------------

def read_tsv(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def read_roster(path):
    names = []
    with open(path, encoding="utf-8", newline="") as fh:
        for row in csv.reader(fh, delimiter="\t"):
            if row and row[0].strip() and row[0].strip() != "Artist":
                names.append(row[0].strip())
    return names


def load_aliases():
    out = {}
    if not ALIASES.exists():
        return out
    for line in ALIASES.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0] != "Alias":
            out[norm(parts[0])] = norm(parts[1])
    return out


class Matcher:
    """Alias-aware key sets. identity() for ledger-vs-ledger, lookup() for
    platform names, where a bill component ("Trombone Shorty" inside
    "Trombone Shorty & Orleans Avenue") is a legitimate match."""

    def __init__(self, aliases):
        self.aliases = aliases

    def _expand(self, keys):
        # norm() drops "&" but keeps the word "and", so "X & Y" and "X and Y"
        # come out different; platforms spell the same act both ways.
        keys = set(keys) | {k.replace(" and ", " ") for k in keys}
        return keys | {self.aliases[k] for k in keys if k in self.aliases}

    def identity(self, name):
        return self._expand(variant_keys(name))

    def lookup(self, name):
        return self._expand({norm(f) for f in lookup_forms(name)})

    def index(self, rows, key="Artist", mode="identity"):
        idx = {}
        for r in rows:
            name = r[key] if isinstance(r, dict) else r
            for k in getattr(self, mode)(name):
                idx.setdefault(k, r)
        return idx

    @staticmethod
    def hit(keys, idx):
        for k in keys:
            if k in idx:
                return idx[k]
        return None


# ---- checks ----------------------------------------------------------------

def export_age(path):
    """Days since the export was last committed (the files carry no date)."""
    try:
        out = subprocess.run(
            ["git", "log", "-1", "--format=%cs", "--", str(path.relative_to(ROOT))],
            cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
        return (date.today() - date.fromisoformat(out)).days if out else None
    except (subprocess.CalledProcessError, ValueError, FileNotFoundError):
        return None


def where(name, m, nar_i, ft_i, art_i):
    tags = []
    if m.hit(m.identity(name), ft_i):
        tags.append("fast_track")
    r = m.hit(m.identity(name), nar_i)
    if r:
        tags.append(f"NAR[{r.get('Status', '')}]")
    if m.hit(m.identity(name), art_i):
        tags.append("artists.tsv")
    return ", ".join(tags) or "nowhere"


def run():
    m = Matcher(load_aliases())
    fm = read_tsv(FOLLOWS_MASTER)
    nar = read_tsv(NAR) if NAR.exists() else []
    ft = read_tsv(FAST_TRACK) if FAST_TRACK.exists() else []
    art = read_tsv(ARTISTS) if ARTISTS.exists() else []
    fm_i, nar_i, ft_i, art_i = (m.index(x) for x in (fm, nar, ft, art))

    findings = {}

    def add(section, line):
        findings.setdefault(section, []).append(line)

    # Invariant 1
    for r in nar:
        if r.get("Status", "").startswith("promoted"):
            continue
        hit = m.hit(m.identity(r["Artist"]), fm_i)
        if hit:
            add("Invariant 1 - NAR row already in follows_master",
                f"{r['Artist']}  NAR[{r.get('Status', '')}]  follows_master[{hit.get('Tier', '')}]")
    # Invariant 2
    for r in nar:
        if m.hit(m.identity(r["Artist"]), art_i):
            add("Invariant 2 - NAR row for an artist already seen live",
                f"{r['Artist']}  NAR[{r.get('Status', '')}]")
    # Invariant 3
    for r in ft:
        if not m.hit(m.identity(r["Artist"]), fm_i):
            add("Invariant 3 - fast_track artist with no follows_master row", r["Artist"])

    # Invariant 4, per platform
    ages = {}
    for platform, path in EXPORTS.items():
        if not path.exists():
            add("Exports", f"{platform}: no export at {path.relative_to(ROOT)} - platform checks skipped")
            continue
        ages[platform] = export_age(path)
        roster = read_roster(path)
        ri = m.index(roster, mode="lookup")
        col = platform
        for r in fm:
            keys = m.lookup(r["Artist"])
            followed = m.hit(keys, ri) is not None
            flagged = r.get(col, "").strip() == "Y"
            note = r.get("Notes", "").lower()
            expected = any(p in note for p in EXPECTED_GAP.get(platform, ()))
            if flagged and not followed:
                add(f"{platform} - flagged Y, not followed", f"{r['Artist']}  [{r.get('Tier', '')}]")
            elif followed and not flagged:
                if expected:
                    add(f"{platform} - followed, but note says it is an expected gap (fix the note)",
                        r["Artist"])
                else:
                    add(f"{platform} - followed, flag blank", f"{r['Artist']}  [{r.get('Tier', '')}]")
        for name in roster:
            if not m.hit(m.lookup(name), fm_i):
                add(f"{platform} - followed, no follows_master row",
                    f"{name}  where: {where(name, m, nar_i, ft_i, art_i)}")

    return findings, ages


def render(findings, ages, footer):
    lines = []
    for section, items in findings.items():
        lines.append(f"## {section} ({len(items)})")
        lines.extend(f"  {i}" for i in items)
        lines.append("")
    if footer or findings:
        for platform, days in ages.items():
            lines.append(f"{platform} export: {days} days old" if days is not None
                         else f"{platform} export: age unknown (no git history)")
    return "\n".join(lines).rstrip()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--hygiene", action="store_true")
    ap.add_argument("--footer", action="store_true")
    args = ap.parse_args()

    findings, ages = run()

    if args.hygiene:
        from hygiene_report import Report  # noqa: E402
        report = Report("follows-pipeline invariants")
        for section, items in findings.items():
            if not section.startswith("Invariant"):
                continue
            path = NAR if "NAR" in section else FAST_TRACK
            for item in items:
                report.warn(f"{section}: {item}", path=str(path.relative_to(ROOT)))
        return report.finish()

    if args.json:
        print(json.dumps({"findings": findings, "export_age_days": ages}, indent=2))
        return 0

    text = render(findings, ages, args.footer)
    if text:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
