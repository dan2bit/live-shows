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
import argparse, ast, csv, json, math, os, random, re, sys
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
        "label": "The Delta Coast",
        "terrain": "coastal tidewater — estuary, levees, shotgun porches",
        "anchor": (300, 560), "rx": 245, "ry": 92,
        "toponym_suffixes": ["Haven", "Quay", "Levee", "Landing", "Shoals"],
        "toponym_prefixes": ["Port "],
    },
    "amplified_range": {
        "label": "The Amplified Range",
        "terrain": "high mountains — basalt cliffs, feedback storms",
        "anchor": (790, 205), "rx": 175, "ry": 125,
        "toponym_suffixes": ["Crag", "Pass", "Summit", "Overdrive", "Ridge"],
        "toponym_prefixes": ["Mount "],
    },
    "slide_foothills": {
        "label": "The Steel Foothills",
        "terrain": "foothills - slide scarps, steel terraces, bottleneck switchbacks",
        "anchor": (650, 292), "rx": 102, "ry": 74,
        "toponym_suffixes": ["Scarp", "Terrace", "Rise", "Switchback", "Bend"],
        "toponym_prefixes": ["Steel "],
    },
    "heartland": {
        "label": "The Heartland",
        "terrain": "farmland plains — wheat, gravel roads, grain towers",
        "anchor": (515, 375), "rx": 235, "ry": 115,
        "toponym_suffixes": ["Hollow", "Fields", "Prairie", "Crossing", "Silo"],
        "toponym_prefixes": [],
    },
    "river_port": {
        "label": "Second Line Riverlands",
        "terrain": "riverside port — wharves, brass balconies, paddle steam",
        "anchor": (668, 555), "rx": 150, "ry": 82,
        "toponym_suffixes": ["Wharf", "Landing", "Parade", "Bend", "Ward"],
        "toponym_prefixes": [],
    },
    "quiet_woods": {
        "label": "The Quiet Woods",
        "terrain": "forest and lakes — pine shade, cabin lights, still water",
        "anchor": (230, 200), "rx": 195, "ry": 125,
        "toponym_suffixes": ["Glen", "Hollow", "Lake", "Grove", "Vale"],
        "toponym_prefixes": [],
    },
    "outer_isles": {
        "label": "The Outer Isles",
        "terrain": "offshore archipelago continuing the range's line north - ferry weather, distant genres",
        "anchor": (900, 62), "rx": 88, "ry": 48,
        "toponym_suffixes": ["Isle", "Skerry", "Sound", "Rock"],
        "toponym_prefixes": ["Isle of "],
    },
}

# Waterway suggestions (polylines, canvas units). The design layer may redraw;
# routes reference these only thematically.
WATERWAYS = [
    {"id": "the_bigmuddy", "label": "The Big Muddy",
     "points": [(838, 128), (762, 248), (662, 328), (582, 428), (602, 518), (642, 588), (656, 648)],
     "note": "rises where the massif meets the north coast, runs the range's southwest slope past the Steel Foothills, and spills into the sheltered bay"},
    {"id": "slowhand_creek", "label": "Slowhand Creek",
     "points": [(246, 256), (322, 332), (422, 402), (512, 438), (582, 428)],
     "note": "rises from a forest lake in the Quiet Woods and joins the Big Muddy above the foothill reach"},
    {"id": "the_sound", "label": "The Wide Water",
     "points": [(0, 690), (240, 665), (520, 672), (1000, 680)],
     "note": "the southern sea; the sheltered bay opens off it at the Big Muddy mouth"},
    {"id": "the_north_reach", "label": "The North Reach",
     "points": [(0, 30), (400, 42), (760, 36), (1000, 48)],
     "note": "the northern sea; the massif runs to its shore and the Outer Isles continue the range line offshore"},
    {"id": "the_central_sound", "label": "The Chainwater Sound",
     "points": [(300, 70), (452, 58), (610, 72)],
     "note": "the north sea's central inroad; a short coastal range (the Chain) holds its south shore"},
    {"id": "the_west_water", "label": "The West Water",
     "points": [(30, 60), (34, 240), (28, 420), (40, 600)],
     "note": "fjord coast off the Quiet Woods; ragged fingers, no settlements"},
    {"id": "the_east_shore", "label": "The East Shore",
     "points": [(965, 150), (952, 340), (958, 520), (948, 640)],
     "note": "eastern shore below the massif's cape; the range is a coastal cordillera"},
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
TIER_SCORE = {"Strong": 3, "Medium-Strong": 2, "Medium": 1, "Lower": 0.5, "Legacy": 2}
def score(c):
    m = seen_meta.get(c, {})
    r = records[c]
    return (3 * min(m.get("times_seen", 0), 8)
            + 2 * m.get("vip", 0)
            + TIER_SCORE.get(r.get("tier"), 0))

CAPITAL_OVERRIDE = {"slide_foothills": "Larkin Poe"}

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

xy = {}
for reg, spec in REGIONS.items():
    members = [c for c in records if region_of[c] == reg]
    if not members:
        continue
    sub = G.subgraph(members)
    pos = nx.spring_layout(sub, weight="weight", seed=RNG_SEED,
                           k=1.6 / max(math.sqrt(len(members)), 1))
    xy.update(ellipse_fit(pos, spec["anchor"], spec["rx"], spec["ry"]))

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
        "size": size_tier(c, s, reg_max[reg]), "score": round(s, 1),
        "xy": [round(x, 1), round(y, 1)],
        "region_uv": [round((x - (spec["anchor"][0]-spec["rx"])) / (2*spec["rx"]), 4),
                      round((y - (spec["anchor"][1]-spec["ry"])) / (2*spec["ry"]), 4)],
        "flags": {k: v for k, v in {
            "faded": faded(c),
            "legacy": records[c].get("tier") == "Legacy",
            "unvisited": m.get("times_seen", 0) == 0,
        }.items() if v},
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
    routes.append({"a": a, "b": b, "cls": cls, "crossRegion": cross, "render": render})

out = {
    "meta": {"generated_from": idx.get("generated"), "seed": RNG_SEED,
             "counts": {"settlements": len(settlements), "routes": len(routes),
                        "districts": len(districts)}},
    "canvas": CANVAS,
    "regions": [{"id": rid, **{k: v for k, v in spec.items()
                               if k not in ("toponym_suffixes", "toponym_prefixes")},
                 "anchor": list(spec["anchor"])} for rid, spec in REGIONS.items()],
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
