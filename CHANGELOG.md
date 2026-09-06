# Changelog

Releases of the local Jellyfin fork. Each entry is one built,
gated and smoke-tested image.

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

