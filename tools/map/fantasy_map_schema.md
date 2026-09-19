# Fantasy Map Data — contract for the JS/CSS overlay layer

`fantasy_map_data.json` reorganizes the artist-graph data (the same sources the force
simulation reads) into a speculative-fiction map model. It is deliberately design-agnostic:
it tells the overlay *what exists, where it clusters, and how big it is* — every visual
decision (iconography, typography, the painted background) belongs to the design layer.

## The model in one paragraph

Every tracked artist is a **settlement**. Genre gravity (Last.fm tags) sorts settlements into
six tag-derived **regions** (a seventh, the Steel Foothills, is hand-rostered — see the end of
this file), each with a terrain archetype: trad/acoustic blues on the coastal tidewater,
blues-rock in the mountains, Americana/country on the farmland plains, funk/brass/jam at the
river port, folk/singer-songwriter in the forest, and genre outliers plus Celtic acts offshore
on the isles. Within a region, graph community detection groups settlements into **districts**
(neighborhoods), each with a seat (its best-connected member) and a procedurally suggested
toponym you are free to rename. Engagement depth (times seen, VIP count, follow tier) sets
settlement **size** from capital down to waystation. Graph edges become **routes**, classed by
provenance: hand-curated kinship is a road, your own attendance history is a river-road, shared
sidemen are bridges, and Last.fm taste similarity is a trail. Cross-region routes are re-classed
for rendering as ferries (to the isles), passes (into the mountains), or highways.

## File contract

Top level: `meta`, `canvas`, `regions`, `waterways`, `districts`, `settlements`, `routes`.

**canvas** — `{w:1000, h:700}`. All `xy` coordinates and waterway points are in this space.
Treat it as a viewBox: `<svg viewBox="0 0 1000 700">` over the background image, or scale by
`clientWidth/1000` for absolutely-positioned DOM nodes.

**regions[]** — `id`, `label`, `terrain` (flavor text), `anchor` [x,y], `rx`, `ry`. The
anchor+radii describe the ellipse the generator laid the region out inside. These are *hints*:
if the painted map puts the mountains elsewhere, re-anchor using `region_uv` (below) instead of
`xy` and the whole region transplants cleanly.

**waterways[]** — suggested polylines (`points`) for the two rivers and the southern sea, with
ids referenced nowhere else; they exist so the background painter and the data layer can agree
on where water is. Redraw freely.

**districts[]** — `id` (`region:dN`, `region:outskirts`, or `outer_isles:pN`), `region`,
`members` (canonical artist names), `seat`, `suggested_name`. Outer Isles districts are
"peg crews" — genre-family buckets (celtic, tribute, metal, pop, far) chunked to island
size, since the taste graph barely connects the outliers — and carry two extra fields:
`island_center` [x,y] and `island_r`, the island each crew stands on. The overlay can
draw peg islands from these directly; the heightmap emitter already does. Districts are the neighborhood layer: label them on
hover, draw soft hulls around their members, or ignore them entirely at low zoom.

**settlements[]** — one per artist:

```json
{
  "id": 173, "name": "The Lone Bellow",
  "region": "quiet_woods", "district": "quiet_woods:d1",
  "size": "capital", "score": 24.0,
  "xy": [212.4, 187.9],
  "region_uv": [0.4551, 0.4516],
  "flags": {"legacy": true, "faded": true, "unvisited": true},
  "times_seen": 5, "vip": 3, "tier": "Strong"
}
```

`label`, present only when it differs from `name`, is the short form the canvas prints
beside the mark (from `data/artist_display.tsv`, Short then Medium, the same file the
festival posters use). `name` is canonical and is what the readout, the finder and the artist
card show; a renderer that has room should ignore `label`.

`src`, present on nearly every settlement, is the builder's own sentence about why this
artist is on the map at all - `follow (Medium)`, `history pass: seen as support`,
`seen as support (history TSVs; no artists.tsv row)`. It is provenance, not taste: the
readout prints it in small type, and the artist card surfaces it as *on the map because:
...* for a settlement nobody has visited, where it is the only answer to "why is this here".

`size` is one of `capital` (one per region, the highest-scoring seen act), `city`, `town`,
`village`, `hamlet`, `waystation` (followed but never seen — render as a campfire, survey
marker, or rumor on the map's edge). `region_uv` is the settlement's position normalized 0..1
inside its region's bounding box — the transplant-safe coordinate. `flags` appear only when
true: `faded` (not seen since before 2019 — ruins, ghost towns, overgrown signposts),
`legacy` (Buddy Guy tier — lighthouses or monuments rather than towns), `unvisited`
(same population as waystation, kept separate so you can restyle without re-deriving).
Three more are the editor's worklist rather than facts about the artist, and a viewer-facing
render should ignore them: `unplaced` (staged in a ring by the builder; the position is
meaningless until hand-placed), `unpinned` (builder-positioned with no pins.json entry, so
the position can move on a rebuild), `stray` (pinned, but the pin lies outside the region's
polygon — advisory, since the polygons are not exact borders). All three are mainland-only.
`score` is the raw size metric (3×times-seen capped at 8, +2×VIP, +tier bonus) if you want
continuous scaling instead of the tier buckets.

**routes[]** — `{a, b, cls, crossRegion, render}` with `a`/`b` as canonical names. `cls` is
provenance (`road` kinship, `river` attended-bill, `bridge` shared-sideman, `trail` taste
similarity); `render` equals `cls` within a region and is upgraded across regions to `ferry`,
`pass`, or `highway`. Suggested visual weight: roads and river-roads solid, bridges distinct
(they are rare and interesting — nine exist), trails faint/dashed, ferries as dotted arcs over
water. Current census: 480 routes — 285 trails, 172 river-roads, 14 roads, 9 bridges; after the
cross-region re-class, 99 render as passes, 85 as highways and 8 as ferries.

## What the artist card consumes

`artist-modal.js` renders a settlement-aware card, and the contract between it and this
data is deliberately narrow - the module never learns map internals. A caller passes:

```js
openArtistModal(settlement.name, {          // ALWAYS the canonical name, never `label`
  surface:'the map',
  label: settlement.label || null,          // the short form the canvas printed, context only
  settlement:{
    region, region_label, size,             // -> the "where" line, under the canonical name
    tint,                                   // the region colour, becomes the card's accent
    flags,                                  // `unvisited` switches the glyph and the phrasing
    src                                     // -> "on the map because: ..." when never visited
  }
});
```

Two rules the map side must honour:

**The card opens on the canonical name.** `label` may legitimately read `Kingfish` on a
narrow mark, but the card resolves and displays the full `artists.tsv` identity, with the
short form shown beneath it as *opened from the map as Kingfish* - never in its place.

**The glyph agrees with the canvas.** The card draws the settlement mark the way the map
draws it - filled tinted dot, plus a ring for a capital, hollow and dashed for `unvisited` -
so the two surfaces never contradict each other about what a settlement is.

## Suggested render order

Background image, then waterways (if drawn live), then region labels, then trails, then
roads/rivers/bridges, then ferry/pass/highway arcs, then district hulls (hover-only), then
settlements smallest-to-largest so capitals sit on top, then settlement labels gated by zoom
(capitals always, cities > 0.6×, towns > 1.2×, the rest on hover).

## Minimal JS binding sketch

```js
const map = await (await fetch('fantasy_map_data.json')).json();
const svg = d3.select('#map').attr('viewBox', `0 0 ${map.canvas.w} ${map.canvas.h}`);
const S = new Map(map.settlements.map(s => [s.name, s]));
svg.selectAll('path.route').data(map.routes).join('path')
   .attr('class', r => `route ${r.render}`)
   .attr('d', r => arc(S.get(r.a).xy, S.get(r.b).xy, r.crossRegion ? 0.25 : 0));
svg.selectAll('g.settlement').data(map.settlements).join('g')
   .attr('class', s => `settlement ${s.size} ${Object.keys(s.flags||{}).join(' ')}`)
   .attr('transform', s => `translate(${s.xy})`);
```

CSS then owns everything: `.settlement.capital`, `.settlement.waystation`, `.route.ferry`,
`.settlement.faded`, per-region tints via a `data-region` attribute, and so on.

## Regenerating

Both scripts live in `tools/map/` and run from anywhere:
`python3 tools/map/build_fantasy_map.py` auto-detects the repo root by walking up from
the script (override with `--repo-root`), reads everything from `data/`, and writes
`fantasy_map_data.json` beside itself (`--out` to redirect). Then
`python3 tools/map/emit_heightmap.py` reads that JSON from beside itself (`--data`) and
writes `heightmap.png` next to it (`--out`, `--scale`; scale 2 = 2000x1400). Dependencies:
networkx, numpy, pillow. Output is fully deterministic: the layout seed is 2026 and the
build script pins PYTHONHASHSEED (one self re-exec) because community-detection
tie-breaking otherwise leaks the per-process hash seed into district and coordinate
assignments. The knobs worth turning live at the top of build_fantasy_map.py: TAG_VOTES
(genre-to-terrain gravity - the most taste-sensitive dial), REGIONS, FORCED_REGION /
CURATED_REGIONS / CAPITAL_OVERRIDE (the Steel Foothills machinery), EDGE_WEIGHT, and the
size thresholds in size_tier.

## Current census (2026-09-18 index)

403 settlements, 480 routes, 78 districts across seven regions - by size: 7 capitals,
29 cities, 99 towns, 46 villages, 141 hamlets, 81 waystations.

| region | settlements | capital |
|---|---|---|
| The Amplified Range | 98 | Christone 'Kingfish' Ingram |
| The Quiet Woods | 81 | The Lone Bellow |
| Secondline Riverlands | 63 | Trombone Shorty & Orleans Avenue |
| The Heartland | 51 | Daniel Donato |
| The Delta Coast | 43 | Shemekia Copeland |
| The Outer Isles | 43 | AJR |
| The Steel Foothills | 24 | Larkin Poe (see below) |

Two capitals are decreed rather than computed: Larkin Poe and AJR hold theirs through
`CAPITAL_OVERRIDE`, and Shemekia Copeland through `CURATED_SIZE` - an explicit curatorial
swap with Ana Popovic, independent of either artist's score. The Outer Isles is where the
tribute acts, the pop outliers and the Celtic bands share ferry service.

## The Steel Foothills (curated region)

One region is hand-rostered rather than tag-derived: the Steel Foothills, sitting between
the Amplified Range and the Heartland, home of the slide, lap-steel, and sacred-steel
players. Larkin Poe governs from Poe Scarp by decree (CAPITAL_OVERRIDE), with Ghalia Volt
and Sonny Landreth up the same ridge; districts below include Landreth Bend (the brothers),
Birchwood Switchback, Allstars Terrace, and Band Rise (Tedeschi Trucks). Full roster:
Larkin Poe, Ghalia Volt, Mike Zito, Robert Randolph, Ariel Posen, Sonny Landreth, Selwyn
Birchwood, The Bros. Landreth, Joey Landreth, Warren Haynes, North Mississippi Allstars,
Tedeschi Trucks Band. Curated regions never recruit by neighbor vote - edit FORCED_REGION
to change the roster, CURATED_REGIONS to add another hand-rostered territory, and
CAPITAL_OVERRIDE to appoint its ruler. Duane Betts, Luther Dickinson, and Jack White would
belong here but are not in the recommendation index, so they have no node to place.
