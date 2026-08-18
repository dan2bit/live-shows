---
name: item-log
description: Add or update rows in the live-shows item log (data/show_goals/item_log.tsv) - signed merch, picks, posters, setlists, and show mementos. Use whenever Dan mentions getting, finding, or photographing a show item, e.g. "I got a pick at last night's show", "Jackie Venson signed my t-shirt", "I found a show poster from the VIP package", "here's the photo link for the set list", "add to the item log", or when show-notes processing (Routine 2) surfaces a signed item or memento. Do NOT use for hat signings or autograph-book signatures - those have their own event logs.
---

# Item Log - Additions and Updates

Maintains `data/show_goals/item_log.tsv` in `dan2bit/live-shows` (public repo,
commits to `staging`). Works conversationally or inline during Routine 2
show-notes processing - the confirmation gates below apply in both modes.

## Routing guard - what belongs here

The item log records physical show items: signed merch (CDs, vinyl, posters,
shirts, drumheads), unsigned mementos (picks, setlists, laminates), and their
photo links. Two categories route ELSEWHERE:

- **Hat signings** -> `data/show_goals/hat_signatures.tsv`
- **Autograph book signatures** -> `data/show_goals/book_signatures.tsv`

If the mention is a hat or book signing, say so and follow that file's
protocol instead. An item that is both (e.g. a poster signed at the same
moment as the hat) gets a row in each applicable log.

## Schema (12 columns, tab-separated)

```
seq | signer | attribution | item | signed | show_date | venue | region | photo_ref | legible | confidence | notes
```

- **seq** - integer, next after the current max. One row per signer: an item
  signed by three band members is three rows sharing photo_ref, each noting
  `same item as seq N` for the first row of the group.
- **signer** - the associated artist, even for unsigned mementos (a pick's
  signer is the artist who used/threw it).
- **attribution** - GOALS_SPEC binding vocabulary: `of <band>` for a band
  member, blank for a solo/headline artist under their own name.
- **item** - short type with parenthetical detail: `pick`, `CD`,
  `vinyl (Dirty Shine LP)`, `poster (show poster)`, `t-shirt`, `setlist`.
- **signed** - `Y` or `N` (`N` = unsigned memento; note it as such).
- **show_date** - ISO `YYYY-MM-DD` of the show the item came from.
- **venue** - canonical Venue Name from `data/venues.tsv`.
- **region** - usually blank; fill only when Dan supplies it.
- **photo_ref** - Google Photos share link (see Step 3).
- **legible** - usually blank; fill only when Dan supplies it.
- **confidence** - `high` when Dan states the facts directly; `medium`/`low`
  when signer or item needs later verification (say what to verify in notes).
- **notes** - provenance and context (VIP bundle, pick branding, farewell-tour
  context, verification reminders). ASCII punctuation only.

## Step 1 - Pre-flight

1. If the show reference is relative ("last night", "Saturday"), resolve the
   date via the `current-date` skill first - never from model memory.
2. Fetch fresh from `dan2bit/live-shows` `main`:
   - `data/show_goals/item_log.tsv` (current rows + max seq)
   - `data/live_shows_current.tsv`, plus `data/history/<year>.tsv` for the
     year in question (attended shows migrate to history once terminal -
     check both).

## Step 2 - Locate the show row and CONFIRM

Resolve the mention to exactly one show:

- "last night's show" -> the attended show on the resolved date.
- "<artist> signed my <item>" -> that artist's most recent attended show.
- "<year> show poster from <artist>" -> that artist's show(s) in that year.
- "<artist>'s <venue> appearance" -> that artist at that venue.

Match artists alias-aware (`data/recommend_aliases.tsv` normalization; a band
member's item matches the BAND's show row - e.g. a band member's signed poster
matches the band's show row). If more than one show matches, list the
candidates and ask. If none matches, say so and stop - never guess a date.

**Confirmation gate: state the located show (artist - date - venue) and wait
for Dan's yes before going further.** In Routine 2 this can fold into the
routine's own confirmation flow, but the show identification must be
explicitly surfaced, not assumed.

## Step 3 - Gather fields

- Signer(s), attribution, item, signed Y/N from the conversation; ask only
  for what is genuinely missing.
- **If there is no photo URL, prompt for one** ("got a photo link for it?").
  Accept "none yet" - leave photo_ref blank and add `photo TBD` to notes so a
  later "here's the photo link" update has a hook.
- **Duplicate-URL check:** if the supplied photo URL already appears on a row
  for a DIFFERENT item, flag it as a probable paste error and re-confirm
  before proceeding. A shared URL is correct only within one physical item's
  signer group.
- Multi-signer items: one row per signer, shared photo_ref, `same item as
  seq N` in notes.

## Step 4 - Preview before committing

- **Insert:** render the complete new row(s), field by field, with the
  assigned seq number(s).
- **Update** (e.g. adding a photo link or correcting a field on an existing
  row): locate the row by signer + item + show_date, and show a before/after
  for exactly the fields changing. If the row can't be found, offer the
  closest candidates - never create a duplicate when an update was intended.

Wait for explicit approval of the preview. No approval, no commit.

## Step 5 - Commit and verify

- Full-file push of `data/show_goals/item_log.tsv` to `staging` in
  `dan2bit/live-shows` - fresh blob SHA immediately before the write, plain
  tab-joined lines, LF endings, never the csv module, every row padded to 12
  columns, ASCII punctuation in data.
- Verify the pushed file byte-for-byte against the intended content and
  confirm auto-promote carried it to `main`.
- Report the committed seq number(s) so follow-ups can reference them.

`DATA_WRITE_PROTOCOLS.md` in the repo remains authoritative for all write
mechanics; if this skill and that file ever disagree, the playbook wins.
