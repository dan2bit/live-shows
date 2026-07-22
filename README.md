# live-shows

Concert tracking system for the [@dan2bit](https://www.youtube.com/@dan2bit) YouTube channel — attended and upcoming shows, potential purchases, venue intelligence, artist follow lists, and YouTube bootleg playlist management. Maintained collaboratively with [Claude](https://claude.ai) via MCP tools.

Dashboard site (GitHub Pages): **[https://dan2bit.github.io/live-shows/](https://dan2bit.github.io/live-shows/)**

---
## Main Functionality

_What the main dashboard site does_

### Tracking for Upcoming Shows and Potential Purchases
Enables calendar management, driving & parking directions, prevents double or dense bookings, enables decisions on what to attend, stages links for online purchase.

### History of Attended Shows
Aggregates setlist.fm links, artist photos, bootleg videos, badges and personal show notes for all shows since the pandemic of 2020-2021. Includes a summary card for each artist, caching and normalizing information from last.fm, spotify, musicbrainz.

### Show Goals and Badges
An optional layer on top of the history: hat signatures, autograph books, and artist photo albums tracked as event logs, rendered as badges and gauges on the artist summary cards. Spec: [`docs/GOALS_SPEC.md`](docs/GOALS_SPEC.md).

### Spend and Budget Management
An optional, separate private sidecar repo records actual spending on and at shows — potential ticket prices are public; actual spend, seats, and quantities are not. Requires PAT authorization.

*Detailed Data Schema documentation for the tsv file storage layer: [`docs/PROJECT.md`](docs/PROJECT.md)**

### Recommendation Intake
Allows visitors to submit 1 or 2 recommendations in a day, which get reviewed in the github issue queue.

### CI Tools and gating

A bespoke, optional automation layer: all agentic and bot writes land on a `staging` branch, pass a private-data guard, and auto-promote to `main`. A dozen or so python scripts in `scripts` back the workflows — see [`.github/workflows/README.md`](.github/workflows/README.md) for the full pipeline and catalog.
- _agentic repo management is done in a staging branch through the official github MCP server_

---

_[Work is in progress](https://github.com/dan2bit/live-shows/issues/72) to enable simple forking of the Main Functionality above, including `config.yaml` customization support. No agentic dependency required._

---

## Supplemental Functionality

_These vibe-coded, optional tools exist in conjunction with a dedicated set of accounts on YouTube, Spotify and Google Workspace_

### YouTube Channel Management
In `tools/youtube` - support for playlist creation and management for bootleg videos, both historical and ongoing.

### Artist Follow Management
In `tools/research` - support for personal bandsintown and seated follow rosters, as well as direct email subscription to artists and venues. Also tools for taste profile curation, venue calendar ingestion, and new artist web and spotify exploration tools.
Includes an optional [d3 forceSimulation graph visualization](https://dan2bit.github.io/live-shows/tools/research/graph/artist-graph.html) of related artists that appear in the attendance history and taste profile.

### Agentic Playbooks

In `tools/playbooks` - a handful of bespoke, *ymmv* automation workflow playbooks for site data management, inbox monitoring, calendar management and artist discovery. Architecture reference: [`docs/AGENTIC_WORKFLOWS.md`](docs/AGENTIC_WORKFLOWS.md).
