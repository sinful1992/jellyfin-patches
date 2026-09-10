# jellyfin-patches

A personally maintained Jellyfin server build: an upstream release, plus a small set
of local patches, plus a watcher that says when upstream has something worth taking.

This is **not** a contribution pipeline. Upstream is a source we pull *from*.

## Why

Three real defects were found in the server and verified against a live 10.11.11
instance. Two are fixed here. Upstream has not fixed any of them.

| Change | What it fixes | Status |
|---|---|---|
| stream-ticket policy (4 commits) | 11 media endpoints served with no authentication at all | applied, ticket-scoped |
| userdata stale snapshot | Favourites/played state reverted by playback progress reports | applied |
| BDMV/TrueHD PGS subtitles | Wrong subtitle stream index on BluRay folder rips (upstream #17674) | backported from master |
| trickplay N+1 | A query per media source per item, plus a blocking wait, in every DTO | **not ported** |

The trickplay fix is deliberately not ported. On master it rides on DTO batching
infrastructure that does not exist in 10.11.11, so porting it means building that
plumbing from scratch. It is a performance win only, and not worth the blast radius
on a release branch. It stays on the `perf/trickplay-batch` branch of
`jellyfin-server-fixes` for whenever the base moves to a release that has the
batching.

The four upstream issues behind patch 0001 (#13983-#13986) were filed by
`felix920506` on 2025-04-23 — not by us — and all four are still open sixteen
months later. A standalone brief on that defect, written up for a second opinion,
is in `notes/unauthenticated-media-endpoints.md`.

A fourth patch — bounding the HLS remux seek offset — was written, then **disproved
by measurement** and dropped. The underlying defect is real (the hard-coded 0.5s
offset makes 11 of 15 segments start late, losing up to 0.334s of content) but the
fix was worse than the bug. See `notes/hls-seek.md`.

## The auth issue, concretely

`ApiServiceCollectionExtensions` configures only `DefaultPolicy`. There is no
`FallbackPolicy` and no global `AuthorizeFilter`, so any action without an explicit
`[Authorize]` is anonymous. Item ids are `MD5(type.FullName + path)`, so they are
derived from the file path rather than being secret -- verified by reproducing an id
from a path alone and streaming it with no token.

Against an unpatched server:

    GET /Items/{id}                  -> 401
    GET /Audio/{id}/stream?static=true -> 206, media body, no token

That works for video items too, because `AudioController` does not type-check.

### Why not a bare `[Authorize]`

It breaks direct play. Jellyfin for Android TV 0.19.10 composes the stream URL itself
and attaches no credential -- no `ApiKey`, no `api_key`, no `PlaySessionId`, no header.
Under `[Authorize]` it 401s, reports "Player error encountered, will retry", and falls
back to a server-side HLS remux on **every** playback. Upstream leaves these routes
anonymous deliberately; `HlsSegmentController` carries a comment saying so.

This also rules out server-minted signed URLs, which was the most promising idea on
paper: **this client does not use the URL the server hands it.** By contrast
`DynamicHlsController` is `[Authorize]` at class level and works fine, because there
the server writes the segment URLs -- token included -- into the playlist it returns.

### Why not `AnonymousLanAccessPolicy` either

That was the previous revision, and it was inert. Every path that can reach this
server (LAN, Docker bridge, Tailnet) is already inside `LocalNetworkSubnets`, so it
refused nothing stock Jellyfin would have served, and its deny branch could not be
exercised on this host at all: a container on a deliberately excluded bridge still
arrives NATed as an address that *is* on the list.

### What it does instead: playback tickets

An authenticated playback negotiation grants access to the media it just handed out.

`MediaInfoController` is `[Authorize]`, so every `PlaybackInfo` call has a user behind
it. `MediaInfoHelper.GetPlaybackInfo` issues a ticket keyed on the caller's normalized
remote address, covering the item id and every media source id in the response.
`StreamAccessHandler` redeems it for anonymous requests and slides the expiry on each
use, so a long or paused playback does not expire mid-stream. Tickets live 4 hours, in
memory only. Authenticated callers pass as before.

So a caller that never authenticated gets nothing, **on any subnet**. Guessing a file
path is no longer enough, which is the actual defect.

Residual, stated plainly: a ticket is bound to an address, so anything sharing that
address -- another process on the same host, or a second device behind the same NAT --
could ride a ticket while a real playback is live. That is strictly narrower than
"anyone who can reach the port, at any time, for any item".

The two Live TV routes keep `AnonymousLanAccessPolicy`: they are keyed by a
server-generated recording/stream id rather than an item id, so no ticket covers them,
and unlike item ids those are not derived from a file path.

Unit tests in `tests/Jellyfin.Api.Tests/Auth/StreamAccessPolicy/` cover the deny branch
the LAN policy could not: anonymous with no ticket is refused, a ticket does not travel
to another address or cover another item, a query-string media source id is honoured,
and an authenticated caller needs no ticket.

### Verified end to end, 2026-09-02

On a throwaway instance of this exact image, from a peer container with its own address
(`172.17.0.3`, no NAT collapsing it onto the host), sending the URL shape Android TV
actually sends and no credential of any kind:

| Step | Result |
|---|---|
| bare `GET /Videos/{id}/stream?...` before negotiating | `401` |
| authenticated `POST /Items/{id}/PlaybackInfo` | `200` |
| the *identical* bare request, still no credentials | `200`, full media body |
| bare request for an unrelated item id | `401` |

So the deny branch that could not be constructed under the LAN policy is now
exercisable on real infrastructure, and direct play survives.

On production, all nine patched routes answer `401` unauthenticated, `/health` and
`/System/Info/Public` still answer `200`, and Intro Skipper 1.10.11.23 loads against
the pinned ABI.

## How this is maintained

This is a permanent fork, not a waiting room. Upstream has not fixed the auth defect
in **any** shipping version -- `AudioController.GetAudioStream` carries no
authorization attribute in `v12.0` either (verified in the release source, not the
issue tracker) -- and the 10.11 line is dead: `release-10.11.z` had no commit between
`v10.11.11` (2026-06-06) and 12.0 superseding it. Nothing arrives for free, so the
maintenance model has to be cheap to run indefinitely.

**The source of truth is a commit series, not the patch files.**

    ~/src/jellyfin   branch patched/12.0 = v12.0 + one commit per change
    patches/         GENERATED from it by tools/regen-patches.sh -- never hand-edited

    (patched/10.11.11 is the ARCHIVED previous series; tag v10.11.11-p5 still
     rebuilds that image exactly, but new work does not land there.)

Everything follows from that:

- **Conflicts localize.** A base bump used to conflict as one 39 KB patch spanning 13
  files. Now `tools/port-check.py` names the individual commits and the files each
  one conflicts in.
- **A base bump is one rebase**, with `rerere` on so each conflict is resolved once
  and replayed forever. The 10.11.11 -> 12.0 bump is what this bought: rerere replayed
  the banked MediaInfoHelper resolution and the four commits landed with **no manual
  conflict resolution at all**. Use the series' actual base as the upstream ref
  (`git rebase --onto <new> <current base> <series>`), never an older one.
- **Backports are ordinary commits.** An upstream fix worth taking is cherry-picked
  with `-x`, which records the upstream sha, so `port-check` can later say *drop this,
  the new base already has it* instead of letting it conflict as a duplicate.
- **To change a patch, edit the commit** (`git rebase -i`) and re-run
  `tools/regen-patches.sh`. Editing a file in `patches/` will be overwritten.

### The gates, and why each exists

| Gate | Catches |
|---|---|
| derived `ASSEMBLIES` in `build.sh` | a patch touching a project the image does not ship -- green build, half-applied fix |
| assembly-version comparison | ABI drift against the base image's closed binding graph |
| `tools/smoke-test.sh` | the patch not being live in the **binary**, whatever the source says |
| `tools/port-check.py` | a base bump becoming a cliff instead of a known cost |
| deployment check in the watcher | the stock image quietly replacing the local build |

The first and third exist because of a near miss: the BDMV backport is the first
change to reach `MediaBrowser.MediaEncoding`, which the old hand-written four-assembly
list did not include. It would have compiled, versioned, imaged and shipped with that
half of the fix silently absent.

## Building

Needs the **.NET 10** SDK (12.0 pins `sdk 10.0.0` with `rollForward: latestMinor`;
the archived 10.11.11 series needs .NET 9 instead). Only the assemblies the patch set actually touches are replaced -- the
set is **derived from the patches**, not hand-listed -- and jellyfin-web, ffmpeg, s6
and the volume layout all come from the stock LinuxServer image untouched. A patched
file that maps to no shippable assembly fails the build rather than being dropped.

    ./build/build.sh

Building from the `v12.0` **tag** keeps the base's `AssemblyVersion`, which the
overlay requires anyway: the image is a closed binding graph, so every assembly we
emit must match what the base image ships. ABI-pinned plugins get that for free as a
side effect — but no plugin gates the base version. Building from `master` would not work: it is 2000+ commits
ahead, a 10.12-dev jump that breaks the plugin and touches the database schema.

Before it finishes, the script runs `tools/smoke-test.sh` against the image it just
built: a throwaway container on a loopback port, startup wizard driven through the
API, then three unauthenticated stream requests that must answer `401`. The stock
image answers `400`/`404` there, so the test genuinely distinguishes them. Compiling
proves the source was patched; only this proves the image was.

The script builds and tags an image. It does **not** touch the running container.
Switching is a separate, explicit step, and rolling back is repointing the tag at
`lscr.io/linuxserver/jellyfin:12.0ubu2604-ls48`.

## Releases, versions and the changelog

**Version = `<upstream base>-p<N>`**, in the `VERSION` file — `12.0-p1`. The base is
what we build from; `N` counts releases of the fork on that base and resets when the base
moves. `build.sh`, `tools/release.py` and the watcher all read that one file.

This is *not* the server's `AssemblyVersion`, which stays at the upstream version: the
image is a closed binding graph and plugins bind against it. The fork version names the
**image**, not the assemblies.

**Image tags are immutable.** There is deliberately no moving `jellyfin-patched:10.11.11`
tag any more. That is not hypothetical tidiness: the container was running that tag while
it was rebuilt underneath it, so a restart for any unrelated reason would have silently
adopted four commits of change. Deployment is now an explicit edit:

    # ~/media/docker-compose.yml
    image: jellyfin-patched:12.0-p1

    docker compose -f ~/media/docker-compose.yml up -d --no-deps jellyfin

Rolling back is repointing at the previous tag — `docker images | grep jellyfin-patched`.
The watcher reports the difference between what `VERSION` says and what the container
actually runs, and distinguishes "an older release of ours" from "the stock image is
back".

**The base image is pinned by digest**, in `BASE_IMAGE`, not just by tag. The lsio tag is
mutable, and the assembly-version gate compares against whatever that image ships, so an
unpinned rebuild could pass against a different dependency graph than the one tested.

### Cutting a release

    tools/release.py                      # next -pN: build, gate, smoke, manifest, changelog, tag
    tools/release.py --version 10.11.12-p1
    tools/release.py --publish            # ...and push the tag + create the GitHub release

It refuses to run if `patches/` is out of date with the series, so a release cannot
record a state that was never built. The build runs first: if the gates or the smoke
test fail, `VERSION` is rolled back and nothing is released. **Nothing is pushed without
`--publish`.**

Each release writes `releases/<version>.json`: the series commits with their subjects,
`patch-id`s and backport shas, the base tag, the pinned base image digest, and the
assemblies replaced. That is what makes a release rebuildable and a rollback informed.

### The image copy (GHCR)

`jellyfin-patched` is built locally and used to exist in **no registry at all**, so a
`docker image prune -a` or a stray `compose pull` left rebuild-from-source as the only
recovery — on a box that needs the .NET 10 SDK to do it. `tools/push-image.sh` publishes
the built tag to `ghcr.io/sinful1992/jellyfin-patched`, and `release.py --publish` calls
it after the GitHub release. A failed push warns but never unpublishes the release.

    tools/push-image.sh                 # pushes the version in VERSION
    docker pull ghcr.io/sinful1992/jellyfin-patched:12.0-p1   # recovery

It needs `write:packages`, which a default `gh` login does not carry:

    gh auth refresh -s write:packages,read:packages

### How the changelog is derived

`CHANGELOG.md` is generated by diffing the new manifest against the previous one, into
**Added / Changed / Removed**, plus the repo's own commits since the last tag as
*Tooling*.

Matching is by **commit subject**, not by `patch-id`. `git patch-id --stable` is recorded
and is reliable for spotting a commit whose content changed *within* one base — but it is
**not** stable across a base bump. Measured, not assumed: the same commit cherry-picked
from `v10.11.11` onto `v12.0-rc7` cleanly gave `dcc38a19…` before and `0a6bf71e…` after,
because patch-id covers context lines and the surrounding code differs. Subject matching
survives that; patch-id would have reported every commit as new.

The two histories are kept apart on purpose: the **series** is rebased whenever the base
moves, the **repo** is not. Trying to merge them into one changelog would fight the
rebase forever.

## Watching upstream

`watch/jellyfin-upstream-watch.py` runs from cron and reports to Discord as
**Bloodhound**. It never changes anything — adopting an upstream change is always a
decision, not an automatic action.

It reports:

- a new Jellyfin release **or prerelease**. `/releases/latest` excludes prereleases,
  which is why this watcher reported "10.11.11 is upstream's latest" through seven
  `v12.0` release candidates while the 10.11 line was abandoned underneath it. It now
  enumerates releases and tracks both.
- **a per-commit port check** against those tags: each commit of the series is
  cherry-picked into a throwaway worktree and reported as `clean`, `CONFLICTS` (with
  the files named), or `DROP` when the target already contains a backport we carry.
  The verdict is posted only when it *changes*, so a standing set of conflicts does
  not become daily noise. `$SRC_DIR`'s working tree is never disturbed.
- upstream commits touching any file our patches touch, on **both `master` and
  `release-12.z`** (a rebase will conflict, or upstream fixed it and a patch can be
  dropped). The release branch matters most: a 12.z security backport lands there,
  and the GitHub commits API only looks at the default branch unless told otherwise.
- **it does NOT watch base images.** The checks are GitHub releases/commits/issues
  plus a local `docker image inspect`; nothing polls Docker Hub. The LinuxServer 12.0
  release-tag image, which unblocked this whole bump, had to be found by hand.
- any of the six tracked issues closing upstream (our patch may be redundant)
- Intro Skipper, compared **against the version actually installed**, on **our own
  release line only**. The plugin keeps one line per server major (`12.0/v12.0.3.0`,
  `10.11/v1.10.11.24`) and `/releases/latest` returns the newest publish across all
  of them: on 2026-09-10 it announced a 10.11 build to a 12.0 server and said nothing
  about `12.0/v12.0.3.0`, which had landed five minutes earlier. The check now filters
  to the line named by `PINNED` and diffs it against the plugin directory under the
  container's `/config` mount, so "we never upgraded it" is visible and the report
  cannot be silenced by its own memory of a tag. It is keyed on the
  installed-vs-newest pair, so it posts once per real gap, again by itself if either
  side moves, and once when the gap closes. It says so out loud when the line has no
  build yet, or when the installed version cannot be read, instead of going quiet.
  All of it is **informational only**: a nice-to-have plugin that does not gate a base
  bump, a feature, or an update, reported so a bump can bring a matching build along
  if one exists.
- **local drift** -- that `jellyfin-patched` still exists and is what the `jellyfin`
  container is actually running. The image is built locally and exists in no registry,
  so `docker image prune -a` or a stray `compose pull` can put the stock image back
  silently. A watcher reporting diligently on upstream while the local build has
  evaporated is exactly the dead-end cascade this setup exists to avoid.

It uses the **anonymous** GitHub API deliberately: no token to leak from a public
repo, and it is unaffected by an account-level block on the jellyfin org.

Failures are reported loudly rather than swallowed — a monitor that goes quiet when
it breaks is worse than no monitor.

    DISCORD_WEBHOOK_URL=... ./watch/jellyfin-upstream-watch.py

## Layout

    VERSION    the fork version, <upstream base>-p<N> -- read by build, release, watcher
    BASE_IMAGE the base image pinned by tag AND digest
    CHANGELOG.md  generated at release time
    releases/  one manifest per release: series, patch-ids, base digest, assemblies
    patches/   GENERATED from the series branch; applied in order onto the base tag
    build/     Dockerfile + build script (derives the assemblies, runs the smoke test)
    tools/     regen-patches.sh, port-check.py, smoke-test.sh, release.py, push-image.sh
    watch/     upstream watcher
    notes/     investigation write-ups, including things that turned out to be wrong
