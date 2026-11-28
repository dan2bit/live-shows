#!/usr/bin/env python3
"""The items ledger: everything owned from artists, and who signed it.

Two hand-kept files, both plain tab-joined TSV with `-` for an empty cell:

    data/items.tsv                         one row per thing owned
    data/show_goals/item_signatures.tsv    one row per signature on an item

An item's number (item_id) is permanent. New items are appended with the next
number; a row is never renumbered or reused, because photo links, issue
comments (`item=73`) and the photo crosswalk all name items by number.

items.tsv columns
    item_id        permanent number
    artist         the act the item belongs to (the band, for a member's item)
    title          release or item name; `-` for a bare pick or setlist
    kind           cd, vinyl, digital-album, digital-track, poster, shirt,
                   setlist, pick, print, other
    acquired       show, vip, mail, crowdfund, bandcamp, download, raffle,
                   gift, own (the owner's own photo, printed), or `-` if unknown
    paid           Y, N or ? - whether it was paid for (a VIP bundle item is Y)
    acquired_date  YYYY, YYYY-MM or YYYY-MM-DD, as precisely as is known
    venue          where it was acquired, when that was a show
    status         received, or pending for an order not yet arrived
    photo_ref      share link to the item's photo
    source_key     `bandcamp:<type>:<id>` for a Bandcamp purchase, else `-`
    notes          provenance and context; names only, never prices or orders

item_signatures.tsv columns
    item_id, signer, attribution (`of <band>` for a member, else `-`),
    show_date, venue, photo_ref (a close-up of the signature, optional),
    legible, confidence (high, medium, low), notes

    python3 tools/items/ledger.py check
    python3 tools/items/ledger.py needs-photo [--signed] [--since DATE] [--kind K] [--markdown]
    python3 tools/items/ledger.py show 73
    python3 tools/items/ledger.py set-photo 73 https://photos.../share/KEY
    python3 tools/items/ledger.py add --artist "Eric Johanson" --kind cd --title "Open Bayou" \\
        --acquired show --paid Y --date 2026-10-20 --venue "Hamilton Live"
    python3 tools/items/ledger.py sign 80 --signer "Eric Johanson" --date 2026-10-20 \\
        --venue "Hamilton Live" --confidence high
    python3 tools/items/ledger.py import-bandcamp

needs-photo lists physical items only: a download has nothing to photograph.
import-bandcamp appends every owned row of the Bandcamp export that the ledger
does not hold yet, matched on Bandcamp's own catalogue id, and never removes
or renumbers anything.

Every write command validates the result before saving, so a file that would
fail `check` is never written. Editing the two files by hand is also fine;
run `check` afterwards.
"""
import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ITEMS = REPO_ROOT / "data" / "items.tsv"
SIGNATURES = REPO_ROOT / "data" / "show_goals" / "item_signatures.tsv"
BANDCAMP = REPO_ROOT / "tools" / "research" / "follows" / "dan2bit-bandcamp-collection.tsv"

ITEM_COLS = ["item_id", "artist", "title", "kind", "acquired", "paid", "acquired_date",
             "venue", "status", "photo_ref", "source_key", "notes"]
SIG_COLS = ["item_id", "signer", "attribution", "show_date", "venue",
            "photo_ref", "legible", "confidence", "notes"]

KINDS = ("cd", "vinyl", "digital-album", "digital-track", "poster", "shirt",
         "setlist", "pick", "print", "other")
DIGITAL_KINDS = ("digital-album", "digital-track")
ACQUIRED = ("show", "vip", "mail", "crowdfund", "bandcamp", "download", "raffle", "gift", "own", "")
PAID = ("Y", "N", "?")
STATUS = ("received", "pending")
CONFIDENCE = ("high", "medium", "low", "")
# Ledger kind -> the memorabilia/ leaf the photo library tags it with.
SUBTYPE_OF = {"cd": "cd", "vinyl": "vinyl", "poster": "poster", "setlist": "setlist",
              "pick": "pick", "print": "photo-print"}
DATE = re.compile(r"^(?:\d{4}(?:-\d{2}(?:-\d{2})?)?)?$")
ISO_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# Typographic punctuation that must be typed as its ASCII form in data files.
FANCY = re.compile("[‘’“”–—… ]")


# ── reading and writing ────────────────────────────────────────────────────

def _read(path, cols, problems=None):
    """Rows as dicts with `-` read as "". Shape problems are appended to
    `problems` when given, else they stop the run."""
    name = str(path.relative_to(REPO_ROOT))
    found = []
    text = path.read_text(encoding="utf-8")
    if "\r" in text:
        found.append("%s: has CR line endings; LF only" % name)
    if not text.endswith("\n") or text.endswith("\n\n"):
        found.append("%s: must end with exactly one newline" % name)
    lines = text.rstrip("\n").split("\n")
    if lines[0].split("\t") != cols:
        found.append("%s: header must be %s" % (name, " | ".join(cols)))
    rows = []
    for n, line in enumerate(lines[1:], start=2):
        cells = line.split("\t")
        if len(cells) != len(cols):
            found.append("%s line %d: %d cells, expected %d" % (name, n, len(cells), len(cols)))
            continue
        if any(c == "" or c != c.strip() for c in cells):
            found.append("%s line %d: an empty cell is `-`, and no cell has edge spaces" % (name, n))
        if FANCY.search(line):
            found.append("%s line %d: typographic quote or dash; use ASCII punctuation" % (name, n))
        row = {c: ("" if v.strip() == "-" else v.strip()) for c, v in zip(cols, cells)}
        row["_line"] = n
        rows.append(row)
    if problems is None:
        if found:
            sys.exit("\n".join(found))
    else:
        problems.extend(found)
    return rows


def _render(rows, cols):
    lines = ["\t".join(cols)]
    for r in rows:
        lines.append("\t".join((r.get(c) or "-").replace("\t", " ").strip() or "-" for c in cols))
    return "\n".join(lines) + "\n"


def load_items():
    return _read(ITEMS, ITEM_COLS)


def load_signatures():
    """{item_id: [signature rows]} in file order."""
    by_item = {}
    for r in _read(SIGNATURES, SIG_COLS):
        by_item.setdefault(r["item_id"], []).append(r)
    return by_item


def get_item(item_id):
    item_id = str(item_id).strip()
    for it in load_items():
        if it["item_id"] == item_id:
            return it
    sys.exit("no item %s in %s" % (item_id, ITEMS.relative_to(REPO_ROOT)))


def validate(items=None, sigs=None):
    """Every problem with the two files (or with the rows given), as text."""
    problems = []
    if items is None:
        items = _read(ITEMS, ITEM_COLS, problems)
    if sigs is None:
        sigs = _read(SIGNATURES, SIG_COLS, problems)
    seen, last, keys = set(), 0, {}
    for it in items:
        where = "items.tsv item %s" % (it["item_id"] or "?")
        if not it["item_id"].isdigit() or int(it["item_id"]) < 1:
            problems.append("%s: item_id must be a positive whole number" % where)
            continue
        num = int(it["item_id"])
        if it["item_id"] in seen:
            problems.append("%s: number used twice" % where)
        if num <= last:
            problems.append("%s: rows must stay in ascending number order" % where)
        seen.add(it["item_id"])
        last = max(last, num)
        if not it["artist"]:
            problems.append("%s: artist is required" % where)
        if it["kind"] not in KINDS:
            problems.append("%s: kind must be one of %s" % (where, ", ".join(KINDS)))
        if it["acquired"] not in ACQUIRED:
            problems.append("%s: acquired must be one of %s" % (where, ", ".join(a for a in ACQUIRED if a)))
        if it["paid"] not in PAID:
            problems.append("%s: paid must be Y, N or ?" % where)
        if not DATE.match(it["acquired_date"]):
            problems.append("%s: acquired_date is YYYY, YYYY-MM or YYYY-MM-DD" % where)
        if it["status"] not in STATUS:
            problems.append("%s: status must be received or pending" % where)
        if it["photo_ref"] and not it["photo_ref"].startswith("https://"):
            problems.append("%s: photo_ref must be an https link" % where)
        if it["source_key"]:
            if it["source_key"] in keys:
                problems.append("%s: source_key already on item %s" % (where, keys[it["source_key"]]))
            keys[it["source_key"]] = it["item_id"]
    for sg in sigs:
        where = "item_signatures.tsv, item %s signer %s" % (sg["item_id"] or "?", sg["signer"] or "?")
        if sg["item_id"] not in seen:
            problems.append("%s: no such item" % where)
        if not sg["signer"]:
            problems.append("%s: signer is required" % where)
        if sg["attribution"] and not sg["attribution"].startswith("of "):
            problems.append("%s: attribution is `of <band>` or blank" % where)
        if not DATE.match(sg["show_date"]):
            problems.append("%s: show_date is YYYY, YYYY-MM or YYYY-MM-DD" % where)
        if sg["confidence"] not in CONFIDENCE:
            problems.append("%s: confidence must be high, medium or low" % where)
        if sg["photo_ref"] and not sg["photo_ref"].startswith("https://"):
            problems.append("%s: photo_ref must be an https link" % where)
    return problems


def _save(items, sigs):
    """Write both files, refusing a result that would fail `check`."""
    problems = validate(items, sigs)
    if problems:
        sys.exit("not saved:\n" + "\n".join(problems))
    for path, text in ((ITEMS, _render(items, ITEM_COLS)),
                       (SIGNATURES, _render(sigs, SIG_COLS))):
        # open() rather than Path.write_text(): its newline argument needs
        # Python 3.10, and a local checkout may run an older interpreter
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)


def _all():
    return _read(ITEMS, ITEM_COLS), _read(SIGNATURES, SIG_COLS)


# ── questions other tools ask ──────────────────────────────────────────────

def photo_plan(item_id):
    """What the photo library needs to know to file a picture of this item:
    {"show", "artist", "subtype", "signed", "signers"}. `show` is the night the
    item belongs to - where it was last signed, else the show it was acquired
    at - or "" for something that never passed through a show (a mail order)."""
    it = get_item(item_id)
    sigs = load_signatures().get(it["item_id"], [])
    signed_days = sorted(s["show_date"] for s in sigs if ISO_DAY.match(s["show_date"]))
    show = signed_days[-1] if signed_days else ""
    if not show and it["venue"] and ISO_DAY.match(it["acquired_date"]):
        show = it["acquired_date"]
    return {"show": show, "artist": it["artist"], "signed": bool(sigs),
            "signers": [s["signer"] for s in sigs],
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
        mine = sigs.get(it["item_id"], [])
        if signed_only and not mine:
            continue
        days = sorted(s["show_date"] for s in mine if ISO_DAY.match(s["show_date"]))
        when = days[-1] if days else it["acquired_date"]
        if since and (when or "") < since:
            continue
        out.append(dict(it, when=when, signers=[s["signer"] for s in mine]))
    out.sort(key=lambda r: (r["when"] or "", int(r["item_id"])), reverse=True)
    return out


# ── writes ─────────────────────────────────────────────────────────────────

def set_item_photo(item_id, url):
    """Record `url` as the item's photo. Returns a one-line summary."""
    url = (url or "").strip()
    if not re.match(r"^https://\S+$", url):
        sys.exit("a photo link must be an https URL, got %r" % url)
    items, sigs = _all()
    hit = [it for it in items if it["item_id"] == str(item_id).strip()]
    if not hit:
        sys.exit("no item %s in %s" % (item_id, ITEMS.relative_to(REPO_ROOT)))
    hit[0]["photo_ref"] = url
    _save(items, sigs)
    return "item %s (%s - %s) photo recorded" % (
        hit[0]["item_id"], hit[0]["artist"], hit[0]["title"] or hit[0]["kind"])


def add_item(artist, kind, title="", acquired="", paid="?", date="", venue="",
             status="received", photo="", source_key="", notes=""):
    """Append an item with the next number and return that number."""
    items, sigs = _all()
    new_id = str(max([int(it["item_id"]) for it in items] or [0]) + 1)
    items.append({"item_id": new_id, "artist": artist, "title": title, "kind": kind,
                  "acquired": acquired, "paid": paid, "acquired_date": date, "venue": venue,
                  "status": status, "photo_ref": photo, "source_key": source_key, "notes": notes})
    _save(items, sigs)
    return new_id


def add_signature(item_id, signer, attribution="", date="", venue="", photo="",
                  legible="", confidence="high", notes=""):
    """Append a signature to an item. The same signer twice on one item is refused."""
    items, sigs = _all()
    item_id = str(item_id).strip()
    if any(s["item_id"] == item_id and s["signer"].lower() == signer.strip().lower() for s in sigs):
        sys.exit("item %s already has a signature by %s" % (item_id, signer))
    row = {"item_id": item_id, "signer": signer, "attribution": attribution, "show_date": date,
           "venue": venue, "photo_ref": photo, "legible": legible, "confidence": confidence,
           "notes": notes}
    # Keep an item's signatures together: after its last one, else in item order.
    at = max([i for i, s in enumerate(sigs) if s["item_id"] == item_id], default=None)
    if at is None:
        at = max([i for i, s in enumerate(sigs)
                  if s["item_id"].isdigit() and int(s["item_id"]) < int(item_id or 0)], default=-1)
    sigs.insert(at + 1, row)
    _save(items, sigs)


def import_bandcamp(dry_run=False):
    """Append owned Bandcamp rows the ledger lacks. Returns (added, missing):
    the new items, and ledger items whose key is no longer in the export."""
    lines = BANDCAMP.read_text(encoding="utf-8").rstrip("\n").split("\n")
    header = lines[0].split("\t")
    rows = [dict(zip(header, ln.split("\t"))) for ln in lines[1:] if ln]
    items, sigs = _all()
    have = {it["source_key"] for it in items if it["source_key"]}
    next_id = max([int(it["item_id"]) for it in items] or [0]) + 1
    added, exported = [], set()
    for r in rows:
        if (r.get("Source") or "").strip().lower() != "collection":
            continue
        key = (r.get("Key") or "").strip()
        if not key or key == "-":
            sys.exit("bandcamp export: %s / %s has no Key - re-run the export" % (r.get("Artist"), r.get("Item")))
        key = "bandcamp:%s" % key
        exported.add(key)
        if key in have:
            continue
        item_type = (r.get("Item Type") or "").strip().lower()
        notes = [n for n in ((r.get("Note") or "").strip(),) if n and n != "-"]
        if item_type == "package":
            notes.append("Bandcamp merch package (physical item)")
        it = {"item_id": str(next_id), "artist": r["Artist"].strip(), "title": r["Item"].strip(),
              "kind": {"album": "digital-album", "track": "digital-track"}.get(item_type, "other"),
              "acquired": "bandcamp", "paid": "Y", "acquired_date": "", "venue": "",
              "status": "received", "photo_ref": "", "source_key": key, "notes": "; ".join(notes)}
        items.append(it)
        added.append(it)
        have.add(key)
        next_id += 1
    missing = [it for it in items if it["source_key"].startswith("bandcamp:")
               and it["source_key"] not in exported]
    if added and not dry_run:
        _save(items, sigs)
    return added, missing


# ── command line ───────────────────────────────────────────────────────────

def _label(it):
    return "%s %s" % (it["kind"], it["title"]) if it["title"] else it["kind"]


def main():
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="validate both files; exit 1 on any problem")
    p = sub.add_parser("needs-photo", help="received physical items with no photo link")
    p.add_argument("--since", metavar="DATE", help="only items from this night on (YYYY-MM-DD)")
    p.add_argument("--kind", action="append", help="only this kind; repeatable")
    p.add_argument("--signed", action="store_true", help="only signed items")
    p.add_argument("--markdown", action="store_true", help="a checklist to paste into an issue")
    p = sub.add_parser("show", help="one item and its signatures")
    p.add_argument("item")
    p = sub.add_parser("set-photo", help="record a photo link on an item")
    p.add_argument("item")
    p.add_argument("url")
    p = sub.add_parser("add", help="append an item with the next number")
    p.add_argument("--artist", required=True)
    p.add_argument("--kind", required=True, choices=KINDS)
    p.add_argument("--title", default="")
    p.add_argument("--acquired", default="", choices=ACQUIRED)
    p.add_argument("--paid", default="?", choices=PAID)
    p.add_argument("--date", default="", help="YYYY, YYYY-MM or YYYY-MM-DD")
    p.add_argument("--venue", default="")
    p.add_argument("--status", default="received", choices=STATUS)
    p.add_argument("--photo", default="")
    p.add_argument("--notes", default="")
    p = sub.add_parser("sign", help="append a signature to an item")
    p.add_argument("item")
    p.add_argument("--signer", required=True)
    p.add_argument("--attribution", default="", help="`of <band>` for a band member")
    p.add_argument("--date", default="")
    p.add_argument("--venue", default="")
    p.add_argument("--photo", default="")
    p.add_argument("--legible", default="")
    p.add_argument("--confidence", default="high", choices=[c for c in CONFIDENCE if c])
    p.add_argument("--notes", default="")
    p = sub.add_parser("import-bandcamp", help="append owned Bandcamp rows the ledger lacks")
    p.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.cmd == "check":
        problems = validate()
        if problems:
            sys.exit("\n".join(problems))
        items, sigs = _all()
        print("items ledger: %d items, %d signatures, clean." % (len(items), len(sigs)))
    elif args.cmd == "needs-photo":
        rows = needs_photo(args.since, args.kind, args.signed)
        for r in rows:
            if args.markdown:
                by = " - signed by %s" % ", ".join(r["signers"]) if r["signers"] else ""
                print("- [ ] item %s: %s, %s (%s)%s" % (r["item_id"], r["artist"], _label(r),
                                                       r["when"] or "no date", by))
            else:
                print("%4s  %-10s  %-28s  %-36s  %s" % (
                    r["item_id"], r["when"] or "-", r["artist"][:28], _label(r)[:36],
                    "signed x%d" % len(r["signers"]) if r["signers"] else ""))
        print("%d item(s) need a photo." % len(rows), file=sys.stderr)
    elif args.cmd == "show":
        it = get_item(args.item)
        for k in ITEM_COLS:
            print("%-14s %s" % (k, it[k] or "-"))
        for s in load_signatures().get(it["item_id"], []):
            print("  signed by %s %s  %s %s" % (s["signer"], s["attribution"], s["show_date"] or "-",
                                               s["venue"]))
    elif args.cmd == "set-photo":
        print(set_item_photo(args.item, args.url))
    elif args.cmd == "add":
        new_id = add_item(args.artist, args.kind, args.title, args.acquired, args.paid, args.date,
                          args.venue, args.status, args.photo, "", args.notes)
        print("added item %s" % new_id)
    elif args.cmd == "sign":
        add_signature(args.item, args.signer, args.attribution, args.date, args.venue,
                      args.photo, args.legible, args.confidence, args.notes)
        print("signature by %s added to item %s" % (args.signer, args.item))
    else:
        added, missing = import_bandcamp(args.dry_run)
        for it in added:
            print("%s item %s: %s - %s" % ("would add" if args.dry_run else "added",
                                          it["item_id"], it["artist"], it["title"]))
        for it in missing:
            print("NOTE: item %s (%s - %s) is no longer in the Bandcamp export; left in place"
                  % (it["item_id"], it["artist"], it["title"]))
        print("%d new Bandcamp item(s)." % len(added))


if __name__ == "__main__":
    main()
