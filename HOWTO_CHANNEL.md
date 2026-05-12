# HOWTO_CHANNEL.md — @dan2bit YouTube Channel Workflows

Covers the YouTube utility scripts, the playlist issue workflow, venv setup,
and credential configuration.

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

### 1. Copy env.example to .env

```bash
cp env.example .env
```

Then fill in `.env` with your values. It is gitignored and must never be committed.

### 2. YouTube API key (read-only, for youtube_fetch.py)

1. Go to [Google Cloud Console](https://console.cloud.google.com) → APIs & Services → Credentials
2. Create an API Key
3. Paste it into `.env` as `YOUTUBE_API_KEY=...`

### 3. OAuth credentials (required for write operations)

All playlist creation and description updates are write operations requiring OAuth.

1. Google Cloud Console → APIs & Services → Credentials → Create OAuth 2.0 Client ID
2. Application type: Desktop App
3. Download the JSON file and save it as `client_secrets.json` in the repo root
4. Set `.env`: `YOUTUBE_CLIENT_SECRETS=client_secrets.json`

### 4. First-time OAuth token

Run once to open the browser consent flow and cache `token.json`:

```bash
source .venv/bin/activate
python3 youtube_create_playlists.py --auth-only
```

A browser window opens. **Sign in as `dan2bit@gmail.com` — not `redhat.bootlegs`.**
When prompted to choose an identity, select the **@dan2bit brand channel**,
not the gmail account itself. The brand channel is what owns the videos and playlists.
`token.json` is written to the repo root (gitignored). Future runs refresh
it automatically.

### 5. Fixing invalid_grant errors

If a script fails with `google.auth.exceptions.RefreshError: invalid_grant`,
the cached token is stale. Delete it and re-authenticate:

```bash
rm token.json
python3 youtube_create_playlists.py --auth-only
```

In the browser flow: sign in as `dan2bit@gmail.com` (not `redhat.bootlegs`),
then select the **@dan2bit brand channel** identity, not the gmail account.
A fresh `token.json` will be written and subsequent runs will work normally.

Common causes: venv was recreated, token expired after extended inactivity,
or the wrong Google account was selected during a previous auth flow.

---

## YouTube Scripts

### youtube_create_playlists.py

**The primary script.** Creates playlists on the @dan2bit channel from
`youtube_videos.tsv`, orders videos using setlist.fm, and optionally writes
the playlist URL back to `live_shows_current.tsv` or `history/*.tsv`.

**Typical post-show workflow:**

```bash
# 1. Upload videos to YouTube Studio (private is fine).
#    Videos must be uploaded before running the script.

# 2. Dry run to verify video matching and ordering.
python3 youtube_create_playlists.py --new-show 2026-05-09 --dry-run

# 3. Create playlist and write URL back to live_shows_current.tsv.
python3 youtube_create_playlists.py --new-show 2026-05-09 --update-history
```

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

- OAuth account is `dan2bit@gmail.com` — not `redhat.bootlegs`
- In the browser auth flow, always select the **@dan2bit brand channel** identity,
  not the gmail account itself
- Videos must be uploaded to YouTube Studio before running any script —
  the script matches by upload date and video title
- Private videos are fine; draft/unsubmitted videos will not appear
- `youtube_videos.tsv`, `youtube_playlists.tsv`, `history_youtube_correlation.tsv`
  are all too large for MCP commits — always use GitHub Desktop for these
- `logs/` is gitignored; `playlist_creation_log.tsv` stays local
