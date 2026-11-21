#!/usr/bin/env python3
"""Read the items ledger, list what still needs a photo, and record a photo link.

The ledger is data/items.tsv (one row per thing owned) with
data/show_goals/item_signatures.tsv (one row per signature). This module is the
one place other tools ask "what is item N?" and "which items have no photo?",
so the photo tooling never parses those files itself.

    python3 tools/items/ledger.py needs-photo             # the photo backlog
    python3 tools/items/ledger.py needs-photo --signed    # signed things only
    python3 tools/items/ledger.py needs-photo --since 2026-01-01 --markdown
    python3 tools/items/ledger.py show 73                 # one item, with its signatures
    python3 tools/items/ledger.py set-photo 73 https://photos.../share/KEY

needs-photo lists physical items only: a download has nothing to photograph.

set-photo writes the link where the item's row comes from, then rebuilds the
ledger. While items.tsv is still built from the older files that means the item
log's photo_ref column for an item that came from the item log, and a row in
tools/items/overrides.tsv for everything else. Callers only ever name the item.
"""
import argparse
import csv
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import convert_item_log as builder  # noqa: E402

REPO_ROOT = builder.REPO_ROOT
DIGITAL_KINDS = ("digital-album", "digital-track")
# Ledger kind -> the memorabilia/ leaf the photo library tags it with.
SUBTYPE_OF = {"cd": "cd", "vinyl": "vinyl", "poster": "poster", "setlist": "setlist",
              "pick": "pick", "print": "photo-print"}
ISO_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PHOTO_TBD = re.compile(r"(?:;\s*)?\bphoto TBD\b", re.I)


def _read(path):
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE))
    for r in rows:
        for k, v in r.items():
            if v == "-":
                r[k] = ""
    return rows


def load_items():
    return _read(builder.ITEMS_OUT)


def load_signatures():
    """{item_id: [signature rows]} in file order."""
    by_item = {}
    for r in _read(builder.SIGS_OUT):
        by_item.setdefault(r["item_id"], []).append(r)
    return by_item


def get_item(item_id):
    item_id = str(item_id).strip()
    for it in load_items():
        if it["item_id"] == item_id:
            return it
    sys.exit("no item %s in %s" % (item_id, builder.ITEMS_OUT.relative_to(REPO_ROOT)))


def photo_plan(item_id):
    """What the photo library needs to know to file a picture of this item:
    {"show", "artist", "subtype", "signed"}. `show` is the night the item belongs
    to - where it was last signed, else the show it was acquired at - or "" for
    something that never passed through a show (a mail order)."""
    it = get_item(item_id)
    sigs = load_signatures().get(it["item_id"], [])
    signed_days = sorted(s["show_date"] for s in sigs if ISO_DAY.match(s["show_date"] or ""))
    show = signed_days[-1] if signed_days else ""
    if not show and it["venue"] and ISO_DAY.match(it["acquired_date"] or ""):
        show = it["acquired_date"]
    return {"show": show, "artist": it["artist"], "signed": bool(sigs),
            "subtype": SUBTYPE_OF.get(it["kind"], "other")}


def needs_photo(since=None, kinds=None, signed_only=False):
    """Received physical items with no photo link, newest night first."""
    sigs = load_signatures()
    out = []
    for it in load_items():
        if it["photo_ref"] or it["kind"] in DIGITAL_KINDS or it["status"] != "received":
            continue
        if kinds and it["kind"] not in kinds:
            continue
        signers = [s["signer"] for s in sigs.get(it["item_id"], [])]
        if signed_only and not signers:
            continue
        when = photo_plan(it["item_id"])["show"] or it["acquired_date"]
        if since and (when or "") < since:
            continue
        out.append(dict(it, when=when, signers=signers))
    out.sort(key=lambda r: (r["when"] or "", int(r["item_id"])), reverse=True)
    return out


def _item_key(item_id):
    """The builder's source key for an item (`log:N`, `purchase:...`, `bandcamp:...`)."""
    items, _sigs = builder.build()
    for it in items:
        if it["item_id"] == str(item_id).strip():
            return it["_key"]
    sys.exit("no item %s in a fresh build of the ledger" % item_id)


def _set_item_log_photo(lead_seq, url):
    """Write `url` into the item log row that starts the item, and drop the
    "photo TBD" marker from every row of that item."""
    path = builder.ITEM_LOG
    lines = path.read_text(encoding="utf-8").split("\n")
    header = lines[0].split("\t")
    seq_i, photo_i, notes_i = header.index("seq"), header.index("photo_ref"), header.index("notes")
    same = re.compile(r"same item as seq %d\b" % lead_seq, re.I)
    found = False
    for n, line in enumerate(lines[1:], start=1):
        if not line:
            continue
        cells = line.split("\t")
        cells += [""] * (len(header) - len(cells))
        is_lead = cells[seq_i].strip() == str(lead_seq)
        if not (is_lead or same.search(cells[notes_i])):
            continue
        if is_lead:
            cells[photo_i] = url
            found = True
        cells[notes_i] = PHOTO_TBD.sub("", cells[notes_i]).strip().strip(";").strip()
        lines[n] = "\t".join(cells)
    if not found:
        sys.exit("item log has no row with seq %d" % lead_seq)
    path.write_text("\n".join(lines), encoding="utf-8", newline="")


def _set_override_photo(key, url):
    path = builder.OVERRIDES
    lines = path.read_text(encoding="utf-8").split("\n") if path.is_file() else ["key\ttarget\tfield\tvalue\treason"]
    row = "\t".join([key, "item", "photo_ref", url, "photo filed"])
    kept = [ln for ln in lines if ln.split("\t")[:3] != [key, "item", "photo_ref"] and ln != ""]
    path.write_text("\n".join(kept + [row]) + "\n", encoding="utf-8", newline="")


def set_item_photo(item_id, url):
    """Record `url` as the item's photo and rebuild the ledger. Returns a one-line
    summary. Refuses anything that is not an https link."""
    url = (url or "").strip()
    if not re.match(r"^https://\S+$", url):
        sys.exit("a photo link must be an https URL, got %r" % url)
    it = get_item(item_id)
    key = _item_key(item_id)
    if key.startswith("log:"):
        _set_item_log_photo(int(key.split(":", 1)[1]), url)
        where = "item_log.tsv"
    else:
        _set_override_photo(key, url)
        where = "tools/items/overrides.tsv"
    items, sigs = builder.build()
    builder.ITEMS_OUT.write_text(builder.render(items, builder.ITEM_COLS), encoding="utf-8", newline="")
    builder.SIGS_OUT.write_text(builder.render(sigs, builder.SIG_COLS), encoding="utf-8", newline="")
    return "item %s (%s - %s) photo recorded in %s; ledger rebuilt" % (
        it["item_id"], it["artist"], it["title"] or it["kind"], where)


def _label(it):
    title = it["title"] or ""
    return "%s %s" % (it["kind"], title) if title else it["kind"]


def main():
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("needs-photo", help="received physical items with no photo link")
    p.add_argument("--since", metavar="DATE", help="only items from this night on (YYYY-MM-DD)")
    p.add_argument("--kind", action="append", help="only this kind; repeatable")
    p.add_argument("--signed", action="store_true", help="only signed items")
    p.add_argument("--markdown", action="store_true", help="a checklist to paste into an issue")
    p = sub.add_parser("show", help="one item and its signatures")
    p.add_argument("item")
    p = sub.add_parser("set-photo", help="record a photo link on an item and rebuild the ledger")
    p.add_argument("item")
    p.add_argument("url")
    args = ap.parse_args()

    if args.cmd == "needs-photo":
        rows = needs_photo(args.since, args.kind, args.signed)
        if args.markdown:
            for r in rows:
                by = " - signed by %s" % ", ".join(r["signers"]) if r["signers"] else ""
                print("- [ ] item %s: %s, %s (%s)%s" % (r["item_id"], r["artist"], _label(r),
                                                       r["when"] or "no date", by))
        else:
            for r in rows:
                print("%4s  %-10s  %-28s  %-36s  %s" % (
                    r["item_id"], r["when"] or "-", r["artist"][:28], _label(r)[:36],
                    "signed x%d" % len(r["signers"]) if r["signers"] else ""))
        print("%d item(s) need a photo." % len(rows), file=sys.stderr)
    elif args.cmd == "show":
        it = get_item(args.item)
        for k in builder.ITEM_COLS:
            print("%-14s %s" % (k, it[k] or "-"))
        for s in load_signatures().get(it["item_id"], []):
            print("  signed by %s %s  %s %s" % (s["signer"], s["attribution"], s["show_date"] or "-",
                                               s["venue"] or ""))
        print("photo plan     %s" % photo_plan(args.item))
    else:
        print(set_item_photo(args.item, args.url))


if __name__ == "__main__":
    main()
