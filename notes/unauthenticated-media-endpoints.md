# Jellyfin: media streaming endpoints served without authentication

A self-contained brief. Everything below was verified against a live Jellyfin
10.11.11 server on 2026-09-02; nothing is quoted from memory or documentation.

---

## What I want

Jellyfin serves media files to unauthenticated callers. The obvious fix
(`[Authorize]`) breaks playback on real clients — I tried it, it broke, and I
had to weaken it to something that is a no-op on my network. **I want a fix
that actually closes the hole without breaking streaming clients.**

Skip to "The question" at the bottom if you want the ask first.

---

## Environment

| | |
|---|---|
| Server | Jellyfin **10.11.11**, `linuxserver/jellyfin:10.11.11ubu2604-ls43`, Docker |
| Host | Linux, media files bind-mounted at `/data/tv`, `/data/movies` inside the container |
| Client that broke | **Jellyfin for Android TV 0.19.10** (ExoPlayer) |
| Exposure | LAN only. Not port-forwarded, not behind a reverse proxy, not on Tailscale Funnel. |
| Source | `github.com/jellyfin/jellyfin`, tag `v10.11.11`, built locally with patches |

I maintain a small patch set against the release tag and build my own image, so
**a source-level fix is viable for me** — I am not limited to configuration.

---

## Root cause

`Jellyfin.Server/Extensions/ApiServiceCollectionExtensions.cs` configures
authorization like this (line ~68):

```csharp
options.DefaultPolicy = new AuthorizationPolicyBuilder()
    .AddRequirements(new DefaultAuthorizationRequirement())
    .Build();

options.AddPolicy(Policies.AnonymousLanAccessPolicy, new AnonymousLanAccessRequirement());
options.AddPolicy(Policies.CollectionManagement, ...);
// ... ~15 more named policies
```

There is **no `FallbackPolicy`** and **no global `AuthorizeFilter`** registered
on MVC. In ASP.NET Core, `DefaultPolicy` only applies to an action that already
carries an `[Authorize]` attribute with no policy named. An action with *no*
`[Authorize]` attribute at all carries no authorization metadata, so the
authorization middleware has nothing to evaluate and lets it through.

So authentication in Jellyfin is **opt-in per action**. Any controller action
whose author forgot the attribute — or deliberately omitted it — is anonymous.
Eleven media-serving actions omit it.

## The eleven endpoints

Verified by parsing the pristine `v10.11.11` sources and checking each
`[HttpGet]`/`[HttpHead]` action for an `[Authorize]` attribute in its attribute
block. `BaseJellyfinApiController` carries `[Route("[controller]")]`, so
`AudioController` → `/Audio`, `VideosController` → `/Videos`.

| Controller | Route |
|---|---|
| AudioController | `GET\|HEAD /Audio/{itemId}/stream` |
| AudioController | `GET\|HEAD /Audio/{itemId}/stream.{container}` |
| VideosController | `GET\|HEAD /Videos/{itemId}/stream` |
| VideosController | `GET\|HEAD /Videos/{itemId}/stream.{container}` |
| VideoAttachmentsController | `GET /Videos/{videoId}/{mediaSourceId}/Attachments/{index}` |
| SubtitleController | `GET /Videos/{itemId}/{mediaSourceId}/Subtitles/{index}/Stream.{format}` |
| SubtitleController | `GET /Videos/{itemId}/{mediaSourceId}/Subtitles/{index}/{startPositionTicks}/Stream.{format}` |
| HlsSegmentController | `GET /Audio/{itemId}/hls/{segmentId}/stream.mp3` and `.aac` |
| HlsSegmentController | `GET /Videos/{itemId}/hls/{playlistId}/{segmentId}.{segmentContainer}` |
| LiveTvController | `GET /LiveRecordings/{recordingId}/stream` |
| LiveTvController | `GET /LiveStreamFiles/{streamId}/stream.{container}` |

`AudioController` does not type-check the item it serves, so `/Audio/{id}/stream`
will happily return a **video** file given a video item's id.

Note the asymmetry that makes this easy to miss: the *metadata* endpoint is
protected while the *file* endpoint is not.

```
GET /Items/{id}                     -> 401 Unauthorized
GET /Videos/{id}/stream?static=true -> 206 Partial Content + the media file
```

## Upstream is aware

Four issues, all filed by `felix920506` on **2025-04-23**, all still **open** as
of 2026-09-02 — sixteen months:

- #13983 — `GetAttachment()` (VideoAttachmentsController) endpoint is unauthenticated
- #13984 — Video streams unauthenticated (VideosController, HlsSegmentController)
- #13985 — Subtitle endpoints unauthenticated
- #13986 — All endpoints in AudioController are unauthenticated

## Why "you still need to know the item id" is not a defence

The item id is not a secret. It is a pure function of the file's path.

`Emby.Server.Implementations/Library/LibraryManager.cs`, `GetNewItemIdInternal`:

```csharp
if (forceCaseInsensitive || !_configurationManager.Configuration.EnableCaseSensitiveItemIds)
{
    key = key.ToLowerInvariant();
}

key = type.FullName + key;

return key.GetMD5();
```

where `key` is the item's path as the server sees it (i.e. the path *inside the
container*), and `GetMD5()` is
`MediaBrowser.Common/Extensions/BaseExtensions.cs` — an MD5 over
**UTF-16LE** bytes, returned as a `Guid` (so the first three fields are
byte-swapped when formatted).

Reimplemented in Python:

```python
import hashlib, uuid

def jellyfin_item_id(type_full_name, path, case_sensitive_ids=True):
    key = path if case_sensitive_ids else path.lower()
    key = type_full_name + key
    return uuid.UUID(bytes_le=hashlib.md5(key.encode('utf-16-le')).digest()).hex

# type_full_name is the .NET type, e.g.
#   MediaBrowser.Controller.Entities.TV.Episode
#   MediaBrowser.Controller.Entities.Movies.Movie
#   MediaBrowser.Controller.Entities.Audio.Audio
```

**Verified end to end.** Taking a file path only:

```
type: MediaBrowser.Controller.Entities.TV.Episode
path: /data/tv/Only Fools and Horses/Season 4/Only Fools and Horses-1981-S04E01-1080p AMZN WEB-DL H265 SDR DDP 2.0 English-HONE.mkv

derived id: 67fb2c449e21baa890f29f33428f3b14
server's actual id for that item, from its own logs: 67fb2c449e21baa890f29f33428f3b14
```

Then, with **no token, no cookie, no API key**:

```
$ curl -s -o /dev/null -w 'status=%{http_code} bytes=%{size_download} type=%{content_type}\n' \
    -r 0-1048575 \
    'http://192.168.1.15:8096/Videos/67fb2c449e21baa890f29f33428f3b14/stream?static=true'

status=206 bytes=1048576 type=video/x-matroska
```

So an attacker who can reach the server needs only to *guess the path*, not
steal an id. Media paths are extremely guessable — scene/release naming is
formulaic, and the mount prefix is one of a handful of conventions
(`/data/tv`, `/media/tv`, `/mnt/media`…). Enumeration is offline: hash
candidate paths locally, then make one request per hit. `EnableCaseSensitiveItemIds`
was `true` on my server, which *narrows* the space further because the exact
release-cased filename is the only thing that hashes correctly — but with
`false` the attacker's job is easier still, since case no longer matters.

---

## Why the obvious fix does not work

I added a bare `[Authorize]` to all eleven actions, built, and deployed. **It
broke playback on the Android TV client immediately.**

Observed: the app showed "Player error encountered, will retry" at the start of
every playback. Server access log, five times in the window:

```
GET /Videos/67fb2c44-…/stream?container=mkv&static=true&tag=…&mediaSourceId=…
    &streamOptions=%7B%7D&enableAudioVbrEncoding=true   -> 401
```

The client sends **no `api_key` query parameter and no `X-Emby-Token` /
`Authorization` header** on the stream URL itself. It authenticates the
`PlaybackInfo` negotiation, receives a stream URL, and then fetches that URL
bare. On 401 it gives up on direct play, re-POSTs `PlaybackInfo`, and falls back
to `/Videos/{id}/hls1/main/*.ts`, i.e. a server-side HLS remux — so every
playback silently dropped off direct play onto transcoding infrastructure.

This is not an oversight by Jellyfin. `HlsSegmentController.cs` carries this
comment above `GetHlsVideoSegmentLegacy`, verbatim from the v10.11.11 tag:

```csharp
// Can't require authentication just yet due to seeing some requests come from Chrome without full query string
// [Authenticated]
```

So the anonymity is load-bearing for client compatibility. **Closing it
naively and keeping direct play working are mutually exclusive on this client.**

## What I settled for, and why it is unsatisfying

I switched from `[Authorize]` to a policy Jellyfin already registers:

```csharp
[Authorize(Policy = Policies.AnonymousLanAccessPolicy)]
```

`Jellyfin.Api/Auth/AnonymousLanAccessPolicy/AnonymousLanAccessHandler.cs`:

```csharp
var ip = _httpContextAccessor.HttpContext?.GetNormalizedRemoteIP();

// Loopback will be on LAN, so we can accept null.
if (ip is null || _networkManager.IsInLocalNetwork(ip))
{
    context.Succeed(requirement);
}
else
{
    context.Fail();
}
```

Anonymous requests from `NetworkConfiguration.LocalNetworkSubnets` pass;
everything else gets 401. Direct play works again (verified: zero ffmpeg
processes spawned across subsequent playbacks, where previously every playback
spawned a remux).

**But on my network this is a no-op.** My `LocalNetworkSubnets` is
`192.168.1.0/24`, `172.19.0.0/16`, `100.64.0.0/10` — LAN, Docker bridge,
Tailscale CGNAT range. Every path that can currently reach the server is inside
one of those. There is no request in existence today that this refuses but stock
Jellyfin would have served. Its only value is defence in depth for the day the
server ends up behind a proxy or a port forward.

I also could not construct a genuine negative test: a request from a container
on a different Docker bridge (`172.18.0.0/16`, deliberately *not* in the list)
still passed, because Docker NATs it and the server sees `172.19.0.1` — which
legitimately is on the list. So the deny branch is unexercised on this host.

---

## Constraints on any proposed solution

1. **Direct play must survive.** Any fix that makes Jellyfin Android TV 0.19.10
   fall back to HLS remuxing is a regression, not a fix. Transcoding on this
   hardware is expensive and the fallback is what I was originally debugging.
2. **I cannot modify the client.** Assume the client sends the stream URL with
   no credentials attached, as observed.
3. **Server-side source changes are fine.** I build from the `v10.11.11` tag
   with my own patches, so I can change any server code. I would prefer a small,
   rebase-friendly patch, because I carry it across upstream releases by hand.
4. **It must not depend on the reverse proxy**, because there isn't one, and the
   point is to be correct if one appears later.
5. Web UI, other clients (Jellyfin Web, iOS, Kodi) should keep working.

## Things I have already considered

- **`FallbackPolicy` / global `AuthorizeFilter`** — closes everything at once,
  but has the same client-breaking effect and a far larger blast radius.
- **Signed, expiring stream URLs** — the server already knows the item and user
  at `PlaybackInfo` time and mints the stream URL there, so it could append an
  HMAC over `(itemId, mediaSourceId, userId, expiry)` and validate it in an
  authorization handler. This seems like the strongest option to me, but I have
  not established whether *every* stream URL the clients use actually originates
  from a server response I control, or whether some clients construct URLs
  themselves — which would break them.
- **`RemoteIPFilter`** — Jellyfin has a built-in IP allow/deny list
  (`<RemoteIPFilter>`, `<IsRemoteIPFilterBlacklist>`), currently empty. Blunt,
  and same practical scope as what I already have.

## The question

Given the constraint that the client fetches stream URLs with no credentials:

1. **Is the signed-URL approach sound for Jellyfin specifically?** Where exactly
   are stream URLs minted server-side (`MediaInfoHelper` / `PlaybackInfo`
   response construction), and do all official clients use the URL the server
   returns rather than composing their own? If some compose their own, which?
2. **Is there an existing Jellyfin mechanism I have missed** — a device/session
   token bound to `PlaySessionId`, for instance? Every one of these requests
   does carry `mediaSourceId` and usually `PlaySessionId`, which the server
   already tracks in `SessionManager`. Could a handler validate that the
   requested item matches an *active, authenticated* play session, and 401
   otherwise? That would authenticate the request without needing a credential
   on the URL. What breaks — resume-after-restart, seeking, multiple
   simultaneous sessions?
3. **Is my threat model right?** Given the server is LAN-only today, is the
   `AnonymousLanAccessPolicy` mitigation actually the proportionate answer, and
   the correct move is to stop here and just never expose Jellyfin directly?
4. **Anything wrong with the analysis above?** Particularly the id-derivation
   claim and the assertion that the missing `FallbackPolicy` is what makes these
   actions anonymous.

Concrete, code-level answers preferred. I can test anything against a live
10.11.11 instance and rebuild from source in about two minutes.
