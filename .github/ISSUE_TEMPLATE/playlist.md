---
name: Bootleg playlist standup
about: Stand up a YouTube bootleg playlist for a show (headliner + support)
title: "Playlist: {{HEADLINER}} w/ {{SUPPORT}} — YYYY-MM-DD ({{VENUE}})"
labels: playlist
---

Setlist.fm:
- {{SUPPORT}}: {{SETLIST_FM_SUPPORT}}
- {{HEADLINER}}: {{SETLIST_FM_HEADLINER}}

YouTube:
- {{HEADLINER}}: {{HEADLINER_HANDLE}}
- {{SUPPORT}}: {{SUPPORT_HANDLE}}

Show note:
{{SHOW_NOTE}}

<!-- Fill-in values, used by the steps below:
  HEADLINER / SUPPORT        band names
  *_HANDLE                   @channel handles
  DATE_ISO   = YYYY-MM-DD    Google Photos search + video titles
  DATE_DISP  = M/D/YY        playlist title
  DATE_DESC  = MM/DD/YYYY    video descriptions
  VENUE      = short form for titles, e.g. Pier Six (MD)
  VENUE_FULL = full name for descriptions, e.g. Pier Six Pavilion (MD)
  SEAT       = seat/location token for the playlist description
  SHOW_NOTE  public Notes for the show (data/live_shows_current.tsv); may hold
             song-ID context, e.g. an act known for playing covers. Omit if none.
-->

Task List:

- [ ] search Google Photos for `video {{DATE_ISO}}`
- [ ] check durations & orientation - skip any too short, rotate any that need it on mobile first
- [ ] download locally, unzip, and upload to YouTube channel content
- [ ] per video (headliner), set Title: `{{HEADLINER}} LIVE - #song-title (bootleg)`
- [ ] per video (headliner), set Description: `from {{VENUE_FULL}} on {{DATE_DESC}} {{HEADLINER_HANDLE}}`
- [ ] add each video to a new Playlist
- [ ] set Playlist Title: `{{HEADLINER}} LIVE @ {{VENUE}} {{DATE_DISP}}`
- [ ] set Playlist Description: `select tracks from {{SEAT}} - full playlists at {{SETLIST_FM_HEADLINER}} and {{SETLIST_FM_SUPPORT}}`
- [ ] for each new video, reuse details from the first, set Monetization on, and Submit Rating "none of the above"
- [ ] per video (support), set Title: `{{SUPPORT}} LIVE @ {{VENUE}} {{DATE_DISP}}`
- [ ] per video (support), set Description: `from {{VENUE_FULL}} on {{DATE_DESC}} {{SUPPORT_HANDLE}} supporting {{HEADLINER_HANDLE}}`
- [ ] when processing is complete, identify song titles via YouTube checks or listening
- [ ] compare to setlist if complete, or lyric searches
- [ ] when a song title is set, set that video to Public
- [ ] when all are Public, edit the playlist on YouTube and reorder: headliner first, supporting acts follow
- [ ] copy the share playlist link as a comment on this issue and close it (picked up by CI for updating the show row)
