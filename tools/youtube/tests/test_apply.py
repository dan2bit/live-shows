#!/usr/bin/env python3
"""
Tests for the --apply stage: the publish guard, the `unknown` crowdsourcing
sentinel, and the title/description builders they hang off (issue #252).

The guard's contract: a numbered `#song-title` placeholder or the legacy
`???` notation refuses the WHOLE publish; the deliberate `unknown` sentinel
renders as "Unknown Song #N", asks for help in the description, and passes.

Run from tools/youtube/:  python3 -m unittest discover tests
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import yt_manifest
from youtube_upload_show import (
    SONG_PLACEHOLDER,
    build_description,
    build_title,
    is_unknown_song,
    publish_blockers,
)


SHOW = {"date": "2026-08-08", "artist": "Anna Moss",
        "venue": "Jammin' Java", "support": "Sabine McCalla",
        "setlist_url": ""}


def row(clip="c1.mp4", order="3", decision="got", song="", video_id="vid1",
        artist="Sabine McCalla"):
    r = yt_manifest.blank_row()
    r.update({"Clip": clip, "Capture Order": order, "Decision": decision,
              "Song": song, "Video ID": video_id, "Set Artist": artist})
    return r


class TestUnknownSentinel(unittest.TestCase):
    def test_sentinel_variants_recognized(self):
        for value in ("unknown", "Unknown", "UNKNOWN", "unknown song", "?"):
            self.assertTrue(is_unknown_song(row(song=value)), value)
        for value in ("", "Louisiana Hound Dog", "Unknown Pleasures"):
            self.assertFalse(is_unknown_song(row(song=value)), value)

    def test_unknown_title_is_numbered_and_publishable(self):
        title = build_title(row(song="unknown", order="7"), SHOW)
        self.assertEqual(title,
                         "Sabine McCalla LIVE - Unknown Song #7 (bootleg)")
        self.assertNotIn(SONG_PLACEHOLDER, title)
        self.assertNotIn("???", title)

    def test_unknown_description_asks_for_help(self):
        desc = build_description(row(song="unknown"), SHOW)
        self.assertIn("name this song", desc)

    def test_named_description_does_not_ask(self):
        desc = build_description(row(song="Louisiana Hound Dog"), SHOW)
        self.assertNotIn("name this song", desc)

    def test_blank_song_still_gets_placeholder(self):
        title = build_title(row(song="", order="4"), SHOW)
        self.assertIn(f"{SONG_PLACEHOLDER}-4", title)


class TestPublishGuard(unittest.TestCase):
    def test_placeholder_blocks(self):
        rows = [row(clip="a.mp4", song="", video_id="v1")]
        blockers = publish_blockers(rows, SHOW)
        self.assertEqual(len(blockers), 1)
        self.assertEqual(blockers[0][0], "a.mp4")

    def test_legacy_question_marks_block(self):
        rows = [row(clip="a.mp4", song="??? maybe the ballad", video_id="v1")]
        self.assertEqual(len(publish_blockers(rows, SHOW)), 1)

    def test_unknown_sentinel_passes(self):
        rows = [row(clip="a.mp4", song="unknown", video_id="v1")]
        self.assertEqual(publish_blockers(rows, SHOW), [])

    def test_named_song_passes(self):
        rows = [row(clip="a.mp4", song="Two of Hearts", video_id="v1")]
        self.assertEqual(publish_blockers(rows, SHOW), [])

    def test_one_bad_row_reported_among_good(self):
        rows = [row(clip="a.mp4", song="Two of Hearts", video_id="v1"),
                row(clip="b.mp4", song="", video_id="v2"),
                row(clip="c.mp4", song="unknown", video_id="v3")]
        blockers = publish_blockers(rows, SHOW)
        self.assertEqual([b[0] for b in blockers], ["b.mp4"])

    def test_skip_and_not_uploaded_rows_ignored(self):
        rows = [row(clip="a.mp4", song="", decision="skip", video_id="v1"),
                row(clip="b.mp4", song="", video_id="")]
        self.assertEqual(publish_blockers(rows, SHOW), [])


if __name__ == "__main__":
    unittest.main()
