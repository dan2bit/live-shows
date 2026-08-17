---
name: find-potential-tickets
description: Audit the live-shows potentials Buy and Choose rows for missing price, purchase URL, or event URL, and present one best clickable link per incomplete show. Use when Dan says "find potential tickets", "audit the potentials", "ticket link audit", or asks which Buy/Choose shows are missing prices or links.
---

# Find Potential Tickets — completeness audit for the Buy/Choose lists

Read-only audit of `data/live_shows_potential.tsv` in `dan2bit/live-shows`.
The goal: for every Buy or Choose row missing purchase-decision data, hand Dan
ONE clickable link — whichever gets closest to the full information set — so
each gap is a click away from being filled. This skill never writes anything.

## Step 1 — Fetch fresh

From `dan2bit/live-shows` branch `main` (never a cached copy):

- `data/live_shows_potential.tsv`
- `data/venues.tsv`

## Step 2 — Audit

Consider only rows with `Decision` = `Buy` or `Choose`. **Blank means empty,
the `-` sentinel, or `TBD` (case-insensitive)** — the file uses all three;
treating TBD as populated made a first-draft audit report zero gaps when four
existed. The completeness set is three fields:

- `Face Price`
- `Purchase URL`
- `Event URL`

A row with all three populated is complete — exclude it. For each incomplete
row, pick the **best link** by this priority (first non-blank wins):

1. `Purchase URL` — already the closest thing to checkout
2. `Event URL` — venue's event page, usually one click from tickets + price
3. `BIT URL` — Bandsintown event page
4. venues.tsv `Venue Event Calendar` — join the row's `Venue` against
   `Venue Name` or `Short Name`, case-insensitive
5. Nothing on file at all → flag "no link available — venue not in
   venues.tsv" and suggest adding the venue row (that gap is worth fixing
   regardless of this show)

## Step 3 — Present

Group **Buy first, then Choose** (the file's own order within groups is
already date-ascending — preserve it). One line per incomplete show, link
rendered clickable:

```
[Angélique Kidjo — Sun 4/25/27, GMU Center for the Arts](https://…) — missing: price  (via purchase link) · watching: individual tickets on sale Aug 4
```

- The link text carries artist, day/date, venue; the `(via …)` tag says which
  priority tier supplied the link, so a venue-calendar fallback is visibly
  weaker than a purchase link.
- Show the `Watching For` value inline when non-blank — an on-sale date
  explains WHY data is missing and when to look.
- End with a two-line summary: N of M Buy/Choose rows incomplete; which venues
  (if any) need venues.tsv rows.

## Boundaries

- Read-only: no TSV writes, no web fetches, no filling fields. If Dan comes
  back with prices/URLs to record, that is a normal potentials write —
  fresh SHA, re-sort Buy → Choose → Sell → Pass, commit to `staging`,
  confirmation first, per `tools/playbooks/DATA_WRITE_PROTOCOLS.md`. Private
  purchasing notes (promo codes, fee tricks) go to the private repo's
  `potential_private.tsv`, never the public file.
- Do not invent or search for links this pass — the audit reports what is on
  file. (Researching missing links is a fine FOLLOW-UP if Dan asks, but the
  audit itself must reflect file state so gaps stay visible.)
