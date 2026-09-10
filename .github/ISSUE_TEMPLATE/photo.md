---
name: Photos
about: Every photo from one show, filed into the show library one comment at a time
title: "Photos: {{HEADLINER}} — {{YYYY-MM-DD}} ({{VENUE_SHORT}})"
labels: photo
---

Show: {{HEADLINER}} — {{YYYY-MM-DD}} — {{VENUE_SHORT}}
Bill: {{HEADLINER}}{{SUPPORT_IF_ANY}}

Expected from the notes (edit freely):
- [ ] with-artist: {{ARTIST_1}}
- [ ] with-artist: {{ARTIST_2_OR_DELETE_LINE}}
- [ ] pre-show selfie
- [ ] memorabilia: {{ITEM_OR_DELETE_LINE}}

## How to file each photo

**On the phone:** Immich app → Library → On this device → select the photo →
Upload, into the album that says what it is. **That album is the photo's
kind; nothing else sets it.**

| Upload into | for |
|---|---|
| Guitar Gods and Goddesses, and Me | you with an artist or band member |
| Player Portraits | the performer on stage |
| Preshow Selfies | you, before the show |
| Crowds I'm in | the room |
| Concert Memorabilia | a setlist, pick, poster, signed thing, ticket, the hat |

Then open the photo → **Share → Create link** (leave the defaults) and paste
the address here as a **new comment, link first**. One comment per photo.
Only the repository owner's comments fire the automation, and a link
mentioned mid-sentence does not.

## Comment forms (copy one)

```
https://photos.redhat-bootlegs.net/share/...
```
A with-artist photo of the headliner, a selfie, a crowd shot. Nothing else needed.

```
https://photos.redhat-bootlegs.net/share/... artist="Steve Bell"
```
A with-artist photo of someone other than the headliner, or a Player Portrait
(portraits are never assumed to be the headliner - name who it is). Use the
library's spelling; quotes required.

```
https://photos.redhat-bootlegs.net/share/... subtype=pick signed artist="Ghalia Volt"
```
Memorabilia. `subtype=` is one of exactly these:

`setlist` `cd` `vinyl` `poster` `pick` `ticket` `autograph-book` `photo-print` `hat` `other`

Add `signed` if it carries a signature, `artist="..."` for whose item or
signature it is, `detail` for a close-up of something already filed.
A signed setlist: `subtype=setlist signed artist="..."`. The hat after a
signing: `subtype=hat signed artist="..."`. A pick with no signature:
`subtype=pick`.

```
https://photos.redhat-bootlegs.net/share/... close
```
Add `close` to whichever comment is the last photo. The issue stays open
until then (an open photo issue also holds the show row back from rollover,
which is the point).

## What happens

Each comment: the photo is tagged (`kind/`, `show/`, `venue/`, `artist/`,
`memorabilia/`, `signed`), filed into the show album, the kind album and the
artist album (any of them created on first need, one share link each), the
show-album link is written to the show row's Photo URL, the artist-album link
to `data/show_goals/artist-albums.tsv`, and the workflow replies with the
links. Second and later photos from the show are no-ops on the rows.

**Memorabilia is also a ledger entry.** After the comment, record the item in
`data/show_goals/item_log.tsv` (the `item-log` skill does this) - the photo
pipeline files the picture, not the fact that you own the thing.

If the workflow is ever unavailable, the same thing by hand:

```
python3 tools/photos/show_photos.py add --asset <pasted link> --show {{YYYY-MM-DD}} [--artist "..."] [--subtype pick --signed] --write
```

Do not touch `artists.tsv` - it carries no photo column.
