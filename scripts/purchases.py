#!/usr/bin/env python3
"""
purchases.py - the one place that knows what music has been bought.

A purchase is the strongest attachment the tracking data can show: money changed
hands. Two surfaces weigh it - the affinity score in build_artist_index.py (which
sizes the artist-graph nodes) and the settlement score in
tools/map/build_fantasy_map.py - and both must count the same purchases the same
way, so the reading, the de-duplication and the weighting live here and nowhere else.

ONE SOURCE. data/items.tsv is the ledger of things owned, one row per item,
and data/show_goals/item_signatures.tsv records who signed which item. A row is a
purchase when its `paid` column is Y - a CD, a download, a poster or a shirt alike.
A release received as a gift counts too - a signed CD a friend brought back is
music owned, the same as one that was bought. Mementos (a setlist, a thrown pick),
raffle prizes and prints of the owner's own photos are in the ledger but are not purchases. Something that came inside a VIP
package was paid for and counts. Status = pending counts: the money is committed.

An item is credited to its `artist`. A signed item is also credited to every signer
recorded without an "of <band>" attribution - a joint album signed by both of its
artists credits both, while a band member's signature credits only the band.

WEIGHTING. Every purchase weighs 1.0 whatever the channel or format - a single track,
a full album and a tour poster are each one purchase. A signed item adds SIGNED_BONUS
on top (it has at least one row in item_signatures.tsv).

SHAPE. The question the signal answers is "did I buy from this artist?", and only
then "did I keep buying?". share() turns a purchase weight into a 0..1 share: the
first purchase alone earns FIRST_SHARE (most of it), and each further unit closes a
small, fixed fraction of what is left. Both consumers scale that one share, so the
graph and the map agree on what a deep collection is worth next to a single track.

DE-DUPLICATION. The same release can be owned more than once (Kent Burnside's
"Hill Country Blood" is both a Bandcamp album and a signed CD). It is one purchase,
and it keeps the signed bonus if ANY copy is signed. The key is the resolved artist
plus the normalized title, so it needs the caller's resolver - see weigh(). Merch is
keyed with its kind in front ("poster: 2026 tour"), so a poster never merges with a
release of the same name, and identical posters from one night count once.

Names only. Nothing here reads or emits a price, a date of purchase or a sale id:
the inputs are public files and carry none.

Usage:
    python3 scripts/purchases.py            # per-artist report, from the repo root
    python3 scripts/purchases.py --unmatched  # also list purchases by untracked acts
"""
import argparse
import csv
import os
import re
import sys
import unicodedata

ITEMS_TSV = "data/items.tsv"
ITEM_SIGNATURES_TSV = "data/show_goals/item_signatures.tsv"

# Kinds whose title is a release title. Everything else is merch.
_MUSIC_KINDS = ("cd", "vinyl", "digital-album", "digital-track")

# What an autograph adds to a purchase's weight of 1.0. Callers may pass their own.
SIGNED_BONUS = 0.5
# share(): what the first purchase earns, and how much of the remainder is still
# left after each further unit of weight (0.8 = every further purchase closes 20%).
FIRST_SHARE = 0.7
MORE_DECAY = 0.8

_TRAILING_BAND = re.compile(r"\s+band$", re.I)


def _rows(path):
    if not os.path.isfile(path):
        return []
    with open(path, newline="", encoding="utf-8") as fh:
        lines = [ln for ln in fh if not ln.startswith("#")]
    return list(csv.DictReader(lines, delimiter="\t"))


def _cell(row, key):
    v = (row.get(key) or "").strip()
    return "" if v == "-" else v


def _yes(v):
    return (v or "").strip().upper() in ("Y", "YES")


def title_key(title):
    """Normalized release title for de-duplication: de-accented, lowercased, "&" and
    "+" read as "and", a trailing format word dropped ("Liberation LP"), punctuation
    to spaces. "Still & Bright" and "Still + Bright" are the same release."""
    s = unicodedata.normalize("NFKD", title or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"\s*[&+]\s*", " and ", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r" (lp|ep|cd|vinyl)$", "", s)
    return s


def load_purchases(root="."):
    """Every purchase in the items ledger, NOT yet de-duplicated:
    [{"artist", "title", "signed", "source"}]. One dict per credited artist per
    purchase, so a joint album yields one dict for each of its artists. `source`
    is the item's `acquired` value (show, bandcamp, mail, vip ...)."""
    signers = {}  # item_id -> signers recorded with no "of <band>" attribution
    signed = set()
    for r in _rows(os.path.join(root, ITEM_SIGNATURES_TSV)):
        item_id = _cell(r, "item_id")
        signed.add(item_id)
        if _cell(r, "signer") and not _cell(r, "attribution"):
            signers.setdefault(item_id, []).append(_cell(r, "signer"))

    out = []
    for r in _rows(os.path.join(root, ITEMS_TSV)):
        item_id, artist, kind = _cell(r, "item_id"), _cell(r, "artist"), _cell(r, "kind").lower()
        # A release received as a gift counts like one that was bought: what the signal
        # measures is owning the artist's music, and a signed CD handed over by a
        # friend is that. Other unpaid things (mementos, raffle prizes) are not.
        gifted_release = _cell(r, "acquired") == "gift" and kind in _MUSIC_KINDS
        if not (_yes(r.get("paid")) or gifted_release):
            continue
        title = _cell(r, "title")
        # A Bandcamp merch package is a physical copy of the release it is named for.
        is_release = kind in _MUSIC_KINDS or _cell(r, "source_key").startswith("bandcamp:package:")
        if not is_release:
            title = "%s: %s" % (kind or "item", title or "untitled")
        if not artist or not title:
            continue
        credited = [artist] + [s for s in signers.get(item_id, []) if s != artist]
        for name in credited:
            out.append({"artist": name, "title": title, "signed": item_id in signed,
                        "source": _cell(r, "acquired") or "unknown"})
    return out


def share(weight, first=FIRST_SHARE, decay=MORE_DECAY):
    """0..1 share of the purchase bonus for a purchase weight (from weigh()).

    0 for no purchases. The first purchase earns `first`; every further unit of weight
    closes (1 - decay) of what is left, so the share rises in small steps and stays
    below 1.0:  share = first + (1 - first) * (1 - decay ** (weight - 1)).
    A weight under 1 cannot occur (a purchase weighs at least 1) and is read as 1.
    """
    if not weight or weight <= 0:
        return 0.0
    return first + (1 - first) * (1 - decay ** (max(weight, 1.0) - 1))


def weigh(purchases, resolve, signed_bonus=SIGNED_BONUS):
    """De-duplicate and total the purchases per resolved artist.

    resolve(name) -> the caller's identity key for name, or None when the caller does
    not track that act. Returns (by_artist, unmatched):

      by_artist  {key: {"count": distinct releases, "signed": how many of them are
                 signed, "weight": count + signed_bonus * signed}}
      unmatched  [{"artist", "title", "signed", "source"}] for names resolve() rejected,
                 de-duplicated by raw name + title, in a stable order.
    """
    seen = {}       # (artist key, title key) -> signed?
    stray = {}      # (raw artist lower, title key) -> row
    for p in purchases:
        key = resolve(p["artist"])
        if key is None:
            # House convention (recommend_aliases.tsv): a trailing " Band" is the same
            # act. The item log writes "of Jax Hollow band" in lower case, which the
            # callers' resolvers do not all fold on their own.
            bare = _TRAILING_BAND.sub("", p["artist"]).strip()
            if bare and bare != p["artist"].strip():
                key = resolve(bare)
        tk = title_key(p["title"])
        if key is None:
            sk = (p["artist"].strip().lower(), tk)
            if sk in stray:
                stray[sk]["signed"] = stray[sk]["signed"] or p["signed"]
            else:
                stray[sk] = dict(p)
            continue
        seen[(key, tk)] = seen.get((key, tk), False) or p["signed"]

    by_artist = {}
    for (key, _tk), signed in seen.items():
        e = by_artist.setdefault(key, {"count": 0, "signed": 0})
        e["count"] += 1
        e["signed"] += 1 if signed else 0
    for e in by_artist.values():
        e["weight"] = round(e["count"] + signed_bonus * e["signed"], 3)
    unmatched = sorted(stray.values(), key=lambda p: (p["artist"].lower(), title_key(p["title"])))
    return by_artist, unmatched


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=".")
    ap.add_argument("--unmatched", action="store_true",
                    help="also list purchases by acts the tracker does not know")
    args = ap.parse_args()

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from build_artist_index import build, make_canon  # noqa: E402

    # The index's own universe decides what "tracked" means here, so this report
    # counts exactly the purchases the affinity score sees.
    canon, _resolver = make_canon(args.root)
    tracked = {key: rec["name"] for key, rec in build(args.root)["artists"].items()}
    purchases = load_purchases(args.root)
    by_artist, unmatched = weigh(purchases, lambda n: canon(n) if canon(n) in tracked else None)

    print(f"{len(purchases)} purchase rows -> {sum(e['count'] for e in by_artist.values())} "
          f"distinct releases across {len(by_artist)} tracked artists; "
          f"{len(unmatched)} by untracked acts")
    for key, e in sorted(by_artist.items(), key=lambda kv: (-kv[1]["weight"], tracked[kv[0]].lower())):
        print(f"  {e['weight']:>5}  share {share(e['weight']):.2f}  {tracked[key]}  "
              f"({e['count']} owned, {e['signed']} signed)")
    if args.unmatched:
        print("untracked:")
        for p in unmatched:
            print(f"  {p['artist']} - {p['title']} [{p['source']}]")


if __name__ == "__main__":
    main()
