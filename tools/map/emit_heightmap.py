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
    r = {"capital": 34, "city": 34, "town": 24, "village": 20}.get(st["size"], 15)
    dist = np.hypot(kx - x, ky - y)
    keep_low = np.maximum(keep_low, np.clip(1 - dist / r, 0, 1))
keep = np.asarray(Image.fromarray((keep_low * 255).astype(np.uint8))
                  .resize((W, H), Image.BILINEAR)).astype(np.float64) / 255
keep = np.asarray(Image.fromarray((keep * 255).astype(np.uint8))
                  .filter(ImageFilter.GaussianBlur(4 * SCALE))).astype(np.float64) / 255

# river corridor is land, except the mouth zone where the bay may flood
big_path = meander([tuple(p) for p in ww["the_bigmuddy"]["points"]] + [(648, 665)], rkey=0)
creek_path = meander([tuple(p) for p in ww["slowhand_creek"]["points"]], wobble=10, rkey=1)
parade = meander([tuple(p) for p in ww["the_parade"]["points"]] + [(636, 618)], wobble=8, rkey=2)
big_d = dist_to_polyline(big_path)
creek_d = dist_to_polyline(creek_path)
parade_d0 = dist_to_polyline(parade)
river_keep = np.clip(1 - np.minimum(np.minimum(big_d, creek_d), parade_d0) / 40, 0, 1)
mouth_zone = bump(648, 600, 92, 84, 1.15)
keep = np.maximum(keep, river_keep * (1 - np.clip(mouth_zone * 1.8, 0, 1)))

# ---------------------------------------------------------------- sea potential
rngL = np.random.default_rng(SEED + 3)
coast_noise = fbm((H, W), (3, 4), 5, rngL) - 0.5
fjord_noise = fbm((H, W), (17, 4), 5, np.random.default_rng(SEED + 11)) - 0.5
shift = ((-0.85 * xx) % H).astype(int)
rows = (np.arange(H)[:, None] + shift) % H
fjord_diag = fjord_noise[rows, np.arange(W)[None, :]]

# the guitar silhouette: a soft landness field the coastline noise then roughens.
AXIS = np.deg2rad(-38)
ua, va = np.cos(AXIS), np.sin(AXIS)          # along-axis unit (toward headstock)
HEEL = (645, 325)
def circ(cx, cy, r):
    # plateau disc: solid land to ~80% radius, soft shoulder to the edge
    rr = np.hypot(ux - cx, uy - cy) / r
    return np.clip((1 - rr) * 5.5, 0, 1)
def on_axis(t, off=0.0):
    return (HEEL[0] + ua * t - va * off, HEEL[1] + va * t + ua * off)

nx1, ny1 = on_axis(80); nxm, nym = on_axis(175); nx2, ny2 = on_axis(292)
neck_lo = np.clip((1 - dist_to_polyline([(HEEL[0], HEEL[1]), (nx1, ny1), (nxm, nym)]) / 88) * 4.0, 0, 1)
neck_hi = np.clip((1 - dist_to_polyline([(on_axis(120)), (nxm, nym), (nx2, ny2)]) / 58) * 4.0, 0, 1)
neck = np.maximum(neck_lo, neck_hi)
c_up = on_axis(-105); c_wa = on_axis(-205); c_lo = on_axis(-318)
land_f = np.maximum.reduce([
    neck,
    circ(*c_up, 168),          # upper bout
    circ(*c_wa, 126),          # the waist
    circ(*c_lo, 196),          # lower bout
    circ(598, 492, 138),       # heel-to-bout seam lobe (the bay bites into this)
])
sea = np.clip(0.55 - land_f, -1, 1) * 3.4          # outside the silhouette: sea
sea += coast_noise * 1.7                            # ragged everything
# fjord fingers cut the waist from the northwest
sea += (np.clip((c_wa[0] + 130 - ux) / 300, 0, 1) ** 0.8
        * np.clip((uy - 160) / 220, 0, 1)
        * np.clip(fjord_diag * 4.4, 0, 3.4))
sea += mouth_zone * 1.9                             # the bay bites the bottom curve
# east of the bay: the seam coast collapses into deep diagonal fjords, no promontory
sea += bump(800, 548, 66, 80, 1.2) * 1.30
sea += (np.clip((ux - 655) / 170, 0, 1) * np.clip((uy - 420) / 160, 0, 1)
        * np.clip((820 - ux) / 60, 0, 1) * np.clip(fjord_diag * 3.4, 0, 2.8))
# channel cuts through the southwest islet cluster (asymmetric triplet, not one mass)
sea += bump(181, 613, 8, 34, 1.3, rot=0.85) * 2.6
sea += bump(208, 634, 7, 26, 1.3, rot=0.95) * 2.6
# barrier-lagoon bites along the bottom-curve tidewater
sea += bump(300, 616, 150, 70, 1.3) * np.clip((fbm((H, W), (10, 14), 4,
        np.random.default_rng(SEED + 12)) - 0.42) * 3.0, 0, 2) * 0.8

sea -= keep * 4.0                                           # inhabited ground wins
water = sea > 0.55

# spit ridges flanking the mouth shape the flood into a sheltered bay
spit_w = bump(590, 598, 52, 13, 1.5, rot=0.52) * 0.10
spit_e = np.zeros_like(spit_w)   # the seam coast itself is the bay's east shore
# one deterministic assist: the harbor floods properly behind the arm
harbor = (bump(642, 592, 58, 48, 1.05) + 0.14 * (fbm((H, W), (12, 16), 3,
          np.random.default_rng(SEED + 13)) - 0.5)) > 0.30
water |= harbor & (uy > 556)
water &= ~(spit_w > 0.055)

# ---------------------------------------------------------------- elevation
elev = np.full((H, W), 0.30)
elev += 0.09 * (fbm((H, W), (6, 8), 5, np.random.default_rng(SEED)) - 0.5)

ridge = fbm((H, W), (14, 20), 6, np.random.default_rng(SEED + 1), gain=0.55)
ridge = (1 - abs(2 * ridge - 1)) ** 1.5
spine = np.clip(0.88 * bump(695, 290, 140, 72, 1.2, AXIS)
                + bump(788, 205, 145, 70, 1.15, AXIS)
                + bump(866, 118, 135, 68, 1.1, AXIS), 0, 1.15)
elev += spine * (0.20 + 0.35 * ridge)
sx2, sy2 = on_axis(258)
elev += bump(sx2, sy2, 56, 38, 1.5, AXIS) * (0.10 + 0.08 * ridge)   # the headstock summit

cx, cy, rx, ry = R("slide_foothills")
base = bump(cx, cy, rx * 1.25, ry * 1.3, 1.1)
tn = fbm((H, W), (16, 22), 4, np.random.default_rng(SEED + 8))
shelf = np.round((base + 0.35 * (tn - 0.5)) * 5) / 5 * 0.16 * (base > 0.05)
elev += np.clip(shelf, 0, None) + base * 0.07 * ridge

# the shoulder ridge: a short chain on the upper bout's north shoulder
ridge_n = fbm((H, W), (14, 20), 5, np.random.default_rng(SEED + 14), gain=0.55)
ridge_n = (1 - abs(2 * ridge_n - 1)) ** 1.5
coast_chain = np.clip(bump(468, 232, 60, 24, 1.2, rot=0.30)
                      + bump(552, 208, 60, 24, 1.2, rot=0.34), 0, 1)
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
parade_d = parade_d0
for path, wmax, depth in ((big_path, 30, 0.17), (creek_path, 15, 0.09), (parade, 13, 0.10)):
    dist = big_d if path is big_path else (creek_d if path is creek_path else parade_d)
    prog = np.clip((uy - path[0][1]) / max(path[-1][1] - path[0][1], 1), 0, 1)
    grad = 0.55 + 0.45 * prog          # valley floor drops downstream
    elev -= np.clip(1 - dist / (8 + wmax * prog), 0, 1) ** 1.7 * depth * grad

# a low divide west of the confluence, so drainage cannot escape across the plains
elev += bump(500, 430, 85, 100, 1.4) * 0.04

# lakes: the forest (pickup) lake at the creek's source, and the knob pair
lx, ly = ww["the_forest_lake"]["points"][0]
lake = bump(lx, ly, 17, 12, 1.3) > 0.25
for kx2, ky2 in ww["the_knob_lakes"]["points"]:
    lake |= bump(kx2, ky2, 11, 9, 1.3) > 0.3
for sx3, sy3 in ww["the_shoulder_lakes"]["points"]:
    lake |= bump(sx3, sy3, 30, 20, 1.3) > 0.3

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
isle_districts = [dd for dd in d["districts"] if dd["region"] == "outer_isles"]
islands = []
for dd in isle_districts:
    ic = dd.get("island_center")
    if ic:
        islands.append((ic[0], ic[1], dd.get("island_r", 12) + 6, dd.get("island_r", 12) + 4))
for _ in range(2):   # uninhabited skerries off the headstock tip
    islands.append((915 + isl_rng.random() * 60, 30 + isl_rng.random() * 55,
                    6 + 5 * isl_rng.random(), 5 + 4 * isl_rng.random()))
islands.append((655, 612, 12, 9))   # the harbor island, inside the bay
islands.append((72, 84, 34, 24))    # the undiscovered northwest island
covered = lambda x_, y_: any(((x_-a_)/b_)**2 + ((y_-c_)/d_)**2 < 0.5
                             for a_, c_, b_, d_ in islands)
for st in d["settlements"]:
    if st["region"] == "outer_isles" and not covered(*st["xy"]):
        islands.append((st["xy"][0], st["xy"][1], 8, 6))
for px, py, rxi, ryi in islands:
    isl = bump(px, py, rxi, ryi, 1.3)
    lift = np.where(isl > 0.04, SEA_T + 0.02 + isl * (0.13 + 0.09 * isl_rng.random()), 0.0)
    elev = np.maximum(elev, lift)

elev = np.clip(elev, 0.02, 1.0)
Image.fromarray((elev * 255).astype(np.uint8), "L") \
     .filter(ImageFilter.GaussianBlur(0.8 * SCALE)).save(OUT)
print(f"wrote {OUT} {W}x{H}; land fraction {(elev > SEA_T).mean():.0%}")
