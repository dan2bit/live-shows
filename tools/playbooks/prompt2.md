This is a site development and repo management session for the live-shows project.

Repo: dan2bit/live-shows (public). GitHub Pages: https://dan2bit.github.io/live-shows/.
Working dir root /. Key source files: index.html, app.js, recommend.js, styles.css.

Start every session by:
1. **Tool preflight (blocking — do this first).** Enumerate the tools actually available this session and report which of these are present: `github:issue_write` (create/update issue) and `tool_search`.
   - If `github:issue_write` is ABSENT: STOP and alert Dan — issue triage can't happen; ask whether to proceed (commits only) or restart.
   - If `tool_search` is ABSENT: note that this is an eager-tool session, so any deferred tools (Spotify, time, etc.) are unreachable. For most Site+Repo work the GitHub tools are enough, so this is usually fine to proceed — but say so explicitly rather than discovering it later.
   (Whether a session gets `tool_search` is decided at session provisioning, before this prompt is read; nothing here can summon it. A fresh chat or a Sonnet session is the lever if a deferred tool is needed and missing.)
2. Checking for open PRs awaiting merge — list them with title and status.
3. Checking for any files presented for manual check-in but not yet committed.
4. Reviewing the open issue list for anything that became actionable since the last session.

Commit rules:
- TSVs and non-executable data files → **staging** branch (not main); auto-promote.yml fast-forwards main after the guard passes
- Private sidecar TSVs (dan2bit/live-shows-private → current_private.tsv etc.) → commit to that repo's main directly; the private repo does not use the staging pipeline
- app.js → get confirmation on whether Dan should commit or directly via MCP (to staging)
- other JS, Python, shell scripts → PR branch; Dan merges
- index.html → staging directly via MCP (Unicode handled correctly by official binary)
- Always fetch fresh SHA immediately before every create_or_update_file call
- Never pass GitHub-fetched content back as commit content — read local patched file for content, use GitHub SHA only for the sha parameter
- Large architectural changes to app.js or index.html → PR branch regardless
- push_files does NOT trigger auto-promote on staging — follow up with a single-file create_or_update_file nudge commit, or use sequential create_or_update_file calls instead of push_files for data writes

Active constraints to keep in mind:
- Potential rows matched by Artist+Date in handleDecisionChange, handleRevoke, and saveEdit — never by array index (stale-index fix, commit 5cf7506)
- RECOMMEND_PAT is split across two concatenated string literals in recommend.js to pass push protection — do not reunify into a single string in any commit
- Tab labels in UI: Current, History, Potential, Waiting — TSV/JS variable names are unchanged
