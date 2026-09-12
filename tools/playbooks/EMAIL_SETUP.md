# Email Setup — Live Show Archive

Infrastructure reference for the redhat.bootlegs@gmail.com Gmail account. Covers
label setup, filter configuration, and mailing list subscriptions. This document is
for setup and auditing — not needed during routine inbox processing. See
`EMAIL_WORKFLOWS.md` for the operational routines.

---

## Gmail Label Configuration

### Labels in use

| Label | ID | Applied by | Used in |
|-------|----|------------|---------|
| `processed` | `Label_421272830174798850` | Manual (after each routine) | All routines |
| `ticket-alert` | `Label_8111132848568068688` | Manual or filter | Routine 3 |
| `show-notes` | `Label_4852367418911615829` | Filter (subject + from: match) | Routine 2 |
| `ticket-receipt` | `Label_8008139800288276097` | Manual (or future filter) | Routine 1 |
| `artist-mail` | — | Manual or filter | Routine 4 |
| `artist-follow` | — | Filter (BIT/Songkick) or manual | Routine 5 |

### Gmail filters to create

For each venue newsletter sender, create a filter:
- **Matches:** `from:[sender address]`
- **Do this:** Apply label `ticket-alert`, Skip Inbox (optional — keeps Primary clean)

For each artist newsletter sender, create a filter:
- **Matches:** `from:[sender address]`
- **Do this:** Apply label `artist-mail`, Skip Promotions

Bandsintown and Songkick sender addresses should be filtered to `artist-follow`.

The `show-notes` label is applied by a filter matching subject keywords combined with
`from:dan2bit` — catches post-show note emails forwarded from the dan2bit account.

The `ticket-receipt` label is applied manually before a processing request, or can be
automated with a filter on subject keywords (e.g. "ticket purchase", "ticket receipt").

**Template (IMP/9:30 Club filter — already created, use as reference):**
- From: `@imppresents.com`
- Apply label: `ticket-alert`

---

## Venue Newsletter Subscriptions

**Subscription state is not tracked here.** It lives in `data/venues.tsv`, where it
can be checked against the inbox instead of asserted. This section explains the
schema and the signup quirks; the current state is always the file.

### Where it lives

Three columns, replacing the old free-text `Calendar Coverage` (2026-09):

| Column | Values |
|---|---|
| `Coverage` | pipe-separated: `hftb`, `email`, `scrape`, `watch`, `artist-platform`, `none` |
| `Newsletter Source` | the sending domain, e.g. `info.impconcerts.com` |
| `Subscription` | `flowing`, `awaiting`, `unconfirmed`, or blank |
| `Coverage Checked` | ISO date the row was last verified against the inbox |

`Coverage` is multi-valued because most venues have more than one channel - Blues
Alley reads `hftb|email|watch`.

### Why `Newsletter Source` is separate from the venue

Several subscriptions cover **multiple rooms from one sender**, which the old
single-column format could not express:

| Sender | Covers |
|---|---|
| `info.impconcerts.com` | 9:30 Club, The Anthem, Lincoln Theatre, Merriweather |
| `unionstagepresents.com` | Union Stage, Pearl Street Warehouse, Jammin' Java |
| `r2.arts-mail.com` | Weinberg Center for the Arts, New Spire Arts |
| `music.ramsheadonstage.com` | Rams Head On Stage, Maryland Hall |

So "is this venue covered" is a question about the sender, not the venue name.

### The three subscription states, and why they are distinct

All three are attested in the current data, and only the first is really coverage:

- **`flowing`** - newsletters arriving. Verifiable: search the inbox for the sender.
- **`awaiting`** - signup confirmed, no newsletter yet. A welcome mail arrived and
  nothing since.
- **`unconfirmed`** - subscribed as far as we know, but nothing has ever arrived from
  that sender, not even a welcome.

The distinction matters because `Calendar Coverage` had been recording **intent**
rather than observed coverage since the mid-2026 subscription burst - values written
when subscribing, never reconciled against what actually arrived. An audit found six
of its claims wrong in one direction or the other.

### Verifying

Search the inbox by sender domain and update `Subscription` and `Coverage Checked`.
`Coverage Checked` is the column that makes staleness visible; without a date, a
wrong value is indistinguishable from a current one.

Two cautions from the audit that produced this schema:

- **Resolve venue names through `data/venue_aliases.tsv` first.** HFTB and the
  newsletters spell rooms differently (`The Hamilton` / `Hamilton Live`,
  `Songbyrd DC` / `Songbyrd Music House`). Normalization folds case, a leading
  "The" and punctuation - it does **not** bridge word-level differences.
- **Page the whole search window.** A first page of Gmail results is not 90 days;
  a venue mailing fortnightly can fall outside it and read as silent.

### Signup quirks worth remembering

Operational notes, not status:

| Venue | Note |
|---|---|
| Hub City Vinyl | Mailchimp; email change not supported, requires a fresh signup |
| Bethesda Theater | Re-targeted 2026-04-01 via Constant Contact |
| Rams Head On Stage | Two lists: `mail@restaurant.ramsheadgroup.com` is the hospitality list (beer releases, festivals) and is **not** show announcements; `hello@music.ramsheadonstage.com` is the ticket-alert list |
| Blues Alley | Mail arrives reliably but is an image with no parseable text - the changedetection watch exists to supply the content the mail withholds |
| Sixth & I | The mail on file is an **account registration**, not a newsletter signup - weaker evidence than a "thanks for subscribing" confirmation |
| Ticketmaster | Forwarded from dan2bit rather than subscribed directly |

---

## Artist Newsletter Subscriptions

Canonical source: `Direct Mail` column in `tools/research/follows/follows_master.tsv`.

The list of who is subscribed is **not duplicated here** - it drifts from the
column the moment either changes. Filter `follows_master.tsv` on `Direct Mail`
instead.

### Not subscribed — known reasons

Kept here because these are *reasons*, which the column has nowhere to store:

| Artist | Reason |
|--------|--------|
| Enter the Haggis | Defunct; follow Haggis X-1 and House of Hamill instead |
| Eric Gales, Selwyn Birchwood, Valerie June, Ana Popović | No email list found |
| Kingsley Flood, Oh He Dead | Too small/hyperlocal; shows caught by venue newsletters |
| Ally Venable | Uses Patreon instead of email list |

---

## Follow Services

### Bandsintown

Account: **rhbl** (redhat.bootlegs@gmail.com)
Gmail filter: BIT sender addresses → `artist-follow` (auto-labeled, no manual action)
Artist follow list: managed via `tools/research/follows/follows_master.tsv` (BIT column)
Worklist: `web-src/rhbl-bandsintown.tsv`

### Songkick

Gmail filter: Songkick sender addresses → `artist-follow` (auto-labeled)

### Seated

Account: rhbl
Alert emails → `ticket-alert` (not `artist-follow`) — treated as ticket-sale notifications
Artist follow list: audit against Strong-tier artists in `artists.tsv` periodically

---

## Ticketing Platform Notes

| Platform | Venues | Account | Notes |
|----------|--------|---------|-------|
| AXS | Rams Head On Stage | rhbl | Mobile app; paper ticket at box office saves fees |
| Opendate | Jammin' Java, Union Stage, Pearl Street, Howard | rhbl | Never infer sold out from SVG badge — text only |
| Eventim / See Tickets | Hamilton Live, Hub City Vinyl | rhbl | Remind Dan to photo barcode for Google Wallet |
| Eventbrite | Collective Encore | rhbl | Remind Dan to photo barcode for Google Wallet |
| Ticketmaster SafeTix | 9:30 Club, Wolf Trap (some), general | dan2bit+ticketmaster | Mobile only; newsletter forwarded to rhbl |
| Wolf Trap | Wolf Trap Filene Center | rhbl | Paper ticket (donor); no fees |
| HyltonCenter.org | Hylton Performing Arts Center | rhbl | Own platform |

---

## Subscription Management: Re-targeting to redhat.bootlegs

When processing a forwarded email that was sent to dan2bit rather than rhbl,
scan the email footer for a subscription management link:

- **Constant Contact:** "Update Profile" link — allows direct email address change
- **Mailchimp:** "Update your preferences" link — may or may not allow email change;
  if locked, do a fresh signup at the venue website under rhbl
- **Other providers:** note the sender address if no management link is found

Which venues still need re-targeting is derivable rather than listed: a venue whose
`Subscription` in `venues.tsv` is not `flowing`, or whose `Newsletter Source` is
blank while mail arrives at dan2bit, is a candidate. Do not keep a list here - the
last one went stale (it named Hub City Vinyl as pending long after
`mail.liveathubcityvinyl.com` began arriving at rhbl).

---

## Autograph Book Reference

**RHBS** (Red Hat Book of Shows) — primary autograph book
**APS** — secondary autograph book

Source file: `autograph_books_combined.tsv`
Google Drive ID: `1ENPcmHxrbdMfJNuDlqy-RRBHkGm8Onyy`

**Hat autograph Google Doc:**
https://docs.google.com/document/d/1haKMpfwPWosdPnZXBAAlLUzj3926hoTEH7icg6gTRA8/edit

Format for hat entries: `**[Name]** [*of/w/ Act*] @ [Venue short name] [M/D/YY]`
Hat signatures TSV: `data/show_goals/hat_signatures.tsv` (per-signature; `seq` matches the gdoc order).

No write connector exists for Google Docs — all hat autograph gdoc updates are manual.
The gdoc is the completeness authority for hat signers; TSV files are the authority
for show dates.
