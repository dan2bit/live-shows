# FORK_SETUP.md

> Setup guide for running your own copy of live-shows. It's organized in three
> levels; **each level is a complete, working stopping point**. Most forks only
> need Level 0. The issue history behind these designs is logged in
> [`ISSUE_LOG.md`](ISSUE_LOG.md).

- **Level 0 — UI-only fork.** A public tracker site you edit in the browser or on
  GitHub.com. No private data, no automation.
- **Level 1 — private data sidecar.** Adds a second, private repo for costs,
  seats, and private notes, merged into the site only when you authenticate.
- **Level 2 — automation + CI pipeline.** The staging branch, private-data guard,
  auto-promotion, and an agentic/MCP token — the full operating setup.

The [Spotify section](#spotify-optional-any-level) at the end is optional at any
level. Operational reference for a running Level 2 setup:
[`AGENTIC_WORKFLOWS.md`](AGENTIC_WORKFLOWS.md) (this file tells you how to build
the pipeline; that one tells you how to work inside it).

---

## Level 0 — UI-only fork

### 0. Level 0 in five commands

The fastest path — fork on GitHub, then:

```bash
git clone https://github.com/<you>/<repo>.git && cd <repo>
python3 scripts/fork_reset.py --dry-run     # review the plan
python3 scripts/fork_reset.py --patch-meta  # reset data; bootstrap the <head>
git commit -am "fork reset" && git push
# then: Settings -> Pages -> Deploy from a branch -> main / root
```

`fork_reset.py` replaces every data file with its exemplar from
`sample-files/` (canonical header + one synthetic row you delete via the
in-page editor), empties the derived JSON caches to valid structures, clears
`data/history/` + `data/setlists/` and sets `history_years: []`, and — with
`--patch-meta` — applies your `config.yaml` values to the hand-maintained
static `<head>` once. It refuses to run against the original repo and prints
the full manual-steps checklist (secrets, tokens, image guidance) when done.
**Acceptance test:** your Pages URL renders an empty, correctly-branded
tracker with no console errors. Sections 1–5 below are the same ground in
detail; Level 1's private seeds come from the same tool
(`--private-dir <path-to-your-private-clone>`).

### 1. Fork and serve

1. Fork the repo on GitHub.
2. Settings → Pages → **Deploy from a branch** → branch `main`, folder `/ (root)`.
3. Your site appears at `https://<you>.github.io/<repo>/` within a minute or two.

### 2. Point `config.yaml` at yourself

`config.yaml` is the personalization layer — the site code never needs editing
for a rename. At minimum change:

```yaml
site:
  title: my-shows
  owner: <your-github-username>
  repo: <your-repo-name>
  about_handle: "About @you"
  about_tagline: ...
  about_text: ...
  region: <your metro>        # appears in visitor-facing copy
history_years: []             # unless you import past-year archives (see below)
```

Every block is annotated in-file with what it does and what removing it does.
The `owner`/`repo` keys matter beyond display: asset URLs and all in-browser
editing derive from them.

**The static `<head>` is a hand-edit.** Social unfurlers don't run JavaScript, so
the `<title>`, OpenGraph, and Twitter tags in `index.html` must be edited
directly — every such tag is flagged with a `<!-- config: -->` marker, and the
`meta:` block at the bottom of `config.yaml` is the checklist of them. Editing
that block alone does nothing.

### 3. Data files

Everything the site shows lives in TSVs under `data/`:

| File | What it holds |
|---|---|
| `live_shows_current.tsv` | This year's shows, upcoming + attended (19 columns; `-` sentinels for empty link cells) |
| `live_shows_potential.tsv` | Shows you're considering — `Buy` / `Choose` / `Pass` (+ `Sell` listings) |
| `fast_track.tsv` | Artists you'd buy instantly if they toured near you (the Waiting tab) |
| `artists.tsv` | Per-artist ledger: times seen, first/last seen, YouTube/Spotify links |
| `history/<year>.tsv` | Past-year archives (list the years in config `history_years`) |
| `venues.tsv` + `venue_aliases.tsv` | Venue facts + name-variant resolution |
| `recommend_aliases.tsv` | Artist name variants → canonical names (drives several joins) |
| `show_goals/` | Optional achievement logs (signatures, photos) — delete along with config `show_goals` for a badge-free site |

`fork_reset.py` (above) empties these for you from `sample-files/` — each
sample is the live header plus one synthetic row, and CI guards the sample
headers against schema drift. If you'd rather do it by hand, start by emptying
the personal rows and adding your own. Two format rules
matter: keep header rows intact (the in-page editor derives columns from line 1 —
never add `#` comment lines to `current`/`potential`/`fast_track`), and use plain
ASCII punctuation in data values (curly quotes and long dashes silently break
name joins).

The derived JSON files under `data/` (`artist_modal_index.json`,
`recommend_index.json`, `artist_spotify.json`) are build products — at Level 0
you can leave the stale ones in place (artist modals will show Dan's data until
regenerated) or delete them (modals degrade gracefully). Level 2's CI rebuilds
the first two automatically; the Spotify cache is optional back-office tooling.

Two more TSVs under `data/` are **optional sidecars**, and they work differently
from everything in the table above: they are not in `sample-files/`, so
`fork_reset.py` neither seeds nor clears them, and the site treats a missing,
empty, or header-only file as "no data" — the fetch fails soft, nothing 404s
visibly, and the UI renders exactly as it would without the feature. Your fork
gains each one the day it has a row to put in it.

| File | How it appears | What it does |
|---|---|---|
| `artist_favorites.tsv` | Written by the site — click the brand-hat gauge in an artist modal while authed (needs config `features.favorite`) | Pins that artist's gauge to full with a star. Columns: `Artist`, `Since`. Public by design: the star and pinned gauge are visible to every viewer; only the promote/remove control is authed |
| `artist_status.tsv` | Hand-curated — create it yourself | Renders one muted line under the artist name in the modal for an act that is no longer active |

`artist_status.tsv` columns are `Artist`, `Status`, `Years`, `Status Date`,
`Note`, `Source`. `Status` is one of `deceased`, `defunct`, or `retired`, and the
file is **sparse on purpose: absence means active** — never write an `active`
row, so every row in the file means something. The line renders as `d. 2026`,
`disbanded 2025`, or `retired 2021`; the year comes from `Status Date`, falling
back to the closing year of `Years`. `Note` becomes the line's tooltip, and
`Source` is your own provenance note. The ASCII-punctuation rule applies to the
values like any other data file — write `1970-2026` with a plain hyphen, and let
the renderer do the typography.

### 4. The site-editing token (in-browser edits)

A fine-grained PAT (<https://github.com/settings/personal-access-tokens/new>):

- **Repository:** your public repo
- **Permissions:** Contents → Read and write · Issues → Read and write
- **Where it lives:** your password manager; paste it into the site's 🔑 auth
  modal. It is stored in your browser's localStorage only.

Authenticated, the site edits data in-page: decision dropdowns and notes on
potentials, the config editor (gear), show-row notes, and — if enabled — the
purchase flow and favorites. Everything else (adding shows, new columns,
history files) is a normal git/GitHub edit. Without a staging pipeline
(Level 2), in-page writes go straight to `main`: leave `site.data_branch` unset.

### 5. Optional trims

- `features:` in config — turn off any subsystem (`for_sale`, `recommendations`,
  `fast_track`, `spotify_integration`, `favorite`, `in_page_purchase`…).
  `private_data: false` (or just never authenticating) means a fully public
  site; financial fields simply don't exist anywhere in the public schema.
- The **recommendations feature** needs its own throwaway token — see
  [Tokens](#the-three-tokens-summary) below for why it's world-readable by design.
- The `tools/` tree is the original owner's personal research kit — **nothing
  on the site or in CI reads it** (the only consumed trees are `data/`,
  `scripts/`, the root site files, and `static/`). Delete it, or keep whatever
  amuses you (`tools/research/graph/` is a self-contained artist-network page).

**You know Level 0 works when:** your Pages URL renders your shows, the About
modal shows your text and links, and an authed decision change on a potentials
row commits to `main` under your name.

---

## Level 1 — private data sidecar

The public schema deliberately carries no money. Costs, seat details, ticket
quantities, and private notes live in a **separate private repo**, merged into
the page at runtime only when you're authed.

### 1. Create the sidecar

Create `<you>/<repo>-private` (private). Seed three files at its **root**:

```
current_private.tsv    →  Show Date	Artist	Seat Info / GA	Ticket Quantity	Face Value (per ticket)	Fees	Total Cost	Purchase Date	Food & Bev	Parking	Merch	Private Notes
potential_private.tsv  →  Artist	Date	Private Notes
fast_track_caps.tsv    →  Artist	Price Cap	Distance Cap	Venue Cap
```

(Header rows only, to start.)

### 2. Wire it up

- Expand the **site-editing PAT** to cover both repos (same token, add the
  private repo; same two permissions).
- In config:

```yaml
features:
  private_data: true
site:
  private_owner: <you>
  private_repo: <repo>-private
```

### 3. How the merge works

`mergePrivateData()` joins sidecar rows onto the loaded public rows at render
time — nothing private is ever written to the public repo. Join keys:
`Show Date + Artist` (current), `Artist + Date` (potentials). **Copy the key
fields verbatim from the public row** when adding sidecar rows; name or date
drift orphans the row (the site console-warns about orphans on authed loads).

Public vs private, per show: the public row keeps denormalized flags (`Seat
Type`, `VIP`, `Group`) and show metadata; the sidecar holds everything with a
dollar sign plus `Private Notes`. A show's public and private halves are **two
separate commits to two separate repos**, never one.

**You know Level 1 works when:** an authed reload shows COST columns on attended
rows and your private notes on potentials — and an incognito window shows
neither.

---

## Level 2 — automation + CI pipeline

The full setup: bots and agents write freely to a `staging` branch, a
server-side guard proves each commit leaks nothing private, and only clean
commits fast-forward to `main` (and therefore to Pages).

### 1. Staging branch + required check

1. Create `staging` from `main`.
2. Settings → Branches → protect `main`: require the **`guard`** status check
   (from `private-data-guard.yml`), and allow no direct pushes.
3. Set `site.data_branch: staging` in config so in-page edits ride the pipeline
   too.

The guard blocks: any `live-shows-private/` path, any `*_private.tsv` or
`*_caps.tsv` file, and any TSV whose header contains `Private Notes` (a private
schema smuggled in under another name). It exists because exactly that leak
happened once — see `ISSUE_LOG.md`. Verify it's alive by pushing a scratch
branch with a file named `test_private.tsv` and watching the check fail.

### 2. Auto-promotion + deploy key

`auto-promote.yml` re-runs the guard on every staging push and fast-forwards
`main` when clean. It pushes via a deploy key (the sole branch-protection
bypass):

```
ssh-keygen -t ed25519 -f promote_key -N ""
```

- Public key → repo Settings → Deploy keys (write access).
- Private key → Actions secret **`PROMOTE_DEPLOY_KEY`**.

Two behaviors worth knowing before you rely on it: a guard-failing commit is
**reset off staging** (the reset also fires if `main` diverges — merge PRs
based on `main` only when staging is quiet, and re-sync staging afterward), and
bot pushes retry with rebase to survive races.

### 3. The automation/MCP token

A third fine-grained PAT for whatever drives your automation (MCP server,
scripts): both repos, Contents + Issues + Pull requests read/write — and
**Workflows read/write if you want it to edit workflow files** (without that
scope, workflow edits 404 and must go through another path).

### 4. Working rules that keep the pipeline honest

The operational versions live in the playbooks; the ones a new setup trips over:

- Data commits target `staging`; the private sidecar's `main` has no pipeline —
  commit to it directly.
- Batch multi-file changes into one commit (a multi-file Git Data push may not
  fire the staging trigger — follow with a single-file nudge commit).
- PRs based on `staging` don't auto-close their linked issues (the closes
  keyword only fires on default-branch merges) — close manually.
- PR previews: `site.preview_data_branch` in config, or `?dataref=<branch>` on
  the URL, points the site's reads at a branch; writes stay on `data_branch`.

**You know Level 2 works when:** a TSV commit to `staging` appears on `main` by
itself within a minute, and the scratch `test_private.tsv` push gets rejected.

---

## The three tokens (summary)

| Token | Repos | Permissions | Lives in |
|---|---|---|---|
| Site-editing | public (+ private at Level 1) | Contents, Issues RW | Password manager → 🔑 modal |
| Recommendations (optional) | public only | Issues RW **only** | Split across two string literals in `app.js` |
| Automation/MCP (Level 2) | both | Contents, Issues, PRs (+ Workflows) RW | Your MCP/automation config |

**The recommendations token is effectively public.** The split-literal trick
only defeats GitHub's commit-time secret scanner; anyone reading the deployed
`app.js` can reassemble it. That's acceptable *only* because its blast radius is
opening issues on a public repo. Never widen its scope.

Tool credentials (YouTube/Spotify/Last.fm) are separate and live in gitignored
`.env` files — see [`env.example`](env.example).

---

## GitHub Pages & asset URLs

In `config.yaml`, the brand asset fields hold **repo-relative paths**:

```yaml
site:
  favicon: static/favicon.png
  brand_icon: static/brand-hat.png
  about_hero_image: static/hero.jpg
```

At load time `app.js` expands each into an absolute
`https://<owner>.github.io/<repo>/<path>` URL. **This expansion is required, not
cosmetic** — on a GitHub *project page* a bare relative asset URL resolves
against the current page path and 404s.

**Custom domains and user/org pages behave differently.** If relative paths
already resolve at your host, either set `site.pages_base` to your base URL
(used verbatim instead of the github.io derivation) or put full `https://` URLs
directly in the asset fields (passed through untouched). This affects only the
three image fields; the site code files and `config.yaml` itself load as plain
relative URLs and must stay that way.

---

## Spotify (optional, any level)

Back-office tooling, not a site dependency: `features.spotify_integration` only
gates Spotify links on the Waiting tab — set it `false` (or omit the whole
subsystem) and nothing else changes.

Two components with a **two-tier trust posture**:

- **Read side** — `scripts/spotify_cache.py` builds `data/artist_spotify.json`
  under **client credentials** (no account access). Credentials in
  `scripts/.env` (`SPOTIFY_CLIENT_ID/SECRET`), plus **`LASTFM_API_KEY`** — the
  enrichment layer's only credential (tags, listeners, similar-artists).
- **Write side** — the marcelmarais `spotify-mcp-server` holds a **user-OAuth
  token that can modify your account**. Treat its `spotify-config.json` like a
  GitHub PAT: it lives in the cloned server's directory, never in this repo.

Write-MCP setup, with the traps pre-sprung:

1. Create a Spotify app (developer dashboard). In its settings the Redirect URI
   **must be exactly `http://127.0.0.1:8888/callback`** — loopback IP, `http`,
   port, path. Spotify rejects `https://localhost` forms; a mismatch surfaces as
   `redirect_uri: Not matching configuration` at auth time.
2. **Dev-Mode User Management:** a development-mode app only serves accounts
   listed under dashboard → User Management. Add the authorizing account (name +
   email) or every playlist write 403s.
3. Clone/build/auth: `git clone … && npm install && npm run build`, fill
   `spotify-config.json` (client id/secret + the redirect URI), `npm run auth`
   (one-time browser consent; tokens self-refresh).
4. **SDK endpoint patch:** the server's pinned `@spotify/web-api-ts-sdk` still
   calls retired playlist endpoints (`POST /users/{id}/playlists` →
   `/me/playlists`; `/playlists/{id}/tracks` → `/playlists/{id}/items` for item
   ops), which surfaces as a misleading `403 "Bad OAuth request"` on
   `createPlaylist`. Patch both `dist/mjs` and `dist/cjs` copies of
   `PlaylistsEndpoints.js` (leave `getUsersPlaylists` alone) and add a
   `postinstall` hook to reapply — any `npm install` wipes the patch. This is a
   local workaround for an upstream bug, needed until it's fixed there.
5. Dev-mode quotas are real: search caps at ~10 results (eyeball same-name
   artists), and the cache's release sweeps drip at ~100 calls/day
   (`--count-pending` before spending; bare runs self-resume).

Workflow recipes (sampler / bill top-tracks / playlist→research) live in
`tools/playbooks/SPOTIFY_WORKFLOWS.md`.
