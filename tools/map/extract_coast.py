#!/usr/bin/env python3
"""
extract_coast.py - pull the painted coastline out of map.svg into coast.json.

An FMG export defines every landmass and lake once, as a path under
<defs id="featurePaths">, and references them from the land and water masks.
The mainland is the largest of the land features; the lakes are the features
the freshwater group references. All of it is already in the 1000x700 canvas
frame the map page draws in, so nothing is rescaled - the curves are flattened
and simplified (Douglas-Peucker) so a page can do point-in-polygon on them.

The painted rivers come along too. FMG draws each river under <g id="rivers"> as one
closed ribbon - down one bank and back up the other - so the centerline is the midpoint
of the two banks taken at matching fractions of their length, and the gap between them
is the painted width there. Each river is written as its widest painted width and its
centerline points, simplified like the coast; map.html uses them to put bridges where a
route crosses water.

Run it again after an FMG repaint; map.html reads build/coast.json.
"""
import argparse, json, re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ap = argparse.ArgumentParser()
ap.add_argument("--svg", type=Path, default=HERE / "art" / "map.svg")
ap.add_argument("--out", type=Path, default=HERE / "build" / "coast.json")
ap.add_argument("--eps", type=float, default=0.8, help="simplification tolerance, canvas units")
args = ap.parse_args()

svg = args.svg.read_text(encoding="utf-8")
feats = {fid: d for d, fid in re.findall(r'<path d="([^"]+)" id="(feature_\d+)"', svg)}
land_ids = set(re.findall(r'xlink:href="#(feature_\d+)"', re.search(r'<mask id="land">(.*?)</mask>', svg, re.S).group(1)))
fw = re.search(r'<g id="freshwater"[^>]*>(.*?)</g>', svg, re.S)
lake_ids = set(re.findall(r'xlink:href="#(feature_\d+)"', fw.group(1))) if fw else set()

def flatten(d, n=3):
    toks = re.findall(r"[A-Za-z]|-?\d+\.?\d*", d); pts = []; i = 0; cur = None
    while i < len(toks):
        t = toks[i]
        if t in "ML":
            cur = (float(toks[i + 1]), float(toks[i + 2])); pts.append(cur); i += 3
        elif t == "Q":
            c = (float(toks[i + 1]), float(toks[i + 2])); p = (float(toks[i + 3]), float(toks[i + 4]))
            for k in range(1, n + 1):
                u = k / n; v = 1 - u
                pts.append((v*v*cur[0] + 2*v*u*c[0] + u*u*p[0], v*v*cur[1] + 2*v*u*c[1] + u*u*p[1]))
            cur = p; i += 5
        elif t == "C":
            c1 = (float(toks[i + 1]), float(toks[i + 2])); c2 = (float(toks[i + 3]), float(toks[i + 4]))
            p = (float(toks[i + 5]), float(toks[i + 6]))
            for k in range(1, n + 1):
                u = k / n; v = 1 - u
                pts.append((v*v*v*cur[0] + 3*v*v*u*c1[0] + 3*v*u*u*c2[0] + u*u*u*p[0],
                            v*v*v*cur[1] + 3*v*v*u*c1[1] + 3*v*u*u*c2[1] + u*u*u*p[1]))
            cur = p; i += 7
        elif t == "Z":
            i += 1
        elif t.isalpha():
            raise SystemExit(f"unhandled path command {t!r} - extend flatten() before trusting the output")
        else:
            i += 1
    return pts

def simplify(pts, eps):
    def dp(p):
        if len(p) < 3:
            return p
        a, b = p[0], p[-1]; dx, dy = b[0] - a[0], b[1] - a[1]; L = (dx*dx + dy*dy) ** .5 or 1e-9
        dm, im = -1, 0
        for i in range(1, len(p) - 1):
            d = abs((p[i][0] - a[0]) * dy - (p[i][1] - a[1]) * dx) / L
            if d > dm:
                dm, im = d, i
        if dm > eps:
            return dp(p[:im + 1])[:-1] + dp(p[im:])
        return [a, b]
    h = len(pts) // 2   # a closed ring: split it in two open runs so the ends survive
    return dp(pts[:h + 1])[:-1] + dp(pts[h:] + [pts[0]])[:-1]

def simplify_open(pts, eps):
    """Douglas-Peucker on an open run of [x, y, ...] points; extra fields ride along."""
    if len(pts) < 3:
        return pts
    a, b = pts[0], pts[-1]; dx, dy = b[0] - a[0], b[1] - a[1]; L = (dx*dx + dy*dy) ** .5 or 1e-9
    dm, im = -1, 0
    for i in range(1, len(pts) - 1):
        d = abs((pts[i][0] - a[0]) * dy - (pts[i][1] - a[1]) * dx) / L
        if d > dm:
            dm, im = d, i
    if dm > eps:
        return simplify_open(pts[:im + 1], eps)[:-1] + simplify_open(pts[im:], eps)
    return [a, b]

def centerline(ring):
    """A river ribbon (one bank out, the other back) as [x, y, width] down its middle."""
    h = len(ring) // 2
    a, b = ring[:h], ring[h:][::-1]
    def at(P, t):
        k = t * (len(P) - 1); k0 = int(k); k1 = min(k0 + 1, len(P) - 1); f = k - k0
        return (P[k0][0] * (1 - f) + P[k1][0] * f, P[k0][1] * (1 - f) + P[k1][1] * f)
    n = max(len(a), len(b))
    out = []
    for k in range(n):
        p, q = at(a, k / (n - 1)), at(b, k / (n - 1))
        out.append([(p[0] + q[0]) / 2, (p[1] + q[1]) / 2, ((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2) ** .5])
    return out

def area(p):
    return abs(sum(p[i-1][0]*p[i][1] - p[i][0]*p[i-1][1] for i in range(len(p)))) / 2

rings = {fid: simplify(flatten(d), args.eps) for fid, d in feats.items() if fid in land_ids}
lakes = [rings.pop(f) for f in list(rings) if f in lake_ids]
mainland_id = max(rings, key=lambda f: area(rings[f]))
mainland = rings.pop(mainland_id)
islands = [rings[f] for f in sorted(rings, key=lambda f: -area(rings[f]))]
rnd = lambda ring: [[round(x, 1), round(y, 1)] for x, y in ring]
rv = re.search(r'<g id="rivers"[^>]*>(.*?)</g>', svg, re.S)
rivers = []
for rid, d in re.findall(r'<path id="(river\d+)" d="([^"]+)"', rv.group(1) if rv else ""):
    full = centerline(flatten(d))
    c = simplify_open(full, args.eps / 2)
    rivers.append({"id": rid, "w": round(max(w for _, _, w in full), 2),
                   "pts": [[round(x, 1), round(y, 1)] for x, y, _ in c]})
out = {
    "_note": f"Coastline from map.svg ({mainland_id} is the mainland), 1000x700 canvas units, "
             f"Douglas-Peucker eps {args.eps}; rivers are painted centerlines with their widest width, "
             f"eps {args.eps / 2}. Regenerate with extract_coast.py after a repaint.",
    "mainland": rnd(mainland), "islands": [rnd(r) for r in islands], "lakes": [rnd(r) for r in lakes],
    "rivers": rivers,
}
args.out.write_text(json.dumps(out, separators=(",", ":")) + "\n")
print(f"wrote {args.out}: mainland {len(mainland)} pts, {len(islands)} islands, {len(lakes)} lakes, "
      f"{len(rivers)} rivers ({sum(len(r['pts']) for r in rivers)} pts)")
