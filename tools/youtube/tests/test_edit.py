#!/usr/bin/env python3
"""
Tests for the manifest editor (yt_edit) and the Duration promotion.

The editor's contract: saves touch only the human columns of known clips;
the machine sidecar and its Video IDs survive every edit. Duration's
contract: it lives in the lean file now, and a sidecar written before the
move still supplies it on read.

Run from tools/youtube/:  python3 -m unittest discover tests
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import yt_edit
import yt_manifest
from yt_setlist import parse_setlist


def make_rows():
    rows = []
    for clip, order, dur, artist, song, vid in [
            ("a.mp4", "1", "4:02", "Anna Moss", "", "v1"),
            ("b.mp4", "2", "5:28", "Anna Moss", "Penis Envy", "v2"),
            ("c.mp4", "3", "3:20", "Sabine McCalla", "", "v3")]:
        r = yt_manifest.blank_row()
        r.update({"Clip": clip, "Capture Order": order, "Duration": dur,
                  "Decision": "got", "Set Artist": artist, "Song": song,
                  "Video ID": vid, "Upload Status": "uploaded"})
        rows.append(r)
    return rows


SHOW = {"artist": "Anna Moss", "support": "Sabine McCalla",
        "date": "2026-08-08", "venue": "Jammin' Java", "setlist_url": ""}


def song_li(title, info=""):
    info_html = f'<small class="fontSmall">{info}</small>' if info else \
                '<small class="fontSmall"></small>'
    return (f'<li class="setlistParts song"><div class="songPart">'
            f'<a class="songLabel">{title}</a></div>'
            f'<div class="infoPart">{info_html}</div></li>')


SETLIST_HTML = ('<html><body><div class="setlistList"><ol class="songsList">'
                + song_li("Two of Hearts")
                + song_li("Save My Soul")
                + song_li("Sparrows", '(<a>Big Joe Williams</a> cover)')
                + '</ol></div></body></html>')


def setlists():
    sl, _ = parse_setlist(SETLIST_HTML, "Sabine McCalla", "test://x")
    return {"Sabine McCalla": sl}


class TestDurationPromotion(unittest.TestCase):
    def test_duration_written_lean_not_machine(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "t.tsv")
            yt_manifest.save(path, make_rows())

            with open(path, encoding="utf-8") as f:
                header = f.readline().rstrip("\n").split("\t")
            self.assertIn("Duration", header)
            self.assertEqual(header, yt_manifest.LEAN_FIELDS)

            with open(yt_manifest.machine_path(path), encoding="utf-8") as f:
                sidecar = json.load(f)
            self.assertNotIn("Duration", sidecar["clips"]["a.mp4"])

            loaded = yt_manifest.load(path)
            self.assertEqual(loaded[0]["Duration"], "4:02")

    def test_old_sidecar_still_supplies_duration(self):
        # A manifest split before the move: lean v1 (no Duration column),
        # sidecar carrying Duration. Load must recover it; the next save
        # moves it lean-side.
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "t.tsv")
            with open(path, "w", encoding="utf-8") as f:
                f.write("\t".join(yt_manifest.LEAN_FIELDS_V1) + "\n")
                f.write("a.mp4\tgot\tAnna Moss\t\t\t\t\t\n")
            with open(yt_manifest.machine_path(path), "w",
                      encoding="utf-8") as f:
                json.dump({"clips": {"a.mp4": {"Duration": "4:02",
                                               "Video ID": "v1"}}}, f)

            loaded = yt_manifest.load(path)
            self.assertEqual(loaded[0]["Duration"], "4:02")
            self.assertEqual(loaded[0]["Video ID"], "v1")

            yt_manifest.save(path, loaded)
            with open(path, encoding="utf-8") as f:
                header = f.readline().rstrip("\n").split("\t")
            self.assertEqual(header, yt_manifest.LEAN_FIELDS)
            again = yt_manifest.load(path)
            self.assertEqual(again[0]["Duration"], "4:02")


class TestState(unittest.TestCase):
    def test_state_shape(self):
        state = yt_edit.build_state(make_rows(), setlists(), SHOW)
        self.assertEqual([r["clip"] for r in state["rows"]],
                         ["a.mp4", "b.mp4", "c.mp4"])
        self.assertEqual(state["rows"][0]["duration"], "4:02")
        self.assertEqual(state["rows"][0]["videoId"], "v1")
        self.assertEqual(state["artists"], ["Anna Moss", "Sabine McCalla"])
        sl = state["setlists"]["Sabine McCalla"]
        self.assertEqual(sl["songs"][2]["cover"], "Big Joe Williams")

    def test_render_page_embeds_state_and_token(self):
        page = yt_edit.render_page(
            yt_edit.build_state(make_rows(), setlists(), SHOW), "tok123")
        self.assertIn("tok123", page)
        self.assertIn("Save My Soul", page)
        self.assertIn("a.mp4", page)


class TestApplyEdits(unittest.TestCase):
    def test_human_fields_updated_machine_untouched(self):
        rows = make_rows()
        changed, errors = yt_edit.apply_edits(rows, [
            {"clip": "a.mp4", "song": "Two of Hearts",
             "decision": "got", "setArtist": "Anna Moss",
             "cover": "", "skipReason": ""}])
        self.assertEqual(errors, [])
        self.assertEqual(changed, 1)
        self.assertEqual(rows[0]["Song"], "Two of Hearts")
        self.assertEqual(rows[0]["Video ID"], "v1")   # untouched

    def test_unknown_clip_is_error_not_new_row(self):
        rows = make_rows()
        changed, errors = yt_edit.apply_edits(rows, [{"clip": "zz.mp4",
                                                      "song": "X"}])
        self.assertEqual(changed, 0)
        self.assertTrue(any("unknown clip" in e for e in errors))
        self.assertEqual(len(rows), 3)

    def test_bad_decision_rejected(self):
        rows = make_rows()
        _, errors = yt_edit.apply_edits(rows, [{"clip": "a.mp4",
                                                "decision": "keep"}])
        self.assertTrue(any("not got/skip" in e for e in errors))
        self.assertEqual(rows[0]["Decision"], "got")

    def test_unchanged_rows_not_counted(self):
        rows = make_rows()
        changed, errors = yt_edit.apply_edits(rows, [
            {"clip": "b.mp4", "song": "Penis Envy", "decision": "got",
             "setArtist": "Anna Moss", "cover": "", "skipReason": ""}])
        self.assertEqual((changed, errors), (0, []))

    def test_save_round_trip_preserves_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "t.tsv")
            yt_manifest.save(path, make_rows())

            rows = yt_manifest.load(path)
            yt_edit.apply_edits(rows, [{"clip": "c.mp4",
                                        "song": "Save My Soul"}])
            yt_manifest.save(path, rows)

            loaded = yt_manifest.load(path)
            c = next(r for r in loaded if r["Clip"] == "c.mp4")
            self.assertEqual(c["Song"], "Save My Soul")
            self.assertEqual(c["Video ID"], "v3")
            self.assertEqual(c["Upload Status"], "uploaded")


if __name__ == "__main__":
    unittest.main()
