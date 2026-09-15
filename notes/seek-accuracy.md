# Seek accuracy on the HLS path — measured 2026-09-15

Question asked: when a client seeks, where does playback actually land, and how long does
it take? Measured against the **live** server with `tools/seek-probe.py`, which does what a
client does — `PlaybackInfo` → `master.m3u8` → `main.m3u8` → `GET` the segment exactly as
the playlist spells it — then ffprobes the served bytes (first packet in file order) and
compares them with the `runtimeTicks` the playlist declared for that segment.

## Which path actually runs here

All 14 retained `FFmpeg.Transcode-*` logs and all 9 launches in three days of main log are
`-codec:v:0 h264_vaapi -codec:a:0 copy`: the Fire TV Stick (`Amazon AFTT`) transcoding
1080p HEVC 10-bit. **Zero copy-codec remuxes.** Every other client direct-plays.

So the +0.5s remux offset in `notes/hls-seek.md` is a real defect that has not run once on
this server in the retained history. It is not where seek time goes here.

On the transcode path: segments are equal-length (`ComputeEqualLengthSegments`, 3.004s for
29.97fps, 3.003s for 23.976), `-ss` is passed unmodified, `-copyts` keeps absolute
timestamps, and audio is stream-copied with `-bsf:a noise=drop='lt(pts*tb,<seek>)'` to drop
packets before the seek point.

## Landing accuracy: within one frame, nothing to fix

`v0` = first video packet, `a0` = first audio packet, both minus the constant +10s the
muxer adds (checked constant across restarts: segment 0 from a cold start lands at 10.000).

    file                          seg  declared   v0.dts   v0.pts   a0.pts   Δpts     Δaudio
    MwC S03E14 (29.97, 8.5 Mbps)  272  817.088  817.083  817.116  817.088  +0.028  +0.000
                                  100  300.400  300.367  300.400  300.416   0.000  +0.016
                                  50   150.200  150.183  150.217  150.208  +0.017  +0.008
    Banshee S03E08 (24, 19 Mbps)  100  300.300  300.258  300.300  300.266   0.000  -0.034
                                  117  351.351  351.268  351.309  351.275  -0.042  -0.076

Every segment starts on a keyframe, exactly 90 (or 72) frames long, first displayed frame
within ±1 frame of the declared start, audio within one EAC3/DTS frame. Video that starts
one frame early is overlap with truthful timestamps; the player discards it. No holes.

## Where the time goes: latency, not accuracy

TTFB of the requested segment, as the client sees it.

    cold seek (new ffmpeg)                        2.0–3.2 s   (ffmpeg open+seek ≈0.9 s, then
                                                               3 s of content at ~3x)
    next segment while ffmpeg runs                0.6–0.7 s
    backward into already-produced segments       0.00 s
    forward within the no-restart window          up to 7.7 s  ← the only defect found

The controller restarts ffmpeg for a backward seek or a forward gap of more than
`24 / SegmentLength` = 8 segments; anything closer **waits for the encoder to get there**.
That was tuned for encoders well above realtime. This CPU decodes 1080p HEVC 10-bit in
software at **2.87x (29.97fps) / 3.41x (24fps)** — every transcode log ends on 2.84–2.88x —
so waiting costs `(segments ahead × 3s) / 2.9`:

    pattern (MwC S03E14)                                     ffmpeg    TTFB
    seek 100 → immediately +7 segs (21 s)                    waited    5.94 s
    seek 100 → immediately +9 segs (27 s)                    waited    7.73 s   (gap shrank to ≤8 while ffmpeg advanced)
    seek 100 → 5 s later +10 segs (the app's 30 s skip)      waited    3.52 s
    seek 100 → 5 s later +10 segs again                      waited    3.72 s
    seek 100 → 10 s later +10 segs                           produced  0.01 s
    seek 100 → immediately +10 segs, ×4                      restart   2.6–3.2 s each
    Banshee: seek 100 → immediately +7 segs                  waited    4.73 s

A restart would have served every "waited" row in ~2–3 s. Cost of the wait path on this
hardware: **1–5 s extra per skip, only when the skip is pressed within ~10 s of the
previous start/seek** (after that the encoder is far enough ahead and the skip is instant;
the throttler keeps it ≤180 s ahead). Mashing skip-forward through an intro on the Fire TV
is exactly that pattern. On content the encoder cannot do above realtime the wait path never
wins — but that content is unwatchable via transcode on this CPU anyway.

Candidate fix (not built — measure first, this is the measurement): make the restart
decision speed-aware. `TranscodingJob` already receives ffmpeg's progress (`Framerate`,
`TranscodingPositionTicks`, set in `TranscodeManager.OnTranscodeProgress`); estimated wait = segments-ahead × segment length ÷ (framerate ÷
source fps); restart when that exceeds the observed restart cost (~2.5 s here). Proving it
is one `seek-probe.py` run per row above against a `jf12test`-style container.

## One-off: 15.9 s first start, and where it went

The very first segment request of the evening (segment 0, cold, after ~20 h with no
transcodes) took **15.9 s**; every later cold start took 1.9–2.2 s, including a file that
had never been played. Where it went is in the logs: ffmpeg was launched 0.3 s after
`PlaybackInfo` and ran 16.8 s of wall time, but its own `elapsed=` counter reached only
3.79 s — so **~13 s were spent inside ffmpeg before it produced a frame**: opening and
probing the input, not Jellyfin, not encoding. The same open+probe measured directly
afterwards takes 0.18 s (`-analyzeduration 200M -probesize 1G` are Jellyfin's defaults for
everyone and are maxima, not minima). Suspect: a cold read from the NAS (`/data/tv` is
Vol1/sda, which by the 2026-06-29 finding never spins down — so not a spin-up, unless that
finding is stale). Not reproduced tonight; reproducing it needs 30+ min of NAS idle before
a cold probe. If "first play of the day is slow" ever gets reported, this is the number and
the split.

`Unrepairable overflow!` appears exactly once per transcode job, mid-stream, on every job
including the ones that ran fine. Unattributed; not a seek symptom.

## Method notes

- Probe the real endpoint, not re-derived ffmpeg args: this run caught that the playlist
  declares 817.088 for segment 272 (3.004 × 272), which is why the live log shows
  `-ss 00:13:37.088` — a plain segment request, not a resume. Equal-length segments are
  frame-aligned, not 3.000 s.
- The +10 s muxer offset is constant; compare deltas, never absolute PTS.
- The gap rule is evaluated against `currentTranscodingIndex` *at request time*, so the
  same skip lands on a different path depending on how far ffmpeg has already run. Pace the
  requests (`sN` tokens) to reproduce what a viewer does.
