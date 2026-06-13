## Email Workflows — Live Show Archive

Five standing routines for processing emails from the **redhat.bootlegs@gmail.com** inbox.
None are automatic — you trigger each by starting a new conversation in this project
and telling me there's an email to process.

See `EMAIL_SETUP.md` for Gmail label setup, filter configuration, and mailing list
subscription management.

---

## Step 0 — Pre-Flight MANDATORY

**This step runs before every routine invocation, without exception. If any part
fails, stop immediately — do not proceed with email analysis.**

### 0a — Time calibration

Call `time:get_current_time` (timezone: `America/New_York`) and record the result.
Use this date for:
- All date pruning decisions (is a show date in the past?)
- All activity log draft subjects (YYYY-MM-DD)
- All calendar availability checks
- Any "days until" or "days since" calculations

Never rely on the model's internal knowledge of the current date. The time MCP is
the sole authority on what day it is.

### 0b — Fetch live context

Fetch both files from the repo and hold them in context for the full routine:

1. `live_shows_current.tsv` — extract all rows where Status = `upcoming`: artist, date, venue
2. `live_shows_potential.tsv` — extract all rows: artist, date, decision

**If `time:get_current_time` fails, or if either file fetch fails, stop immediately
and ask Dan to check MCP connectivity before retrying. Do not proceed.**

These two files are used to suppress duplicate recommendations (Step 0b cross-reference
in Routines 3, 4, and 5) and to drive date pruning (Routine 3).
---

## Gmail Label System

Four labels are in use on the redhat.bootlegs inbox:

**`processed`** -- Applied to emails after any email workflow completes, to prevent
re-processing. I always include `-label:processed` in my search queries.
**Applying `processed` requires explicit confirmation from Dan** — see Processed Label
Protocol below.

**`ticket-alert`** -- Applied manually (or via a Gmail filter) to incoming venue/artist
newsletter emails. Routine 3 searches `label:ticket-alert -label:processed`.
Seated alert emails also go here.

**`artist-mail`** -- Applied manually (or via Gmail filter) to emails from artist
newsletter subscriptions. Routine 4 searches `label:artist-mail -label:processed`.

**`artist-follow`** -- Applied automatically by Gmail filter (Bandsintown and Songkick
sender addresses) or manually for other sources. Routine 5 searches
`label:artist-follow -label:processed`.

**Label IDs:**
- `processed` = `Label_421272830174798850`
- `ticket-alert` = `Label_8111132848568068688`

**Search patterns used by each routine:**

| Routine | Search query |
|---------|-------------|
| 1 -- Ticket purchase | `from:dan2bit -label:processed` |
| 2 -- Post-show notes | `from:dan2bit -label:processed` |
| 3 -- On-sale alert | `label:ticket-alert -label:processed` |
| 4 -- Artist newsletter | `label:artist-mail -label:processed` |
| 5 -- Artist follow / signup | `label:artist-follow -label:processed` |

---

## Processed Label Protocol

**Applying `processed` always requires explicit confirmation from Dan — no exceptions.**

The sequence at the end of every routine invocation:

1. Complete all routine steps (TSV writes, calendar events, autograph checks, etc.)
2. Write the activity log draft
3. Present a summary of all threads to be labeled, by thread ID and subject
4. **Wait for Dan to confirm** before calling `label_thread` on any thread
5. Apply `processed` to all confirmed threads

Labeling does not need to be included in the activity log draft. The confirmation
request is the final step of every routine, after the draft is written.

**Never apply `processed` speculatively or as part of a batch without confirmation.**
Even if Dan says "process the inbox" or "run all routines", the label step still
requires a separate explicit go-ahead.

---

## Draft Activity Log

**The activity log draft is mandatory. It must be created at the end of every routine
invocation, without exception.**

At the end of every routine, I create a draft email in the redhat.bootlegs inbox
as a persistent log of what was processed and what actions were taken.

**Subject format:** `[LOG] Routine N — [brief descriptor] — YYYY-MM-DD`

Examples:
- `[LOG] Routine 1 — Gov't Mule ticket — 2026-06-03`
- `[LOG] Routine 2 — Vanessa Collier post-show — 2026-05-09`
- `[LOG] Routine 3 — Birchmere / Wolf Trap / Hub City newsletters — 2026-06-03`
- `[LOG] Routine 4 — Danielle Nicole / Galactic / Southern Avenue — 2026-06-03`
- `[LOG] Routine 5 — Kingsley Flood BIT alert — 2026-01-15`

**Searching the log:** Use `subject:[LOG]` in Gmail to find all log drafts.

**Draft body includes:**
- Which email(s) were processed (sender, subject, date)
- Every action taken: calendar events created or updated, TSV rows added,
  on-sale reminders created, recommendations made
- Any skipped items and why (including calendar conflicts)
- Any manual follow-up items

**One draft per routine invocation.** Draft creation is non-blocking -- if it fails,
the summary stays in conversation.

**Pure reminder emails (BIT/Songkick) require no log draft** -- see Routine 5.

---

## Calendar Availability Rule

**A date is unavailable if it has a timed show event OR an all-day `NO SHOWS` block.**
Always query the calendar for both before any recommendation or potentials write.

All calendar mechanics — event titles, descriptions, locations, reminders, the NO SHOWS
block spec, and the on-sale event format — live in **`CALENDAR_WORKFLOWS.md`**, which is the
authority on **how** every event is built. The routines below decide **when** an event is
created; see that file for **how**. Key carry-overs:

- **Never update calendar events for past shows** — edits apply to upcoming/same-day only.
- **Prev/Next Show belongs in `live_shows_potential.tsv` only** — never in calendar
  descriptions or `live_shows_current.tsv`.
- **Confirm before creating a calendar event for an unpurchased show.**

---

## Fast Track Protocol

**`fast_track.tsv`** is a curated list of artists who should be treated as immediate
buys when a local show surfaces -- skipping the potential list evaluation cycle entirely.

**Discipline:** Fast Track is strictly for artists who would NOT already be caught as
a strong buy based on show history. Artists with an established DC attendance history
must NOT be added here.

### Cap defaults

| Cap | Default | Narrower options |
|-----|---------|--------------------|
| Price Cap | $100 all-in | Any lower dollar amount |
| Distance Cap | Regional (DC/MD/VA + Baltimore, ~60 mi) | Local (DC/MD/VA only) / Extended (~90 mi) |
| Venue Cap | Mid (Small rooms + 9:30 Club, Wolf Trap Barns, State Theatre, ~500-1200 cap) | Small (Birchmere/Hamilton/Rams Head/Hub City tier only) / Large (adds Wolf Trap Filene, The Anthem) |

If **any cap is exceeded** -- surface as a **Choose** recommendation in
`live_shows_potential.tsv` instead, noting which cap was exceeded.

### When Fast Track applies

During Routine 3 (Step 2) and Routine 5 (Step 4):

1. Look up the artist in `fast_track.tsv`
2. Check all three caps against the show details
3. **All caps satisfied** -> present as **Fast Track buy**. No potential list row needed.
4. **Any cap exceeded** -> present as Choose recommendation, flagging which cap was exceeded

---

## live_shows_potential.tsv Write Protocol

**Always fetch a fresh SHA immediately before writing `live_shows_potential.tsv`.**

The sequence for every potential list write:
1. `get_file_contents` -> capture the current `sha` and content
2. Apply the change (add row, remove row, or re-sort)
3. Re-sort the full file: `Buy` -> `Choose` -> `Sell` -> `Pass`, date ascending within each group
4. Commit using `create_or_update_file` with the freshly fetched `sha`

### Prev/Next Show bracket rule

**Brackets are only calculated for Buy and Choose rows.** Sell and Pass rows always
have empty (`-`) Prev/Next columns. Brackets represent the surrounding purchased upcoming
shows to help evaluate density -- a show you're not attending has no need for this context.

When a Buy or Choose row is downgraded to Pass or Sell, clear its brackets at the same time.
When recalculating brackets after a new purchase (Routine 1 Step 5b), only update Buy and
Choose rows -- never populate brackets on Pass or Sell rows.

---

## live_shows_current.tsv Write Protocol

**Sentinel rule:** Every row must have exactly 25 columns. For upcoming rows, cols 16
(Setlist URL) and 22 (Playlist URL) must never be empty -- use `-` as a sentinel if
there is no real value. This prevents MCP trailing-tab stripping from collapsing columns
and shifting note content into the wrong column.

---

## artists.tsv Counting Policy

**Times Seen counts every appearance -- headliner and supporting act alike.**

**New Entry Rule -- support acts:** A supporting artist not yet in `artists.tsv` gets a
new row added **only when their second appearance is recorded.** One-off openers do not
get entries.

**First Seen / Most Recent Seen** use the same inclusive logic across all roles.

**History files are the source of truth.** Audit `history/*.tsv` and
`live_shows_current.tsv` together when in doubt.

---

## Routine 1 -- New Ticket Purchase Email

**Trigger:** A ticket confirmation forwarded from dan2bit@gmail.com arrives in the
redhat.bootlegs inbox.

### What I do

**Step 0 -- Get current date/time** via `time:get_current_time` (America/New_York).

**Step 1 -- Find and parse the email**

Search `from:dan2bit -label:processed`, identify the ticket confirmation, and extract:
artist, supporting act(s), show date/times, venue, seat info, ticket access method,
ticket quantity, face value, fees, total cost, purchase date, order numbers.

**Step 2 -- Apply venue defaults**

| Venue | Doors | Show | Notes |
|-------|-------|------|-------|
| The Birchmere | 5:00 PM | 7:30 PM | GA; seating begins 6:30 PM; always free parking |
| Hamilton Live | 6:30 PM | 8:00 PM | $13 parking |
| Rams Head On Stage | 1 hr before show | -- | -- |
| Wolf Trap Filene Center | -- | -- | Use ticket for times |

"An Evening With" billing means no supporting act. VIP tickets get `(VIP)` appended
to the calendar event title.

**Step 3 -- Check autograph books**

Look up the headliner and any known supporting acts in `autograph_books_combined.tsv`.

- If in **RHBS** and **not yet signed**: prepend `BRING RHBS -- [Artist] p.[N]` to the calendar event description
- If in **APS** and **not yet signed**: prepend `BRING APS -- [Artist] p.[N]`
- If already signed: no reminder needed

**Hat signing eligibility:** Female or female-presenting artists only, or bands with
female members. Before flagging a hat signer, verify gender via web search if not
already known. Also check `autograph_books_combined.tsv` to confirm she has not
already signed the hat.

**Venue likelihood for artist interaction:**
- **Yes (likely):** Pearl Street Warehouse, Hamilton Live, Collective Encore, Union Stage, Jammin' Java
- **Maybe (artist's choice):** 9:30 Club, The Birchmere
- **No (unlikely):** Wolf Trap Filene Center, The Anthem, Lincoln Theatre
if the venue is not on the prior list, include a question for Dan to confirm

**Step 4 -- Create calendar event**

Create the **show event** per **`CALENDAR_WORKFLOWS.md` → Event Type 1 — Show Events**.
Apply the autograph-book result from Step 3 to the description. In brief: title is `[Artist]`
(with `(N)`/`(N PAPER)`/`(N VIP)` suffix as applicable); Location is the **parking-lot
address from `venues.tsv`** for venues without on-site parking (feeds driving directions),
else the venue address; reminders 24 h + 3 h. Full title/description/location/merch-caution
rules are in the calendar file.

**Step 5 -- Commit new row to `live_shows_current.tsv`**

Insert in date order, commit directly to `main`. Status = `upcoming`.
Apply sentinel `-` to col16 (Setlist URL) and col22 (Playlist URL) per write protocol above.

**Step 5b -- Update Prev/Next Show in `live_shows_potential.tsv`**

Scan every **Buy and Choose** row and update brackets where the new show falls. Do not
populate or modify brackets on Pass or Sell rows (see bracket rule above).

**Step 6 -- Remove from `live_shows_potential.tsv` if present**

Fetch fresh SHA, remove row, re-sort, commit.

**Step 7 -- Remove from `fast_track.tsv` if present**

A purchased ticket means the artist enters the history-based tier system.

**Step 8 -- Create activity log draft MANDATORY**

Subject: `[LOG] Routine 1 — [Artist] ticket — YYYY-MM-DD`

**Final step:** Present thread IDs to be labeled `processed` and wait for Dan's
confirmation before applying any labels.

---

## Routine 2 -- Post-Show Notes Email

**Trigger:** You send/forward an email to redhat.bootlegs after attending a show,
including: spending amounts, setlist.fm URL, autograph note, show memories,
artist interaction type.

### What I do

**Step 0 -- Get current date/time** via `time:get_current_time` (America/New_York).

**Step 1 -- Find the matching email and show**

Search `from:dan2bit -label:processed`, find the matching calendar event and
`live_shows_current.tsv` row.

**Step 2 -- Update the calendar event**

Append spending and setlist info. Only for upcoming or same-day events -- never past shows.
See **`CALENDAR_WORKFLOWS.md` → Updating a show event**.

**Step 3 -- Append row to `spending.tsv` MANDATORY — DO NOT SKIP**

**Always fetch `spending.tsv` fresh from the repo immediately before appending.**
Do not rely on a locally cached copy — the file may have been updated since pre-flight.

Append one row:
```
Show Date | Artist | Ticket Cost | Food & Bev | Parking | Merch | Artist Interaction | Show Total | Notes
```
Commit directly to `main`. This step is required even if all spending amounts are zero.

**`spending.tsv` is the sole long-term authority for spending data.** The spending
columns in `live_shows_current.tsv` are a convenience scratch pad for the current year
only and are not guaranteed to be complete. A missing `spending.tsv` row cannot be
reconstructed from the activity log alone — it must be committed at the time of
show-notes processing. If this step is skipped for any reason, flag it explicitly
in the activity log draft and correct it before closing the routine.

**Step 4 -- Update autograph records (if applicable)**

If book autograph: update `autograph_books_combined.tsv` -- set RHBS/APS Signed to Yes.

If hat autograph:
1. Update `artists.tsv` -- set `Hat Autograph` to `Y`
2. Update `autograph_books_combined.tsv` -- add signer to Hat Notes
3. **Remind you to manually append to the hat autograph Google Doc**
   (https://docs.google.com/document/d/1haKMpfwPWosdPnZXBAAlLUzj3926hoTEH7icg6gTRA8/edit)
   Format: `**[Name]** [*of/w/ Act*] @ [Venue short name] [M/D/YY]`

**Step 5 -- Commit all file changes directly to `main`**

TSV files commit directly to `main` -- no PR needed. Commit all changed files together:
- `live_shows_current.tsv` -- status -> attended, spending, setlist, notes, interaction filled
- `artists.tsv` -- always included; apply counting policy
- `autograph_books_combined.tsv` -- if applicable

Commit message: `post-show: [Artist] [YYYY-MM-DD]`

**Step 6 -- Open a GitHub issue for YouTube playlist creation**

Title: `Playlist: [Artist] -- [YYYY-MM-DD] ([Venue short name])`
Label: `playlist`

Body includes show details, notes, and the playlist creation workflow. Skip if no footage.

**playlist creation workflow -- if only the videos have been uploaded and tagged**

1. Activate venv: `source .venv/bin/activate`
2. Dry run: `python3 youtube_create_playlists.py --new-show YYYY-MM-DD --dry-run`
3. Create: `python3 youtube_create_playlists.py --new-show YYYY-MM-DD --update-history`

**skip to here if playlist already created manually on the channel**
4. Add the playlist URL to this issue body: `Playlist: https://...`
5. Add the URL to `live_shows_current.tsv` col22 (Playlist URL) for YYYY-MM-DD or have Claude do it
6. Close this issue or have Claude do it


**Step 7 -- Create activity log draft MANDATORY**

Subject: `[LOG] Routine 2 — [Artist] post-show — YYYY-MM-DD`

**Final step:** Present thread IDs to be labeled `processed` and wait for Dan's
confirmation before applying any labels.

### artists.tsv update rules for Routine 2

**Headliner:** increment Times Seen, update Most Recent Seen. If VIP package: increment VIP Count.

**Supporting acts:**
1. Already in `artists.tsv` -> increment Times Seen, update Most Recent Seen
2. First time seeing them -> do not add a row yet; note in log
3. Second or subsequent time -> add row now with full history backfilled

---

## Routine 3 -- Pre-Sale / On-Sale Notification Email

**Trigger:** An on-sale alert, pre-sale announcement, or venue/artist newsletter
tagged `ticket-alert`.

### What I do

**Step 0 -- Get current date/time** via `time:get_current_time` (America/New_York).

**Step 1 -- Find and parse the email**

Search `label:ticket-alert -label:processed`. Classify each artist mention:

**Case A -- Tickets already on sale:** Filter to Strong/Medium tier artists, apply the
calendar conflict rule below, then present tiered recommendations with ticket links.
No calendar event created.

**Case B -- Specific future on-sale time given:** Only Strong tier artists with confirmed
open date. Apply the calendar conflict rule before creating an on-sale reminder (Step 4).

**Calendar conflict rule (applies before any recommendation or potentials write):**
For every show date surfaced, query the Dan Concert Calendar before making any
recommendation or writing any potential row:

- **Date has a timed show event already booked:** skip silently — conflict with existing purchase.
- **Date has an all-day `NO SHOWS` block:**
  - **Strong tier:** add a Pass row with `Watching For` = `[block description] calendar conflict [date range]`
    (e.g., `Beach Week calendar conflict Jul 25–Aug 1`). This suppresses future re-analysis
    when the same show keeps appearing in newsletters.
  - **Medium tier or lower:** skip silently — not worth tracking.
- **Date is open:** proceed with the recommendation as normal.

Never recommend a show, create an on-sale reminder, or write a potential row without
first confirming the date is open in the calendar.

**Songkick source note:** Songkick was acquired by Suno (AI music generation company)
in November 2025; all user data transferred to Suno in April 2026. During Routine 3
processing, if an artist show surfaces that appears **first or exclusively on Songkick**
(i.e., not yet visible on BIT, Seated, or the venue's own site), flag this in the
recommendation summary so Dan can decide whether to act on Songkick-sourced data.
Do not suppress the recommendation — just note the source provenance.

**IMP newsletter:** Also flag any The Atlantis show featuring a local DC artist as a
gift card opportunity.

**Non-Ticketmaster forwarded emails:** Surface the subscription management link so you
can re-target to redhat.bootlegs@gmail.com.

**Step 2 -- Cross-reference current shows and potentials**

Using the data fetched in Step 0b, for every artist/show surfaced in Step 1:

1. **Check `live_shows_current.tsv`:** if the artist already has an upcoming row,
   skip silently — the show is already purchased.

2. **Check `live_shows_potential.tsv`:**
   - Pass → skip silently
   - Buy → remind Dan to complete the purchase if not yet done
   - Choose → present as a normal recommendation
   - Not present → check `fast_track.tsv` first (see Fast Track Protocol)

**Confirmation required before any potentials write.** Present the full proposed set of
changes in conversation — new rows, row updates, and date-pruning removals — and wait
for explicit confirmation from Dan before committing anything to `live_shows_potential.tsv`.
Do not write speculatively.

**Date pruning:** Identify any row in `live_shows_potential.tsv` whose show date has
passed per the date confirmed in Step 0a, regardless of Decision. Include these removals
in the confirmation step above — do not remove silently.

After removing a past-dated row, for each removed artist check `artists.tsv` and
`new_artist_research.tsv`; if absent from both, add to `new_artist_research.tsv` with
tier and a note derived from the potentials row.

**Step 3 -- Check autograph books**

For any show recommendation, look up the artist in `autograph_books_combined.tsv`:
- If in RHBS or APS and **not yet signed**: note the bring reminder in the recommendation
- If already signed: omit the reminder

For hat signing: verify the artist is female or female-presenting (web search if
uncertain), and confirm not already signed before flagging as a hat signer.

Venue likelihood for autographs applies here too — factor into how prominently the
interaction angle is surfaced in the recommendation.

**Step 4 -- Create on-sale reminder event (Case B only)**

Create the **ticket purchase (on-sale) event** per
**`CALENDAR_WORKFLOWS.md` → Event Type 3**. In brief: title `ON SALE: [Artist]`; start
**exactly 5 minutes before the on-sale time**; description must carry a **deep-link purchase
URL** (resolve any redirect/tracking URL and confirm with Dan first), plus pre-sale code if
present; reminders 24 h + 5 min.

**Step 5 -- Create activity log draft MANDATORY**

Subject: `[LOG] Routine 3 — [source(s)] — YYYY-MM-DD`

**Final step:** Present thread IDs to be labeled `processed` and wait for Dan's
confirmation before applying any labels.

---

## Routine 4 -- Artist Newsletter Email

**Trigger:** An email from an artist mailing list tagged `artist-mail`.

### Subscribed artists

Canonical source: `Direct Mail` column in `follows/follows_master.tsv`.

Quick reference (as of 2026-04): Albert Castiglia, Allison Russell, Amythyst Kiah,
Buffalo Nichols, Bywater Call, Christone 'Kingfish' Ingram, Daniel Donato, Ghalia Volt,
Jackie Venson, Judith Hill, Larkin Poe, The Lone Bellow, Mike Zito, Robert Randolph,
Ruthie Foster, Samantha Fish, Shemekia Copeland, Southern Avenue, Sue Foley, Taj Farrant,
Tal Wilkenfeld, Trombone Shorty & Orleans Avenue, Vanessa Collier, The War and Treaty.

### What I do

**Step 0 -- Get current date/time** via `time:get_current_time` (America/New_York).

**Step 1 -- Find and read the emails**

Search `label:artist-mail -label:processed`.

Also check `in:promotions -label:processed` for unlabeled newsletters that bypassed
the filter -- requires manual action in Gmail to move to Primary and label.

**Step 1b -- Cross-reference current shows and potentials**

Using the data fetched in Step 0b, for any DC/MD/VA show date mentioned in the email:

1. **Check `live_shows_current.tsv`:** if the artist already has an upcoming row for
   this date, skip silently.

2. **Check `live_shows_potential.tsv`:**
   - Pass → skip silently
   - Buy → remind Dan to complete the purchase if on sale
   - Choose → surface as a reminder that it's pending a decision
   - Not present → proceed to Step 2

**Step 2 -- Classify and act on content**

For any DC/MD/VA show surfaced that is not suppressed by Step 1b, apply the
**calendar conflict rule** before making any recommendation or writing any potential row:

- **Date has a timed show event already booked:** skip silently.
- **Date has an all-day `NO SHOWS` block:**
  - **Strong tier:** add a Pass row with `Watching For` = `[block description] calendar conflict [date range]`.
  - **Medium tier or lower:** skip silently.
- **Date is open:** proceed with the recommendation.

Then classify and act:
- **Tour announcements / new shows:** buy recommendation or on-sale event (after conflict check above)
- **Pre-sale codes:** on-sale calendar event with code in description
- **New music releases:** surface the info; no file action needed

**Step 3 -- Autograph book check**

For any DC/MD/VA show recommendation.

**Step 4 -- Create activity log draft MANDATORY**

Subject: `[LOG] Routine 4 — [Artist(s)] newsletter — YYYY-MM-DD`

**Final step:** Present thread IDs to be labeled `processed` and wait for Dan's
confirmation before applying any labels.

---

## Routine 5 -- Artist Follow / Signup Email

**Trigger:** An email tagged `artist-follow` -- either a BIT/Songkick show alert,
or a direct signup response from an artist mailing list.

### Reminder suppression rule

**If the show is already in `live_shows_current.tsv` or `live_shows_potential.tsv`,
this is a reminder -- skip entirely.** No log draft needed for pure reminders.

### What I do

**Step 0 -- Get current date/time** via `time:get_current_time` (America/New_York).

**Step 1 -- Find and read the emails**

Search `label:artist-follow -label:processed`. Apply reminder suppression before proceeding.

**BIT "Just Announced" emails require full HTML body parsing.**
The subject line `Just Announced: [Artist] in [City]` signals a potentially actionable new show.
The plain-text snippet is truncated — the full HTML body contains:
- Show date (look for a `<p>` near a calendar icon image)
- Venue (look for a `<p>` near a location pin image)
- Get Tickets / Buy link (encoded as `=3D` in quoted-printable; decode before using)
- the buy link will be masked for email tracking, but will resolve/redirect correctly for
    the relevant venue ticketing service if presented in conversation

When processing a Just Announced thread: always fetch the full thread body, extract
date, venue and purchase link, surface all 3 in conversation before any potentials write.
Flag for potential Fast Track or Strong tier check before adding to potentials.

**Step 2 -- Check `follows/follows_master.tsv`**

- Artist not present -> add a new row (present for approval first)
- Service not marked -> note discrepancy
- Direct Mail not Y for a signup -> set to Y and commit

**Step 3 -- Recommend follow coverage**

Surface any gaps in conversation. Do not automatically add to services -- confirm first.

**Step 4 -- Process any show content**

Apply the **calendar conflict rule** (same as Routine 3 Step 1) before any recommendation
or potentials write. Then check `fast_track.tsv` first, and handle as Routine 4 Step 2.

**Step 5 -- Create activity log draft MANDATORY**

Subject: `[LOG] Routine 5 — [Artist] [source] — YYYY-MM-DD`

No log draft for pure reminders.

**Final step:** Present thread IDs to be labeled `processed` and wait for Dan's
confirmation before applying any labels.

---

## Notes

**Inbox monitoring is not automatic.** Trigger routines by saying "there's a ticket
email", "I just sent my post-show notes", "process the inbox", etc.

**Hat autograph gdoc is the completeness authority.** If there is a discrepancy between
the gdoc and the TSV files, the gdoc wins for the list of signers; the TSV files win
for show dates.

**Google Calendar MCP fails on Android.** Switch to macOS desktop before retrying
calendar operations.

**Songkick ownership note:** Songkick was acquired by Suno (AI music generation) in
November 2025 as part of a WMG copyright settlement. All Songkick user data transferred
to Suno in April 2026. Dan has chosen not to expand Songkick follows or delete the
account (data can age). New artists are followed on BIT and Seated only. See
`follows/follows_master.tsv` Songkick column for current coverage.

**YouTube pipeline is separate.** Tracked via GitHub issues (label: `playlist`).
Scripts run manually after videos are uploaded to YouTube Studio.
