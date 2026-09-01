# jellyfin-patches

A personally maintained Jellyfin server build: an upstream release, plus a small set
of local patches, plus a watcher that says when upstream has something worth taking.

This is **not** a contribution pipeline. Upstream is a source we pull *from*.

## Why

Three real defects were found in the server and verified against a live 10.11.11
instance. Two are fixed here. Upstream has not fixed any of them.

| Patch | What it fixes | Status |
|---|---|---|
| `0001-require-auth-on-media-endpoints` | 11 media endpoints served with no authentication at all | applied |
| `0002-userdata-no-stale-item-snapshot` | Favourites/played state reverted by playback progress reports | applied |
| trickplay N+1 | A query per media source per item, plus a blocking wait, in every DTO | **not ported** |

The trickplay fix is deliberately not ported. On master it rides on DTO batching
infrastructure that does not exist in 10.11.11, so porting it means building that
plumbing from scratch. It is a performance win only, and not worth the blast radius
on a release branch. It stays on the `perf/trickplay-batch` branch of
`jellyfin-server-fixes` for whenever the base moves to a release that has the
batching.

A fourth patch — bounding the HLS remux seek offset — was written, then **disproved
by measurement** and dropped. The underlying defect is real (the hard-coded 0.5s
offset makes 11 of 15 segments start late, losing up to 0.334s of content) but the
fix was worse than the bug. See `notes/hls-seek.md`.

## The auth issue, concretely

`ApiServiceCollectionExtensions` configures only `DefaultPolicy`. There is no
`FallbackPolicy` and no global `AuthorizeFilter`, so any action without an explicit
`[Authorize]` is anonymous. Item ids are `MD5(type.FullName + path)`, so they are
derived from the file path rather than being secret.

Against an unpatched server:

    GET /Items/{id}                  -> 401
    GET /Audio/{id}/stream?static=true -> 206, media body, no token

That works for video items too, because `AudioController` does not type-check.

## Building

Needs the **.NET 9** SDK (10.11.x pins `rollForward: latestMinor`, so a 10.x SDK
will not do). The build only replaces four assemblies; jellyfin-web, ffmpeg, s6 and
the volume layout all come from the stock LinuxServer image untouched.

    ./build/build.sh

Building from the `v10.11.11` **tag** keeps `AssemblyVersion("10.11.11")`, which is
what ABI-pinned plugins need — Intro Skipper is versioned `1.10.11.x` against
exactly this server. Building from `master` would not work: it is 2000+ commits
ahead, a 10.12-dev jump that breaks the plugin and touches the database schema.

The script builds and tags an image. It does **not** touch the running container.
Switching is a separate, explicit step, and rolling back is repointing the tag at
`lscr.io/linuxserver/jellyfin:10.11.11ubu2604-ls43`.

## Watching upstream

`watch/jellyfin-upstream-watch.py` runs from cron and reports to Discord as
**Bloodhound**. It never changes anything — adopting an upstream change is always a
decision, not an automatic action.

It reports:

- a new Jellyfin release (time to consider moving the base tag)
- upstream commits touching any file our patches touch (a rebase will conflict, or
  upstream fixed it and a patch can be dropped)
- any of the six tracked issues closing upstream (our patch may be redundant)
- Intro Skipper releases (it is what pins the base version, so its support for a
  newer server is what opens the upgrade path)

It uses the **anonymous** GitHub API deliberately: no token to leak from a public
repo, and it is unaffected by an account-level block on the jellyfin org.

Failures are reported loudly rather than swallowed — a monitor that goes quiet when
it breaks is worse than no monitor.

    DISCORD_WEBHOOK_URL=... ./watch/jellyfin-upstream-watch.py

## Layout

    patches/   patch files, applied in order onto the base tag
    build/     Dockerfile + build script
    watch/     upstream watcher
    notes/     investigation write-ups, including things that turned out to be wrong
