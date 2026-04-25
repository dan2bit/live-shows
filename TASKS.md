# live-shows — Archive Task List

Collaborative task list for the live show archive project.

---

## 🎟 Standing Checks — Every Inbox Session

### A. Potential shows monitoring

At the start of every inbox processing session, open `live_shows_potential.tsv`
and apply the following checks to any row that has a value in the `Watching For` column:

**If `Watching For` = `low ticket / sold out`** (applies to any `Buy` row):
- Check the ticket URL in `Purchase URL` for current availability
- Also watch for venue/artist emails arriving at redhat.bootlegs@gmail.com mentioning
  the show
- Alert Dan immediately if low ticket warning or sold-out status is detected

**If `Watching For` contains `closer` (applies to `Pass` or `Choose` rows):**
- Scan new emails and newsletters in this session for announcements of a show by
  the same artist at a DC/MD/VA venue, or any venue closer/more convenient than the
  one in the file
- If a closer show is found, surface it as a buy recommendation and note the
  trade-off vs. the existing entry

**Date pruning:** Remove any row whose show date has already passed, regardless of
Decision value. Purchased shows are removed via Routine 1 (Step 6) when the ticket
is confirmed. Unpurchased rows (Buy, Choose, Pass) are removed here once the date
has passed — the opportunity is gone.

Current rows with `Watching For` values (update this list as rows are added/resolved):

| Artist | Decision | Watching For | Ticket URL |
|--------|----------|--------------|------------|
| Taj Mahal | Buy (paper @ Lyle Lovett) | low ticket / sold out | https://www.ticketmaster.com/event/15006470A6EE71A1?brand=birchmere |
| Carolyn Wonderland | Buy | closer DC/MD show | https://www.eventbrite.com/e/carolyn-wonderland-tickets-1983173922588 |
| Christone 'Kingfish' Ingram | Pass | closer headliner show | https://www.ticketmaster.com/christone-kingfish-ingram-harrisburg-pennsylvania-05-21-2026/event/02006453C19ACCCD |
| JD Simo & Luther Dickinson | Pass | closer show | https://www.eventbrite.com/e/bluesamericana-with-jd-simo-luther-dickinson-tickets-1970731399667 |

### B. Potential shows list

See `live_shows_potential.tsv` for the full list of uncommitted shows with
ticket links, pricing, and notes. The `Watching For` column is the authoritative source
for what needs monitoring — the table above is kept in sync with it.

**Schema:** Artist | Support | Date | Decision | Watching For | Venue | Venue City | Tier |
Ticket Service | Purchase URL | Event URL | Face Price | Fees Notes | Availability Notes |
Prev Show (2026) | Next Show (2026) | Notes

**Decision values:** `Buy`, `Buy (paper @ [show])`, `Choose`, `Sell`, `Pass`

**Sort order:** Primary sort alpha on Decision (`Buy` → `Choose` → `Sell` → `Pass`),
secondary sort by show date ascending within each group.

**`Sell` decision:** Read-only — applied when tickets for a confirmed show have been
listed for resale. Cannot be set via the index.html dropdown. Requires manual Claude
operation touching both `live_shows_current.tsv` and `live_shows_potential.tsv`.

**Maintenance rules:**
- **Purchased:** remove via Routine 1 Step 6 when ticket confirmed
- **Date passed:** remove the row regardless of Decision — the opportunity is gone
- **Undecided:** use `Choose` (never leave Decision blank)

**Watching For values:** `low ticket / sold out`, `closer [description]`, or blank

---

## 📋 Open Issues

Project tasks are tracked as GitHub issues. See the [issues list](https://github.com/dan2bit/live-shows/issues) for full details.

| # | Title | Labels |
|---|-------|--------|
| [#3](https://github.com/dan2bit/live-shows/issues/3) | Upload found videos and create playlists for 11 no-playlist shows | playlist, backlog |
| [#4](https://github.com/dan2bit/live-shows/issues/4) | Review and potentially include pre-pandemic show history (2002–2019) | research, backlog |
| [#5](https://github.com/dan2bit/live-shows/issues/5) | 📬 Inbox label hygiene — Gmail filter setup and artist follow service audit | backlog |
| [#6](https://github.com/dan2bit/live-shows/issues/6) | Public-facing mode for index.html | enhancement |
| [#7](https://github.com/dan2bit/live-shows/issues/7) | 🔑 UI PAT setup — create, test, and store GitHub token for Decision editing | enhancement |

Per-show YouTube playlist issues are opened automatically by Routine 2 when post-show notes are processed — search issues for `label:playlist` to see the full queue.
