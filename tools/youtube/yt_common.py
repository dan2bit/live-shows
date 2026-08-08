#!/usr/bin/env python3
"""
yt_common.py — Shared helpers for the @dan2bit YouTube tooling

Auth, repo-path anchoring, and TSV I/O for the show-upload toolchain. Imported
by youtube_upload_show.py, yt_clipscan.py, and yt_songid.py.

The older scripts in this directory (youtube_create_playlists.py,
youtube_fix_descriptions.py, youtube_fetch.py, youtube_fill_handles.py) each
carry their own copy of the auth helper and are deliberately NOT migrated here.
They keep working unchanged. Consolidating them is a separate, later change.

PATH ANCHORING:
  Every path is resolved against this file's location, never the working
  directory. The older scripts use bare cwd-relative names ("venues.tsv",
  "history/*.tsv") that match no single working directory; new code does not
  copy that pattern.

    SCRIPT_DIR  tools/youtube/
    REPO_ROOT   repo root
    DATA_DIR    repo root/data/

DEPENDENCIES:
  This module imports nothing outside the standard library at module scope.
  dotenv and the Google client stack are imported inside
  get_authenticated_service(). The local-only stages of the toolchain need the
  path and TSV helpers here but never authenticate, so they must keep working
  on a machine where the Google libraries are absent.

OAUTH:
  Scopes are youtube + youtube.upload. The upload scope is what authorizes
  videos.insert; a token minted before it was added cannot be refreshed into
  it, so widening scopes requires deleting token.json and re-consenting.

  Administer the Google Cloud project (client_secrets.json, consent screen,
  API key) as redhat.bootlegs. Consent as the @dan2bit brand channel — that
  is the identity that owns the videos and playlists. See HOWTO_CHANNEL.md.

REQUIRES:
  pip install google-api-python-client google-auth-oauthlib python-dotenv
"""

import csv
import os
import re
import sys
import unicodedata


# ── paths ──────────────────────────────────────────────────────────────────

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT  = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
DATA_DIR   = os.path.join(REPO_ROOT, "data")


def data_path(*parts: str) -> str:
    """Absolute path inside the repo's data/ directory."""
    return os.path.join(DATA_DIR, *parts)


def script_path(*parts: str) -> str:
    """Absolute path inside tools/youtube/."""
    return os.path.join(SCRIPT_DIR, *parts)


# ── auth ───────────────────────────────────────────────────────────────────

SCOPES = ["https://www.googleapis.com/auth/youtube",
          "https://www.googleapis.com/auth/youtube.upload"]

DEFAULT_CLIENT_SECRETS = "client_secrets.json"
DEFAULT_TOKEN_FILE     = "token.json"


def _load_env() -> None:
    """Read tools/youtube/.env into the environment. Deferred, see below."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        sys.exit("Missing dependency: pip install python-dotenv")
    load_dotenv(os.path.join(SCRIPT_DIR, ".env"))


def get_authenticated_service():
    """Return an authorized youtube/v3 service, minting or refreshing token.json.

    Mirrors the helper in youtube_create_playlists.py so behavior is identical
    across the toolchain: refresh when possible, discard a dead refresh token
    and re-consent, always write the credentials back to disk.

    Every third-party import this needs — dotenv and the Google client stack —
    is deliberately made HERE rather than at module scope. The local-only
    stages of the toolchain import this module for its path and TSV helpers
    but never authenticate, and they must keep running on a machine where the
    Google libraries were never installed. A module-level import would break
    a scan that touches nothing remote.
    """
    try:
        from google.auth.exceptions import RefreshError
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError:
        sys.exit("Missing dependency: pip install google-api-python-client "
                 "google-auth-oauthlib")

    _load_env()
    client_secrets = os.environ.get("YOUTUBE_CLIENT_SECRETS", DEFAULT_CLIENT_SECRETS)
    token_file     = os.environ.get("YOUTUBE_TOKEN_FILE", DEFAULT_TOKEN_FILE)

    client_secrets_path = script_path(client_secrets)
    token_path          = script_path(token_file)

    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError:
                # Dead refresh token (invalid_grant: revoked, or 7-day expiry on a
                # Testing-status OAuth app). Discard and fall through to fresh consent.
                print(f"Stored token in {token_file} can no longer be refreshed "
                      "(invalid_grant) — starting a fresh OAuth flow; a browser "
                      "window will open for consent. USE THE BRAND ACCOUNT "
                      "(@dan2bit), not the gmail account and not redhat.bootlegs.")
                creds = None

        if not creds:
            if not os.path.exists(client_secrets_path):
                sys.exit(
                    f"Missing OAuth client secrets: {client_secrets_path}\n"
                    "Download from Google Cloud Console (signed in as redhat.bootlegs) "
                    "→ Credentials → OAuth 2.0 Client IDs → Desktop App.\n"
                    "See tools/youtube/HOWTO_CHANNEL.md → Credential Configuration."
                )
            flow  = InstalledAppFlow.from_client_secrets_file(client_secrets_path, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(token_path, "w", encoding="utf-8") as f:
            f.write(creds.to_json())

    return build("youtube", "v3", credentials=creds)


# ── tsv i/o ────────────────────────────────────────────────────────────────

def read_tsv(path: str) -> list[dict]:
    """Read a tab-delimited file into a list of dicts. Missing file returns []."""
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def write_tsv(path: str, rows: list[dict], fieldnames: list[str] | None = None) -> None:
    """Write rows as a tab-delimited file, creating parent directories.

    No comment block is ever emitted. Several TSVs in this repo are edited
    in-page by deriving the header from the first line; a leading comment
    wipes every row on save.
    """
    if fieldnames is None:
        if not rows:
            raise ValueError(f"write_tsv({path}): no rows and no fieldnames")
        fieldnames = list(rows[0].keys())

    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t",
                                extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def append_log(path: str, fieldnames: list[str], rows: list[dict]) -> None:
    """Append rows to a log TSV, writing the header only if the file is new."""
    if not rows:
        return
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    write_header = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t",
                                extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerows(rows)


# ── formatting ─────────────────────────────────────────────────────────────

def dry(dry_run: bool) -> str:
    """Output prefix marking a simulated write."""
    return "[DRY RUN] " if dry_run else ""


def slugify(value: str) -> str:
    """Lowercase ASCII slug suitable for a filename component."""
    value = unicodedata.normalize("NFKD", value)
    value = value.encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^\w\s-]", "", value).strip().lower()
    return re.sub(r"[\s_-]+", "-", value) or "unknown"
