# DOM Reference — YouTube Playlist Inventory & Setlist Attendances

Companion to the two ON DEMAND tasks in `scraping_tasks.md`. Provide this file to the
Claude for Chrome session before starting either task — it contains tested DOM selectors,
extraction scripts, and verification gates. Selectors verified June 2026; if a site
redesign breaks them, note the new selectors here.

---

## Workflow 1 — YouTube Studio playlists

URL: `https://studio.youtube.com/channel/UCLk1BKTtXoyFD068_Ob2pcw/content/playlists`

Total playlist count varies over time — never hard-code it.

**Setup:** set rows-per-page (`ytcp-select#page-size`) to 50 before extracting.

**Verify page range** after load — `text[3]` is the total; pages = `Math.ceil(total / 50)`:
```js
const text = document.body.innerText.match(/(\d+)–(\d+) of (\d+)/);
```

**Extraction (run per page):**
```js
function extractPlaylists() {
  const rows = Array.from(document.querySelectorAll('ytcp-playlist-row'));
  return rows.map(row => {
    const titleEl = row.querySelector('a.remove-default-style');
    const title = titleEl ? titleEl.textContent.trim() : '';
    // Shareable link — built from the playlist ID in the Studio edit href.
    // NEVER use the "Get shareable link" overflow menu (clipboard-only, unreadable).
    const studioHref = titleEl ? titleEl.href : '';
    const idMatch = studioHref.match(/\/playlist\/([^\/]+)\//);
    const playlistId = idMatch ? idMatch[1] : '';
    const shareableLink = playlistId
      ? 'https://www.youtube.com/playlist?list=' + playlistId : '';
    const descEl = row.querySelector('div.description');
    let description = descEl ? descEl.textContent.trim() : '';
    description = description.replace(/\s+/g, ' ').trim();
    const countEl = row.querySelector('.videos-count-cell');
    const videoCount = countEl ? countEl.textContent.trim() : '';
    return { title, shareableLink, description, videoCount };
  });
}
```

**Paginate and accumulate:** initialize `window._playlistData = []`; on each page run
`extractPlaylists()` and concat, then click `document.getElementById('navigate-after').click()`,
wait ~2s for render, repeat. Stop when the range footer's end equals the total
(e.g. "201–225 of 225"). The Next button is `ytcp-icon-button#navigate-after`
(check `aria-disabled="false"` on non-final pages).

**Verify:** `window._playlistData.length` equals the Step-1 total; all rows have
non-empty title, shareableLink, and videoCount.

**Build and download TSV** (filename per the datestamped convention in `scraping_tasks.md`):
```js
const escape = s => (s || '').replace(/\t/g, ' ').replace(/\n/g, ' ').replace(/\r/g, '');
const header = ['Title', 'Description', 'Shareable Link', 'Video Count'];
const rows = window._playlistData.map(d =>
  [escape(d.title), escape(d.description), escape(d.shareableLink), escape(d.videoCount)].join('\t')
);
const tsv = [header.join('\t'), ...rows].join('\n');
const blob = new Blob([tsv], { type: 'text/tab-separated-values' });
const url = URL.createObjectURL(blob);
const a = document.createElement('a');
a.href = url;
a.download = 'youtube_playlists_YYYYMMDD.tsv';  // substitute current date
document.body.appendChild(a); a.click(); document.body.removeChild(a);
URL.revokeObjectURL(url);
```

**Selector table (YouTube Studio):**
| Element | Selector |
|---|---|
| Playlist rows | `ytcp-playlist-row` |
| Title link | `a.remove-default-style` (inside row) |
| Description | `div.description` (inside row) |
| Video count | `div.videos-count-cell` (inside row) |
| Rows-per-page | `ytcp-select#page-size` |
| Next page | `ytcp-icon-button#navigate-after` |
| Page range | `body.innerText` vs `/(\d+)–(\d+) of (\d+)/` |

---

## Workflow 2 — Setlist.fm attended concerts

URL: `https://www.setlist.fm/attended/dan2bit` (username segment is account-specific)

Total attendance count varies — never hard-code it.

**Setup:** set setlists-per-page to the maximum (500). All entries must be in the
rendered DOM before extraction; if pagination remains, step pages with the same
accumulation pattern as Workflow 1.

**Pre-flight count gate — do not proceed if it fails:**
```js
const allLinks = Array.from(document.querySelectorAll('a'));
const setlistLinks = allLinks.filter(a =>
  a.href && a.href.includes('/setlist/') &&
  !a.href.endsWith('/setlists') && !a.href.endsWith('/setlist')
);
const uniqueHrefs = [...new Set(setlistLinks.map(a => a.href))];
console.log('Unique setlist links:', uniqueHrefs.length);
// Must equal the total number of attended concerts before continuing.
// NOTE: every entry produces TWO anchors to the same URL — dedup is mandatory.
```

**Extraction:** each concert is `<li class="setlist">` in a `<ul class="list-unstyled">`.
```js
function extractEntry(li) {
  const dateA = li.querySelector('div.column.date a');
  const url = dateA ? dateA.href : '';
  const dateBlock = dateA ? dateA.querySelector('span.smallDateBlock') : null;
  let date = '';
  if (dateBlock) {
    const month = dateBlock.querySelector('strong.text-uppercase')?.textContent.trim() || '';
    const day   = dateBlock.querySelector('strong.big')?.textContent.trim() || '';
    const yearSpan = Array.from(dateBlock.querySelectorAll('span'))
      .find(s => s !== dateBlock && !s.className);   // year = the bare classless span
    const year = yearSpan?.textContent.trim() || '';
    date = month + ' ' + day + ' ' + year;
  }
  // Band name: first <strong> inside div.setlistLink NOT inside div.column.date
  const setlistLinkDiv = li.querySelector('div.setlistLink');
  let bandName = '';
  if (setlistLinkDiv) {
    const dateColDiv = setlistLinkDiv.querySelector('div.column.date');
    const allStrongs = Array.from(setlistLinkDiv.querySelectorAll('strong'));
    for (const s of allStrongs) {
      if (!dateColDiv?.contains(s) && s.textContent.trim()) { bandName = s.textContent.trim(); break; }
    }
  }
  const sublineEl = li.querySelector('span.subline');
  const description = sublineEl ? sublineEl.textContent.trim() : '';
  return { date, url, bandName, description };
}
const liItems = Array.from(document.querySelectorAll('li.setlist'));
const allData = liItems.map(extractEntry);
```

**Verify:** `allData.length` equals `uniqueHrefs.length`; zero entries with empty
url, date, or bandName.

**Build and download TSV** (same escape/blob pattern as Workflow 1; header
`['Date', 'Band Name', 'Description', 'URL']`; filename `setlist_attendances_YYYYMMDD.tsv`
with the current date substituted).

**Selector table (setlist.fm):**
| Element | Selector |
|---|---|
| Concert rows | `li.setlist` |
| Date anchor | `div.column.date a` (inside li) |
| Date block | `span.smallDateBlock` (inside date anchor) |
| Month / Day | `strong.text-uppercase` / `strong.big` |
| Year | bare classless `span` inside smallDateBlock |
| Band name | first `strong` in `div.setlistLink` not in `div.column.date` |
| Description | `span.subline` (venue/city/state — or event name for festivals; both correct) |
