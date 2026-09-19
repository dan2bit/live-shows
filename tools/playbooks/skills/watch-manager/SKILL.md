---
name: watch-manager
description: Add, retire, or force-check a page watch in the daily page-watch system (tools/watch/watches.tsv) - the headless replacement for the retired changedetection pod. Use when Dan says "watch <url>", "add a watch for <artist/venue>", "stop watching X", "retire the X watch", "check the X watch now", or asks what's being watched. Do NOT use for the inbox routines (that's live-shows-inbox) or for one-off page lookups Dan isn't asking to watch repeatedly.
---

# Watch Manager - add, retire, and force-check page watches

`tools/watch/watches.tsv` in `dan2bit/live-shows` is the registry; `watch_diff.py`
and `extractors.py` in the same directory are the engine. `.github/workflows/
daily-page-watch.yml` runs it once a day, and each row's own `check_every_days`
decides whether it's actually fetched that day. Full design rationale, including
why this replaced the changedetection pod, is in the issue that opened it -
search `label:watch-alert` mail or `docs/ISSUE_LOG.md` if the history is needed.

## The constraint that governs every add (read this before proposing a URL)

**Nothing in this registry may need a browser to render.** The changedetection
pod was retired specifically because interactive Claude-for-Chrome or Desktop
reads a page fine - real browser session, no bot check - but the same page
checked unattended (no session, no browser) hits 403s or crashes outright.
InstantSeats (Blues Alley) is the one surface confirmed to work headless; that
is exactly why it's in the registry and nothing else is yet.

**Before proposing a row, test-fetch the candidate URL with a plain HTTP
fetch** (the `web_fetch` tool if the URL already appears in this conversation
or a search result; otherwise `web_search` for it first) or, from Desktop
Claude, `curl`. If the fetched content is empty, boilerplate-only, or
obviously missing the real listing (a JS-shell page that only renders client
side), **stop and say so plainly** - this candidate cannot be a daily CI watch.
Offer instead: the existing monthly interactive-Chrome pass, or looking for a
lower-JS surface for the same information (a venue's own ticketing platform is
often more scrapeable than its marketing site - that is precisely the InstantSeats
pattern). Do not add a row on the hope that it might work; a row that fails
silently every day is worse than not watching the page at all.

## Step 1 - Gather what the row needs

- **URL** - from Dan, or found via search if he names an artist/venue instead.
- **kind** - `artist` (a single-subject tour/shows page - any change on it is
  relevant by construction, mails on any diff) or `venue` (a multi-act listings
  page - needs an extractor, see Step 2). Ask if it's ambiguous from the page
  itself.
- **check_every_days** - ask, or default to 1 for anything Dan is actively
  waiting on (an on-sale countdown, the way this project's earlier one-shot
  watches worked), wider (5-7) for a passive general-interest page.
- **ignore_contains** - only matters for `artist` kind (raw text diff); look at
  the fetched page for obvious boilerplate that would otherwise churn every
  check (nav menus, a cookie banner, a "last updated" timestamp) and propose a
  `|`-separated list of substrings to drop. Leave `-` if nothing stands out.

## Step 2 - `venue` kind: draft an extractor together

A `venue`-kind page needs a function in `tools/watch/extractors.py` that turns
the fetched page into `{"date": "YYYY-MM-DD", "title": str, "status": str}`
records - see `blues_alley()` there for the pattern (day-of-week / date anchor,
walk visible lines via the shared `visible_lines()` helper, close each block on
a reliable boilerplate marker). Do this now, with the real fetched content in
hand, not from a template - every listings page's markup differs. If the site
labels its own off-profile categories the way Blues Alley does ("... Jazz
Series"), add an `offprofile(title)` function too; it's optional and only
saves an API call, so skip it if nothing about the source makes an obvious
free pre-filter.

Sanity-check the draft against the actual fetched page by hand before
proposing the row - count the events a human would see and compare to what
the function extracts. A mismatch here is the single most likely bug class in
this system.

## Step 3 - Propose, confirm, commit

Show the complete proposed `watches.tsv` row and (for `venue` kind) the
extractor function, exactly as they will be committed. Wait for Dan's explicit
go-ahead - same confirmation gate as `item-log` and every other write in this
project. Then:

1. Fetch fresh SHAs for `tools/watch/watches.tsv` and, if touched,
   `tools/watch/extractors.py`.
2. Append the row (`watches.tsv`, `staging`) - `last_checked` starts as `-`.
3. If `venue` kind, commit the extractor addition (`extractors.py`, `staging`).
4. **Do not fabricate a baseline snapshot.** Leave `tools/watch/snapshots/`
   alone; the first real CI run seeds it from a genuine live fetch and
   correctly sends no mail for that first run (nothing to diff against yet).
   A hand-written fake baseline risks the next real run reporting bogus
   "changes" that are really just a guess being wrong.

## Retiring a watch

Locate the row by name or slug, confirm with Dan, then:
- **Soft retire (default, reversible):** flip `active` to `N`. History and the
  snapshot stay in place; the row simply stops being checked.
- **Hard delete (only on explicit request):** remove the row from
  `watches.tsv` and delete its snapshot file(s) under `tools/watch/snapshots/`.

Either way: fresh SHA, confirm before committing, `staging`.

## Force-checking a site now, off its normal cadence

Two paths, and either is fine to offer:
- **Via CI:** `daily-page-watch.yml` takes a `force` input
  (`workflow_dispatch`) - Dan can trigger it from the Actions tab with the
  slug, which runs the exact same engine that runs daily.
- **In this session, right now:** if Claude has `bash_tool` (Desktop, or a
  Cowork-style environment), clone/fetch the relevant files and run
  `python3 tools/watch/watch_diff.py --force <slug>` directly - this is
  genuinely the same engine, not a simulation, and is a reasonable way to
  calibrate a brand-new extractor against live content before the first real
  CI run. It still needs the six tracking files and `score_candidates.py`'s
  dependencies present to fully exercise relevance scoring; without
  `LASTFM_API_KEY` set it degrades to cache-only scoring, same as CI would
  with the secret unset.

## What this skill is not for

- The six inbox routines (ticket receipts, show notes, alerts, etc.) - that's
  `live-shows-inbox`.
- A one-off "what does this page say right now" question Dan isn't asking to
  track repeatedly - just fetch and answer directly, no registry involved.
- Anything that needs a login, a personalized view, or a JS-rendered SPA shell
  to show real content - per the constraint at the top, that stays on the
  monthly interactive-Chrome pass, permanently, not as a "try it and see."
