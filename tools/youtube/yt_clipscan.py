#!/usr/bin/env python3
"""
yt_clipscan.py — Local inspection of a night's phone clips

Reads a directory of video files and derives everything that can be known
without uploading anything: capture order, duration, set structure, and which
clips are fragments rather than song captures. No network, no OAuth, no
YouTube API. Importable and testable on its own.

WHAT IT PRODUCES, AND HOW MUCH TO TRUST IT

  Capture order        Authoritative. Sorting by capture start is the only
                       reliable sequencing signal available. Upload/list order
                       carries none — the same workflow produced reverse-order
                       on one show and scrambled on another.

  Duration             Exact from ffprobe; approximate from a file-size proxy
                       when ffprobe is absent. Good enough for fragment
                       detection either way.

  Segment boundaries   Reliable. A long dark gap between the end of one clip
                       and the start of the next is a real break in the show —
                       a set change, a support-to-headliner turnover, or an
                       encore break. Which of those it is, this module does
                       not claim to know; it numbers the segments and reports
                       the gap that produced each one.

  Set position         A weak prior only. Capture order does not reliably equal
                       setlist order — sets are often filmed out of order. Two
                       independent estimates are produced (dark-gap arithmetic
                       and elapsed-clock) and reported as a RANGE. Where they
                       diverge, the divergence is the uncertainty signal. This
                       is never a basis for naming a song.

THE DURATION LADDER

  1. ffprobe        exact duration + container creation_time. Enables the
                    integrity check below.
  2. size proxy     bytes / bytes-per-second, calibrated from whichever clips
                    in the same batch did probe cleanly, else a default.
                    Phone encoders are variable-bitrate, so this runs +/-10-30%
                    — fine for ranking and fragment detection, not a substitute
                    for exact duration.
  3. filename only  start time with no duration. Ordering and integrity are
                    unavailable; the clip is still placed in sequence.

THE INTEGRITY GATE

  On phones that stamp the filename with the recording START and the container
  creation_time with the recording STOP, filename_start + duration should equal
  creation_time. Agreement within a few seconds proves the file is an untrimmed
  original; a large delta means it was trimmed or re-encoded and its timestamps
  can no longer be trusted for ordering.

REQUIRES:
  ffprobe on PATH for exact durations (brew install ffmpeg). Degrades without it.
"""

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


# ── constants ──────────────────────────────────────────────────────────────

VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".3gp", ".webm"}

DEFAULT_TIMEZONE       = "America/New_York"
# At or under this, pre-flag as a skip candidate. Set above the longest known
# real fragment (54s) rather than at the low end of the observed range: the two
# errors are not symmetric. A wrongly flagged keeper costs one edit in the
# manifest; a missed fragment becomes an uploaded, titled, published false start.
DEFAULT_FRAGMENT_SECS  = 60.0
DEFAULT_MIN_GAP_MINS   = 15.0   # floor for a dark gap to count as a boundary
DEFAULT_OUTLIER_FACTOR = 2.0    # and it must exceed this multiple of the median gap
DEFAULT_AVG_SONG_SECS  = 240.0  # 4:00, for position estimates only
INTEGRITY_TOLERANCE    = 5.0    # seconds of slack on start + duration == stop

# Fallback only, used when no clip in the batch probed cleanly. Roughly a
# 1080p phone capture at ~20 Mbps.
DEFAULT_BYTES_PER_SEC = 2_500_000

FFPROBE_TIMEOUT = 30  # seconds per file

# Capture-start patterns, most specific first. `utc` marks formats known to
# stamp UTC rather than local wall time.
FILENAME_PATTERNS = [
    (re.compile(r"PXL_(\d{8})_(\d{6})(\d{3})"), "%Y%m%d%H%M%S", True,  "pixel"),
    (re.compile(r"VID_(\d{8})_(\d{6})"),        "%Y%m%d%H%M%S", False, "vid"),
    (re.compile(r"IMG_(\d{8})_(\d{6})"),        "%Y%m%d%H%M%S", False, "img"),
    (re.compile(r"(\d{8})_(\d{6})"),            "%Y%m%d%H%M%S", False, "generic"),
    (re.compile(r"(\d{4}-\d{2}-\d{2})[ T_](\d{2})[.:-](\d{2})[.:-](\d{2})"),
                                                 None,           False, "dashed"),
]


# ── model ──────────────────────────────────────────────────────────────────

@dataclass
class Clip:
    """One local video file and everything derived from it."""
    path: str
    name: str
    size_bytes: int

    duration_s: float | None = None
    duration_rung: str = "none"          # ffprobe | size-proxy | none

    capture_start: datetime | None = None
    capture_start_source: str = "none"   # pixel | vid | img | generic | dashed
                                         # | container-derived | mtime | none
    creation_time: datetime | None = None

    integrity: str = "unverified"        # ok | delta:Ns | unverified
    integrity_delta_s: float | None = None

    capture_order: int = 0
    segment: int = 1
    gap_before_s: float | None = None    # dark time since the previous clip ended

    is_fragment: bool = False
    skip_reason: str = ""

    position_low: int | None = None
    position_high: int | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def capture_end(self) -> datetime | None:
        if self.capture_start is None or self.duration_s is None:
            return None
        return self.capture_start + timedelta(seconds=self.duration_s)

    @property
    def size_mb(self) -> float:
        return self.size_bytes / 1_000_000

    @property
    def position_range(self) -> str:
        if self.position_low is None:
            return ""
        if self.position_low == self.position_high:
            return f"~{self.position_low}"
        return f"~{self.position_low}-{self.position_high}"


# ── probing ────────────────────────────────────────────────────────────────

def ffprobe_available() -> bool:
    """True if ffprobe is on PATH."""
    return shutil.which("ffprobe") is not None


def probe_file(path: str) -> tuple[float | None, datetime | None]:
    """Return (duration_seconds, creation_time_utc) from ffprobe, or (None, None).

    Never raises: a missing binary, an unreadable file, or malformed output all
    degrade to (None, None) so the caller can fall back down the ladder.
    """
    if not ffprobe_available():
        return None, None

    cmd = ["ffprobe", "-v", "quiet", "-print_format", "json",
           "-show_format", path]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True,
                             timeout=FFPROBE_TIMEOUT)
        if out.returncode != 0:
            return None, None
        fmt = json.loads(out.stdout).get("format", {})
    except (subprocess.SubprocessError, OSError, ValueError):
        return None, None

    duration = None
    try:
        duration = float(fmt["duration"])
    except (KeyError, TypeError, ValueError):
        pass

    created = None
    raw = (fmt.get("tags") or {}).get("creation_time")
    if raw:
        try:
            created = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
        except ValueError:
            created = None

    return duration, created


def parse_capture_start(name: str, tz: ZoneInfo) -> tuple[datetime | None, str]:
    """Extract the recording start time from a filename.

    Returns (aware datetime in `tz`, source label). Pixel filenames stamp UTC;
    the other recognized formats stamp local wall time.
    """
    for pattern, fmt, is_utc, label in FILENAME_PATTERNS:
        match = pattern.search(name)
        if not match:
            continue

        try:
            if label == "dashed":
                date_part, hh, mm, ss = match.groups()
                naive = datetime.strptime(f"{date_part}{hh}{mm}{ss}", "%Y-%m-%d%H%M%S")
            else:
                date_part, time_part = match.group(1), match.group(2)
                naive = datetime.strptime(date_part + time_part, fmt)
                if pattern.groups >= 3 and match.group(3):
                    naive += timedelta(milliseconds=int(match.group(3)))
        except (ValueError, IndexError):
            continue

        if is_utc:
            return naive.replace(tzinfo=timezone.utc).astimezone(tz), label
        return naive.replace(tzinfo=tz), label

    return None, "none"


def check_integrity(start: datetime | None,
                    duration_s: float | None,
                    creation_time: datetime | None,
                    tolerance: float = INTEGRITY_TOLERANCE) -> tuple[str, float | None]:
    """Verify that filename start + duration lands on the container stop time.

    Agreement within `tolerance` means the file is an untrimmed original.
    Returns ("ok" | "delta:Ns" | "unverified", delta_seconds_or_None).
    """
    if start is None or duration_s is None or creation_time is None:
        return "unverified", None

    expected = start + timedelta(seconds=duration_s)
    delta = abs((creation_time - expected).total_seconds())
    if delta <= tolerance:
        return "ok", delta
    return f"delta:{delta:.0f}s", delta


# ── scanning ───────────────────────────────────────────────────────────────

def list_clip_files(clip_dir: str) -> list[str]:
    """Absolute paths of video files in a directory, name-sorted, non-recursive."""
    if not os.path.isdir(clip_dir):
        raise NotADirectoryError(f"Not a directory: {clip_dir}")
    names = sorted(n for n in os.listdir(clip_dir)
                   if os.path.splitext(n)[1].lower() in VIDEO_EXTENSIONS
                   and not n.startswith("."))
    return [os.path.join(clip_dir, n) for n in names]


def calibrate_bytes_per_second(clips: list[Clip]) -> float:
    """Median bytes/sec across clips that probed cleanly, else the default.

    Calibrating within the batch is much better than a fixed constant: the
    clips share a device and capture settings, so their bitrate is consistent
    with each other even when it differs from any global assumption.
    """
    rates = sorted(c.size_bytes / c.duration_s
                   for c in clips
                   if c.duration_rung == "ffprobe" and c.duration_s)
    if not rates:
        return float(DEFAULT_BYTES_PER_SEC)
    mid = len(rates) // 2
    if len(rates) % 2:
        return rates[mid]
    return (rates[mid - 1] + rates[mid]) / 2


def scan_dir(clip_dir: str,
             timezone_name: str = DEFAULT_TIMEZONE,
             fragment_seconds: float = DEFAULT_FRAGMENT_SECS,
             min_gap_minutes: float = DEFAULT_MIN_GAP_MINS,
             outlier_factor: float = DEFAULT_OUTLIER_FACTOR,
             avg_song_seconds: float = DEFAULT_AVG_SONG_SECS) -> list[Clip]:
    """Inspect every video file in a directory and return ordered, annotated Clips.

    Runs the full local pipeline: probe, timestamp, integrity-check, order,
    segment, fragment-flag, position-estimate.
    """
    tz = ZoneInfo(timezone_name)
    clips = [_build_clip(path, tz) for path in list_clip_files(clip_dir)]
    if not clips:
        return []

    _apply_size_proxy(clips)
    _resolve_missing_starts(clips, tz)

    for clip in clips:
        clip.integrity, clip.integrity_delta_s = check_integrity(
            clip.capture_start, clip.duration_s, clip.creation_time)

    clips = order_clips(clips)
    detect_segments(clips, min_gap_minutes, outlier_factor)
    flag_fragments(clips, fragment_seconds)
    estimate_positions(clips, avg_song_seconds)
    return clips


def _build_clip(path: str, tz: ZoneInfo) -> Clip:
    """Probe one file and populate what is directly readable from it."""
    name = os.path.basename(path)
    clip = Clip(path=path, name=name, size_bytes=os.path.getsize(path))

    duration, created = probe_file(path)
    if duration is not None:
        clip.duration_s = duration
        clip.duration_rung = "ffprobe"
    clip.creation_time = created.astimezone(tz) if created else None

    clip.capture_start, clip.capture_start_source = parse_capture_start(name, tz)
    return clip


def _apply_size_proxy(clips: list[Clip]) -> None:
    """Fill unknown durations from a batch-calibrated bytes-per-second rate."""
    rate = calibrate_bytes_per_second(clips)
    for clip in clips:
        if clip.duration_s is None:
            clip.duration_s = clip.size_bytes / rate
            clip.duration_rung = "size-proxy"
            clip.notes.append("duration estimated from file size")


def _resolve_missing_starts(clips: list[Clip], tz: ZoneInfo) -> None:
    """Derive a capture start for clips whose filename carried no timestamp.

    Prefers the container stop time minus duration; falls back to filesystem
    mtime, which is the weakest signal available and is labeled as such.
    """
    for clip in clips:
        if clip.capture_start is not None:
            continue
        if clip.creation_time and clip.duration_s is not None:
            clip.capture_start = clip.creation_time - timedelta(seconds=clip.duration_s)
            clip.capture_start_source = "container-derived"
            clip.notes.append("start derived from container stop time")
        else:
            mtime = datetime.fromtimestamp(os.path.getmtime(clip.path), tz)
            clip.capture_start = mtime
            clip.capture_start_source = "mtime"
            clip.notes.append("start fell back to file mtime — ordering is unreliable")


def order_clips(clips: list[Clip]) -> list[Clip]:
    """Sort by capture start and assign 1-based capture_order."""
    far_future = datetime.max.replace(tzinfo=timezone.utc)
    ordered = sorted(clips, key=lambda c: (c.capture_start or far_future, c.name))
    for index, clip in enumerate(ordered, start=1):
        clip.capture_order = index
    return ordered


def detect_segments(clips: list[Clip],
                    min_gap_minutes: float = DEFAULT_MIN_GAP_MINS,
                    outlier_factor: float = DEFAULT_OUTLIER_FACTOR) -> int:
    """Split clips into segments at long dark gaps. Returns the segment count.

    A dark gap is the stage time between the end of one clip and the start of
    the next. A large one is a genuine break — a set change, a support-to-
    headliner turnover, or an encore break. This deliberately does not guess
    WHICH of those it is; it numbers segments and records the gap that opened
    each, leaving the interpretation to the caller and to human correction.

    A gap must clear two independent tests to count as a boundary: an absolute
    floor, and a multiple of the batch's own median gap. The floor alone is
    brittle in both directions — a night filmed in tight bursts makes ordinary
    banter look like a set change, while a night filmed sparsely buries a real
    one. Judging each gap against the median of the same night adapts to how
    that night was actually filmed.

    Every gap is recorded on the clip regardless, so a near-miss is visible in
    the report and can be forced with --min-gap-minutes.
    """
    gaps = []
    previous_end = None
    for clip in clips:
        if previous_end is not None and clip.capture_start is not None:
            clip.gap_before_s = (clip.capture_start - previous_end).total_seconds()
            gaps.append(clip.gap_before_s)
        if clip.capture_end is not None:
            previous_end = clip.capture_end

    threshold = min_gap_minutes * 60
    if gaps:
        ordered = sorted(gaps)
        mid = len(ordered) // 2
        median = (ordered[mid] if len(ordered) % 2
                  else (ordered[mid - 1] + ordered[mid]) / 2)
        threshold = max(threshold, median * outlier_factor)

    segment = 1
    for clip in clips:
        if clip.gap_before_s is not None and clip.gap_before_s >= threshold:
            segment += 1
            clip.notes.append(
                f"segment boundary — {clip.gap_before_s / 60:.0f} min dark gap")
        clip.segment = segment

    return segment


def flag_fragments(clips: list[Clip], fragment_seconds: float = DEFAULT_FRAGMENT_SECS) -> int:
    """Pre-flag short clips as skip candidates. Returns how many were flagged.

    False starts and fumbles are invisible to start times and obvious in
    duration. Flagging is a seed for the human pass, never a deletion — the
    file is untouched and the row stays in the manifest with its reason
    showing, so flipping it back to got is a one-word edit.
    """
    flagged = 0
    for clip in clips:
        if clip.duration_s is not None and clip.duration_s <= fragment_seconds:
            clip.is_fragment = True
            approx = "~" if clip.duration_rung == "size-proxy" else ""
            clip.skip_reason = f"fragment:{approx}{clip.duration_s:.0f}s"
            flagged += 1
    return flagged


def estimate_positions(clips: list[Clip],
                       avg_song_seconds: float = DEFAULT_AVG_SONG_SECS) -> None:
    """Attach a weak set-position range to each clip, per segment.

    Two independent estimates are computed and reported as a range:

      count estimate  walks the segment accumulating one position per captured
                      clip plus one per average-song-length of dark gap.
      clock estimate  elapsed time since the segment's first clip, divided by
                      the average song length.

    Where they agree the guess is worth something; where they diverge, the
    spread is the honest output. Neither is evidence for a song title.
    """
    by_segment: dict[int, list[Clip]] = {}
    for clip in clips:
        by_segment.setdefault(clip.segment, []).append(clip)

    for segment_clips in by_segment.values():
        counted = 0
        segment_start = segment_clips[0].capture_start
        previous_end = None

        for clip in segment_clips:
            if previous_end is not None and clip.capture_start is not None:
                dark = max(0.0, (clip.capture_start - previous_end).total_seconds())
                counted += int(round(dark / avg_song_seconds))
            counted += 1

            clock = counted
            if segment_start is not None and clip.capture_start is not None:
                elapsed = (clip.capture_start - segment_start).total_seconds()
                clock = 1 + int(round(elapsed / avg_song_seconds))

            clip.position_low  = max(1, min(counted, clock))
            clip.position_high = max(1, max(counted, clock))

            if clip.capture_end is not None:
                previous_end = clip.capture_end


# ── reporting ──────────────────────────────────────────────────────────────

def human_duration(seconds: float | None) -> str:
    """Seconds as M:SS, or a placeholder when duration is unknown."""
    if seconds is None:
        return "?:??"
    minutes, secs = divmod(int(round(seconds)), 60)
    return f"{minutes}:{secs:02d}"


def summarize(clips: list[Clip]) -> str:
    """Human-readable scan table, printed before anything is uploaded."""
    if not clips:
        return "No video files found."

    lines = []
    segments = sorted({c.segment for c in clips})
    keepers = [c for c in clips if not c.is_fragment]

    lines.append(f"{len(clips)} clips — {len(keepers)} keepers, "
                 f"{len(clips) - len(keepers)} fragments, "
                 f"{len(segments)} segment(s)")

    probed = sum(1 for c in clips if c.duration_rung == "ffprobe")
    if probed < len(clips):
        lines.append(f"  WARNING: only {probed}/{len(clips)} clips probed exactly; "
                     "the rest use the file-size proxy (+/-10-30%)")

    bad = [c for c in clips if c.integrity.startswith("delta:")]
    if bad:
        lines.append(f"  WARNING: {len(bad)} clip(s) failed the untrimmed-original "
                     "check — their timestamps may not be reliable")

    for segment in segments:
        members = [c for c in clips if c.segment == segment]
        gap = members[0].gap_before_s
        noun = "clip" if len(members) == 1 else "clips"
        header = f"\n  Segment {segment} — {len(members)} {noun}"
        if gap and segment > 1:
            header += f" (after a {gap / 60:.0f} min break)"
        lines.append(header)

        for clip in members:
            mark = "skip" if clip.is_fragment else "got "
            start = (clip.capture_start.strftime("%I:%M %p").lstrip("0")
                     if clip.capture_start else "??:??")
            lines.append(
                f"    {clip.capture_order:2}. [{mark}] {start:>8}  "
                f"{human_duration(clip.duration_s):>5}  "
                f"seg pos {clip.position_range or '?':>7}  "
                f"{clip.integrity:<12} {clip.name}"
            )

    lines.append("\n  Dark gaps, longest first (a boundary was drawn at the ones marked *):")
    gapped = sorted((c for c in clips if c.gap_before_s is not None),
                    key=lambda c: c.gap_before_s, reverse=True)
    for clip in gapped[:6]:
        drawn = "*" if any(n.startswith("segment boundary") for n in clip.notes) else " "
        lines.append(f"    {drawn} {clip.gap_before_s / 60:5.0f} min before clip "
                     f"{clip.capture_order}")
    lines.append("    Re-run with --min-gap-minutes to move the line.")

    lines.append("\n  Set position is a per-segment estimate and a weak prior only — "
                 "capture order\n  does not reliably equal setlist order. It never names a song.")

    return "\n".join(lines)
