---
name: item-log
description: Add or update items in the live-shows items ledger (data/items.tsv and data/show_goals/item_signatures.tsv) - signed merch, picks, posters, setlists, mail-order and crowdfunded releases, and show mementos. Use whenever Dan mentions getting, finding, receiving, or photographing an item ("I got a pick at last night's show", "Jackie Venson signed my t-shirt", "the CD arrived", "here's the photo link for the set list"), asks to add to the item log or items ledger, or when Routine 2 show-notes processing surfaces a signed item or memento. Do NOT use for hat signings or autograph-book signatures - those have their own event logs - or for Bandcamp purchases, which are imported from the Bandcamp export.
---

# Items Ledger - Additions and Updates

Maintains the items ledger in `dan2bit/live-shows` (public repo, commits to
`staging`): everything Dan owns from artists, and who signed it.

- `data/items.tsv` - one row per thing owned
- `data/show_goals/item_signatures.tsv` - one row per signature on an item

Works conversationally or inline during Routine 2 show-notes processing - the
confirmation gates below apply in both modes. `tools/items/ledger.py` in the
repo documents the columns and is the validator; if this skill and that file
ever disagree, the file wins.

## Routing guard - what belongs here

The ledger records items: signed merch (CDs, vinyl, posters, shirts,
drumheads), unsigned mementos (picks, setlists, laminates), mail-order and
crowdfunded releases, downloads bought outside Bandcamp, and their photo
links. These route ELSEWHERE:

- **Hat signings** -> `data/show_goals/hat_signatures.tsv`
- **Autograph book signatures** -> `data/show_goals/book_signatures.tsv`
- **Bandcamp purchases** -> never typed by hand. They arrive from the Bandcamp
  export (`tools/research/web-src/scraping_tasks.md`) through
  `python3 tools/items/ledger.py import-bandcamp`.

If the mention is a hat or book signing, say so and follow that file's
protocol instead. An item that is both (a poster signed at the same moment as
the hat) gets a row in each applicable log.

## Privacy - names only

Both files are public. Never write a price, an order or invoice number, a
sale ID or an account detail. `notes` is provenance and context only.

## Schema

`items.tsv` (12 columns, tab-separated, `-` for an empty cell):

```
item_id | artist | title | kind | acquired | paid | acquired_date | venue | status | photo_ref | source_key | notes
```

- **item_id** - the next whole number after the current maximum. Permanent:
  never renumber, reuse or reorder. New rows are appended at the end.
- **artist** - the act the item belongs to: the band for a band member's
  item, the artist who used or threw a pick.
- **title** - release or item name (`Open Bayou`, `show poster`); `-` for a
  bare pick or setlist.
- **kind** - `cd`, `vinyl`, `digital-album`, `digital-track`, `poster`,
  `shirt`, `setlist`, `pick`, `print`, `other`.
- **acquired** - `show`, `vip`, `mail`, `crowdfund`, `bandcamp`, `download`,
  `raffle`, `gift`, `own` (a print of Dan's own photo), or `-` if unknown.
- **paid** - `Y`, `N` or `?`. An item inside a VIP bundle is `acquired=vip`,
  `paid=Y`. A thrown pick or a handed-over setlist is `N`.
- **acquired_date** - `YYYY`, `YYYY-MM` or `YYYY-MM-DD`, as precisely as Dan
  states it. For a show item, the show date.
- **venue** - canonical Venue Name from `data/venues.tsv` when acquired at a
  show; `-` otherwise.
- **status** - `received`, or `pending` for an order not yet arrived.
- **photo_ref** - share link to the item's photo (see Step 3).
- **source_key** - `-` for everything this skill adds.
- **notes** - ASCII punctuation only.

`item_signatures.tsv` (9 columns):

```
item_id | signer | attribution | show_date | venue | photo_ref | legible | confidence | notes
```

- One row per signer. An item signed by three band members is ONE item row
  and three signature rows carrying its `item_id`, kept together in the file.
- **attribution** - `of <band>` for a band member, `-` for a solo or headline
  artist under their own name.
- **show_date / venue** - where it was signed, which may be a later show than
  the one where the item was acquired.
- **photo_ref** - optional close-up of the signature; usually `-`.
- **legible** - usually `-`; fill only when Dan supplies it.
- **confidence** - `high` when Dan states the facts directly; `medium` or
  `low` when the signer needs later verification (say what in notes).

## Step 1 - Pre-flight

1. If the show reference is relative ("last night", "Saturday"), resolve the
   date via the `current-date` skill first - never from model memory.
2. Fetch fresh from `dan2bit/live-shows` `main`:
   - `data/items.tsv` and `data/show_goals/item_signatures.tsv`
   - `data/live_shows_current.tsv`, plus `data/history/<year>.tsv` for the
     year in question (attended shows migrate to history once terminal -
     check both).

## Step 2 - Locate the show row and CONFIRM

Skip this step for an item that never passed through a show (a mail order
arriving, a crowdfund reward) - go to Step 3.

Resolve the mention to exactly one show:

- "last night's show" -> the attended show on the resolved date.
- "<artist> signed my <item>" -> that artist's most recent attended show.
- "<year> show poster from <artist>" -> that artist's show(s) in that year.
- "<artist>'s <venue> appearance" -> that artist at that venue.

Match artists alias-aware (`data/recommend_aliases.tsv` normalization; a band
member's item matches the BAND's show row). If more than one show matches,
list the candidates and ask. If none matches, say so and stop - never guess a
date.

**Confirmation gate: state the located show (artist - date - venue) and wait
for Dan's yes before going further.** In Routine 2 this can fold into the
routine's own confirmation flow, but the show identification must be
explicitly surfaced, not assumed.

## Step 3 - Gather fields

- **Is it already in the ledger?** Search `items.tsv` by artist and title
  first. A CD bought earlier and signed tonight is a new signature row on the
  existing item, not a new item. An order arriving flips `pending` to
  `received` on its existing row.
- Artist, title, kind, acquired, paid, and signer(s) with attribution from
  the conversation; ask only for what is genuinely missing.
- **If there is no photo URL, prompt for one** ("got a photo link for it?").
  Accept "none yet" - leave `photo_ref` as `-`. Nothing else is needed: the
  item then shows up in `python3 tools/items/ledger.py needs-photo`, and Dan
  can file the photo later from a `Photos:` issue comment with `item=N`.
- **Duplicate-URL check:** if the supplied photo URL already appears on a
  DIFFERENT item, flag it as a probable paste error and re-confirm.

## Step 4 - Preview before committing

- **Insert:** render the complete new item row, field by field, with its
  assigned `item_id`, and each signature row.
- **Update** (a photo link, a status change, a corrected field, a new
  signature on an existing item): locate the item by number, or by artist +
  title, and show a before/after for exactly the cells changing. If the item
  cannot be found, offer the closest candidates - never create a duplicate
  when an update was intended.

Wait for explicit approval of the preview. No approval, no commit.

## Step 5 - Commit and verify

- Full-file push to `staging` in `dan2bit/live-shows` of each file that
  changed - fresh blob SHA immediately before each write, plain tab-joined
  lines, LF endings, never the csv module, every row padded to its column
  count with `-` in empty cells, ASCII punctuation in data, exactly one
  trailing newline.
- Existing rows stay byte-for-byte as they were unless a cell was meant to
  change. No renumbering, no re-sorting.
- When a checkout is available, run `python3 tools/items/ledger.py check`
  before pushing. The data-hygiene run applies the same check after the push.
- Verify the pushed files against the intended content and confirm
  auto-promote carried them to `main`.
- Report the item number(s) so follow-ups and photo comments can use them.

`DATA_WRITE_PROTOCOLS.md` in the repo remains authoritative for all write
mechanics.
