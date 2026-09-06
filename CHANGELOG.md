# Changelog

Releases of the local Jellyfin fork. Each entry is one built,
gated and smoke-tested image.

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

