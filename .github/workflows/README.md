# Workflows — `staging` → `main` pipeline

`main` requires the `guard` status check (the post-#76 private-data backstop),
so nothing is pushed to `main` directly. All commits land on `staging`.

`auto-promote.yml` runs on every push to `staging`: it re-runs the private-data
guard and, only if clean, fast-forwards `main` using the `PROMOTE_DEPLOY_KEY`
deploy key — the sole ruleset bypass actor. A failing commit is reset off
`staging` and never reaches `main`.

The maintenance bots (`cache-bust`, `recommend-index`, `potentials-maintenance`)
therefore commit their generated output to `staging` via that same deploy key
(`GITHUB_TOKEN` pushes would not trigger `auto-promote`), never to `main`.

Writing via MCP: push to `staging` and let `auto-promote` carry it to `main`.
A multi-file Git Data API commit (`push_files`) does not fire the `push`
trigger; use a single-file `create_or_update_file` commit to nudge promotion.
