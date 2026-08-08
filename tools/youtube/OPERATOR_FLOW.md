# Bootleg upload — the operator flow

How a show actually gets from your phone to a titled, ordered playlist.

**Status:** only `--scan` is built today. Steps 4 and 6 below are the agreed design and
are marked accordingly — the CLI accepts those flags and stops with a "not implemented
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
python3 youtube_upload_show.py --show 2026-08-04 --clips ~/Downloads/pier6 --scan
```

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

Right now the useful edits are:

- **`Decision`** — `got` or `skip`. Flip any wrongly flagged fragment back to `got`.
- **`Set Artist`** — the tool guesses the opener played segment 1. That's right on a
  support night and wrong when *you* played two sets of the same artist (acoustic then
  full band). This drives the video title, so it matters.

Re-running `--scan` after editing is safe: it refreshes only its own columns and never
touches a `Song` you typed. `--reseed` resets `Decision` and `Set Artist` back to
guesses — but still leaves `Song` alone.

## 4. Upload  *(designed, not built)*

```bash
python3 youtube_upload_show.py --show 2026-08-04 --upload --dry-run   # always first
python3 youtube_upload_show.py --show 2026-08-04 --upload
```

Uploads every row marked `got`, resumable, landing **private**. Writes each `Video ID`
back to the manifest as it goes.

**Resuming is automatic.** A blank `Video ID` is the entire work queue. Laptop sleeps,
network drops, you get bored and close the lid — re-run the same command and it picks
up exactly where it stopped. Same mechanism if you want to split a big night across
two days: just stop, and run it again later.

Quota is no longer the constraint it was — Google cut `videos.insert` from ~1,600 units
to ~100 in Dec 2025, so a 14-clip night fits comfortably where it used to blow the
daily cap at 6.

## 5. Studio pass  *(manual, unavoidable)*

Monetization on + Submit Rating, per video. No API surface exists for either — this
stays a Studio visit regardless of how much else gets automated.

## 6. Identify, correct, apply  *(designed, not built)*

```bash
python3 youtube_upload_show.py --show 2026-08-04 --identify
```

Run this **after** YouTube has finished its Content ID scan — minutes to hours after
upload, not immediately. It seeds `Song` with locked Content-ID matches, brackets the
rest to candidates from the setlist, and pulls opening-lyric hints. It never overwrites
a `Song` you typed.

Then correct by lyric or by ear, and write it back:

```bash
python3 youtube_upload_show.py --show 2026-08-04 --apply --dry-run
python3 youtube_upload_show.py --show 2026-08-04 --apply --publish
```

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

**A manifest row has no file.** Kept, not deleted, with a warning — because that row
may hold the `Video ID` proving the clip is already uploaded. Delete the row yourself
if it's genuinely dead.

**`invalid_grant` on upload.** Token is stale. `rm token.json`, re-run, and in the
browser pick the **@dan2bit brand channel** — not the gmail account, not
redhat.bootlegs. (Cloud project is administered as rhbl; consent is as the brand
channel. Mixing these up is the usual cause of an auth flow that succeeds but can't
see the channel.)

**No setlist on the show row.** Not fatal. You still get correct ordering, fragment
flags, and set structure — a title-less skeleton you name by ear.
