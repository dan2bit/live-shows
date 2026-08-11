#!/usr/bin/env python3
"""
yt_setlist.py — Structured setlist.fm parsing for song identification

youtube_create_playlists.fetch_setlist_songs returns a flat list of song
labels, which is all playlist ordering needs. Song identification needs more:
positions, set structure, cover attributions, per-song notes, unknown-song
markers, and the page's own completeness warning. This module is that richer
parser. The flat one in youtube_create_playlists.py is deliberately left
untouched (issue #251).

WHAT A PARSE RETURNS

  Setlist
    .artist        whose set this page claims to be
    .url           where it came from
    .note          the page's own editor note ("Setlist incomplete and out of
                   order"), verbatim. setlist.fm's warning proved accurate,
                   not stale, on a real show — when present, positions are
                   ordering hints only and the caller must degrade.
    .songs         [SetlistSong] in page order

  SetlistSong
    .position      1-based across the whole set, encore included
    .title         the song label, or "" for an unknown-song marker
    .unknown       True for setlist.fm's "(Unknown)" placeholder rows
    .section       "" for the main set, else the set-marker text that
                   preceded this song ("Encore:", "Set 2:", "Acoustic:")
    .cover_of      originating artist for "(X cover)" notes, else ""
    .info          the full parenthetical note text, verbatim — section
                   headers and notes like "(+ sax solo)" or "(unreleased)"
                   are high-value verification anchors (issue #251)

MARKUP THIS IS PINNED TO (verified live 2026-08-11 against three pages)

  div.setlistList > ol.songsList
    li.setlistParts.song            one song
      div.songPart > a.songLabel        the title
      div.songPart > span.unknownSong   "(Unknown)" placeholder instead
      div.infoPart > small.fontSmall    "(Pete Seeger cover)", "(New song?)"
    li.setlistParts.encore.highlight    a set marker row ("Encore:")
    li.setlistParts.setlistFluidAd      an ad row — skipped
  p.info.fontSmall                  "Note: Setlist incomplete and out of order"

MULTI SHOWS

  A show row's Setlist.fm URL is either a direct link (headliner's set) or
  MULTI:YYYY-MM-DD, meaning every act's link lives in data/setlists/<year>.json
  under that date. resolve_setlist_urls() hides the difference: it always
  returns {artist name: url} for every act it can find.

FETCH BEHAVIOR

  Fetches are polite (same headers and delay as the playlist tool) and cached
  next to the manifest so a correction session re-runs offline and a parse
  bug can be fixed against the exact HTML that confused it. Pass
  refresh=True to refetch.
"""

import json
import os
import re
from dataclasses import dataclass, field

from yt_common import data_path


SETLIST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; dan2bit-playlist-tool/1.0)"
}
SETLIST_DELAY = 2.0  # seconds between fetches, same as the playlist tool

SETLISTS_JSON_GLOB = ("setlists", "{year}.json")

_COVER_RE = re.compile(r"\(([^()]+?)\s+cover\)", re.IGNORECASE)


# ── model ──────────────────────────────────────────────────────────────────

@dataclass
class SetlistSong:
    position: int
    title: str
    unknown: bool = False
    section: str = ""
    cover_of: str = ""
    info: str = ""


@dataclass
class Setlist:
    artist: str
    url: str
    note: str = ""
    songs: list = field(default_factory=list)

    @property
    def incomplete(self) -> bool:
        """True when the page itself warns the list is partial or disordered."""
        return bool(re.search(r"incomplete|out of order", self.note, re.IGNORECASE))

    @property
    def titled_songs(self) -> list:
        """Songs with a real title — unknown-song placeholders excluded."""
        return [s for s in self.songs if not s.unknown]


# ── resolution: show row → per-artist urls ─────────────────────────────────

def resolve_setlist_urls(show: dict) -> tuple[dict[str, str], str]:
    """Map every act of a show to its setlist URL.

    Returns ({artist: url}, status). A direct URL is attributed to the
    headliner. MULTI:date goes through data/setlists/<year>.json, which
    carries one entry per act. An empty mapping is legitimate — a show with
    no setlist data still identifies structurally.
    """
    raw = (show.get("setlist_url") or "").strip()
    if not raw:
        return {}, "no setlist URL on the show row"

    if not raw.upper().startswith("MULTI:"):
        return {show["artist"]: raw}, "direct URL (headliner)"

    date_key = raw.split(":", 1)[1].strip()
    year = date_key[:4]
    path = data_path(*[part.format(year=year) for part in SETLISTS_JSON_GLOB])

    try:
        with open(path, encoding="utf-8") as f:
            entries = json.load(f)
    except (OSError, ValueError) as error:
        return {}, f"MULTI but {os.path.basename(path)} unreadable: {error}"

    entry = entries.get(date_key)
    if not entry:
        return {}, f"MULTI but no {date_key} entry in {os.path.basename(path)}"

    urls = {}
    for item in entry.get("setlists", []):
        artist = (item.get("artist") or "").strip()
        url = (item.get("url") or "").strip()
        if artist and url:
            urls[artist] = url

    return urls, f"MULTI resolved ({len(urls)} setlists)"


# ── fetching, with cache ───────────────────────────────────────────────────

def fetch_html(url: str, cache_dir: str | None = None,
               refresh: bool = False) -> tuple[str, str]:
    """The page HTML, from cache when possible. Returns (html, status).

    An empty html with a status is a failed fetch. The caller decides what
    degrading looks like; this never raises.
    """
    cache_file = None
    if cache_dir:
        slug = re.sub(r"[^a-z0-9]+", "-", url.lower()).strip("-")[-80:]
        cache_file = os.path.join(cache_dir, f"setlist-{slug}.html")
        if not refresh and os.path.exists(cache_file):
            try:
                with open(cache_file, encoding="utf-8") as f:
                    return f.read(), "cached"
            except OSError:
                pass

    try:
        import time

        import requests
    except ImportError:
        return "", "requests not installed (pip install requests)"

    try:
        resp = requests.get(url, headers=SETLIST_HEADERS, timeout=15)
        time.sleep(SETLIST_DELAY)
    except Exception as error:                          # noqa: BLE001
        return "", f"fetch error: {error}"

    if resp.status_code != 200:
        return "", f"HTTP {resp.status_code}"

    if cache_file:
        try:
            os.makedirs(cache_dir, exist_ok=True)
            with open(cache_file, "w", encoding="utf-8") as f:
                f.write(resp.text)
        except OSError:
            pass

    return resp.text, "fetched"


# ── parsing ────────────────────────────────────────────────────────────────

def parse_setlist(html: str, artist: str, url: str) -> tuple[Setlist, str]:
    """Structured setlist from a page's HTML. Returns (Setlist, status).

    Song rows, set markers and ads all arrive as siblings in one ol.songsList;
    the section a song belongs to is whatever marker row most recently
    preceded it. A page with no parseable songs is returned empty with a
    status saying so, never raised.
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return Setlist(artist, url), "bs4 not installed (pip install beautifulsoup4)"

    soup = BeautifulSoup(html, "html.parser")
    result = Setlist(artist=artist, url=url)

    note = soup.find("p", class_="info")
    if note:
        result.note = re.sub(r"^Note:\s*", "",
                             note.get_text(" ", strip=True)).strip()

    container = soup.find(class_="setlistList")
    if not container:
        return result, "no setlist block on the page"

    section = ""
    position = 0
    for li in container.find_all("li", class_="setlistParts"):
        classes = li.get("class", [])

        if "setlistFluidAd" in classes:
            continue

        if "song" not in classes:
            # A set-marker row: "Encore:", "Set 2:", "Acoustic:" …
            text = li.get_text(" ", strip=True)
            if text:
                section = text
            continue

        label = li.find(class_="songLabel")
        unknown = li.find(class_="unknownSong")
        info_part = li.find(class_="infoPart")
        info = info_part.get_text(" ", strip=True) if info_part else ""

        position += 1
        song = SetlistSong(
            position=position,
            title=label.get_text(" ", strip=True) if label else "",
            unknown=unknown is not None and label is None,
            section=section,
            info=info,
        )

        match = _COVER_RE.search(info)
        if match:
            song.cover_of = match.group(1).strip()

        result.songs.append(song)

    if not result.songs:
        return result, "setlist block present but no songs parsed"

    unknowns = sum(1 for s in result.songs if s.unknown)
    status = f"ok ({len(result.songs)} songs"
    if unknowns:
        status += f", {unknowns} unknown"
    if result.incomplete:
        status += ", page warns incomplete"
    return result, status + ")"


def load_setlist(artist: str, url: str, cache_dir: str | None = None,
                 refresh: bool = False) -> tuple[Setlist, str]:
    """Fetch (or reuse cached) and parse one artist's setlist."""
    html, fetch_status = fetch_html(url, cache_dir=cache_dir, refresh=refresh)
    if not html:
        return Setlist(artist, url), fetch_status

    setlist, parse_status = parse_setlist(html, artist, url)
    return setlist, f"{fetch_status}; {parse_status}"
