#!/usr/bin/env python3
"""Render signers/index.html from data/show_goals/hat_signatures.tsv.

Replaces the hand-maintained "Who Has Signed This Hat?" Google Doc (#412):
Google's forced mobile renderer clipped the doc's margins in Firefox and
dropped its banner entirely in Chrome, and the doc drifted from the TSV
(the actual completeness authority) because Routine 2's manual append step
was easy to skip. This script is deterministic - identical inputs produce
byte-identical output - so CI can run it after every input change with
nothing to hand-maintain, and --check lets CI (or a person) catch drift
without diffing by eye.

Inputs: hat_signatures.tsv, venues.tsv, tools/signers/signers.yaml, the
repo-root config.yaml (site.pages_base and site.title, for the absolute URLs
in the head), and data/artist_modal_index.json (to decide which names can
open the artist modal).

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
import json
import re
import struct
import sys
import unicodedata
from collections import OrderedDict
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
HAT_SIGNATURES_TSV = REPO_ROOT / "data" / "show_goals" / "hat_signatures.tsv"
VENUES_TSV = REPO_ROOT / "data" / "venues.tsv"
ARTIST_INDEX_JSON = REPO_ROOT / "data" / "artist_modal_index.json"
SITE_CONFIG_YAML = REPO_ROOT / "config.yaml"
CONFIG_YAML = Path(__file__).resolve().parent / "signers.yaml"
TEMPLATE_HTML = Path(__file__).resolve().parent / "signers.template.html"
OUTPUT_HTML = REPO_ROOT / "signers" / "index.html"


def load_tsv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def load_site_config():
    """The two values the head needs from the repo-root config.yaml, so a fork
    sets them once there rather than a second time in signers.yaml."""
    with open(SITE_CONFIG_YAML, encoding="utf-8") as f:
        site = (yaml.safe_load(f) or {}).get("site") or {}
    for key in ("pages_base", "title"):
        if not site.get(key):
            sys.exit(f"config.yaml: site.{key} is missing - the page head needs it "
                      f"to build absolute canonical and og: URLs.")
    return {"pages_base": str(site["pages_base"]).rstrip("/"), "title": str(site["title"])}


def load_config():
    with open(CONFIG_YAML, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    for key in ("banner_svg", "playlist_qr", "site_qr", "og_image"):
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


def png_size(path):
    """(width, height) from the PNG header - no image library needed."""
    head = Path(path).read_bytes()[:24]
    if head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        sys.exit(f"{path} is not a PNG - og:image must be a PNG or JPEG raster, "
                  f"and this generator only reads PNG headers.")
    return struct.unpack(">II", head[16:24])


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


# --- artist modal links -----------------------------------------------------

def am_norm(s):
    """Port of amNorm() in artist-modal.js (itself a mirror of norm() in
    scripts/build_artist_index.py): de-invert "Lone Bellow, The", drop accents,
    lowercase, drop one leading article, punctuation to space, collapse
    whitespace. The index is keyed by this, so a name resolves here exactly when
    it would resolve in the browser."""
    s = (s or "").strip()
    m = re.match(r"^(.*),\s+(the|a|an)$", s, re.I)
    if m:
        s = m.group(2) + " " + m.group(1)
    s = unicodedata.normalize("NFKD", s)
    s = re.sub(r"[\u0300-\u036f]", "", s).lower()
    s = re.sub(r"^\s*(the|a|an)\s+", "", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def load_artist_index():
    """(artists, aliases) from the modal index, or ({}, {}) with a warning when
    it is absent - a fork without the modal still gets a working, unlinked page."""
    if not ARTIST_INDEX_JSON.is_file():
        print(f"signers: {ARTIST_INDEX_JSON.relative_to(REPO_ROOT)} not found - "
              f"rendering without artist links.", file=sys.stderr)
        return {}, {}
    data = json.loads(ARTIST_INDEX_JSON.read_text(encoding="utf-8"))
    return data.get("artists", {}), data.get("aliases", {})


def resolve_slug(name, artists, aliases):
    """The modal's own lookup: amNorm key, else the alias map. None if unknown."""
    key = am_norm(name)
    rec = artists.get(key)
    if rec is None and key in aliases:
        key = aliases[key]
        rec = artists.get(key)
    if rec is None:
        return None
    return rec.get("slug") or key.replace(" ", "-")


def lookup_slug(name, artists, aliases):
    """(slug, folded). The modal's own lookup first; only when that misses, the
    equivalence recommend_aliases.tsv documents as automatic - "drop a trailing
    ' Band'" - tried in the other direction: 'Jesse Williams' finds the record
    'The Jesse Williams Band'. build_artist_index.py does not apply that rule (it
    keeps 'X' and 'X Band' as separate records, or only the Band form), so a
    bandleader whose act is named for them would otherwise get no link. The slug
    returned is the real record's, so the modal opens exactly that card; `folded`
    tells the caller the plain name was not what matched."""
    slug = resolve_slug(name, artists, aliases)
    if slug is not None:
        return slug, False
    slug = resolve_slug(name + " Band", artists, aliases)
    return (slug, True) if slug is not None else (None, False)


def build_entries_html(rows, venue_short, artists, aliases):
    """Group by year (in seq/ledger order, which is already chronological
    in the data) and render each entry. The `notes` column is deliberately
    NOT rendered here - it carries internal photo-panel-tracking shorthand
    ("panel anchor (Dan)", raw PXL_ filenames) that was never meant for a
    public page. See #412, open decision 3, for the one case (Talia Segal's
    "RIP") this leaves out - it needs an explicit, documented representation
    before it belongs here, not a public page maintainer parsing free text.

    Modal links: the anchor goes on the band for an "of <band>" attribution
    (Pipkin, Baldino, Browning...), otherwise on the signer's own name. It is a
    plain "#artist/<slug>" anchor - the modal module's hash router opens it - and
    only when the target resolves in the index, so nothing opens an empty
    "unknown artist" card. An unresolved target stays plain text.
    Returns (markup, names that could not be linked, {name: slug} for names that
    matched only through the trailing-Band equivalence).
    """
    unlinked = []
    folded = {}

    def target(label, cls=None):
        slug, via_band = lookup_slug(label, artists, aliases)
        if via_band:
            folded[label] = slug
        text = html.escape(label)
        if slug is None:
            if label not in unlinked:
                unlinked.append(label)
            return f'<span class="{cls}">{text}</span>' if cls else text
        classes = f"{cls} signer-link" if cls else "signer-link"
        return f'<a class="{classes}" href="#artist/{html.escape(slug, quote=True)}">{text}</a>'

    years = OrderedDict()
    for row in rows:
        years.setdefault(row["show_date"][:4], []).append(row)

    out = []
    for year, entries in years.items():
        out.append(f'    <section class="year-group">\n      <h2 class="year">{year}</h2>\n      <ul class="entry-list">')
        for r in entries:
            attribution = (r.get("attribution") or "").strip()
            band = re.match(r"^of\s+(.+)$", attribution, re.I)
            if band:
                signer_html = f'<span class="signer">{html.escape(r["signer"])}</span>'
                prefix = html.escape(attribution[:band.start(1)])
                attr_html = f' <span class="attribution">{prefix}{target(band.group(1).strip())}</span>'
            else:
                signer_html = target(r["signer"], "signer")
                attr_html = f' <span class="attribution">{html.escape(attribution)}</span>' if attribution else ""
            venue = html.escape(venue_short.get(r["venue"], r["venue"]))
            when = fmt_date(r["show_date"])
            out.append(
                f'        <li class="entry">{signer_html}{attr_html}'
                f'<span class="meta">{venue} &middot; {when}</span></li>'
            )
        out.append("      </ul>\n    </section>")
    return "\n".join(out), unlinked, folded


def render():
    cfg = load_config()
    site = load_site_config()
    rows = load_tsv(HAT_SIGNATURES_TSV)
    if not rows:
        sys.exit("hat_signatures.tsv has no rows - refusing to render an empty page.")
    rows.sort(key=lambda r: int(r["seq"]))  # ledger order; also the chronological order
    venue_short = short_venue_names()
    artists, aliases = load_artist_index()

    template = TEMPLATE_HTML.read_text(encoding="utf-8")
    playlist_url_short = re.sub(r"^https?://", "", cfg["playlist_url"])
    og_w, og_h = png_size(REPO_ROOT / cfg["og_image"])
    entries_html, unlinked, folded = build_entries_html(rows, venue_short, artists, aliases)
    if folded:
        print("signers: linked through the trailing-Band equivalence: "
              + ", ".join(f"{n} -> {s}" for n, s in folded.items()), file=sys.stderr)
    if unlinked and artists:
        print(f"signers: no artist-modal record for {len(unlinked)} name(s), left as plain "
              f"text: {', '.join(unlinked)}", file=sys.stderr)

    substitutions = {
        "TITLE": html.escape(cfg["title"]),
        "DESCRIPTION": html.escape(cfg["description"]),
        "SITE_TITLE": html.escape(site["title"]),
        "CANONICAL_URL": html.escape(f"{site['pages_base']}/{OUTPUT_HTML.parent.name}/"),
        "OG_IMAGE_URL": html.escape(f"{site['pages_base']}/{cfg['og_image']}"),
        "OG_IMAGE_WIDTH": str(og_w),
        "OG_IMAGE_HEIGHT": str(og_h),
        "BANNER_ALT": html.escape(cfg["banner_alt"]),
        "COUNT": str(len(rows)),
        "FIRST_DATE": fmt_date(rows[0]["show_date"]),
        "LATEST_DATE": fmt_date(rows[-1]["show_date"]),
        "BANNER_SVG": cfg["banner_svg"],
        "SITE_QR": cfg["site_qr"],
        "PLAYLIST_URL": html.escape(cfg["playlist_url"]),
        "PLAYLIST_URL_SHORT": html.escape(playlist_url_short),
        "PLAYLIST_QR": cfg["playlist_qr"],
        "PRINT_PDF": html.escape(cfg["print_pdf"]),
        "PRINT_PAGE_SIZE": cfg["print_page_size"],
        "PRINT_CONTENT_WIDTH_IN": str(cfg["print_content_width_in"]),
        "PRINT_COLUMN_COUNT": str(cfg["print_column_count"]),
        "ENTRIES": entries_html,
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
