# GOALS_SPEC.md

Frozen design for the show-goals system (issue [#85](https://github.com/dan2bit/live-shows/issues/85)).
This document is the spec that sub-issues #138 (books split), #139 (builder), and #140
(app.js row badges) implement against. Ratified 2026-07-09 via [#137](https://github.com/dan2bit/live-shows/issues/137).

---

## Overview

A **goal** is a tracked accomplishment (hat signed, book signed, photo taken, video
captured) that binds to existing data sources rather than a dedicated per-row column.
Goals produce badges on show rows and in the artist modal, and contribute to the
affinity score.

The design principle is **source-binding + universal-null degradation**: each goal
declares where its accomplishment data lives; missing data (absent file, empty config,
uncurated artist) degrades gracefully to `absent` without new builder semantics.

Deleting `data/show_goals/` entirely, or emptying the `show_goals` config list,
produces a badge-free but fully functional site. This is the exit criterion for the
#85 umbrella.

---

## Config shape

Goals are declared in `config.yaml` as a list under `show_goals`:

```yaml
show_goals:
  - key: hat
    label: HAT
    icon: "🎩"
    color: "#e8a838"
    source: event_log:hat_signatures
    eligibility: hat_eligibility
    weight: 0.6
  - key: book
    label: BOOK
    icon: "📚"
    color: "#8b6b4a"
    source: event_log:book_signatures
    eligibility: autograph_books_eligibility
    weight: 0.4
  - key: photo
    label: PHOTO
    icon: "📷"
    color: "#5aa1e5"
    source: column:Photo URL
  - key: video
    label: VIDEO
    icon: "🎬"
    color: "#c85555"
    source: column:Playlist URL
```

Fields per entry:

| Field | Required | Description |
|---|---|---|
| `key` | yes | Stable identifier used in badges and index (`hat`, `book`, `photo`, …) |
| `label` | yes | Short display string for the badge |
| `icon` | yes | Emoji string (no icon-path system) |
| `color` | yes | Badge color as CSS hex |
| `source` | yes | Binding rule; see [Source binding syntax](#source-binding-syntax) |
| `eligibility` | no | Eligibility file name (without extension) under `data/show_goals/` |
| `weight` | no | Affinity contribution weight; see [Affinity contribution](#affinity-contribution) |

The four goals above are the initial set (2026-07-09). A fork may add, remove, or
edit any entry without code changes.

---

## Source binding syntax

Three binding types, all string-form for YAML readability. A goal has exactly one
binding — no merging of multiple sources per goal.

### `event_log:<name>`

Resolves to `data/show_goals/<name>.tsv`. Base schema (hat pattern established
by #115):

```
seq | signer | attribution | show_date | venue | region | photo_ref | legible | confidence | notes
```

`book_signatures` inserts a `book` column between `attribution` and `show_date`
(indicating which book was signed, e.g. `APS` or `RHBS`).

**Attribution vocabulary** — the string in the `attribution` column determines how a
signature maps to artists:

| Attribution | Maps to |
|---|---|
| empty or `self` | the `signer` value only |
| `of <band>` or `w/ <band>` | both `<band>` AND the `signer` (treated identically) |
| any other freeform text | the `signer` only |

Example: signer=`Kanene Pipkin`, attribution=`of The Lone Bellow` maps to both
`Kanene Pipkin` and `The Lone Bellow` — either would render the badge as completed.

### `column:<name>`

Non-empty check on a named column of the show row. Empty string, `-`, and `None`
all count as absent; any other value counts as present.

### `interaction:<value>[|<value>...]`

Matches when the `Artist Interaction` field equals any of the listed values.
E.g. `interaction:Photo|Both`. This binding demotes Artist Interaction from a
parallel encoding to storage that goals bind to.

---

## Eligibility file (optional per goal)

An eligibility file lives at `data/show_goals/<name>.tsv` (name from the `eligibility`
config field). Schema:

```
Artist | Eligible | Basis
```

The second column header is **`Eligible`** (uniform across goals) — not `Hat Eligible`.
This is a rename from the current hat file's schema; the semantic content is unchanged.

**Semantics** vary by goal, but the mechanics are shared:

- **Curated eligibility** (hat): `Yes` = "would I try to get this signed?" — hand-curated intent per #115.
- **Factual eligibility** (book): `Yes` = "is this artist printed in the book?" — book-entry keyed.
  Book files carry additional columns alongside `Eligible` (per-book `In APS`, `APS Page`, `In RHBS`).
- **Event-log-only goals** (picks, paper setlists): no eligibility file. Universal-null degradation
  applies — the builder emits `eligible: null`, which renders completed-vs-absent only.

Absent-file and universal-null are the same code path (the builder's existing
degradation from #115); no new semantics are introduced.

---

## State rules

Three states per goal: **`completed`**, **`planned`**, **`absent`**. Computed on the fly,
never stored. `completed` always wins over eligibility.

### Row-level (a specific show row × goal)

Rendered as the row's badge in the show tables (`app.js` `buildBadges`).

| Source type | `completed` | `planned` | `absent` |
|---|---|---|---|
| `event_log` | any signature's `show_date` matches AND attribution maps to the row's artist | `Eligible=Yes` AND row is upcoming AND not completed | otherwise |
| `column` | column non-empty and not `-` | row is upcoming AND not completed | otherwise |
| `interaction` | AI field matches any configured value | row is upcoming AND not completed | otherwise |

### Artist-level (modal / affinity)

Rendered as the modal badge and fed into the affinity G-term.

| Source type | `completed` | `planned` | `absent` |
|---|---|---|---|
| `event_log` | any signature row maps to this artist (attribution rule) | `Eligible=Yes` AND not completed | otherwise |
| `column` | any of this artist's rows satisfies the check | — (column sources don't project artist-level intent) | otherwise |
| `interaction` | any of this artist's rows matches | — | otherwise |

Note: for `column` and `interaction` sources at the artist level, the `planned` state
is not defined — these sources describe what happened at shows, not intent about the artist.

---

## Affinity contribution

Goals composite into the G-term of the affinity formula:

```
G = Σ (weight_i × completed_i)   for goals i with `weight` set
```

Where `completed_i` is 1 if the artist-level state is `completed`, else 0.

**Weight sum rule.** Weights across all goals with a `weight` field must sum to 1.0
(within floating-point tolerance). This matches today's `{hat: 0.6, book: 0.4}` in
`config.yaml → badges.affinity.goals_split`. Goals without `weight` render badges
only and contribute nothing to affinity.

**Validator.** The builder validates the weight sum against `config.yaml`
specifically — narrowly targeted, not a general schema linter. On a mismatch, the
build fails with a clear error message identifying the offending goals and their
sum. This catches silent scoring drift when a fork edits weights or adds a
weighted goal without renormalizing.

**Affinity formula overall** (unchanged from today):

```
score = 0.35·T + 0.40·Seff + 0.25·G
```

---

## Rollout ordering

Strict S2 → S3 → S4:

### S2 — Books split (#138)

- Rename `autograph_books_combined.tsv` → `autograph_books_eligibility.tsv`; header second column becomes `Eligible`; extract `Signed`/`Notes` columns out.
- New `book_signatures.tsv` mirroring the hat pattern, with the extra `book` column between `attribution` and `show_date`.
- Backfill dates (research complete per #138: 18 events / 21 rows including attribution expansions).
- Builder gets a **temporary compat-read** that unions the two new book files into the shape S3 expects — so S2 can land without S3 being ready. Compat-read is removed as part of S3.
- Playbook ride-alongs: `EMAIL_WORKFLOWS.md` book steps, `DATA_WRITE_PROTOCOLS.md` book protocol section and `hat_eligibility` header uniformity note.

### S3 — Builder (#139)

- Consume `show_goals` config; iterate goals generically per source binding.
- Retire the deprecated `artists.tsv Hat Autograph` column read (currently at ~line 298 of `scripts/build_artist_index.py`) and remove the column from `artists.tsv` in the same PR.
- Bake per-show goal accomplishments into each artist's `show_log` entries so S4's row badges can join client-side without extra fetches.
- Implement the [weight sum validator](#affinity-contribution) targeted at `config.yaml → show_goals`.
- Remove the S2 compat-read.

### S4 — app.js row badges (#140)

- Retire `HAT:` / `BRING RHBS` / `BRING APS` string matching at all three sites (`buildBadges` ~lines 298–299; history renders ~765/789).
- Render row badges from the S1 config list + S3's baked `show_log` events.
- The `HAT:` / `BRING` note-strings stay in the data as inert human reminders; Routine 1 continues writing `BRING` reminders to calendar descriptions (human-facing, doesn't drive badges).

**No data cleanup required** at any stage — nothing parses the note-strings after S4 lands.

---

## Explicit non-goals

- **No merging of multiple bindings per goal** (YAGNI). One `source` per entry.
- **No config-driven state badges** (Seat / VIP / Group). Those stay code-fixed; config
  exposes thresholds and colors only, as today.
- **No per-book row-level badges.** The book row badge shows the artist's overall signed
  state; per-book detail (`In APS` / `APS Page` / `In RHBS` + signed states) remains
  modal-only via `badges.book_detail` (per #107).
- **Icons stay emoji strings.** No icon-path system, no font-icon integration.
- **No storage of `planned` state.** It's computed at render time from eligibility +
  upcoming + not-yet-completed. There is no `Goal Planned` column anywhere.

---

## Exit criterion for #85

Deleting `data/show_goals/` **and** emptying `config.yaml → show_goals` yields a
badge-free but fully functional site. If either condition alone doesn't degrade
gracefully, the implementation has a bug.

---

Related: #85 (umbrella) · #107 (frozen index schema) · #115 (hat_eligibility) ·
#118 (artist modal builder) · #131 (photo derivation) · #137 (this spec) ·
#138 (S2) · #139 (S3) · #140 (S4).
