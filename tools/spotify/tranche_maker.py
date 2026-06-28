import json
from collections import Counter, defaultdict

cache = json.load(open('../../data/artist_spotify.json'))
vals = []
for name, e in cache.items():
    L = ((e or {}).get('lastfm') or {}).get('listeners')
    if isinstance(L, str):
        L = int(L) if L.strip().isdigit() else None
    if isinstance(L, (int, float)):
        vals.append((int(L), name))
vals.sort()
ls = [v for v, _ in vals]; n = len(ls)

def q(p):
    if n <= 1: return ls[0] if ls else 0
    i = (n - 1) * p; lo = int(i); hi = min(lo + 1, n - 1)
    return round(ls[lo] + (ls[hi] - ls[lo]) * (i - lo))

print(f"with-listeners: {n} of {len(cache)} cache entries")
print(f"min {ls[0]:,}   median {q(.5):,}   max {ls[-1]:,}")
for p in (.1, .2, .25, .33, .4, .5, .6, .66, .75, .8, .9, .95):
    print(f"  p{int(p*100):>2}: {q(p):>10,}")

cuts = [q(.2), q(.4), q(.6), q(.8)]
print("quintile cuts (even 5-way):", [f"{c:,}" for c in cuts])

labels = ["tiny", "niche", "medium", "popular", "superstar"]
def bucket(L):
    for i, c in enumerate(cuts):
        if L < c: return labels[i]
    return labels[-1]

cnt = Counter(); ex = defaultdict(list)
for L, name in vals:
    b = bucket(L); cnt[b] += 1
    if len(ex[b]) < 4: ex[b].append(f"{name} ({L:,})")
for lab in labels:
    print(f"{lab:>9}: {cnt[lab]:>3}  e.g. " + ", ".join(ex[lab]))
