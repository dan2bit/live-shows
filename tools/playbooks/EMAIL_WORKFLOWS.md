# EMAIL_WORKFLOWS.md

Six standing routines for processing emails from the **redhat.bootlegs@gmail.com** inbox.
None are automatic — trigger each by starting a new conversation in this project.

**Authority map:**

| Topic | File |
|---|---|
| File write rules, commit targets, TSV protocols | `DATA_WRITE_PROTOCOLS.md` |
| Calendar event construction (how) | `CALENDAR_WORKFLOWS.md` |
| Gmail label setup, filter config, mailing list management | `EMAIL_SETUP.md` |
| Branch pipeline, CI, PR strategy | `docs/AGENTIC_WORKFLOWS.md` |

---

## Step 0 — Pre-Flight MANDATORY

**This step runs before every routine invocation, without exception. If any part
fails, stop immediately — do not proceed.**

### 0a — Time calibration

Call `time:get_current_time` (timezone: `America/New_York`) and record the result.
Use this date for all date pruning decisions, activity log subjects, calendar availability
checks, and "days until / since" calculations. Never rely on the model's internal
knowledge of the current date.

### 0b — Fetch live context

Fetch both files and hold them in context for the full session:

1. `data/live_shows_current.tsv` — extract all upcoming rows: artist, date, venue
2. `data/live_shows_potential.tsv` — extract all rows: artist, date, decision

**If `time:get_current_time` fails, or if either file fetch fails, stop immediately.**
These two files drive duplicate suppression (Routines 3–5) and date pruning (Routine 3).

---

## Gmail Label System

| Label | Applied by | Searched by |
|---|---|---|
| `ticket-receipt` | Gmail filter (from dan2bit, subject contains order/ticket keywords) | Routine 1 |
| `show-notes` | Dan manually | Routine 2 |
| `ticket-alert` | Dan manually or Gmail filter | Routine 3 |
| `artist-mail` | Gmail filter (artist newsletter senders) | Routine 4 |
| `artist-follow` | Gmail filter (BIT/Songkick) or manual | Routine 5 |
| `ticket-sold` | Gmail filter (forwards from dan2bit@gmail.com with `sold` in subject — covers AXS resales, StubHub, Ticketmaster resales) | Routine 6 |
| `processed` | Claude at end of each routine | All routines (excluded via `-label:processed`) |

**Label IDs:**
- `processed` = `Label_421272830174798850`
- `ticket-alert` = `Label_8111132848568068688`
- `show-notes` = `Label_4852367418911615829`
- `ticket-receipt` = `Label_8008139800288276097`

**Search patterns:**

| Routine | Search query |
|---|---|
| 1 — Ticket purchase | `label:ticket-receipt -label:processed` |
| 2 — Post-show notes | `label:show-notes -label:processed` |
| 3 — On-sale alert | `label:ticket-alert -label:processed` |
| 4 — Artist newsletter | `label:artist-mail -label:processed` |
| 5 — Artist follow / signup | `label:artist-follow -label:processed` |
| 6 — Ticket sold | `label:ticket-sold -label:processed` |

---

## Processed Label Protocol

Apply `processed` (`Label_421272830174798850`) via `Gmail:label_thread` at the end of
each routine, after the activity log draft is written. No manual confirmation required —
labeling is part of routine completion.

**Exception — Routine 5 pure reminders:** Apply `processed` directly without a log draft.

**Never apply `processed` speculatively** to threads from future routines not yet run.

---

## Draft Activity Log

**Mandatory. Created at the end of every routine invocation without exception.**

Subject format: `[LOG] Routine N — [brief descriptor] — YYYY-MM-DD`

Examples:
- `[LOG] Routine 1 — Gov't Mule ticket — 2026-06-03`
- `[LOG] Routine 2 — Vanessa Collier post-show — 2026-05-09`
- `[LOG] Routine 3 — Birchmere / Wolf Trap / Hub City newsletters — 2026-06-03`
- `[LOG] Routine 4 — Danielle Nicole / Galactic / Southern Avenue — 2026-06-03`
- `[LOG] Routine 5 — Kingsley Flood BIT alert — 2026-01-15`
- `[LOG] Routine 6 — TMBG StubHub sale — 2026-06-28`

Search all logs: `subject:[LOG]`

Body includes: which email(s) processed, every action taken (TSV rows added/removed,
calendar events, recommendations), skipped items and why, manual follow-up items.

One draft per routine invocation. If draft creation fails, the summary stays in
conversation. Pure reminder emails (Routine 5) require no log draft.

---

## Calendar Availability Rule

**A date is unavailable if it has a timed show event OR an all-day `NO SHOWS` block.**
Always query the calendar for both before any recommendation or potentials write.

All calendar mechanics — event titles, descriptions, locations, reminders, the NO SHOWS
block spec, and the on-sale event format — live in **`CALENDAR_WORKFLOWS.md`**. The
routines below decide **when** an event is created; see that file for **how**.

Key carry-overs:
- Never update calendar events for past shows.
- Prev/Next Show belongs in `live_shows_potential.tsv` only — never in calendar events.
- Confirm before creating a calendar event for an unpurchased show.

---

## Routine 1 — New Ticket Purchase

**Trigger:** `label:ticket-receipt -label:processed`

**Step 1 — Parse the email**

Extract: artist, supporting act(s), show date/times, venue, seat info, ticket access
method, ticket quantity, face value, fees, total cost, purchase date, order numbers.

**Step 2 — Apply venue defaults**

| Venue | Doors | Show | Notes |
|---|---|---|---|
| The Birchmere | 5:00 PM | 7:30 PM | GA; seating begins 6:30 PM; always free parking |
| Hamilton Live | 6:30 PM | 8:00 PM | $13 parking |
| Rams Head On Stage | 1 hr before show | — | — |
| Wolf Trap Filene Center | — | — | Use ticket for times |

"An Evening With" billing means no supporting act. VIP tickets get `(VIP)` appended
to the calendar event title.

**Step 3 — Check autograph books**

Look up headliner and known supporting acts in `autograph_books_combined.tsv` (book signatures) and `hat_signatures.tsv` (hat).

- In RHBS and not yet signed → prepend `BRING RHBS — [Artist] p.[N]` to calendar description
- In APS and not yet signed → prepend `BRING APS — [Artist] p.[N]`
- Already signed → no reminder

**Hat signing eligibility:** per `data/show_goals/hat_eligibility.tsv` (#115) — `Yes` =
target for signing. Already-signed comes from `data/show_goals/hat_signatures.tsv`
(canonical for actual signers). Web search only for artists absent from the eligibility
file — and add the resulting row while you're there.

Venue likelihood for artist interaction (Yes / Maybe / No) per `venues.tsv`; flag for
confirmation if venue not listed.

**Step 4 — Create calendar event — MANDATORY, NOT OPTIONAL**

Per **`CALENDAR_WORKFLOWS.md` → Event Type 1 — Show Events**. A purchased show is not
fully processed until it has a corresponding calendar event — the TSV row and the
calendar entry are treated as a single unit of work, not two independently-optional
outputs. This applies regardless of ticket access method (paper, mobile barcode,
Ticketmaster SafeTix, etc.) — no ticket type is exempt. If calendar event creation fails
or is skipped for any reason (tool error, ambiguous venue timing, Dan not yet available
to confirm details), the routine is **not complete** — do not proceed past this step
silently. Surface the failure/blocker to Dan explicitly and hold the routine open (do
not apply `processed`, do not write the log draft as if calendar creation succeeded)
until it is resolved or Dan explicitly defers it.

**Step 5 — Commit to both repos**

Per **`DATA_WRITE_PROTOCOLS.md` → `live_shows_current.tsv` write protocol**:
- Public fields → `data/live_shows_current.tsv` on `staging` in `dan2bit/live-shows`
- Private fields → `dan2bit/live-shows-private → current_private.tsv` on `main`

Two separate commits to two separate repos.

**Step 5b — Update Prev/Next brackets in `live_shows_potential.tsv`**

Per **`DATA_WRITE_PROTOCOLS.md` → Prev/Next bracket rule**. Only Buy and Choose rows.

**Step 6 — Remove from `live_shows_potential.tsv` if present**

Fetch fresh SHA, remove row, re-sort, commit to `staging`.

**Step 7 — Remove from `fast_track.tsv` and `fast_track_caps.tsv` if present**

Remove from `data/fast_track.tsv` (`staging`) and
`dan2bit/live-shows-private → fast_track_caps.tsv` (`main`). Keep both in sync.

**Step 8 — Pre-log calendar validation (MANDATORY, blocking)**

Before writing the activity log draft or applying `processed`, re-query the calendar
(`Google Calendar:list_events`, `redhat.bootlegs@gmail.com`, date-bounded around the
show date) and confirm a timed event exists for this show, with a title matching the
artist and a start time matching the parsed doors/show time. This is a positive
verification step, not a re-statement of Step 4 — it exists specifically to catch cases
where Step 4 appeared to succeed but the event was never actually created or committed
(tool call silently no-op'd, wrong calendar targeted, wrong date, event created then
lost), and to catch cases where a show's data made it into `live_shows_current.tsv`
through any other path (manual edit, bulk import, other routine) without ever going
through Step 4. This check does not depend on ticket type — paper-ticket and e-ticket
purchases alike have gone missing from the calendar in practice, so both are verified
identically.

- **Event found, details match:** proceed to Step 9.
- **Event found, details mismatched** (wrong time/date/title): fix it now — this is
  still Routine 1's job, not a deferred cleanup item. Note the correction in the log.
- **No event found:** treat as a Step 4 failure. Do not proceed to the log draft or
  `processed` label. Create the missing event now, per `CALENDAR_WORKFLOWS.md` → Event
  Type 1, then re-verify.

**This step cannot be skipped even if Step 4 "looked" successful in conversation.**
Tool calls can return a success payload for an event that doesn't end up on the visible
calendar (wrong calendar ID, silent auth issue, etc.) — the only reliable confirmation
is a fresh read-back.

**Step 9 — Activity log draft** (subject: `[LOG] Routine 1 — [Artist] ticket — YYYY-MM-DD`)

Include explicit confirmation in the log body that the calendar event was verified
present (Step 8), not just "created."

**Final:** Apply `processed` label.

---

## Routine 2 — Post-Show Notes

**Trigger:** `label:show-notes -label:processed`

**Step 1 — Find the matching email and show**

Find the matching calendar event and `live_shows_current.tsv` row.

**Step 2 — Update the calendar event**

Append spending and setlist info. Only for upcoming or same-day events — never past shows.
Per **`CALENDAR_WORKFLOWS.md` → Updating a show event**.

**Step 3 — Append to `spending.tsv` MANDATORY — DO NOT SKIP**

Per **`DATA_WRITE_PROTOCOLS.md` → `spending.tsv` write protocol**.
Commit to `main` in `dan2bit/live-shows-private`.

**Step 4 — Update autograph records (if applicable)**

If book autograph: update `autograph_books_combined.tsv` — set RHBS/APS Signed to Yes.

If hat autograph:
1. Update `hat_signatures.tsv` — append a row: next `seq`, signer, attribution, show_date, venue (leave region/photo_ref/legible blank). This is the canonical record. The `artists.tsv Hat Autograph` column is **deprecated** (#115, 2026-07-07) — do not set it.
2. Update `data/show_goals/hat_eligibility.tsv` — if the signer is a band member or
   backing singer of a `No`-rated act, flip that act to `Yes` with a membership `Basis`
   (materialized-exception rule, #115). Basis records membership facts only — never
   signature assertions; completion lives in `hat_signatures.tsv` alone.
3. Remind Dan to manually append to the hat autograph Google Doc
   (https://docs.google.com/document/d/1haKMpfwPWosdPnZXBAAlLUzj3926hoTEH7icg6gTRA8/edit)
   Format: `**[Name]** [*of/w/ Act*] @ [Venue short name] [M/D/YY]`

**Step 5 — Commit public file changes to `staging`**

Per **`DATA_WRITE_PROTOCOLS.md` → `artists.tsv` counting policy**. Files committed:
- `data/live_shows_current.tsv` — status → attended; Setlist, Notes / Memories,
  Artist Interaction filled; also update `dan2bit/live-shows-private → current_private.tsv`
  for actual Food & Bev / Parking / Merch
- `data/artists.tsv` — always included
- `data/show_goals/autograph_books_combined.tsv` — if a book was signed
- `data/show_goals/hat_signatures.tsv` — if the hat was signed
- `data/show_goals/hat_eligibility.tsv` — if a membership exception was flipped or a new artist row was added

Commit message: `post-show: [Artist] [YYYY-MM-DD]`

**Step 5b — Times Seen reconciliation (MANDATORY, blocking)**

Before writing the activity log draft or applying `processed`, reconcile the ledger
against `artists.tsv`'s manual count columns for **every artist on this show's bill** —
headliner + support + any combined-bill components. Run
`python3 scripts/build_artist_index.py` (the builder is the source of truth for the
count: it recomputes from `history/*.tsv` + `live_shows_current.tsv` attended +
`seen_with.tsv`, deduped by date, with combined-bill components attributed via the
`Via` column). For each bill artist, compare the builder's `seen.count` / `first` /
`recent` against `Times Seen` / `First Seen` / `Most Recent Seen` in `artists.tsv`.
This is a positive verification step, not a re-statement of Step 5 — it exists
specifically to catch the drift class in #119, where Step 5 committed `artists.tsv`
but a recent attended show or a support-slot appearance never got tallied into
`Times Seen` (the same "the count and its reconciliation are a single unit of work"
treatment Step 8 gives the calendar event in Routine 1).

- **All bill artists match:** proceed to Step 6.
- **Mismatch found (undercount):** correct `Times Seen` / `First Seen` /
  `Most Recent Seen` in `artists.tsv` now and re-commit to `staging` — this is still
  Routine 2's job, not a deferred cleanup item. Note the correction in the log.
- **Overcount from a notes-only sighting** (a show that exists only in a prose Notes
  field, not a structured Artist/Support row): the builder correctly can't count it —
  do **not** edit the count down. Flag it in the activity log instead.

**This step cannot be skipped even if Step 5 "looked" successful in conversation.**
When the `--check` audit primitive from #119 (`feat/times-seen-audit`) lands, this step
switches to running that — a fast, exit-non-zero mismatch report — instead of a full
build + manual compare.

**Step 6 — Open a GitHub issue for YouTube playlist creation; update setlists JSON if MULTI**

**Single-setlist shows:** Open one issue. Title: `Playlist: [Artist] — [YYYY-MM-DD] ([Venue short name])`. Label: `playlist`. Body includes show details and notes. Skip if no footage.

**MULTI shows (two or more setlist.fm links provided):**

1. Set `Setlist.fm URL` in `live_shows_current.tsv` to `MULTI:YYYY-MM-DD` (the show date).
2. Open **one combined playlist issue** — title as above; include all setlist.fm links in the body (support acts first, headliner last).
3. Update `data/setlists/<year>.json` by appending an entry keyed on `YYYY-MM-DD`:

```json
"YYYY-MM-DD": {
  "event": "[Headliner] w/ [Support]",
  "setlists": [
    { "artist": "[Support Act]", "url": "https://www.setlist.fm/setlist/..." },
    { "artist": "[Headliner]", "url": "https://www.setlist.fm/setlist/..." }
  ]
}
```

   Order: support acts first (in bill order), headliner last. Fetch a fresh SHA for the year file and commit to `staging` alongside the other Routine 2 changes. If Dan says "make only one playlist issue for the combined show," that is this step.

**Step 6b — Open a GitHub issue for the artist-photo row (when a photo was taken)**

When the notes indicate Dan got a photo with an artist (`Artist Interaction` is `Photo` or `Both`, or the note describes one), open one issue per photographed artist. Title: `Photo: [Artist] — [YYYY-MM-DD] ([Venue short name])`. Label: `photo`. Body includes the artist, show date, venue, and any caption detail. This mirrors the `playlist` reminder in Step 6 — the Google Photos share link is added to the issue body later, and closing the issue with `Photo: <share link>` in the body will trigger `close-photo-issue.yml` (#131 item 4), which appends the row to `data/show_goals/artist-photos.tsv` (`Date | Share Link | Caption`, header BOM preserved). Until that writer lands, append the row by hand. Do **not** touch `artists.tsv` — the `Photo` column is removed (#131); `artist-photos.tsv` is the sole photo record.

**Step 7 — Activity log draft** (subject: `[LOG] Routine 2 — [Artist] post-show — YYYY-MM-DD`)

**Final:** Apply `processed` label.

---

## Routine 3 — Pre-Sale / On-Sale Alert

**Trigger:** `label:ticket-alert -label:processed`

**Step 1 — Parse the email**

Classify each artist mention:

**Case A — Tickets already on sale:** Filter to Strong/Medium tier artists, apply the
calendar conflict rule, present tiered recommendations with ticket links.

**Case B — Specific future on-sale time given:** Strong tier only, confirmed open date,
apply the calendar conflict rule before creating an on-sale reminder (Step 4).

**Calendar conflict rule (mandatory before any recommendation or potentials write):**

- **Timed show already booked:** skip silently.
- **All-day `NO SHOWS` block:**
  - Strong tier → add Pass row with `Watching For` = `[block description] calendar conflict [date range]`
  - Medium or lower → skip silently.
- **Date open:** proceed.

**Songkick note:** If a show surfaces first or exclusively on Songkick (not yet on BIT,
Seated, or venue site), flag the source provenance in the recommendation summary.
Do not suppress — just note it.

**IMP newsletter:** Flag any Atlantis show featuring a local DC artist as a gift card
opportunity.

**New venue first-contact note:** A venue's first-ever email typically arrives
unlabeled (and may land outside Primary) — Dan only adds the Gmail filter that applies
`ticket-alert` automatically after confirming receipt of that first email. So if a
known/expected venue is suspected of having emailed but nothing surfaces under
`label:ticket-alert -label:processed`, check unlabeled inbox mail from that sender
before concluding there's nothing new — the absence of the label doesn't mean the
absence of the email.

**Step 2 — Cross-reference current shows and potentials**

Using Step 0b data, for every artist/show surfaced:

1. **In `live_shows_current.tsv` (upcoming):** skip silently.
2. **In `live_shows_potential.tsv`:**
   - Pass → skip silently
   - Buy → remind Dan to complete the purchase
   - Choose → surface as normal recommendation
   - Not present → check `fast_track.tsv` first (per `DATA_WRITE_PROTOCOLS.md → fast_track.tsv protocol`)

**Confirmation required before any potentials write.** Present the full proposed set
(new rows, updates, date-pruning removals) and wait for explicit confirmation.

**Date pruning:** Identify past-dated rows in `live_shows_potential.tsv` using the Step
0a date. Include in the confirmation step. After removing a past-dated row, check
`artists.tsv`, `follows_master.tsv`, and `new_artist_research.tsv` — if absent from
all three, add to `new_artist_research.tsv`.

**Pass-prune / NAR triage:** Never create an NAR row for an artist already in
`artists.tsv` or `follows_master.tsv`. For festival/multi-artist events, triage the
actual setlist.fm bill (not the marketing slug) and add only untracked artists as
individual rows.

**Hat eligibility upkeep:** any step that adds a new artist row to `artists.tsv`,
`fast_track.tsv`, or `follows_master.tsv` also adds a `data/show_goals/hat_eligibility.tsv`
row (`Yes`/`No` per the #115 semantics; ask Dan when uncertain).

**Step 3 — Autograph book check**

For any show recommendation, per Routine 1 Step 3 logic.

**Step 4 — Create on-sale reminder event (Case B only)**

Per **`CALENDAR_WORKFLOWS.md` → Event Type 3**. Title `ON SALE: [Artist]`; start
exactly 5 minutes before on-sale time; description carries a deep-link purchase URL
plus pre-sale code if present; reminders 24 h + 5 min.

**Step 5 — Activity log draft** (subject: `[LOG] Routine 3 — [source(s)] — YYYY-MM-DD`)

**Final:** Apply `processed` label.

---

## Routine 4 — Artist Newsletter

**Trigger:** `label:artist-mail -label:processed`

Also check `in:promotions -label:processed` for unlabeled newsletters that bypassed the
filter — flag for Dan to move and label manually.

**Subscribed artists:** Canonical source is `Direct Mail` column in
`tools/research/follows/follows_master.tsv`.

**Step 1 — Read the emails and cross-reference**

Using Step 0b data, for any DC/MD/VA show date mentioned:

1. **In `live_shows_current.tsv` (upcoming):** skip silently.
2. **In `live_shows_potential.tsv`:**
   - Pass → skip silently
   - Buy → remind Dan to complete the purchase
   - Choose → surface as pending decision reminder
   - Not present → proceed to Step 2

**Step 2 — Classify and act**

Apply the **calendar conflict rule** before any recommendation or potentials write (same
as Routine 3 Step 1). Then:

- Tour announcements / new shows → buy recommendation or on-sale calendar event
- Pre-sale codes → on-sale calendar event with code in description
- New music releases → surface in conversation; no file action

**Step 3 — Autograph book check**

Per Routine 1 Step 3 logic for any DC/MD/VA show recommendation.

**Step 4 — Activity log draft** (subject: `[LOG] Routine 4 — [Artist(s)] newsletter — YYYY-MM-DD`)

**Final:** Apply `processed` label.

---

## Routine 5 — Artist Follow / Signup

**Trigger:** `label:artist-follow -label:processed`

**Reminder suppression rule:** If the show is already in `live_shows_current.tsv` or
`live_shows_potential.tsv`, skip entirely. Apply `processed` directly. No log draft.

**Step 1 — Read the emails**

Apply reminder suppression before proceeding.

**BIT "Just Announced" emails require full HTML body parsing.** The plain-text snippet
is truncated; the full HTML body contains the show date, venue, and purchase link
(encoded as `=3D` in quoted-printable; decode before using). The buy link is masked for
tracking but resolves correctly. Always surface date, venue, and purchase link in
conversation before any potentials write.

**Step 2 — Check `follows_master.tsv`**

- Artist not present → propose a new row for confirmation
- Service not marked → note the discrepancy
- Direct Mail not Y for a signup → set to Y and commit to `staging`

**Step 3 — Recommend follow coverage**

Surface gaps. Confirm before adding to services.

**Step 4 — Process any show content**

Apply the **calendar conflict rule** (Routine 3 Step 1). Check `fast_track.tsv` first
(per `DATA_WRITE_PROTOCOLS.md`), then handle per Routine 4 Step 2.

**Step 5 — Activity log draft** (subject: `[LOG] Routine 5 — [Artist] [source] — YYYY-MM-DD`)

No log draft for pure reminders.

**Final:** Apply `processed` label.

---

## Routine 6 — Ticket Sold (Resale)

**Trigger:** `label:ticket-sold -label:processed`

Filter condition: forwards from `dan2bit@gmail.com` with `sold` in the subject. Covers
AXS resales (Rams Head), StubHub, and Ticketmaster resales.

This is the rarest routine — it fires only when a ticket previously purchased and
tracked in `live_shows_current.tsv` has been resold.

**Step 1 — Parse the sale notification**

Extract: artist, show date, venue, sale price, platform, net proceeds (after fees).

**Step 2 — Update `live_shows_current.tsv`**

Remove the row (or update Status if a partial resale). Commit to `staging`.

**Step 3 — Update `dan2bit/live-shows-private → current_private.tsv`**

Remove or update the matching row (keyed `Show Date` + `Artist`). Commit to `main` in
the private repo.

**Step 4 — Append to `spending.tsv`**

Per **`DATA_WRITE_PROTOCOLS.md` → `spending.tsv` write protocol**. Record the sale as
a negative cost row (net proceeds as a negative Ticket Cost) so the ledger reflects the
offset. Commit to `main` in `dan2bit/live-shows-private`.

**Step 5 — Remove from calendar**

Delete the show event from the Dan Concert Calendar if the resale is complete (no
remaining tickets).

**Step 6 — Activity log draft** (subject: `[LOG] Routine 6 — [Artist] [platform] sale — YYYY-MM-DD`)

**Final:** Apply `processed` label.

---

## Notes

**Inbox monitoring is not automatic.** Trigger routines by saying "there's a ticket
email", "process the inbox", "run Routine 3", etc.

**`data/show_goals/hat_signatures.tsv` is the authority for hat signers.** The gdoc is
the public-facing version (linked from the about modal in `index.html`); on any
discrepancy, reconcile the gdoc to the TSV.

**Google Calendar MCP fails on Android.** Switch to macOS desktop before retrying
calendar operations.

**Songkick ownership:** Songkick was acquired by Suno (AI music generation) in November
2025 as part of a WMG copyright settlement. All Songkick user data transferred to Suno
in April 2026. New artists are followed on BIT and Seated only. See
`tools/research/follows/follows_master.tsv` for current coverage per service.

**YouTube pipeline is separate.** Tracked via GitHub issues (`playlist` label).
Scripts run manually after videos are uploaded to YouTube Studio.
