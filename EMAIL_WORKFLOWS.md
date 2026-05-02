# Email Workflows — Live Show Archive

Five standing routines for processing emails from the **redhat.bootlegs@gmail.com** inbox.
None are automatic — you trigger each by starting a new conversation in this project
and telling me there's an email to process.

See `EMAIL_SETUP.md` for Gmail label setup, filter configuration, and mailing list
subscription management.

---

## Step 0 — Establish Current Date and Time MANDATORY

**This step runs before every routine invocation and before any analysis workflow.**

Call `time:get_current_time` (timezone: `America/New_York`) and record the result.
Use this date for:
- All date pruning decisions (is a show date in the past?)
- All activity log draft subjects (YYYY-MM-DD)
- All calendar availability checks
- Any "days until" or "days since" calculations

Never rely on the model's internal knowledge of the current date. The time MCP is
the sole authority on what day it is.

---

## Gmail Label System

Four labels are in use on the redhat.bootlegs inbox:

**`processed`** -- Applied manually by you after any email workflow completes. I always
include `-label:processed` in my search queries so previously handled emails are never
re-processed. At the end of each routine I will remind you to apply this label.

**`ticket-alert`** -- Applied manually (or via a Gmail filter) to incoming venue/artist
newsletter emails. Routine 3 searches `label:ticket-alert -label:processed`.
Seated alert emails also go here.

**`artist-mail`** -- Applied manually (or via Gmail filter) to emails from artist
newsletter subscriptions. Routine 4 searches `label:artist-mail -label:processed`.

**`artist-follow`** -- Applied automatically by Gmail filter (Bandsintown and Songkick
sender addresses) or manually for other sources. Routine 5 searches
`label:artist-follow -label:processed`.

**What I cannot do:** I can read labels and search by them, but I cannot apply, remove,
or create labels, mark emails as read, or create Gmail filters. All label management
is manual.

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

## Draft Activity Log

**The activity log draft is mandatory. It must be created at the end of every routine
invocation, without exception.**

At the end of every routine, I create a draft email in the redhat.bootlegs inbox
as a persistent log of what was processed and what actions were taken.

**Subject format:** `[LOG] Routine N -- [brief descriptor] -- YYYY-MM-DD`

**Draft body includes:**
- Which email(s) were processed (sender, subject, date)
- Every action taken: calendar events created or updated, TSV rows added,
  on-sale reminders created, recommendations made
- Any skipped items and why
- Any manual follow-up items

**One draft per routine invocation.** Draft creation is non-blocking -- if it fails,
the summary stays in conversation.

**Pure reminder emails (BIT/Songkick) require no log draft** -- see Routine 5.

**Searching the log:** Use `subject:[LOG]` in Gmail to find all log drafts.

---

## Calendar Availability Rule

**A date is unavailable if it has a timed show event OR an all-day `NO SHOWS` block.**

Always query the calendar for both timed and all-day events. Treat either as unavailable:
- A timed event (any show already booked)
- An all-day event titled **NO SHOWS**

**Never update calendar events for past shows.** Calendar edits only apply to upcoming
events -- past events are read-only.

**Prev/Next Show belongs in `live_shows_potential.tsv` only.** Do not include it in
calendar event descriptions or `live_shows_current.tsv` rows.

**Confirm before creating a calendar event for an unpurchased show.**

---

## Fast Track Protocol

**`fast_track.tsv`** is a curated list of artists who should be treated as immediate
buys when a local show surfaces -- skipping the potential list evaluation cycle entirely.

**Discipline:** Fast Track is strictly for artists who would NOT already be caught as
a strong buy based on show history. Artists with an established DC attendance history
must NOT be added here.

### Cap defaults

| Cap | Default | Narrower options |
|-----|---------|-----------------|
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

Look up the headliner in `autograph_books_combined.tsv`.

- If in **RHBS**: prepend `BRING RHBS -- [Artist] p.[N]` to the calendar event description
- If in **APS**: prepend `BRING APS -- [Artist] p.[N]`

**Step 4 -- Create calendar event**

Calendar: `redhat.bootlegs@gmail.com` -- Dan Concert Calendar

Event title format:
- Single electronic ticket, no other suffixes: `[Artist]` (omit the count)
- Multiple tickets or PAPER/VIP: `[Artist] (N)`, `[Artist] (N PAPER)`, `[Artist] (N VIP)`

Description format:
```
BRING RHBS -- [Artist] p.[N]          <- only if in autograph book

[Order # / Ref] ([Ticketer])
Ticket access: [method]
Payment: [card/method] / Face $X.XX / Fees $X.XX / Total $X.XX
[Supporting act line if applicable]
[Any special notes]

[Seat / GA info]
Doors: [time] / Show: [time]

High ticket cost -- cool it on merch tonight   <- face value >= $100, NOT VIP, NOT Wolf Trap Filene
```

Location field: use the **parking address** from `venues.tsv`, not the venue street address.

Reminders: 24 hours (1440 min) and 3 hours (180 min) popup.

**Merch caution rule:** face value per ticket >= $100, not VIP, not Wolf Trap Filene Center,
not evaluated on order total for multi-ticket orders.

**Step 5 -- Commit new row to `live_shows_current.tsv`**

Insert in date order, commit directly to `main`. Status = `upcoming`.
Apply sentinel `-` to col16 (Setlist URL) and col22 (Playlist URL) per write protocol above.

**Step 5b -- Update Prev/Next Show in `live_shows_potential.tsv`**

Scan every potential row and update brackets where the new show falls.

**Step 6 -- Remove from `live_shows_potential.tsv` if present**

Fetch fresh SHA, remove row, re-sort, commit.

**Step 7 -- Remove from `fast_track.tsv` if present**

A purchased ticket means the artist enters the history-based tier system.

**Step 8 -- Create activity log draft MANDATORY**

Subject: `[LOG] Routine 1 -- [Artist] ticket -- YYYY-MM-DD`

**Final step:** Remind you to apply the `processed` label.

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

**Step 3 -- Append row to `spending.tsv` MANDATORY**

Append one row:
```
Show Date | Artist | Ticket Cost | Food & Bev | Parking | Merch | Artist Interaction | Show Total | Notes
```
Commit directly to `main`.

**`spending.tsv` is the sole long-term authority for spending data.** The spending
columns in `live_shows_current.tsv` are a convenience scratch pad for the current year only.

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

**Step 7 -- Create activity log draft MANDATORY**

Subject: `[LOG] Routine 2 -- [Artist] post-show -- YYYY-MM-DD`

**Final step:** Remind you to apply the `processed` label.

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

**Case A -- Tickets already on sale:** Filter to Strong/Medium tier artists, check calendar,
present tiered recommendations with ticket links. No calendar event created.

**Case B -- Specific future on-sale time given:** Only Strong tier artists with confirmed
open date. Create an on-sale reminder calendar event (Step 4).

**IMP newsletter:** Also flag any The Atlantis show featuring a local DC artist as a
gift card opportunity.

**Non-Ticketmaster forwarded emails:** Surface the subscription management link so you
can re-target to redhat.bootlegs@gmail.com.

**Step 2 -- Check `live_shows_potential.tsv` and `fast_track.tsv`**

If already in potential list:
- Pass -> skip silently
- Buy -> remind Dan to complete purchase
- Choose -> present as normal recommendation

If new, check `fast_track.tsv` first (see Fast Track Protocol).

When adding a row: fetch fresh SHA, add row, re-sort (`Buy` -> `Choose` -> `Sell` -> `Pass`), commit.

**Date pruning:** Remove any row whose show date has passed per the date confirmed in Step 0.

**Step 3 -- Check autograph books**

Include book reminder in any recommendation or calendar event description.

**Step 4 -- Create on-sale reminder event (Case B only)**

Title: `ON SALE: [Artist]`
Timing: start 5 minutes before on-sale time, duration 15 minutes.
Reminders: 24 hours and 5 minutes.

```
[Ticket URL]
Pre-sale code: [CODE]    <- if present
```

**Step 5 -- Create activity log draft MANDATORY**

Subject: `[LOG] Routine 3 -- [source] -- YYYY-MM-DD`

**Final step:** Remind you to apply the `processed` label.

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

**Step 2 -- Classify and act on content**

- **Tour announcements / new shows:** calendar check, buy recommendation or on-sale event
- **Pre-sale codes:** on-sale calendar event with code in description
- **New music releases:** surface the info; no file action needed

**Step 3 -- Autograph book check**

For any DC/MD/VA show recommendation.

**Step 4 -- Create activity log draft MANDATORY**

Subject: `[LOG] Routine 4 -- [Artist] newsletter -- YYYY-MM-DD`

**Final step:** Remind you to apply the `processed` label.

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

**Step 2 -- Check `follows/follows_master.tsv`**

- Artist not present -> add a new row (present for approval first)
- Service not marked -> note discrepancy
- Direct Mail not Y for a signup -> set to Y and commit

**Step 3 -- Recommend follow coverage**

Surface any gaps in conversation. Do not automatically add to services -- confirm first.

**Step 4 -- Process any show content**

Check `fast_track.tsv` first, then handle as Routine 4 Step 2.

**Step 5 -- Create activity log draft MANDATORY**

Subject: `[LOG] Routine 5 -- [Artist] [source] -- YYYY-MM-DD`

No log draft for pure reminders.

**Final step:** Remind you to apply the `processed` label.

---

## Notes

**Inbox monitoring is not automatic.** Trigger routines by saying "there's a ticket
email", "I just sent my post-show notes", "process the inbox", etc.

**Hat autograph gdoc is the completeness authority.** If there is a discrepancy between
the gdoc and the TSV files, the gdoc wins for the list of signers; the TSV files win
for show dates.

**Google Calendar MCP fails on Android.** Switch to macOS desktop before retrying
calendar operations.

**YouTube pipeline is separate.** Tracked via GitHub issues (label: `playlist`).
Scripts run manually after videos are uploaded to YouTube Studio.
