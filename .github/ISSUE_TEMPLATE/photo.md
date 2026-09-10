---
name: Photo
about: One photo with one artist, to be filed into the show library
title: "Photo: {{ARTIST}} — {{YYYY-MM-DD}} ({{VENUE_SHORT}})"
labels: photo
---

Artist: {{ARTIST}}
Show date: {{YYYY-MM-DD}}
Venue: {{VENUE_SHORT}}

Caption: {{ONE_LINE_ON_WHO_WHAT_WHERE}}

**To close this issue:** upload the photo from the Immich app into the
*Guitar gods and goddesses* album, open it, and use **Share → Create link**
(leave the defaults: download on, metadata off). Paste the resulting
`https://photos.redhat-bootlegs.net/share/...` address as a new comment,
**as the first thing in the comment** - a link mentioned mid-sentence does
not fire the automation, and only the repository owner's comments do.

That comment triggers `close-photo-issue.yml`, which tags the photo
(`kind/with-artist`, `artist/`, `show/`, `venue/`), files it in the show
album, the artist album and the kind album (creating whichever are missing,
one share link each), writes the show-album link to the show row's Photo URL
and the artist-album link to `data/show_goals/artist-albums.tsv`, and closes
this issue. A second photo from the same show, or a second show with the
same artist, is a no-op on the rows and a membership add on the server.

If the workflow is ever unavailable, run the same thing by hand:

```
python3 tools/photos/show_photos.py add --asset <pasted link> --show {{YYYY-MM-DD}} --kind with-artist --artist "{{ARTIST}}" --write
```

Do not touch `artists.tsv` - it carries no photo column.
