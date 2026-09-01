# HLS remux seek offset — real defect, fix disproved

## The defect (confirmed)

`EncodingHelper.GetFastSeekCommandLineParameter` adds a hard-coded 0.5s to the seek
position when remuxing to HLS:

    var seekTick = isHlsRemuxing ? time + 5000000L : time;

The comment says this stops ffmpeg landing on the previous keyframe. It does far more
than that on dense-GOP content.

Measured on a 1080p BluRay remux, using Jellyfin's exact remux args
(`-copyts -avoid_negative_ts disabled -ss <t> -i <file> -c:v copy`) at real segment
boundaries from Jellyfin's own `ComputeSegments` (6s, the copy-codec default), reading
the first packet in file order:

    segment K |   +0.5s -> start    drift |  no offset -> start    drift
       24.566 |           24.775   +0.209 |              23.774   -0.792
       42.167 |           42.292   +0.125 |              41.333   -0.834
       84.084 |           84.167   +0.083 |              83.250   -0.834
      150.192 |          150.233   +0.041 |             149.358   -0.834

    starting LATE (content missing) -- fixed +0.5s: 11/15   no offset: 0/15

Late means the segment is missing content the playlist says it contains: a gap. 25% of
segment boundaries (37/148 over 15 minutes) sit close enough to the next keyframe for
this to happen.

Without the offset nothing starts late; everything starts *early* instead, by up to
0.834s. With `-copyts` an early start carries truthful absolute timestamps — overlap a
player can reconcile — where a late start is a hole it cannot.

## The fix that did not work

The first attempt bounded the offset by half the distance to the next keyframe. It
rested on an assumption that was never tested: that `-ss` lands on the nearest keyframe
at or before the request, so `K + epsilon` yields `K`.

It does not. Asking for `24.566` **exactly** still lands at `23.774`, a full cue back —
the seek has to satisfy all 8 streams in the file. So the bounded offset undershot and
started segments 0.4–0.88s early, worse in magnitude than the bug it targeted.

Unit tests passed because they encoded the same false premise. They tested arithmetic,
not ffmpeg. The A/B against the real encoder took ten minutes and refuted it immediately.

## Also wrong

An intermediate theory — that the Matroska cue index is sparser than the keyframe list,
so segment boundaries are unseekable — is false. Jellyfin's own `MatroskaKeyframeExtractor`
reports 11,051 cues for this file, and `24.566` is one of them. These are legitimate
boundaries.

## Where it stands

Removing the offset entirely eliminates the gap failure mode (0/15 late) at the cost of
up to 0.8s of overlap per seek. That looks right on the numbers, but how players handle
the overlap is untested, and the `// This will help subtitle syncing` comment suggests
someone hit a problem there before. Not worth shipping on a hunch — this needs a real
playback test before it becomes a patch.

## Method note

Two of the measurement harnesses gave wrong answers before the numbers above were
trusted:

- taking `min()` of several packets instead of the first packet in file order
- reusing a stale output file when ffmpeg failed, silently reporting the previous run

Both produced plausible, wrong data. Delete the output and check the exit code every run.
