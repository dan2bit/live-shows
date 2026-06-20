# FORK_SETUP.md

> Setup guide for forking live-shows as a template.
> Work in progress — this currently covers credentials; the rest is filled in as the fork process is exercised.

## Credentials & tokens

live-shows uses two kinds of credentials, kept in two different places:

- **Tool credentials** (YouTube + Spotify) live in a gitignored `.env` next to the scripts — see [`env.example`](env.example). They never leave your machine.
- **GitHub tokens** are described below. **None of them belong in `.env`.** Store them in a password manager, and put each only where the thing that consumes it needs it — the browser, `app.js`, or your automation/MCP config.

All GitHub tokens are **fine-grained PATs**: <https://github.com/settings/personal-access-tokens/new>

### 1. Site-editing token — required for in-browser edits

Lets you edit Decisions and notes from the site's auth modal (the 🔑 button in `index.html`).

- **Repository:** your public repo (and your private sidecar, if you enabled private data)
- **Permissions:** Contents → Read and write · Issues → Read and write
- **Where it lives:** your password manager. You paste it into the auth modal when editing; it is never written to disk or committed.

### 2. Recommendations token — optional, only if you enable the recommendations feature

Lets visitors submit artist/show recommendations, which the site files as issues.

- **Repository:** your **public** repo only
- **Permissions:** Issues → Read and write (nothing else)
- **Where it lives:** embedded in `app.js`, split across two concatenated string literals.

**Important — this token is effectively public.** The split-literal trick only gets it past GitHub's commit-time secret scanner; it does **not** hide the token from anyone reading the deployed `app.js` or your repo source. Treat it as readable by the world. That is acceptable *only* because its scope is Issues-on-a-public-repo (worst case: someone opens spam issues). Never put a broader-scoped token here.

### 3. Automation / agentic token — optional, for the agentic playbooks / MCP

Used by the MCP server and the automation playbooks to read and write the repo on your behalf.

- **Repository:** your public repo (and private sidecar, if used)
- **Permissions:** Contents → Read and write · Issues → Read and write · Pull requests → Read and write · Workflows → Read and write
- **Where it lives:** your password manager (canonical copy), and wherever your automation/MCP reads it (e.g. the MCP connector config). Not in `.env`, not committed.

---

*Remaining setup sections — Pages, `config.yaml`, data files, private sidecar — to be written as the fork process is exercised.*
