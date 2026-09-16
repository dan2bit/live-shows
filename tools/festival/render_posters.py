#!/usr/bin/env python3
"""
render_posters.py - generate both festival posters from lineup.json.

Second half of the festival pipeline:

    festival_lineup.md + data/artist_display.tsv
        -> build_lineup.py  -> festival/lineup.json
        -> render_posters.py -> festival/index.html
                                festival/festival_poster.html

Deliberately a separate script from `build_lineup.py`. The two fail in
different ways and need different review: a parse bug produces wrong DATA and
`check()` catches it; a template bug produces wrong LAYOUT, which no assertion
catches and only eyes do. Keeping them apart also keeps `lineup.json` a real
contract that can be tested on its own.

    python3 tools/festival/render_posters.py           # write both posters
    python3 tools/festival/render_posters.py --check    # fail if they are stale
    python3 tools/festival/render_posters.py --diff     # show what would change

STATIC OUTPUT, NOT CLIENT-SIDE FETCH

A poster gets saved to disk, printed, and opened from a stale cache. Fetching
the JSON at render time makes it blank in all three cases, which is a worse
failure than the duplication it removes.

THE .template.html FILES ARE THE EDITABLE SOURCE

`tools/festival/poster_*.template.html` hold the full page - every rule of CSS,
the masthead, the footer. Only the lineup regions are placeholders. Design
changes go there; the posters under `festival/` are generated and any hand-edit
is lost on the next run.

The "generated file" banner is INJECTED at render time rather than stored in the
template. A banner living in the template would greet anyone opening it with
"do not hand-edit" about the one file they are supposed to edit - and would
point at itself as the place to make changes.

Flat naming rather than a `templates/` subdirectory: the suffix already says
what the file is, and a directory holding two files next to the one script that
reads them earns nothing. It also removes a `mkdir` that can silently not
happen, leaving the script to fail at runtime instead.

THREE WIDTH CONTEXTS, WHICH IS WHY THE DATA CARRIES ALL THREE FORMS

  crescendo bill      short    type is graded by slot, largest on the page
  timeline set list   medium   two narrow columns
  timeline closer/co  CANONICAL  the headline lines have room for the real name

So `Christone "Kingfish" Ingram` closes day 1 in full on the timeline poster
while appearing as `Kingfish Ingram` in the list directly beneath it. That is
not an inconsistency to fix - it is why `artist_display.tsv` has two columns and
why the canonical name stays on every slot.

DERIVED, NOT STORED

Everything positional comes from the running order rather than the data file:

  crescendo size class   hour block index -> h12, h1x .. h9x
  line breaks            before the last two hour blocks
  timeline closer        main stage, last slot
  timeline co-headliners main second-to-last, second stage last, second-to-last

Storing any of it would let the JSON disagree with the layout it describes.

ACT NAMES ARE LINKS, PRINTED AS PLAIN TYPE

Every rendered name is an <a class="act"> that opens the artist card. The anchor
carries the CANONICAL artist (data-artist) and a slot note; the visible label is
whatever width the context called for. The templates style the anchor to print
with no link colour or underline - the underline appears only under a pointer or
keyboard focus, on screen - so a printed poster looks exactly as it did before.
The slug in the href comes from data/artist_modal_index.json when present.
"""

import argparse
import html.entities
import json
import re
import unicodedata
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LINEUP = ROOT / "festival" / "lineup.json"
HERE = Path(__file__).resolve().parent
TARGETS = {
    "crescendo": (HERE / "poster_crescendo.template.html",
                  ROOT / "festival" / "index.html"),
    "timeline": (HERE / "poster_timeline.template.html",
                 ROOT / "festival" / "festival_poster.html"),
}

# Injected directly under <html>, so it is the first thing in the generated file
# and the first thing a "view source" shows.
BANNER = """<!--
  GENERATED FILE - do not hand-edit. Changes here are lost on the next run.

  Lineup content : festival/festival_lineup.md  (plus data/artist_display.tsv
                   for names that need shortening to fit)
  Design, CSS,
  masthead, foot : tools/festival/%s

  Rebuild both posters:
      python3 tools/festival/build_lineup.py       # md  -> festival/lineup.json
      python3 tools/festival/render_posters.py     # json -> both posters

  `render_posters.py --check` fails if a committed poster has drifted from what
  the template would produce, and `--diff` shows what a hand-edit would lose.
-->
"""

# h12 is the noon block; h1x..h9x are the nine hours after it.
SIZE_CLASSES = ["h12"] + ["h%dx" % n for n in range(1, 10)]
BREAK_BEFORE = 2   # line break before the final two hour blocks


def esc(s):
    """HTML-escape a name the way the hand-written posters did.

    Curly punctuation and named entities are a RENDERING concern - the source
    files keep ASCII per the repo's TSV rule, and this is where it is converted.
    That is why typography never belongs in artist_display.tsv.
    """
    s = s.replace("&", "&amp;")
    # paired double quotes become typographic quotes: Christone "Kingfish" Ingram
    s = re.sub(r'"([^"]*)"', lambda m: "&ldquo;" + m.group(1) + "&rdquo;", s)
    s = s.replace("'", "&rsquo;")
    out = []
    for ch in s:
        if ord(ch) < 128:
            out.append(ch)
        else:
            name = html.entities.codepoint2name.get(ord(ch))
            out.append("&%s;" % name if name else "&#%d;" % ord(ch))
    return "".join(out)


def attr(s):
    """Plain attribute escaping - canonical names and notes ride in data-* attributes
    exactly as stored, so the modal's own normalizer sees the ASCII source form."""
    s = html.escape(s, quote=True)
    return "".join(ch if ord(ch) < 128 else "&#%d;" % ord(ch) for ch in s)


def norm(s):
    """The artist index's key form - mirrors the modal's own normalizer (de-invert
    "X, The", de-accent, lowercase, drop one leading article, punctuation to space).
    Lookups go through it so the lineup's Christone "Kingfish" Ingram meets the
    index's Christone 'Kingfish' Ingram, and James Hunter Six meets The James Hunter Six."""
    s = s.strip()
    m = re.match(r"^(.*),\s+(the|a|an)$", s, re.I)
    if m:
        s = m.group(2) + " " + m.group(1)
    s = "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch)).lower()
    s = re.sub(r"^\s*(the|a|an)\s+", "", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def load_slugs():
    """(index keys -> slug, alias key -> index key) from the prebuilt artist index.
    The anchor href carries the slug so an act name is a real deep link
    (#artist/<slug>) even without the click handler; a missing index yields
    href="#", and the click path still resolves by name."""
    idx = ROOT / "data" / "artist_modal_index.json"
    if not idx.exists():
        return {}, {}
    doc = json.loads(idx.read_text(encoding="utf-8"))
    arts = doc.get("artists") or {}
    return ({k: a.get("slug", "") for k, a in arts.items() if a.get("slug")},
            doc.get("aliases") or {})


SLUGS, ALIASES = load_slugs()


def slug_for(canonical):
    k = norm(canonical)
    return SLUGS.get(k) or SLUGS.get(ALIASES.get(k, ""), "")


STAGE_NAMES = {1: "Main Stage", 2: "Second Stage"}


def act_link(slot, label_html, day, extra=""):
    """Wrap a rendered name so a click opens the artist card. The anchor carries the
    CANONICAL artist in data-artist - the modal resolves and displays that, never the
    poster's abbreviated label - plus a note the card shows as its breadcrumb. Styled
    to print as plain type (see the template's a.act rules)."""
    canonical = slot["artist"]
    note = "Day %d \u00b7 %s %s%s" % (day["number"], STAGE_NAMES[slot["stage"]], slot["time"],
                                    (" \u00b7 " + extra) if extra else "")
    slug = slug_for(canonical)
    href = "#artist/" + slug if slug else "#"
    return ('<a class="act" href="%s" data-artist="%s" data-note="%s">%s</a>'
            % (href, attr(canonical), attr(note), label_html))


def time_key(t):
    """Running order on a 12-hour clock that starts at noon."""
    h, m = (int(x) for x in t.split(":"))
    return (0 if h == 12 else h, m)


def name_for(slot, width):
    """width: 'short' | 'medium' | 'canonical'. Falls back canonical-ward."""
    if width == "canonical":
        return slot["artist"]
    d = slot.get("display") or {}
    if width == "medium":
        return d.get("medium") or d.get("short") or slot["artist"]
    return d.get("short") or slot["artist"]


def ordered(day):
    return sorted(day["slots"], key=lambda s: (time_key(s["time"]), -s["stage"]))


def render_bill(day):
    """The crescendo running order: one span per act, size graded by hour block."""
    slots = ordered(day)
    blocks = [slots[i:i + 2] for i in range(0, len(slots), 2)]
    if len(blocks) > len(SIZE_CLASSES):
        raise SystemExit("FATAL: day %d has %d hour blocks, more than the %d size "
                         "classes the stylesheet defines"
                         % (day["number"], len(blocks), len(SIZE_CLASSES)))
    parts = []
    for i, block in enumerate(blocks):
        cls = SIZE_CLASSES[i]
        if i >= len(blocks) - BREAK_BEFORE:
            parts.append("<br>")
        elif parts:
            parts.append('<span class="sep">&middot;</span>')
        inner = []
        for slot in block:
            inner.append('<span class="%s s%d">%s</span>'
                         % (cls, slot["stage"], act_link(slot, esc(name_for(slot, "short")), day)))
        parts.append('<span class="sep">&middot;</span>'.join(inner))
    return "".join(parts)


def render_stage(day, stage):
    """One timeline column: time-ordered list items, favourites flagged."""
    rows = []
    for slot in sorted((s for s in day["slots"] if s["stage"] == stage),
                       key=lambda s: time_key(s["time"])):
        cls = ' class="fav"' if slot["favorite"] else ""
        rows.append('          <li%s>%s<span class="t">%s</span></li>'
                    % (cls, act_link(slot, esc(name_for(slot, "medium")), day), slot["time"]))
    return "\n" + "\n".join(rows) + "\n        "


def headline(day):
    """(closer, [co-headliners]) - positional, in canonical form.

    The closer is the main stage's last slot. The co-headliners are the other
    three favourites, ordered main second-to-last, second stage last, second
    stage second-to-last - which is how the hand-written posters read.
    """
    main = sorted((s for s in day["slots"] if s["stage"] == 1), key=lambda s: time_key(s["time"]))
    second = sorted((s for s in day["slots"] if s["stage"] == 2), key=lambda s: time_key(s["time"]))
    if len(main) < 2 or len(second) < 2:
        raise SystemExit("FATAL: day %d has too few slots to derive a headline"
                         % day["number"])
    return main[-1], [main[-2], second[-1], second[-2]]


def render(kind, doc):
    tpl_path, _ = TARGETS[kind]
    out = tpl_path.read_text(encoding="utf-8")

    anchor = '<html lang="en">\n'
    if anchor not in out:
        raise SystemExit("FATAL: %s has no `%s` line to anchor the banner to"
                         % (tpl_path.name, anchor.strip()))
    out = out.replace(anchor, anchor + BANNER % tpl_path.name, 1)

    for day in doc["days"]:
        n = day["number"]
        out = out.replace("{{DAY%d_NAME}}" % n, esc(day["name"]))
        if kind == "crescendo":
            out = out.replace("{{DAY%d_BILL}}" % n, render_bill(day))
        else:
            closer, co = headline(day)
            out = out.replace("{{DAY%d_CLOSER}}" % n,
                              act_link(closer, esc(name_for(closer, "canonical")), day, "closer"))
            out = out.replace(
                "{{DAY%d_CO}}" % n,
                ' <span class="dot">&#9733;</span> '.join(
                    act_link(s, esc(name_for(s, "canonical")), day, "co-headliner") for s in co))
            out = out.replace("{{DAY%d_STAGE1}}" % n, render_stage(day, 1))
            out = out.replace("{{DAY%d_STAGE2}}" % n, render_stage(day, 2))

    left = re.findall(r"\{\{[A-Z0-9_]+\}\}", out)
    if left:
        raise SystemExit("FATAL: unfilled placeholder(s) in the %s template: %s"
                         % (kind, ", ".join(sorted(set(left)))))
    return out


def main():
    try:
        import signal
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    except (ImportError, AttributeError, ValueError):
        pass

    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--lineup", help="override the lineup.json path")
    ap.add_argument("--check", action="store_true",
                    help="exit 3 if a committed poster differs from what the "
                         "template would produce; writes nothing")
    ap.add_argument("--diff", action="store_true",
                    help="show the difference and write nothing")
    args = ap.parse_args()

    src = Path(args.lineup) if args.lineup else LINEUP
    if not src.exists():
        raise SystemExit("FATAL: %s not found - run build_lineup.py first" % src)
    doc = json.loads(src.read_text(encoding="utf-8"))

    stale, wrote = [], []
    for kind, (tpl, target) in TARGETS.items():
        if not tpl.exists():
            raise SystemExit("FATAL: missing template %s" % tpl)
        new = render(kind, doc)
        current = target.read_text(encoding="utf-8") if target.exists() else None

        if args.diff:
            import difflib
            d = list(difflib.unified_diff((current or "").splitlines(True),
                                          new.splitlines(True),
                                          str(target), "rendered"))
            sys.stdout.writelines(d or ["%s: no change\n" % target.name])
            continue
        if args.check:
            if current != new:
                stale.append(target)
            continue
        if current != new:
            target.write_text(new, encoding="utf-8")
            wrote.append(target)

    if args.diff:
        return 0
    if args.check:
        for t in stale:
            print("FATAL: %s is stale - re-run render_posters.py" % t, file=sys.stderr)
        if stale:
            return 3
        print("OK - both posters match the templates and lineup.json")
        return 0

    if wrote:
        for t in wrote:
            print("wrote %s" % t)
    else:
        print("no change - both posters already current")
    return 0


if __name__ == "__main__":
    sys.exit(main())
