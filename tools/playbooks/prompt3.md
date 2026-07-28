This is a strategic planning session for the live-shows project.

Repo: dan2bit/live-shows (public). GitHub Pages: https://dan2bit.github.io/live-shows/.

This session is for open-ended work: architectural design, artist research and follow tier decisions, 
quarterly inbox refresh analysis (Routine 3 deep pass), artist discovery (Gnoosic, festival lineups, 
award nominees), and fork-template design (the #19 / #72 successors — see Active strategic threads).

Start every session by:
1. **Tool preflight (blocking — do this first, before any work).** Enumerate the tools actually available this session and report which of these are present: `tool_search`, `github:issue_write`, and (if the session's work needs them) Spotify, Calendar, time, and Claude-in-Chrome.
   - If `tool_search` is ABSENT: this is an eager-tool session — every deferred tool (Spotify, Calendar, time, Chrome, Gmail) is unreachable, and `tool_search` cannot be summoned by anything in this prompt (provisioning happens before the prompt is read). STOP and tell Dan plainly which tools are present, that the deferred ones are unavailable, and ask whether to (a) proceed with the subset that works (often GitHub-only — issue/architecture/research-writeup work, no Spotify/Chrome/calendar), or (b) restart in a fresh session/chat to try to get the deferred set. Do NOT silently start work that will hit a wall three steps in.
   - If `github:issue_write` is absent: STOP and alert Dan — most strategy work lands as issues, so this is a hard blocker.
   - Only proceed once the tool state is stated and, if degraded, Dan has chosen the path.
   (This has bitten before — e.g. a session with no `tool_search` that couldn't fetch the time or reach Spotify mid-task. A fresh chat, or a Sonnet session, is the lever when the deferred set is missing; this check just makes the gap visible in the first 10 seconds.)

Before substantive work, check:
- Open issues relevant to the session's focus area
- The open fork-template threads (see Active strategic threads) if doing template design work
- tools/research/follows/follows_master.tsv and tools/research/follows/new_artist_research.tsv if doing artist research
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
- Scripts and code → PR branch; Dan merges
- `.github/workflows/*.yml` cannot be written by the agent — the MCP PAT was narrowed to drop Workflows write (2026-07-28) and GitHub reports the refusal as **404, not 403**. Patch locally, present the full file, hand the push to Dan.
- Auto-promote trigger: the **Contents API** (`create_or_update_file`) fires the `push` event and promotes staging to main. The **Git Data API** (`push_files`, or a manual blobs → tree → commit → ref sequence) does not. After any Git Data batch, follow up with a single-file Contents write — ideally a real change rather than a synthetic nudge.
- **ASCII punctuation only in every TSV value** (#204): `-` not an en/em dash, straight quotes not curly, `...` not an ellipsis. Curly punctuation silently orphans sidecar keys, goal-badge matches, and alias lookups. Accented letters are fine — this is a punctuation rule, not an ASCII-only rule.

Active strategic threads:
- Fork-ready template. #19 (restructure as reusable template, closed 2026-06-22) and #72
  (annotations and documentation for forking, closed 2026-07-27) are both DONE — read them for
  history only. The live work is #199–#205 (de-bespoke sweep, issue log + evergreen-comment
  convention, config restructure, FORK_SETUP levels, Spotify playbook split, CI hygiene guards),
  #216 (Level 0 bootstrap: sample-files/ exemplar tree + fork_reset.py + header drift check),
  and #220 (data-hygiene: blocking vs advisory split, and giving the advisory half a reader).
- Gnoosic artist discovery (Claude in Chrome, work interrupted — resume from https://www.gnoosic.com/artist/larkin+poe)
- Quarterly artist research workflow: first run Jul 7, 2026 (festival lineups + award nominees)
- On-sale dates to watch: read the `Watching For` column in data/live_shows_potential.tsv — that
  column is the source of truth and is maintained by Routine 3. Do not keep a hand-copied list
  here; it drifts out of date between sessions.
