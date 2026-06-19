## Calendar Workflows — Live Show Archive

All Google Calendar management for the live-shows project. The email routines in
`EMAIL_WORKFLOWS.md` decide **when** an event is created or updated; this file is the
authority on **how** each event is built.

There are exactly three event types on the Dan Concert Calendar:

1. **Show events** — one timed event per confirmed/purchased show.
2. **NO SHOWS blocks** — all-day or multi-day blocks marking dates when no tickets should be bought.
3. **Ticket purchase (on-sale) events** — timed reminders that fire just before tickets go on sale.

---

## Common Rules (all event types)

- **Calendar:** always `redhat.bootlegs@gmail.com` ("Dan Concert Calendar"). Never use `primary`.
- **Time first.** Call `time:get_current_time` (`America/New_York`) before any date-relative
  calendar action — availability checks, on-sale timing, "days until" math. The time MCP is the
  sole authority on the current date.
- **Search fallback.** If a calendar `q` search returns nothing, fall back to a date-bounded listing.
- **Never edit past events.** Calendar edits apply only to upcoming or same-day events. Past
  events are read-only.
- **Autograph book check is a hard pre-condition for show events.** Before creating any show
  event, look up the headliner and known supporting acts in `autograph_books_combined.tsv`.
  No show event without the check. (See per-type detail below.)
- **Prev/Next Show belongs in `live_shows_potential.tsv` only** — never in calendar event
  descriptions.
- **Confirm before creating a calendar event for an unpurchased show.**
- **Google Calendar MCP fails silently on the Android app.** Run calendar operations from a
  macOS desktop browser session. If an operation fails, ask Dan to switch to desktop and retry.

---

## Calendar Availability / Conflict Definition

**A date is unavailable if it has either:**
- a **timed show event** (any show already booked), or
- an **all-day `NO SHOWS` block**.

Always query for both timed and all-day events on the target date — and, for density
judgment, adjacent dates. Same-night conflicts are hard stops; adjacent-night conflicts are
density warnings for Dan to weigh.

The email routines layer their own recommendation logic on top of this definition (e.g. adding
a Pass row when a Strong-tier show collides with a NO SHOWS block). That routine-specific
handling lives in `EMAIL_WORKFLOWS.md`; this file defines only what makes a date unavailable.

---

## Event Type 1 — Show Events

One timed event per confirmed show. Created in Routine 1 (ticket purchase) and updated in
Routine 2 (post-show notes), or on direct request from Dan at any time.

### Title

- Single electronic ticket, no other suffix: `[Artist]` (omit the count)
- Multiple tickets or PAPER/VIP: `[Artist] (N)`, `[Artist] (N PAPER)`, `[Artist] (N VIP)`
- VIP package: append `(VIP)`

### Location — REINFORCED

The Location field feeds driving directions, so it must point to **where Dan actually parks**,
not the venue door.

- **Venues WITHOUT on-site parking** (e.g. Rams Head On Stage, Hamilton Live, Warner Theatre,
  9:30 Club, and any other venue whose `venues.tsv` **Parking** column holds a separate lot
  address): set Location to the **parking-lot street address** from `venues.tsv` (column 4,
  Parking). Strip the lot name / validation notes after the em-dash and use the clean street
  address so directions route to the lot, not the venue.
  - Example: Rams Head → `25 Calvert St, Annapolis, MD 21401` (not `33 West St`).
  - Example: Hamilton Live / Warner Theatre → `1325 G St NW, DC 20005`.
- **Venues WITH on-site parking** (`venues.tsv` Parking = `On site…`): set Location to the
  venue street Address (column 2). On-site lot and venue door are effectively the same drive.

Always read the venue's Parking field from `venues.tsv` to decide — do not assume.

### Description

```
BRING RHBS -- [Artist] p.[N]          <- only if in autograph book, not yet signed

[Order # / Ref] ([Ticketer])
Ticket access: [method]
Payment: [card/method] / Face $X.XX / Fees $X.XX / Total $X.XX
[Supporting act line if applicable]
[Any special notes]

[Seat / GA info]
Doors: [time] / Show: [time]

High ticket cost -- cool it on merch tonight   <- face value >= $100, NOT VIP, NOT Wolf Trap Filene
```

**Autograph reminder lines** (from the `autograph_books_combined.tsv` check):
- In **RHBS** and not yet signed → prepend `BRING RHBS -- [Artist] p.[N]`
- In **APS** and not yet signed → prepend `BRING APS -- [Artist] p.[N]`
- Already signed → no reminder.

**Hat signing eligibility:** female or female-presenting artists only, or bands with female
members. Verify gender via web search if unknown; do not infer. Confirm she has not already
signed the hat in `autograph_books_combined.tsv` before flagging.

**Merch caution line:** add only when face value per ticket ≥ $100, AND not VIP, AND not Wolf
Trap Filene Center. Evaluated per ticket — never on the order total for multi-ticket orders.

### Reminders

24 hours (1440 min) and 3 hours (180 min) popup.

### Venue timing defaults

| Venue | Doors | Show | Notes |
|-------|-------|------|-------|
| The Birchmere | 5:00 PM | 7:30 PM | GA; seating begins 6:30 PM; always free parking |
| Hamilton Live | 6:30 PM | 8:00 PM | $13 parking |
| Rams Head On Stage | 1 hr before show | -- | -- |
| Wolf Trap Filene Center | -- | -- | Use ticket for times |

"An Evening With" billing means no supporting act.

### Updating a show event (Routine 2 — post-show)

Append spending and setlist info to the existing event. Upcoming or same-day events only —
never past shows.

---

## Event Type 2 — NO SHOWS Blocks

All-day or multi-day calendar events marking periods when no tickets should be bought —
travel, family commitments, recovery time, or voluntary show-density limits.

- **Always all-day or multi-day** — never a timed event.
- **Title:** `NO SHOWS`.
- **The block carries a note explaining the reason** in its description (e.g. "out of town",
  "Beach Week", "rest — too many recent shows"). The reason text is what the email routines
  quote when recording a calendar-conflict Pass row, so keep it short and descriptive.
- Created on request from Dan. The email routines never create NO SHOWS blocks — they only
  read them during availability/conflict checks.

A date covered by a NO SHOWS block counts as unavailable (see Calendar Availability above).

---

## Event Type 3 — Ticket Purchase (On-Sale) Events

Timed reminders that fire just before tickets go on sale. Created in Routine 3 (Case B — a
specific future on-sale time is given), Strong-tier artists only, after the conflict check —
or on direct request from Dan at any time.

### Title

`ON SALE: [Artist]`

### Timing — REINFORCED

- **Start time = exactly 5 minutes BEFORE the tickets go on sale.** The event must lead the
  on-sale moment so Dan is in front of the purchase page before the queue opens.
- Duration: 15 minutes.

### Description — REINFORCED

Must include a **deep-link purchase URL** — the direct link to the specific event's purchase
page on the ticketing platform, not a venue homepage or a generic search.

```
[Deep-link purchase URL]
Pre-sale code: [CODE]    <- only if present
```

If the only link available is a redirect / email-tracking URL, resolve it to the real venue
ticketing-platform event URL and present it to Dan for confirmation before committing the event.

### Reminders

24 hours and 5 minutes.

---

## Cross-References

- `EMAIL_WORKFLOWS.md` — when each event is created/updated within the five inbox routines.
- `venues.tsv` — Parking column (4) drives the Location rule for show events.
- `autograph_books_combined.tsv` — the hard pre-condition check for show events.
- `AGENTIC_WORKFLOWS.md` — architectural overview of calendar integration.
