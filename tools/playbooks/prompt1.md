This is an inbox and data maintenance session for the live-shows project.

Repo: dan2bit/live-shows (public). Working dir root /.
Concert calendar: redhat.bootlegs@gmail.com ("Dan Concert Calendar").
Gmail account: redhat.bootlegs@gmail.com.

Start every session by:
1. enumerating the tools available in this session. if github issue_write or tool_search are missing, alert Dan
1. Check the current time via the MCP
2. Noting how many days since the last inbox run (flag if 7+).
3. Fetching live_shows_current.tsv and live_shows_potential.tsv before any routine that touches them.

Available routines:
- Routine 1: ticket receipts (label:ticket-receipt)
- Routine 2: post-show notes (label:show-notes) — always updates spending.tsv, artists.tsv, and potentially autograph_books_combined.tsv
- Routine 3: ticket-alert newsletters (label:ticket-alert -label:processed) — requires a clear date on the calendar and explicit confirmation before any potentials write
- Routine 4: artist mail (label:artist-mail -label:processed)
- Routine 5: reminders/skips
- Incoming recommendation issues in the repo (label:recommendation) — research + supplement each new issue

Apply the `processed` label (ID: Label_421272830174798850) directly via Gmail MCP at the end of each routine. Draft activity log to redhat.bootlegs@gmail.com at session end.

Key rules in effect:
- Before recommending any Buy or Choose potential in Routine 3, check the Dan Concert Calendar (`redhat.bootlegs@gmail.com`) for the surrounding date window using the Google Calendar MCP. 
-- Look for: hard conflicts (same date), consecutive-night density, and any personal calendar blocks (travel, Beach Week, etc.) that wouldn't appear in `live_shows_current.tsv`. 
-- This check applies per-artist before surfacing a recommendation, not as a single batch at the end.
- Purchasing/fee notes go in Private Notes, not public Notes, unless explicitly requested otherwise
- Hat signing: female musicians who have not already signed only; check autograph_books_combined.tsv before flagging eligibility
- Potentials sort: Buy → Choose → Sell → Pass, date asc within groups; re-sort on every change
- Prev/Next brackets: purchased upcoming shows only; never potentials or attended
- Fetch fresh SHA immediately before every create_or_update_file call
- TSVs and data files commit to main; JS/Python scripts go to PR branch