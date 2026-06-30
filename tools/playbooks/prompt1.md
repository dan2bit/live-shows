This is an inbox and data maintenance session for the live-shows project.

Repo: dan2bit/live-shows (public). Working dir root /.
Concert calendar: redhat.bootlegs@gmail.com ("Dan Concert Calendar").
Gmail account: redhat.bootlegs@gmail.com.

Start every session by:
1. **Tool preflight (blocking — do this first, before anything else).** Enumerate the tools actually available this session and report which of these are present: `tool_search`, `github:issue_write`, Gmail, Google Calendar. This session depends on deferred tools (Gmail, Calendar) that are loaded via `tool_search`.
   - If `tool_search` is ABSENT: STOP and tell Dan plainly that this is an eager-tool session, that the deferred tools (Gmail, Calendar, time) are unreachable, and that the inbox routines cannot run. Ask whether to (a) proceed with only the tools present (likely GitHub-only — data/issue work, no email/calendar), or (b) restart in a fresh session/chat to try to get the deferred-tool set. Do NOT silently proceed as if email/calendar will work.
   - If `github:issue_write` is absent: note it (recommendation-issue work will be limited).
   - Only continue to the steps below once the tool situation is stated and, if degraded, Dan has chosen how to proceed.
   (Note: whether a session gets `tool_search` is decided at session provisioning, before this prompt is read — nothing here can summon it. This check exists to surface the gap in the first 10 seconds instead of mid-routine. A fresh chat, or a Sonnet session, is the lever if it's missing.)
2. Check the current time via the MCP.
3. Noting how many days since the last inbox run (flag if 7+).
4. Fetching live_shows_current.tsv and live_shows_potential.tsv before any routine that touches them.

Available routines:
- Routine 1: ticket receipts (label:ticket-receipt)
- Routine 2: post-show notes (label:show-notes) — always updates spending.tsv, artists.tsv, and potentially autograph_books_combined.tsv (book) / hat_signatures.tsv (hat)
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
- Hat signing: female musicians who have not already signed only; check hat_signatures.tsv before flagging eligibility
- Potentials sort: Buy → Choose → Sell → Pass, date asc within groups; re-sort on every change
- Prev/Next brackets: purchased upcoming shows only; never potentials or attended
- Fetch fresh SHA immediately before every create_or_update_file call
- TSVs and data files commit to **staging** (not main); private sidecar TSVs commit to dan2bit/live-shows-private main; JS/Python scripts go to PR branch
- push_files does NOT trigger auto-promote on staging — follow up with a single-file create_or_update_file nudge, or use sequential create_or_update_file calls instead
