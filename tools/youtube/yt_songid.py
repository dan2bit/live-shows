#!/usr/bin/env python3
"""
yt_songid.py — Seed song titles for uploaded bootleg clips (issue #251)

Fills the identification columns of a show's manifest: Song, Candidates,
Lyric Hint in the lean file; Confidence, Evidence, Setlist Pos in the machine
sidecar. Writes nothing to YouTube. Driven by
youtube_upload_show.py --identify.

THE LAYERED ARCHITECTURE, IN PRIORITY ORDER

  1. Content-ID claims     trustworthy fixed points, bound to clips by video
                           ID. Read from an optional <manifest>.claims.tsv —
                           written by hand today, by yt_claims.py when the
                           Studio claims reader lands (#251 comments; its
                           absence degrades to the layers below with zero
                           ceremony).
  2. Lyric identifications resolve a clip within its candidate pool. Read
                           from an optional <manifest>.lyrics.tsv recording
                           each lookup's TRI-STATE outcome:
                             matched  a distinctive lyric named this song
                             none     lookup succeeded, no released lyric
                                      exists — the unreleased signal
                             error    lookup failed — asserts NOTHING
                           A failed lookup that silently read as "unreleased"
                           would be a wrong answer wearing a confident face,
                           so only `none` may imply unreleased.
  3. Setlist bracketing    the candidate pool. Anchored positions constrain
                           each unconfirmed clip to the setlist songs between
                           its neighbouring anchors, minus every globally
                           confirmed song. Position is a WEAK PRIOR: sets get
                           filmed out of order, so bracketing proposes and
                           lists candidates — it only seeds a Song when a
                           pool collapses to exactly one candidate.
  4. Human ear             final resolver, in the lean manifest file.

THE LOAD-BEARING RULE

  Lyric and Content-ID evidence override the positional guess, never the
  reverse. A clip anchored by layer 1 or 2 keeps that answer even when its
  capture position argues otherwise.

EVIDENCE FILES

  <manifest>.claims.tsv    Video ID, Claimed Title, Claimed Artist, Match Start
  <manifest>.lyrics.tsv    Clip, Status, Song, Lyric Hint, Source

  Both optional; both keyed to the manifest. Claim rows bind by Video ID
  because that is what the Studio claims surface reports against. Lyric rows
  bind by clip filename because lyric work happens against local playback.

WHAT --reseed MEANS HERE

  Identification never overwrites a non-blank Song. A Song this module
  seeded is recognizable by its machine-owned Evidence value; a Song a
  person typed carries none. --reseed discards only the machine-seeded ones
  and re-derives them — a typed Song survives even --reseed.
"""

import os
import re
import unicodedata
from dataclasses import dataclass, field

from yt_common import read_tsv
from yt_setlist import Setlist, load_setlist, resolve_setlist_urls


CONFIDENCE_HIGH   = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW    = "low"

# Above this many candidates, a pool is reported as a count rather than
# spelled out. Set high enough that a typical club set lists in full — a
# truncated "+4 more" proved worse than useless once the visible names were
# assigned and only the hidden ones remained.
CANDIDATE_LIST_MAX = 12

EVIDENCE_HUMAN_MARKERS = ("", "human")


# ── evidence files ─────────────────────────────────────────────────────────

def claims_path(manifest_path: str) -> str:
    return manifest_path[:-4] + ".claims.tsv"


def lyrics_path(manifest_path: str) -> str:
    return manifest_path[:-4] + ".lyrics.tsv"


def read_claims(manifest_path: str) -> dict[str, dict]:
    """Content-ID claim rows keyed by video ID. Missing file returns {}."""
    claims = {}
    for row in read_tsv(claims_path(manifest_path)):
        video_id = (row.get("Video ID") or "").strip()
        title = (row.get("Claimed Title") or "").strip()
        if video_id and title:
            claims[video_id] = {
                "title":  title,
                "artist": (row.get("Claimed Artist") or "").strip(),
                "start":  (row.get("Match Start") or "").strip(),
            }
    return claims


def read_lyrics(manifest_path: str) -> dict[str, dict]:
    """Lyric lookup outcomes keyed by clip name. Missing file returns {}."""
    outcomes = {}
    for row in read_tsv(lyrics_path(manifest_path)):
        clip = (row.get("Clip") or "").strip()
        status = (row.get("Status") or "").strip().lower()
        if not clip:
            continue
        if status not in ("matched", "none", "error"):
            print(f"  WARNING: {os.path.basename(lyrics_path(manifest_path))}: "
                  f"clip {clip} has status '{status}' — expected matched/none/"
                  "error; treating as error (asserts nothing)")
            status = "error"
        outcomes[clip] = {
            "status": status,
            "song":   (row.get("Song") or "").strip(),
            "hint":   (row.get("Lyric Hint") or "").strip(),
            "source": (row.get("Source") or "").strip(),
        }
    return outcomes


# ── title normalization ────────────────────────────────────────────────────

def normalize_title(value: str) -> str:
    """Fold a song title to a match key: ASCII, lowercase, bare words."""
    value = unicodedata.normalize("NFKD", value)
    value = value.encode("ascii", "ignore").decode("ascii").lower()
    value = re.sub(r"[^a-z0-9 ]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def match_song(title: str, setlist: Setlist):
    """The setlist song a free-text title names, or None.

    Exact normalized match first; then containment either way, which absorbs
    the medley separators and parentheticals both sides add. First hit wins in
    setlist order.
    """
    wanted = normalize_title(title)
    if not wanted:
        return None

    for song in setlist.titled_songs:
        if normalize_title(song.title) == wanted:
            return song
    for song in setlist.titled_songs:
        have = normalize_title(song.title)
        if have and (have in wanted or wanted in have):
            return song
    return None


# ── the per-artist identification pass ─────────────────────────────────────

@dataclass
class ArtistReport:
    artist: str
    setlist_status: str = ""
    incomplete: bool = False
    confirmed: list = field(default_factory=list)   # (clip, song, evidence)
    seeded: list = field(default_factory=list)      # (clip, song, pool)
    open_pools: list = field(default_factory=list)  # (clip, candidates)
    unreleased: list = field(default_factory=list)  # clip names
    notes: list = field(default_factory=list)


def identify_rows(rows: list[dict], show: dict, setlists: dict[str, "Setlist"],
                  claims: dict[str, dict], lyrics: dict[str, dict],
                  reseed: bool = False) -> list[ArtistReport]:
    """Fill identification columns in place. Returns per-artist reports.

    Only rows with Decision=got participate. Rows are grouped by Set Artist,
    because each act has its own setlist and its own candidate pool.
    """
    if reseed:
        _discard_machine_seeds(rows)

    reports = []
    for artist in _artists_in_order(rows):
        group = [r for r in rows
                 if (r.get("Set Artist") or "").strip() == artist
                 and (r.get("Decision") or "").strip() == "got"]
        if not group:
            continue

        setlist = setlists.get(artist)
        report = ArtistReport(artist=artist)
        report.incomplete = bool(setlist and setlist.incomplete)
        if setlist is None:
            report.notes.append("no setlist — structural identification only")

        _apply_claims(group, setlist, claims, report)
        _apply_lyrics(group, setlist, lyrics, report)
        _honor_human_songs(group, setlist, report)
        _resolve_positions(group, setlist)

        if setlist and setlist.titled_songs:
            _bracket(group, setlist, report)

        _carry_slugs(group, setlist)
        reports.append(report)

    return reports


def _artists_in_order(rows: list[dict]) -> list[str]:
    """Distinct Set Artist values, in first-appearance (capture) order."""
    seen, order = set(), []
    for row in rows:
        artist = (row.get("Set Artist") or "").strip()
        if artist and artist not in seen:
            seen.add(artist)
            order.append(artist)
    return order


def _discard_machine_seeds(rows: list[dict]) -> None:
    """Blank every Song this module previously seeded. Typed Songs survive."""
    for row in rows:
        evidence = (row.get("Evidence") or "").strip()
        if evidence not in EVIDENCE_HUMAN_MARKERS:
            row["Song"] = ""
            row["Confidence"] = ""
            row["Evidence"] = ""
            row["Setlist Pos"] = ""


def _confirm(row: dict, song, confidence: str, evidence: str,
             report: ArtistReport, seeded_pool: int | None = None) -> None:
    """Record a confirmed identification on a row."""
    if song is not None:
        row["Song"] = song.title
        row["Setlist Pos"] = str(song.position)
        if song.info and not (row.get("Desc Slug") or "").strip():
            row["Desc Slug"] = _slug_from_info(song.info)
    row["Confidence"] = confidence
    row["Evidence"] = evidence

    entry = (row["Clip"], (row.get("Song") or "").strip(), evidence)
    if seeded_pool is None:
        report.confirmed.append(entry)
    else:
        report.seeded.append(entry)


def _apply_claims(group: list[dict], setlist, claims: dict[str, dict],
                  report: ArtistReport) -> None:
    """Layer 1: bind Content-ID claims to clips by video ID."""
    for row in group:
        if (row.get("Song") or "").strip():
            continue
        claim = claims.get((row.get("Video ID") or "").strip())
        if not claim:
            continue

        evidence = f"content-id:{claim['title']}"
        song = match_song(claim["title"], setlist) if setlist else None
        if song is None:
            # The claim is still the best evidence there is — a claim can
            # name a song the setlist page never listed. Seed the claimed
            # title verbatim; position stays unknown.
            row["Song"] = claim["title"]
            row["Confidence"] = CONFIDENCE_HIGH
            row["Evidence"] = evidence + " (not on setlist)"
            report.confirmed.append((row["Clip"], claim["title"], evidence))
            continue

        _confirm(row, song, CONFIDENCE_HIGH, evidence, report)


def _apply_lyrics(group: list[dict], setlist, lyrics: dict[str, dict],
                  report: ArtistReport) -> None:
    """Layer 2: lyric outcomes. Only `none` may whisper "unreleased"."""
    for row in group:
        outcome = lyrics.get((row.get("Clip") or "").strip())
        if not outcome:
            continue

        if outcome["hint"]:
            row["Lyric Hint"] = outcome["hint"]

        if outcome["status"] == "matched" and outcome["song"]:
            if (row.get("Song") or "").strip():
                continue
            evidence = "lyric"
            if outcome["source"]:
                evidence += f":{outcome['source']}"
            song = match_song(outcome["song"], setlist) if setlist else None
            if song is None:
                row["Song"] = outcome["song"]
                row["Confidence"] = CONFIDENCE_HIGH
                row["Evidence"] = evidence + " (not on setlist)"
                report.confirmed.append((row["Clip"], outcome["song"], evidence))
            else:
                _confirm(row, song, CONFIDENCE_HIGH, evidence, report)

        elif outcome["status"] == "none":
            # Lookup SUCCEEDED and found nothing — the unreleased signal.
            if not (row.get("Song") or "").strip():
                row["Evidence"] = "lyric-absence:unreleased?"
                row["Confidence"] = CONFIDENCE_LOW
                report.unreleased.append(row["Clip"])

        else:  # error — asserts nothing, but stays visible
            if not (row.get("Evidence") or "").strip():
                row["Evidence"] = "lyric-lookup:error"


def _honor_human_songs(group: list[dict], setlist, report: ArtistReport) -> None:
    """A Song typed by hand is an anchor too — resolve its setlist position."""
    for row in group:
        song_title = (row.get("Song") or "").strip()
        if not song_title:
            continue
        if (row.get("Evidence") or "").strip() not in EVIDENCE_HUMAN_MARKERS:
            continue  # machine-seeded this run or earlier; already handled

        row["Evidence"] = "human"
        row.setdefault("Confidence", "")
        row["Confidence"] = row["Confidence"] or CONFIDENCE_HIGH
        song = match_song(song_title, setlist) if setlist else None
        if song is not None:
            row["Setlist Pos"] = str(song.position)
            if song.info and not (row.get("Desc Slug") or "").strip():
                row["Desc Slug"] = _slug_from_info(song.info)
        report.confirmed.append((row["Clip"], song_title, "human"))


def _resolve_positions(group: list[dict], setlist) -> None:
    """Any confirmed Song with an unknown position becomes a bracketing anchor.

    Provenance does not matter here: a title that arrived via a claim row, a
    legacy manifest (Evidence values like "Content-ID" predating this
    pipeline), or a hand edit anchors bracketing equally well. Without this
    pass, a confirmed song with foreign Evidence was excluded from candidate
    pools but never anchored a position — so every bracket silently spanned
    the whole setlist and every Candidates hint came out identical.
    """
    if not setlist:
        return
    for row in group:
        song_title = (row.get("Song") or "").strip()
        if not song_title or song_title.lower() in ("unknown",
                                                    "unknown song", "?"):
            continue
        if (row.get("Setlist Pos") or "").strip():
            continue
        song = match_song(song_title, setlist)
        if song is not None:
            row["Setlist Pos"] = str(song.position)
            if song.info and not (row.get("Desc Slug") or "").strip():
                row["Desc Slug"] = _slug_from_info(song.info)


def _bracket(group: list[dict], setlist, report: ArtistReport) -> None:
    """Layer 3: anchored bracketing with global exclusion.

    Every clip with a confirmed Song and a known position is an anchor. Each
    unconfirmed clip's pool is the setlist positions strictly between its
    neighbouring anchors, minus every globally confirmed song. On a page
    that warns incomplete/out-of-order, positions are ordering hints only:
    no bracketing happens and the pool is simply every unconfirmed song
    (issue #251: trust the warning — it proved accurate, not stale).
    """
    confirmed_keys = {normalize_title(r.get("Song") or "")
                      for r in group if (r.get("Song") or "").strip()}
    pool_all = [s for s in setlist.titled_songs
                if normalize_title(s.title) not in confirmed_keys]

    ordered = sorted(group, key=lambda r: _int(r.get("Capture Order")))
    unconfirmed = [r for r in ordered if not (r.get("Song") or "").strip()]

    for row in unconfirmed:
        if report.incomplete:
            pool = pool_all
        else:
            low, high = _neighbour_anchor_positions(row, ordered)
            pool = [s for s in pool_all if low < s.position < high] or pool_all

        # Unknown-song placeholders in the bracket are part of the honest
        # answer: an unnamed setlist slot may be exactly this clip.
        unknown_here = [s for s in setlist.songs
                        if s.unknown and (report.incomplete
                                          or _within(row, ordered, s.position))]

        if len(pool) == 1 and not unknown_here and not report.incomplete:
            _confirm(row, pool[0], CONFIDENCE_MEDIUM,
                     "bracket:collapsed", report, seeded_pool=1)
            confirmed_keys.add(normalize_title(pool[0].title))
            pool_all = [s for s in pool_all if s is not pool[0]]
            continue

        names = [s.title for s in pool]
        names += [f"(unknown #{s.position})" for s in unknown_here]
        if len(names) > CANDIDATE_LIST_MAX:
            shown = " | ".join(names[:CANDIDATE_LIST_MAX])
            row["Candidates"] = f"{shown} | +{len(names) - CANDIDATE_LIST_MAX} more"
        else:
            row["Candidates"] = " | ".join(names)
        if not (row.get("Confidence") or "").strip():
            row["Confidence"] = CONFIDENCE_LOW
        report.open_pools.append((row["Clip"], row["Candidates"]))


def _neighbour_anchor_positions(row: dict, ordered: list[dict]) -> tuple[int, int]:
    """Setlist positions of the nearest confirmed clips either side, by capture."""
    index = ordered.index(row)

    low = 0
    for earlier in reversed(ordered[:index]):
        pos = _int(earlier.get("Setlist Pos"))
        if pos and (earlier.get("Song") or "").strip():
            low = pos
            break

    high = 10_000
    for later in ordered[index + 1:]:
        pos = _int(later.get("Setlist Pos"))
        if pos and (later.get("Song") or "").strip():
            high = pos
            break

    return low, high


def _within(row: dict, ordered: list[dict], position: int) -> bool:
    low, high = _neighbour_anchor_positions(row, ordered)
    return low < position < high


def _slug_from_info(info: str) -> str:
    """The Desc Slug prefill: the setlist parenthetical minus its outer parens,
    whitespace collapsed. "(Pete Seeger cover)" -> "Pete Seeger cover";
    "(unreleased)" -> "unreleased"; "(with Rose Droll)" -> "with Rose Droll".
    Whatever it returns is later prepended to the description verbatim."""
    t = (info or "").strip()
    if t.startswith("(") and t.endswith(")"):
        t = t[1:-1]
    return re.sub(r"\s+", " ", t).strip()


def _carry_slugs(group: list[dict], setlist) -> None:
    """Setlist parentheticals reach the Desc Slug column for every titled row."""
    if not setlist:
        return
    for row in group:
        if (row.get("Desc Slug") or "").strip():
            continue
        song_title = (row.get("Song") or "").strip()
        if not song_title:
            continue
        song = match_song(song_title, setlist)
        if song and song.info:
            row["Desc Slug"] = _slug_from_info(song.info)


def _int(value) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


# ── reporting ──────────────────────────────────────────────────────────────

def format_reports(reports: list[ArtistReport]) -> str:
    """Human-readable identification summary, one block per act."""
    lines = []
    for report in reports:
        lines.append(f"\n  {report.artist}")
        if report.setlist_status:
            lines.append(f"    setlist: {report.setlist_status}")
        if report.incomplete:
            lines.append("    PAGE WARNS INCOMPLETE — positions were treated "
                         "as hints, no bracketing")
        for note in report.notes:
            lines.append(f"    {note}")

        for clip, song, evidence in report.confirmed:
            lines.append(f"    ok   {clip}  {song}  [{evidence}]")
        for clip, song, evidence in report.seeded:
            lines.append(f"    seed {clip}  {song}  [{evidence}] — verify by ear")
        for clip in report.unreleased:
            lines.append(f"    ??   {clip}  unreleased? (lyric lookup found "
                         "nothing) — name it by ear")
        for clip, candidates in report.open_pools:
            lines.append(f"    pick {clip}  ← {candidates}")

    lines.append("\n  Edit Song in the lean manifest to resolve the open rows, "
                 "then run --apply --dry-run.")
    return "\n".join(lines)
