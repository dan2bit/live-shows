# DATA_WRITE_PROTOCOLS.md

Canonical rules for every file write in the live-shows system. All agentic sessions
(Inbox+Data, Site+Repo, Strategy) follow these. `EMAIL_WORKFLOWS.md` and
`AGENTIC_WORKFLOWS.md` reference this file rather than restating rules inline.

---

## ⚠️ CRITICAL — Private data boundary

The MCP token can write to **both** `dan2bit/live-shows` (public) and
`dan2bit/live-shows-private` (private). That is a hazard, not a convenience.

**Hard rules — no exceptions:**

1. A private file is a commit to the **repository** `dan2bit/live-shows-private`, at
   that repo's **root**. It is never a path inside `dan2bit/live-shows`.

2. **NEVER** create, in `dan2bit/live-shows` (public): any path under
   `live-shows-private/`, any file matching `*_private.tsv`, or any file matching
   `*_caps.tsv`. These are gitignored and the CI guard (`private-data-guard.yml`)
   will reject them — but the responsibility is yours first.

3. Throughout these docs, private files are written as
   **`dan2bit/live-shows-private → <file>`**. The `→` means "the file `<file>` at the
   root of the `dan2bit/live-shows-private` repo." If you ever find yourself about to
   write a path that looks like `live-shows-private/<file>` inside the public repo,
   **STOP** — that is the leak pattern that caused the 2026-06-27 incident.

4. A show's public fields and its private fields are **two separate commits to two
   separate repos**, never one commit.

---

## Commit targets

| File / type | Branch | Repo |
|---|---|---|
| Public TSVs (`live_shows_current.tsv`, `live_shows_potential.tsv`, `fast_track.tsv`, `artists.tsv`, etc.) | `staging` | `dan2bit/live-shows` |
| Private sidecar TSVs (`current_private.tsv`, `potential_private.tsv`, `fast_track_caps.tsv`, `spending.tsv`) | `main` | `dan2bit/live-shows-private` |
| `index.html` | `staging` | `dan2bit/live-shows` |
| `app.js`, `recommend.js`, `styles.css` | `staging` (small fixes) or PR branch (logic changes) | `dan2bit/live-shows` |
| Python / shell scripts | PR branch | `dan2bit/live-shows` |

`auto-promote.yml` fires on every push to `staging`, re-runs the private-data guard,
and fast-forwards `main` if clean. Nothing is pushed to `main` directly.

**`push_files` quirk:** The multi-file Git Data API (`push_files`) does **not** fire
the `push` trigger on `staging` and therefore does **not** auto-promote. After any
`push_files` call, follow up with a single-file `create_or_update_file` nudge commit
to trigger promotion — or use sequential `create_or_update_file` calls instead.

**SHA discipline:** Always fetch a fresh blob SHA immediately before every
`create_or_update_file` call. Never reuse a SHA from earlier in the session.

### In-page UI writes (authenticated browser)

The in-page editor (`handleDecisionChange`, `handleRevoke`, `saveEdit`, `commitConfig`)
also writes to the public repo via the GitHub Contents API. These writes previously
targeted `main` directly, which broke when branch protection was enabled (issue #111).

The fix: `app.js` reads `site.data_branch` from `config.yaml` via the `dataBranch()`
helper and passes it as `branch:dataBranch()` in every public-repo PUT body. This
fork sets `site.data_branch: staging`; forks without a staging pipeline omit the key
and get the `'main'` default.

**Implication:** in-page edits (decision changes, notes, revokes, config) land on
`staging` and auto-promote to `main` via CI — the same pipeline as MCP data commits.
Private sidecar writes (`_savePrivateSidecar`) are unaffected: they target the private
repo's `main` directly, which has no branch protection.

---

## `live_shows_current.tsv` write protocol

**19 columns — no exceptions.** `validate_current.py` enforces this. For upcoming rows,
cols 13 (Setlist URL) and 16 (Playlist URL) must never be empty — use `-` as a sentinel
if there is no real value. MCP trailing-tab stripping collapses empty trailing columns
and shifts content into the wrong column; the sentinel prevents this.

**Public/private split (PR #59):** The public file carries only denormalized flags
(`Seat Type`: `GA`|`Seated`; `VIP`: `Y`; `Group`: `Y`), show metadata, public Notes /
Memories, and Photo URL. All financial and seat detail lives in the private sidecar.

| Public (`data/live_shows_current.tsv` → `staging`) | Private (`dan2bit/live-shows-private → current_private.tsv`) |
|---|---|
| Artist, Supporting Artist, Venue Name, Show Date, Venue Event URL, Ticket Access, Seat Type, VIP, Group, Status, Notes / Memories, Setlist.fm URL, Photo URL, Playlist URL, Match Type, Artist Interaction | Seat Info / GA, Ticket Quantity, Face Value (per ticket), Fees, Total Cost, Purchase Date, Food & Bev, Parking, Merch, Private Notes |

**Key:** `Show Date` + `Artist` — used by `mergePrivateData()` in `app.js` to join the sidecars at runtime.

---

## `live_shows_potential.tsv` write protocol

**Always fetch a fresh SHA immediately before writing.**

The sequence for every write:

1. `get_file_contents` → capture current `sha` and content
2. Apply the change (add row, remove row, or field update)
3. Re-sort the full file: `Buy` → `Choose` → `Sell` → `Pass`, date ascending within each group
4. Commit to `staging` via `create_or_update_file` with the freshly fetched `sha`

**Private notes for a potential** (purchasing reminders, fee-avoidance, promo codes,
box-office tips) go to `dan2bit/live-shows-private → potential_private.tsv`, keyed by
`Artist` + `Date` — not a column in the public file (removed in PR #59).

**Prev/Next Show bracket rule:** Brackets are only calculated for Buy and Choose rows.
Sell and Pass rows always have empty (`-`) Prev/Next columns. Brackets represent the
surrounding purchased upcoming shows to help evaluate density.

- When a Buy or Choose row is downgraded to Pass or Sell, clear its brackets at the same time.
- When recalculating brackets after a new purchase (Routine 1 Step 5b), only update Buy and
  Choose rows — never populate brackets on Pass or Sell rows.
- "2 shows in 2 nights is a no-go for lower tiers" — factor into bracket review.

**Never reintroduce `#` comment blocks** into `live_shows_potential.tsv` (or any
in-page-editable TSV). The in-page editor derives the header from `raw.split('\n')[0]`;
a comment block wipes all rows on save (issue #80).

---

## `artists.tsv` counting policy

**Times Seen counts every appearance** — headliner and supporting act alike.

**New Entry Rule — support acts:** A supporting artist not yet in `artists.tsv` gets a
new row added **only when their second appearance is recorded.** One-off openers do not
get entries.

**First Seen / Most Recent Seen** use the same inclusive logic across all roles.

**History files are the source of truth.** Audit `history/*.tsv` and
`live_shows_current.tsv` together when in doubt.

Commits to `staging` in `dan2bit/live-shows`.

### Component artist / bill provenance (issue #103)

A combined bill (co-headliner pairing or supergroup name) creates a sighting for
**each component artist**, not just the bill name — but only when a component artist
would plausibly headline their own show. The test: **would this name plausibly headline
independently?** Taj Mahal, Keb' Mo', Joe Satriani, and Steve Vai all clearly would (and
several already have). A touring bassist or keyboardist would not.

**Artists that pass the test** get their own `artists.tsv` row, with:
- `Times Seen` / `First Seen` / `Most Recent Seen` computed from the bill's show row,
  same as any other sighting
- `Via` column set to the bill name (e.g. `SatchVai Band`, `TajMo: The Taj Mahal & Keb' Mo' Band`)

The bill name itself **keeps its own row too**. Both rows carry the count for the same
night — this mirrors how a headliner and a supporting act both get credited for one
show already; it is not a bug to reconcile.

**Artists that fail the test** (band members, sit-ins, sidemen — e.g. Laura Chavez,
Scot Sutherland, DeShawn Alexander) stay in `data/seen_with.tsv` only. No `artists.tsv`
row, no `Via` entry.

**`Via` is informational, not load-bearing.** It records provenance for a component row
so it's clear the sighting came via a bill rather than the artist's own headline show.
It does not gate or discount the count.

### Promotion from `seen_with.tsv` (conversational only)

If a `seen_with`-only artist later headlines or co-headlines independently — e.g. Laura
Chavez eventually plays a solo show — that is the trigger for a **one-time backfill**:
their prior `seen_with` appearances fold into the new `artists.tsv` row, with `Times Seen`
/ `First Seen` computed from those prior appearances plus the new one, and each prior
appearance still traceable via `Via`.

**This trigger is conversational, never scheduled.** There is no periodic scan of
`seen_with.tsv` for promotion candidates. The backfill happens naturally when processing
a ticket purchase (Routine 1) or post-show notes (Routine 2) for an artist who already
has `seen_with` history — check `seen_with.tsv` for the artist name at that point, and
if found, fold the prior appearances in as part of creating the new row.

---

## `fast_track.tsv` protocol

**`fast_track.tsv`** is a curated list of artists who should be treated as immediate
buys when a local show surfaces — skipping the potential list evaluation cycle entirely.

**Discipline:** Fast Track is strictly for artists who would NOT already be caught as
a strong buy based on show history. Artists with an established DC attendance history
must NOT be added here.

When a Fast Track artist's ticket is purchased (Routine 1 Step 7), remove the row from
both `data/fast_track.tsv` and `dan2bit/live-shows-private → fast_track_caps.tsv` so
the two stay in sync.

**Never reintroduce `#` comment blocks** into `fast_track.tsv` — same in-page-editor
hazard as potentials (issue #80).

### Cap defaults

| Cap | Default | Narrower options |
|-----|---------|-----------------|
| Price Cap | $100 all-in | Any lower dollar amount |
| Distance Cap | Regional (DC/MD/VA + Baltimore, ~60 mi) | Local (DC/MD/VA only) / Extended (~90 mi) |
| Venue Cap | Mid (small rooms + 9:30 Club, Wolf Trap Barns, State Theatre, ~500–1200 cap) | Small (Birchmere/Hamilton/Rams Head/Hub City tier only) / Large (adds Wolf Trap Filene, The Anthem) |

If **any cap is exceeded** — surface as a **Choose** recommendation in
`live_shows_potential.tsv` instead, noting which cap was exceeded.

### When Fast Track applies

During Routine 3 (Step 2) and Routine 5 (Step 4):

1. Look up the artist in `fast_track.tsv`
2. Check all three caps against the show details
3. **All caps satisfied** → present as **Fast Track buy**. No potential list row needed.
4. **Any cap exceeded** → present as Choose recommendation, flagging which cap was exceeded

---

## `data/show_goals/hat_eligibility.tsv` protocol

Single source of truth for hat-signing eligibility (#115). Schema: `Artist | Hat Eligible | Basis`.
- **Semantics:** `Yes` = female artist or female front/co-lead. Band-member / backing-singer
  cases are `No` until a signature is actually obtained, then flipped with a membership
  `Basis` (materialized exception). `Basis` records membership/fronting facts only —
  never signature assertions; completion is sourced exclusively from `hat_signatures.tsv`.
- **Writes:** `staging`, full-file pushes, fresh blob SHA before every write. Not
  in-page-editable; keep it comment-free anyway.
- **Upkeep:** every new artist row in `artists.tsv` / `fast_track.tsv` / `follows_master.tsv`,
  and every new show row (headliner or named support) in `live_shows_current.tsv`, gets
  an eligibility row for any artist not already present in the same session.
- Forkers: the file is goal-specific and safe to delete — the builder emits
  `hat_eligible: null` when it is absent (graceful degradation per #115).

## `spending.tsv` write protocol

`dan2bit/live-shows-private → spending.tsv` is the **sole long-term authority** for
spending data. The per-show cost breakdown also lives in `current_private.tsv` (a
purchase-time snapshot), but that is not the authority.

**Always fetch `spending.tsv` fresh from the private repo immediately before appending.**
Do not rely on a locally cached copy — it may have been updated since pre-flight.

Append one row per show:

```
Show Date | Artist | Ticket Cost | Food & Bev | Parking | Merch | Artist Interaction | Show Total | Notes
```

This step is **mandatory even if all spending amounts are zero**. A missing row cannot
be reconstructed from the activity log alone. If the write fails for any reason:
present the full row data in conversation before closing the routine, flag it in the
activity log draft, and correct it before closing.

Commits to **`main`** in `dan2bit/live-shows-private`.

---

## `artist_modal_index.json` — frozen schema (issue #107)

Build-time precomputed payload for the artist modal / `#artist/{slug}` route. **Public**,
name-keyed, lazy-loaded on first open. Path: `data/artist_modal_index.json`. Rebuilt by CI
(`artist-modal-index.yml`, mirrors `recommend-index.yml`) on any change to a payload/score
source; commits to `staging`. The affinity score is a pure function of **public** data, so
the whole index is public-safe; the only personal signal (⭐ favorite, #116) is never baked
here — it merges client-side from the private repo when authed.

### Top level
Name-keyed dict (key = normalized name, post-`recommend_aliases.tsv`):

```jsonc
{
  "schema_version": 1,
  "generated_at": "2026-07-02T20:00:00Z",
  "artists": { "vanessa collier": { /* per-artist object */ } }
}
```

### Per-artist object (source · null-rule per field)

```jsonc
{
  "name": "Vanessa Collier",            // display name
  "slug": "vanessa-collier",            // route + cross-link key
  "spotify_id": "5WLpN9bFV4liSYhf4J3aVs",
  "mbid": "…",                          // artist_spotify.json lastfm.mbid; null if absent

  // Identity
  "image_url": "https://i.scdn.co/…",   // BUILD-TIME resolved: Spotify Web API images[] -> embed og:image -> null
  "banner_url": null,                   // P2 (TheAudioDB/fanart.tv by mbid); null in P1
  "genres": ["blues","soul"],           // lastfm.tags (top N); [] if none
  "listener": {"tranche":"popular","raw":471203},  // lastfm.listeners + config; null if no listener data

  // Taste tier (dots + affinity input)
  "tier": {"label":"Strong","rank":4},  // follows_master Tier; rank 1-4 (Lower->Strong).
                                        //   Legacy / not-in-follows -> rank:null (no dots, excluded from affinity)

  // History — CANONICAL from ledger, NOT artists.tsv "Times Seen" (drifts after history repairs, cf #103)
  "seen": {
    "count": 7,                         // deduped rows across history/*.tsv + seen_with.tsv
    "first": "2023-10-14",
    "recent": "2026-05-03",
    "show_log": [                       // BAKED (bounded ~1-7 rows/artist; self-contained modal)
      {"date":"2026-05-03","venue":"The Hamilton","via":null,"photo_url":"https://…"},
      {"date":"2024-…","venue":"…","via":"SatchVai Band","photo_url":null}  // via = headliner for seen_with
    ]
  },
  "fast_track": false,                  // fast_track.tsv membership (affinity floor + "1st" framing)

  // Affinity gauge — build-time derived (see formula below)
  "affinity": {"score":0.976,"band":"high"},  // null when render-gate fails (no hat). Never 1.0 (⭐ pins client-side).

  // Badges
  "badges": {
    "hat": "completed",                 // completed|not_yet|absent — hat_eligibility.tsv(#115)+hat_signatures.tsv (canonical); not_yet suppressed while hat_eligible null
    "book": "completed",                // autograph_books_eligibility.tsv (In APS/RHBS + page) + book_signatures.tsv (completion via attribution)
    "book_detail": {"aps":{"in":true,"signed":true,"page":"42"},"rhbs":{"in":false,"signed":false}},
    "vip": 2,                           // artists.tsv VIP Count (non-numeric -> 0)
    "photo": 3                          // count of non-null show_log[].photo_url; badge when >0. (-> Google Photos link deferred: #117)
  },

  // Music
  "latest_release": {                   // null if none
    "name":"Do It My Own Way","type":"album","date":"2025-…",
    "url":"https://open.spotify.com/album/…",
    "image_url":"https://i.scdn.co/…"   // BUILD-TIME resolved (same chain as identity)
  },

  // Similar (resolved)
  "similar": [                          // lastfm.similar
    {"name":"Southern Avenue","in_tracker":true,"slug":"southern-avenue"},  // -> cross-link modal
    {"name":"Nikki Hill","in_tracker":false,"slug":null}                     // -> client builds Last.fm link
  ],

  // Links footer (constructed/resolved at build; null when unavailable)
  "links": {
    "spotify":"…","youtube":"…","lastfm":"…",
    "musicbrainz":"https://musicbrainz.org/artist/{mbid}",
    "bandsintown":"…","seated":null,
    "setlistfm":"https://www.setlist.fm/search?query=…"   // search link (decision 4)
  }
}
```

### NOT in the index (row-local — joined client-side from loaded arrays)
Upcoming **countdown**, the **"Considering {date} · {venue} · {decision}"** line, and the
**venue drive-time chip** come from the already-loaded `live_shows_current` /
`live_shows_potential` arrays at render time — never baked (so they never go stale).

### Client-side overlays (not baked)
- **⭐ favorite (#116, P2):** merges only when authed; overrides `affinity.score -> 1.0`
  and adds the star marker. Private repo; never in this public index.
- **`features.spotify: false`:** hides the music/lastfm sections; the fields still ship.

### Affinity formula (config: `config.yaml -> badges.affinity`)
```
T    = Strong 1.0 · Medium-Strong 0.7 · Medium 0.45 · Lower 0.2 · (Legacy|not-in-follows) -> null->0
S    = 1 - exp(-seen/2.5)                    # seen from history + seen_with; asymptotic (S(1)=0.33, S(7)=0.94)
Seff = max(S, fast_track ? 0.33 : 0)         # fast-track floors at "seen once"
G    = goals = 0.6·hat_signed + 0.4·book_signed   # goals composite (config: goals_split); extensible per #85
score = clamp(0.35·T + 0.40·Seff + 0.25·G, 0, 1)   # asymptotic; NEVER 1.0 without the ⭐
render the hat iff (T!=null OR seen>0 OR any signing OR fast_track)
band  = high >=0.60 · medium >=0.30 · low <0.30      # frozen; also in config
```

### Badge state rules
- **hat:** absent if not `hat_eligible` (#115) · completed if any canonical signer in
  `data/show_goals/hat_signatures.tsv` maps to the artist per the attribution vocabulary
  in `docs/GOALS_SPEC.md` § Source binding syntax (`self`, `of <band>`, `<name> entry`
  credit; `w/ <band>` and `co-bill w/ <band>` don't) · else not_yet. Completed always
  wins regardless of eligibility. `hat_eligible` is null only for artists outside
  `data/show_goals/hat_eligibility.tsv`; while null, render completed-vs-absent only.
- **book:** absent if `In APS`!=Yes AND `In RHBS`!=Yes (per
  `data/show_goals/autograph_books_eligibility.tsv`) · completed if any row in
  `data/show_goals/book_signatures.tsv` maps to the artist per the attribution
  vocabulary (same rules as hat) · else not_yet. `book_detail` (`{aps: {in, signed, page},
  rhbs: {in, signed}}`) is derived from the same two files: `in`/`page` from
  eligibility, `signed` per-book from the event log.
- **photo:** count of non-null `show_log[].photo_url`; badge when >0 (-> link: #117).

### Builder inputs (all public -> index is public-safe)
`history/*.tsv` + `seen_with.tsv` (seen) · `follows_master.tsv` (tier) · `fast_track.tsv`
(floor) · `artists.tsv` (photo/Spotify, VIP) · `data/show_goals/hat_eligibility.tsv`
(hat eligibility, #115) · `data/show_goals/hat_signatures.tsv` (hat completion, canonical) ·
`data/show_goals/autograph_books_eligibility.tsv` (book eligibility + page) ·
`data/show_goals/book_signatures.tsv` (book completion, canonical) ·
`artist_spotify.json` (image_url, latest_release,
lastfm, similar) · `config.yaml` (weights, tranches) · `recommend_aliases.tsv` (normalize).

Related: #107 (parent) · #115 (`hat_eligible`) · #116 (⭐ favorite) · #117 (photo link).
