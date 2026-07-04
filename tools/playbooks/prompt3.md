This is a strategic planning session for the live-shows project.

Repo: dan2bit/live-shows (public). GitHub Pages: https://dan2bit.github.io/live-shows/.

This session is for open-ended work: architectural design, artist research and follow tier decisions, 
quarterly inbox refresh analysis (Routine 3 deep pass), artist discovery (Gnoosic, festival lineups, 
award nominees), and issue #19 (fork-ready template design).

Start every session by:
1. **Tool preflight (blocking — do this first, before any work).** Enumerate the tools actually available this session and report which of these are present: `tool_search`, `github:issue_write`, and (if the session's work needs them) Spotify, Calendar, time, and Claude-in-Chrome.
   - If `tool_search` is ABSENT: this is an eager-tool session — every deferred tool (Spotify, Calendar, time, Chrome, Gmail) is unreachable, and `tool_search` cannot be summoned by anything in this prompt (provisioning happens before the prompt is read). STOP and tell Dan plainly which tools are present, that the deferred ones are unavailable, and ask whether to (a) proceed with the subset that works (often GitHub-only — issue/architecture/research-writeup work, no Spotify/Chrome/calendar), or (b) restart in a fresh session/chat to try to get the deferred set. Do NOT silently start work that will hit a wall three steps in.
   - If `github:issue_write` is absent: STOP and alert Dan — most strategy work lands as issues, so this is a hard blocker.
   - Only proceed once the tool state is stated and, if degraded, Dan has chosen the path.
   (This has bitten before — e.g. a session with no `tool_search` that couldn't fetch the time or reach Spotify mid-task. A fresh chat, or a Sonnet session, is the lever when the deferred set is missing; this check just makes the gap visible in the first 10 seconds.)

Before substantive work, check:
- Open issues relevant to the session's focus area
- Current state of issue #19 including all comments, if doing template design work
- follows/follows_master.tsv and follows/new_artist_research.tsv if doing artist research
- **dan2bit/live-shows-private → taste_profile.md** if doing artist research or follow-tier work
  (private repo, file at repo root — fetch via MCP get_file_contents; raw.githubusercontent does
  NOT work for the private repo)

Taste profile for artist evaluation:
The authoritative profile is **dan2bit/live-shows-private → taste_profile.md** (root of the
private repo — moved from the public repo 2026-07-04). It carries the full genre map, anchor
artists, venue preferences, buy/pass signals, curated-source hit-rate weighting, and discovery
methods, and is reassessed at the close of each quarterly research run. Read it before tiering
or researching artists; the summary below is orientation only.
Quick orientation: blues, blues-rock, Americana, roots. Primary venues: small/mid-size
(Rams Head, Hamilton Live, Birchmere, 9:30 Club, Jammin' Java, Hub City Vinyl, Hylton,
Collective Encore). Arena shows are generally out of scope regardless of artist.
Cruises and multi-day festivals are generally out of scope for attending, but if they are
curated to Dan's taste profile, the lineups are good sources for artist discovery.

Follow tier model:
- Strong: automatic buy for any DMV date at any in-scope venue, willing to travel to Hub City
- Medium-Strong: buy for DC/MD/VA core venues; Hub City only if no closer date expected
- Medium: regional cap — pass on Hub City, wait for Rams Head/Hamilton/Birchmere/9:30
- Low: watch only; no active purchase intent

Commit rules (for any file writes in this session):
- TSVs and data files → **staging** branch in dan2bit/live-shows; auto-promote.yml fast-forwards main after guard passes
- Private sidecar TSVs → dan2bit/live-shows-private main directly
- push_files does NOT trigger auto-promote on staging — follow up with a single-file create_or_update_file nudge, or use sequential create_or_update_file calls
- Scripts and code → PR branch; Dan merges

Active strategic threads:
- Issue #19 and related issues: fork-ready template (config.yaml, CSS/JS separation, fast_track exemplar, features flags)
- Gnoosic artist discovery (Claude in Chrome, work interrupted — resume from https://www.gnoosic.com/artist/larkin+poe)
- Quarterly artist research workflow: first run Jul 7, 2026 (festival lineups + award nominees)
- On-sale dates to watch: Shemekia Copeland Aug 4, Angélique Kidjo Aug 4, Whitney Mongé by email invite early August
