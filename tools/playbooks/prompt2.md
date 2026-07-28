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
- `.github/workflows/*.yml` → **cannot be committed by the agent at all; hand off to Dan.** See "Workflow files" below.
- Always fetch fresh SHA immediately before every create_or_update_file call
- Never pass GitHub-fetched content back as commit content — read local patched file for content, use GitHub SHA only for the sha parameter
- Large architectural changes to app.js or index.html → PR branch regardless

Workflow files (`.github/workflows/*.yml`):
- The MCP PAT was **narrowed on 2026-07-28 to drop Workflows write**, deliberately: the private-data guard is the backstop for the 2026-06-27 leak, and a guard the agent can rewrite is not an independent check. The capability now lives with Dan's local `gh` (its OAuth token carries the `workflow` scope), which is the credential under his hand rather than the agent's.
- **GitHub reports this refusal as `404 Not Found`, not `403`.** Any blob, tree, commit, or contents write whose path is under `.github/workflows/` fails as a 404. Read an unexplained 404 on a workflow path as a permissions answer, not as a missing file — do not go hunting for a typo in the path.
- Correct handoff: patch the file locally, verify with the relevant checkers, present the **full file** for check-in, and give Dan the exact commit command. Never present a fragment or a diff alone for a workflow file.

Auto-promote trigger — which API fires the `push` event:
- **Contents API** (`create_or_update_file`, `PUT /repos/.../contents/...`) fires `push` → auto-promote runs → main fast-forwards. This is the reliable path for a single-file data write.
- **Git Data API** (`push_files`, and any manual blobs → tree → commit → ref-update sequence) does **not** fire `push`, so a batch committed this way sits on staging unpromoted.
- A real `git push` from a local clone fires it normally.
- So: after any Git Data batch, follow up with a single-file Contents write to trigger promotion — ideally a genuine change rather than a synthetic nudge. Or use sequential `create_or_update_file` calls instead of a batch for data writes.

Dan's local clone (`~/github/hm/live-shows`):
- Before advising any local git operation, check `git rev-list --left-right --count staging...origin/staging` and `git status --porcelain`.
- A local branch that is "ahead" only by a **superseded** commit — e.g. a local squash of a PR that also landed upstream as a different commit — should be `git reset --hard origin/staging`, **not** rebased and **not** pulled. The merge base predates both landings, so both sides look like they independently *added* the same tree, and a merge produces add/add conflicts across every added file. `git cherry` will report the local commit as new (`+`) even when its content is entirely upstream, because the patch-ids differ; verify with a reverse diff (`git diff origin/staging staging`) before concluding anything is at risk.
- git's own hint in `git status` ("use git pull to merge the remote branch into yours") is generic and is the wrong advice in that situation.

Active constraints to keep in mind:
- Potential rows matched by Artist+Date in handleDecisionChange, handleRevoke, and saveEdit — never by array index (stale-index fix, commit 5cf7506)
- RECOMMEND_PAT is split across two concatenated string literals in recommend.js to pass push protection — do not reunify into a single string in any commit
- Tab labels in UI: Current, History, Potential, Waiting — TSV/JS variable names are unchanged
