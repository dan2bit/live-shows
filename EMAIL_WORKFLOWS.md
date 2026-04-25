# Email Workflows — Live Show Archive

Four standing routines for processing emails from the **redhat.bootlegs@gmail.com** inbox.
None are automatic — you trigger each by starting a new conversation in this project
and telling me there's an email to process.

**Pre-requisite:** Subscribe redhat.bootlegs@gmail.com to venue and artist mailing lists
so that on-sale alerts, pre-sale codes, and newsletters arrive there directly. See the
list of suggested subscriptions at the bottom of this file.

---

## Gmail Label System

Four labels are in use on the redhat.bootlegs inbox:

**`processed`** — Applied manually by you after any email workflow completes. I always
include `-label:processed` in my search queries so previously handled emails are never
re-processed. At the end of each routine I will remind you to apply this label to the
email(s) that were processed.

**`ticket-alert`** — Applied manually (or via a Gmail filter) to incoming venue/artist
newsletter emails once mailing list subscriptions are in place. Routine 3 searches
`label:ticket-alert -label:processed` to find unprocessed on-sale alerts. **Seated**
alert emails also go here — Seated sends ticket-sale-style notifications and is treated
as a venue/service newsletter source, not a follow-relationship source.

**`artist-mail`** — Applied manually (or via Gmail filter) to emails from artist
newsletter subscriptions. Routine 4 searches `label:artist-mail -label:processed`
to find unprocessed artist mail. The primary things to mine are: tour announcements,
artist pre-sale codes, and new music releases.

**`artist-follow`** — Applied automatically by Gmail filter (for Bandsintown and
Songkick sender addresses) or manually for other sources. Covers service notifications
about followed artists and direct mailing list signup responses. Routine 5 searches
`label:artist-follow -label:processed`.

- **Bandsintown** and **Songkick** emails are auto-labeled `artist-follow` via Gmail
  filter rules on their sender addresses. No manual labeling needed.
- **Seated** emails go to `ticket-alert` (not `artist-follow`) — Seated sends
  ticket-sale-style alerts that fit the Routine 3 model.
- Direct mailing list signup welcome emails and confirmations: label manually as
  `artist-follow`.

**What I cannot do:** I can read labels and search by them, but I cannot apply, remove,
or create labels, mark emails as read, or create Gmail filters. All label management
is manual. I can compose draft emails but cannot send them — sending is always manual.

**Search patterns used by each routine:**

| Routine | Search query |
|---------|-------------|
| 1 — Ticket purchase | `from:dan2bit subject:[artist] -label:processed` (forwarded confirmation) |
| 2 — Post-show notes | `from:dan2bit subject:[artist] notes -label:processed` |
| 3 — On-sale alert | `label:ticket-alert -label:processed` |
| 4 — Artist newsletter | `label:artist-mail -label:processed` |
| 5 — Artist follow / signup | `label:artist-follow -label:processed` |

---

## Draft Activity Log

**The activity log draft is mandatory. It must be created at the end of every routine
invocation, without exception. It is never optional, never skippable, and must not be
omitted even when a routine is simple, quick, or partially overlaps with another routine
run in the same session. If the draft creation fails, note the failure in conversation
and include the full log text so it is preserved there.**

At the end of every routine, I create a draft email in the redhat.bootlegs inbox
as a persistent log of what was processed and what actions were taken. This gives
you a searchable history in Gmail alongside the source emails.

**Subject format:** `[LOG] Routine N — [brief descriptor] — YYYY-MM-DD`
Examples:
- `[LOG] Routine 1 — Lone Bellow ticket — 2026-04-03`
- `[LOG] Routine 3 — Birchmere newsletter — 2026-04-03`
- `[LOG] Routine 4 — Larkin Poe newsletter — 2026-04-03`
- `[LOG] Routine 5 — Joey Landreth BIT follow — 2026-04-06`

**Draft body includes:**
- Which email(s) were processed (sender, subject, date)
- Every action taken: calendar events created or updated, TSV rows added,
  on-sale reminders created, recommendations made
- For Routine 3/4 recommendations: tier (Strong/Medium/Low), show date, venue,
  calendar availability result, and ticket link
- Any skipped items and why (date conflict, below threshold, already have tickets, etc.)
- Any manual follow-up items (label to apply, hat autograph gdoc update, etc.)

**One draft per routine invocation.** If Routines 3 and 4 both run in the same
conversation, two separate drafts are created. Draft creation is non-blocking —
if it fails, the summary stays in conversation and we move on.

**Pure reminder emails (BIT/Songkick) require no log draft** — see Routine 5 for
the suppression rule.

**Searching the log:** Use `subject:[LOG]` in Gmail to find all log drafts.
Use `subject:[LOG] Routine 3` to find on-sale processing history, etc.

---

## Calendar Availability Rule

**A date is unavailable if it has a timed show event OR an all-day `NO SHOWS` block.**

When checking whether a date is open — for conflict checking in Routine 1, for
recommendations in Routine 3, or for any direct availability question — always query
the calendar for both timed events and all-day events on that date. Treat either of
the following as unavailable:

- A timed event (any show already booked)
- An all-day event titled **NO SHOWS** (a personal block marking a date off-limits
  for any reason — travel, prior commitment, recovery day, etc.)

Do not recommend a ticket purchase or create a show event on a date blocked by either.

**Never update calendar events for past shows.** Calendar edits (description, location,
etc.) only apply to upcoming events. Past events are read-only — their content is the
permanent record as captured at show time.

**Prev/Next Show belongs in `live_shows_potential.tsv` only.** The Prev Show and Next
Show columns exist to aid purchase decisions. Do not include Prev/Next Show information
in calendar event descriptions or in `live_shows_current.tsv` rows — the calendar's
own week and month views already provide that context.

**Confirm before creating a calendar event for an unpurchased show.** If a show has
not yet been purchased (e.g. a potential show added to the calendar as a reminder),
always confirm with Dan that a calendar event is wanted before creating one.

---

## Fast Track Protocol

**`live-shows/fast_track.tsv`** is a curated list of artists who should be treated as
immediate buys when a local show surfaces — skipping the potential list evaluation cycle
entirely. The file exists for artists with **no DC show history** (or no headlining
history) who have earned a pre-authorized buy signal through external credibility
(BMA nominations, Alligator Records, critical consensus, etc.).

**Discipline:** Fast Track is strictly for artists who would NOT already be caught as
a strong buy based on show history. Artists with an established history of DC attendance
(Kingfish, Larkin Poe, Lone Bellow, ZZ Ward, etc.) are handled by the existing tier
system and must NOT be added here.

### Cap defaults

All three caps default to their most expansive values unless explicitly narrowed in the file:

| Cap | Default | Narrower options |
|-----|---------|-----------------  |
| Price Cap | $100 all-in | Any lower dollar amount |
| Distance Cap | Regional (DC/MD/VA + Baltimore, ~60 mi) | Local (DC/MD/VA only) · Extended (~90 mi) |
| Venue Cap | Mid (Small rooms + 9:30 Club, Wolf Trap Barns, State Theatre, ~500–1200 cap) | Small (Birchmere/Hamilton/Rams Head/Hub City tier only) · Large (adds Wolf Trap Filene, The Anthem) |

A blank cell in any cap column means the default applies. All three caps must be
satisfied for Fast Track treatment. If **any cap is exceeded** — price too high,
venue too large, show too far — surface as a normal **Choose** recommendation in
`live_shows_potential.tsv` instead, noting that it narrowly missed Fast Track and why.

### When Fast Track applies

During Routine 3 (Step 2) and Routine 5 (Step 4), after the standard checks:

1. Look up the artist in `fast_track.tsv`
2. If found, check all three caps against the show details
3. **All caps satisfied** → present as **🚀 Fast Track buy**: recommend immediate
   purchase without adding to potential list first. Note the book check from the
   `Book Check` column. No potential list row needed unless purchase is deferred.
4. **Any cap exceeded** → present as a normal Choose recommendation in the potential
   list, flagging which cap was exceeded and by how much

Fast Track overrides the normal "Strong tier only" filter for Case B on-sale events —
a Fast Track artist with a confirmed open date and a specific on-sale time still gets
an on-sale reminder calendar event (Routine 3 Step 4), not just a mention.

---

## live_shows_potential.tsv Write Protocol

**Always fetch a fresh SHA immediately before writing `live_shows_potential.tsv`.**

Any time a routine needs to add, remove, or re-sort rows in `live_shows_potential.tsv`,
call `get_file_contents` on the file right before the write — even if the file was
read earlier in the same session. Dan may have committed changes independently between
reads, and a stale SHA will cause the commit to fail or silently clobber his edits.

The sequence for every potential list write is:
1. `get_file_contents` → capture the current `sha` and content
2. Apply the change (add row, remove row, or re-sort)
3. Re-sort the full file: `Buy` → `Choose` → `Pass`, date ascending within each group
4. Commit using `create_or_update_file` with the freshly fetched `sha`

This applies to:
- **Routine 1 Step 6** — row removal when a ticket is purchased
- **Routine 3 Step 2** — row addition when a new show is approved

---

## artists.tsv Counting Policy

**Times Seen counts every appearance — headliner and supporting act alike.**

When updating `artists.tsv` after a show, count the show for every artist in
`artists.tsv` who was in the room, regardless of whether they headlined or opened.
This applies to:

- The headliner
- Any named supporting act who is already in `artists.tsv`
- Any named supporting act who reaches their **second** appearance across all shows
  (see New Entry Rule below)

**First Seen / Most Recent Seen** use the same inclusive logic: if an artist's earliest
appearance was as a support act, that date is their First Seen. Most Recent Seen is
updated whenever they appear, in any role.

**New Entry Rule — support acts:** A supporting artist who is not yet in `artists.tsv`
gets a new row added **only when their second appearance is recorded.** One-off openers
do not get entries. The first time you see someone only as a support act, make a note
in the post-show email if they seem worth tracking; on their second appearance, add the
row at that time and backfill the first date. Carly Harvey is the reference example:
three support appearances across Ana Popović and Selwyn Birchwood shows, added on
reaching that threshold.

**History files are the source of truth.** When in doubt about counts or dates, audit
`history/*.tsv` and `live_shows_current.tsv` together rather than relying on the
current `artists.tsv` values.

---

## Routine 1 — New Ticket Purchase Email

**Trigger:** A ticket confirmation forwarded from dan2bit@gmail.com arrives in the
redhat.bootlegs inbox (Ticketmaster, AXS, Eventbrite, See Tickets/Eventim, box office
receipt image, etc.)

### What I do

**Step 1 — Find and parse the email**

Search `from:dan2bit -label:processed` filtered to recent messages, identify the
ticket confirmation, and extract:
- Artist and supporting act(s)
- Show date, doors time, show time
- Venue name and full address
- Seat info / GA status
- Ticket access method (AXS app, Ticketmaster app, paper, mobile barcode, etc.)
- Ticket quantity
- Face value per ticket
- Fees (itemized if available)
- Total cost
- Purchase date
- Any order reference numbers, promo codes, or special notes

**Step 2 — Apply venue defaults**

Default times and details if not explicit in the email:

| Venue | Doors | Show | Notes |
|-------|-------|------|-------|
| The Birchmere | 5:00 PM | 7:30 PM | GA; seating begins 6:30 PM; always free parking |
| Hamilton Live | 6:30 PM | 8:00 PM | $13 parking |
| Rams Head On Stage | 1 hr before show | — | — |
| Wolf Trap Filene Center | — | — | Use ticket for times |
| Wolf Trap Barns | — | — | Use ticket for times |

"An Evening With" billing means no supporting act. VIP tickets get `(VIP)` appended
to the calendar event title as a reminder to watch for access instructions.

**Step 3 — Check autograph books**

Look up the headliner in `autograph_books_combined.tsv`
(Google Drive ID: `1ENPcmHxrbdMfJNuDlqy-RRBHkGm8Onyy`).

- If artist is in **RHBS**: prepend `📚 BRING RHBS — [Artist] p.[N]` to the calendar event description
- If artist is in **APS**: prepend `📚 BRING APS — [Artist] p.[N]`
- If in both: list both books
- If not in either: no prefix

**Step 4 — Create calendar event**

Calendar: `redhat.bootlegs@gmail.com` — Dan Concert Calendar

Event title format: `[Artist]` with ticket count and type suffix:
- Electronic/mobile ticket: `[Artist] (N)` — e.g. `Orianthi (1)`, `Sarah McLachlan (2)`
- Paper ticket (only if explicitly stated in the email): `[Artist] (N PAPER)` — e.g. `Gary Clark Jr. (1 PAPER)`
- VIP ticket: append `(VIP)` after the count suffix — e.g. `The Lone Bellow (1 VIP)`
- Single electronic ticket with no other suffixes: omit the `(1)` for clean titles — only add the count when N > 1 or when PAPER or VIP applies

Description format:
```
📚 BRING RHBS — [Artist] p.[N]          ← only if in autograph book

[Order # / Ref] ([Ticketer])
Ticket access: [method]
Payment: [card/method] · Face $X.XX · Fees $X.XX · Total $X.XX
[Supporting act line if applicable]
[Any special notes: promo code, resale note, upgrade available, etc.]

[Seat / GA info]
Doors: [time] · Show: [time]

💸 High ticket cost — cool it on merch tonight   ← only if face value per ticket ≥ $100, NOT VIP, NOT Wolf Trap Filene Center
```

Do **not** include Prev/Next Show in the description — the calendar's week and month
views already provide that context. Prev/Next belongs in `live_shows_potential.tsv` only.

Location field: use the **parking address** for the venue, not the venue street address.
Refer to `venues.tsv` for the correct parking address per venue. For venues where
parking is on site (Birchmere, Wolf Trap, etc.), use the venue address itself.

Reminders: 24 hours (1440 min) and 3 hours (180 min) popup.

**Merch caution rule:** If the **face value per ticket** is ≥ $100 and the ticket is
**not** a VIP package, append `💸 High ticket cost — cool it on merch tonight` to the
event description. Three exceptions — do **not** add this note for:
- **VIP tickets** — the premium is expected and factored in at purchase time
- **Wolf Trap Filene Center** — venue/lawn context makes merch spend a different calculus
- **Multi-ticket orders** — evaluate per-ticket face value only, not the order total

**Step 5 — Commit new row to `live_shows_current.tsv`**

Insert the new row in date order and commit directly to `main` via the GitHub MCP.

Row format (25 columns):

```
Show ID | Artist | Supporting Artist | Show Date | Doors Time | Start Time |
Venue Name | Venue Address | Venue Event URL | Seat Info / GA | Ticket Access |
Ticket Quantity | Face Value (per ticket) | Fees | Total Cost | Purchase Date |
Setlist.fm URL | Personal Rating | Status | Food & Bev | Parking | Merch |
Artist Interaction | Playlist URL | Notes / Memories
```

- `Show ID` = same as Show Date (YYYY-MM-DD)
- `Status` = `upcoming`
- Spending columns (Food & Bev, Parking, Merch, Artist Interaction) = blank
- `Setlist.fm URL` = blank
- `Notes / Memories` = any pre-show notes from the ticket (order #, seat notes, etc.)
- Do **not** include Prev/Next Show — that belongs in `live_shows_potential.tsv` only

**If the commit fails:** present the full updated `live_shows_current.tsv` in the
conversation for download and manual check-in.

**Step 5b — Update `Prev Show / Next Show` columns in `live_shows_potential.tsv`**

Adding a new show to `live_shows_current.tsv` may make existing potential rows stale.
Scan every row in `live_shows_potential.tsv` and update the `Prev Show (2026)` or
`Next Show (2026)` columns where the newly committed show now falls between the
recorded dates, or where it is now the furthest-out committed show. Include any
updates in the same potential list commit as Step 6 (row removal), or as a standalone
commit if no row is being removed. Note any updates in the activity log draft.

**Step 6 — Remove from `live_shows_potential.tsv` if present**

Look up the artist in `live_shows_potential.tsv` by matching Artist and show date.

- **If found:** fetch a fresh SHA (see Live Shows Potential Write Protocol above),
  remove the row, re-sort the full file (`Buy` → `Choose` → `Pass`, date ascending
  within each group), and commit using `create_or_update_file` with the fresh SHA.
  Note the removal in the activity log draft.
- **If not found:** no action needed — many tickets are purchased without first
  appearing in the potential list.

Match on Artist name (normalized) and show date. If the potential row has a date
range (e.g. a festival) or TBD date, match on artist name alone and confirm the
date before removing.

**If the commit fails:** present the updated `live_shows_potential.tsv` in the
conversation for download and manual check-in.

**Step 7 — Remove from `fast_track.tsv` if present**

Look up the headliner in `fast_track.tsv` by artist name.

- **If found:** remove the row and commit the updated file directly to `main`.
  The rationale: Fast Track is for artists not yet seen. This ticket purchase means
  they are now entering the history-based tier system — future shows will be evaluated
  on the same basis as any other Strong/Medium artist. They no longer need pre-authorized
  buy treatment. Note the removal in the activity log draft.
- **If not found:** no action needed — most ticket purchases will not involve Fast Track
  artists.

**If the commit fails:** present the updated `fast_track.tsv` in the conversation for
download and manual check-in.

**Step 8 — Create activity log draft ⚠️ MANDATORY**

This step is required for every Routine 1 invocation without exception — including
same-day/impromptu shows where the ticket and show notes arrive together.

Create a draft in the redhat.bootlegs inbox with:
- Subject: `[LOG] Routine 1 — [Artist] ticket — YYYY-MM-DD`
- Body summarising: email found (sender, subject, date), ticket details parsed,
  autograph book check result, calendar event created (title, date, time, any
  book reminder or merch note), TSV row committed or presented for manual check-in,
  potential list Prev/Next Show columns reviewed (any rows updated noted),
  potential list row removed (or confirmed not present), Fast Track row removed
  (or confirmed not present), any notable decisions or caveats

**Final step:** Remind you to apply the `processed` label to the email.

---

## Routine 2 — Post-Show Notes Email

**Trigger:** You send an email to (or forward to) redhat.bootlegs@gmail.com after
attending a show. The email should include:

- Spending: food & bev, parking, merch amounts
- Setlist.fm URL for the show
- Autograph note (if you got one — book vs. hat, who signed, and if a supporting act member)
- Any show notes or memories worth recording
- Artist interaction type (Autograph, Photo, Both, or none)

**Subject line convention:** Use the artist name (e.g. "Danielle Nicole 3/20/26 notes")
so I can find the matching calendar event and TSV row easily.

### What I do

**Step 1 — Find the matching email and show**

Search `from:dan2bit subject:[artist] notes -label:processed`, read the email, then
find the matching calendar event and `live_shows_current.tsv` row.

**Step 2 — Update the calendar event**

Append spending and setlist info to the existing event description. **Only do this
for upcoming or same-day events — never update calendar events for past shows.**

```
Spending: Food/Bev $X · Parking $X · Merch $X
Setlist: [setlist.fm URL]
[Notes / memories if notable]
```

**Step 3 — Append row to `spending.tsv` ⚠️ MANDATORY**

`live-shows/spending.tsv` is the canonical permanent record of show spending. This
step is required for every attended show — it is not optional.

Append one row to `spending.tsv` with:

```
Show Date | Artist | Ticket Cost | Food & Bev | Parking | Merch | Artist Interaction | Show Total | Notes
```

- `Ticket Cost` = total paid (face + fees) from `live_shows_current.tsv`
- `Food & Bev`, `Parking`, `Merch` = from the post-show email (use $0.00 if none, never blank)
- `Artist Interaction` = Autograph / Photo / Both / blank
- `Show Total` = sum of all columns
- `Notes` = brief context (VIP, matinee, split ticket cost, etc.) — same as Notes/Memories summary

Commit directly to `main`. If the commit fails, present the updated file in conversation
for manual check-in.

**`spending.tsv` is the sole long-term authority for spending data.** The spending
columns in `live_shows_current.tsv` are a convenience scratch pad for the current year
only and will not be carried into archive files at rollover.

**Step 4 — Update autograph records (if applicable)**

If the email mentions getting a **book autograph** (RHBS or APS):

1. Read `autograph_books_combined.tsv` from Drive
   (Drive ID: `1ENPcmHxrbdMfJNuDlqy-RRBHkGm8Onyy`)
2. Find the artist row
3. Set the appropriate `RHBS Signed` or `APS Signed` column to `Yes`
4. Add any notes to the `APS Autograph Notes` column if relevant

If the email mentions a **hat autograph**:

1. Update `artists.tsv` — set `Hat Autograph` to `Y` for the signing artist
2. Update `autograph_books_combined.tsv` — add signer name, show, and date to the
   `Hat Notes` column for that artist row
3. **Remind you to manually append the entry to the hat autograph Google Doc**
   (https://docs.google.com/document/d/1haKMpfwPWosdPnZXBAAlLUzj3926hoTEH7icg6gTRA8/edit)
   — no write connector is available for Google Docs, so this step is always manual.
   Format to use: `**[Name]** [*of/w/ Act*] @ [Venue short name] [M/D/YY]`

Note: hat signers are often supporting act members or band members rather than the
headliner. The email should make clear who signed and in what capacity.

**Step 5 — Commit all file changes directly to `main`**

All files changed in Routine 2 are `.tsv` files. Per the repo commit policy, TSV files
are non-executable and commit directly to `main` — **no PR is needed or appropriate**,
regardless of how many files are touched together.

Use `push_files` to commit all changed files in a single commit to `main`:

- `live_shows_current.tsv` — row updated: `Status` → `attended`, spending filled,
  `Setlist.fm URL` filled, `Notes / Memories` filled, `Artist Interaction` filled
- `artists.tsv` — always included; apply counting policy below
- `autograph_books_combined.tsv` — `RHBS Signed` / `APS Signed` set to `Yes`
  and/or `Hat Notes` updated if applicable (omit file if no change)

Note: `spending.tsv` is already committed directly to `main` in Step 3 — do not
include it again here.

Commit message format: `post-show: [Artist] [YYYY-MM-DD]`

**If the commit fails:** present each changed file in the conversation for
download and manual check-in.

**Step 6 — Open a GitHub issue for YouTube playlist creation**

Create a new issue in `dan2bit/songs-for-my-funeral` for the playlist creation task.
This issue stays open until the playlist is built and the pipeline has been run.

Issue title format: `🎬 Playlist: [Artist] — [YYYY-MM-DD] ([Venue short name])`

Issue body:
```
## Show details

**Artist:** [Artist]
**Supporting:** [Supporting Artist, or — if none]
**Date:** [YYYY-MM-DD]
**Venue:** [Venue Name]
**Setlist.fm:** [URL, or TBD if not yet available]
**Artist interaction:** [Photo / Autograph / Both / None]
**YouTube:** [headliner's YouTube Channel value from artists.tsv — use as-is if a full URL,
             prefix with https://youtube.com/ if a bare @handle; omit this line if blank or N/A]

## Notes / memories

[Full notes from the post-show email, verbatim or lightly cleaned up]

## Workflow

1. Upload show videos to YouTube Studio (`@dan2bit` channel) — arrange in order per setlist.fm
2. Create playlist titled: `[Artist] — [Venue short name] [M/D/YY]`
3. Set playlist to Public once complete
4. Run:
   ```bash
   python3 youtube_fetch.py --force --since [show-date]
   python3 youtube_correlate.py --merge
   ```
5. Fill in `Playlist URL` in `live_shows_current.tsv`, then commit and push:
   `playlist: [Artist] [YYYY-MM-DD] fix #[issue]`
   (The `fix #N` keyword auto-closes this issue on push.)
```

Labels: `playlist`

If there is **no footage** from the show (noted in the post-show email or known at
processing time), skip this step and note it in the activity log draft instead.

**Step 7 — Create activity log draft ⚠️ MANDATORY**

This step is required for every Routine 2 invocation without exception.

Create a draft in the redhat.bootlegs inbox with:
- Subject: `[LOG] Routine 2 — [Artist] post-show — YYYY-MM-DD`
- Body summarising: email found, spending recorded (spending.tsv row appended,
  show total), calendar event updated (or skipped — past show), autograph records
  updated (if applicable), files committed (list which files changed), GitHub issue
  opened for playlist (issue number and link, or noted as skipped if no footage),
  any manual follow-up items (hat autograph gdoc, `processed` label)

**Final step:** Remind you to apply the `processed` label to the email.

### artists.tsv update rules for Routine 2

Apply the following every time a post-show commit is built. `artists.tsv` is **always**
included — never committed separately.

**For the headliner:**
- Increment `Times Seen` by 1
- Update `Most Recent Seen` to the show date
- `First Seen` only changes if this show predates the current value (rare)
- **If the ticket was a VIP package:** also increment `VIP Count` by 1 for the
  headliner. The `VIP Count` column is numeric — blank means zero, never use `Y`.

**For each named supporting act listed in the show's `Supporting Artist` field:**

1. **Already in `artists.tsv`:** increment their `Times Seen` by 1, update
   `Most Recent Seen`. Update `First Seen` if this show predates their current value.

2. **Not yet in `artists.tsv` — first time seeing them:** do not add a row yet.
   Note in the commit message or log draft that this artist appeared as support for
   the first time. No action in the file until their second appearance.

3. **Not yet in `artists.tsv` — second or subsequent time seeing them:** add a new
   row now. `Times Seen` = total number of times seen across all shows (headliner and
   support combined). `First Seen` = their earliest appearance date. `Most Recent Seen`
   = their most recent appearance date (blank if only one appearance, which cannot
   apply here since this is at least their second). Fill `YouTube Channel` and
   `Spotify URL` if known; leave blank otherwise.

**Hat Autograph / Book Autograph columns** are updated separately per the autograph
rules above and are not affected by the counting policy change.

---

## Routine 3 — Pre-Sale / On-Sale Notification Email

**Trigger:** An on-sale alert, pre-sale announcement, or venue/artist newsletter
tagged `ticket-alert` arrives in the redhat.bootlegs inbox. This includes Seated
alert emails, which are treated as ticket-sale notifications rather than follow
service alerts.

### What I do

**Step 1 — Find and parse the email**

Search `label:ticket-alert -label:processed`, read each unprocessed alert, and
classify each artist mention as one of two cases:

**Case A — Tickets already on sale** (no specific future on-sale time given):
- Filter to artists on the Strong or Medium tiers (seen before, or in autograph books)
- Check calendar for conflicts on the show date (apply Calendar Availability Rule above)
- Present a tiered list of open-date recommendations with direct Ticketmaster/AXS
  search links — no calendar event created
- Include autograph book note if applicable

**Case B — Specific future on-sale time given** (pre-sale or general on-sale announced):
- Only act on **Strong tier** artists (previously seen) with a confirmed open date
- Check calendar for conflicts before proceeding (apply Calendar Availability Rule above)
- Create an on-sale reminder calendar event (see Step 4 below)

For digest-style newsletters (multiple artists, no specific on-sale times), treat all
entries as Case A and present the tiered list. Do not create calendar events for
digest newsletters.

**Non-Ticketmaster forwarded emails:** If the email is tagged `ticket-alert` but was
forwarded from `dan2bit@gmail.com` (rather than arriving directly from a ticketing
platform), it means the subscription is still pointed at the dan2bit address and needs
to be re-targeted. After processing the content as normal, scan the email body for a
subscription management link — typically labeled "Update Profile", "Manage
Preferences", "Update email address", or similar, often in the footer. Present that
link so you can re-subscribe under `redhat.bootlegs@gmail.com`. Common providers:
- **Constant Contact** — "Update Profile" link in footer; allows direct email change
- **Mailchimp** — "Update your preferences" link in footer; may or may not allow email
  change depending on list settings. If the email field is locked, a fresh signup at
  the venue's website under `redhat.bootlegs@gmail.com` is required instead.
- Venue box office systems vary — note the sender address if no management link is found

**IMP newsletter special rule:** When processing an IMP newsletter (9:30 Club,
The Anthem, Lincoln Theatre, The Atlantis, Merriweather), apply the standard tiering
above and additionally flag any **The Atlantis** show featuring a local DC artist as a
gift card opportunity — even for artists below the Strong/Medium threshold.

**Step 2 — Check against `live_shows_potential.tsv` and `fast_track.tsv`**

Before presenting any recommendation, look up the artist in `live_shows_potential.tsv`.
If the show is already in the file:
- **Decision = `Pass`** — skip silently; no recommendation needed
- **Decision = `Buy` or `Buy (paper @ ...)`** — remind Dan to complete the purchase
- **Decision = `Choose`** — present as a normal recommendation (still undecided)

If the show is new, check `fast_track.tsv` **before** applying the standard tier filter:

- **Artist is in `fast_track.tsv`** — evaluate all three caps (Price, Distance, Venue)
  against the show details:
  - All caps satisfied → present as **🚀 Fast Track buy** (see Fast Track Protocol above).
    Do not add to potential list unless purchase is being deferred.
  - Any cap exceeded → present as a Choose recommendation in the potential list,
    noting which cap was exceeded and by how much.
- **Artist is not in `fast_track.tsv`** — apply the standard Strong/Medium tier filter
  and present normally.

When adding an approved row to the potential list, use the following Decision values:
- **Clear buy signal** → `Buy` or `Buy (paper @ [show])` as appropriate
- **Undecided** → `Choose` (never leave Decision blank)
- **Likely skip** → `Pass`

**Adding a row — write protocol:** Fetch a fresh SHA immediately before writing
(see Live Shows Potential Write Protocol above), apply the new row, re-sort the full
file (`Buy` → `Choose` → `Pass`, date ascending within each group), and commit using
`create_or_update_file` with the fresh SHA.

**Date pruning:** At the start of each inbox session, remove any row whose show date
has already passed, regardless of Decision value. Purchased shows are removed via
Routine 1 Step 6; all other rows (Buy, Choose, Pass) are removed here once the date
has passed. Apply the same fresh-SHA write protocol when pruning.

**Step 3 — Check autograph books**

Same lookup as Routine 1 — note book reminder in any recommendation or calendar
event description. For Fast Track artists, the `Book Check` column in `fast_track.tsv`
is pre-filled; use it directly rather than doing a separate lookup.

**Step 4 — Create on-sale reminder event (Case B only, or Fast Track with specific on-sale time)**

Calendar: `redhat.bootlegs@gmail.com` — Dan Concert Calendar

Event title format: `🎟 ON SALE: [Artist]`

Timing:
- **Start:** 5 minutes before the on-sale/pre-sale time
- **Duration:** 15 minutes

Description format:
```
📚 BRING RHBS — [Artist] p.[N]          ← only if in autograph book

[Artist] tickets on sale [date] at [time]
Buy here: [ticket URL]

Pre-sale code: [CODE]                   ← only if present
Pre-sale window: [start] – [end]        ← only if known
[Venue] · [Show date if known]
[Any pricing or seat tier notes]
```

Reminders:
- 24 hours before (1440 min) — advance notice to plan
- 5 minutes before (5 min) — fires right as you're sitting down to buy

**No TSV row is created** — that comes when the ticket is actually purchased
and processed via Routine 1.

**Step 5 — Create activity log draft ⚠️ MANDATORY**

This step is required for every Routine 3 invocation without exception.

Create a draft in the redhat.bootlegs inbox with:
- Subject: `[LOG] Routine 3 — [source newsletter/venue] — YYYY-MM-DD`
- Body summarising: email source and date, every artist evaluated with their
  tier classification and calendar availability result, all recommendations
  made (artist, date, venue, ticket link), Fast Track evaluations (artist, caps checked,
  result), all on-sale reminder events created (artist, on-sale time, calendar event
  title), items skipped and why (date conflict, below threshold, already have tickets,
  Pass decision, etc.), any re-subscription links surfaced

**Final step:** Remind you to apply the `processed` label to the email.

---

## Routine 4 — Artist Newsletter Email

**Trigger:** An email from an artist mailing list subscription arrives in the
redhat.bootlegs inbox tagged `artist-mail`.

### Subscribed artists

The canonical source of truth for direct mailing list subscriptions is the
`Direct Mail` column in `live-shows/follows/follows_master.tsv` (Y = subscribed).

For quick reference, as of 2026-04-06:

| Artist |
|--------|
| Albert Castiglia |
| Allison Russell |
| Amythyst Kiah |
| Buffalo Nichols |
| Bywater Call |
| Christone 'Kingfish' Ingram |
| Daniel Donato |
| Ghalia Volt |
| Jackie Venson |
| Judith Hill |
| Larkin Poe |
| The Lone Bellow |
| Mike Zito |
| Robert Randolph |
| Ruthie Foster |
| Samantha Fish |
| Shemekia Copeland |
| Southern Avenue |
| Sue Foley |
| Taj Farrant |
| Tal Wilkenfeld |
| Trombone Shorty & Orleans Avenue |
| Vanessa Collier |
| The War and Treaty |

**Not subscribed — known reasons:**
- Enter the Haggis — defunct; follow Haggis X-1 and House of Hamill instead
- Eric Gales, Selwyn Birchwood, Valerie June, Ana Popović — no email list found
- Kingsley Flood, Oh He Dead — too small/hyperlocal; shows already caught by venue newsletters
- Ally Venable — uses Patreon instead of email list

### What I do

**Step 1 — Find and read the emails**

Search `label:artist-mail -label:processed`, read each unprocessed email.

**⚠️ Gmail Promotions tab:** Artist welcome emails and newsletters sometimes land in
the **Promotions** tab rather than Primary, bypassing the `artist-mail` label filter.
When running Routine 4, also check `in:promotions -label:processed` for any unlabeled
newsletters from subscribed artists. Move any found to Primary and apply the
`artist-mail` label before processing. This cannot be done by Claude — it requires
manual action in Gmail.

**Step 2 — Classify and act on content**

For each email, look for three things:

**Tour announcements / new show dates:**
- Check if any announced show is in the DC/MD/VA area (or a driveable venue you've
  attended before)
- Check calendar for conflicts on the show date (apply Calendar Availability Rule)
- If open date + Strong tier artist + DC/MD/VA venue: present as a buy recommendation
  with the ticket link
- If specific on-sale time is given: create a `🎟 ON SALE:` calendar event exactly
  as in Routine 3 Step 4

**Pre-sale codes:**
- If a pre-sale code is included for a show on an open date: create a `🎟 ON SALE:`
  calendar event with the code prominently in the description
- If no show date is yet announced alongside the code: note the code and artist in
  the response so you can act when the date is confirmed

**New music releases:**
- Note the release (title, format, release date) in the response
- No calendar event or TSV action needed — just surfacing the information

**Step 3 — Autograph book check**

For any DC/MD/VA show recommendation, check `autograph_books_combined.tsv` and
include the book reminder in the recommendation exactly as in Routine 1.

**Step 4 — Create activity log draft ⚠️ MANDATORY**

This step is required for every Routine 4 invocation without exception.

Create a draft in the redhat.bootlegs inbox with:
- Subject: `[LOG] Routine 4 — [Artist] newsletter — YYYY-MM-DD`
- Body summarising: email source and date, tour announcements found (artist,
  date, venue, calendar availability, recommendation or skip reason),
  pre-sale codes surfaced (artist, code, show date if known),
  new music releases noted (title, format, release date),
  on-sale reminder events created (artist, on-sale time, calendar event title),
  any manual follow-up items

**Final step:** Remind you to apply the `processed` label to each email processed.

---

## Routine 5 — Artist Follow / Signup Email

**Trigger:** An email tagged `artist-follow` arrives in the redhat.bootlegs inbox.
This label covers two source types:

1. **Service notification** — a Bandsintown or Songkick "new show" alert for a
   followed artist. Gmail filters automatically apply `artist-follow` to emails
   from these senders. Note: Seated alert emails go to `ticket-alert` instead and
   are handled by Routine 3.
2. **Direct signup response** — a welcome email, confirmation, or first newsletter
   from an artist mailing list you just signed up for (labeled manually).

### Reminder suppression rule

BIT and Songkick send repeat alerts as show dates approach — the same show may
trigger multiple emails (on-sale, reminder, "last chance"). Before doing any
processing, apply this filter:

**If the show is already in `live_shows_current.tsv` or `live_shows_potential.tsv`
for that artist and date, this is a reminder — skip it entirely.** Mark processed
and move on. No log draft needed for pure reminder emails.

**If multiple emails arrive in the same session for the same show and it hasn't been
evaluated yet**, process it once and skip the rest as duplicates.

### What I do

**Step 1 — Find and read the emails**

Search `label:artist-follow -label:processed`, read each unprocessed email.
Identify the artist, the service (BIT, Songkick, direct signup), and whether it
contains new show information not already in the system.

Apply the reminder suppression rule before proceeding — if the show is already
known, mark processed and stop.

**Step 2 — Check `follows_master.tsv`**

Look up the artist in `live-shows/follows/follows_master.tsv`:

- **Artist not present at all** — add a new row. Tier defaults to Medium unless
  there's clear reason for Strong (seen before) or Lower. For service notifications,
  also check the relevant service list (e.g. `rhbl-bandsintown.tsv`) and add there
  too if missing. Present proposed row(s) in conversation for approval before committing.

- **Artist present, service not marked** — if this is a service notification from
  a service (BIT, Songkick) that isn't already marked Y in the artist's row,
  note the discrepancy and ask whether to update the file.

- **Artist present, `Direct Mail` not Y** — if this is a direct signup response,
  set `Direct Mail` to Y and commit. Ask in conversation first if it seems like
  a new signup rather than a known subscription.

- **Artist present, all columns correct** — no file change needed; just process
  the content.

**Step 3 — Recommend follow coverage**

After confirming the artist's `follows_master.tsv` status, assess whether their
follow coverage is complete and make recommendations in conversation:

- **Missing a service (BIT, Songkick, Seated)** — recommend adding, especially
  for Strong/Medium tier. Note which services the artist is likely to be found on.
- **`Direct Mail` is blank** — for Strong tier artists, recommend signing up for
  their mailing list if one exists. For Medium, flag as worth considering.
- **Coverage looks complete** — confirm in conversation; no action needed.

Do not automatically add the artist to additional services — present the recommendation
and let Dan confirm before making any file changes.

**Step 4 — Process any show content**

If the email contains a show announcement or pre-sale code:

1. **Check `fast_track.tsv` first** — if the artist is in the Fast Track list, evaluate
   all three caps against the show details and present as a 🚀 Fast Track buy (all caps
   satisfied) or a Choose recommendation (any cap exceeded), per the Fast Track Protocol.
2. **Otherwise** — handle exactly as Routine 4 Step 2 would: calendar check, autograph
   book lookup, buy recommendation or on-sale reminder event as appropriate.

**Step 5 — Create activity log draft ⚠️ MANDATORY**

This step is required for every Routine 5 invocation without exception, unless
suppressed by the reminder rule in Step 1.

Create a draft in the redhat.bootlegs inbox with:
- Subject: `[LOG] Routine 5 — [Artist] [BIT/Songkick/signup/etc.] — YYYY-MM-DD`
- Body summarising: email source and type, follows_master.tsv status found,
  any file changes made or proposed, follow coverage recommendations,
  any show content processed (date, venue, Fast Track evaluation if applicable,
  action taken), manual follow-up items

**No log draft for pure reminders** — if the email was suppressed by the reminder
rule in Step 1, just apply the `processed` label and move on.

**Final step:** Remind you to apply the `processed` label to each email processed.

---

## Notes

**Inbox monitoring is not automatic.** I don't poll the inbox. You trigger these
routines by telling me "there's a ticket email", "I just sent my post-show notes",
"there's an on-sale alert", or "process my artist mail" in a new project conversation.
I'll search the inbox and take it from there.

**Draft log searching.** Use `subject:[LOG]` in Gmail to find all activity log drafts.
Refine with `subject:[LOG] Routine 3` for on-sale history, `subject:[LOG] Routine 2`
for post-show history, etc.

**Hat autograph gdoc is the completeness authority.** The Google Doc at the link
above is more carefully maintained for hat autographs than the TSV files. If there
is a discrepancy between the gdoc and the TSV, the gdoc wins for the list of signers;
the TSV files win for show dates. No write connector exists for Google Docs — all
gdoc updates are manual.

**Google Calendar MCP fails on Android.** Calendar operations only work reliably
on macOS desktop. If calendar steps fail, switch to desktop before retrying.

**YouTube pipeline is separate.** Playlist creation is tracked via GitHub issues
(label: `playlist`) opened automatically by Routine 2. The pipeline scripts
(`youtube_fetch.py`, `youtube_correlate.py`) run manually after videos are uploaded
to YouTube Studio — see issue bodies for the exact command sequence. The issue is
auto-closed by the `fix #N` keyword in the playlist commit message.

---

## Pre-Requisite: Mailing List Subscriptions

Subscribe **redhat.bootlegs@gmail.com** to the following so that on-sale alerts
and pre-sale codes arrive in the inbox for Routine 3 to process. Apply the
`ticket-alert` label (manually or via a Gmail filter on the sender address) as
each subscription is set up.

**Venues (subscribed ✅):**
- The Birchmere ✅
- Hamilton Live ✅
- Rams Head On Stage ✅
- State Theatre ✅
- Collective Encore ✅
- Ticketmaster newsletter (forwarded from dan2bit) ✅
  Union Stage Presents (Pearl Street, Jammin Java, Howard Theatre, Union Stage) ✅
- Wolf Trap — wolftrap.org (email alerts) ✅
- 9:30 Club / Merriweather / other IMP venues — imppresents.com ✅
- Bethesda Theater — bethesdatheater.com ✅ (re-targeted 4/1/26 via Constant Contact)

**Venues (pending — fresh signup needed under redhat.bootlegs):**
- Hub City Vinyl (Hagerstown) — liveathubcityvinyl.com (Mailchimp; email change not supported, requires new signup)
- Strathmore — strathmore.org
- Capital One Hall — capitalonehall.com
- The Fillmore Silver Spring — fillmoresilverspring.com

**Ticketing platforms:**
- AXS — axs.com (artist follows)
- Seated — seated.com (artist follows); alert emails go to `ticket-alert`
- Eventbrite — follow relevant organizers

**Bandsintown** — redhat.bootlegs account. Gmail filter auto-labels emails from
BIT sender addresses as `artist-follow`. Artist follow list managed via
`worklist_bandsintown.tsv` and `follows_master.tsv`. ~120 artists per the worklist.

**Songkick** — Gmail filter auto-labels emails from Songkick sender addresses as
`artist-follow`.

**Artist newsletters** — see `Direct Mail` column in `follows_master.tsv` for the
complete subscribed list. Routine 4 subscriber table above is kept in sync.
