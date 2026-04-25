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

**Template (IMP/9:30 Club filter — already created, use as reference):**
- From: `@imppresents.com`
- Apply label: `ticket-alert`

---

## Venue Newsletter Subscriptions

Subscribe **redhat.bootlegs@gmail.com** to these. Apply `ticket-alert` label via Gmail
filter on the sender address once subscribed.

### Subscribed ✅

| Venue | Notes |
|-------|-------|
| The Birchmere | |
| Hamilton Live | |
| Rams Head On Stage | |
| The State Theatre | |
| Collective Encore | |
| Union Stage Presents (Jammin' Java, Union Stage, Pearl Street, Howard Theatre) | |
| Wolf Trap — wolftrap.org | Email alerts |
| 9:30 Club / Merriweather / other IMP venues | imppresents.com |
| Bethesda Theater | Re-targeted 2026-04-01 via Constant Contact |
| Ticketmaster newsletter | Forwarded from dan2bit |

### Pending — fresh signup needed under redhat.bootlegs ⚠️

| Venue | Notes |
|-------|-------|
| Hub City Vinyl (Hagerstown) | liveathubcityvinyl.com · Mailchimp; email change not supported, requires new signup |
| Strathmore | strathmore.org |
| Capital One Hall | capitalonehall.com |
| The Fillmore Silver Spring | fillmoresilverspring.com |

---

## Artist Newsletter Subscriptions

Canonical source: `Direct Mail` column in `follows/follows_master.tsv`.

### Subscribed ✅

Albert Castiglia, Allison Russell, Amythyst Kiah, Buffalo Nichols, Bywater Call,
Christone 'Kingfish' Ingram, Daniel Donato, Ghalia Volt, Jackie Venson, Judith Hill,
Larkin Poe, The Lone Bellow, Mike Zito, Robert Randolph, Ruthie Foster, Samantha Fish,
Shemekia Copeland, Southern Avenue, Sue Foley, Taj Farrant, Tal Wilkenfeld,
Trombone Shorty & Orleans Avenue, Vanessa Collier, The War and Treaty.

### Not subscribed — known reasons

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
Artist follow list: managed via `follows/follows_master.tsv` (BIT column)
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

Venues successfully re-targeted: Bethesda Theater (2026-04-01, Constant Contact).
Venues pending re-targeting: Hub City Vinyl (Mailchimp, requires new signup).

---

## Autograph Book Reference

**RHBS** (Red Hat Book of Shows) — primary autograph book
**APS** — secondary autograph book

Source file: `autograph_books_combined.tsv`
Google Drive ID: `1ENPcmHxrbdMfJNuDlqy-RRBHkGm8Onyy`

**Hat autograph Google Doc:**
https://docs.google.com/document/d/1haKMpfwPWosdPnZXBAAlLUzj3926hoTEH7icg6gTRA8/edit

Format for hat entries: `**[Name]** [*of/w/ Act*] @ [Venue short name] [M/D/YY]`

No write connector exists for Google Docs — all hat autograph gdoc updates are manual.
The gdoc is the completeness authority for hat signers; TSV files are the authority
for show dates.
