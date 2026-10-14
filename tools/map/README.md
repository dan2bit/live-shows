# tools/map — Guitarlandria

The fantasy-map rendering of the tracked artists: every artist a settlement, genre
gravity the terrain. The page is `map.html` and its URL does not move; everything
else is sorted by who writes it.

| path | what | written by |
|---|---|---|
| `map.html` | the viewer and, for an authed desktop, the editor | humans, by PR |
| `build_fantasy_map.py` | settlements, regions, districts from the tracking data | humans, by PR |
| `emit_heightmap.py` | the FMG heightmap seed from the built data | humans, by PR |
| `extract_coast.py` | the painted coast as polygons and the painted rivers as centerlines, from `art/map.svg` | humans, by PR |
| `docs/` | `fantasy_map_schema.md` (the data contract, the device/desktop split), `heightmap_azgaar_notes.md` (the repaint procedure) | humans |
| `edits/` | `pins.json`, `labels.json`, `map_overrides.json`, `thoroughfares.json`, `discovered_adds.json` — the hand-owned state | the in-page editor (read-merge-write, to `staging`), or a hand edit |
| `build/` | `fantasy_map_data.json`, `coast.json`, `heightmap.png` — derived, never hand-edited | `map-rebuild.yml` on every push to `main` that touches `edits/` or a generator; `coast.json` by running `extract_coast.py` after a repaint |
| `art/` | `map.svg`, the painted background the page draws under everything; the Azgaar `.map` project it was exported from | a repaint session in Azgaar's FMG |

Regenerate locally from the repo root — the scripts find the repo and their own
folder, so no arguments are needed:

```
python3 tools/map/build_fantasy_map.py          # edits/ -> build/fantasy_map_data.json
python3 tools/map/emit_heightmap.py             # build/fantasy_map_data.json -> build/heightmap.png
python3 tools/map/extract_coast.py              # art/map.svg -> build/coast.json
```

The builder is deterministic (seed 2026, pinned PYTHONHASHSEED), so identical inputs
give byte-identical output; a local run that changes `build/fantasy_map_data.json`
means an input changed, not the builder. `?svg=` and `?data=` on `map.html` still
point the page at alternative files for a repaint preview.

Not kept here: Azgaar's PNG exports. They are re-exportable from the `.map` at any
resolution and were 8.5 MB in every Pages deploy; the `.map` is the source.

## The in-page editor

An authed desktop gets edit mode on `map.html`. Signed in, the page loads
every `edits/` file from `staging` through the GitHub API - where its saves land - rather
than from the Pages copy, which trails a save by the promote and the deploy; everyone else
sees the Pages copy. **save changes** writes each touched file as one Contents-API commit
to `staging`, folding only this session's changes into the file as it stands there: pins
and overrides by name, labels by `group:key`, routes by class + chain.
An edit made while a save is running stays unsaved and goes out with the next save.
**discard** drops every unsaved edit by reloading the page: the dirty bookkeeping knows
which keys changed, not what they were, and an authed load already reads `staging`, so a
reload is exactly "back to the last save there", other tabs' saves included. The view and
edit mode come back after the reload; a selected route does not. It asks first, and is
disabled while a save is in flight.

Dragging maps the cursor through the SVG's own matrix (`getScreenCTM`), so a dragged pin,
waypoint or label stays under the cursor in any window shape. The viewBox is 10:7 and
letterboxed with `xMidYMid meet`; dividing by the element's bounding box, as the page did
until October 2026, ignored the bars and put a dragged pin to the side of the cursor by a
fraction of its distance from the window's centre.

Waterways are not traced by hand any more. The rivers are painted: `extract_coast.py`
reads them off the Azgaar export into `build/coast.json -> rivers`, and their names are
`labels.json -> waters`, placed in the editor like any other label (#460). The earlier
trace mode - click settlements source to mouth, save the polyline - produced
`edits/traced_waterways.json`, whose 47 names seeded that label set; the file and the mode
were retired in October 2026 and live on in history. An unnamed tributary of a named water
earns a fork or branch label of its own when the builder scores of the settlements on it
sum to 12 or more across two or more settlements, or when any one of them is a city -
otherwise its settlements count as on the named water they drain into. Birch Fork (off
Slowhand Creek) is the first to clear it.

A water name shows its reach. Hover one (tap, on a device) and the painted line it belongs
to is stroked in blue, every settlement on that water gets a ring and its label, and the
readout lists them: `Tweed Creek - stream, 198 units - 6 on it: Sue Foley, ...`. The rule is
the strand census's: a name belongs to the nearest painted centerline (a river-class line
within 25 wins, since a wide river's name sits off its bank), no two names share a line
(bigger waters claim first, by tier, so a creek's name a few units off a river's bank keeps
its creek rather than taking the river's own line), the reach floods through touching lines
but stops at any line that is another name's home, and a settlement within 10 units is on
it. In edit mode every water name shows at any zoom, grabbing one holds the
reach and dims everything else, and the reach follows the label as it moves - slide a name
six units onto the next creek and the rings jump, which is the point. A tap or a drag holds
the reach until the next press or Esc; a hover clears on leave. Water names are hit
targets in every mode for this; a click that lands on one is handed to the dot beneath it.
(The same change fixed the view-mode click itself: the stage captures the pointer on press,
so pointerup's target is the stage, and the dot-toggles-label / name-opens-card branch had
been reading the wrong element. It now reads what the press hit.)

Routes: click a road, pass, trail or ferry hop to drag its waypoints, click a white handle
to add one, alt-click to remove one. The autobahn is not clickable; its waypoints are hand
edits in `thoroughfares.json`, where a hop's `via` replaces its one generated bump.

Bridges are drawn, never stored: wherever a road, the autobahn, a pass or a trail crosses
painted water, the page puts a bridge on the crossing, recomputed every time the route is
drawn - bend a route in the editor and its bridges follow. Roads and the autobahn get
parapet rails, passes a stone arch, and trails a plank over a river or stepping stones
across a stream or rill. The water is `build/coast.json -> rivers` (painted centerlines
and widths from `extract_coast.py`); 2.4 units wide and up is a river, 1.2 and up a
stream, anything narrower a rill. Ferries take no bridges.

## The legacy ledger

The history TSVs begin in 2021. `data/legacy_shows.tsv` is the record of the shows before
that - 24 shows, 1985-2019, lifted once from the setlist.fm attendance cache
(`tools/archive/setlist_attendances_20260626.tsv`, issue #468) - one row per act per show:
`Show Date`, `Artist`, `Venue`, `Setlist URL`. It lives in `data/` because it is domain
content, like `related_acts.tsv`; the map is its first consumer, not its owner, and
`map-rebuild.yml` watches it alongside `edits/`. `artists.tsv`, the history TSVs and the
recommendation index never see it. The builder adds each row to the
act's `times_seen` (so Peter Gabriel is seen five times, not a follow), gives an act the
index does not know a record of its own (status `legacy`, no tags, no tier - its region
comes from its pin), and treats rows that share a date and a venue as one bill, so they
become river edges like any other bill. A settlement credited this way carries
`legacy_shows` in the built JSON and, when nothing in the live history explains it, a
`src` of the form `seen 4x before the history begins (1985-2016, setlist.fm)`. A name
the index does not resolve can be aliased in `data/recommend_aliases.tsv`; the builder
reads that file directly, so the alias works on the next build rather than the next
index regeneration. Acts that no longer exist are `ruin`s (the builder's `RUINS` set),
which is a different thing from `faded` and suppresses it.

## Region hulls

Each mainland region's dashed ghost border is a hand-built polygon in
`MANUAL_HULL` in `build_fantasy_map.py`; Outer Isles has none. Since #457:

- Neighbours share their borders vertex for vertex, so no land falls between two
  regions and no two overlap. Change a shared border in both polygons at once.
- Where a region meets the sea, its edge runs a few units offshore: the coast from
  `build/coast.json`, offset 5 units out and simplified at 2.5.
- Two rivers are borders, followed bend for bend: the Big Muddy below The Source
  (Quiet Woods west, Steel Foothills east, Secondline below both), and the creek
  from Pokey LaFarge to the sea at Valerie June's harbor (Quiet Woods north,
  Heartland south). Those edges are the river's centerline from `art/map.svg`.
- Two stretches stay unclaimed on purpose: the Gospel Desert, south of the
  Judith Hill → Ruthie Foster → Danielle Nicole road, and the fretboard north of
  the Amplified Range.

The builder comment above `MANUAL_HULL` lists the shared border points.

A pin inside a polygon decides the settlement's region, ahead of tags, the
builder's forced regions and any `region` in `map_overrides.json`: drag a pin
across a border and the next rebuild rehomes it. Moving a border rehomes every
pin it passes over, so check who sits along an edge before changing it. Only a
pin outside every polygon keeps a region from elsewhere - Taj Farrant on Farrant
Rock, Queen Latifah - and a mainland settlement in that state is flagged `stray`.

## The plate's view toggles

Four boxes in two rows, all on by default:

| row | box | shows |
|---|---|---|
| features | labels | region hulls and their labels, plus geo names (islands, waters) |
| features | routes | the thoroughfares layer from `edits/thoroughfares.json` |
| settlements | names | settlement name labels |
| settlements | unvisited | the dashed, paper-filled dots for acts not yet seen |

The boxes are display preferences only: they set `style.display` on a layer and
never change the data, the settlement count, or what the editor saves.
