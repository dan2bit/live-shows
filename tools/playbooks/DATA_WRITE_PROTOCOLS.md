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
