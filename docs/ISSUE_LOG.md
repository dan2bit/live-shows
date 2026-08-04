# Issue log

The design decisions in this repo's code and docs were driven by specific issues and
incidents. Code comments and forker-facing docs describe those designs on their own
terms; this file is the one place the history lives. Each row maps an issue (or
incident) to what it drove, so a reference removed from a comment is never orphaned.

Dan-facing surfaces (`tools/` playbooks, the private repo) keep inline issue
references as working shorthand and are not logged here.

| Issue | What it drove |
|---|---|
| [#59](https://github.com/dan2bit/live-shows/issues/59) | The public/private data split: cost, seat, quantity, and cap columns moved to the private sidecar repo; the public TSVs carry denormalized flags only. |
| [#69](https://github.com/dan2bit/live-shows/issues/69) | `config.yaml` itself — personalization externalized from the site code; `DEFAULT_CONFIG` fallback; static-head mirroring convention in `index.html`. |
| [#71](https://github.com/dan2bit/live-shows/issues/71) | Theme color variables in `styles.css` driven from config; the intentionally-preserved accent `#c83020` (AA-contrast discussion). |
| [#73](https://github.com/dan2bit/live-shows/issues/73) | The Spotify subsystem: write-MCP + local read cache architecture (`spotify_cache.py`). |
| [#76](https://github.com/dan2bit/live-shows/issues/76) | **Incident 2026-06-27:** private purchasing data was committed to a folder inside the public repo. Drove the private-data guard workflow, the staging→main auto-promote pipeline with the required `guard` check, and the playbook reorganization. |
| [#77](https://github.com/dan2bit/live-shows/issues/77) | The in-page config editor (gear) for authed users. |
| [#80](https://github.com/dan2bit/live-shows/issues/80) | **Incident:** a `#` comment block in an in-page-editable TSV wiped all rows on save (the editor derives the header from line 1). Drove the no-comment-blocks rule for `current`/`potential`/`fast_track`. |
| [#82](https://github.com/dan2bit/live-shows/issues/82) | Config phase 5: tab labels, feature toggles, display preferences, decision-stage display strings, merch threshold. |
| [#85](https://github.com/dan2bit/live-shows/issues/85) | Badge taxonomy: show/ticket state separated from goals; config-driven `show_goals` with the delete-it-all exit criterion. |
| [#87](https://github.com/dan2bit/live-shows/issues/87) | Group/Solo badge + authed ticket-count visibility, per config. |
| [#89](https://github.com/dan2bit/live-shows/issues/89) | `site.data_branch` / `?dataref` override so the site can read TSVs from a non-default branch (PR preview). |
| [#94](https://github.com/dan2bit/live-shows/issues/94) | `spotify_cache.py --add-artist --to research\|fast_track\|seen_with`. |
| [#97](https://github.com/dan2bit/live-shows/issues/97) | Cache reads `seen_with.tsv`; the permanent-unresolvable skip list. |
| [#100](https://github.com/dan2bit/live-shows/issues/100) | Misattribution guard in the release fetch (a Bach album landed on Angelique Francis) + `--stale-days`. |
| [#102](https://github.com/dan2bit/live-shows/issues/102) | `seen_with` artists included in the History search filter. |
| [#103](https://github.com/dan2bit/live-shows/issues/103) | Bill-component ledger modeling: the `Via` column, the would-they-headline test, `seen_with.tsv` for sidemen. |
| [#107](https://github.com/dan2bit/live-shows/issues/107) | The artist modal / `#artist/{slug}` route and its build-time index (`artist_modal_index.json`, frozen schema). |
| [#109](https://github.com/dan2bit/live-shows/issues/109) | A null release pull must never overwrite a known release (keep-on-miss rule in the cache). |
| [#115](https://github.com/dan2bit/live-shows/issues/115) | `hat_eligible` schema: eligibility file as single source of truth; materialized-exception flips; `Basis` records membership facts only. |
| [#116](https://github.com/dan2bit/live-shows/issues/116) | Explicit favorite: PUBLIC `data/artist_favorites.tsv` (privacy reversal 2026-07-15), gauge-as-control with confirm-below-band friction, `features.favorite`. |
| [#117](https://github.com/dan2bit/live-shows/issues/117) | Photo badge links to the Google Photos album; `artist-photos.tsv` pipeline and the photo-issue close workflow. |
| [#119](https://github.com/dan2bit/live-shows/issues/119) | Times Seen drift audit: ledger recount vs `artists.tsv`, the read-only CI check, Routine 2 reconciliation step. |
| [#121](https://github.com/dan2bit/live-shows/issues/121) | `seen_with.tsv` conventions cleanup. |
| [#124](https://github.com/dan2bit/live-shows/issues/124) | Semantic markup / a11y pass on `index.html`; utility modals placed at the end of the DOM. |
| [#125](https://github.com/dan2bit/live-shows/issues/125) | Build-time cached artist/release art replacing failed oEmbed fetches. |
| [#126](https://github.com/dan2bit/live-shows/issues/126) | `--audit-ids` / `--repoint` for wrong-profile spotify_ids. |
| [#131](https://github.com/dan2bit/live-shows/issues/131) | Artist-photo handling: `artist-photos.tsv` as sole photo record; the `Photo` column removed from `artists.tsv`. |
| [#140](https://github.com/dan2bit/live-shows/issues/140) | Config-driven row goal badges; note-string detection retired. |
| [#142](https://github.com/dan2bit/live-shows/issues/142) | Bot-vs-bot push races: the retry-with-rebase loop in every workflow that pushes to staging. |
| [#145](https://github.com/dan2bit/live-shows/issues/145) | `--new-artist` chaining resolve + images + Last.fm for skeleton entries. |
| [#146](https://github.com/dan2bit/live-shows/issues/146) | Search empty-state render race with lazy history loading (re-render on load completion). |
| [#148](https://github.com/dan2bit/live-shows/issues/148) | On This Day carousel (one match at a time, dots control). |
| [#150](https://github.com/dan2bit/live-shows/issues/150) | Bill-name decomposition for the goal join (`_goalBillKeys` / `bill_keys()` twins); explicit separators, no fuzzy matching. |
| [#152](https://github.com/dan2bit/live-shows/issues/152) | In-page purchase flow: 🎟 bought modal (client does 4 simple writes), CI reconciler owning all derived potentials/fast-track state, the `in-page purchase` provenance marker. |
| [#154](https://github.com/dan2bit/live-shows/issues/154) | `signed` vs `completed` badge semantics: an obtained autograph stops advertising as planned on future rows. |
| [#159](https://github.com/dan2bit/live-shows/issues/159) | `--prune` safety around deliberately-excluded artists. |
| [#160](https://github.com/dan2bit/live-shows/issues/160) | One shared surface-form vocabulary (`name_forms.py`) across the cache, index builders, and audits — Last.fm lookups no longer stamp false nulls on bill names. |
| [#165](https://github.com/dan2bit/live-shows/issues/165) | Flat affinity G-term: every goal completion event equal-based with diminishing increments (`G = 1 − d^n`). |
| [#171](https://github.com/dan2bit/live-shows/issues/171) | The artist-graph research page (force-directed Last.fm network, Pages-served, unlinked). |
| [#174](https://github.com/dan2bit/live-shows/issues/174) | Kinship edges: `related_acts.tsv` + `Via`-derived bill edges; kin suppresses the duplicate taste edge. |
| [#177](https://github.com/dan2bit/live-shows/issues/177) | Concert-history edges from Dan's own logs: bill edges (attended only), shared-personnel pairs, sideman↔act attribution incl. the support-slot note convention. |
| [#180](https://github.com/dan2bit/live-shows/issues/180) | Graph cosmetics: home link, ringed-node marker, authed graph link on the site header, zoom tool, tooltip badge chips. |
| [#183](https://github.com/dan2bit/live-shows/issues/183) | Resilience for missing `row.items()` in the cache. |
| [#186](https://github.com/dan2bit/live-shows/issues/186) | Box-office badge: explicit `Box Office` flag on potentials + venue cross-reference, replacing note-text matching; `In Person Box Office` venue capability column; warn-only guardrail. |
| [#189](https://github.com/dan2bit/live-shows/issues/189) | Venue identity as shared data: `venue_aliases.tsv` + venues.tsv `Short Name`, one resolution chain across app.js, the guardrail, and the YouTube tooling. |
| [#193](https://github.com/dan2bit/live-shows/issues/193) | Photo-issue close also writes the share link into the matching show row's `Photo URL`. |
| [#197](https://github.com/dan2bit/live-shows/issues/197) | Stale-days inference from the sweep's oldest recent check (the median re-burned half the previous sweep against the API quota). |
| [#199](https://github.com/dan2bit/live-shows/issues/199) | De-bespoke sweep: owner-specific assumptions pulled out of the shared surfaces so a fork reads as a template, not as one person's tracker. |
| [#200](https://github.com/dan2bit/live-shows/issues/200) | This log, plus the evergreen-comment convention: forker-facing comments stand on their own; issue history lives here. |
| [#201](https://github.com/dan2bit/live-shows/issues/201) | config.yaml restructured into forker reading order, with opt-in blocks (merch cap) marked as such and the meta block documented as record-only. |
| [#202](https://github.com/dan2bit/live-shows/issues/202) | FORK_SETUP rewritten as three stopping points: UI-only, private sidecar, full CI pipeline. |
| [#203](https://github.com/dan2bit/live-shows/issues/203) | Spotify workflows split into their own playbook, with the ephemeral-by-default persistence rule. |
| [#204](https://github.com/dan2bit/live-shows/issues/204) | Warn-only data-hygiene guards (ASCII punctuation, artist-name drift, evergreen comments) as a CI backstop for conventions previously enforced only at write time. |
| [#205](https://github.com/dan2bit/live-shows/issues/205) | Playbook additions: batch-commit rule, ASCII punctuation rule, alias-key frozen schema. |
| [#216](https://github.com/dan2bit/live-shows/issues/216) | Level 0 fork bootstrap: the sample-files/ exemplar tree, fork_reset.py, and the CI check that fails when a sample header drifts from its canonical file. The private-data guard and its auto-promote mirror gained a sample-files/private/ exemption; both copies of the sniff must be edited together. |
| [#227](https://github.com/dan2bit/live-shows/issues/227) | Replaced the hardcoded `_UNRESOLVABLE_ARTISTS` set with `data/spotify_unresolvable.tsv` (dated, reasoned, self-expiring via `Recheck After`); the `--new-artist`/bare-mode "Unresolved" reports now print ready-to-paste rows instead of just names. |
| [#229](https://github.com/dan2bit/live-shows/issues/229) | Scheduled Spotify sweeps: the `--limit` voluntary request budget enforced at the shared request layer (`BudgetExhausted` exits 0 — a spent budget is a scheduled run's expected end; a real 429 stays exit 1), the late-month `--refresh-releases` workflow with an explicit `--stale-days` sized for the monthly gap the auto-inferrer can't straddle, and the weekly Last.fm-seed → `--new-artist` resolve pass (seeding must run first: bare mode only sees cache skeletons). |
| [#240](https://github.com/dan2bit/live-shows/issues/240) | `prune_potentials.py` now checks `data/artists.tsv` and `follows_master.tsv` before appending a pruned artist to NAR — an already-seen/already-followed artist (e.g. Mohini Dey) no longer lands in NAR just because their potentials row got pruned as past-dated. |
| [#238](https://github.com/dan2bit/live-shows/issues/238) | `build_artist_index.py` emits proper display names: `display_name()` de-inverts "X, The" at emission (ported from `build_recommend_index.py`), surface-casing `see()` passes were added for follows / fast-track / book-eligibility (collected as normalized keys only, so their cased names never reached the display map), and the universe fallback moved to run last with Title-Case as the true last resort. 266 of 628 records recovered proper names; slugs and keys byte-identical (both derive through `norm()`, which is invariant to every change made). Deliberately-lowercase stage names (boygenius) survive because a real source surface form always beats the fallback. |

Other incident dates that appear in history: the Spotify Web API deprecations of
2024-11-27 (dev-mode metadata strip) and the 2026-02-11 → 2026-03-09 endpoint
migration both reshaped `spotify_cache.py`'s scope — context lives in the #73
thread.
