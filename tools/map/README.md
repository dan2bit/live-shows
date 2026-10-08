# tools/map — Guitarlandria

The fantasy-map rendering of the tracked artists: every artist a settlement, genre
gravity the terrain. The page is `map.html` and its URL does not move; everything
else is sorted by who writes it.

| path | what | written by |
|---|---|---|
| `map.html` | the viewer and, for an authed desktop, the editor | humans, by PR |
| `build_fantasy_map.py` | settlements, regions, districts from the tracking data | humans, by PR |
| `emit_heightmap.py` | the FMG heightmap seed from the built data | humans, by PR |
| `extract_coast.py` | the painted coast as polygons, from `art/map.svg` | humans, by PR |
| `docs/` | `fantasy_map_schema.md` (the data contract, the device/desktop split), `heightmap_azgaar_notes.md` (the repaint procedure) | humans |
| `edits/` | `pins.json`, `labels.json`, `map_overrides.json`, `thoroughfares.json`, `traced_waterways.json`, `discovered_adds.json` — the hand-owned state | the in-page editor (read-merge-write, to `staging`), or a hand edit |
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

An authed desktop gets edit and trace modes on `map.html`. Signed in, the page loads
every `edits/` file from `staging` through the GitHub API - where its saves land - rather
than from the Pages copy, which trails a save by the promote and the deploy; everyone else
sees the Pages copy. **save changes** writes each touched file as one Contents-API commit
to `staging`, folding only this session's changes into the file as it stands there: pins
and overrides by name, labels by `group:key`, routes by class + chain, traces appended.
An edit made while a save is running stays unsaved and goes out with the next save.

Routes: click a road, pass, trail or ferry hop to drag its waypoints, click a white handle
to add one, alt-click to remove one. The autobahn is not clickable; its waypoints are hand
edits in `thoroughfares.json`, where a hop's `via` replaces its one generated bump.

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
