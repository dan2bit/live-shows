# SUPERSEDED by youtube_fill_handles.py
# Spotify search logic recovered and integrated; YouTube handle logic evolved
# into the two-phase --fetch / --write workflow.
# Kept here for reference only. Do not run.

#!/usr/bin/env python3
"""
Populates the YouTube Channel and Spotify URL columns in artists.tsv.

For each artist with a blank YouTube Channel or Spotify URL, the script:

  YouTube:
    1. Calls search.list (type=channel) to find candidate channels.
    2. For each candidate that passes the name-similarity check, calls
       channels.list to retrieve the channel's customUrl (@handle).
       Falls back to https://www.youtube.com/@<customUrl> or the channel URL
       if no handle is available.
    Writes nothing if no result passes the similarity check.

  Spotify:
    Calls the Spotify Web API search endpoint with type=artist.
    Uses the top result's external_urls.spotify value.
    Writes nothing if no result passes the similarity check.

Progress is saved to artists.tsv after every successful API write, so if the
script is interrupted (e.g. by a YouTube quota limit) results already found
are not lost. Re-running the script safely skips any row that already has a value.

Usage:
    python3 artists_youtube_spotify.py [--dry-run] [--only-youtube] [--only-spotify]
                                       [--artist NAME]

    --dry-run       Print proposed changes without writing to artists.tsv
    --only-youtube  Only run the YouTube pass
    --only-spotify  Only run the Spotify pass
    --artist NAME   Only process this artist (case-insensitive substring match)

Environment variables (from .env in the same directory):
    YOUTUBE_API_KEY          YouTube Data API v3 key (read-only)
    SPOTIFY_CLIENT_ID        Spotify app client ID
    SPOTIFY_CLIENT_SECRET    Spotify app client secret

Requires:
    pip install python-dotenv requests
"""

import argparse
import csv
import os
import re
import sys
import time
import unicodedata

import requests
from dotenv import load_dotenv

# ── Config ────────────────────────────────────────────────────────────────────

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
DOTENV_PATH  = os.path.join(SCRIPT_DIR, ".env")
ARTISTS_TSV  = os.path.join(SCRIPT_DIR, "artists.tsv")

YT_SEARCH_URL   = "https://www.googleapis.com/youtube/v3/search"
YT_CHANNEL_URL  = "https://www.googleapis.com/youtube/v3/channels"
SPOTIFY_TOKEN_URL  = "https://accounts.spotify.com/api/token"
SPOTIFY_SEARCH_URL = "https://api.spotify.com/v1/search"

# Seconds to wait between API calls
YT_DELAY      = 0.6   # search.list + channels.list = 2 calls per artist; be conservative
SPOTIFY_DELAY = 0.3

# Minimum Jaccard similarity to accept a result as a genuine match
MATCH_THRESHOLD = 0.55

# ── Name normalisation & similarity ──────────────────────────────────────────

def _norm(s: str) -> str:
    """Lowercase, strip accents, remove punctuation, drop leading 'the'."""
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.lower()
    s = re.sub(r"[^\w\s]", "", s)
    s = re.sub(r"^the\s+", "", s).strip()
    return s


def _tokens(s: str) -> set:
    """Return meaningful (>2 char) tokens, dropping noise words."""
    NOISE = {"and", "the", "feat", "with", "band", "live"}
    return {w for w in _norm(s).split() if len(w) > 2 and w not in NOISE}


def _similarity(a: str, b: str) -> float:
    """Jaccard similarity on token sets."""
    wa, wb = _tokens(a), _tokens(b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def is_match(query: str, result: str) -> bool:
    sim = _similarity(query, result)
    if sim >= MATCH_THRESHOLD:
        return True
    qn, rn = _norm(query), _norm(result)
    if len(qn) > 5 or len(_tokens(query)) >= 2:
        if qn in rn or rn in qn:
            return True
    return False

# (remainder of original file omitted for brevity — see git history)
