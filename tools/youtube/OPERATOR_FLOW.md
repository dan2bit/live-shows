# Bootleg upload — the operator flow

How a show actually gets from your phone to a titled, ordered playlist.

**Status:** `--scan` and `--upload` are built. Step 6 below is the agreed design and
is marked accordingly — the CLI accepts those flags and stops with a "not implemented
yet" message, so nothing silently half-works.

---

## The shape of a night

```
export from Photos  →  scan  →  read the table  →  upload  →  (wait)
                                     ↑                            ↓
                                     └──── correct the manifest ← identify
                                                    ↓
                                             apply → playlist
```

One file carries state between every step: the **manifest**, at
`tools/youtube/manifests/YYYY-MM-DD-artist-slug.tsv`. It is a plain TSV. Open it in
whatever you like. Everything the tool guesses is a starting point you overwrite.

---

## 1. Export the clips  *(manual, unchanged)*

Google Photos → search `video YYYY-MM-DD` → download → unzip into a folder.

Don't pre-curate. Skip the "delete the short ones" pass — step 2 finds them, and
deleting by hand is the step this replaces. Do still rotate anything filmed sideways;
that's a visual call no script makes.

## 2. Scan  *(built)*

```bash
cd tools/youtube
source ../../.venv/bin/activate
python3 youtube_upload_show.py --clips ~/Downloads/pier6 --scan
```

**You don't pass a date.** The clips carry their own capture timestamps, so the scan
collects them and matches against your attended shows. It prints what it resolved:

```
Lake Street Dive — 2026-08-04 — Pier Six Pavilion
support: The Dip
(resolved from 10 clips; pass --show to override)
```

A set running past midnight still resolves, because only one of the two candidate
dates is a show. If it can't resolve or finds two shows, it stops and tells you
rather than guessing — `--show 2026-08-04` overrides. If you're already sitting in
the clip folder you can drop `--clips` too.

Reads every file locally. No network, no OAuth, nothing uploaded — safe to run
repeatedly. It needs `ffprobe` (`brew install ffmpeg`); without it durations fall back
to a file-size estimate and you lose the untrimmed-original check, but ordering and
fragment flags still work.

**Read the output before anything else.** Three things to check:

- **Segment count.** Should match the number of real breaks — support→headliner, a
  set change, an encore. If it's wrong, look at the ranked gap list at the bottom and
  re-run with `--min-gap-minutes 25` (or lower) to move the line. Cheap to redo.
- **The `[skip]` rows.** Anything ≤60s is pre-flagged as a false start. Glance at the
  durations; if a real short song got caught, you'll fix it in the manifest.
- **The integrity column.** `ok` means the file is an untrimmed original and its
  timestamps can be trusted. A `delta:Ns` means it was trimmed or re-encoded — that
  clip's ordering is suspect.

## 3. Fix the manifest  *(your pass)*

Open the manifest. Columns split into three kinds:

| Yours to edit | The tool's (rewritten each scan) | Filled later |
|---|---|---|
| `Decision`, `Song`, `Set Artist`, `Skip Reason`, `Cover` | `Clip`, `Capture Order`, `Capture Start`, `Duration`, `Size MB`, `Integrity`, `Set` | `Confidence`, `Evidence`, `Candidates`, `Lyric Hint`, `Setlist Pos`, `Video ID`, `Upload Status`, `Title Set` |

The edits worth making before uploading:

- **`Decision`** — `got` or `skip`. Flip any wrongly flagged fragment back to `got`.
- **`Set Artist`** — the tool guesses the opener played segment 1. That's right on a
  support night and wrong when *you* played two sets of the same artist (acoustic then
  full band). This drives the video title, so it matters.
- **`Song`** — optional here. Anything you already know saves a retitle later; the
  rest gets a placeholder and is fixed in step 6.

Re-running `--scan` after editing is safe: it refreshes only its own columns and never
touches a `Song` you typed. `--reseed` resets `Decision` and `Set Artist` back to
guesses — but still leaves `Song` alone.

## 4. Upload  *(built)*

```bash
python3 youtube_upload_show.py --upload --dry-run   # always first
python3 youtube_upload_show.py --upload
```

No date and no folder needed — the scan recorded both. Uploads every row marked `got`,
landing each video **private**, and writes its `Video ID` back to the manifest as it
goes.

**Resuming is automatic.** A blank `Video ID` is the entire work queue. Laptop sleeps,
network drops, you close the lid — re-run the same command and it picks up exactly
where it stopped. Same mechanism if you want to split a big night across two days:
just stop, and run it again later. A clip that fails outright is recorded as
`failed:upload` and stays in the queue; the rest of the run continues.

`--limit 1` uploads a single clip and stops, which is the right way to start on a
night you care about.

Quota is no longer the constraint it once was — Google cut `videos.insert` from ~1,600
units to ~100 in Dec 2025, so a 14-clip night fits comfortably where it used to blow
the daily cap at 6.

### What the titles look like

Every video gets the channel's one shape, whether or not the song is known:

```
Lake Street Dive LIVE - Good Kisser (bootleg)      ← Song filled in
Lake Street Dive LIVE - #song-title-7 (bootleg)    ← not yet identified
```

The date and venue are **not** in the title — they go in the description, matching
what the channel has done since 2023:

```
from Pier Six Pavilion (MD) on 08/04/26 @lakestreetdive
```

The numbered placeholder is deliberate: it's unique per clip and greppable, so an
un-replaced one is easy to find before it goes public. Bare `#song-title` has reached
the public channel more than once.

## 5. Studio pass  *(manual, unavoidable)*

Monetization on + Submit Rating, per video. No API surface exists for either — this
stays a Studio visit regardless of how much else gets automated.

## 6. Identify, correct, apply  *(designed, not built)*

```bash
python3 youtube_upload_show.py --identify
```

Run this **after** YouTube has finished its Content ID scan — minutes to hours after
upload, not immediately. It seeds `Song` with locked Content-ID matches, brackets the
rest to candidates from the setlist, and pulls opening-lyric hints. It never overwrites
a `Song` you typed.

Then correct by lyric or by ear, and write it back:

```bash
python3 youtube_upload_show.py --apply --dry-run
python3 youtube_upload_show.py --apply --publish
```

`--publish` will refuse to make a video public while its title still contains
`#song-title`, so an unfinished clip cannot escape.

**Trust order when the tool and your memory disagree:** Content ID beats everything,
then a lyric match, then the setlist, and the capture-order guess is last. Sets get
filmed out of order often enough that position is only ever a hint — on the TFC show it
would have shipped 4–5 wrong titles on its own.

## 7. Hand off to the playlist script  *(existing, unchanged)*

```bash
python3 youtube_fetch.py
python3 youtube_create_playlists.py --new-show 2026-08-04 --update-history
```

Nothing new here — this is the same script you already run. It gets easier once the
videos carry exact setlist titles, because its matching stops having to guess.

Then paste the playlist link into the playlist issue body and close it.

---

## When something goes sideways

**Wrong number of segments.** Ranked gap list at the bottom of the scan shows every
gap and which ones became boundaries. Re-run with `--min-gap-minutes`.

**"No show matches the clips' capture date(s)."** Either the show row doesn't exist
yet, or the folder holds clips from a different night. Add the row, or pass `--show`.

**A manifest row has no file.** Kept, not deleted, with a warning — because that row
may hold the `Video ID` proving the clip is already uploaded. Delete the row yourself
if it's genuinely dead.

**A clip failed to upload.** Its row reads `failed:upload` and it's still in the
queue, so re-running picks it up. Transient server errors retry automatically with
backoff; a permanent one (bad file, rejected metadata) needs a look.

**`invalid_grant` on upload.** Token is stale. `rm token.json`, re-run, and in the
browser pick the **@dan2bit brand channel** — not the gmail account, not
redhat.bootlegs. (Cloud project is administered as rhbl; consent is as the brand
channel. Mixing these up is the usual cause of an auth flow that succeeds but can't
see the channel.)

**Manifests showing up in `git status`.** They shouldn't — `tools/youtube/manifests/`
and `logs/*.tsv` are ignored. If they appear, they were staged before the ignore rule
existed; `git reset` unstages them without deleting anything. Keep the files: the
manifest holds the video IDs that let an interrupted upload resume.

**No setlist on the show row.** Not fatal. You still get correct ordering, fragment
flags, and set structure — a title-less skeleton you name by ear.
