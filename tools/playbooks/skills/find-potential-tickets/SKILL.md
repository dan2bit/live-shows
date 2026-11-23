---
name: "find-potential-tickets"
description: "Audit the live-shows potentials Buy and Choose rows for missing price, purchase URL, or event URL, and present one best clickable link per incomplete show. Use when Dan says \"find potential tickets\", \"audit the potentials\", \"ticket link audit\", or asks which Buy/Choose shows are missing prices or links."
---

# Find Potential Tickets — completeness audit for the Buy/Choose lists

Read-only audit of `data/live_shows_potential.tsv` in `dan2bit/live-shows`.
The goal: for every Buy or Choose row missing purchase-decision data, hand Dan
ONE clickable link — whichever gets closest to the full information set — plus
the venue's known URL pattern, so each gap is a click (or one targeted search)
away from being filled. The audit itself never writes anything.

The link policy this skill enforces is the **Event URL Rule** in
`tools/playbooks/EMAIL_WORKFLOWS.md` and the "Buy and Choose rows need both
links" paragraph in `tools/playbooks/DATA_WRITE_PROTOCOLS.md`. If those and
this skill disagree, the playbooks win.

## Step 1 — Fetch fresh

From `dan2bit/live-shows` branch `main` (never a cached copy):

- `data/live_shows_potential.tsv`
- `data/venues.tsv` — read columns by header name, not position. The ones used
  here: `Venue Name`, `Short Name`, `Venue Event Calendar`,
  `Event URL Pattern`, `Purchase URL Pattern`.

## Step 2 — Audit

Consider only rows with `Decision` = `Buy` or `Choose` (Sell rows carry Dan's
own resale listing and are out of scope; Pass rows need no links).
**Blank means empty, the `-` sentinel, or `TBD` (case-insensitive)** — the file
uses all three; treating TBD as populated made a first-draft audit report zero
gaps when four existed.

The completeness set is three fields, each checked for presence AND quality:

- `Face Price` — gap if blank.
- `Purchase URL` — gap if blank, or if it is a **reseller or aggregator**
  (StubHub, Vivid Seats, SeatGeek, TicketSmarter, Gametime, JamBase, Songkick,
  Bandsintown, or a tracking redirect through any of them). Primary sellers are
  fine: Ticketmaster, AXS, Eventim/See Tickets, Opendate, Eventbrite, Dice,
  Etix, InstantSeats, Tixr, the venue's own box-office page, Union Stage
  Presents show pages.
- `Event URL` — gap if blank, if it is a reseller or aggregator, or if it is
  **generic**: a site root or listing page (`/calendar/`, `/shows`,
  `/events/`, `/upcoming`), including an exact match for the venue's
  `Venue Event Calendar`. A calendar URL here is the playbook's known
  placeholder fallback — report it as "calendar placeholder", a softer gap
  than blank, but still a gap until a child page replaces it. A URL is
  specific when its path names this one event (a slug or event ID).
  Union Stage Presents `/shows/<slug>` pages are specific and may
  legitimately equal the Purchase URL.

A row with all three populated and passing is complete — exclude it.

For each incomplete row, join `Venue` against venues.tsv `Venue Name` or
`Short Name` (case-insensitive) and pick the **best link** by this priority
(first usable wins; a reseller/aggregator link is never usable):

1. `Purchase URL` — already the closest thing to checkout
2. `Event URL` if specific — the venue's event page, usually one click from
   tickets + price
3. `BIT URL` — Bandsintown event page (acceptable as an audit *pointer* to
   find the real page, never as a value to write)
4. venues.tsv `Venue Event Calendar` (this also covers a calendar-placeholder
   Event URL)
5. Nothing on file at all → flag "no link available — venue not in
   venues.tsv" and suggest adding the venue row (that gap is worth fixing
   regardless of this show)

## Step 3 — Present

Group **Buy first, then Choose** (the file's own order within groups is
already date-ascending — preserve it). One line per incomplete show, link
rendered clickable:

```
[Angélique Kidjo — Sun 4/25/27, GMU Center for the Arts](https://…) — missing: price  (via purchase link) · watching: individual tickets on sale Aug 4
[Example Artist — Fri 1/8/27, The Birchmere](https://…) — missing: event page (calendar placeholder), purchase  (via venue calendar) · pattern: birchmere.com/events/<artist-slug>/
```

- The link text carries artist, day/date, venue; the `(via …)` tag says which
  priority tier supplied the link, so a venue-calendar fallback is visibly
  weaker than a purchase link.
- Name each gap precisely: `price`, `purchase`, `event page`, or
  `event page (calendar placeholder)`. A reseller/aggregator value is reported
  as `purchase: reseller link — replace` or `event page: aggregator link —
  replace`, naming the site.
- When the missing field has a pattern in venues.tsv, append
  `pattern: <Event URL Pattern or Purchase URL Pattern>` — it tells Dan (or a
  follow-up pass) exactly what shape of URL to look for.
- Show the `Watching For` value inline when non-blank — an on-sale date
  explains WHY data is missing and when to look.
- End with a short summary: N of M Buy/Choose rows incomplete (how many are
  calendar placeholders only); any reseller/aggregator links found; which
  venues need a venues.tsv row; which venues in the gap list have blank
  pattern columns (worth recording next time a link is found).

## Follow-up: filling the gaps (only when Dan asks)

The audit reports file state. If Dan then asks to find the missing links or
prices, research per the Event URL Rule order in `EMAIL_WORKFLOWS.md`:

1. Venue patterns first: a site-restricted search on the venue's domain for
   the URL shape in `Event URL Pattern` / `Purchase URL Pattern`. Use URLs from
   search results or links Dan supplies; guessed URLs are often blocked.
2. The venue calendar's child link for this show.
3. The primary ticketing platform's event page.
4. Still nothing → ask Dan, as a numbered question per show.
5. Only after he has had the chance to answer: Event URL falls back to the
   venue calendar URL, Purchase URL stays `-`.

Rules while researching:

- Never write resellers or aggregators (JamBase, Songkick, StubHub,
  SeatGeek, …) into either column. When the venue page and a seller
  disagree, the venue page wins for Event URL.
- Opendate and Union Stage Presents pages carry a hidden "SOLD OUT" SVG on
  every event page — never infer sold-out (or anything else) from SVG markup;
  read visible text only.
- Strip session parameters (`utm_*`, `fbclid`, `CFID`, `CFTOKEN`); keep
  event-identifying ones (InstantSeats `eventid`, Eventim `afflky`).
- Prices: record what the primary seller shows, with the source in the cell
  when it is a range (e.g. `$41-$282 (Ticketmaster)`).

Writing what was found is a normal potentials write, with confirmation first:
fetch a fresh SHA, write every column (`-` for empty), keep data files ASCII,
re-sort Buy → Choose → Sell → Pass, run `python3 scripts/validate_potential.py`,
commit to `staging`, per `tools/playbooks/DATA_WRITE_PROTOCOLS.md`. If a venue's
child-page or ticket-link shape was seen for the first time, add it to that
venue's pattern columns in `data/venues.tsv` in the same commit. Private
purchasing notes (promo codes, fee tricks, box-office tips) go to the private
repo — `dan2bit/live-shows-private → potential_private.tsv`, a separate commit
to that repo's `main` — never the public file.

## Boundaries

- The audit pass is read-only: no TSV writes, no web fetches, no filling
  fields, no searching. It must reflect file state so gaps stay visible.
- Research and writes happen only in the follow-up, only when Dan asks, and
  writes only after his explicit confirmation.
