#!/usr/bin/env python3
"""One-time converter: item_log.tsv + music_purchases.tsv -> the items ledger.

The item log records one row per SIGNER, so a CD signed by three people is
three rows and "what do I own" has to be rebuilt by grouping. The purchases
ledger holds the things that had no show to hang on. This writes the two files
that replace both:

  data/items.tsv                        one row per thing owned
  data/show_goals/item_signatures.tsv   one row per signature on a thing

Grouping follows the item log's own convention: a row whose notes say
"same item as seq N" belongs to the item that row N started; every other row
starts a new item. That is what keeps three separately personalized posters
from one night as three items.

Two dates are kept apart. An item's show_date / venue say where it was
ACQUIRED; a signature's show_date / venue say where it was SIGNED. The item
log only ever recorded the signing, so the converter copies it to both and the
reviewer corrects the items that were bought elsewhere and signed later.

`paid` is Y, N or ? - a ? is a question for the reviewer (was this poster
bought, or handed over with a VIP package?), and no ? may remain when the
ledger goes live.

Bandcamp purchases are not converted here. They arrive through their own
import from a scraped snapshot that carries a stable catalogue key.

Deterministic: the same inputs give byte-identical outputs.

    python3 tools/items/convert_item_log.py            # write both files
    python3 tools/items/convert_item_log.py --check    # exit 1 if they differ
    python3 tools/items/convert_item_log.py --report   # review lists only
"""
import argparse
import csv
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ITEM_LOG = REPO_ROOT / "data" / "show_goals" / "item_log.tsv"
PURCHASES = REPO_ROOT / "tools" / "research" / "follows" / "music_purchases.tsv"
ITEMS_OUT = REPO_ROOT / "data" / "items.tsv"
SIGS_OUT = REPO_ROOT / "data" / "show_goals" / "item_signatures.tsv"

ITEM_COLS = ["item_id", "artist", "title", "kind", "acquired", "paid", "show_date",
             "venue", "status", "photo_ref", "source_key", "notes"]
SIG_COLS = ["item_id", "seq", "signer", "attribution", "show_date", "venue",
            "photo_ref", "legible", "confidence", "notes"]

SAME_ITEM = re.compile(r"same item as seq (\d+)", re.I)
# Bookkeeping phrases that described the old one-row-per-signer shape.
BOILERPLATE = [
    re.compile(r"\bphoto TBD\b", re.I),
    re.compile(r"same item as seq \d+", re.I),
    re.compile(r"\b(?:two|three|four|five|six)-signer (?:CD|poster|item), one row per signer\b", re.I),
]
KIND_OF = [
    (re.compile(r"^cd\b", re.I), "cd"),
    (re.compile(r"^vinyl\b", re.I), "vinyl"),
    (re.compile(r"^poster\b", re.I), "poster"),
    (re.compile(r"^t-?shirt\b", re.I), "shirt"),
    (re.compile(r"^setlist\b", re.I), "setlist"),
    (re.compile(r"^pick\b", re.I), "pick"),
    (re.compile(r"print\b", re.I), "print"),
]
PAID_BY_KIND = {"cd": "Y", "vinyl": "Y", "shirt": "Y", "setlist": "N", "pick": "N",
                "print": "N", "poster": "?", "other": "?"}


def load(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE))


def clean_notes(text):
    """Notes with the old bookkeeping phrases removed and separators tidied."""
    text = text or ""
    for pat in BOILERPLATE:
        text = pat.sub("", text)
    parts = [p.strip() for p in text.split(";")]
    return "; ".join(p for p in parts if p)


def split_item(item):
    """'CD (Open Bayou)' -> ('cd', 'Open Bayou'); 'pick' -> ('pick', '-')."""
    item = (item or "").strip()
    m = re.match(r"^(.*?)\s*\((.*)\)\s*$", item)
    head, detail = (m.group(1), m.group(2)) if m else (item, "")
    kind = next((k for pat, k in KIND_OF if pat.search(head)), "other")
    if kind in ("cd", "vinyl"):
        title = re.sub(r"\s+LP$", "", detail) if kind == "vinyl" else detail
    elif kind == "other":
        title = item  # nothing to split off: "photo magnet (raffle prize)" reads best whole
    else:
        title = detail if detail else (head if kind == "print" else "")
    return kind, (title or "-")


def credited_artist(first):
    """The act an item belongs to: the band for a member's signature, else the signer."""
    attribution = (first.get("attribution") or "").strip()
    m = re.match(r"^of\s+(.+)$", attribution, re.I)
    if not m:
        return first["signer"].strip()
    band = m.group(1).strip()
    # "of Jax Hollow band" / "of Judith Hill's band" name the leader's own act.
    band = re.sub(r"(?:'s)?\s+band$", "", band, flags=re.I)
    return band


def acquired_and_paid(kind, item_text, notes):
    text = "%s %s" % (item_text, notes)
    if re.search(r"\braffle\b", text, re.I):
        return "raffle", "N"
    if re.search(r"\bacquired by\b|\bcourtesy\b|\bgift from\b", text, re.I):
        return "gift", "N"
    paid = PAID_BY_KIND[kind]
    # Anything that came inside a VIP package was not bought as its own item.
    # (A CD carried to a VIP meet and greet to be signed is still a bought CD.)
    if re.search(r"\bVIP (?:package|bundle|perk|poster|attendees)\b", text, re.I) and paid != "N":
        paid = "?"
    return "show", paid


def build():
    log = load(ITEM_LOG)
    by_seq = {int(r["seq"]): r for r in log}
    groups, leader_of = {}, {}
    for r in sorted(log, key=lambda x: int(x["seq"])):
        seq = int(r["seq"])
        m = SAME_ITEM.search(r.get("notes") or "")
        lead = int(m.group(1)) if m else seq
        if lead not in by_seq:
            sys.exit("item_log seq %d points at seq %d, which does not exist." % (seq, lead))
        lead = leader_of.get(lead, lead)  # a pointer at a follower resolves to its leader
        leader_of[seq] = lead
        groups.setdefault(lead, []).append(r)

    items, sigs = [], []
    for item_id, lead in enumerate(sorted(groups), start=1):
        rows = groups[lead]
        first = rows[0]
        kind, title = split_item(first["item"])
        acquired, paid = acquired_and_paid(kind, first["item"], first.get("notes") or "")
        photo = next((r["photo_ref"].strip() for r in rows if (r.get("photo_ref") or "").strip()), "")
        items.append({
            "item_id": str(item_id), "artist": credited_artist(first), "title": title, "kind": kind,
            "acquired": acquired, "paid": paid, "show_date": first["show_date"], "venue": first["venue"],
            "status": "received", "photo_ref": photo, "source_key": "",
            "notes": clean_notes(first.get("notes")),
        })
        for i, r in enumerate(rows):
            if r["signed"].strip().upper() != "Y":
                continue
            sigs.append({
                "item_id": str(item_id), "seq": r["seq"], "signer": r["signer"].strip(),
                "attribution": (r.get("attribution") or "").strip(), "show_date": r["show_date"],
                "venue": r["venue"], "photo_ref": "", "legible": (r.get("legible") or "").strip(),
                "confidence": (r.get("confidence") or "").strip(),
                # The first row's notes describe the item and live there.
                "notes": "" if i == 0 else clean_notes(r.get("notes")),
            })

    next_id = len(items) + 1
    for r in load(PURCHASES):
        channel = (r.get("Channel") or "").strip().lower()
        acquired = {"direct": "mail", "crowdfund": "crowdfund"}.get(channel, "")
        items.append({
            "item_id": str(next_id), "artist": r["Artist"].strip(), "title": r["Item"].strip(),
            "kind": (r.get("Format") or "other").strip().lower(), "acquired": acquired, "paid": "Y",
            "show_date": "", "venue": "", "status": (r.get("Status") or "").strip() or "received",
            "photo_ref": "", "source_key": "", "notes": (r.get("Note") or "").strip(),
        })
        if (r.get("Signed") or "").strip().upper() == "Y":
            sigs.append({
                "item_id": str(next_id), "seq": "", "signer": r["Artist"].strip(), "attribution": "",
                "show_date": "", "venue": "", "photo_ref": "", "legible": "", "confidence": "low",
                "notes": "signer assumed from the purchases ledger's Signed flag - confirm who signed",
            })
        next_id += 1
    return items, sigs


def render(rows, cols):
    lines = ["\t".join(cols)]
    for r in rows:
        lines.append("\t".join((r[c] or "-").replace("\t", " ") for c in cols))
    return "\n".join(lines) + "\n"


def report(items, sigs):
    out = ["%d items, %d signatures." % (len(items), len(sigs))]
    by_kind = {}
    for it in items:
        by_kind[it["kind"]] = by_kind.get(it["kind"], 0) + 1
    out.append("by kind: " + ", ".join("%s %d" % kv for kv in sorted(by_kind.items())))
    for label, pick in (("paid = ?  (decide Y or N)", lambda it: it["paid"] == "?"),
                        ("no photo", lambda it: not it["photo_ref"])):
        chosen = [it for it in items if pick(it)]
        out.append("\n%s: %d" % (label, len(chosen)))
        if label.startswith("paid"):
            for it in chosen:
                out.append("  %3s  %-8s %-28s %-34s %s" % (it["item_id"], it["kind"], it["artist"][:28],
                                                          it["title"][:34], it["show_date"]))
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if the committed files differ from a fresh build")
    ap.add_argument("--report", action="store_true", help="print the review lists and write nothing")
    args = ap.parse_args()
    items, sigs = build()
    outputs = ((ITEMS_OUT, render(items, ITEM_COLS)), (SIGS_OUT, render(sigs, SIG_COLS)))
    if args.report:
        print(report(items, sigs))
        return
    if args.check:
        stale = [str(p.relative_to(REPO_ROOT)) for p, text in outputs
                 if not p.is_file() or p.read_text(encoding="utf-8") != text]
        if stale:
            sys.exit("stale: %s - run tools/items/convert_item_log.py" % ", ".join(stale))
        print("items ledger matches a fresh build.")
        return
    for path, text in outputs:
        path.write_text(text, encoding="utf-8", newline="")
        print("wrote %s" % path.relative_to(REPO_ROOT))
    print(report(items, sigs))


if __name__ == "__main__":
    main()
