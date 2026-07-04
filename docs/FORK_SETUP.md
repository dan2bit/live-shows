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

## GitHub Pages & asset URLs

The site is built to run from **GitHub Pages**, and there is one Pages-specific wrinkle worth understanding before you change the brand assets (favicon, hat icon, hero image). Everything else is path-agnostic.

In `config.yaml`, the asset fields hold **repo-relative paths**:

```yaml
site:
  favicon: static/favicon.png
  brand_icon: static/brand-hat.png
  about_hero_image: static/hero.jpg
```

At load time `app.js` expands each of these into an absolute `https://<owner>.github.io/<repo>/<path>` URL, derived from your `site.owner` and `site.repo`. **This expansion is required, not cosmetic.** On a GitHub *project page* (served from `<user>.github.io/<repo>/`), a bare relative asset URL resolves against the current page path and 404s, so the absolute form is the only one that works here. Doing the expansion in code keeps `config.yaml` short and portable: change `owner`/`repo` and the asset URLs follow automatically.

**Custom domains and user/org pages behave differently.** If you serve from a custom domain, or from a user/organization page (site root, with no `/<repo>/` segment in the path), relative paths may resolve fine on their own and the github.io derivation will not point at your host. Two ways to handle it:

- Set `site.pages_base` to your site's base URL (e.g. `https://example.com`). `app.js` uses it verbatim as the base instead of deriving `<owner>.github.io/<repo>`.
- Or put fully-qualified absolute URLs (starting `https://`) directly in the asset fields. Any value that already begins with `http(s)://` is passed through untouched.

> Note: this only affects the three image asset fields. The site code files (`app.js`, `styles.css`, `recommend.js`) and `config.yaml` itself load as plain relative URLs and must stay that way.

---

## The `tools/` tree — operator-specific, safe to delete

Everything under `tools/` is the repo owner's personal research and workflow kit — artist
research pipelines, browser-scraping playbooks, personal reference data, and archived
point-in-time snapshots. **None of it is consumed by the site or by CI.** The only trees
the deployed site and the workflows read are `data/`, `scripts/`, the root site files
(`index.html`, `app.js`, `recommend.js`, `styles.css`, `config.yaml`), and `static/`.

For your fork, either delete `tools/` outright or add it to your fork's `.gitignore` and
build your own workflow kit in its place. Nothing on the site will change either way.

---

*Remaining setup sections — Pages, `config.yaml`, data files, private sidecar — to be written as the fork process is exercised.*
