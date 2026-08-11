#!/usr/bin/env python3
"""
lint_manifest.py — Validate a pasted show manifest and report progress (#247)

The validator behind the playlist-issue CI, and a local pre-flight check.
Given a manifest — pasted into a GitHub issue comment or read from disk — it
reports exactly the mistakes that otherwise surface as a wrong title on a
public video, plus a phone-readable progress scoreboard.

WHAT THIS IS, AND IS NOT (#247)

  A validator and a scoreboard. NOT a state machine: an issue makes a good
  log and checklist and a poor control plane, so nothing here acts on
  YouTube, touches a credential, or drives the pipeline. The local CLI
  remains the thing that acts. This needs no secret of any kind.

THE COMMENT CONVENTION

  Paste the lean manifest TSV in a fenced block whose info string is
  `manifest`, and (optionally) the machine sidecar JSON in a block whose
  info string is `machine`:

      ```manifest
      Clip	Duration	Decision	Set Artist	Song	...
      PXL_1.mp4	3:20	got	Sabine McCalla	Louisiana Hound Dog	...
      ```

      ```machine
      { "clips": { "PXL_1.mp4": { "Video ID": "...", ... } } }
      ```

  The `manifest` info string is also the workflow's trigger filter, chosen
  so a lint comment can never collide with the close-playlist workflow,
  which watches for a youtube.com/playlist URL.

WHAT GETS CHECKED

  Errors (the wrong-title-in-public class):
    - unrecognized header (neither lean layout nor the legacy 20-column)
    - a row with more non-blank columns than the header (a shifted row);
      SHORT rows are padded instead of flagged, because GitHub comments and
      the MCP both strip trailing tabs — the same reality parseTsv() in
      index.html already compensates for
    - a Decision that is neither `got` nor `skip`
    - a duplicate Clip name
    - a Song carrying `???` or a literal `#song-title` — unpublishable text
      typed where a real title belongs
    - duplicate Setlist Pos within one Set Artist (machine block present)

  Warnings:
    - a skip row that carries a Song (which one is wrong?)
    - a skip row that carries a Video ID (uploaded, then demoted — deliberate?)
    - a legacy single-file manifest (any stage run will migrate it)
    - the pre-Duration lean layout (still valid; the next save upgrades it)

  Neither: got rows with a blank Song are PROGRESS, not errors — that is
  what a manifest looks like between --scan and the correction pass. They
  are counted on the scoreboard instead.

USAGE

  python3 lint_manifest.py --comment-file body.txt   # CI: a comment body
  python3 lint_manifest.py --manifest path.tsv       # local: files on disk

  Output is the reply markdown on stdout. Exit code is 0 even on lint
  errors — the CI reply carries the verdict; a red workflow run would just
  bury it.
"""

import argparse
import json
import re
import sys

from yt_manifest import (
    LEAN_FIELDS,
    LEAN_FIELDS_V1,
    LEGACY_FIELDS,
    MACHINE_FIELDS,
)


VALID_DECISIONS = {"got", "skip"}
UNPUBLISHABLE_IN_SONG = ("???", "#song-title")
UNKNOWN_SENTINELS = {"unknown", "unknown song", "?"}

SCOREBOARD_START = "<!-- manifest-scoreboard:start -->"
SCOREBOARD_END = "<!-- manifest-scoreboard:end -->"

_FENCE_RE = re.compile(
    r"```[ \t]*(manifest|machine)[ \t]*\r?\n(.*?)```", re.DOTALL)


# ── comment parsing ────────────────────────────────────────────────────────

def extract_blocks(body: str) -> tuple[str | None, str | None]:
    """The (manifest_tsv, machine_json) text blocks from a comment body."""
    manifest = machine = None
    for match in _FENCE_RE.finditer(body or ""):
        kind, content = match.group(1), match.group(2)
        if kind == "manifest" and manifest is None:
            manifest = content
        elif kind == "machine" and machine is None:
            machine = content
    return manifest, machine


def parse_tsv(text: str) -> tuple[list[str], list[list[str]]]:
    """(header, rows) from pasted TSV text. Blank lines are skipped."""
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return [], []
    header = lines[0].split("\t")
    rows = [ln.split("\t") for ln in lines[1:]]
    return header, rows


def parse_machine(text: str) -> tuple[dict[str, dict], str | None]:
    """({clip: fields}, error) from pasted sidecar JSON.

    Accepts either the full sidecar payload ({"clips": {...}}) or the bare
    clips mapping.
    """
    try:
        payload = json.loads(text)
    except ValueError as error:
        return {}, f"machine block is not valid JSON: {error}"
    clips = payload.get("clips", payload) if isinstance(payload, dict) else None
    if not isinstance(clips, dict):
        return {}, "machine block JSON has no clips mapping"
    return {clip: fields for clip, fields in clips.items()
            if isinstance(fields, dict)}, None


# ── linting ────────────────────────────────────────────────────────────────

def lint(header: list[str], rows: list[list[str]],
         machine: dict[str, dict]) -> tuple[list[str], list[str], dict]:
    """(errors, warnings, stats) for one manifest."""
    errors: list[str] = []
    warnings: list[str] = []

    legacy = header == LEGACY_FIELDS
    if legacy:
        warnings.append(
            "legacy single-file manifest — running any pipeline stage will "
            "migrate it to the lean TSV + machine sidecar split")
    elif header == LEAN_FIELDS_V1:
        warnings.append(
            "pre-Duration lean layout — still valid; the next save upgrades it")
    elif header != LEAN_FIELDS:
        errors.append(
            f"unrecognized header ({len(header)} columns). Expected the lean "
            f"schema: `{'` | `'.join(LEAN_FIELDS)}`")
        return errors, warnings, {}

    if legacy:
        fields = LEGACY_FIELDS
    elif header == LEAN_FIELDS_V1:
        fields = LEAN_FIELDS_V1
    else:
        fields = LEAN_FIELDS
    records: list[dict] = []
    seen_clips: set[str] = set()

    for lineno, row in enumerate(rows, start=2):
        # Trailing blank fields are meaningless either way: comments and the
        # MCP strip trailing tabs, and editors add them back. Normalize, then
        # judge: too many NON-BLANK columns means a genuinely shifted row.
        while row and not row[-1].strip():
            row = row[:-1]
        if len(row) > len(fields):
            errors.append(f"line {lineno}: {len(row)} non-blank columns, "
                          f"expected at most {len(fields)} — a shifted row?")
            continue
        row = row + [""] * (len(fields) - len(row))
        record = dict(zip(fields, row))
        clip = record.get("Clip", "").strip()
        if not clip:
            errors.append(f"line {lineno}: blank Clip name")
            continue
        if clip in seen_clips:
            errors.append(f"line {lineno}: duplicate Clip `{clip}`")
            continue
        seen_clips.add(clip)
        records.append(record)

        decision = record.get("Decision", "").strip()
        if decision not in VALID_DECISIONS:
            errors.append(f"`{clip}`: Decision `{decision}` — must be "
                          "`got` or `skip`")

        song = record.get("Song", "").strip()
        if any(mark in song for mark in UNPUBLISHABLE_IN_SONG):
            errors.append(f"`{clip}`: Song `{song}` contains unpublishable "
                          "text — name the song, or type `unknown` to "
                          "publish it with a crowdsourcing title")
        if decision == "skip" and song:
            warnings.append(f"`{clip}`: skip row carries a Song "
                            f"(`{song}`) — which one is wrong?")

    # Machine-side checks, joined on Clip.
    for clip, mfields in machine.items():
        record = next((r for r in records
                       if r.get("Clip", "").strip() == clip), None)
        if record is None:
            warnings.append(f"machine block has `{clip}` with no lean row — "
                            "orphan (kept by the tools, but check it)")
            continue
        if (record.get("Decision", "").strip() == "skip"
                and str(mfields.get("Video ID") or "").strip()):
            warnings.append(f"`{clip}`: skip row carries a Video ID — "
                            "uploaded and then demoted? The video itself "
                            "is untouched either way.")

    # Duplicate Setlist Pos within one Set Artist.
    if machine:
        by_artist_pos: dict[tuple[str, str], list[str]] = {}
        for record in records:
            clip = record["Clip"].strip()
            pos = str((machine.get(clip) or {}).get("Setlist Pos") or "").strip()
            artist = record.get("Set Artist", "").strip()
            if pos and record.get("Decision", "").strip() == "got":
                by_artist_pos.setdefault((artist, pos), []).append(clip)
        for (artist, pos), clips in sorted(by_artist_pos.items()):
            if len(clips) > 1:
                errors.append(f"{artist}: Setlist Pos {pos} claimed by "
                              f"{len(clips)} clips ({', '.join(clips)}) — "
                              "two clips cannot be the same song")

    stats = _stats(records, machine)
    return errors, warnings, stats


def _stats(records: list[dict], machine: dict[str, dict]) -> dict:
    got = [r for r in records if r.get("Decision", "").strip() == "got"]

    def mfield(record, name):
        return str((machine.get(record["Clip"].strip()) or {})
                   .get(name) or "").strip()

    named = [r for r in got if r.get("Song", "").strip()
             and r.get("Song", "").strip().lower() not in UNKNOWN_SENTINELS]
    unknowns = [r for r in got
                if r.get("Song", "").strip().lower() in UNKNOWN_SENTINELS]

    return {
        "clips": len(records),
        "keepers": len(got),
        "skips": len(records) - len(got),
        "uploaded": sum(1 for r in got if mfield(r, "Video ID")),
        "named": len(named),
        "unknown_marked": len(unknowns),
        "titles_pending": len(got) - len(named) - len(unknowns),
        "applied": sum(1 for r in got
                       if mfield(r, "Title Set") and mfield(r, "Desc Set")),
        "published": sum(1 for r in got if mfield(r, "Privacy") == "public"),
        "has_machine": bool(machine),
    }


# ── rendering ──────────────────────────────────────────────────────────────

def render_scoreboard(stats: dict) -> str:
    """The progress checklist that lives in the issue body."""
    if not stats:
        return ""

    def box(done: bool) -> str:
        return "[x]" if done else "[ ]"

    keepers = stats["keepers"]
    lines = [
        SCOREBOARD_START,
        "### Pipeline progress",
        "",
        f"- {box(stats['clips'] > 0)} scanned — {stats['clips']} clips, "
        f"{keepers} keepers, {stats['skips']} skipped",
    ]
    if stats["has_machine"]:
        lines.append(f"- {box(stats['uploaded'] >= keepers > 0)} uploaded — "
                     f"{stats['uploaded']} of {keepers}")
    identified = stats["named"] + stats["unknown_marked"]
    id_note = f"{stats['named']} named"
    if stats["unknown_marked"]:
        id_note += f" + {stats['unknown_marked']} marked unknown"
    if stats["titles_pending"]:
        id_note += f", {stats['titles_pending']} pending"
    lines.append(f"- {box(identified >= keepers > 0)} identified — {id_note}")
    if stats["has_machine"]:
        lines.append(f"- {box(stats['applied'] >= keepers > 0)} titles "
                     f"applied — {stats['applied']} of {keepers}")
        lines.append(f"- {box(stats['published'] >= keepers > 0)} published "
                     f"— {stats['published']} of {keepers}")
    lines += ["", SCOREBOARD_END]
    return "\n".join(lines)


def render_reply(errors: list[str], warnings: list[str], stats: dict) -> str:
    """The lint reply comment."""
    lines = []
    if errors:
        lines.append(f"**Manifest lint: {len(errors)} problem(s)** — these "
                     "are exactly the mistakes that end as a wrong title on "
                     "a public video:")
        lines += [f"- {e}" for e in errors]
    else:
        lines.append("**Manifest lint: clean.**")
    if warnings:
        lines.append("")
        lines.append("Worth a look:")
        lines += [f"- {w}" for w in warnings]
    if stats:
        lines.append("")
        board = render_scoreboard(stats)
        # The reply shows the same board; the workflow also mirrors it into
        # the issue body between the scoreboard markers.
        lines.append(board.replace(SCOREBOARD_START + "\n", "")
                          .replace("\n" + SCOREBOARD_END, ""))
    return "\n".join(lines)


def update_body(body: str, scoreboard: str) -> str:
    """The issue body with its scoreboard section replaced or appended."""
    body = body or ""
    if SCOREBOARD_START in body and SCOREBOARD_END in body:
        pattern = re.compile(
            re.escape(SCOREBOARD_START) + r".*?" + re.escape(SCOREBOARD_END),
            re.DOTALL)
        return pattern.sub(scoreboard, body)
    return body.rstrip() + "\n\n" + scoreboard + "\n"


# ── cli ────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Lint a show manifest and render the progress scoreboard")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--comment-file", metavar="PATH",
                        help="File holding an issue-comment body with "
                             "```manifest / ```machine fenced blocks.")
    source.add_argument("--manifest", metavar="PATH",
                        help="Lean manifest TSV on disk (the machine sidecar "
                             "next to it is read automatically).")
    parser.add_argument("--scoreboard-file", metavar="PATH",
                        help="Also write the issue-body scoreboard fragment "
                             "here (used by CI).")
    args = parser.parse_args()

    if args.comment_file:
        with open(args.comment_file, encoding="utf-8") as f:
            body = f.read()
        manifest_text, machine_text = extract_blocks(body)
        if manifest_text is None:
            print("No ```manifest block found in the comment — nothing to lint.")
            return
        machine, machine_error = ({}, None)
        if machine_text is not None:
            machine, machine_error = parse_machine(machine_text)
    else:
        with open(args.manifest, encoding="utf-8") as f:
            manifest_text = f.read()
        machine_error = None
        try:
            with open(args.manifest[:-4] + ".machine.json",
                      encoding="utf-8") as f:
                machine, machine_error = parse_machine(f.read())
        except OSError:
            machine = {}

    header, rows = parse_tsv(manifest_text)
    errors, warnings, stats = lint(header, rows, machine)
    if machine_error:
        warnings.append(machine_error)

    print(render_reply(errors, warnings, stats))

    if args.scoreboard_file and stats:
        with open(args.scoreboard_file, "w", encoding="utf-8") as f:
            f.write(render_scoreboard(stats) + "\n")


if __name__ == "__main__":
    main()
