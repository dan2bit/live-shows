
*BIT recommended shows list MONTHLY**

1. log in as rhbl to bandsintown
2. open https://www.bandsintown.com/c/washington-dc?came_from=278&utm_medium=web&utm_source=city_page&utm_campaign=recommended_event&recommended_artists_filter=Recommended
3. choose view all, and scroll until all the progressive disclosure is exposed

_Prompt_
create rhbl-bandsintown-dc-recommends-2026-MM.tsv for download
use the current two-digit month in place of MM
Schema: Artist | Venue/Event | Date | Time | Tracking
Capture: artist name, venue/event name, date, time, attending count (Tracking)

4. Save the file in `/tools/research/web-src`
5. Have Claude Desktop diff the file against the previous month

*Here for the Bands shows list MONTHLY*

1. open https://www.hereforthebands.com/shows.php and choose dc
2. scroll to the bottom and click ALL, wait for the load to complete

_Prompt_
create rhbl-hereforthebands-dc-2026-MM.tsv for download
use the current two-digit month in place of MM
Schema: Artist | Venue | Date | Venue URL
Capture: artist name, venue, date, venue URL
all shows at the same venue share the same Venue URL

3. Save the file in `/tools/research/web-src`
4. Have Claude Desktop diff the file against the previous month

*Bandsintown scrape follows list ON CHANGE*

1. log in as rhbl to bandsintown
2. open https://www.bandsintown.com/u/tracked-artists and make sure View All is active

_Prompt_
create rhbl-bandsintown.tsv for download. one column: Artist
Capture: the artist names only from the tracked-artists page

3. Save the file in `/tools/research/follows`, overwriting the existing file

*Seated scrape follows list ON CHANGE*

1. login as rhbl to seated.com
2. open https://go.seated.com/notifications and make sure all artists are visible

_Prompt_
create rhbl-seated.tsv for download. one column: Artist
Capture: only the artists names in the Following section of this page. 
skip over the "Recommended for You" list

3. Save the file in `/tools/research/follows`, overwriting the existing file

*Fast track tour pages scrape MONTHLY*

1. ask Claude Desktop to produce just the list of tour page URLs from data/fast_track.csv

_Prompt 1_
open each of these URLs in a new tab in this window

2. review the pages for completely empty lists (Bell, Ponder) and close the tabs

_Prompt 2_

for each artist with an open tab
create fast-track-<artist>-tour-dates.tsv for download
Capture: upcoming dates only. ignore past events
Click All Shows, Load More, or equivalent expansion or pagination controls
Schema: Date | Day | Time | Event/Venue | Venue | City | State (or Country if non-USA)
offer the completed file before moving on to the next artist

3. save the files in `tools/research/web-src` overwriting the existing files

*Youtube Playlist Inventory ON DEMAND*

1. login to Youtube Studio and navigate to Content -> Playlists
2. set Rows Per Page to 50

_Prompt_
create `youtube_playlists_YYYYMMDD.tsv` for download, using the current date in the filename
Schema: Title | Description | Shareable Link | Video Count
Capture: do not use the clipboard tool `Get shareable link` - build the link programmatically
use the pagination controls to collect all playlists

3. save the file in `tools/archive` and optionally delete the prior file

*Setlist Attendances Inventory ON DEMAND*

1. login to setlist.fm and navigate to https://www.setlist.fm/attended/dan2bit
2. change Setlists shown per page to 500 and scroll to the bottom

_Prompt_
create `setlist_attendances_YYYYMMDD.tsv` for download, using the current date in the filename
Schema: Date | Band Name | Description | URL
Capture: use the pagination controls to collect all playlists if necessary

3. save the file in `tools/archive` and optionally delete the prior file




