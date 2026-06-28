import json
# todo: make this print any tranche. possibly combine with tranchemaker.py
c = json.load(open('../../data/artist_spotify.json'))
top = []
for n, e in c.items():
    L = ((e or {}).get('lastfm') or {}).get('listeners')
    if L is None:
        continue
    L = int(L)
    if L >= 1_000_000:
        top.append((L, n))
top.sort(reverse=True)
print(len(top), "artists ≥1M")
for L, n in top:
    print(f"{L:>10,}  {n}")
