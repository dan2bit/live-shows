#!/usr/bin/env python3
"""
yt_config.py — shared conventions loader + template engine for the YouTube toolset.

Reads youtube.yml (same directory) so emitters and parsers share one source of
truth for titles, descriptions, and sentinels. Every value has an in-code
default matching the channel's existing convention: an absent file, or an
absent key, changes nothing.

Template grammar (render):
    "[{slug} ]from [{vantage} at ]{venue_short} on {date}[ {handle}]"
  - {field} substitutes a value.
  - [ ... ] is an optional group: it renders only when every {field} inside it
    resolves to a non-empty value. Joining words and spacing live INSIDE the
    group, so they appear and disappear with the field.
  - [[ and ]] escape literal brackets. No nesting.

Title grammar (parse_title):
    {artist} LIVE - {song} (bootleg)[ trailing text]
  The marker "(bootleg)" is an anchor, not a terminus: anything after it is
  operator-owned trailing text — parsers ignore it, writers must preserve it.

The issue history behind these designs is logged in docs/ISSUE_LOG.md.
"""

import copy
import os
import re

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(_SCRIPT_DIR, "youtube.yml")

DEFAULTS = {
    "titles": {
        "video": "{artist} LIVE - {song} (bootleg)",
        "unknown_song": "Unknown Song #{n}",
        "playlist_show": "{headliner} LIVE @ {venue_short} {date}",
        "playlist_topical": "{artist} - {topic} (bootlegs)",
        "bootleg_marker": "(bootleg)",
    },
    "descriptions": {
        "video": "[{slug} ]from [{vantage} at ]{venue_short} on {date}[ {handle}][\n\n{note}]",
        "crowdsource_line": "- can you name this song? Leave a comment!",
        "playlist": "Select tracks from {setlist_url}",
        "date_format": "mm/dd/yy",
    },
    "sentinels": {
        "song_placeholder": "#song-title",
        "unknown": ["unknown", "unknown song", "?"],
    },
    "mcp": {
        "apply_cap_default": 10,
        "changeset_dir": ".changesets",
        "changeset_expiry_hours": 24,
    },
}


def _naive_yaml(text: str) -> dict:
    """Two-level section/key parser for this file's flat shape.

    Used only when pyyaml is absent, so the toolset stays runnable with zero
    extra dependencies. Handles: sections, scalar keys, quoted strings,
    integers, and single-line ["a", "b"] lists. Comments and blanks skipped.
    """
    out: dict = {}
    section = None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip() if not raw.lstrip().startswith("#") else ""
        if not line.strip():
            continue
        if not raw.startswith(" ") and line.endswith(":"):
            section = line[:-1].strip()
            out[section] = {}
            continue
        if section is None or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if value.startswith("[") and value.endswith("]"):
            items = [v.strip().strip("\"'") for v in value[1:-1].split(",") if v.strip()]
            out[section][key] = items
        elif len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            out[section][key] = value[1:-1]
        else:
            try:
                out[section][key] = int(value)
            except ValueError:
                out[section][key] = value
    return out


def load_config(path: str = CONFIG_PATH) -> dict:
    """DEFAULTS deep-merged under whatever youtube.yml provides."""
    cfg = copy.deepcopy(DEFAULTS)
    if not os.path.exists(path):
        return cfg
    with open(path, encoding="utf-8") as f:
        text = f.read()
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(text) or {}
    except ImportError:
        data = _naive_yaml(text)
    for section, keys in (data or {}).items():
        if isinstance(keys, dict) and section in cfg:
            cfg[section].update(keys)
    return cfg


_GROUP_RE = re.compile(r"\[([^\[\]]*)\]")
_FIELD_RE = re.compile(r"\{(\w+)\}")


def render(template: str, fields: dict) -> str:
    """Render a template with optional [bracket groups].

    A group is dropped whole when any {field} inside it is empty or missing;
    otherwise its literal text stays and its fields substitute. Ungrouped
    fields substitute directly (empty -> empty string). Literal brackets
    escape as [[ and ]]. The template's own \\n sequences become newlines.
    """
    text = template.replace("\\n", "\n")
    text = text.replace("[[", "\x00").replace("]]", "\x01")

    def _group(match):
        inner = match.group(1)
        names = _FIELD_RE.findall(inner)
        if any(not str(fields.get(n, "") or "").strip() for n in names):
            return ""
        return _FIELD_RE.sub(lambda m: str(fields.get(m.group(1), "")), inner)

    text = _GROUP_RE.sub(_group, text)
    text = _FIELD_RE.sub(lambda m: str(fields.get(m.group(1), "") or ""), text)
    return text.replace("\x00", "[").replace("\x01", "]")


def parse_title(title: str, cfg: dict = None) -> dict:
    """Split a channel video title into its conventional parts.

    Returns {"artist", "song", "trailer", "is_bootleg"}. Non-conforming titles
    (channel history predating the convention) return is_bootleg=False with
    artist/song empty — callers treat those as unparseable rather than guess.
    Legacy "(bootleg - qualifier)" marker variants parse (the qualifier lands
    in "marker_qualifier") so audits can propose tidying them.
    """
    cfg = cfg or load_config()
    marker = cfg["titles"]["bootleg_marker"]
    stem = marker[:-1] if marker.endswith(")") else marker
    result = {"artist": "", "song": "", "trailer": "", "marker_qualifier": "",
              "is_bootleg": False}
    idx = title.find(stem)
    if idx < 0:
        return result
    close = title.find(")", idx)
    if close < 0:
        return result
    result["is_bootleg"] = True
    result["marker_qualifier"] = title[idx + len(stem):close].lstrip(" -").strip()
    result["trailer"] = title[close + 1:].strip()
    head = title[:idx].rstrip()
    sep = head.find(" LIVE - ")
    if sep >= 0:
        result["artist"] = head[:sep].strip()
        result["song"] = head[sep + len(" LIVE - "):].strip()
    return result


def norm_name(name: str) -> str:
    """Loose identity form for artist/venue comparison: de-accented,
    casefolded, punctuation collapsed. Matching only — never displayed."""
    import unicodedata
    s = unicodedata.normalize("NFKD", name or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^\w\s]", " ", s.casefold())
    return re.sub(r"\s+", " ", s).strip()
