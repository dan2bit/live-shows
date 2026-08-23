# IMAGE_SERVER runbook

Operational runbook for the still-photo **image server** — the Immich instance that hosts curated concert stills (player portraits, memorabilia, pre-show selfies, artist photos) for the live-shows site, replacing the manual Google Photos share-link flow. Pipeline design and open decisions live in issue **#294**.

> **Secrets policy:** this document records only non-secret operational detail and the *location* of secrets. The Immich API key value, admin/account passwords, and Cloudflare credentials are **never** committed to any repo — they live in the password manager and, for the API key, the operator's local environment. See "API key" below.

## Domain & DNS

- **Registered domain:** `redhat-bootlegs.net`
- **DNS:** Cloudflare (free plan).
- **Registrar:** Cloudflare Registrar. Registered 2026-08-19 through **2027-08-20**, auto-renew **ON**. Billing alerts → `redhat.bootlegs@gmail.com`.
- **Records:**
  - `www` / apex → GitHub Pages (the live-shows site). **Not yet wired** — the site still serves at the default `dan2bit.github.io` Pages URL. When wired, keep these **DNS-only (grey cloud)** so Pages can provision its own HTTPS cert without Cloudflare intercepting the ACME challenge.
  - `photos.redhat-bootlegs.net` → the Immich pod. **Live** (2026-08-22): CNAME to `natural-dodo.pikapod.net`, **DNS-only (grey cloud)**, registered as a custom domain in the PikaPods pod settings (PikaPods issues the Let's Encrypt cert). Grey cloud is required — PikaPods' domain verification and cert issuance need the CNAME visible in DNS and traffic hitting the pod directly; a proxied (orange) record masks the CNAME and breaks both. Add the Cloudflare record **first**, then add the domain in PikaPods (it verifies the CNAME at add-time).

## Hosting — PikaPods

- **Provider:** PikaPods (managed open-source app hosting — no Docker/tunnel to run ourselves; a public HTTPS URL comes with the pod).
- **App:** Immich
- **Pod URL:** `https://natural-dodo.pikapod.net`
- **Account / billing email:** see password manager. Billing alerts → `dan2bit@gmail.com`.
- **Billing:** resource-based, ~$5.50/mo base at photos-only scale (storage is trivial for this library), drawn down from a **prepaid balance with no auto top-off** — the balance can run dry silently, so watch the low-balance alerts. Charges are tracked in the private repo → `hosting_costs.tsv`.

## Immich

- **Version:** v3.1.0 (as of 2026-08-22)
- **Public URL (canonical, for image links):** `https://photos.redhat-bootlegs.net`
- **Server base URL (API/CLI):** the custom domain or `https://natural-dodo.pikapod.net` both work — base only, **no** `/photos` and **no** `/api` suffix (tools append `/api` themselves; a browser redirects `/` → `/auth/login` when signed out, or `/photos` when signed in — both normal). Prefer the custom domain as the canonical host so links written into the show library sit on the stable hostname.
- **Admin user:** `dan2bit@gmail.com`
- **Admin password:** password manager (not stored here).
- **Storage template:** enabled — `{{y}}/{{y}}-{{MM}}-{{dd}}/{{filename}}` (date-keyed on capture time; albums and tags live in the database, never in the file path, so multi-homing a photo across albums/tags is unaffected).
- **Server Storage widget:** the TiB figure reflects the shared PikaPods **host disk**, not your data or quota — ignore it. Real per-user usage is under Administration → Server Stats; your capacity limit is the pod's storage allocation in the PikaPods dashboard.

## Mobile capture — manual upload

The Immich app on the Pixel runs **alongside** Google Photos (non-destructive; both read the same on-device storage). We deliberately do **not** use auto-backup, because:

- Immich has **no photos-only option** — auto-backup is per device *album* and uploads videos too, and concert video belongs on YouTube, not here.
- The app sees **on-device folders** (Camera, Screenshots), **not** Google Photos cloud albums (e.g. "Player Portraits"), so there's no clean way to auto-select just the curated stills.

Instead, upload curated stills **manually, per show**:

1. App → **Library → "On this device"** → open the local album (Camera).
2. Select just the keeper stills for that show.
3. Tap **Upload** in the bottom menu.

Notes: grant Android **"Allow all"** photos/videos permission (not "Selected"), or the app can't see the roll. Immich uploads the **on-device original**, so keep originals on the phone — don't let Google "free up space" purge them first. This manual step will fold into the **photo-reminder workflow rewrite** (#294): the per-show reminder will prompt the upload and then capture the resulting Immich link into the show library.

_Ref: Immich mobile app docs — <https://docs.immich.app/features/mobile-app/>_

## API key (for immich-go / automation)

- **The value is not stored here or in any committed file — by design.** It lives only in the operator's environment as `IMMICH_API_KEY` (exported in the shell for a run). Recover from the password manager if lost, or rotate (below).
- **Key label:** `immich-go import`
- **Scopes granted** — the verified full set a *default* `immich-go upload from-google-photos` run needs:
  - `asset.upload`, `asset.read`, `asset.update`, `asset.copy`
  - `album.create`, `album.read`, `album.update`
  - `albumAsset.create`
  - `tag.create`, `tag.asset`
  - `stack.create`
  - `job.create`
  - `server.about`, `user.read`
- **Why the non-obvious ones** (each caused a 403 that halted the run until granted):
  - `asset.update` — immich-go PUTs the sidecar caption/date onto each asset after upload.
  - `asset.copy` — edited-version / duplicate handling (replaces the deprecated `replaceAsset`).
  - `tag.create` + `tag.asset` — the default `--takeout-tag` / `--people-tag` behavior tags assets on import.
  - `stack.create` — stacks burst and `-edited` pairs (default `--manage-*` behavior).
  - `job.create` — pauses/resumes server jobs around the import.
- **Where to manage it:** Immich → avatar (top-right) → **Account Settings** → **API Keys** (or `/user-settings`). This is a *personal* setting, not the Administration panel.
- **Rotation:** editing a key's scopes in place does **not** change the token; deleting and recreating **does**. To rotate, delete the key, create a new one with the same scopes, and update `IMMICH_API_KEY` in the local environment.
- **Automation key:** the `photos` module uses a **separate least-privilege key** — see the next section. This import key stays import-only.

## Automation key + `photos` module

The repo's Immich tooling is `tools/photos/immich.py` — a stdlib-only REST wrapper + CLI (mirrors the `tools/youtube` pattern). It reads `IMMICH_API_KEY` (and optionally `IMMICH_URL`) from the environment or `tools/photos/.env` (gitignored via the global `.env` rule). The canonical public host is the built-in default URL.

### Key scopes (label: `photos automation`)

Read/search core: `asset.read` (metadata search, asset detail, OCR read), `asset.view` (thumbnail bytes for visual ID), `server.about` (verify smoke-test).
Tags: `tag.create`, `tag.read`, `tag.asset`, plus `tag.update`/`tag.delete` for taxonomy cleanup (droppable for a tighter key).
Albums: `album.create`, `album.read`, `albumAsset.create`, plus optional `album.update`.
Shared links: `sharedLink.create`, `sharedLink.read` (list-before-mint keeps re-runs from duplicating links).
People/faces: `person.read`; add `face.read` only if person-asset reads 403 without it.

**Deliberately excluded:** `asset.upload`, `asset.update`, `asset.copy`, `asset.delete`, `stack.create`, `job.create`, `sharedLink.update`/`delete`, and all admin scopes — this key can classify, collect, and link but can never modify or destroy a photo. Server job runs (OCR/faces backfill) go through the Admin → Jobs UI, not this key.

### Module quick reference

```
export IMMICH_API_KEY='...'                       # never commit
python3 tools/photos/immich.py verify              # version + key smoke-test
python3 tools/photos/immich.py tags --bootstrap    # seed kind/, memorabilia/, signed
python3 tools/photos/immich.py search --taken-after 2026-03-11T00:00:00.000Z --taken-before 2026-03-11T23:59:59.999Z
python3 tools/photos/immich.py thumb <asset-id> --out /tmp/peek.jpg
python3 tools/photos/immich.py ocr <asset-id>
python3 tools/photos/immich.py tag artist/sue-foley <asset-id> ...
python3 tools/photos/immich.py link --assets <id> [<id> ...]
python3 tools/photos/immich.py seed-crosswalk      # backfill working file
```

- **Shared-link defaults:** `allowDownload=true`, `showMetadata=false`, no expiry — viewers can save photos, but capture time/device/location EXIF stays private (parity with the old Google Photos shares).
- **Taxonomy:** `tags --bootstrap` creates the standard facets — `kind/{with-artist,performance,memorabilia,selfie,crowd}`, `memorabilia/{setlist,cd,vinyl,poster,pick,ticket,autograph-book,photo-print,hat,other}`, and flat `signed`. Hat detail is a memorabilia subtype, not a kind. `show/<year>/<date>`, `artist/<slug>`, and `venue/<slug>` tags are created on demand via `tag`/`--ensure` (slugs must match the show-library slug rules).
- **Crosswalk seeding:** `seed-crosswalk` enumerates every Google Photos link across `data/show_goals/artist-photos.tsv`, `data/live_shows_current.tsv`, `data/history/*.tsv`, and `data/show_goals/item_log.tsv` into `tools/photos/backfill_crosswalk.tsv` — one row per distinct link (shared links merge their sources), existing rows always preserved so confirmed matches are never re-litigated. `--no-immich` seeds offline; with the key set it also prefills same-day capture-date candidates.

## Seed migration (Google Photos → Immich)

- **Tool:** immich-go v0.32.0 (macOS `Darwin_arm64` binary; clear Gatekeeper quarantine with `xattr -d com.apple.quarantine ./immich-go`). Reads Google Takeout **zips directly** — do not unzip, do not use the Immich web uploader (it ignores the metadata sidecars).
- **Command:**

  ```
  export IMMICH_API_KEY='...'      # never commit
  immich-go upload from-google-photos \
    --server=https://photos.redhat-bootlegs.net \
    --api-key="$IMMICH_API_KEY" \
    --include-type=IMAGE \
    --include-partner=false --include-trashed=false \
    /path/to/takeout-*.zip
  ```

- `--include-type=IMAGE` keeps bootleg videos out (those live on YouTube). Captions and Google album membership are carried across from the `*.supplemental-metadata.json` sidecars.
- **Log file:** `~/Library/Caches/immich-go/immich-go_<timestamp>.log`

## Post-import: drain the Jobs queue

immich-go pauses Thumbnail Generation, Metadata Extraction, Face Detection, and Smart Search during the import and resumes them at the end. On a small pod they backlog and drain slowly — expect "Error Loading Image" grid tiles and wrong aspect ratios until they finish (the originals still open; only the derived thumbnails/metadata lag).

- Watch progress at Administration → **Jobs**. Let Thumbnail Generation and Metadata Extraction drain to 0 waiting.
- Don't hit **Clear** (wipes the queue) or **Pause**, and don't queue **All** on top of a running backlog.
- Once those two are clean, run **Face Detection** then **Smart Search** (they enable search and the artist/portrait face-clustering). Then run **OCR** with **Missing** — auto-OCR only covers new uploads, so the imported batch needs this one-time pass before OCR search/read returns anything for it.
- A *failed* count (vs. a backlog) signals the pod is underpowered — consider a memory bump.

## Secrets — do not commit

The Immich API key value, Immich admin password, PikaPods account password, and Cloudflare credentials all live in the password manager / local env only. This runbook and every repo file record only non-secret config and secret *locations*.

## Related

- **#294** — still-photo pipeline design & open decisions (public repo)
- **#293** — Changedetection/RSSHub on the same PikaPods account
- **Cost ledger** — `dan2bit/live-shows-private → hosting_costs.tsv`
