# Bootleg upload — the operator flow

How a show actually gets from your phone to a titled, ordered playlist.

**Status:** all four stages are built — `--scan`, `--upload`, `--identify`,
`--apply` (with `--publish`). Credentials and the surrounding utility scripts are
covered in **HOWTO_CHANNEL.md**, next to this file.

---

## The shape of a night

```
export from Photos  →  scan  →  read the table  →  upload  →  (wait)
                                     ↑                            ↓
                                     └──── correct the manifest ← identify
                                                    ↓
                                             apply → playlist
```

The **manifest** carries state between every step, split into two files joined
on the clip name (issue #251):

- `tools/youtube/manifests/YYYY-MM-DD-artist-slug.tsv` — the **lean edit file**,
  the only file you touch: `Clip | Duration | Decision | Set Artist | Song |
  Desc Slug | Skip Reason`, plus two read-only aids (`Candidates`, `Lyric Hint`)
  that `--identify` maintains for you. `Duration` is read-only too — it's
  there because the Studio UI shows durations everywhere and clip filenames
  nowhere, so it's the fastest way to be sure which row is which video.
- `…-artist-slug.machine.json` — everything the tools own (durations, video
  IDs, upload status, confidence, positions). Never edit it; never delete it —
  it holds the video IDs that make an interrupted upload resumable.

A pre-split single-file manifest migrates automatically the first time any
stage reads it. Everything the tool guesses is a starting point you overwrite.

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

Open the lean manifest TSV. Every column is either yours (`Decision`,
`Set Artist`, `Song`, `Desc Slug`, `Skip Reason`) or a read-only aid
(`Duration`, `Candidates`, `Lyric Hint`) — the machine bookkeeping lives in
the JSON sidecar and stays out of your way.

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

## 6. Identify, correct, apply  *(built)*

```bash
python3 youtube_upload_show.py --identify
```

Run this **after** YouTube has finished its Content ID scan — minutes to hours after
upload, not immediately. It fetches and caches the setlist(s) — `MULTI:` shows
resolve every act via `data/setlists/<year>.json` — then works each act's clips:

- **Evidence files** (both optional, next to the manifest): a
  `.claims.tsv` holds Content-ID claim titles keyed by video ID (read them
  out of Studio for now; a claims reader is a planned follow-up), and a
  `.lyrics.tsv` records lyric-lookup outcomes as `matched` / `none` /
  `error` — only `none` (a lookup that SUCCEEDED and found nothing) flags a
  song as possibly unreleased; `error` asserts nothing.
- **Bracketing** constrains each remaining clip to the setlist songs between
  its confirmed neighbours, minus every song already confirmed anywhere. A
  pool that collapses to one candidate is seeded (marked `bracket:collapsed`
  — verify by ear); pools of a few land in the read-only `Candidates` column.
  A setlist page warning "incomplete and out of order" disables bracketing —
  the warning has proved accurate.
- It never overwrites a `Song` you typed, even with `--reseed`.

Then correct — either straight in the lean manifest, or in the browser:

```bash
python3 youtube_upload_show.py --edit
```

`--edit` serves the manifest as a page on localhost and opens it — meant to
sit in the tab next to Studio. Each keeper clip gets a dropdown of its Set
Artist's setlist songs in setlist order; a song picked on one clip vanishes
from every other clip's options, so duplicate titles are impossible by
construction. Rows link straight to their video's Studio edit page, show the
duration and thumbnail, and carry the `Candidates`/`Lyric Hint` aids. Free
text and the `unknown` sentinel are one click away. Save rewrites only the
lean TSV — the machine sidecar is never touched, nothing talks to YouTube,
and the page dies with the process. Run `--identify` first (even `--dry-run`)
so the setlists are cached; without a cached setlist an artist's rows
degrade to free-text entry.

Either way, write it back:

```bash
python3 youtube_upload_show.py --apply --dry-run
python3 youtube_upload_show.py --apply             # titles + descriptions, still private
python3 youtube_upload_show.py --apply --publish   # flip to public
```

Setting metadata and publishing are deliberately separate — there are nights
where the titles are right but you want another listen before anything goes
public.

**The publish guard:** `--publish` hard-refuses the WHOLE show — reporting
every offending clip and flipping nothing — while any title still contains
`#song-title` or the legacy `???` notation. An unfinished clip cannot escape,
and a partial publish cannot happen.

**The escape hatch:** a track that genuinely cannot be identified
(instrumental, non-English, rough audio even after processing) is marked by
typing `unknown` in its Song column. It publishes as
`ARTIST LIVE - Unknown Song #N (bootleg)` with a "can you name this song?"
ask in the description — the crowdsourcing pattern that eventually named the
Sona Jobarteh tracks — and it passes the guard, so one stubborn track never
holds the whole night back.

Clips whose `Set Artist` has no `@handle` in `artists.tsv` are flagged at
apply time and ship without a mention — hydrate `artists.tsv` later and
re-run `--apply` to add it.

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

---

## The invariants the pipeline guarantees

These rules used to live as the regression suite under `tools/youtube/tests/`; the
suite was removed (#270) once captured here in prose, because it was never wired into
CI and an untriggered suite silently rots. They are the hard-won, hard-to-re-derive
findings behind the song-ID work (#245 / #251), the publish guard (#252), and the
manifest split and linter (#251 / #247). **Preserve them** when touching `yt_songid.py`,
`yt_setlist.py`, `youtube_upload_show.py`, `yt_manifest.py`, `yt_edit.py`, or
`lint_manifest.py`.

### Song identification (the #245 / #251 findings — the most load-bearing)

- **Evidence order is fixed, and identity evidence outranks position.** Trust order:
  Content-ID claim → lyric match → setlist bracketing → the capture-order guess, which
  is last. Position is only ever a hint — sets get filmed out of order, and a matched
  lyric sets both the `Song` and its true `Setlist Pos` even when capture order says
  otherwise (the Family Crest show: capture order alone would have shipped ~4–5 wrong
  titles). Lyric and Content-ID evidence override the positional guess, never the
  reverse.
- **A claim binds to its clip by Video ID**, seeds the `Song` at high confidence, and
  resolves the setlist position. A claim naming a song the setlist page never listed is
  still seeded verbatim, marked "not on setlist" — a claim can be righter than the
  crowd-sourced setlist.
- **Foreign-evidence Songs must anchor a position, not merely be pool-excluded.** A
  `Song` carried in from a legacy manifest (Evidence like `Content-ID`), a claim, or a
  hand edit anchors bracketing exactly like a native identification. The Moss/McCalla
  regression was precisely this: such a Song was excluded from other clips' pools but
  never anchored a position, so every bracket spanned the whole setlist and every
  `Candidates` hint came out identical.
- **Bracketing is anchored and globally exclusive.** Each unconfirmed clip's candidate
  pool is the setlist songs strictly between its confirmed neighbours, minus every song
  confirmed anywhere in the set. A pool that collapses to exactly one song is seeded at
  *medium* confidence (`bracket:collapsed` — verify by ear); larger pools populate the
  read-only `Candidates` column.
- **An "incomplete / out of order" setlist page disables bracketing entirely.** Clips
  stay open pools rather than collapsing — the page's own warning has proved accurate,
  not stale, so position stops being usable at all.
- **Lyric absence is a signal; a lyric error is not.** A lyric lookup that SUCCEEDED and
  found nothing (`none`) flags the clip as possibly unreleased (`lyric-absence:unreleased?`).
  A lookup that FAILED (`error`) asserts nothing (`lyric-lookup:error`) — a failed lookup
  must never be read as "unreleased."
- **A human-typed `Song` is never overwritten** — not by a claim, not by anything — and
  its Evidence becomes `human`. `--reseed` discards only machine-seeded Songs (recognisable
  by their machine Evidence) and keeps every typed one.
- **Skip rows never participate** in identification.
- **The full setlist parenthetical seeds `Desc Slug` verbatim** (minus the outer parens):
  `(Big Joe Williams cover)` → `Big Joe Williams cover`, prepended to the description
  as-is. The tool never injects the word "cover" (or anything else) on its own — #269.
- **The setlist parser** skips ad rows, keeps "(Unknown)" placeholder rows (they hold a
  real position an unnamed clip may fill), attaches the most recent set-marker (`Encore:`,
  `Set 2:`, …) to each following song as its section, reads `(X cover)` into a cover
  attribution, and detects the page's incomplete/out-of-order warning. It is pinned to
  setlist.fm's `li.setlistParts.song` / `a.songLabel` / `span.unknownSong` / `infoPart` /
  `p.info` markup; a markup change breaks parsing loudly rather than silently.

### The publish guard (#252)

- **`--apply --publish` refuses the WHOLE show** — reporting every offending clip and
  flipping nothing — if any keeper's title still carries a `song-title` placeholder in
  *any* form (the current `#N-song-title`, the older `#song-title-N`, the bare legacy
  `#song-title`) or the legacy `???` notation. A partial publish cannot happen.
- **The `unknown` sentinel is publishable.** `unknown` / `Unknown` / `unknown song` / `?`
  in the `Song` column renders as `ARTIST LIVE - Unknown Song #N (bootleg)` with a "can you
  name this song?" ask in the description (the crowdsourcing pattern that eventually named
  the Sona Jobarteh tracks), and passes the guard — one stubborn track never holds the
  night hostage. A named song's description carries no such ask.
- **The guard ignores rows it shouldn't judge:** `skip` rows and not-yet-uploaded rows
  (blank Video ID) are never blockers, and only the offending clips are reported so a
  single bad row is easy to find among good ones.

### Manifest integrity (#251) and the linter (#247)

- **The manifest is a lean TSV + a machine JSON sidecar, joined on clip name.** The lean
  file holds only human columns (`Clip | Duration | Decision | Set Artist | Song |
  Desc Slug | Skip Reason`) plus the read-only aids (`Candidates`, `Lyric Hint`); the
  sidecar owns everything the tools write (Video IDs, upload status, confidence, positions,
  title/desc/privacy state). `save` writes both and never puts a Video ID in the lean
  header; `load` merges them back.
- **A pre-split single-file (legacy 20-column) manifest migrates in place** the first time
  any stage loads it: the TSV is rewritten lean, the sidecar is created, and a second load
  returns the same merged rows.
- **The sidecar is authoritative for uploads and must never be deleted.** A clip whose lean
  row was hand-deleted still resurfaces from the sidecar on load — it may hold the only
  record that the clip was uploaded (its Video ID). Remove a dead row deliberately, never
  by editing the TSV out from under the sidecar.
- **`Duration` lives in the lean file** (the Studio UI shows durations everywhere and clip
  filenames nowhere). A sidecar written before that move still supplies Duration on read,
  and the next save moves it lean-side.
- **The editor (`--edit`) only ever writes the human columns of known clips.** Saves leave
  the sidecar and its Video IDs untouched, reject an unknown clip as an error (never create
  a new row), reject a decision that isn't `got`/`skip`, and don't count unchanged rows.
- **The linter behind the playlist-issue CI refuses:** an unrecognised header; a duplicate
  `Clip`; a decision that isn't `got`/`skip`; unpublishable `Song` text (`???`,
  `#song-title-N`, `#N-song-title`); and two clips of the same Set Artist claiming the same
  `Setlist Pos`. It *warns* (not errors) on a legacy or pre-Duration header (still parsed), a
  `skip` row carrying a `Song`, and a Video ID on a skip row. It pads a short row (GitHub
  comments and the MCP strip trailing tabs) but flags a genuinely over-long/shifted row, and
  the `unknown` sentinel is never an error. Its scoreboard counts uploaded / applied /
  published against the keeper total and rewrites the issue body between its markers.
