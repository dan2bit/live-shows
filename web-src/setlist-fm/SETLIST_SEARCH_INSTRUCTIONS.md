# Claude-for-Chrome instructions — resolve setlist.fm searches

**Input files** (one per year, process them one at a time — finishing a file before starting the next keeps a stall from losing progress):

| File | Rows |
|------|------|
| `setlist_search_worklist_2021-2022.tsv` | 12 |
| `setlist_search_worklist_2023.tsv` | 45 |
| `setlist_search_worklist_2024.tsv` | 39 |
| `setlist_search_worklist_2025.tsv` | 47 |

(2021 and 2022 are combined into one file because each year is small.)

Each file is tab-separated with a header row. Columns:
`Year · Date · Headliner · Venue · Act to Find · Search URL · Setlist URL`
The **`Setlist URL`** column is empty — your job is to fill it in for every row, then return/save the updated file.

## For each row

1. Open the **Search URL** in the row (it is a date-scoped setlist.fm search for that act).
2. On the results page, find the **first** search result, which renders as an `<h2>` with an anchor, e.g.:

   ```html
   <h2><a href="setlist/ally-venable-band/2021/sixth-and-i-historic-synagogue-washington-dc-138a0505.html" title="View this Ally Venable Band setlist">Ally Venable Band at Sixth &amp; I Historic Synagogue, Washington, DC, USA</a></h2>
   ```

3. Take the anchor's `href` (it is **relative**, with no leading slash, e.g. `setlist/ally-venable-band/2021/...html`) and build the fully-qualified URL by prepending `https://www.setlist.fm/`:

   ```
   https://www.setlist.fm/setlist/ally-venable-band/2021/sixth-and-i-historic-synagogue-washington-dc-138a0505.html
   ```

4. Write that FQDN into the row's **`Setlist URL`** column.

## Matching / verification

- The search is already scoped to the act **and** the exact date, so there is usually a single correct result. If there are several `<h2>` results, choose the one whose anchor **title/text matches the `Act to Find`** and whose text mentions the **`Venue`** (or its city) for that row.
- If the act name in the result differs slightly from `Act to Find` but is clearly the same artist (e.g. punctuation, "The", `&` vs "and"), accept it.
- **No result:** if the results page shows no matching `<h2>` setlist link, write `NOT FOUND` in the `Setlist URL` column. Some openers genuinely have no setlist.fm entry — that's expected.
- Do **not** invent or guess a URL. Only ever copy an `href` that actually appears on the results page.

## Notes

- Several dates have the **same act on different dates** (e.g. Larkin Poe, Carly Harvey, Christone 'Kingfish' Ingram appear multiple times) — the date in each Search URL keeps them distinct, so resolve each row independently.
- In the 2023 file, **`2023-09-09`** has two rows at two different venues (Pearl Street Warehouse and Rosslyn Jazz Fest); resolve each by its own venue.
- Go at a polite pace (a short pause between searches) to avoid rate-limiting.
- When a file is finished, return / save that `setlist_search_worklist_<year>.tsv` with its `Setlist URL` column populated before moving to the next file.
