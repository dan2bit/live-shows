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
- Never add `#` comment lines to samples for in-page-editable files
  (`current`, `potential`, `fast_track`): the reset copies samples live, and a
  comment block in those files triggers the issue-#80 editor wipe bug.
