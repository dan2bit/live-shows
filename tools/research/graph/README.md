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

**Kinship edges (#174):** solid amber edges mark membership/kinship relations
the co-listening data can't see — fronts, member-of, successor-of, sibling —
sourced from `data/related_acts.tsv` (domain content, same species as
`recommend_aliases.tsv`) plus bill relations derived from the `Via` column of
`data/artists.tsv` (TajMo, SatchVai, etc., which stay authoritative there). Add
a `data/related_acts.tsv` row whenever a new fronts / successor / sibling
relation shows up in `follows_master` notes; rows whose endpoints aren't
tracked yet are skipped silently and activate when the artist lands. A node's
tooltip lists its kin with relation labels.

**Concert-history edges (#177):** the same solid treatment also carries edges
derived from Dan's own attendance logs. Bill edges connect headliner ↔ support
act from attended `live_shows_current.tsv` rows (`Supporting Artist`) and
`data/history/*.tsv` (`Supporting Acts`), with multiple support acts
`/`-separated. Shared-personnel edges connect two tracked headliners when the
same `data/seen_with.tsv` sideman appears with both (≥2 different headliners;
the sideman gets no node of their own). Attended shows only — upcoming rows and
potential-show `Support` are deliberately excluded. On overlap, label
precedence is curated #174 relation > `same bill` > `shared personnel: <name>`,
and the matching taste edge is suppressed exactly as with #174. Endpoints that
don't resolve to tracked nodes skip silently.

**Strategy-session workflow:** open the page, set the candidate threshold to 3+,
and review hollow nodes not already in `new_artist_research.tsv` or
`follows_master.tsv`. A candidate's tooltip lists which tracked artists point at
it. High in-degree candidates sitting inside the blues cluster are annexation
material; candidates off the Americana coast chart the folk frontier.

Opening the file locally requires a static server (`python3 -m http.server` from
the repo root, then `/tools/research/graph/artist-graph.html`) — `file://` can't
fetch the relative data paths.

See issue #171 for the full rendering spec and normalization rules, and #174 for
the kinship edge design.

# geographic narrative

_generated 7-17-26_

The map is dominated by a single warm supercontinent: contemporary blues and
blues-rock, where nearly every heavyweight in the system lives within a border
crossing of the others. Vanessa Collier, Larkin Poe, Samantha Fish, Ana Popović, Sue
Foley, and Kingfish form its dense interior — the Last.fm similarity roads there are
so thick that dragging any one of them pulls half the continent along. Its coastlines
shade off gradually rather than ending: a Gulf-facing shore of swamp and slide (Tab
Benoit, Sonny Landreth, Eric Johanson) drifts toward the New Orleans funk-and-brass
delta where Galactic, Trombone Shorty, and the Dirty Dozen Brass Band trade horns,
while the northern highlands climb through Texas and Chicago tradition — Jimmie
Vaughan, Robert Cray Band, Buddy Guy — up to a legacy ridge where the elders keep
touring past ninety. A second, cooler landmass sits across a narrow strait: the
Americana-and-roots continent of The Lone Bellow, The Wood Brothers, Jake Xerxes
Fussell, and Shakey Graves, connected to blues country by a handful of bridge artists
— Valerie June, Amythyst Kiah, Rhiannon Giddens — who hold dual citizenship and keep
the two worlds in trade.

Beyond the continents, the archipelagos: a Celtic islet where Young Dubliners, Gaelic
Storm, and the Enter the Haggis successor states cluster with ferry service mostly to
each other; a guitar-virtuoso atoll (Satriani, Vai, Matteo Mancuso, Mohini Dey) whose
technical volcanoes rise steeply from deep water; and scattered one-off islands with
no roads at all — Suzanne Vega, They Might Be Giants, AJR, Sparkbird — visited for
their own sake, no connecting flights required. The unexplored territory rings all of
it in teal: hollow, dashed outlines of lands the map knows exist only because tracked
artists keep pointing toward them. Some sit just offshore of the blues interior with
multiple roads already sketched in — Alastair Greene, Aynsley Lister, Janiva Magness,
Toronzo Cannon — practically annexation candidates. Others mark the far folk frontier
off the Americana coast: Sarah Jarosz, Rosanne Cash, Shawn Colvin, Brandi Carlile,
territories the system's own geography keeps recommending. The threshold slider is the
expedition budget: raise it and only the most-charted unknowns remain; lower it and
the fog of war recedes to show every rumored coastline at once.
