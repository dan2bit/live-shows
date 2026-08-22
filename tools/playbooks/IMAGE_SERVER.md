# IMAGE_SERVER runbook

Operational runbook for the still-photo **image server** — the Immich instance that hosts curated concert stills (player portraits, memorabilia, pre-show selfies, artist photos) for the live-shows site, replacing the manual Google Photos share-link flow. Pipeline design and open decisions live in issue **#294**.

> **Secrets policy:** this document records only non-secret operational detail and the *location* of secrets. The Immich API key value, admin/account passwords, and Cloudflare credentials are **never** committed to any repo — they live in the password manager and, for the API key, the operator's local environment. See "API key" below.

## Domain & DNS

- **Registered domain:** `redhat-bootlegs.net`
- **DNS:** Cloudflare (free plan). Registrar: Cloudflare Registrar per the setup plan — confirm the registrar of record.
- **Records:**
  - `www` / apex → GitHub Pages (the live-shows site). Keep these **DNS-only (grey cloud)** so Pages can provision its own HTTPS cert without Cloudflare intercepting the ACME challenge.
  - `photos.redhat-bootlegs.net` → the Immich pod. **Planned, not yet wired** — Immich is currently reached at its default PikaPods URL (below). When wired, CNAME to the pod (proxied is fine for a managed pod).

## Hosting — PikaPods

- **Provider:** PikaPods (managed open-source app hosting — no Docker/tunnel to run ourselves; a public HTTPS URL comes with the pod).
- **App:** Immich
- **Pod URL:** `https://natural-dodo.pikapod.net`
- **Account / billing email:** see password manager.
- **Billing:** resource-based, ~$5.50/mo base at photos-only scale (storage is trivial for this library). Charges are tracked in the private repo → `hosting_costs.tsv`.

## Immich

- **Version:** v3.1.0 (as of 2026-08-22)
- **Server base URL (API/CLI):** `https://natural-dodo.pikapod.net` — base only, **no** `/photos` and **no** `/api` suffix (the tools append `/api` themselves; a browser redirects `/` → `/photos`, which is normal).
- **Admin user:** `dan2bit@gmail.com`
- **Admin password:** password manager (not stored here).
- **Storage template:** enabled — `{{y}}/{{y}}-{{MM}}-{{dd}}/{{filename}}` (date-keyed on capture time; albums and tags live in the database, never in the file path, so multi-homing a photo across albums/tags is unaffected).
- **Mobile capture:** the Immich app on the Pixel runs **alongside** Google Photos (non-destructive, reads the same `DCIM/Camera` storage), scoped to the show-stills device album. It uploads the on-device original, so keep originals on the phone (don't let Google "free up space" purge them before backup).

## API key (for immich-go / automation)

- **The value is not stored here or in any committed file — by design.** It lives only in the operator's environment as `IMMICH_API_KEY` (exported in the shell for a run). Recover from the password manager if lost, or rotate (below).
- **Key label:** `immich-go import`
- **Scopes granted** (least-privilege for the import job):
  - `asset.upload`, `asset.read`, `asset.update`
  - `album.create`, `album.read`, `album.update`
  - `albumAsset.create`
  - `job.create`
  - `server.about`, `user.read`
  - (`asset.update` is required — immich-go PUTs the sidecar caption/date onto each asset after upload; without it the run 403s and stops.)
- **Where to manage it:** Immich → avatar (top-right) → **Account Settings** → **API Keys** (or `/user-settings`). This is a *personal* setting, not the Administration panel.
- **Rotation:** editing a key's scopes in place does **not** change the token; deleting and recreating **does**. To rotate, delete the key, create a new one with the same scopes, and update `IMMICH_API_KEY` in the local environment.
- **Future automation key:** when the `photos` module / Immich MCP is built (#294), mint a **separate** key scoped to `tag.*` + `sharedLink.create`, keeping this import key import-only.

## Seed migration (Google Photos → Immich)

- **Tool:** immich-go v0.32.0 (macOS `Darwin_arm64` binary; clear Gatekeeper quarantine with `xattr -d com.apple.quarantine ./immich-go`). Reads Google Takeout **zips directly** — do not unzip, do not use the Immich web uploader (it ignores the metadata sidecars).
- **Command:**

  ```
  export IMMICH_API_KEY='...'      # never commit
  immich-go upload from-google-photos \
    --server=https://natural-dodo.pikapod.net \
    --api-key="$IMMICH_API_KEY" \
    --include-type=IMAGE \
    --include-partner=false --include-trashed=false \
    /path/to/takeout-*.zip
  ```

- `--include-type=IMAGE` keeps bootleg videos out (those live on YouTube). Captions and Google album membership are carried across from the `*.supplemental-metadata.json` sidecars.
- **Log file:** `~/Library/Caches/immich-go/immich-go_<timestamp>.log`

## Secrets — do not commit

The Immich API key value, Immich admin password, PikaPods account password, and Cloudflare credentials all live in the password manager / local env only. This runbook and every repo file record only non-secret config and secret *locations*.

## Related

- **#294** — still-photo pipeline design & open decisions (public repo)
- **#293** — Changedetection/RSSHub on the same PikaPods account
- **Cost ledger** — `dan2bit/live-shows-private → hosting_costs.tsv`
