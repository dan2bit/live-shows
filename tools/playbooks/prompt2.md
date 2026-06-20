This is a site development and repo management session for the live-shows project.

Repo: dan2bit/live-shows (public). GitHub Pages: https://dan2bit.github.io/live-shows/.
Working dir root /. Key source files: index.html, app.js, recommend.js, styles.css.

Start every session by:
1. enumerate your available tools and specifically check for two things: github issue_write (create/update issue) and tool_search. If not available, alert Dan
2. Checking for open PRs awaiting merge — list them with title and status.
3. Checking for any files presented for manual check-in but not yet committed.
4. Reviewing the open issue list for anything that became actionable since the last session.

Commit rules:
- TSVs and non-executable data files → main directly via MCP
- app.js -> get confirmation on whether Dan should commit or directly via MCP
- other JS, Python, shell scripts → PR branch; Dan merges
- index.html → main directly via MCP (Unicode handled correctly by official binary)
- Always fetch fresh SHA immediately before every create_or_update_file call
- Never pass GitHub-fetched content back as commit content — read local patched file for content, use GitHub SHA only for the sha parameter
- Large architectural changes to app.js or index.html → PR branch regardless

Active constraints to keep in mind:
- Potential rows matched by Artist+Date in handleDecisionChange, handleRevoke, and saveEdit — never by array index (stale-index fix, commit 5cf7506)
- RECOMMEND_PAT is split across two concatenated string literals in recommend.js to pass push protection — do not reunify into a single string in any commit
- Tab labels in UI: Current, History, Potential, Waiting — TSV/JS variable names are unchanged
