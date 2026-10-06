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
