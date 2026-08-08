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


# ── venue and artist identity ──────────────────────────────────────────────
#
# Resolves the surface forms the channel's descriptions use. This is the same
# alias -> canonical -> short-name chain that youtube_create_playlists.py runs
# for playlist titles; it is reimplemented here rather than imported because
# that module does its lookups at import time against cwd-relative paths.
# Consolidating the two into one shared chain is tracked separately.

VENUES_TSV        = "venues.tsv"
VENUE_ALIASES_TSV = "venue_aliases.tsv"
ARTISTS_TSV       = "artists.tsv"

# venues.tsv has no state column; the two-letter code is parsed out of the
# free-text Address, which ends "..., CITY, ST ZIP".
_STATE_RE = re.compile(r",\s*([A-Z]{2})\s+\d{5}")

_IDENTITY_CACHE: dict = {}


def _venue_key(value: str) -> str:
    """Fold a venue name to a match key: no leading 'the', no punctuation."""
    key = re.sub(r"^the\s+", "", value.strip().lower())
    key = re.sub(r"[^a-z0-9 ]+", " ", key)
    return re.sub(r"\s+", " ", key).strip()


def _load_venue_identity() -> tuple[dict, dict, dict]:
    """Build (aliases, short names, states) keyed by folded venue name."""
    aliases: dict = {}
    short:   dict = {}
    state:   dict = {}

    for row in read_tsv(data_path(VENUE_ALIASES_TSV)):
        alias = (row.get("Alias") or "").strip()
        canon = (row.get("Venue Name") or "").strip()
        if alias and canon:
            aliases[_venue_key(alias)] = canon

    for row in read_tsv(data_path(VENUES_TSV)):
        name = (row.get("Venue Name") or "").strip()
        if not name:
            continue
        key = _venue_key(name)
        # Rows are ragged — trailing empty columns are truncated rather than
        # written, so DictReader yields None for the tail. Short Name is the
        # last column and the usual casualty, hence (x or "") throughout.
        short[key] = (row.get("Short Name") or "").strip() or name
        match = _STATE_RE.search(row.get("Address") or "")
        if match:
            state[key] = match.group(1)

    return aliases, short, state


def venue_short(venue_str: str) -> str:
    """'Wolf Trap (VA)' from whatever spelling a show row carries.

    Falls back to the full venue name where no short name is recorded (most
    venues have none), and omits the state where the address has no parseable
    one. Never raises on an unknown venue — an unrecognized name is returned
    as given, which is better than a blank in a description.
    """
    raw = (venue_str or "").split(",")[0].strip()
    if not raw:
        return ""

    if "venues" not in _IDENTITY_CACHE:
        _IDENTITY_CACHE["venues"] = _load_venue_identity()
    aliases, short, state = _IDENTITY_CACHE["venues"]

    key = _venue_key(raw)
    if key in aliases:
        key = _venue_key(aliases[key])

    name = short.get(key, raw)
    code = state.get(key, "")
    return f"{name} ({code})" if code else name


def artist_handle(artist: str) -> str:
    """The @handle for an artist, or "" when there is no usable one.

    The YouTube Channel column holds three things that are not handles: blank,
    the literal N/A, and a bare channel URL for artists with no custom handle.
    None of those belong in a description, so they resolve to nothing rather
    than to a broken mention.
    """
    if "artists" not in _IDENTITY_CACHE:
        index = {}
        for row in read_tsv(data_path(ARTISTS_TSV)):
            name = (row.get("Artist") or "").strip()
            if name:
                index[name.casefold()] = (row.get("YouTube Channel") or "").strip()
        _IDENTITY_CACHE["artists"] = index

    handle = _IDENTITY_CACHE["artists"].get((artist or "").strip().casefold(), "")
    return handle if handle.startswith("@") else ""


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
