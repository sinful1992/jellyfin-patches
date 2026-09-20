# Changelog

Releases of the local Jellyfin fork. Each entry is one built,
gated and smoke-tested image.

## 12.1-p2 — 2026-09-20

Base `v12.1` · image `jellyfin-patched:12.1-p2`
Built on `lscr.io/linuxserver/jellyfin:12.1ubu2604-ls50@sha256:51252e7a416e703cdc3cd91e8a54673a2430cc80409be8a38abe511411577b95`

**First performance commits in the series, chosen from measuring this server rather than
upstream's tracker.** EF command logging on a 134-episode series list with the Android TV
app's field set: **~1,480 database commands for one request, ~1 s, of which the database itself
took under 100 ms** — the cost is round-trips. Per item: media streams, attachments, two
alternate-version link lookups, the media-segment flag (all inside `item.GetMediaSources()`),
a trickplay query per media source, and a chapters query. Three new commits:

- **Batch the reads GetMediaSources repeats per item across a page of DTOs** — `PagePrefetch`, a
  request-scoped (`AsyncLocal`) batch opened by `DtoService` for a page; `MediaSourceManager`,
  `LibraryManager` and `MediaSegmentManager` answer whole-item reads from it while open. Nothing
  cached across requests.
- **Fetch a page's trickplay manifests with one query instead of one per media source.**
- **Fetch a page's chapters with one query instead of one per item.**

**Verified** on a copy of the live config: DTOs byte-identical to `12.1-p1` across 8 request
shapes (series list, season, movie grid, NextUp, audio, single item, streams-only, trickplay-only);
1,481 → 12 database commands and 910 → 235 ms on the full-series list; movie grid 560 → 240 ms.
**Stated limit:** this library has no alternate-version links (all 95 `LinkedChildren` rows are
collection links), so the batched alternate-version path returned empty on every compared request
— it is exercised for correctness only when two versions of a film are merged.

**Also fixed — a defect in our own auth patch, found by the deploy of this very image:**
stream tickets lived in memory, so **every server restart revoked them** and any client that
fetches its direct-play stream uncredentialed (the Android TV app) fell into a loop of 401s
until the user pressed play again. Seen live 2026-09-20 01:08, bedroom TV, two minutes dark.
True of every fork image since `10.11.11-p1`; never noticed because restarts happened at night.
`StreamTicketStore` now persists to `data/stream-tickets.json` (written on issue, refreshed at
most once a minute while a stream slides a ticket, reloaded at startup minus expired entries);
4 new unit tests. Series is now **8 commits**.

**Replaced assembly set grows 2 → 3:** `Jellyfin.Server.Implementations.dll` joins
`Emby.Server.Implementations.dll` and `Jellyfin.Api.dll`. `MediaBrowser.Controller` — the
assembly plugins bind against — is deliberately untouched: batch loaders sit on the concrete
classes, reached by type test.

<details><summary>Contains 8 change(s)</summary>

- Add a stream-ticket authorization policy
- Issue a stream ticket when playback info is requested
- Require a stream ticket on the media endpoints
- Add regression tests for media endpoint authentication
- Batch the reads GetMediaSources repeats per item across a page of DTOs
- Fetch a page's trickplay manifests with one query instead of one per media source
- Fetch a page's chapters with one query instead of one per item
- Persist stream tickets so a server restart does not revoke them

</details>

Assemblies replaced: Emby.Server.Implementations.dll, Jellyfin.Api.dll, Jellyfin.Server.Implementations.dll

## 12.1-p1 — 2026-09-19

Base `v12.1` · image `jellyfin-patched:12.1-p1`
Built on `lscr.io/linuxserver/jellyfin:12.1ubu2604-ls50@sha256:51252e7a416e703cdc3cd91e8a54673a2430cc80409be8a38abe511411577b95`

**DEPLOYED 2026-09-19 23:29.** Live server migrated 12.0 → 12.1 (3 code migrations,
`StripEmbeddedLinkedChildren` cleaned 2768 items), startup 15 s, 0 `[ERR]`/`[FTL]`, `vaapi`
intact, Intro Skipper 12.0.4.0 loaded unchanged, auth patch 401 ×3 live, PlaybackInfo → 206.
Pre-migration backup: `/mnt/data/docker-data/_jellyfin-pre-12.1-backup-20260919-232810`
(full config minus `cache/` + `transcodes/`; 4.5G). `jellyfin-patched:12.0-p1` kept on disk.
That snapshot predates `logging.json` (2026-09-20) — a rollback drops the access log; re-copy
`config/logging.json` in after restoring.

**Base bump: 12.0 → 12.1.** Upstream tagged `v12.1` on 2026-09-15 (47 PRs / 148 files)
and LinuxServer published `12.1ubu2604-ls50` the same day. The 12.0→12.1 diff touches
**none** of the 12 files the series changes; `patched/12.1` is `patched/12.0` rebased onto
`v12.1` with no conflicts and byte-identical series content. `patched/12.0` is archived
(tag `v12.0-p1` still rebuilds it).

The series is unchanged: 4 commits (stream-ticket auth). Still needed — at `v12.1`
`GetAudioStream`/`GetVideoStream` carry no `[Authorize]`. `UserDataManager.cs` is
untouched upstream, so the unported userdata fix stays unported.

**12.1 is another one-way DB upgrade**: 4 migration routines
(`ConsolidateLocalizedUserViews`, `RepairAlternateVersionLinks`, `MigrateRatingLevels`,
`StripEmbeddedLinkedChildren`) + 3 EF schema migrations. The pre-12.0 config backup does
not cover a 12.1 rollback; take a fresh stopped-container copy before deploying.

Intro Skipper: `targetAbi` is a minimum, not a pin. The 12.0→12.1 public API only gained
members (`ILibraryManager.GetTagNames`, `ILiveTvManager.IsEnabledForUser`) and no type
the plugin implements changed, so the `12.0/` line (12.0.4.0 installed) is expected to
load unchanged. Verified at deploy, not assumed — the smoke test does not check plugin load.

### Tooling
- Base tag and series are now DERIVED from `VERSION` in `build.sh`, `regen-patches.sh`,
  `release.py`, `port-check.py` and the watcher (the hook already did this). The 12.0
  bump left `release.py` and `port-check.py` on `patched/10.11.11`, and `12.0-p1` was cut
  by hand as a result — no manifest, no GitHub release.
- Watcher: new `check_base_image` watches LinuxServer's release-tag images — the thing
  that actually gates a bump. Both 12.0 and 12.1 images had to be found by hand; 12.1
  sat unbumped 2026-09-15..19 with every gate clear because nothing said so.
- Watcher: the Intro Skipper line is picked at run time (newest line ≤ our base that
  exists), so a base bump to 12.1 keeps watching `12.0/` instead of reporting an empty
  `12.1/` line every day.

Series diff vs the previous manifest (`10.11.11-p5` — `12.0-p1` was cut by hand and has
none): the two "removed" commits went at 12.0, and the two "changed" ones differ only in
patch-id, which is not stable across a base bump.

<details><summary>Contains 4 change(s)</summary>

- Add a stream-ticket authorization policy
- Issue a stream ticket when playback info is requested
- Require a stream ticket on the media endpoints
- Add regression tests for media endpoint authentication

</details>

Assemblies replaced: Emby.Server.Implementations.dll, Jellyfin.Api.dll

## 12.0-p1 — 2026-09-09

Base `v12.0` · image `jellyfin-patched:12.0-p1`
Built on `lscr.io/linuxserver/jellyfin:12.0ubu2604-ls48@sha256:0f42497a69fa0441bfd5f9d6bba8694f2a656ec984e571d0ac04c6dd91250039`

**DEPLOYED 2026-09-09 10:59.** Live server migrated 10.11.11 → 12.0 (34 migrations),
Intro Skipper swapped to 12.0.2.0, 0 errors, `vaapi` intact, auth patch live.
Pre-migration backup: `/mnt/data/docker-data/_jellyfin-pre-12.0-backup-20260909-105748`.
**Rollback is no longer a compose edit alone** — the database schema moved.

**Base bump: 10.11.11 → 12.0, and the series moves with it.** `patched/12.0` is now the
source of truth; `patched/10.11.11` is archived and still rebuildable from tag
`v10.11.11-p5`. Upstream cut `v12.0` on 2026-09-08 and LinuxServer published a
release-tag image the same day, which removed the last two blockers.

The series is **4 commits, down from 6**:

- **Dropped** `Backport: fix PGS subtitles for BDMV with TrueHD` — upstream `7c463f5fb`
  is in `v12.0`, so the base now carries it.
- **Not ported** `Read user data from the cache and database, never the item snapshot`.
  Upstream restructured the code it targets; the patch has no target at 12.0.
  **This image therefore lacks a fix that was live in 10.11.11-p5.** Whether the
  favourites-revert defect still occurs at 12.0 is UNANSWERED — it needs a
  reproduction on a running 12.0. Do not re-derive the fix blind.

The rebase itself needed **no manual conflict resolution**: `rerere` replayed the banked
MediaInfoHelper resolution, and dropping the BDMV commit took the SubtitleEncoder
conflict with it.

<details><summary>Contains 4 change(s)</summary>

- Add a stream-ticket authorization policy
- Issue a stream ticket when playback info is requested
- Require a stream ticket on the media endpoints
- Add regression tests for media endpoint authentication

</details>

### Verified
- `dotnet build Jellyfin.Server -c Release` on **.NET 10** — 0 warnings, 0 errors
- `Jellyfin.Api.Tests` — **145 passed, 0 failed**, including `StreamAccessHandlerTests`
- version gate: base ships `Jellyfin.Api` at `26.4.0.0`, matched
- smoke test: video / audio / HLS unauthenticated endpoints all **401**

**Scope of that smoke test:** it starts a throwaway container, drives the startup wizard
and checks the three unauthenticated media endpoints. It does **not** cover database
migration, transcoding, subtitle extraction or playback. The functional test recorded in
`notes/12.0-port.md` covered those, but against **rc7 on the nightly base** — a different
pairing from what is built here. Re-run it against this image before deploying.

### Tooling
- Watcher rebaselined to 12.0: `PINNED`, `SERIES`, and `release-10.11.z` → `release-12.z`
- Watcher no longer port-checks **backwards** against a base already contained in the
  pinned tag, and skips a target tag that does not resolve
- Documented that the watcher does **not** watch base images — the LinuxServer 12.0
  release tag that unblocked this bump had to be found by hand

Assemblies replaced: Emby.Server.Implementations.dll, Jellyfin.Api.dll

## 10.11.11-p5 — 2026-09-07

Base `v10.11.11` · image `jellyfin-patched:10.11.11-p5`
Built on `lscr.io/linuxserver/jellyfin:10.11.11ubu2604-ls47@sha256:438e44330078e6b1a810fdec9dc0f4773e6595edb137c5eb4417a516da4c7f0e`

No change to the patch series; rebuilt for tooling or base reasons.

<details><summary>Contains 6 change(s)</summary>

- Add a stream-ticket authorization policy
- Issue a stream ticket when playback info is requested
- Require a stream ticket on the media endpoints
- Add regression tests for media endpoint authentication
- Read user data from the cache and database, never the item snapshot
- Backport: fix PGS subtitles for BDMV with TrueHD

</details>

### Tooling
- Functionally test 12.0 on a copy of the live config
- 12.0 on the nightly base: tested, and it works

Assemblies replaced: Emby.Server.Implementations.dll, Jellyfin.Api.dll, MediaBrowser.Controller.dll, MediaBrowser.MediaEncoding.dll

## 10.11.11-p4 — 2026-09-06

Base `v10.11.11` · image `jellyfin-patched:10.11.11-p4`
Built on `lscr.io/linuxserver/jellyfin:10.11.11ubu2604-ls43@sha256:b8dcc7b71d0ea872b74314da4b995c0cf282b1778438c295996e7be88c70fdda`

No change to the patch series; rebuilt for tooling or base reasons.

<details><summary>Contains 6 change(s)</summary>

- Add a stream-ticket authorization policy
- Issue a stream ticket when playback info is requested
- Require a stream ticket on the media endpoints
- Add regression tests for media endpoint authentication
- Read user data from the cache and database, never the item snapshot
- Backport: fix PGS subtitles for BDMV with TrueHD

</details>

### Tooling
- Record the 12.0 port: 5 of 6 commits, compiling and tested
- Accept the GHCR image name as a deployed release
- Publish the image from Actions instead of by hand

Assemblies replaced: Emby.Server.Implementations.dll, Jellyfin.Api.dll, MediaBrowser.Controller.dll, MediaBrowser.MediaEncoding.dll

## 10.11.11-p3 — 2026-09-06

Base `v10.11.11` · image `jellyfin-patched:10.11.11-p3`
Built on `lscr.io/linuxserver/jellyfin:10.11.11ubu2604-ls43@sha256:b8dcc7b71d0ea872b74314da4b995c0cf282b1778438c295996e7be88c70fdda`

No change to the patch series; rebuilt for tooling or base reasons.

<details><summary>Contains 6 change(s)</summary>

- Add a stream-ticket authorization policy
- Issue a stream ticket when playback info is requested
- Require a stream ticket on the media endpoints
- Add regression tests for media endpoint authentication
- Read user data from the cache and database, never the item snapshot
- Backport: fix PGS subtitles for BDMV with TrueHD

</details>

Assemblies replaced: Emby.Server.Implementations.dll, Jellyfin.Api.dll, MediaBrowser.Controller.dll, MediaBrowser.MediaEncoding.dll

## 10.11.11-p2 — 2026-09-06

Base `v10.11.11` · image `jellyfin-patched:10.11.11-p2`
Built on `lscr.io/linuxserver/jellyfin:10.11.11ubu2604-ls43@sha256:b8dcc7b71d0ea872b74314da4b995c0cf282b1778438c295996e7be88c70fdda`

No change to the patch series; rebuilt for tooling or base reasons.

<details><summary>Contains 6 change(s)</summary>

- Add a stream-ticket authorization policy
- Issue a stream ticket when playback info is requested
- Require a stream ticket on the media endpoints
- Add regression tests for media endpoint authentication
- Read user data from the cache and database, never the item snapshot
- Backport: fix PGS subtitles for BDMV with TrueHD

</details>

### Tooling
- Report GHCR package visibility instead of pretending to set it
- Accept a PAT for the GHCR push, not just the gh token
- Publish the image to GHCR as part of a release
- Ignore __pycache__ from the tools directory
- Enforce version bump + changelog before any commit that changes what ships

Assemblies replaced: Emby.Server.Implementations.dll, Jellyfin.Api.dll, MediaBrowser.Controller.dll, MediaBrowser.MediaEncoding.dll

## 10.11.11-p1 — 2026-09-06

Base `v10.11.11` · image `jellyfin-patched:10.11.11-p1`
Built on `lscr.io/linuxserver/jellyfin:10.11.11ubu2604-ls43@sha256:b8dcc7b71d0ea872b74314da4b995c0cf282b1778438c295996e7be88c70fdda`

First recorded release. Contains 6 change(s):
- Add a stream-ticket authorization policy
- Issue a stream ticket when playback info is requested
- Require a stream ticket on the media endpoints
- Add regression tests for media endpoint authentication
- Read user data from the cache and database, never the item snapshot
- Backport: fix PGS subtitles for BDMV with TrueHD

Assemblies replaced: Emby.Server.Implementations.dll, Jellyfin.Api.dll, MediaBrowser.Controller.dll, MediaBrowser.MediaEncoding.dll

