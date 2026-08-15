---
name: live-shows-inbox
description: Triage and process the live-shows project inbox (redhat.bootlegs@gmail.com). Use whenever Dan mentions a ticket receipt, a Ticketmaster/AXS/Eventbrite order or confirmation email, forwarding a receipt, show notes from a recent concert, ticket alerts or venue newsletters, artist follow/signup emails, a resold ticket, "process the inbox", "run Routine N", "what's in the inbox", or asks whether anything in the concert inbox needs attention. Also use when Dan mentions buying concert tickets and the purchase needs to be recorded. Do NOT use for site/repo development, YouTube playlist tooling, or general conversation about shows and artists.
---

# Live-Shows Inbox — Triage and Routines

The repo playbook `tools/playbooks/EMAIL_WORKFLOWS.md` in `dan2bit/live-shows` is
the single source of truth for how routines execute. This skill exists for two
reasons: (1) so receipt/notes/alert language reliably starts the workflow without
Dan having to remember to invoke it, and (2) to open every inbox session with a
triage snapshot — queue depth and gap nudges — before any routine runs. Never
execute a routine from memory of the playbook; fetch it fresh (Step 3).

## Step 1 — Pre-flight

1. Establish today's date via the `current-date` skill (real clock, America/New_York).
   Never trust context or model memory for the date.
2. Fetch from `dan2bit/live-shows` (branch `main`) and hold for the session:
   - `data/live_shows_current.tsv`
   - `data/live_shows_potential.tsv`

If the clock or either fetch fails, stop and tell Dan — the gap checks and
duplicate suppression below depend on them.

## Step 2 — Triage snapshot (read-only; always runs first)

### 2a — Queue depth

Run the six searches and count unprocessed threads per routine:

| Routine | Query |
|---|---|
| 1 Ticket receipt | `label:ticket-receipt -label:processed` |
| 2 Show notes | `label:show-notes -label:processed` |
| 3 Ticket alert | `label:ticket-alert -label:processed` |
| 4 Artist mail | `label:artist-mail -label:processed` |
| 5 Artist follow | `label:artist-follow -label:processed` |
| 6 Ticket sold | `label:ticket-sold -label:processed` |

Then establish **per-routine last-run dates** — Dan rarely runs all six at once,
so a single "last inbox run" date hides which queues are actually stale. Every
routine invocation ends with a draft whose subject is
`[LOG] Routine N — ... — YYYY-MM-DD`, so the drafts folder is the run ledger:
search drafts for `subject:[LOG] "Routine N"` per routine (results are
newest-first; the top hit's date is the last run) and add a "Last run" column
to the queue table. Flag any routine 7+ days stale *that also has unprocessed
threads* — a stale-but-empty queue needs no attention. Two caveats: Routine 5
pure reminders are labeled `processed` without a log draft, so its date can
understate recency; and Routine 6 may legitimately show months since last run
(resales are rare).

### 2b — Missing show-notes nudge

Any `live_shows_current.tsv` row whose show date is **3+ days past** but whose
Status is still `upcoming` means Routine 2 never ran for that show (the
status flip to `attended` is that routine's fingerprint). Nudge:
"[Artist] was N days ago and is still marked upcoming — no show-notes email yet."

### 2c — Missing ticket-receipt nudge

The rhbl account cannot see the dan2bit inbox, so receipt gaps are inferred:

1. **In-page purchase, no forward:** fetch `current_private.tsv` from the
   **repo** `dan2bit/live-shows-private` (file at that repo's root). Rows whose
   Private Notes carry an `in-page purchase YYYY-MM-DD` marker but no order
   number → search `label:ticket-receipt` (processed or not) for the artist;
   no thread → Dan bought via the site modal and never forwarded the receipt.
2. **Buy row past its window:** a `Buy` decision in `live_shows_potential.tsv`
   whose `Watching For` on-sale date is past → either bought-but-not-forwarded
   or not yet bought. Nudge either way.
3. **Stale ON SALE event:** list Dan Concert Calendar (`redhat.bootlegs@gmail.com`,
   never `primary`) events titled `ON SALE:` in the past ~60 days; if the artist
   is still a potentials row (not in `live_shows_current.tsv`), surface it.
   Skip this check gracefully if calendar tools are unavailable (they fail
   silently on Android — suggest the macOS desktop app).

An impulse buy with no prior trigger is undetectable until forwarded — say so
only if Dan asks why something was missed.

### 2d — Report

Present one compact summary: queue table, days-since-last-run, and any nudges
from 2b/2c. Recommend a run order — Routines 1 and 2 first (rare,
high-stakes writes), then the bulk sift of 3/4/5, then 6 — and let Dan pick.
Do not start processing threads until Dan chooses.

## Step 3 — Execute routines from the live playbook

Before processing any thread, fetch `tools/playbooks/EMAIL_WORKFLOWS.md` fresh
from `dan2bit/live-shows` `main` and follow it exactly for the chosen
routine(s), including its Step 0 pre-flight, confirmation gates, activity log
draft, and `processed` labeling. The playbook evolves; a cached or remembered
version of it has caused real data errors.

Two invariants worth carrying even if the fetch fails (in which case stop and
tell Dan rather than improvising):

- **Private data boundary.** Cost, seat info, ticket quantity, and private
  notes commit ONLY to the separate repo `dan2bit/live-shows-private`, at that
  repo's root — never to any path inside the public `dan2bit/live-shows` repo.
  Public fields and private fields are two commits to two repos. A path like
  `live-shows-private/<file>` inside the public repo is a data leak, not a
  shortcut.
- **Ticketmaster quantity.** TM confirmation emails omit quantity and
  per-ticket price. Never default quantity to 1; a pasted order-detail block
  may appear anywhere in the forwarded message (often above the forwarded
  body). Details in the playbook's Routine 1 Step 1.
