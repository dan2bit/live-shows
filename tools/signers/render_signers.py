#!/usr/bin/env python3
"""Render signers/index.html from data/show_goals/hat_signatures.tsv.

Replaces the hand-maintained "Who Has Signed This Hat?" Google Doc (#412):
Google's forced mobile renderer clipped the doc's margins in Firefox and
dropped its banner entirely in Chrome, and the doc drifted from the TSV
(the actual completeness authority) because Routine 2's manual append step
was easy to skip. This script is deterministic - identical inputs produce
byte-identical output - so CI can run it after every hat_signatures.tsv
change with nothing to hand-maintain, and --check lets CI (or a person)
catch drift without diffing by eye.

Usage:
    python3 tools/signers/render_signers.py            # write signers/index.html
    python3 tools/signers/render_signers.py --check     # exit 1 if the committed
                                                          # file doesn't match a
                                                          # fresh render

Run from the repo root - every path below is relative to it.
"""
import argparse
import csv
import html
import re
import sys
from collections import OrderedDict
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
HAT_SIGNATURES_TSV = REPO_ROOT / "data" / "show_goals" / "hat_signatures.tsv"
VENUES_TSV = REPO_ROOT / "data" / "venues.tsv"
CONFIG_YAML = Path(__file__).resolve().parent / "signers.yaml"
TEMPLATE_HTML = Path(__file__).resolve().parent / "signers.template.html"
OUTPUT_HTML = REPO_ROOT / "signers" / "index.html"


def load_tsv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def load_config():
    with open(CONFIG_YAML, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    for key in ("banner_svg", "playlist_qr"):
        asset_path = REPO_ROOT / cfg[key]
        if not asset_path.is_file():
            # A silently-missing banner is exactly the Chrome bug this page
            # replaces (#412) - fail the build rather than ship a hole.
            sys.exit(f"signers.yaml -> {key}: {cfg[key]} does not exist at "
                      f"{asset_path} - the build refuses to ship a missing asset.")

    # The stored QR's <desc> records the URL it was generated from
    # (tools/signers/make_qr.py). Compare that against playlist_url so a
    # config edit that forgets to regenerate the QR fails loudly here
    # instead of shipping a QR that points somewhere else.
    qr_svg = (REPO_ROOT / cfg["playlist_qr"]).read_text(encoding="utf-8")
    m = re.search(r"<desc>(.*?)</desc>", qr_svg, re.DOTALL)
    qr_url = m.group(1).strip() if m else None
    if qr_url != cfg["playlist_url"]:
        sys.exit(f"{cfg['playlist_qr']} encodes {qr_url!r} but signers.yaml's "
                  f"playlist_url is {cfg['playlist_url']!r} - regenerate the QR: "
                  f"python3 tools/signers/make_qr.py '{cfg['playlist_url']}' {cfg['playlist_qr']}")
    return cfg


def short_venue_names():
    """Venue Name -> Short Name, falling back to the full name when blank
    or when the venue has no venues.tsv row at all (#412, open decision 2:
    only 3 of 20 hat-signing venues currently have Short Name filled in).
    """
    names = {}
    for row in load_tsv(VENUES_TSV):
        full = row.get("Venue Name", "").strip()
        short = (row.get("Short Name") or "").strip()
        if full:
            names[full] = short or full
    return names


def fmt_date(iso_date):
    """'2023-09-08' -> '9/8/23' (matches the source doc's own format)."""
    y, m, d = (int(p) for p in iso_date.split("-"))
    return f"{m}/{d}/{y % 100}"


def build_entries_html(rows, venue_short):
    """Group by year (in seq/ledger order, which is already chronological
    in the data) and render each entry. The `notes` column is deliberately
    NOT rendered here - it carries internal photo-panel-tracking shorthand
    ("panel anchor (Dan)", raw PXL_ filenames) that was never meant for a
    public page. See #412, open decision 3, for the one case (Talia Segal's
    "RIP") this leaves out - it needs an explicit, documented representation
    before it belongs here, not a public page maintainer parsing free text.
    """
    years = OrderedDict()
    for row in rows:
        year = row["show_date"][:4]
        years.setdefault(year, []).append(row)

    out = []
    for year, entries in years.items():
        out.append(f'    <section class="year-group">\n      <h2 class="year">{year}</h2>\n      <ul class="entry-list">')
        for r in entries:
            signer = html.escape(r["signer"])
            attribution = html.escape(r["attribution"]) if r.get("attribution") else ""
            venue = html.escape(venue_short.get(r["venue"], r["venue"]))
            when = fmt_date(r["show_date"])
            attr_html = f' <span class="attribution">{attribution}</span>' if attribution else ""
            out.append(
                f'        <li class="entry"><span class="signer">{signer}</span>{attr_html}'
                f'<span class="meta">{venue} &middot; {when}</span></li>'
            )
        out.append("      </ul>\n    </section>")
    return "\n".join(out)


def render():
    cfg = load_config()
    rows = load_tsv(HAT_SIGNATURES_TSV)
    if not rows:
        sys.exit("hat_signatures.tsv has no rows - refusing to render an empty page.")
    rows.sort(key=lambda r: int(r["seq"]))  # ledger order; also the chronological order
    venue_short = short_venue_names()

    latest = rows[-1]
    template = TEMPLATE_HTML.read_text(encoding="utf-8")

    playlist_url_short = re.sub(r"^https?://", "", cfg["playlist_url"])

    substitutions = {
        "TITLE": html.escape(cfg["title"]),
        "TAGLINE": html.escape(cfg["tagline"]),
        "COUNT": str(len(rows)),
        "FIRST_DATE": fmt_date(rows[0]["show_date"]),
        "LATEST_NAME": html.escape(latest["signer"]),
        "LATEST_DATE": fmt_date(latest["show_date"]),
        "BANNER_SVG": cfg["banner_svg"],
        "PLAYLIST_URL": html.escape(cfg["playlist_url"]),
        "PLAYLIST_URL_SHORT": html.escape(playlist_url_short),
        "PLAYLIST_QR": cfg["playlist_qr"],
        "PRINT_PAGE_SIZE": cfg["print_page_size"],
        "PRINT_CONTENT_WIDTH_IN": str(cfg["print_content_width_in"]),
        "PRINT_COLUMN_COUNT": str(cfg["print_column_count"]),
        "ENTRIES": build_entries_html(rows, venue_short),
    }
    for key, value in substitutions.items():
        template = template.replace("{{" + key + "}}", value)

    if "{{" in template:
        leftover = re.findall(r"\{\{[A-Z_]+\}\}", template)
        sys.exit(f"unfilled template placeholder(s): {leftover}")

    return template


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true",
                         help="exit 1 if signers/index.html doesn't match a fresh render, without writing")
    args = parser.parse_args()

    rendered = render()

    if args.check:
        if not OUTPUT_HTML.is_file():
            sys.exit(f"{OUTPUT_HTML} does not exist - run without --check to create it.")
        current = OUTPUT_HTML.read_text(encoding="utf-8")
        if current != rendered:
            sys.exit(f"{OUTPUT_HTML} is stale - it doesn't match a fresh render of the current inputs. "
                      f"Run: python3 {Path(__file__).relative_to(REPO_ROOT)}")
        print("signers/index.html is up to date.")
        return

    OUTPUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_HTML.write_text(rendered, encoding="utf-8")
    print(f"wrote {OUTPUT_HTML} ({len(rendered)} bytes)")


if __name__ == "__main__":
    main()
