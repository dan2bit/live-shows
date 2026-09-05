#!/usr/bin/env python3
"""
build_fantasy_map.py — reshape the artist-graph data into a speculative-fiction
map model: regions (terrain), districts (neighborhoods), settlements (artists),
and routes (edges), with normalized coordinates for a JS/CSS overlay layer.

Reads the same sources as tools/research/graph/artist-graph.html:
  recommend_index.json   nodes + name-variant resolver
  artist_spotify.json    lastfm tags (terrain votes) + similar (trail edges)
  related_acts.tsv       hand-maintained kinship (road edges)
  artists.tsv            Via column (road edges), Times Seen / VIP (settlement size)
  seen_with.tsv          recurring sidemen (bridge edges)
  live_shows_current.tsv / history/<year>.tsv   bill edges (river-road edges)

Lives in tools/map/ and finds its sources in the repo's data/ tree. Run it from
anywhere; the repo root is auto-detected by walking up from this file (or pass
--repo-root explicitly, e.g. against a second checkout).

Output: fantasy_map_data.json (see fantasy_map_schema.md for the contract).
"""
import argparse, ast, csv, hashlib, json, math, os, random, re, sys
from collections import Counter, defaultdict
from pathlib import Path

# Community detection's tie-breaking leaks Python's per-process hash seed into
# the layout; pin it (via one self re-exec) so identical inputs give identical maps.
if os.environ.get("PYTHONHASHSEED") != "2026":
    os.environ["PYTHONHASHSEED"] = "2026"
    os.execv(sys.executable, [sys.executable, *sys.argv])

import networkx as nx

SCRIPT_DIR = Path(__file__).resolve().parent

def find_repo_root(start):
    for cand in [start, *start.parents]:
        if (cand / "data" / "recommend_index.json").exists():
            return cand
    return None

ap = argparse.ArgumentParser(description="Reshape artist-graph data into the fantasy-map model.")
ap.add_argument("--repo-root", type=Path, default=None,
                help="live-shows checkout root (default: auto-detect above this script)")
ap.add_argument("--out", type=Path, default=SCRIPT_DIR / "fantasy_map_data.json",
                help="output JSON path (default: fantasy_map_data.json beside this script)")
args = ap.parse_args()

ROOT = args.repo_root or find_repo_root(SCRIPT_DIR) or find_repo_root(Path.cwd())
if ROOT is None or not (ROOT / "data" / "recommend_index.json").exists():
    sys.exit("could not locate the repo root (data/recommend_index.json); pass --repo-root")
DATA = ROOT / "data"
OUT = args.out
RNG_SEED = 2026

# ---------------------------------------------------------------- canvas + regions
CANVAS = {"w": 1000, "h": 700}

# Terrain archetypes. Anchors/ellipses are layout hints in canvas units; the
# design layer is free to warp them to the painted background (use region_uv).
REGIONS = {
    "delta_coast": {
        "label": "Delta Coast",
        "terrain": "coastal tidewater — estuary, levees, shotgun porches",
        "label_xy": (327, 633), "label_size": 15,
        "anchor": (308, 598), "rx": 172, "ry": 52,
        "toponym_suffixes": ["Haven", "Quay", "Levee", "Landing", "Shoals"],
        "toponym_prefixes": ["Port "],
    },
    "amplified_range": {
        "label": "Amplified Range",
        "terrain": "high mountains — basalt cliffs, feedback storms",
        "label_xy": (687, 206), "label_size": 18,
        "anchor": (790, 205), "rx": 175, "ry": 125,
        "toponym_suffixes": ["Crag", "Pass", "Summit", "Overdrive", "Ridge"],
        "toponym_prefixes": ["Mount "],
    },
    "slide_foothills": {
        "label": "Steel Foothills",
        "terrain": "foothills - slide scarps, steel terraces, bottleneck switchbacks",
        "label_xy": (606, 323), "label_size": 13,
        "anchor": (648, 398), "rx": 58, "ry": 118,
        "toponym_suffixes": ["Scarp", "Terrace", "Rise", "Switchback", "Bend"],
        "toponym_prefixes": ["Steel "],
    },
    "heartland": {
        "label": "Heartland",
        "terrain": "farmland plains — wheat, gravel roads, grain towers",
        "label_xy": (307, 483), "label_size": 18,
        "anchor": (420, 480), "rx": 190, "ry": 118,
        "toponym_suffixes": ["Hollow", "Fields", "Prairie", "Crossing", "Silo"],
        "toponym_prefixes": [],
    },
    "river_port": {
        "label": "Secondline<br/>Riverlands",
        "terrain": "riverside port — wharves, brass balconies, paddle steam",
        "label_xy": (594, 608), "label_size": 15,
        "anchor": (598, 545), "rx": 125, "ry": 78,
        "toponym_suffixes": ["Wharf", "Landing", "Parade", "Bend", "Ward"],
        "toponym_prefixes": [],
    },
    "quiet_woods": {
        "label": "Quiet Woods",
        "terrain": "forest and lakes — pine shade, cabin lights, still water",
        "label_xy": (495, 307), "label_size": 17,
        "anchor": (480, 318), "rx": 172, "ry": 112,
        "toponym_suffixes": ["Glen", "Hollow", "Lake", "Grove", "Vale"],
        "toponym_prefixes": [],
    },
    "outer_isles": {
        "label": "Outer Isles",
        "terrain": "offshore archipelago continuing the range's line north - ferry weather, distant genres",
        "label_xy": (872, 120), "label_size": 15,
        "anchor": (900, 62), "rx": 88, "ry": 48,
        "toponym_suffixes": ["Isle", "Skerry", "Sound", "Rock"],
        "toponym_prefixes": ["Isle of "],
    },
}

# Waterway suggestions (polylines, canvas units). The design layer may redraw;
# routes reference these only thematically.
WATERWAYS = [
    {"id": "the_bigmuddy", "label": "The Big Muddy",
     "points": [(672, 306), (640, 348), (618, 422), (612, 478), (628, 546), (642, 606)],
     "note": "rises at the heel where the massif's short torrents gather below the Steel Foothills, then runs the body's southeast seam to the bay that bites the bottom curve"},
    {"id": "slowhand_creek", "label": "Slowhand Creek",
     "points": [(585, 372), (600, 424), (612, 470)],
     "note": "short run out of the forest lake on the upper bout, joining the Big Muddy at the seam"},
    {"id": "the_forest_lake", "label": "The Source", "names": ["The Source"],
     "points": [(585, 372)],
     "note": "lake in the Quiet Woods at the creek's source; sits where a neck pickup would"},
    {"id": "the_shoulder_lakes", "label": "The Shoulder Lakes", "names": ["Giddens Pool", "Lake Vega"],
     "points": [(430, 246), (358, 318)],
     "note": "the two big lakes on the upper bout's shoulder; each carries a sizable Quiet Woods settlement on its shore"},
    {"id": "the_parade", "label": "The Parade",
     "points": [(505, 560), (562, 584), (614, 600)],
     "note": "the second river into the bay, draining the knob-lake country along the lower bout; Second Line's twin waterfront with the Big Muddy"},
    {"id": "the_knob_lakes", "label": "The Knob Lakes", "names": ["Volume", "Tone"],
     "points": [(468, 540), (505, 560)],
     "note": "two small lakes on the lower bout, roughly where the knobs would sit"},
    {"id": "the_sound", "label": "The Wide Water",
     "points": [(0, 690), (320, 678), (640, 685), (1000, 682)],
     "note": "the southern sea below the body's bottom curve; the bay opens off it"},
    {"id": "the_north_reach", "label": "The North Reach",
     "points": [(0, 60), (400, 90), (700, 60), (1000, 40)],
     "note": "the northern sea flanking the neck; the Outer Isles are the pegs off the headstock"},
    {"id": "the_west_water", "label": "The West Water",
     "points": [(60, 120), (70, 300), (55, 480), (75, 620)],
     "note": "open sea west of the body; fjord fingers cut the waist on the northwest side"},
    {"id": "the_east_shore", "label": "The East Shore",
     "points": [(940, 200), (880, 360), (800, 480), (740, 570)],
     "note": "the sea southeast of the neck; its cut toward the bay defines the body's seam side"},
]

# tag keyword -> (region, weight). Substring match on lowercased tags.
TAG_VOTES = [
    ("delta blues", "delta_coast", 4), ("acoustic blues", "delta_coast", 3),
    ("country blues", "delta_coast", 3), ("piedmont", "delta_coast", 4),
    ("traditional blues", "delta_coast", 3), ("gospel", "delta_coast", 2),
    ("harmonica", "delta_coast", 2), ("chicago blues", "delta_coast", 2),
    ("soul blues", "delta_coast", 2), ("blues", "delta_coast", 1),
    ("blues rock", "amplified_range", 3), ("blues-rock", "amplified_range", 3),
    ("hard rock", "amplified_range", 3), ("classic rock", "amplified_range", 2),
    ("guitar virtuoso", "amplified_range", 4), ("shred", "amplified_range", 4),
    ("guitar", "amplified_range", 2), ("southern rock", "amplified_range", 2),
    ("rock", "amplified_range", 1), ("stoner", "amplified_range", 2),
    ("psychedelic", "amplified_range", 1),
    ("country", "heartland", 3), ("americana", "heartland", 3),
    ("alt-country", "heartland", 3), ("bluegrass", "heartland", 4),
    ("honky tonk", "heartland", 3), ("red dirt", "heartland", 3),
    ("outlaw", "heartland", 3), ("roots", "heartland", 2),
    ("funk", "river_port", 4), ("soul", "river_port", 2),
    ("new orleans", "river_port", 5), ("brass", "river_port", 5),
    ("jam band", "river_port", 3), ("jam", "river_port", 2),
    ("r&b", "river_port", 2), ("rhythm and blues", "river_port", 2),
    ("jazz", "river_port", 3), ("groove", "river_port", 2),
    ("neo-soul", "river_port", 3),
    ("singer-songwriter", "quiet_woods", 3), ("singer songwriter", "quiet_woods", 3),
    ("folk", "quiet_woods", 3), ("indie folk", "quiet_woods", 3),
    ("acoustic", "quiet_woods", 1), ("chamber", "quiet_woods", 3),
    ("indie", "quiet_woods", 1), ("dream pop", "quiet_woods", 2),
    ("celtic", "outer_isles", 5), ("irish", "outer_isles", 5),
    ("scottish", "outer_isles", 5), ("world", "outer_isles", 2),
    ("progressive metal", "outer_isles", 5), ("metal", "outer_isles", 3),
    ("djent", "outer_isles", 5), ("pop punk", "outer_isles", 3),
    ("pop", "outer_isles", 2), ("tribute", "outer_isles", 3),
    ("cover band", "outer_isles", 3), ("a cappella", "outer_isles", 3),
]

EDGE_WEIGHT = {"road": 2.0, "river": 2.0, "bridge": 1.5, "trail": 1.0}

# ---------------------------------------------------------------- load sources
def tsv_rows(path):
    with open(path, newline="", encoding="utf-8") as f:
        rows = [r for r in csv.reader(f, delimiter="\t") if r and not r[0].startswith("#")]
    hdr = rows[0]
    return [dict(zip(hdr, r)) for r in rows[1:]]

idx = json.loads((DATA / "recommend_index.json").read_text())
records = {r["canonical"]: r for r in idx["records"]}
variants = {k: idx["records"][v]["canonical"] if isinstance(v, int) else v
            for k, v in idx["variants"].items()}
# variants maps lower-name -> record id; normalize to canonical
id2canon = {r["id"]: r["canonical"] for r in idx["records"]}
variants = {k: id2canon[v] for k, v in idx["variants"].items() if v in id2canon}

def resolve(name):
    if not name:
        return None
    n = re.sub(r"\s+", " ", name.strip())
    cands = [n]
    m = re.match(r"^(.*),\s*(The|Los|Las)$", n, re.I)   # "Lone Bellow, The"
    if m:
        cands.append(f"{m.group(2)} {m.group(1)}")
    if " & " in n:                                       # "John Primer & The ..."
        cands.append(n.split(" & ")[0])
    for c in cands:
        hit = variants.get(c.lower()) or (c if c in records else None)
        if not hit:  # variants store some names with punctuation stripped
            hit = variants.get(re.sub(r"[^\w\s]", "", c).lower())
        if hit:
            return hit
    return None

spot = json.loads((DATA / "artist_spotify.json").read_text())
def lastfm(entry):
    lf = entry.get("lastfm")
    if isinstance(lf, str):
        try:
            lf = ast.literal_eval(lf)
        except Exception:
            lf = {}
    return lf or {}

# artists.tsv authoritative seen/VIP; most_recent for the faded flag
seen_meta = {}
for r in tsv_rows(DATA / "artists.tsv"):
    c = resolve(r["Artist"])
    if c:
        seen_meta[c] = {
            "times_seen": int(r.get("Times Seen") or 0),
            "vip": int(r.get("VIP Count") or 0),
            "most_recent": r.get("Most Recent Seen") or r.get("First Seen") or "",
        }

# history TSVs credit seen-time to indexed artists that artists.tsv never rowed
# (support slots, co-headline cells); artists.tsv remains authoritative when present.
def _hist_tokens(cell):
    for tok in re.split(r"[;/]", cell or ""):
        tok = tok.strip()
        if not tok or tok == "-":
            continue
        if resolve(tok):
            yield tok; continue
        parts = [p.strip() for p in re.split(r"\s+&\s+|\s+and\s+", tok) if p.strip()]
        if len(parts) > 1 and all(resolve(p) for p in parts):
            yield from parts
        else:
            yield tok

_hist_seen = defaultdict(lambda: {"n": 0, "last": ""})
for _hp in sorted((DATA / "history").glob("*.tsv")):
    for _hr in tsv_rows(_hp):
        _hd = (_hr.get("Show Date") or "")[:10]
        for _cell in (_hr.get("Artist"), _hr.get("Supporting Acts")):
            for _tok in _hist_tokens(_cell):
                _c = resolve(_tok)
                if _c:
                    _hist_seen[_c]["n"] += 1
                    _hist_seen[_c]["last"] = max(_hist_seen[_c]["last"], _hd)
for _c, _hv in _hist_seen.items():
    if _c not in seen_meta:
        seen_meta[_c] = {"times_seen": _hv["n"], "vip": 0,
                         "most_recent": _hv["last"], "via_history": True}

# audit #318 dedupe: merges and co-bill suppressions, decided 2026-09-05
MERGES = {   # absorbed -> survivor (survivor inherits seen history)
    "Daniel Donato's Cosmic Country": "Daniel Donato",
    "Gillian Welch & David Rawlings": "Gillian Welch",
    "Victor Wooten & The Wooten Brothers": "Victor Wooten",
    "Allman Betts Family Revival: A Decade of Revival": "The Allman Betts Band",
}
SUPPRESSED_CREDIT = {   # co-bill -> principals; each principal gains the co-bill's seen count
    "Samantha Fish & Jesse Dayton": ["Samantha Fish", "Jesse Dayton"],
    "Blood Brothers": ["Mike Zito", "Albert Castiglia"],
}
def _fold_seen(dst, src_meta):
    m_ = seen_meta.setdefault(dst, {"times_seen": 0, "vip": 0, "most_recent": ""})
    m_["times_seen"] = m_.get("times_seen", 0) + src_meta.get("times_seen", 0)
    m_["vip"] = m_.get("vip", 0) + src_meta.get("vip", 0)
    m_["most_recent"] = max(m_.get("most_recent", ""), src_meta.get("most_recent", ""))
for _gone, _keep in MERGES.items():
    if _gone in records:
        if _keep in records:
            _fold_seen(_keep, seen_meta.get(_gone, {}))
            records[_keep]["sources"] = sorted(set(records[_keep].get("sources", []))
                                               | set(records[_gone].get("sources", [])))
        records.pop(_gone); seen_meta.pop(_gone, None)
for _gone, _kin in SUPPRESSED_CREDIT.items():
    if _gone in records:
        for _k in _kin:
            if _k in records:
                _fold_seen(_k, seen_meta.get(_gone, {}))
        records.pop(_gone); seen_meta.pop(_gone, None)

# ---------------------------------------------------------------- edges
edges = {}  # frozenset({a,b}) -> class (strongest wins: road/river > bridge > trail)
RANK = {"road": 3, "river": 3, "bridge": 2, "trail": 1}
def add_edge(a, b, cls):
    if not a or not b or a == b:
        return
    key = frozenset((a, b))
    if key not in edges or RANK[cls] > RANK[edges[key]]:
        edges[key] = cls

# trails: lastfm similar
for name, entry in spot.items():
    a = resolve(name)
    if not a:
        continue
    for s in lastfm(entry).get("similar", []):
        add_edge(a, resolve(s), "trail")

# roads: related_acts + Via
for r in tsv_rows(DATA / "related_acts.tsv"):
    add_edge(resolve(r.get("Artist A")), resolve(r.get("Artist B")), "road")
for r in tsv_rows(DATA / "artists.tsv"):
    via = (r.get("Via") or "").strip()
    if via and not via.lower().startswith("fka"):
        add_edge(resolve(r["Artist"]), resolve(via), "road")

# rivers: bill edges (attended history + current)
def bill_edges(headliner, support):
    h = resolve(headliner)
    for s in re.split(r"\s*/\s*", support or ""):
        add_edge(h, resolve(s), "river")

for p in sorted((DATA / "history").glob("*.tsv")):
    for r in tsv_rows(p):
        bill_edges(r.get("Artist"), r.get("Supporting Acts"))
for r in tsv_rows(DATA / "live_shows_current.tsv"):
    bill_edges(r.get("Artist"), r.get("Supporting Artist"))

# bridges: sidemen recurring across >=2 headliners
side = defaultdict(set)
for r in tsv_rows(DATA / "seen_with.tsv"):
    h = resolve(r.get("Headliner"))
    if h:
        side[r.get("Seen With")].add(h)
for hs in side.values():
    hs = sorted(hs)
    if len(hs) >= 2:
        for i in range(len(hs)):
            for j in range(i + 1, len(hs)):
                add_edge(hs[i], hs[j], "bridge")

# ---------------------------------------------------------------- graph + regions
G = nx.Graph()
for c in records:
    G.add_node(c)
for key, cls in edges.items():
    a, b = tuple(key)
    G.add_edge(a, b, cls=cls, weight=EDGE_WEIGHT[cls])

def tag_region(canon):
    entry = spot.get(canon)
    if not entry:
        return None
    tags = [t.lower() for t in lastfm(entry).get("tags", [])]
    score = Counter()
    for tag in tags:
        for kw, reg, w in TAG_VOTES:
            if kw in tag:
                score[reg] += w
    return score.most_common(1)[0][0] if score else None

CURATED_REGIONS = {"slide_foothills"}

FORCED_REGION = {
    "Danny Burns": "outer_isles",
    "Angelique Francis": "river_port",
    "Beth Hart": "amplified_range",
    "Miko Marks": "delta_coast",
    "Beck": "amplified_range",
    "Taj Mahal": "delta_coast",
    "TajMo: The Taj Mahal & Keb' Mo' Band": "delta_coast",
    "Taj Farrant": "amplified_range",
    "Buffalo Nichols": "delta_coast",
    "Southern Avenue": "delta_coast",
    "Ruthie Foster": "delta_coast",
    # The Steel Foothills: slide, lap steel, and sacred steel players.
    "Larkin Poe": "slide_foothills",
    "Ghalia Volt": "slide_foothills",
    "Mike Zito": "slide_foothills",
    "Robert Randolph": "slide_foothills",
    "Ariel Posen": "slide_foothills",
    "Sonny Landreth": "slide_foothills",
    "Selwyn Birchwood": "slide_foothills",
    "The Bros. Landreth": "slide_foothills",
    "Joey Landreth": "slide_foothills",
    "Warren Haynes": "slide_foothills",
    "North Mississippi Allstars": "slide_foothills",
    "Tedeschi Trucks Band": "slide_foothills",
}

region_of = {c: FORCED_REGION.get(c) or tag_region(c) for c in records}
# neighbor-vote passes for the untagged
for _ in range(3):
    for c in records:
        if region_of.get(c):
            continue
        votes = Counter(region_of[n] for n in G.neighbors(c)
                        if region_of.get(n) and region_of[n] not in CURATED_REGIONS)
        if votes:
            region_of[c] = votes.most_common(1)[0][0]
for c in records:  # stragglers: isolated unknowns drift to the Isles
    if not region_of.get(c):
        region_of[c] = "outer_isles" if G.degree(c) == 0 else "heartland"

# ---------------------------------------------------------------- districts
random.seed(RNG_SEED)
districts = {}          # district id -> {region, members, suggested_name}
district_of = {}
for reg in REGIONS:
    members = [c for c in records if region_of[c] == reg]
    sub = G.subgraph(members)
    comms = [set(cm) for cm in nx.community.greedy_modularity_communities(sub, weight="weight")] \
            if sub.number_of_edges() else []
    comms = [cm for cm in comms if len(cm) >= 2]
    placed = set()
    for i, cm in enumerate(sorted(comms, key=len, reverse=True), 1):
        did = f"{reg}:d{i}"
        # name the district after its best-connected member's last word
        seat = max(cm, key=lambda c: sub.degree(c))
        seatword = re.sub(r"[^A-Za-z]", "", seat.split()[-1]) or "Crossroads"
        sfx = REGIONS[reg]["toponym_suffixes"][i % len(REGIONS[reg]["toponym_suffixes"])]
        districts[did] = {"region": reg, "members": sorted(cm),
                          "seat": seat, "suggested_name": f"{seatword} {sfx}"}
        for c in cm:
            district_of[c] = did
        placed |= cm
    outs = f"{reg}:outskirts"
    rest = sorted(set(members) - placed)
    if rest:
        districts[outs] = {"region": reg, "members": rest, "seat": None,
                           "suggested_name": REGIONS[reg]["label"] + " Outskirts"}
        for c in rest:
            district_of[c] = outs


# ---------------------------------------------------------------- settlements
LEGENDS = {
    "John Hiatt", "Cowboy Junkies", "Willie Nelson",          # of the Heartland
    "Mavis Staples",                                          # of Second Line
    "Bonnie Raitt",                                           # of the Woods
    "Keb' Mo'",                                               # of the Delta
    "Walter Trout", "Steve Miller Band",                      # of the Amplified Range
    "Tommy Castro & the Painkillers", "Jimmie Vaughan", "Robert Cray Band",
    "Taj Mahal", "John Primer", "Chris Smither",              # of the Delta (Legends Island)
    "Lyle Lovett", "Los Lobos", "Emmylou Harris",             # of the Heartland
    "George Clinton & Parliament-Funkadelic",                 # of Second Line
    "Mitch Ryder", "Joan Jett & The Blackhearts",             # of the Amplified Range
    "Billy Gibbons",                                          # the lineup, not the brand
}

TIER_SCORE = {"Strong": 3, "Medium-Strong": 2, "Medium": 1, "Lower": 0.5, "Legacy": 2}
def score(c):
    m = seen_meta.get(c, {})
    r = records[c]
    return (3 * min(m.get("times_seen", 0), 8)
            + 2 * m.get("vip", 0)
            + TIER_SCORE.get(r.get("tier"), 0))

# The Outer Isles regroup: the taste graph barely connects the outliers, so
# districts there are rebuilt as peg crews - genre-family buckets chunked small.
def isle_family(c):
    tags = [t.lower() for t in lastfm(spot.get(c, {})).get("tags", [])]
    joined = " ".join(tags)
    for kws, fam in ((("celtic", "irish", "scottish"), "celtic"),
                     (("tribute", "cover"), "tribute"),
                     (("metal", "djent", "progressive"), "metal"),
                     (("pop", "indie"), "pop")):
        if any(k in joined for k in kws):
            return fam
    return "far"

isle_members_all = sorted(c for c in records if region_of[c] == "outer_isles")
for did in [d_ for d_ in list(districts) if districts[d_]["region"] == "outer_isles"]:
    del districts[did]
fams = defaultdict(list)
for c in isle_members_all:
    fams[isle_family(c)].append(c)
pegs = []
for fam in sorted(fams):
    mem = fams[fam]
    for j in range(0, len(mem), 6):
        pegs.append((fam, mem[j:j + 6]))
for pi2, (fam, mem) in enumerate(pegs, 1):
    did = f"outer_isles:p{pi2}"
    seat = max(mem, key=lambda c: score(c))
    seatword = re.sub(r"[^A-Za-z]", "", seat.split()[-1]) or "Peg"
    sfx = REGIONS["outer_isles"]["toponym_suffixes"][pi2 % len(REGIONS["outer_isles"]["toponym_suffixes"])]
    districts[did] = {"region": "outer_isles", "members": mem, "seat": seat,
                      "suggested_name": f"{seatword} {sfx}"}
    for c in mem:
        district_of[c] = did

CAPITAL_OVERRIDE = {"slide_foothills": "Larkin Poe", "outer_isles": "AJR"}

def size_tier(c, s, regional_max):
    m = seen_meta.get(c, {})
    reg = region_of[c]
    if reg in CAPITAL_OVERRIDE:
        if c == CAPITAL_OVERRIDE[reg]:
            return "capital"
        regional_max = float("inf")  # nobody else in this region auto-promotes
    if m.get("times_seen", 0) == 0:
        return "waystation"
    if s >= regional_max and s >= 12:
        return "capital"
    if s >= 12: return "city"
    if s >= 6:  return "town"
    if s >= 3.5: return "village"
    return "hamlet"

def faded(c):
    mr = seen_meta.get(c, {}).get("most_recent", "")
    return bool(mr) and mr < "2019-01-01"

# ---------------------------------------------------------------- layout
def ellipse_fit(pos, anchor, rx, ry, pad=0.88):
    xs = [p[0] for p in pos.values()] or [0]; ys = [p[1] for p in pos.values()] or [0]
    cx, cy = (min(xs)+max(xs))/2, (min(ys)+max(ys))/2
    span = max(max(xs)-min(xs), 1e-6), max(max(ys)-min(ys), 1e-6)
    out = {}
    for n, (x, y) in pos.items():
        u, v = (x-cx)/span[0]*2, (y-cy)/span[1]*2   # -1..1
        r = math.hypot(u, v)
        if r > 1: u, v = u/r, v/r
        out[n] = (anchor[0] + u*rx*pad, anchor[1] + v*ry*pad)
    return out

# analytic land test mirroring emit_heightmap's silhouette - keep the two in sync
SIL_AXIS = math.radians(-38); SIL_HEEL = (645, 325)
_su, _sv = (math.cos(SIL_AXIS), math.sin(SIL_AXIS)), (-math.sin(SIL_AXIS), math.cos(SIL_AXIS))
def _on_axis(t, off=0.0):
    return (SIL_HEEL[0] + _su[0] * t + _sv[0] * off, SIL_HEEL[1] + _su[1] * t + _sv[1] * off)
def _seg_dist(p, a, b):
    ax, ay = a; bx, by = b; px, py = p
    vx, vy = bx - ax, by - ay; L2 = vx * vx + vy * vy or 1e-9
    t = max(0, min(1, ((px - ax) * vx + (py - ay) * vy) / L2))
    return math.hypot(px - (ax + t * vx), py - (ay + t * vy))
_SIL_DISCS = [(_on_axis(-105), 168), (_on_axis(-205), 126), (_on_axis(-318), 196), ((598, 492), 138)]
def land_field(x, y):
    v = 0.0
    v = max(v, min(1, (1 - _seg_dist((x, y), SIL_HEEL, _on_axis(175)) / 88) * 4.0))
    v = max(v, min(1, (1 - _seg_dist((x, y), _on_axis(120), _on_axis(292)) / 58) * 4.0))
    for (cx_, cy_), r_ in _SIL_DISCS:
        v = max(v, min(1, (1 - math.hypot(x - cx_, y - cy_) / r_) * 5.5))
    return max(v, 0.0)
def clamp_to_land(x, y, toward, thresh=0.78):
    if land_field(x, y) >= thresh:
        return (x, y)
    tx, ty = toward
    lo, hi = 0.0, 1.0
    for _ in range(22):
        mid = (lo + hi) / 2
        mx, my = x + (tx - x) * mid, y + (ty - y) * mid
        if land_field(mx, my) >= thresh: hi = mid
        else: lo = mid
    return (x + (tx - x) * hi, y + (ty - y) * hi)

# per-region layout temperament: heartland spreads loose, others cluster
REGION_SPREAD = {"heartland": 2.1, "delta_coast": 1.3}
OUTSKIRT_ARC = {"delta_coast": (math.radians(25), math.radians(155)),
                "river_port": (math.radians(195), math.radians(345))}

xy = {}
for reg, spec in REGIONS.items():
    members = [c for c in records if region_of[c] == reg]
    if not members:
        continue
    if reg == "outer_isles":
        continue  # placed below, one island per district along the headstock
    # quotient layout: springs position the districts, members ring their district
    dids = sorted({district_of[m] for m in members})
    Q = nx.Graph(); Q.add_nodes_from(dids)
    for u, v, dat in G.subgraph(members).edges(data=True):
        du, dv = district_of[u], district_of[v]
        if du != dv:
            w = Q[du][dv]["weight"] + dat["weight"] if Q.has_edge(du, dv) else dat["weight"]
            Q.add_edge(du, dv, weight=w)
    dpos = nx.spring_layout(Q, weight="weight", seed=RNG_SEED,
                            k=1.4 / max(math.sqrt(len(dids)), 1))
    if reg == "amplified_range":
        # districts string along the ridge: ordered by their spring x, seated on
        # alternating flanks of the axis at varied shoulder heights
        ordered = sorted((d_ for d_ in dids if not d_.endswith(":outskirts")),
                         key=lambda d_: dpos[d_][0])
        centers = {}
        for oi, d_ in enumerate(ordered):
            t_ = -42 + (250 / max(len(ordered) - 1, 1)) * oi
            side_ = 1 if oi % 2 else -1
            off_ = side_ * (17 + 8 * (oi % 3))
            centers[d_] = _on_axis(t_, off_)
        for d_ in dids:
            if d_.endswith(":outskirts"):
                centers[d_] = _on_axis(100)
    else:
        centers = ellipse_fit(dpos, spec["anchor"], spec["rx"] * 0.82, spec["ry"] * 0.8)
    for d_ in dids:
        mem = sorted(m for m in members if district_of[m] == d_)
        cxd, cyd = centers[d_]
        if d_.endswith(":outskirts") and reg == "amplified_range":
            # ridge frontier: cabins strung up the neck with cross-axis jitter
            jr = random.Random(f"{RNG_SEED}:ridge")
            for j, m in enumerate(mem):
                t_ = -50 + ((j * 0.61803) % 1.0) * 320
                off_ = (jr.random() - 0.5) * 56
                xy[m] = clamp_to_land(*_on_axis(t_, off_), toward=_on_axis(t_ * 0.6))
            continue
        if d_.endswith(":outskirts"):
            # frontier scatter along the region rim (arc-limited where the sea presses)
            a0, a1 = OUTSKIRT_ARC.get(reg, (0, 2 * math.pi))
            for j, m in enumerate(mem):
                ang = a0 + ((j * 0.61803) % 1.0) * (a1 - a0)
                px_ = spec["anchor"][0] + math.cos(ang) * spec["rx"] * 0.9
                py_ = spec["anchor"][1] + math.sin(ang) * spec["ry"] * 0.9
                xy[m] = clamp_to_land(px_, py_, spec["anchor"])
            continue
        spread = REGION_SPREAD.get(reg, 1.0)
        ring = (6 + 3.4 * math.sqrt(len(mem))) * spread
        jrng = random.Random(f"{RNG_SEED}:{d_}")
        for j, m in enumerate(mem):
            ang = j * 2.399963
            rr = ring * math.sqrt((j + 0.5) / len(mem)) * (0.8 + 0.4 * jrng.random())
            xy[m] = clamp_to_land(cxd + rr * math.cos(ang), cyd + rr * math.sin(ang), (cxd, cyd))
    continue

# ---- canonical pins and Dan's hand pins (tools/map/pins.json wins last) ----
CANON_PINS = {                                # first pin moves the whole district
    "Larkin Poe": (608, 373),                 # east shore of the source lake
    "The Lone Bellow": (562, 366),            # west shore of the source lake
    "Ana Popović": (296, 662),           # delta capital on the measured coast
}
INDIV_PINS = {                                # hand seats, moved alone, never clamped
    "Trombone Shorty & Orleans Avenue": (654, 556),   # Big Muddy's east bank
    "Jon Batiste": (590, 572),                # the Parade's east bank
    "Amythyst Kiah": (238, 596),              # southwest along the tidewater
    "The Wood Brothers": (422, 452),          # heartland side of the woods border
    "Oliver Wood": (430, 426),                # woods side, within sight of the band
    "Alabama Shakes": (631, 318),             # range heel, toward the Foothills
    "Sue Foley": (615, 334),                  # likewise
    "Barenaked Ladies": (703, 204),           # the neck's northwest shore
}
LAKESIDE = [(430, 246), (358, 318)]           # each shoulder lake gets a district

_shifted = set()
def shift_district(name, target):
    """First pin in a district moves the whole crew; later pins move only the name."""
    if name not in xy:
        return
    did = district_of.get(name)
    if did in _shifted or did not in districts:
        xy[name] = target
        return
    dx_, dy_ = target[0] - xy[name][0], target[1] - xy[name][1]
    for m in districts[did]["members"]:
        if m in xy:
            xy[m] = (xy[m][0] + dx_, xy[m][1] + dy_)
    _shifted.add(did)

for nm, tgt in CANON_PINS.items():
    shift_district(nm, tgt)
for nm, tgt in INDIV_PINS.items():
    if nm in xy:
        xy[nm] = tgt

WATERFRONT = set(CANON_PINS) | set(INDIV_PINS)

# the two largest non-capital Quiet Woods districts take the shoulder-lake shores
woods_ds = sorted((d_ for d_, dd in districts.items()
                   if dd["region"] == "quiet_woods" and not d_.endswith(":outskirts")
                   and "The Lone Bellow" not in dd["members"]),
                  key=lambda d_: -len(districts[d_]["members"]))[:2]
for d_, (lx_, ly_) in zip(woods_ds, LAKESIDE):
    seat_ = districts[d_]["seat"]
    shift_district(seat_, (lx_ + 40, ly_ + 24))
    WATERFRONT.add(seat_)


# final land pass: district shifts may have carried mates seaward
for c in records:
    if region_of[c] == "outer_isles" or c not in xy or c in WATERFRONT:
        continue
    tw = REGIONS[region_of[c]]["anchor"]
    xy[c] = clamp_to_land(xy[c][0], xy[c][1], tw)

# hazard pass: keep everyone off the carved water (rivers, harbor, lakes)
_ww = {w["id"]: w for w in WATERWAYS}
_riv_segs = []
for wid, ext in (("the_bigmuddy", (648, 665)), ("the_parade", (636, 618)), ("slowhand_creek", None)):
    pts = [tuple(p) for p in _ww[wid]["points"]] + ([ext] if ext else [])
    _riv_segs += list(zip(pts, pts[1:]))
_lakes = ([(tuple(_ww["the_forest_lake"]["points"][0]), 20)]
          + [(tuple(p), 14) for p in _ww["the_knob_lakes"]["points"]]
          + [(tuple(p), 34) for p in _ww["the_shoulder_lakes"]["points"]])
_HARBOR = ((642, 592), 62)

def hazard_push(x, y):
    best_d, push = 1e9, None
    for a_, b_ in _riv_segs:
        d_ = _seg_dist((x, y), a_, b_)
        if d_ < best_d:
            vx_, vy_ = b_[0] - a_[0], b_[1] - a_[1]; L2 = vx_ * vx_ + vy_ * vy_ or 1e-9
            t_ = max(0, min(1, ((x - a_[0]) * vx_ + (y - a_[1]) * vy_) / L2))
            nx_, ny_ = x - (a_[0] + t_ * vx_), y - (a_[1] + t_ * vy_)
            best_d, push = d_, (nx_, ny_, 15)
    for (lc, lr) in _lakes + [_HARBOR]:
        d_ = math.hypot(x - lc[0], y - lc[1])
        if d_ - lr < best_d:
            best_d, push = d_ - lr, (x - lc[0], y - lc[1], lr + 12)
    if push is None or best_d >= 13:
        return (x, y)
    nx_, ny_, want = push
    n_ = math.hypot(nx_, ny_) or 1
    return (x + nx_ / n_ * (want - best_d), y + ny_ / n_ * (want - best_d))

for c in records:
    if region_of[c] == "outer_isles" or c not in xy or c in WATERFRONT:
        continue
    hx, hy = hazard_push(*xy[c])
    if (hx, hy) != xy[c]:
        xy[c] = clamp_to_land(hx, hy, REGIONS[region_of[c]]["anchor"])

# breathing space: relax overlapping settlement marks apart
IMMOVABLE = WATERFRONT | {"Tedeschi Trucks Band", "Sonny Landreth"}
def mark_r(c):
    return min(2.6 + score(c) / 5.5, 6.5)
mainland = [c for c in records if region_of[c] != "outer_isles" and c in xy]
def tidy():
    for c in mainland:
        if c in IMMOVABLE:
            continue
        hx, hy = hazard_push(*clamp_to_land(xy[c][0], xy[c][1], REGIONS[region_of[c]]["anchor"]))
        xy[c] = (hx, hy)
def relax(rounds):
    for _pass in range(rounds):
        moved = False
        for i in range(len(mainland)):
            a_ = mainland[i]; ax_, ay_ = xy[a_]
            for j in range(i + 1, len(mainland)):
                b_ = mainland[j]
                d_ = math.hypot(xy[b_][0] - ax_, xy[b_][1] - ay_)
                need = mark_r(a_) + mark_r(b_) + 4.5
                if d_ >= need or d_ == 0:
                    continue
                push = (need - d_) / 2
                nx_, ny_ = (xy[b_][0] - ax_) / d_, (xy[b_][1] - ay_) / d_
                if a_ not in IMMOVABLE:
                    xy[a_] = (xy[a_][0] - nx_ * push, xy[a_][1] - ny_ * push)
                    ax_, ay_ = xy[a_]
                if b_ not in IMMOVABLE:
                    xy[b_] = (xy[b_][0] + nx_ * push, xy[b_][1] + ny_ * push)
                moved = True
        if not moved:
            break
tidy(); relax(24); tidy(); relax(18); tidy()

def refresh_isle_islands():
    """Island geometry follows the members - rerun after any hand pins."""
    for did, dd in districts.items():
        if dd["region"] != "outer_isles":
            continue
        pts = [xy[m] for m in dd["members"] if m in xy and region_of[m] == "outer_isles"]
        if not pts:
            continue
        cxp = sum(p[0] for p in pts) / len(pts)
        cyp = sum(p[1] for p in pts) / len(pts)
        spread = max((math.hypot(p[0] - cxp, p[1] - cyp) for p in pts), default=6)
        dd["island_center"] = [round(cxp, 1), round(cyp, 1)]
        dd["island_r"] = round(min(max(spread + 7, 10), 22), 1)



    """Island geometry follows the members - rerun after any hand pins."""
    for did, dd in districts.items():
        if dd["region"] != "outer_isles":
            continue
        pts = [xy[m] for m in dd["members"] if m in xy and region_of[m] == "outer_isles"]
        if not pts:
            continue
        cxp = sum(p[0] for p in pts) / len(pts)
        cyp = sum(p[1] for p in pts) / len(pts)
        spread = max((math.hypot(p[0] - cxp, p[1] - cyp) for p in pts), default=6)
        dd["island_center"] = [round(cxp, 1), round(cyp, 1)]
        dd["island_r"] = round(min(max(spread + 7, 10), 22), 1)


# The pegs: each Outer Isles district is its own island flanking the headstock.
AXIS_G = math.radians(-38); HEEL_G = (645, 325)
ug = (math.cos(AXIS_G), math.sin(AXIS_G)); vg = (-math.sin(AXIS_G), math.cos(AXIS_G))
isle_ds = sorted((did for did, dd in districts.items() if dd["region"] == "outer_isles"),
                 key=lambda did: -len(districts[did]["members"]))
for pi, did in enumerate(isle_ds):
    dd = districts[did]
    k = pi // 2
    side = 1 if pi % 2 else -1
    t = 246 + ((0, 54, 108) if side < 0 else (6, 56, 100))[k]
    off = side * (116 + (0, 12, -8)[k])
    cxp = HEEL_G[0] + ug[0] * t + vg[0] * off
    cyp = HEEL_G[1] + ug[1] * t + vg[1] * off
    cxp = min(max(cxp, 20), 978); cyp = min(max(cyp, 18), 260)
    n = len(dd["members"])
    r_isl = min(7.5 + 2.0 * math.sqrt(n), 14) * (1.0, 0.82, 1.14)[k]
    dd["island_center"] = [round(cxp, 1), round(cyp, 1)]
    dd["island_r"] = round(r_isl, 1)
    ring = max(3.0, r_isl - 6)
    for j, m in enumerate(sorted(dd["members"])):
        ang = j * 2.399963  # golden angle
        rr = ring * math.sqrt((j + 0.5) / max(n, 1))
        xy[m] = (cxp + rr * math.cos(ang), cyp + rr * math.sin(ang))

# ---- arrivals: discovered settlements and fast-track towns, staged for hand placement ----
SIZE_OVERRIDE = {}
UNPLACED = set()
def staging_ring(members, sx_, sy_):
    for j, m in enumerate(members):
        ang = j * 2.399963
        rr = (4 + 1.15 * math.sqrt(len(members))) * math.sqrt((j + 0.5) / len(members))
        xy[m] = (sx_ + rr * math.cos(ang), sy_ + rr * math.sin(ang))

disc_path = SCRIPT_DIR / "discovered_adds.json"
if disc_path.exists():
    adds = json.loads(disc_path.read_text())
    next_id = max(r["id"] for r in records.values()) + 1
    by_reg = defaultdict(list)
    for a_ in adds:
        nm, reg_, sz = a_["name"], a_["region"], a_["size"]
        if nm in records:
            continue
        records[nm] = {"id": next_id, "canonical": nm, "status": "seen-support",
                       "tier": None, "sources": ["seen-support"]}
        next_id += 1
        seen_meta[nm] = {"times_seen": 1}
        region_of[nm] = reg_
        SIZE_OVERRIDE[nm] = sz
        UNPLACED.add(nm)
        by_reg[reg_].append(nm)
    # islanders arrive on their own anchorage; mainlanders stage inside their region
    if by_reg.get("outer_isles"):
        did = "outer_isles:arrivals"
        mem = sorted(by_reg.pop("outer_isles"))
        districts[did] = {"region": "outer_isles", "members": mem,
                          "seat": mem[0], "suggested_name": "Arrivals Anchorage"}
        for m in mem:
            district_of[m] = did
        staging_ring(mem, 925, 95)
    for reg_, mem in by_reg.items():
        spec_ = REGIONS[reg_]
        sx_, sy_ = clamp_to_land(spec_["anchor"][0] + spec_["rx"] * 0.45,
                                 spec_["anchor"][1] - spec_["ry"] * 0.45, spec_["anchor"])
        staging_ring(sorted(mem), sx_, sy_)
        for m in mem:
            district_of[m] = f"{reg_}:arrivals"

# every unpinned never-seen mainlander stages with the arrivals for hand placement
_pins_now = json.loads((SCRIPT_DIR / "pins.json").read_text()) if (SCRIPT_DIR / "pins.json").exists() else {}
_stage = defaultdict(list)
for c in records:
    if (seen_meta.get(c, {}).get("times_seen") or c in _pins_now or c in UNPLACED
            or region_of[c] == "outer_isles" or c not in xy):
        continue
    UNPLACED.add(c)
    _stage[region_of[c]].append(c)
for reg_, mem in _stage.items():
    spec_ = REGIONS[reg_]
    sx_, sy_ = clamp_to_land(spec_["anchor"][0] - spec_["rx"] * 0.4,
                             spec_["anchor"][1] + spec_["ry"] * 0.4, spec_["anchor"])
    staging_ring(sorted(mem), sx_, sy_)

# every fast-track artist holds an unvisited town, staged with the arrivals
for c in list(records):
    if "fast_track" in records[c].get("sources", []) and not seen_meta.get(c, {}).get("times_seen"):
        SIZE_OVERRIDE[c] = "town"
        UNPLACED.add(c)
        reg_ = region_of[c]
        spec_ = REGIONS[reg_]
        sx_, sy_ = clamp_to_land(spec_["anchor"][0] + spec_["rx"] * 0.45,
                                 spec_["anchor"][1] - spec_["ry"] * 0.45, spec_["anchor"])
        jr2 = random.Random(f"{RNG_SEED}:ft:{c}")
        xy[c] = (sx_ + (jr2.random() - 0.5) * 26, sy_ + (jr2.random() - 0.5) * 20)

# island decree: applied after pins by explicit instruction (supersedes)
DECREE_MOVES = {
    "Danielle Ponder": ("delta_coast", (190.0, 556.0)),   # joins Nichols on The Lonesome
    "Ziggy Marley": ("river_port", (651.0, 611.0)),       # Reggae Isle (Mavis's old ground)
    "Jah Works": ("river_port", (655.5, 617.5)),
}
DECREE_ASHORE = {"Mavis Staples": "river_port"}           # back to the mainland, staged

# Dan's pins are law: name -> [x, y], applied verbatim, never clamped
pins_path = SCRIPT_DIR / "pins.json"
if pins_path.exists():
    for nm, p_ in json.loads(pins_path.read_text()).items():
        if nm in xy:
            xy[nm] = (float(p_[0]), float(p_[1]))
            UNPLACED.discard(nm)   # a pinned settlement is a placed settlement
    # a pinned islander joins the crew whose island he actually stands on
    isle_crews = [d_ for d_, dd in districts.items()
                  if dd["region"] == "outer_isles" and not d_.endswith(":outskirts")]
    for nm in json.loads(pins_path.read_text()):
        if region_of.get(nm) != "outer_isles" or nm not in xy:
            continue
        def crew_center(d_, excl):
            pts = [xy[m] for m in districts[d_]["members"] if m in xy and m != excl]
            return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)) if pts else None
        best = min((d_ for d_ in isle_crews if crew_center(d_, nm)),
                   key=lambda d_: math.hypot(xy[nm][0] - crew_center(d_, nm)[0],
                                             xy[nm][1] - crew_center(d_, nm)[1]))
        cur = district_of.get(nm)
        if best != cur:
            if cur in districts and nm in districts[cur]["members"]:
                districts[cur]["members"].remove(nm)
            districts[best]["members"].append(nm)
            districts[best]["members"].sort()
            district_of[nm] = best
    refresh_isle_islands()

# ---- source references: a short "why on the map" line per non-seen settlement ----
def _read_tsv(p):
    import csv as _csv
    try:
        return list(_csv.DictReader(open(p), delimiter="\t"))
    except FileNotFoundError:
        return []
_ft_why = {r["Artist"]: (r.get("Why Fast Track") or "").strip()
           for r in _read_tsv(ROOT / "data" / "fast_track.tsv")}
_fm_note = {r["Artist"]: (r.get("Notes") or "").strip()
            for r in _read_tsv(SCRIPT_DIR / "follows_master_cache.tsv")}
_pot = {}
for r in _read_tsv(SCRIPT_DIR / "potential_cache.tsv"):
    a_ = r.get("Artist", "").strip()
    if a_ and a_ not in _pot:
        _pot[a_] = f"potential: {r.get('Decision','?')} @ {r.get('Venue','?')} {r.get('Date','')}".strip()

def _trim(t, n=70):
    return t if len(t) <= n else t[:n].rsplit(" ", 1)[0] + "\u2026"

def source_ref(c):
    srcs = records[c].get("sources", [])
    if seen_meta.get(c, {}).get("via_history"):
        return "seen as support (history TSVs; no artists.tsv row)"
    if seen_meta.get(c, {}).get("times_seen") and "seen-support" not in srcs:
        return ""
    if "seen-support" in srcs or records[c].get("status") == "seen-support":
        return "history pass: seen as support"
    if seen_meta.get(c, {}).get("via_history"):
        return "seen as support (history TSVs; no artists.tsv row)"
    if "fast_track" in srcs:
        why = _ft_why.get(c, "")
        return _trim(("fast track: " + why) if why else "fast track list")
    if "potential" in srcs and c in _pot:
        return _trim(_pot[c])
    if "potential" in srcs:
        return "on the potentials list"
    if "follow" in srcs:
        note = _fm_note.get(c, "")
        tier = records[c].get("tier") or "untier'd"
        return _trim((f"follow ({tier})" + (": " + note if note else "")))
    return ", ".join(srcs)

# ---- curated adjustments: islands sorted, ruins fall, harbormistresses appointed ----
_pins_law = (json.loads((SCRIPT_DIR / "pins.json").read_text())
             if (SCRIPT_DIR / "pins.json").exists() else {})
MAP_RENAME = {"New York's Finest": "Every Breath You Take"}   # current performing name
CURATED_SIZE = {
    "George Clinton & Parliament-Funkadelic": "town",
    "Hozier": "city", "Every Breath You Take": "town",
    "Enter the Haggis": "town", "Kate Davis": "town",
    "Glen Hansard": "town", "L\u012bve": "village",
    "Joan Jett & The Blackhearts": "village",
    "Danny Burns": "town",
}
RUINS = {"Enter the Haggis", "Talia Segal", "Glen Hansard"}
HARBORMISTRESSES = {"Ally Venable Band", "Vanessa Collier", "Sue Foley",
                    "Jackie Venson", "Orianthi", "Queen Latifah"}
PEG_CREW = {   # name -> crew; the eye-test canon of 2026-09-05
    "Every Breath You Take": "p3", "Jessie's Girl": "p3", "Honeyfunk": "p3",
    "La Unica": "p3", "The Side Cars Band": "p3", "Zedicus & Abyssinia Roots": "p3",
    "Young Dubliners": "p1", "Cassie & Maggie": "p1", "Gaelic Storm": "p1",
    "Haggis X-1": "p1", "House of Hamill": "p1", "Enter the Haggis": "p1",
    "Danny Burns": "p1",
    "The Roots": "p4", "Wu-Tang Clan": "p4", "Bone Thugs-n-Harmony": "p4",
    "DJ Jazzy Jeff": "p4", "De La Soul": "p4", "LL Cool J": "p4",
    "Nas": "p4", "Z-Trip": "p4",
    "Hozier": "p6", "Chelsea Cutler": "p6", "Gigi Perez": "p6",
    "Valley": "p6", "Zara Larsson": "p6", "kitchen": "p6",
    "Kate Davis": "p5", "Sadurn": "p5", "Brassie": "p5",
    "Mystery Friends": "p5", "The House You Grew Up In (THYGUI)": "p5",
    "Talia Segal": "p5", "Chris Jacobs & Friends": "p5",
    "Hayley Williams": "p5", "Muna": "p5", "Zara Phillips": "p5",
    "AJR": "p2",
}

CURATED_ISLES = {   # crew -> (seat, island name)
    "outer_isles:p1": ("Young Dubliners", "Innis Craic"),
    "outer_isles:p2": ("AJR", "Pop Rock"),
    "outer_isles:p3": ("Every Breath You Take", "Cover Band Cay"),
    "outer_isles:p4": ("The Roots", "Hip Hop Haven"),
    "outer_isles:p5": ("Kate Davis", "Fempop Skree"),
    "outer_isles:p6": ("Hozier", "Indiesoul Isle"),
}

def rename_settlement(old, new):
    if old not in records:
        return
    records[new] = {**records.pop(old), "canonical": new}
    for dmap in (seen_meta, SIZE_OVERRIDE):
        if old in dmap: dmap[new] = dmap.pop(old)
    for smap in (region_of, district_of):
        if old in smap: smap[new] = smap.pop(old)
    if old in xy: xy[new] = xy.pop(old)
    if old in UNPLACED: UNPLACED.discard(old); UNPLACED.add(new)
    for dd in districts.values():
        dd["members"] = [new if m == old else m for m in dd["members"]]
        if dd.get("seat") == old: dd["seat"] = new
for _o, _n in MAP_RENAME.items():
    rename_settlement(_o, _n)

def move_to_region(nm, reg_, stage=True):
    if nm not in records: return
    old_d = district_of.get(nm)
    if old_d in districts and nm in districts[old_d]["members"]:
        districts[old_d]["members"].remove(nm)
    region_of[nm] = reg_
    district_of[nm] = f"{reg_}:arrivals"
    if stage and nm not in _pins_law:
        UNPLACED.add(nm)
        spec_ = REGIONS[reg_]
        jr3 = random.Random(f"{RNG_SEED}:cur:{nm}")
        sx_, sy_ = clamp_to_land(spec_["anchor"][0] + spec_["rx"] * 0.45,
                                 spec_["anchor"][1] - spec_["ry"] * 0.45, spec_["anchor"])
        xy[nm] = (sx_ + (jr3.random() - 0.5) * 24, sy_ + (jr3.random() - 0.5) * 18)

move_to_region("George Clinton & Parliament-Funkadelic", "river_port")
move_to_region("DuPont Brass", "river_port")
move_to_region("Queen Latifah", "river_port")
move_to_region("L\u012bve", "amplified_range", stage=False)   # Dan's pin already mainlands him
# AJR Rock is one-of-one: the rest of the old funk crew stages at the Anchorage
_p2 = districts.get("outer_isles:p2")
if _p2:
    for m in [m for m in _p2["members"] if m != "AJR"]:
        _p2["members"].remove(m)
        districts["outer_isles:arrivals"]["members"].append(m)
        district_of[m] = "outer_isles:arrivals"
        if m not in _pins_law:
            UNPLACED.add(m)
    districts["outer_isles:arrivals"]["members"].sort()
# Brassie and Sadurn emigrate to Fempop Skree (final placement is Dan's)
for m in ("Brassie", "Sadurn"):
    if m in records:
        old_d = district_of.get(m)
        if old_d in districts and m in districts[old_d]["members"]:
            districts[old_d]["members"].remove(m)
        region_of[m] = "outer_isles"
        district_of[m] = "outer_isles:p5"
        districts["outer_isles:p5"]["members"].append(m)
        if m not in _pins_law:
            ic5 = districts["outer_isles:p5"].get("island_center", [960, 240])
            jr4 = random.Random(f"{RNG_SEED}:fp:{m}")
            xy[m] = (ic5[0] + (jr4.random() - 0.5) * 10, ic5[1] + (jr4.random() - 0.5) * 8)
            UNPLACED.add(m)
districts["outer_isles:p5"]["members"].sort()
# PEG_CREW is law: explicit crew assignment overrides proximity drift
for nm, crew in PEG_CREW.items():
    did = f"outer_isles:{crew}"
    if nm not in records or did not in districts:
        continue
    cur = district_of.get(nm)
    if cur == did:
        continue
    if cur in districts and nm in districts[cur]["members"]:
        districts[cur]["members"].remove(nm)
    if region_of.get(nm) == "outer_isles":
        districts[did]["members"].append(nm)
        districts[did]["members"].sort()
        district_of[nm] = did
for did in [d_ for d_, dd in districts.items()
            if dd["region"] == "outer_isles" and not dd["members"]]:
    del districts[did]
for did, (seat_, iname_) in CURATED_ISLES.items():
    if did in districts:
        districts[did]["seat"] = seat_
        districts[did]["suggested_name"] = iname_
refresh_isle_islands()
# crew emigrants without a pin land on their island's shore ring
for nm, crew in PEG_CREW.items():
    did = f"outer_isles:{crew}"
    if (nm not in xy or nm in _pins_law or did not in districts
            or district_of.get(nm) != did):
        continue
    ic_ = districts[did].get("island_center")
    ir_ = districts[did].get("island_r", 12)
    if ic_ and math.hypot(xy[nm][0] - ic_[0], xy[nm][1] - ic_[1]) > ir_:
        jr6 = random.Random(f"{RNG_SEED}:crew:{nm}")
        ang_ = jr6.random() * 6.28318
        rr_ = max(ir_ - 5, 3) * jr6.random()
        xy[nm] = (ic_[0] + rr_ * math.cos(ang_), ic_[1] + rr_ * math.sin(ang_))
refresh_isle_islands()

# Dan's viewer overrides (map_overrides.json): region and size, position untouched
OVERRIDE_SIZE = {}
ov_path = SCRIPT_DIR / "map_overrides.json"
if ov_path.exists():
    for nm, ov in json.loads(ov_path.read_text()).items():
        if nm not in records:
            continue
        if ov.get("region") and ov["region"] in REGIONS and ov["region"] != region_of.get(nm):
            old_d = district_of.get(nm)
            if old_d in districts and nm in districts[old_d]["members"]:
                districts[old_d]["members"].remove(nm)
            region_of[nm] = ov["region"]
            district_of[nm] = f"{ov['region']}:override"
            spec_o = REGIONS[ov["region"]]
            ex_ = (xy[nm][0] - spec_o["anchor"][0]) / spec_o["rx"]
            ey_ = (xy[nm][1] - spec_o["anchor"][1]) / spec_o["ry"]
            if ex_ * ex_ + ey_ * ey_ > 1.1:   # far outside: restage near the new home
                jr5 = random.Random(f"{RNG_SEED}:ov:{nm}")
                sx_, sy_ = clamp_to_land(spec_o["anchor"][0] + spec_o["rx"] * 0.45,
                                         spec_o["anchor"][1] - spec_o["ry"] * 0.45, spec_o["anchor"])
                xy[nm] = (sx_ + (jr5.random() - 0.5) * 24, sy_ + (jr5.random() - 0.5) * 18)
                UNPLACED.add(nm)
        if ov.get("size"):
            OVERRIDE_SIZE[nm] = ov["size"]
    refresh_isle_islands()

_decree_pins = (set(json.loads((SCRIPT_DIR / "pins.json").read_text()))
                if (SCRIPT_DIR / "pins.json").exists() else set())
for nm, (reg_, pt_) in DECREE_MOVES.items():
    if nm in records:
        region_of[nm] = reg_
        if nm not in _decree_pins:      # a fresh pin outranks the decree
            xy[nm] = pt_
        UNPLACED.discard(nm)
for nm, reg_ in DECREE_ASHORE.items():
    if nm in records:
        region_of[nm] = reg_
        if nm in _decree_pins:
            continue
        spec_ = REGIONS[reg_]
        jr7 = random.Random(f"{RNG_SEED}:ashore:{nm}")
        sx_, sy_ = clamp_to_land(spec_["anchor"][0] - spec_["rx"] * 0.3,
                                 spec_["anchor"][1] - spec_["ry"] * 0.5, spec_["anchor"])
        xy[nm] = (sx_ + (jr7.random() - 0.5) * 20, sy_ + (jr7.random() - 0.5) * 14)
        UNPLACED.add(nm)

for did in [d_ for d_, dd in districts.items()
            if dd["region"] == "outer_isles" and not dd["members"]]:
    del districts[did]

settlements = []
reg_max = {reg: max((score(c) for c in records if region_of[c] == reg), default=0)
           for reg in REGIONS}
for c in sorted(records):
    s = score(c)
    reg = region_of[c]
    spec = REGIONS[reg]
    x, y = xy[c]
    m = seen_meta.get(c, {})
    settlements.append({
        "id": records[c]["id"], "name": c,
        "region": reg, "district": district_of.get(c),
        "size": OVERRIDE_SIZE.get(c) or CURATED_SIZE.get(c) or SIZE_OVERRIDE.get(c) or size_tier(c, s, reg_max[reg]),
        "score": round(s, 1),
        "xy": [round(x, 1), round(y, 1)],
        "region_uv": [round((x - (spec["anchor"][0]-spec["rx"])) / (2*spec["rx"]), 4),
                      round((y - (spec["anchor"][1]-spec["ry"])) / (2*spec["ry"]), 4)],
        "flags": {k: v for k, v in {
            "faded": faded(c),
            "legacy": records[c].get("tier") == "Legacy" or c in LEGENDS,
            "unvisited": not m.get("times_seen"),
            "unplaced": c in UNPLACED,
            "ruin": c in RUINS,
            "harbormistress": c in HARBORMISTRESSES,
        }.items() if v},
        "src": source_ref(c),
        "times_seen": m.get("times_seen", 0), "vip": m.get("vip", 0),
        "tier": records[c].get("tier"),
    })

# A capital stranded in an outskirts district renames it as its own seat.
cap_by_reg = {st["region"]: st["name"] for st in settlements if st["size"] == "capital"}
for did, d in districts.items():
    if did.endswith(":outskirts") and cap_by_reg.get(d["region"]) in d["members"]:
        cap = cap_by_reg[d["region"]]
        word = re.sub(r"[^A-Za-z]", "", cap.split()[-1]) or "Capital"
        sfx = REGIONS[d["region"]]["toponym_suffixes"][0]
        d["seat"] = cap
        d["suggested_name"] = f"{word} {sfx}"

# convex hull per region (padded) for the boundary layer
def hull_of(pts, pad=16):
    pts = sorted(set((round(x, 1), round(y, 1)) for x, y in pts))
    if len(pts) < 3:
        return None
    def cross(o, a, b): return (a[0]-o[0])*(b[1]-o[1]) - (a[1]-o[1])*(b[0]-o[0])
    lo, up = [], []
    for p in pts:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], p) <= 0: lo.pop()
        lo.append(p)
    for p in reversed(pts):
        while len(up) >= 2 and cross(up[-2], up[-1], p) <= 0: up.pop()
        up.append(p)
    hull = lo[:-1] + up[:-1]
    cx_ = sum(p[0] for p in hull) / len(hull); cy_ = sum(p[1] for p in hull) / len(hull)
    out = []
    for x, y in hull:
        dx, dy = x - cx_, y - cy_
        d = math.hypot(dx, dy) or 1
        out.append([round(x + dx / d * pad, 1), round(y + dy / d * pad, 1)])
    return out

region_hulls = {}
for reg in REGIONS:
    pts = [xy[c] for c in records if region_of[c] == reg]
    hl = hull_of(pts)
    if hl:
        region_hulls[reg] = hl

# gateways: each ordered region pair gets one crossing point per side, so
# cross-region routes bundle into shared corridors instead of great circles
def edge_point(reg, toward):
    ax, ay = REGIONS[reg]["anchor"]; rx_, ry_ = REGIONS[reg]["rx"], REGIONS[reg]["ry"]
    dx, dy = toward[0] - ax, toward[1] - ay
    d = math.hypot(dx, dy) or 1; ux_, uy_ = dx / d, dy / d
    er = (rx_ * ry_) / math.hypot(ry_ * ux_, rx_ * uy_)
    return (ax + ux_ * er * 0.94, ay + uy_ * er * 0.94)

gates = {}
def gate_pair(ra, rb):
    key = (ra, rb) if ra < rb else (rb, ra)
    if key not in gates:
        pa = edge_point(key[0], REGIONS[key[1]]["anchor"])
        pb = edge_point(key[1], REGIONS[key[0]]["anchor"])
        gates[key] = (pa, pb)
    pa, pb = gates[key]
    return (pa, pb) if (ra, rb) == key else (pb, pa)

routes = []
for key, cls in sorted(edges.items(), key=lambda kv: sorted(kv[0])):
    a, b = sorted(key)
    if a not in region_of or b not in region_of:
        continue
    cross = region_of[a] != region_of[b]
    render = cls
    if cross:
        if "outer_isles" in (region_of[a], region_of[b]):
            render = "ferry"
        elif "amplified_range" in (region_of[a], region_of[b]):
            render = "pass"
        else:
            render = "highway"
    entry = {"a": a, "b": b, "cls": cls, "crossRegion": cross, "render": render}
    if cross:
        ga, gb = gate_pair(region_of[a], region_of[b])
        entry["via"] = [[round(ga[0], 1), round(ga[1], 1)], [round(gb[0], 1), round(gb[1], 1)]]
    routes.append(entry)

# ---- labels.json is the single authority for every label placement ----
# {"regions": {id: {xy, size, lines?}}, "islands": {name: xy}, "waters": {name: xy}}
# Edit by hand, or drag labels in map.html edit mode and export the file.
# Regions fall back to spec/anchor; islands and waters not in the file are not drawn.
_labels_path = SCRIPT_DIR / "labels.json"
LABELS = (json.loads(_labels_path.read_text())
          if _labels_path.exists() else {"regions": {}, "islands": {}, "waters": {}})

out = {
    "water_labels": [{"name": nm_, "xy": xy_} for nm_, xy_ in LABELS["waters"].items()],
    "canonical_islets": [
        {"xy": [185, 617], "r": [10, 7]},    # Foremothers
        {"xy": [216, 641], "r": [11, 7]},    # Kings' Rest
        {"xy": [658, 636], "r": [11, 8]},    # Funk Atoll landing
    ],
    "island_labels": [{"name": nm_, "xy": xy_} for nm_, xy_ in LABELS["islands"].items()],
    "meta": {"generated_from": idx.get("generated"), "seed": RNG_SEED,
             "pins_hash": hashlib.md5((SCRIPT_DIR / "pins.json").read_bytes()).hexdigest()[:10]
                          if (SCRIPT_DIR / "pins.json").exists() else None,
             "overrides_hash": hashlib.md5((SCRIPT_DIR / "map_overrides.json").read_bytes()).hexdigest()[:10]
                          if (SCRIPT_DIR / "map_overrides.json").exists() else None,
             "counts": {"settlements": len(settlements), "routes": len(routes),
                        "districts": len(districts)}},
    "canvas": CANVAS,
    "regions": [{"id": rid, **{k: v for k, v in spec.items()
                               if k not in ("toponym_suffixes", "toponym_prefixes")},
                 "anchor": list(spec["anchor"]),
                 "label_xy": LABELS["regions"].get(rid, {}).get("xy",
                              list(spec.get("label_xy", spec["anchor"]))),
                 "label_lines": LABELS["regions"].get(rid, {}).get("lines",
                              spec.get("label_lines")),
                 "label_size": LABELS["regions"].get(rid, {}).get("size",
                              spec.get("label_size")),
                 "hull": region_hulls.get(rid)} for rid, spec in REGIONS.items()],
    "waterways": [{**w, "points": [list(p) for p in w["points"]]} for w in WATERWAYS],
    "districts": [{"id": did, **d} for did, d in sorted(districts.items())],
    "settlements": settlements,
    "routes": routes,
}
OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False))
print(f"wrote {OUT}: {len(settlements)} settlements, {len(routes)} routes, "
      f"{len(districts)} districts")
for reg in REGIONS:
    n = sum(1 for s in settlements if s["region"] == reg)
    cap = next((s["name"] for s in settlements if s["region"] == reg and s["size"] == "capital"), "-")
    print(f"  {reg:16s} {n:3d} settlements, capital: {cap}")
