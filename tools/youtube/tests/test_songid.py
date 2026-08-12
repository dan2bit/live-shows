#!/usr/bin/env python3
"""
Regression tests for the song-identification layer (issue #251).

Fixtures are synthetic but shaped by the two validated shows: the out-of-order
capture that made lyric evidence override position (The Family Crest pattern),
and the cover + unreleased Content-ID blind spots (Lake Street Dive pattern).
The setlist HTML fixture mirrors the live setlist.fm markup pinned on
2026-08-11: li.setlistParts.song, a.songLabel, span.unknownSong, the encore
marker row, ad rows, infoPart cover notes, and the p.info incomplete warning.

Run from tools/youtube/:  python3 -m unittest discover tests
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import yt_manifest
import yt_songid
from yt_setlist import parse_setlist


# ── fixtures ───────────────────────────────────────────────────────────────

def song_li(title, info=""):
    info_html = f'<small class="fontSmall">{info}</small>' if info else \
                '<small class="fontSmall"></small>'
    return (f'<li class="setlistParts song"><div class="songPart">'
            f'<a class="songLabel">{title}</a></div>'
            f'<div class="infoPart">{info_html}</div></li>')


def unknown_li():
    return ('<li class="setlistParts song"><div class="songPart">'
            '<span class="unknownSong">(Unknown)</span></div>'
            '<div class="infoPart"><small class="fontSmall"></small></div></li>')


def page(songs_html, note=""):
    note_html = (f'<p class="info fontSmall text-center">Note: {note}</p>'
                 if note else "")
    return (f'<html><body>{note_html}<div class="setlistList">'
            f'<ol class="songsList">{songs_html}</ol></div></body></html>')


SETLIST_HTML = page(
    song_li("Howl")
    + song_li("Beneath the Brine")
    + '<li class="setlistParts setlistFluidAd hidden-print">ad</li>'
    + song_li("The River")
    + song_li("Sparrows", '(<a>Big Joe Williams</a> cover)')
    + unknown_li()
    + '<li class="setlistParts encore highlight">Encore:</li>'
    + song_li("Daguerreotype")
)


def manifest_rows(spec):
    """Rows from (clip, capture_order, decision, song, video_id) tuples."""
    rows = []
    for clip, order, decision, song, video_id in spec:
        row = yt_manifest.blank_row()
        row.update({"Clip": clip, "Capture Order": str(order),
                    "Decision": decision, "Set Artist": "The Family Crest",
                    "Song": song, "Video ID": video_id})
        rows.append(row)
    return rows


SHOW = {"date": "2026-08-08", "artist": "The Family Crest",
        "venue": "DC9", "support": "", "setlist_url": ""}


def parsed_setlist(html=SETLIST_HTML):
    setlist, status = parse_setlist(html, "The Family Crest", "test://setlist")
    return setlist


# ── setlist parser ─────────────────────────────────────────────────────────

class TestSetlistParser(unittest.TestCase):
    def test_structure(self):
        s = parsed_setlist()
        self.assertEqual([x.title for x in s.titled_songs],
                         ["Howl", "Beneath the Brine", "The River",
                          "Sparrows", "Daguerreotype"])
        self.assertEqual(len(s.songs), 6)          # ad row skipped, unknown kept
        self.assertEqual(s.songs[4].unknown, True)
        self.assertEqual(s.songs[4].position, 5)

    def test_encore_section(self):
        s = parsed_setlist()
        self.assertEqual(s.songs[-1].section, "Encore:")
        self.assertEqual(s.songs[0].section, "")

    def test_cover_attribution(self):
        s = parsed_setlist()
        sparrows = s.songs[3]
        self.assertEqual(sparrows.cover_of, "Big Joe Williams")

    def test_incomplete_warning(self):
        html = page(song_li("Howl"), note="Setlist incomplete and out of order")
        s, _ = parse_setlist(html, "X", "test://x")
        self.assertTrue(s.incomplete)
        self.assertFalse(parsed_setlist().incomplete)


# ── identification ─────────────────────────────────────────────────────────

class TestIdentify(unittest.TestCase):
    def identify(self, rows, claims=None, lyrics=None, html=SETLIST_HTML,
                 reseed=False):
        setlists = {"The Family Crest": parsed_setlist(html)}
        return yt_songid.identify_rows(rows, SHOW, setlists,
                                       claims or {}, lyrics or {},
                                       reseed=reseed)

    def test_claim_binds_by_video_id(self):
        rows = manifest_rows([("c1.mp4", 1, "got", "", "vidA")])
        self.identify(rows, claims={"vidA": {"title": "Howl", "artist": "",
                                             "start": ""}})
        self.assertEqual(rows[0]["Song"], "Howl")
        self.assertEqual(rows[0]["Confidence"], "high")
        self.assertIn("content-id", rows[0]["Evidence"])
        self.assertEqual(rows[0]["Setlist Pos"], "1")

    def test_claim_off_setlist_still_seeds(self):
        rows = manifest_rows([("c1.mp4", 1, "got", "", "vidA")])
        self.identify(rows, claims={"vidA": {"title": "Not Listed",
                                             "artist": "", "start": ""}})
        self.assertEqual(rows[0]["Song"], "Not Listed")
        self.assertIn("not on setlist", rows[0]["Evidence"])

    def test_lyric_overrides_position_tfc_pattern(self):
        # Encore captured BEFORE the preceding song: capture order says the
        # last clip should be late-set, lyric says it is song 3.
        rows = manifest_rows([
            ("c1.mp4", 1, "got", "", "v1"),
            ("c2.mp4", 2, "got", "", "v2"),   # actually the encore
            ("c3.mp4", 3, "got", "", "v3"),   # actually The River (pos 3)
        ])
        lyrics = {
            "c2.mp4": {"status": "matched", "song": "Daguerreotype",
                       "hint": "opening line …", "source": "bandcamp"},
            "c3.mp4": {"status": "matched", "song": "The River",
                       "hint": "second verse …", "source": "bandcamp"},
        }
        self.identify(rows, lyrics=lyrics)
        self.assertEqual(rows[1]["Song"], "Daguerreotype")
        self.assertEqual(rows[1]["Setlist Pos"], "6")
        self.assertEqual(rows[2]["Song"], "The River")
        self.assertEqual(rows[2]["Setlist Pos"], "3")

    def test_global_exclusion_and_bracketing(self):
        # c2 confirmed as pos 3; c1 (before it) must bracket to pos < 3,
        # minus confirmed songs.
        rows = manifest_rows([
            ("c1.mp4", 1, "got", "", "v1"),
            ("c2.mp4", 2, "got", "", "v2"),
        ])
        lyrics = {"c2.mp4": {"status": "matched", "song": "The River",
                             "hint": "", "source": ""}}
        self.identify(rows, lyrics=lyrics)
        cands = rows[0]["Candidates"]
        self.assertIn("Howl", cands)
        self.assertIn("Beneath the Brine", cands)
        self.assertNotIn("The River", cands)

    def test_bracket_collapse_seeds_medium(self):
        # Anchors at pos 1 and pos 3 leave exactly one song between them.
        rows = manifest_rows([
            ("c1.mp4", 1, "got", "", "v1"),
            ("c2.mp4", 2, "got", "", "v2"),
            ("c3.mp4", 3, "got", "", "v3"),
        ])
        lyrics = {
            "c1.mp4": {"status": "matched", "song": "Howl", "hint": "", "source": ""},
            "c3.mp4": {"status": "matched", "song": "The River", "hint": "", "source": ""},
        }
        self.identify(rows, lyrics=lyrics)
        self.assertEqual(rows[1]["Song"], "Beneath the Brine")
        self.assertEqual(rows[1]["Confidence"], "medium")
        self.assertEqual(rows[1]["Evidence"], "bracket:collapsed")

    def test_lyric_none_flags_unreleased_error_does_not(self):
        rows = manifest_rows([
            ("c1.mp4", 1, "got", "", "v1"),
            ("c2.mp4", 2, "got", "", "v2"),
        ])
        lyrics = {
            "c1.mp4": {"status": "none", "song": "", "hint": "", "source": ""},
            "c2.mp4": {"status": "error", "song": "", "hint": "", "source": ""},
        }
        reports = self.identify(rows, lyrics=lyrics)
        self.assertIn("c1.mp4", reports[0].unreleased)
        self.assertEqual(rows[0]["Evidence"], "lyric-absence:unreleased?")
        self.assertNotIn("c2.mp4", reports[0].unreleased)
        self.assertEqual(rows[1]["Evidence"], "lyric-lookup:error")

    def test_foreign_evidence_song_still_anchors(self):
        # The Moss/McCalla regression: a Song carried in from a legacy
        # manifest with Evidence "Content-ID" was excluded from pools but
        # never anchored a position, so every bracket spanned the whole
        # setlist and every Candidates hint was identical.
        rows = manifest_rows([
            ("c1.mp4", 1, "got", "", "v1"),
            ("c2.mp4", 2, "got", "The River", "v2"),   # pos 3, foreign evidence
            ("c3.mp4", 3, "got", "", "v3"),
        ])
        rows[1]["Evidence"] = "Content-ID"
        self.identify(rows)
        self.assertEqual(rows[1]["Setlist Pos"], "3")
        # c1 (before the anchor) brackets to pos < 3; c3 (after) to pos > 3.
        self.assertIn("Howl", rows[0]["Candidates"])
        self.assertNotIn("Sparrows", rows[0]["Candidates"])
        self.assertIn("Sparrows", rows[2]["Candidates"])
        self.assertNotIn("Howl", rows[2]["Candidates"])

    def test_typed_song_never_overwritten(self):
        rows = manifest_rows([("c1.mp4", 1, "got", "My Pick", "v1")])
        self.identify(rows, claims={"v1": {"title": "Howl", "artist": "",
                                           "start": ""}})
        self.assertEqual(rows[0]["Song"], "My Pick")
        self.assertEqual(rows[0]["Evidence"], "human")

    def test_reseed_discards_machine_keeps_human(self):
        rows = manifest_rows([
            ("c1.mp4", 1, "got", "Typed By Hand", "v1"),
            ("c2.mp4", 2, "got", "Machine Seed", "v2"),
        ])
        rows[1]["Evidence"] = "bracket:collapsed"
        self.identify(rows, reseed=True)
        self.assertEqual(rows[0]["Song"], "Typed By Hand")
        self.assertEqual(rows[1]["Song"], "")

    def test_incomplete_page_disables_bracketing(self):
        html = page(song_li("Howl") + song_li("The River"),
                    note="Setlist incomplete and out of order")
        rows = manifest_rows([
            ("c1.mp4", 1, "got", "", "v1"),
            ("c2.mp4", 2, "got", "", "v2"),
        ])
        lyrics = {"c1.mp4": {"status": "matched", "song": "Howl",
                             "hint": "", "source": ""}}
        self.identify(rows, lyrics=lyrics, html=html)
        # With bracketing, c2 would collapse to The River. Incomplete page
        # means it must stay an open pool instead.
        self.assertEqual(rows[1]["Song"], "")
        self.assertIn("The River", rows[1]["Candidates"])

    def test_cover_carried_to_cover_column(self):
        rows = manifest_rows([("c1.mp4", 1, "got", "", "v1")])
        self.identify(rows, claims={"v1": {"title": "Sparrows", "artist": "",
                                           "start": ""}})
        self.assertEqual(rows[0]["Cover"], "Big Joe Williams")

    def test_skip_rows_ignored(self):
        rows = manifest_rows([("c1.mp4", 1, "skip", "", "")])
        reports = self.identify(rows)
        self.assertEqual(reports, [])


# ── manifest split ─────────────────────────────────────────────────────────

class TestManifestSplit(unittest.TestCase):
    def test_round_trip(self):
        rows = manifest_rows([("c1.mp4", 1, "got", "Howl", "vidA")])
        rows[0]["Upload Status"] = "uploaded"
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "2026-08-08-test.tsv")
            yt_manifest.save(path, rows)
            self.assertTrue(os.path.exists(yt_manifest.machine_path(path)))

            with open(path, encoding="utf-8") as f:
                header = f.readline().rstrip("\n").split("\t")
            self.assertEqual(header, yt_manifest.LEAN_FIELDS)
            self.assertNotIn("Video ID", header)

            loaded = yt_manifest.load(path)
            self.assertEqual(loaded[0]["Video ID"], "vidA")
            self.assertEqual(loaded[0]["Upload Status"], "uploaded")
            self.assertEqual(loaded[0]["Song"], "Howl")

    def test_legacy_migration(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "2026-08-08-test.tsv")
            with open(path, "w", encoding="utf-8") as f:
                f.write("\t".join(yt_manifest.LEGACY_FIELDS) + "\n")
                values = {k: "" for k in yt_manifest.LEGACY_FIELDS}
                values.update({"Clip": "c1.mp4", "Capture Order": "1",
                               "Decision": "got", "Song": "Howl",
                               "Video ID": "vidA", "Upload Status": "uploaded"})
                f.write("\t".join(values[k] for k in yt_manifest.LEGACY_FIELDS) + "\n")

            loaded = yt_manifest.load(path)
            self.assertEqual(loaded[0]["Video ID"], "vidA")
            self.assertEqual(loaded[0]["Song"], "Howl")

            # The TSV is now lean, the sidecar exists, and a second load
            # returns the same merged rows.
            with open(path, encoding="utf-8") as f:
                header = f.readline().rstrip("\n").split("\t")
            self.assertEqual(header, yt_manifest.LEAN_FIELDS)
            again = yt_manifest.load(path)
            self.assertEqual(again[0]["Video ID"], "vidA")

    def test_sidecar_only_row_survives(self):
        # A clip whose lean row was hand-deleted still resurfaces from the
        # sidecar — it may hold the only record of an upload.
        rows = manifest_rows([("c1.mp4", 1, "got", "", "vidA"),
                              ("c2.mp4", 2, "got", "", "vidB")])
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "2026-08-08-test.tsv")
            yt_manifest.save(path, rows)
            with open(path, encoding="utf-8") as f:
                lines = f.readlines()
            with open(path, "w", encoding="utf-8") as f:
                f.writelines(lines[:2])          # drop c2's lean row
            loaded = yt_manifest.load(path)
            clips = [r["Clip"] for r in loaded]
            self.assertIn("c2.mp4", clips)
            c2 = next(r for r in loaded if r["Clip"] == "c2.mp4")
            self.assertEqual(c2["Video ID"], "vidB")


if __name__ == "__main__":
    unittest.main()
