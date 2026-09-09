# Changelog

Releases of the local Jellyfin fork. Each entry is one built,
gated and smoke-tested image.

## 12.0-p1 — 2026-09-09

Base `v12.0` · image `jellyfin-patched:12.0-p1`
Built on `lscr.io/linuxserver/jellyfin:12.0ubu2604-ls48@sha256:0f42497a69fa0441bfd5f9d6bba8694f2a656ec984e571d0ac04c6dd91250039`

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

