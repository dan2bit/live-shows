# live-shows

Concert tracking system for the [@dan2bit](https://www.youtube.com/@dan2bit) YouTube channel — attended and upcoming shows, potential purchases, venue intelligence, artist follow lists, and YouTube bootleg playlist management. Maintained collaboratively with [Claude](https://claude.ai) via MCP tools.

Dashboard site (GitHub Pages): **https://dan2bit.github.io/live-shows/**

---
## Main Functionality

_What the main dashboard site does_

### Tracking for Upcoming Shows and Potential Purchases
Enables calendar management, driving & parking directions, prevents double or dense bookings, enables decisions on what to attend.

### History of Attended Shows
Aggregates setlist.fm links, artist photos, bootleg videos, badges and personal show notes for all shows since the pandemic of 2020-2021

### Spend and Budget Management
Uses a separate private sidecar repo to record spending on and at shows. requires PAT authorization. 

### Recommendation Intake
Allows visitors to submit 1 or 2 recommendations in a day, which get reviewed in the github issue queue

---

_Work is in Progress to enable simple forking of the Main Functionality above_

---

## Supplemental Functionality

_These vibe-coded tools exist in conjunction with a dedicated set of accounts on Youtube, Spotify and Google Workspace_

### Youtube Channel Management
In `tools/youtube` - support for playlist creation and management for bootleg videos, both historical and ongoing

### Artist Follow Management
In `tools/research` - support for bandsintown, seated and songkick rosters, as well as direct email subscription
Also tools for taste profile curation and new artist web and spotify exploration tools

### Agentic Playbooks

In `tools/playbooks` - a few bespoke, *ymmv* automation workflow playbooks for inbox monitoring, calendar management and artist discovery
