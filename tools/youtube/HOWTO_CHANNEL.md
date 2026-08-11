# HOWTO_CHANNEL.md — @dan2bit YouTube Channel Workflows

Covers the YouTube utility scripts, the playlist issue workflow, venv setup,
and credential configuration.

The per-show pipeline (phone clips → uploaded → identified → titled → public
→ playlist) is `youtube_upload_show.py`; its step-by-step operator guide is
**OPERATOR_FLOW.md**, next to this file. This document is the reference for
credentials, environment, the surrounding utility scripts, and conventions.

---

## Python Environment Setup

The YouTube scripts require a virtual environment with several packages.
All commands run from the repo root (`~/path/to/live-shows`).

### Does the venv need to be created or recreated?

```bash
cd ~/path/to/live-shows
source .venv/bin/activate
python -c "import dotenv; from googleapiclient.discovery import build; import bs4"
```

If that runs without error, the venv is healthy. If you see `ModuleNotFoundError`
or `No such file or directory`, create it fresh:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install \
  google-api-python-client \
  google-auth-oauthlib \
  python-dotenv \
  requests \
  beautifulsoup4
```

No `requirements.txt` is committed — the five packages above are the full list.

### Activating the venv

Always activate before running any script:

```bash
source .venv/bin/activate   # prompt changes to (.venv)
```

Deactivate when done:

```bash
deactivate
```

---

## Credential Configuration

### Account split (read first — it spans TWO Google accounts)

Two different accounts are involved, and mixing them up is the usual cause of an
auth flow that succeeds but can't see the channel:

- **The Google Cloud project** — the OAuth client (`client_secrets.json`), the
  OAuth consent screen, and the `YOUTUBE_API_KEY` — is administered under the
  **`redhat.bootlegs@gmail.com` (rhbl)** account. All Cloud Console work
  (creating/editing the client, the API key, adding scopes) is done signed in as
  **rhbl**.
- **The @dan2bit channel** is a **brand account under `dan2bit@gmail.com`**, and
  the **@dan2bit brand channel** is the identity you select in the OAuth
  **consent flow** — it owns the videos and playlists.

Net: **administer the client as rhbl; authorize/consent as the dan2bit brand
channel.**

### 1. Copy env.example to .env

```bash
cp env.example .env
```

Then fill in `.env` with your values. It is gitignored and must never be committed.

### 2. YouTube API key (read-only, for youtube_fetch.py)

Signed in to Google Cloud Console as **`redhat.bootlegs@gmail.com` (rhbl)** — the
account that owns the Cloud project:

1. Go to [Google Cloud Console](https://console.cloud.google.com) → APIs & Services → Credentials
2. Create an API Key
3. Paste it into `.env` as `YOUTUBE_API_KEY=...`

### 3. OAuth credentials (required for write operations)

All playlist creation and description updates are write operations requiring OAuth.
Create the client under the **rhbl** Cloud project (same account as the API key):

1. Google Cloud Console (signed in as **rhbl**) → APIs & Services → Credentials → Create OAuth 2.0 Client ID
2. Application type: Desktop App
3. Download the JSON file and save it as `client_secrets.json` in the repo root
4. Set `.env`: `YOUTUBE_CLIENT_SECRETS=client_secrets.json`

### 4. First-time OAuth token

Run once to open the browser consent flow and cache `token.json`:

```bash
source .venv/bin/activate
cd tools/youtube
python3 youtube_upload_show.py --auth-only
```

(`youtube_create_playlists.py --auth-only` still works and mints the same
token; the upload script's version also prints WHICH channel the token sees,
which catches the wrong-identity mistake immediately.)

A browser window opens. This is the **consent** step, so it uses the **channel**
identity, not the Cloud-project account: sign in with `dan2bit@gmail.com`, and when
prompted to choose an identity, select the **@dan2bit brand channel** — not the
gmail account itself, and not `redhat.bootlegs`. The brand channel is what owns the
videos and playlists. `token.json` is written to the repo root (gitignored). Future
runs refresh it automatically.

(The Cloud *project* is administered under rhbl — see the Account split above — but
the token is *authorized* as the dan2bit brand channel here.)

### 5. Fixing invalid_grant errors

If a script fails with `google.auth.exceptions.RefreshError: invalid_grant`,
the cached token is stale. Delete it and re-authenticate:

```bash
rm token.json
python3 youtube_upload_show.py --auth-only
```

In the browser consent flow: choose the **@dan2bit brand channel** identity (under
`dan2bit@gmail.com`), not the gmail account itself. A fresh `token.json` will be
written and subsequent runs will work normally.

Common causes: venv was recreated, token expired after extended inactivity,
or the wrong identity was selected during a previous auth flow.

---

## YouTube Scripts

### youtube_upload_show.py — the post-show pipeline

**The primary post-show script.** Four stages against one durable per-show
manifest — see OPERATOR_FLOW.md for the full walkthrough:

```bash
cd tools/youtube
python3 youtube_upload_show.py --clips ~/Downloads/showfolder --scan
python3 youtube_upload_show.py --upload --dry-run
python3 youtube_upload_show.py --upload         # clips land PRIVATE
# (Studio pass: monetization + Submit Rating — manual, see below)
python3 youtube_upload_show.py --identify       # after Content ID settles
# (correct Song in the lean manifest by lyric/ear)
python3 youtube_upload_show.py --apply --dry-run
python3 youtube_upload_show.py --apply          # titles/descriptions, still private
python3 youtube_upload_show.py --apply --publish
```

`--publish` hard-refuses the whole show if any title still contains the
`#song-title` placeholder or the legacy `???` notation. A genuinely
unidentifiable track (instrumental, non-English, rough audio) is marked by
typing `unknown` in its Song column: it publishes as “Unknown Song #N” with
a crowdsourcing ask in the description, and does not hold the night hostage.

**What stays manual, permanently: monetization and Submit Rating.** The
API's monetization field is read-only and self-certification is a Studio
questionnaire with no API surface or scope. Every show includes one Studio
visit for those two clicks per video, no matter how much else is automated.

### youtube_create_playlists.py

Creates playlists on the @dan2bit channel from `youtube_videos.tsv`, orders
videos using setlist.fm, and optionally writes the playlist URL back to
`live_shows_current.tsv` or `history/*.tsv`.

**Playlist assembly after the upload pipeline:**

```bash
# 1. Refresh the channel inventory (picks up the new uploads).
python3 youtube_fetch.py

# 2. Dry run to verify video matching and ordering.
python3 youtube_create_playlists.py --new-show 2026-05-09 --dry-run

# 3. Create playlist and write URL back to live_shows_current.tsv.
python3 youtube_create_playlists.py --new-show 2026-05-09 --update-history
```

Once videos carry exact setlist titles from `--apply`, this script's
setlist matching is near-exact.

**Backfill (multiple shows at once):**

```bash
# Dry run first.
python3 youtube_create_playlists.py --new-show since:2026-01-01 --update-history --dry-run

# Execute.
python3 youtube_create_playlists.py --new-show since:2026-01-01 --update-history
```

**Fix blank playlist descriptions (add setlist.fm link):**

```bash
# Always dry run first — this touches all channel playlists.
python3 youtube_create_playlists.py --fix-descriptions --dry-run

# Limit to specific dates to be safe.
python3 youtube_create_playlists.py --fix-descriptions --date 2026-03-29 2026-04-11
```

**Override headliner when lookup is ambiguous:**

```bash
python3 youtube_create_playlists.py --new-show 2026-03-20 --headliner "Danielle Nicole"
```

Log of all runs is written to `logs/playlist_creation_log.tsv` (gitignored).

---

### youtube_fetch.py

Fetches video metadata from the @dan2bit channel and writes to `youtube_videos.tsv`.
Uses the read-only API key (no OAuth required).

```bash
python3 youtube_fetch.py
```

Run this before `youtube_create_playlists.py --worklist` or `--date` to
ensure `youtube_videos.tsv` is current.

---

### youtube_fix_descriptions.py

Standalone version of the fix-descriptions logic. Prefer the
`--fix-descriptions` flag on `youtube_create_playlists.py` for current work;
this script is retained for reference.

---

### youtube_correlate.py

Correlates `youtube_videos.tsv` against the full show history to produce
`history_youtube_correlation.tsv`. Run ad hoc when auditing coverage.

```bash
python3 youtube_correlate.py
```

---

### youtube_audit_blanks.py

Audits `history_youtube_correlation.tsv` for shows with missing playlists.
Run ad hoc.

```bash
python3 youtube_audit_blanks.py
```

---

### youtube_fill_handles.py

Fills in YouTube channel handles in `artists.tsv`. Run ad hoc.

---

## Playlist Issue Workflow

New playlist creation is tracked via GitHub issues.

### Opening an issue (Routine 2, Step 6)

After processing post-show notes, Claude opens an issue if footage exists:

- **Title:** `Playlist: [Artist] — YYYY-MM-DD ([Venue short name])`
- **Label:** `playlist`
- **Body:** show details, notes, and the playlist creation steps

### Closing an issue

Before closing, add the playlist URL to the **issue body** — not a comment.
Comments are not readable via MCP; only the body is.

Format to add to the body before closing:

```
Playlist: https://www.youtube.com/playlist?list=PLxxxxxxxx
```

Then close the issue.

### Finding open playlist issues

```
is:issue is:open label:playlist
```

---

## Playlist Naming Convention

Matches the existing channel:

```
{Headliner} LIVE @ {Venue Short} ({City/State abbrev}) {M/D/YY}
```

Examples:
- `They Might Be Giants LIVE @ Lincoln Theatre (DC) 12/16/22`
- `Vanessa Collier LIVE @ Collective Encore (MD) 5/9/26`

Override per-show with `--title` if auto-generation is wrong.

---

## Playlist Description Convention

Default template (set by `--fix-descriptions`):

```
Select tracks from {setlist_url}
```

Custom template example:

```bash
python3 youtube_create_playlists.py --fix-descriptions \
  --description-template "Select tracks from my vantage point center-left: {setlist_url}"
```

---

## Notes

- The Google Cloud project (OAuth client, consent screen, API key) is under
  **`redhat.bootlegs@gmail.com` (rhbl)** — do all Cloud Console work signed in as rhbl
- In the browser auth flow, always select the **@dan2bit brand channel** identity
  (under `dan2bit@gmail.com`), not the gmail account itself — the brand channel owns
  the videos and playlists
- Upload happens script-side (`youtube_upload_show.py --upload`), so videos
  are API-addressable from the moment they exist. If you ever upload by hand
  in Studio instead: private videos are fine, but draft/unsubmitted videos
  will not appear to the API
- Monetization and Submit Rating are permanently manual in Studio — no API
  surface exists for either
- `youtube_videos.tsv`, `youtube_playlists.tsv`, `history_youtube_correlation.tsv`
  are all too large for MCP commits — always use GitHub Desktop for these
- `logs/` is gitignored; `playlist_creation_log.tsv` stays local
