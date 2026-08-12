#!/usr/bin/env python3
"""
Tests for the manifest linter behind the playlist-issue CI (issue #247).

The exit criterion from the issue: a deliberately corrupted manifest is
caught with a useful reply, and the scoreboard reflects real progress.

Run from tools/youtube/:  python3 -m unittest discover tests
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import lint_manifest
from yt_manifest import LEAN_FIELDS, LEGACY_FIELDS


def tsv(rows):
    lines = ["\t".join(LEAN_FIELDS)]
    for spec in rows:
        record = {f: "" for f in LEAN_FIELDS}
        record.update(spec)
        lines.append("\t".join(record[f] for f in LEAN_FIELDS))
    return "\n".join(lines)


def run_lint(text, machine=None):
    header, rows = lint_manifest.parse_tsv(text)
    return lint_manifest.lint(header, rows, machine or {})


GOOD = tsv([
    {"Clip": "a.mp4", "Decision": "got", "Set Artist": "X", "Song": "One"},
    {"Clip": "b.mp4", "Decision": "got", "Set Artist": "X", "Song": "unknown"},
    {"Clip": "c.mp4", "Decision": "got", "Set Artist": "X"},
    {"Clip": "d.mp4", "Decision": "skip", "Set Artist": "X",
     "Skip Reason": "fragment:12s"},
])


class TestExtraction(unittest.TestCase):
    def test_fenced_blocks(self):
        body = ("preamble\n```manifest\n" + GOOD + "\n```\nmiddle\n"
                '```machine\n{"clips": {"a.mp4": {"Video ID": "v1"}}}\n```\n')
        manifest, machine = lint_manifest.extract_blocks(body)
        self.assertIn("a.mp4", manifest)
        clips, err = lint_manifest.parse_machine(machine)
        self.assertIsNone(err)
        self.assertEqual(clips["a.mp4"]["Video ID"], "v1")

    def test_no_block(self):
        self.assertEqual(lint_manifest.extract_blocks("just words"),
                         (None, None))


class TestLint(unittest.TestCase):
    def test_clean_manifest(self):
        errors, warnings, stats = run_lint(GOOD)
        self.assertEqual(errors, [])
        self.assertEqual(stats["clips"], 4)
        self.assertEqual(stats["keepers"], 3)
        self.assertEqual(stats["named"], 1)
        self.assertEqual(stats["unknown_marked"], 1)
        self.assertEqual(stats["titles_pending"], 1)

    def test_short_row_padded_not_flagged(self):
        # GitHub comments and the MCP strip trailing tabs; a short row is
        # padded, matching the parseTsv() precedent in index.html.
        text = "\t".join(LEAN_FIELDS) + "\na.mp4\t3:00\tgot\tX\n"
        errors, _, stats = run_lint(text)
        self.assertEqual(errors, [])
        self.assertEqual(stats["keepers"], 1)

    def test_overlong_row_flagged(self):
        text = ("\t".join(LEAN_FIELDS)
                + "\na.mp4\t3:00\tgot\tX\tSong\t\t\t\t\textra\n")
        errors, _, _ = run_lint(text)
        self.assertTrue(any("shifted row" in e for e in errors))

    def test_v1_lean_header_accepted_with_note(self):
        from yt_manifest import LEAN_FIELDS_V1
        text = ("\t".join(LEAN_FIELDS_V1)
                + "\na.mp4\tgot\tX\tOne\n")
        errors, warnings, stats = run_lint(text)
        self.assertEqual(errors, [])
        self.assertTrue(any("pre-Duration" in w for w in warnings))
        self.assertEqual(stats["named"], 1)

    def test_bad_decision(self):
        errors, _, _ = run_lint(tsv([{"Clip": "a.mp4", "Decision": "keep"}]))
        self.assertTrue(any("`keep`" in e for e in errors))

    def test_duplicate_clip(self):
        errors, _, _ = run_lint(tsv([{"Clip": "a.mp4", "Decision": "got"},
                                     {"Clip": "a.mp4", "Decision": "got"}]))
        self.assertTrue(any("duplicate Clip" in e for e in errors))

    def test_unpublishable_song_text(self):
        for song in ("???", "#song-title-3", "#3-song-title"):
            errors, _, _ = run_lint(tsv([{"Clip": "a.mp4", "Decision": "got",
                                          "Song": song}]))
            self.assertTrue(any("unpublishable" in e for e in errors), song)

    def test_unknown_sentinel_is_not_an_error(self):
        errors, _, _ = run_lint(tsv([{"Clip": "a.mp4", "Decision": "got",
                                      "Song": "unknown"}]))
        self.assertEqual(errors, [])

    def test_skip_with_song_warns(self):
        _, warnings, _ = run_lint(tsv([{"Clip": "a.mp4", "Decision": "skip",
                                        "Song": "One"}]))
        self.assertTrue(any("skip row carries a Song" in w for w in warnings))

    def test_unrecognized_header(self):
        errors, _, _ = run_lint("Foo\tBar\nx\ty\n")
        self.assertTrue(any("unrecognized header" in e for e in errors))

    def test_legacy_header_warns_not_errors(self):
        text = "\t".join(LEGACY_FIELDS) + "\n" + "\t".join(
            ["a.mp4", "1", "", "3:00", "100", "ok", "seg1", "X",
             "got", "", "One", "", "", "", "", "", "", "v1", "uploaded", ""])
        errors, warnings, stats = run_lint(text)
        self.assertEqual(errors, [])
        self.assertTrue(any("legacy" in w for w in warnings))
        self.assertEqual(stats["keepers"], 1)

    def test_duplicate_setlist_pos_same_artist(self):
        machine = {"a.mp4": {"Setlist Pos": "3"},
                   "b.mp4": {"Setlist Pos": "3"}}
        errors, _, _ = run_lint(tsv([
            {"Clip": "a.mp4", "Decision": "got", "Set Artist": "X",
             "Song": "One"},
            {"Clip": "b.mp4", "Decision": "got", "Set Artist": "X",
             "Song": "Two"},
        ]), machine)
        self.assertTrue(any("Setlist Pos 3" in e for e in errors))

    def test_video_id_on_skip_row_warns(self):
        machine = {"a.mp4": {"Video ID": "v1"}}
        _, warnings, _ = run_lint(tsv([{"Clip": "a.mp4",
                                        "Decision": "skip"}]), machine)
        self.assertTrue(any("Video ID" in w for w in warnings))


class TestScoreboard(unittest.TestCase):
    MACHINE = {
        "a.mp4": {"Video ID": "v1", "Title Set": "t", "Desc Set": "d",
                  "Privacy": "public"},
        "b.mp4": {"Video ID": "v2"},
        "c.mp4": {},
    }

    def test_progress_counts(self):
        _, _, stats = run_lint(GOOD, self.MACHINE)
        self.assertEqual(stats["uploaded"], 2)
        self.assertEqual(stats["applied"], 1)
        self.assertEqual(stats["published"], 1)
        board = lint_manifest.render_scoreboard(stats)
        self.assertIn("uploaded — 2 of 3", board)
        self.assertIn("published — 1 of 3", board)

    def test_body_update_replaces_between_markers(self):
        _, _, stats = run_lint(GOOD, self.MACHINE)
        board = lint_manifest.render_scoreboard(stats)
        body = "intro\n\n" + board.replace("2 of 3", "0 of 3") + "\n\nfooter"
        updated = lint_manifest.update_body(body, board)
        self.assertIn("2 of 3", updated)
        self.assertNotIn("0 of 3", updated)
        self.assertIn("intro", updated)
        self.assertIn("footer", updated)
        self.assertEqual(updated.count(lint_manifest.SCOREBOARD_START), 1)

    def test_body_update_appends_when_absent(self):
        board = "scoreboard"
        updated = lint_manifest.update_body(
            "plain body",
            lint_manifest.SCOREBOARD_START + "\nX\n"
            + lint_manifest.SCOREBOARD_END)
        self.assertIn("plain body", updated)
        self.assertIn(lint_manifest.SCOREBOARD_START, updated)


if __name__ == "__main__":
    unittest.main()
