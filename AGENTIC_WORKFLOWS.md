# AGENTIC_WORKFLOWS.md

> **Audience:** This document is Dan-specific and not part of the forkable template. It describes how agentic AI (Claude, via claude.ai Projects with MCP tool access) is used to manage the live-shows dataset. It is written as an annotated architecture reference for technically inclined forkers who want to build similar workflows — the patterns are general even when the specifics are Dan's.

---

## The core idea

The live-shows project is not just a static list. It is a living dataset that grows through a set of recurring workflows: discovering artists, evaluating shows, buying tickets, attending, documenting, and publishing. Each of these workflows involves reading from external sources, making decisions, and writing structured data back to the repo, calendar, or inbox.

An agentic AI — meaning an AI with tool access that can read and write on your behalf — can handle most of the mechanical work in these workflows: fetching emails, parsing show details, updating TSV rows, creating calendar events, running playlist scripts. What it cannot replace is your judgment: whether to buy a ticket, how much you liked a show, whether an artist is worth following.

The design principle here is that the AI handles retrieval, formatting, and writing; the human handles evaluation and approval. No commit happens without explicit confirmation. No calendar event is created without an autograph book check. The AI is a fast, tireless clerk, not an autonomous agent.

---

## Dedicated account architecture

**What it does:** Isolates all live-shows operational data (email, calendar, photos) from personal accounts.

**Why it matters for agentic access:** When you grant an AI MCP access to Gmail or Google Calendar, you are granting broad read (and potentially write) access. Using a dedicated account means the AI only sees show-relevant mail and events, not personal correspondence or unrelated calendar items. This reduces noise, reduces risk, and makes the AI's search results much more precise.

**Two setup options:**

**Option A — All-in-one:** The dedicated account is also the account you use to purchase tickets and draft show notes. Venue newsletters, ticket confirmations, artist mail, and your own post-show notes all arrive in the same inbox. The AI has a single coherent view of everything. Simpler to set up; means your ticket purchases and any associated payment methods are tied to this account.

**Option B — Hub and spoke:** You purchase tickets and draft show notes from a separate personal account, and forward or BCC the dedicated account on purchase confirmations and show notes emails. The dedicated account is a receiver and operational hub only — it holds the newsletter subscriptions, the calendar, and the structured data, but not your payment history or personal drafts. Slightly more friction to set up; cleaner separation between personal and project data, and the AI never touches your primary inbox.

Either option works with the inbox routines described below. Option B requires consistent forwarding discipline; Option A requires comfort with the dedicated account being the AI's primary operational surface.

**Minimal implementation:**
- Create a dedicated Google account for the project
- Subscribe to venue newsletters, ticket services, and artist mailing lists from that account
- Option A: purchase tickets and send show notes from this account directly
- Option B: forward purchase confirmations and show notes from your primary account to the dedicated account
- Use the dedicated account's Google Calendar as the show calendar
- Store show photos in Google Photos under the dedicated account

**Extended capabilities:**
- Use the dedicated account's YouTube channel for bootleg playlist publishing (see YouTube workflows below)
- Set up Gmail filters to auto-label incoming mail by source type (venue newsletter, ticket alert, artist mail, show notes from self)
- The label structure becomes the input interface for inbox routines — the AI queries by label, not by keyword

---

## Inbox workflows

**What it does:** Processes labeled Gmail threads to extract structured data — new show announcements, ticket alerts, artist updates, and self-sent show notes — and routes each to the appropriate TSV or calendar action.

**Data sources read:** Gmail (dedicated account), labeled threads
**Data written:** `live_shows_potential.tsv`, `live_shows_current.tsv`, `live_shows_history.tsv`, `notes_memories_draft.tsv`, Google Calendar

**The four routine types:**

**Routine 1 — Show notes from self** (`from:[your-notes-address] -label:processed`)
After attending a show, send yourself an email with setlist, notes, and memories. Under Option A this comes from the dedicated account itself; under Option B it is forwarded or BCC'd from your primary account. The agent reads these, drafts TSV updates for history, and flags them for approval before writing. This captures the post-show documentation loop without requiring you to be at a keyboard in the venue. If Option B, also check the Drafts folder of your primary account for show notes that were drafted but not sent.

**Routine 2 — Ticket confirmations** (`label:ticket-confirmation -label:processed`)
Order confirmation emails from ticket services. Under Option A these arrive directly; under Option B they are forwarded from your primary account. Agent extracts artist, date, venue, ticket service, order number, seat/section, and price; drafts a new row for `live_shows_current.tsv` and a calendar event for approval.

**Routine 3 — Venue and ticket service newsletters** (`label:ticket-alert -label:processed`)
Newsletters from venue mailing lists and ticket services. Agent scans for artists on your follow list, flags new shows matching your geography and tier preferences, and drafts potential rows for approval.

**Routine 4 — Artist mail** (`label:artist-mail -label:processed`)
Direct artist mailing lists and Bandsintown/Songkick notifications. Agent extracts tour dates in your region, cross-references the follow list, and surfaces candidates.

**Key design constraint:** The `processed` label is always applied manually by the human, never by the agent. This ensures every processed thread was actually reviewed, not just touched.

**Minimal implementation:**
- Four Gmail labels: `ticket-confirmation`, `ticket-alert`, `artist-mail`, `processed`
- Gmail filters routing incoming mail to the right labels
- An AI with Gmail MCP access and read access to the repo's follow list and venues TSV

**Extended capabilities:**
- Monthly refresh of follow-service exports (Bandsintown, Songkick) as TSV files committed to `web-src/`, used as a backstop when newsletters miss a show
- Activity log drafts emailed to the dedicated account summarizing what each routine processed

---

## Follow services (Bandsintown, Songkick)

**What it does:** Uses artist-follow services as a structured discovery feed, supplementing (not replacing) venue newsletters.

**Data sources read:** Bandsintown and Songkick web exports, venue TSV
**Data written:** `live_shows_potential.tsv`, `web-src/` (monthly snapshots)

**How it works:** Both Bandsintown and Songkick let you follow artists and see upcoming shows. Neither provides a clean API for personal use, so the practical approach is periodic manual export (or browser-assisted scraping) of your upcoming shows feed, saved as TSVs in `web-src/`. The AI then cross-references these against your venues TSV to identify shows at known venues in your region, and against your potentials TSV to avoid duplicates.

**Polling pattern:** Monthly refresh on the first Tuesday of Jan/Apr/Jul/Oct (quarterly for deep research, monthly for feed snapshots). The AI can run a browser session against Bandsintown and Songkick to pull current data if Claude in Chrome is available.

**Signals that matter:**
- New show announced for a followed artist in your region → draft potential row
- Low ticket / sold out warning → escalate if the show is on your potentials list
- On-sale date announcement → add to watching-for field on existing potential row

**Minimal implementation:** Manual quarterly export of your BIT following list; agent cross-references against venues TSV and follow tier list.

**Extended capabilities:** Gnoosic-style artist discovery (`gnoosic.com/artist/[name]`) — a browser-assisted workflow where the agent navigates to an artist's Gnoosic page, clicks "I like it" on known artists to refine recommendations, and surfaces new names for the follow list.

---

## Calendar integration

**What it does:** Keeps a Google Calendar in sync with `live_shows_current.tsv` — one event per confirmed show, with structured fields in the description.

**Data sources read:** `live_shows_current.tsv`, `venues.tsv`, `autograph_books_combined.tsv`
**Data written:** Google Calendar (dedicated account)

**Event structure:** Each calendar event includes artist, venue, doors/show times, parking notes, ticket service, order number, seat/section, and any artist interaction goals. The description is structured enough that the calendar becomes a portable show guide — everything you need the night of the show is in the event.

**Autograph book check:** Before creating any calendar event, the agent checks `autograph_books_combined.tsv` to see if the artist has a page in the autograph book. If so, the event description notes which book and page, so you remember to bring it. This is a hard pre-condition — no event without the check.

**Minimal implementation:**
- Google Calendar MCP access
- A consistent event template (artist — venue in the title; structured description)
- Manual approval before every event creation
- **NO SHOWS blocks:** All-day or multi-day calendar events marking periods when no tickets should be bought — travel, family commitments, recovery time, or voluntary density limits. The agent checks for these before drafting any new show event or potential row, and flags a conflict if one exists. The block itself carries a note explaining the reason (e.g. "out of town" or "rest — too many recent shows").
- **Conflict check:** Before creating any show event or adding a row to potentials, the agent queries the calendar for existing events on the target date and adjacent dates. If a confirmed show or NO SHOWS block already exists, it surfaces the conflict explicitly ("you already have Carolyn Wonderland on 9/24 — is Robin Trower still worth adding as a potential?") rather than silently proceeding. Same-night conflicts are hard stops; adjacent-night conflicts are flagged as density warnings for the human to weigh.

**Known friction:** Google Calendar MCP fails silently on the Android app. Calendar operations should be run from a desktop browser session.

**Extended capabilities:**
- Prev/Next show brackets in the event description, so you can see the surrounding show density at a glance
- Automatic update when a show is rescheduled or cancelled
- Monthly budget summary event on the last day of each month

---

## YouTube channel and playlist management

**What it does:** Manages a YouTube channel of live concert bootlegs — creating playlists per show, ordering videos by setlist, and maintaining descriptions with show metadata.

**Data sources read:** `live_shows_history.tsv`, `youtube_create_playlists.py`, setlist.fm (for song order)
**Data written:** YouTube playlists (via YouTube Data API), `youtube_create_playlists.tsv`

**Architecture:** Two Python scripts manage the YouTube workflow:
- `youtube_create_playlists.py` — creates a playlist per show and populates it with videos in setlist order, using setlist.fm as the ordering source
- `youtube_fix_descriptions.py` — updates playlist descriptions with structured show metadata

**Key constraint:** Scripts require a Python venv and OAuth credentials under the YouTube channel's Google account (separate from the dedicated Gmail account if the channel predates the project). Scripts are committed to a PR branch and merged by hand — never auto-committed to main.

**Minimal implementation for forkers:** The YouTube workflow is the most infrastructure-heavy part of this project. A forker would need a YouTube channel, OAuth credentials, and Python comfort. The scripts are documented but this workflow is explicitly optional.

---

## Photo and media storage

**What it does:** Organizes show photos in Google Photos under the dedicated account, with consistent tagging by artist and date.

**Data sources read:** `artists.tsv`, `artist-photos.tsv`
**Data written:** `artist-photos.tsv` (tracking which artists have photos on file)

**Pattern:** Photos are taken on a device logged into the dedicated Google account so they auto-upload to the right Photos library. After each show, `artist-photos.tsv` is updated to record that a photo exists. The `apply_photos.py` script handles bulk tagging.

**Hat signing:** A separate physical autograph book tracks hat signatures. Female musicians only (by convention). The autograph book check before calendar events covers both the book and the hat.

---

## Project memory and preference modeling

**What it does:** Uses the accumulated TSV data as a structured preference profile, surfaced on demand or used implicitly to score new candidates.

**Data sources read:** `live_shows_history.tsv`, `live_shows_potential.tsv`, `artists.tsv`, `follows/` directory
**Data written:** Claude's memory system (persistent cross-session summaries), `follows/new_artist_research.tsv`

**The implicit model:** Your history TSV is already a rich preference signal. Patterns that emerge with enough data:

- **Tier distribution** — what fraction of your shows are Strong vs Medium vs Low tier artists? This sets a baseline for what "worth going" means to you.
- **Decision patterns** — which factors consistently push a potential from Choose to Buy (venue size? ticket price? solo vs band format?) or from Choose to Pass (distance? consecutive nights? already seen recently?)?
- **Venue affinity** — which venues do you return to most? What capacity range? Seated vs standing?
- **Genre balance** — blues-heavy with occasional diversions; how far from the center is too far?
- **Show density preferences** — how many consecutive nights before fatigue? What's the comfortable monthly cadence?
- **Travel radius** — what distance is a stretch vs comfortable vs routine?

**Explicit surfacing:** "Tell me where Rufus Wainwright fits in my taste profile" is a direct query against this model. The AI reads your history, your tier ratings for similar artists, your genre notes, and your past Decision reasoning, and synthesizes an assessment. It is not a numerical score — it is a qualitative judgment informed by structured data.

**Claude's memory system:** Claude.ai Projects maintain a persistent memory across sessions, populated from conversation history. Key facts (follow tiers, venue defaults, recurring companions, budget rules, tool constraints) are stored there so they don't need to be re-established each session. The TSV files are the ground truth; memory is the working index.

**Minimal implementation:** The history TSV alone is enough to start. Even 20–30 shows creates a meaningful signal. The preference model doesn't require any additional infrastructure — it runs on the AI's ability to read and reason about the data.

**Extended capabilities:**
- `new_artist_research.tsv` tracks artists surfaced through discovery workflows before they graduate to the main follow list, with a tier assignment and discovery source
- Quarterly artist research routine: cross-reference the follow list against upcoming shows in the region, flag anything not yet on potentials. Research sources extend beyond follow services — music award nominee lists (Grammy, Blues Music Awards, etc.), festival and music cruise lineups, and local musician showcases are all productive inputs. Each surfaces a different slice of the discovery space: awards catch critically recognized artists you may have overlooked, festival lineups reveal who is touring actively, and local showcases surface regional artists below the national radar.
- Gnoosic-assisted discovery: starting from a known artist, navigate the similarity graph to surface new names, rate them against the preference model, add strong candidates to research TSV
- **`fast_track.tsv` — human-driven override list:** A manually maintained list of artists who bypass the normal inference pipeline and are automatically promoted to an instant buy regardless of what the preference model or tier data would suggest. These are artists where no amount of scoring is needed — the answer is always yes. The agent checks this list first when processing any new show announcement, before applying any other logic. Because it is a human override rather than an inferred preference, it is never modified by the agent; only the human adds or removes entries. Typical candidates: artists with deep personal significance, rare touring acts where any appearance is an event, or artists where past shows have been exceptional enough to establish unconditional trust.

---

## Recommendation engine

**What it does:** Connects the discovery feeds (follow services, newsletters, Gnoosic) to the preference model to proactively surface shows worth considering, without waiting for you to ask.

**Data sources read:** All of the above
**Data written:** `live_shows_potential.tsv` (new rows, draft for approval)

**How recommendations work in practice:**

1. A new show is announced for an artist on your follow list → automatic candidate, tier already known
2. A new show is announced for an artist *not* on your follow list → agent checks if the artist appears in history notes, research TSV, or recommendation chains; if so, surfaces with context
3. A newsletter mentions an unfamiliar artist → agent checks Bandsintown for tour history and regional presence, cross-references genre against preference model, assigns a provisional tier, asks whether to add to follow list
4. Gnoosic session surfaces a new name → agent drafts a research TSV row with similarity basis and provisional tier for approval

**Proximity tier logic:** Geography matters — a show 10 miles away clears a lower bar than one 60 miles away. The venues TSV records approximate distance and drive time from home base. The preference model weights these: Strong artists at far venues are still worth it; Medium artists at far venues usually aren't unless the venue itself is a draw.

**The recommendation loop is never fully automated.** Every candidate that reaches `live_shows_potential.tsv` was approved by the human. The agent surfaces and drafts; the human decides.

---

## Running these workflows with Claude

All of these workflows run through Claude.ai with MCP tools connected:

- **GitHub MCP** — read/write repo files and issues
- **Gmail MCP** — read labeled threads (dedicated account)
- **Google Calendar MCP** — create and update show events
- **Claude in Chrome** — browser-assisted tasks (Bandsintown scraping, Gnoosic sessions, ticket service navigation)
- **Time MCP** — provides the current date and time before any date-sensitive operation. Critical for workflows that depend on knowing what "now" is: pruning past shows from the potentials list, identifying upcoming shows within a rolling window, checking whether an on-sale date has passed, or computing how many days until a show. Without an authoritative time source, the agent relies on its training cutoff, which can be months stale.

The system prompt (Claude Instructions, pinned to the Project) carries the standing rules, defaults, and schema knowledge so each session starts with full context. The memory system carries the dynamic facts that accumulate over time.

The workflows are invoked conversationally — "run Routine 3" or "process inbox" — rather than through scripts or cron jobs. This keeps the human in the loop at each step and makes it easy to deviate from the routine when something unexpected comes up.
