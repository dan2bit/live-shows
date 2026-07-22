# live-shows

Concert tracking system for the [@dan2bit](https://www.youtube.com/@dan2bit) YouTube channel — attended and upcoming shows, potential purchases, venue intelligence, artist follow lists, and YouTube bootleg playlist management. Maintained collaboratively with [Claude](https://claude.ai) via MCP tools.

Dashboard site (GitHub Pages): **[https://dan2bit.github.io/live-shows](https://dan2bit.github.io/live-shows)/**

---
## Main Functionality

_What the main dashboard site does_

### Tracking for Upcoming Shows and Potential Purchases
Enables calendar management, driving & parking directions, prevents double or dense bookings, enables decisions on what to attend, stages links for online purchase.

### History of Attended Shows
Aggregates setlist.fm links, artist photos, bootleg videos, badges and personal show notes for all shows since the pandemic of 2020-2021. Includes a summary card for each artist, caching and normalizing information from last.fm, spotify, musicbrainz.

### Spend and Budget Management
Uses a separate private sidecar repo to record spending on and at shows. requires PAT authorization. 

### Recommendation Intake
Allows visitors to submit 1 or 2 recommendations in a day, which get reviewed in the github issue queue.

### CI Tools and gating

In `scripts` - a dozen or so python scripts for automation of github actions using `.github/workflows` 
- _agentic repo management is done in a staging branch through the official github MCP server_

---

_Work is in Progress to enable simple forking of the Main Functionality above, including `config.yaml` customization support. No agentic dependency required._

---

## Supplemental Functionality

_These vibe-coded, optional tools exist in conjunction with a dedicated set of accounts on Youtube, Spotify and Google Workspace_

### Youtube Channel Management
In `tools/youtube` - support for playlist creation and management for bootleg videos, both historical and ongoing.

### Artist Follow Management
In `tools/research` - support for personal bandsintown and seated follow rosters, as well as direct email subscription to artists and venues. Also tools for taste profile curation, venue calendar ingestion, and new artist web and spotify exploration tools.
Includes an optional [d3 forceSimulation graph visualization](https://dan2bit.github.io/live-shows/tools/research/graph/artist-graph.html) of related artists that appear in the attendance history and taste profile.

### Agentic Playbooks

In `tools/playbooks` - a handful of bespoke, *ymmv* automation workflow playbooks for site data management, inbox monitoring, calendar management and artist discovery.

