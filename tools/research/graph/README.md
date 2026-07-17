# artist-graph

Force-directed Last.fm similarity network for the artists under management —
tracked artists as discs (size = affinity or times seen, color = tier derived
from `theme.color_accent`, amber ring = hat signed), with untracked names that
appear as "similar" to ≥N tracked artists rendered as hollow teal candidate
nodes. This makes the Strategy-session discovery heuristic ("densely-connected
in the DMV blues peer network") visible: raise or lower the candidate threshold
slider to control how much unexplored territory shows.

**Live page:** https://dan2bit.github.io/live-shows/tools/research/graph/artist-graph.html

The page fetches `artist_modal_index.json`, `artist_spotify.json`,
`recommend_aliases.tsv`, and `config.yaml` from the deployed site at load, so it
always reflects current `main` with no build step. It is deliberately not linked
from the main site — it's a research instrument, not a visitor feature.

**Strategy-session workflow:** open the page, set the candidate threshold to 3+,
and review hollow nodes not already in `new_artist_research.tsv` or
`follows_master.tsv`. A candidate's tooltip lists which tracked artists point at
it. High in-degree candidates sitting inside the blues cluster are annexation
material; candidates off the Americana coast chart the folk frontier.

Opening the file locally requires a static server (`python3 -m http.server` from
the repo root, then `/tools/research/graph/artist-graph.html`) — `file://` can't
fetch the relative data paths.

See issue #171 for the full rendering spec and normalization rules.
