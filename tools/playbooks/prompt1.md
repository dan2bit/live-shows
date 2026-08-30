This is an inbox and data maintenance session for the live-shows project.

Repo: dan2bit/live-shows (public). Working dir root /.
Concert calendar: redhat.bootlegs@gmail.com ("Dan Concert Calendar").
Gmail account: redhat.bootlegs@gmail.com.

Start every session by:
1. **Tool preflight (blocking — do this first, before anything else).** Enumerate the tools actually available this session and report which of these are present: `tool_search`, `github:issue_write`, Gmail, Google Calendar. This session depends on deferred tools (Gmail, Calendar) that are loaded via `tool_search`.
   - If `tool_search` is ABSENT: STOP and tell Dan plainly that this is an eager-tool session, that the deferred tools (Gmail, Calendar) are unreachable, and that the inbox routines cannot run. Ask whether to (a) proceed with only the tools present (likely GitHub-only — data/issue work, no email/calendar), or (b) restart in a fresh session/chat to try to get the deferred-tool set. Do NOT silently proceed as if email/calendar will work.
   - If `github:issue_write` is absent: note it (recommendation-issue work will be limited).
   - Only continue to the steps below once the tool situation is stated and, if degraded, Dan has chosen how to proceed.
   (Note: whether a session gets `tool_search` is decided at session provisioning, before this prompt is read — nothing here can summon it. This check exists to surface the gap in the first 10 seconds instead of mid-routine. A fresh chat, or a Sonnet session, is the lever if it's missing.)
2. **The `time` MCP connector (`mcp__time__get_current_time`) is no longer supported — do not call it and do not look for it in the tool preflight.** Establish today's date via the **`current-date` skill** (`/mnt/skills/user/current-date/SKILL.md`) instead: it reads a real clock (shell `TZ=America/New_York date`, or the skill's other supported methods) and falls back to asking Dan directly if no clock is reachable. Use its result for the days-since-last-run figure in step 3 and everywhere else a current date is needed this session.
3. Noting how many days since the last inbox run (flag if 7+).
4. Fetching live_shows_current.tsv and live_shows_potential.tsv before any routine that touches them.

Available routines:
- Routine 1: ticket receipts (label:ticket-receipt) — public fields (artist, date, venue, seat type, VIP/Group flags) to data/live_shows_current.tsv; private fields (cost, seat info, ticket qty, purchasing/fee notes) to **dan2bit/live-shows-private → current_private.tsv**, keyed on Show Date + Artist. Two separate commits to two separate repos, never one.
- Routine 2: post-show notes (label:show-notes) — always updates **dan2bit/live-shows-private → spending.tsv** (private repo) and data/artists.tsv, and potentially data/show_goals/book_signatures.tsv (book) / data/show_goals/hat_signatures.tsv (hat). Also files a `playlist`-labeled issue (and a `photo`-labeled issue if a photo was taken) — see the template-fetch rule below.
- Routine 3: ticket-alert newsletters (label:ticket-alert -label:processed) — requires a clear date on the calendar and explicit confirmation before any potentials write
- Routine 4: artist mail (label:artist-mail -label:processed)
- Routine 5: artist follow / signup (label:artist-follow -label:processed)
- Routine 6: ticket sold / resale (label:ticket-sold -label:processed) — updates data/live_shows_current.tsv (remove or update the row), **dan2bit/live-shows-private → current_private.tsv** (remove or update), **dan2bit/live-shows-private → spending.tsv** (negative-cost row offsetting the original purchase), and deletes the calendar event
- Incoming recommendation issues in the repo (label:recommendation) — research + supplement each new issue

Apply the `processed` label (ID: Label_421272830174798850) directly via Gmail MCP at the end of each routine. Draft activity log to redhat.bootlegs@gmail.com at session end.

Key rules in effect:
- Before recommending any Buy or Choose potential in Routine 3, check the Dan Concert Calendar (`redhat.bootlegs@gmail.com`) for the surrounding date window using the Google Calendar MCP.
-- Look for: hard conflicts (same date), consecutive-night density, and any personal calendar blocks (travel, Beach Week, etc.) that wouldn't appear in `live_shows_current.tsv`.
-- This check applies per-artist before surfacing a recommendation, not as a single batch at the end.
- Purchasing/fee notes go in Private Notes, not public Notes, unless explicitly requested otherwise
- Hat signing: eligibility per data/show_goals/hat_eligibility.tsv (#115) — Yes = target for signing. Actual signers per data/show_goals/hat_signatures.tsv (canonical). A signature never removes eligibility (completed wins in rendering). The artists.tsv Hat Autograph column is deprecated — do not set it.
- Autograph books: same eligibility/signatures split — eligibility per data/show_goals/autograph_books_eligibility.tsv, actual signers per data/show_goals/book_signatures.tsv. There is no combined file.
- **ASCII punctuation only in every TSV value** (#204): use `-` not an en/em dash, straight quotes not curly, `...` not an ellipsis. Curly punctuation in a data value silently orphans a sidecar key, goal-badge match, or alias lookup. `check_ascii_punctuation.py` scans the public TSVs and warns; accented letters are fine — this is a punctuation rule, not an ASCII-only rule. Applies to notes and prose columns too.
- Potentials sort: Buy → Choose → Sell → Pass, date asc within groups; re-sort on every change
- Prev/Next brackets: purchased upcoming shows only; never potentials or attended
- Fetch fresh SHA immediately before every create_or_update_file call
- TSVs and data files commit to **staging** (not main); private sidecar TSVs commit to dan2bit/live-shows-private main; JS/Python scripts go to PR branch
- `.github/workflows/*.yml` cannot be written by the agent — the MCP PAT was narrowed to drop Workflows write (2026-07-28) and GitHub reports the refusal as **404, not 403**. Patch locally, present the full file, hand the push to Dan.
- Auto-promote trigger: both the **Contents API** (`create_or_update_file`) and the **Git Data API** (`push_files`) fire the `push` event on staging — single writes and batches promote to main with no follow-up commit (verified 2026-08-24).
- **Issue-template fetch rule (2026-08-30):** `github:issue_write` has no template-selection parameter — unlike the "New Issue" button in the GitHub web UI, it cannot read `.github/ISSUE_TEMPLATE/` for you. Any issue that has a template file (currently `playlist.md`, `photo.md`) must be built by fetching that template live via `github:get_file_contents` and filling in every `{{PLACEHOLDER}}` from data already in hand — never reconstructed from memory, habit, or a prior issue's body. This rule exists because four open `playlist`-labeled issues (#296, #297, #300, #308) were found using stale or paraphrased task lists instead of the real template; full procedure is in `tools/playbooks/EMAIL_WORKFLOWS.md` → Routine 2 Step 6.
