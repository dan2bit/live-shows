# FOLLOWS_PIPELINE.md

How the three follow ledgers relate, the invariants that keep them honest, and
what a promotion writes. The write mechanics (branches, SHAs, ASCII punctuation)
are in `DATA_WRITE_PROTOCOLS.md`; the monthly reconcile is Workflow 1-B in
`ANALYSIS_WORKFLOWS.md`; the export procedures are in `../research/web-src/scraping_tasks.md`.

## The ledgers

Three ledgers, one direction of travel:

| Ledger | Meaning | Followed on platforms? |
|---|---|---|
| `tools/research/follows/new_artist_research.tsv` (NAR) | precursor set - candidates under research | **never** |
| `tools/research/follows/follows_master.tsv` | approved to follow; the platform flags say where | yes, as flagged |
| `data/fast_track.tsv` | pre-authorised buy; jumps the queue | yes, both platforms |

Songkick is frozen: the `follows_master` flag is historical and is never reconciled.

## Invariants

Checked by `tools/research/reconcile_follows.py`. Invariants 1-3 need only the
repo and also run advisory in `data-hygiene.yml`; invariant 4 needs the committed
platform exports.

1. NAR ∩ `follows_master` = ∅. A row leaves NAR on promotion or rejection.
2. NAR ∩ `artists.tsv` = ∅. Seen live means a `follows_master` decision, not research. `prune_potentials.py` enforces this with the repo's name normalization and alias map, so band-name variants do not slip through.
3. `fast_track` ⊂ `follows_master`. Tier is **not** constrained - fast track means a strong buy, not automatically Strong tier.
4. Every artist the rhbl account follows has a `follows_master` row, and every row flagged Y is actually followed. NAR gets no platform columns; a followed artist with only a NAR row is drift, resolved by promoting or unfollowing.
5. `NOT ON SEATED` / `not on Seated service` in a `follows_master` note marks an expected gap, never drift. A note that says so for an artist who is in fact followed is a note to fix.

## Promotion: delete on promotion, with a condensed carry-over

No tombstones. The NAR row is removed and three tokens survive into the
`follows_master` `Notes` column, semicolon-separated, each optional:

| Token | From | Example |
|---|---|---|
| `src: <short source>` | NAR `Signal` / `Source` - **always written** | `src: BMA 2026 nominee`, `src: Gnoosic ex.8`, `src: Joe Murphy` |
| `tour: <shape>` | NAR `USA Touring` + touring remarks | `tour: festivals + cruises, rare solo US dates` |
| free remark | venue-shape / hat / format only | `Birchmere-shaped`, `hat eligible`, `trio format` |

`src:` matters beyond the artist: the taste profile weights curated sources by
hit rate, which is only computable if each follow records where it came from.
Bio prose is re-derivable and is dropped. Prune-generated `pending-review` rows
are deleted on resolution with nothing carried; a standing-policy reason found
in one moves to the taste profile once, not per artist.

Every promotion also:

- adds a `data/show_goals/hat_eligibility.tsv` row for the artist if absent (see the hat protocol in `DATA_WRITE_PROTOCOLS.md`)
- adds a `data/recommend_aliases.tsv` row when the platform display name differs from the ledger name - never a hand edit of the platform export, which is evidence of what the account follows

## NAR columns

```
Artist | Signal | Proposed Tier | Genre | Official Site | Bandcamp | Overview & Niche | USA Touring | Most Recent Release | Status | Source
```

`Proposed Tier` holds a tier word (Strong / Medium-Strong / Medium / Lower / Legacy)
or nothing; `Genre` holds the free-text kind of act. They were one column until
2026-09, which is why older rows have one or the other. `Status` is `active`
(under research) or `pending-review` (auto-created by the prune path, unresearched).

## Reminder and reconcile

`follows-watch.yml` mails `[follows] N new - add to BIT/Seated` on any push to
`main` that adds a `follows_master` or `fast_track` row (`scripts/follows_reminder.py`).
The flag is set by hand when the follow is done. `reconcile_follows.py` against a
fresh export - Workflow 1-B - is what closes the loop; between exports the mail
carries the export ages so the staleness of the yardstick is always visible.
