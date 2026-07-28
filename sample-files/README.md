# sample-files/

Exemplar schema files for forkers (issue #216). Each `*-sample.tsv` carries the
canonical header of its `data/` counterpart plus **one clearly-synthetic row**
(`The Example Band`, `Example Hall`, 2099 dates) illustrating the column
conventions. `scripts/fork_reset.py` copies these over the live data files to
produce a clean, working, empty fork — see `docs/FORK_SETUP.md`.

- Public sample headers are **guarded against drift**: CI fails if a sample's
  header no longer matches its canonical file.
- `private/` holds seeds for the separate PRIVATE repo (`fork_reset.py
  --private-dir <path-to-private-clone>` writes them, minus the `-sample`
  suffix, to a directory that must be OUTSIDE this repo). These files carry the
  private schema headers on purpose and are exempted from the private-data
  guard's content sniff by path; they contain only synthetic rows. Their
  canonical schemas live in the private repo, so they are hand-maintained —
  update them when the private schemas change.
- The potentials bracket columns are **year-scoped** (`Prev Show (2026)`,
  `Next Show (2026)`) and must match the canonical header exactly — synthetic
  row *values* use 2099, but the header year is real. The January rollover
  renames these columns in the canonical file; update this sample's header in
  the same pass (the CI drift check will fail loudly until you do).
- **No sample carries `#` comment lines** — every one is header plus synthetic
  row, so a forker can read the schema off the first two lines of any file.
  For the in-page-editable files (`current`, `potential`, `fast_track`) this is
  load-bearing: the reset copies samples live, and a comment block in those
  files triggers the issue-#80 editor wipe bug. Guidance that would otherwise
  live in a comment block goes here instead.
- `private/fast_track_caps-sample.tsv`: the caps are a **buy-constraint policy**
  keyed to public `fast_track.tsv` by Artist. A blank cell means "no cap of
  this kind" and falls back to your default. The sample row shows the shape of
  a fully-specified entry (price ceiling, distance radius, venue scale); define
  whatever cap vocabulary you like — agents read these values as policy, so
  keep the wording consistent across rows.
