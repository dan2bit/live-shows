#!/usr/bin/env python3
"""
emit_heightmap.py — landmask-first heightmap seed for Azgaar's FMG, generated
from fantasy_map_data.json. Lighter = higher; sea sits near black.

Method: a keep-land field built from the actual settlement positions (plus the
river corridor and range core) guarantees inhabited ground stays dry; everywhere
else, low-frequency noise and four directional sea biases decide the coastline —
north reach with a NE gulf, southern sound, a fjordy west water, and an east
shore that makes the massif a coastal cordillera. The sheltered bay is not
stamped: the river-mouth lowland floods naturally between two spit ridges.

Lives in tools/map/; by default it reads fantasy_map_data.json beside itself
(the build_fantasy_map.py output) and writes heightmap.png next to it.
"""
import argparse, json, sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageFilter

SCRIPT_DIR = Path(__file__).resolve().parent
ap = argparse.ArgumentParser(description="Render the FMG heightmap seed from the fantasy-map JSON.")
ap.add_argument("--data", type=Path, default=SCRIPT_DIR / "fantasy_map_data.json",
                help="fantasy_map_data.json path (default: beside this script)")
ap.add_argument("--out", type=Path, default=SCRIPT_DIR / "heightmap.png",
                help="output PNG path (default: heightmap.png beside this script)")
ap.add_argument("--scale", type=int, default=2,
                help="canvas multiplier; 2 -> 2000x1400 (default 2)")
args = ap.parse_args()
DATA, OUT, SCALE = args.data, args.out, args.scale
SEED = 2026
SEA_T = 0.18   # luminance below this reads as water in FMG

d = json.load(open(DATA))
CW, CH = d["canvas"]["w"], d["canvas"]["h"]
W, H = CW * SCALE, CH * SCALE
regions = {r["id"]: r for r in d["regions"]}
ww = {w["id"]: w for w in d["waterways"]}

yy, xx = np.mgrid[0:H, 0:W].astype(np.float64)
ux, uy = xx / SCALE, yy / SCALE

# ---------------------------------------------------------------- primitives
def value_noise(shape, cells, rng):
    gh, gw = cells
    grid = rng.random((gh + 1, gw + 1))
    ys = np.linspace(0, gh, shape[0], endpoint=False)
    xs = np.linspace(0, gw, shape[1], endpoint=False)
    y0 = ys.astype(int); x0 = xs.astype(int)
    ty = (ys - y0)[:, None]; tx = (xs - x0)[None, :]
    ty = ty * ty * (3 - 2 * ty); tx = tx * tx * (3 - 2 * tx)
    a = grid[np.ix_(y0, x0)]; b = grid[np.ix_(y0, x0 + 1)]
    c = grid[np.ix_(y0 + 1, x0)]; e = grid[np.ix_(y0 + 1, x0 + 1)]
    return a * (1 - tx) * (1 - ty) + b * tx * (1 - ty) + c * (1 - tx) * ty + e * tx * ty

def fbm(shape, base_cells, octaves, rng, gain=0.5):
    out = np.zeros(shape); amp = 1.0; total = 0.0; cells = base_cells
    for _ in range(octaves):
        out += amp * value_noise(shape, cells, rng)
        total += amp; amp *= gain; cells = (cells[0] * 2, cells[1] * 2)
    return out / total

def bump(cx, cy, rx, ry, power=2.0, rot=0.0):
    dx, dy = ux - cx, uy - cy
    if rot:
        c, s = np.cos(rot), np.sin(rot)
        dx, dy = dx * c + dy * s, -dx * s + dy * c
    r = np.sqrt((dx / rx) ** 2 + (dy / ry) ** 2)
    return np.clip(1 - r, 0, 1) ** power

def dist_to_polyline(points):
    dmin = np.full((H, W), 1e9)
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        vx, vy = x2 - x1, y2 - y1
        L2 = vx * vx + vy * vy or 1e-9
        t = np.clip(((ux - x1) * vx + (uy - y1) * vy) / L2, 0, 1)
        dmin = np.minimum(dmin, np.hypot(ux - (x1 + t * vx), uy - (y1 + t * vy)))
    return dmin

def meander(points, wobble=13.0, waves=6.0, samples=260, rkey=0):
    pts = np.array(points, dtype=float)
    seg = np.hypot(*(np.diff(pts, axis=0).T))
    t = np.concatenate([[0], np.cumsum(seg)]); t /= t[-1]
    ts = np.linspace(0, 1, samples)
    x = np.interp(ts, t, pts[:, 0]); y = np.interp(ts, t, pts[:, 1])
    dx = np.gradient(x); dy = np.gradient(y)
    n = np.hypot(dx, dy); nx, ny = -dy / n, dx / n
    r = np.random.default_rng(SEED + 7 + rkey)
    off = (np.sin(ts * waves * 2 * np.pi + r.random() * 6.28) * 0.6
           + (r.random(samples) - 0.5) * 0.8)
    off = np.convolve(off, np.ones(9) / 9, mode="same") * wobble
    return list(zip(x + nx * off, y + ny * off))

def R(rid):
    r = regions[rid]; a = r["anchor"]; return a[0], a[1], r["rx"], r["ry"]

# ---------------------------------------------------------------- keep-land field
# Built at quarter resolution from every settlement, then upsampled: inhabited
# ground and its surroundings can never flood, no matter what the noise wants.
kW, kH = W // 4, H // 4
kx, ky = np.mgrid[0:kH, 0:kW][1] * 4 / SCALE, np.mgrid[0:kH, 0:kW][0] * 4 / SCALE
keep_low = np.zeros((kH, kW))
for st in d["settlements"]:
    if st["region"] == "outer_isles":
        continue          # isle settlements stand on islands drawn from their districts
    x, y = st["xy"]
    r = 34 if st["size"] in ("capital", "city") else 25
    dist = np.hypot(kx - x, ky - y)
    keep_low = np.maximum(keep_low, np.clip(1 - dist / r, 0, 1))
keep = np.asarray(Image.fromarray((keep_low * 255).astype(np.uint8))
                  .resize((W, H), Image.BILINEAR)).astype(np.float64) / 255
keep = np.asarray(Image.fromarray((keep * 255).astype(np.uint8))
                  .filter(ImageFilter.GaussianBlur(4 * SCALE))).astype(np.float64) / 255

# river corridor is land, except the mouth zone where the bay may flood
big_path = meander([tuple(p) for p in ww["the_bigmuddy"]["points"]] + [(660, 700)], rkey=0)
creek_path = meander([tuple(p) for p in ww["slowhand_creek"]["points"]], wobble=10, rkey=1)
big_d = dist_to_polyline(big_path)
creek_d = dist_to_polyline(creek_path)
river_keep = np.clip(1 - np.minimum(big_d, creek_d) / 40, 0, 1)
mouth_zone = bump(656, 628, 96, 86, 1.15)
keep = np.maximum(keep, river_keep * (1 - np.clip(mouth_zone * 1.8, 0, 1)))

# ---------------------------------------------------------------- sea potential
rngL = np.random.default_rng(SEED + 3)
coast_noise = fbm((H, W), (3, 4), 5, rngL) - 0.5           # continental wander
fjord_noise = fbm((H, W), (17, 4), 5, np.random.default_rng(SEED + 11)) - 0.5
# shear the fjord field so its fingers run SW->NE, toward the forest lake
shift = ((-0.85 * xx) % H).astype(int)
rows = (np.arange(H)[:, None] + shift) % H
fjord_diag = fjord_noise[rows, np.arange(W)[None, :]]

# the central-north coastal range: a short chain whose north face is the coast
ridge_n = fbm((H, W), (14, 20), 5, np.random.default_rng(SEED + 14), gain=0.55)
ridge_n = (1 - abs(2 * ridge_n - 1)) ** 1.5
coast_chain = np.clip(bump(365, 96, 62, 27, 1.2, rot=0.08)
                      + bump(455, 84, 64, 26, 1.2, rot=-0.05)
                      + bump(538, 94, 58, 25, 1.2, rot=0.1), 0, 1)

sea = np.zeros((H, W))
smoothg = np.clip((ux - 770) / 150, 0, 1); smoothg = smoothg * smoothg * (3 - 2 * smoothg)
sea += np.clip((46 + 100 * smoothg - uy) / 26, 0, 4) * 0.9   # north reach + NE gulf
sea += np.clip((uy - 622) / 26, 0, 4) * 0.9                  # southern sound
sea += np.clip((66 - ux) / 30, 0, 4) * 0.7                   # west water base
sea += (np.clip((250 - ux) / 250, 0, 1) ** 0.8
        * np.clip((uy - 100) / 220, 0, 1)
        * np.clip(fjord_diag * 4.2, 0, 3.4))                  # SW->NE fjord fingers
sea += bump(55, 65, 160, 140, 1.15) * 1.5                     # the northwest sea
# the central sound: the north sea reaches down to the chain's north face
sea += bump(452, 52, 200, 66, 1.1) * 1.35
# inroads flanking the chain's ends
inroad_noise = np.clip((fbm((H, W), (8, 12), 4, np.random.default_rng(SEED + 15)) - 0.35) * 3.0, 0, 2)
sea += (bump(295, 138, 82, 78, 1.2) + bump(612, 132, 84, 74, 1.2)) * inroad_noise * 1.6
sea -= coast_chain * 2.6                                      # the chain holds the coast
# northeast: the sea wraps the massif's north end into a promontory
sea += bump(1005, 155, 165, 195, 1.1) * 2.0                  # pressing from the east
sea += np.clip((ux - (918 - np.clip(uy - 40, 0, 260) * 0.22)) / 28, 0, 3) * 0.9
# east coast cut: the shore slants southwest toward the bay, with bites
sea += np.clip((ux - (952 - np.clip(uy - 280, 0, 340) * 0.45)) / 34, 0, 3) * 0.75
sea += mouth_zone * 1.9                                       # invite the bay in
sea += coast_noise * 2.3                                      # ragged everything
# the sparse southwest: extra bites between delta settlements
sea += bump(190, 592, 160, 95, 1.3) * np.clip((fbm((H, W), (10, 14), 4,
        np.random.default_rng(SEED + 12)) - 0.42) * 3.0, 0, 2) * 0.9

sea -= keep * 4.0                                           # inhabited ground wins
water = sea > 0.55

# spit ridges flanking the mouth shape the flood into a sheltered bay
spit_w = bump(568, 602, 58, 14, 1.5, rot=0.62) * 0.20
spit_e = bump(748, 596, 58, 14, 1.5, rot=-0.55) * 0.20
# one deterministic assist: the harbor floods properly between the spits
harbor = (bump(654, 622, 64, 50, 1.05) + 0.14 * (fbm((H, W), (12, 16), 3,
          np.random.default_rng(SEED + 13)) - 0.5)) > 0.30
water |= harbor & (uy > 584)
water &= ~((spit_w > 0.10) | (spit_e > 0.10))

# ---------------------------------------------------------------- elevation
elev = np.full((H, W), 0.30)
elev += 0.09 * (fbm((H, W), (6, 8), 5, np.random.default_rng(SEED)) - 0.5)

AXIS = np.deg2rad(-38)
ridge = fbm((H, W), (14, 20), 6, np.random.default_rng(SEED + 1), gain=0.55)
ridge = (1 - abs(2 * ridge - 1)) ** 1.5
spine = np.clip(bump(700, 300, 150, 85, 1.2, AXIS)
                + bump(790, 205, 150, 85, 1.15, AXIS)
                + bump(870, 110, 140, 80, 1.1, AXIS), 0, 1.15)
elev += spine * (0.26 + 0.46 * ridge)

cx, cy, rx, ry = R("slide_foothills")
base = bump(cx, cy, rx * 1.25, ry * 1.3, 1.1)
tn = fbm((H, W), (16, 22), 4, np.random.default_rng(SEED + 8))
shelf = np.round((base + 0.35 * (tn - 0.5)) * 5) / 5 * 0.16 * (base > 0.05)
elev += np.clip(shelf, 0, None) + base * 0.07 * ridge

elev_chain = coast_chain * (0.10 + 0.16 * ridge_n)

cx, cy, rx, ry = R("quiet_woods")
elev += bump(cx, cy, rx * 1.25, ry * 1.3, 1.3) * (
    0.09 + 0.10 * fbm((H, W), (14, 20), 4, np.random.default_rng(SEED + 2)))

cx, cy, rx, ry = R("heartland")
elev -= bump(cx, cy, rx, ry, 2.0) * 0.05
for rid in ("delta_coast", "river_port"):
    cx, cy, rx, ry = R(rid)
    elev -= bump(cx, cy, rx * 1.1, ry * 1.15, 1.5) * 0.10

elev += spit_w + spit_e + elev_chain

# river valleys
for path, wmax, depth in ((big_path, 26, 0.13), (creek_path, 15, 0.09)):
    dist = big_d if path is big_path else creek_d
    prog = np.clip((uy - path[0][1]) / max(path[-1][1] - path[0][1], 1), 0, 1)
    elev -= np.clip(1 - dist / (8 + wmax * prog), 0, 1) ** 1.7 * depth

# forest lake at the creek source
lake = bump(246, 256, 17, 12, 1.3) > 0.25

# keep carved valleys above sea level away from the coast
shore_d = np.asarray(Image.fromarray((~water).astype(np.uint8) * 255)
                     .filter(ImageFilter.GaussianBlur(10 * SCALE))).astype(np.float64) / 255
inland = shore_d > 0.93
elev = np.where(inland & ~lake & (elev < 0.21), 0.21, elev)

# ---------------------------------------------------------------- compose land + sea
depth = 0.10 - 0.07 * np.clip((0.93 - shore_d) / 0.93, 0, 1)   # deeper offshore
elev = np.where(water | lake, np.minimum(depth, 0.12), np.maximum(elev, 0.20))
# soften the land->sea step so FMG gets a shore gradient, not a cliff
soft = np.asarray(Image.fromarray((np.clip(elev, 0, 1) * 255).astype(np.uint8))
                  .filter(ImageFilter.GaussianBlur(1.6 * SCALE))).astype(np.float64) / 255
elev = np.where(water | lake, np.minimum(soft, SEA_T - 0.04), np.maximum(soft, SEA_T + 0.02))

# the Outer Isles: a fuller chain continuing the range line through the NE gulf
isl_rng = np.random.default_rng(SEED + 4)
S_by_name = {st["name"]: st for st in d["settlements"]}
isle_districts = [dd for dd in d["districts"] if dd["region"] == "outer_isles"]
islands = []
for dd in isle_districts:
    pts = [S_by_name[m]["xy"] for m in dd["members"] if m in S_by_name]
    if not pts:
        continue
    px = sum(p[0] for p in pts) / len(pts)
    py = max(sum(p[1] for p in pts) / len(pts), 14)
    spread = max(max(abs(p[0] - px) for p in pts), max(abs(p[1] - py) for p in pts), 8)
    islands.append((px, py, min(spread + 14, 46), min(spread * 0.8 + 11, 34)))
islands.append((72, 84, 34, 24))    # the undiscovered northwest island
for _ in range(3):   # uninhabited skerries continuing the line
    islands.append((848 + isl_rng.random() * 140, 16 + isl_rng.random() * 110,
                    7 + 6 * isl_rng.random(), 5 + 5 * isl_rng.random()))
for px, py, rxi, ryi in islands:
    isl = bump(px, py, rxi, ryi, 1.3)
    lift = np.where(isl > 0.04, SEA_T + 0.02 + isl * (0.13 + 0.09 * isl_rng.random()), 0.0)
    elev = np.maximum(elev, lift)

elev = np.clip(elev, 0.02, 1.0)
Image.fromarray((elev * 255).astype(np.uint8), "L") \
     .filter(ImageFilter.GaussianBlur(0.8 * SCALE)).save(OUT)
print(f"wrote {OUT} {W}x{H}; land fraction {(elev > SEA_T).mean():.0%}")
