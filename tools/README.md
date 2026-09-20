# tools/

## reelscope.py

The repo ships a 2:21 highlight reel and no way to look at it. `reelscope.py`
turns the video into timestamped contact sheets you can actually read - either
in a browser/image viewer or by handing them to a model.

### Setup

ffmpeg is the only real dependency. If it's not on PATH:

```bash
pip install imageio-ffmpeg Pillow
```

The script finds the bundled ffmpeg binary automatically.

### Find the clip boundaries first

```bash
python3 tools/reelscope.py reel/Kreye_Zephyr_QB_Anna_2027_CoachReel.mp4 --cuts
```

Scene-change detection prints every segment. The default threshold (0.3) misses
cuts between two clips shot from similar angles - drop it to `--cut-threshold 0.12`
to catch those. On this reel that's the difference between finding 10 plays and
finding 12.

### Survey a play

One frame per second, three per sheet, full field:

```bash
python3 tools/reelscope.py reel/Kreye_Zephyr_QB_Anna_2027_CoachReel.mp4 \
  --start 41.8 --end 47.7 --fps 1 --cols 1 --rows 3 --tile-width 1520 --out /tmp/p04
```

### Zoom in on the throw

Fewer tiles + a crop = more real pixels per frame. `--crop` is `W:H:X:Y` against
the 1920x1080 source, applied before scaling:

```bash
python3 tools/reelscope.py reel/Kreye_Zephyr_QB_Anna_2027_CoachReel.mp4 \
  --start 42.6 --end 44.6 --fps 4 --cols 2 --rows 2 --tile-width 760 \
  --crop 900:506:900:400 --out /tmp/p04zoom
```

### What works

- **Field strip** (`--crop 1920:480:0:280 --cols 1 --rows 3`) drops the sky and
  the sideline and keeps the playing surface at near-native resolution. Best
  default for following a play end to end.
- **2x2 at 760px with a tight crop** is the highest-detail view: enough to read
  jersey numbers and see the ball leave the hand.
- Grids bigger than 3x3 downscale past the point where the ball is visible.
- The stadium scoreboard is legible on the end-zone-angle clips. Crop it
  (`--crop 260:120:1000:140` or thereabouts, it moves shot to shot) and you get
  down, distance, ball-on, quarter and score for free.

Every tile is stamped with its source timecode, so notes cite an exact moment.

---

## recut.py

Builds the reel from `reel/editlist.json` — cut points, play order, label copy
and VO script all live in that one file.

```bash
python3 tools/recut.py --dry-run     # print the plan
python3 tools/recut.py --description reel/..._v2_Description.txt
```

Labels are drawn with Pillow and composited via ffmpeg's `overlay`, because the
ffmpeg builds bundled with imageio-ffmpeg have no `drawtext`.

## voiceover.py

Narrates the recut with ElevenLabs and ducks the crowd audio underneath.

```bash
python3 tools/voiceover.py --script          # copy + pacing, no API calls
python3 tools/voiceover.py --offline-test    # placeholder tones, proves the mix
export ELEVENLABS_API_KEY=sk_...
export ELEVENLABS_VOICE_ID=...
python3 tools/voiceover.py                   # -> ..._v2_VO.mp4
```

Design notes:

- **One call per clip, not one long read.** Each line is anchored to its own
  clip's start offset, so nothing drifts. A single 79-second read will creep out
  of sync by the third play.
- **Duck, don't mute.** `sidechaincompress` keys the source audio off the VO, so
  the crowd only dips while he's talking and comes back up for the reaction.
  Muting the field audio makes it feel sterile.
- **Every branch of the filter graph is pinned** to 48 kHz stereo with `aformat`.
  Skip that and `amix`/`sidechaincompress` silently hand back mono at the wrong
  rate, and `loudnorm` re-rates to 192 kHz on its way out.
- **Pacing is checked before you spend credits.** `--script` flags any line over
  3.2 words/second, which is where a broadcast read starts sounding rushed.
- Output goes to a separate `_VO.mp4`. The clean coach cut is never overwritten.

`api.elevenlabs.io` is blocked by some sandboxed network policies (403 at
CONNECT). If the synth step fails that way, run it somewhere with open outbound
HTTPS — everything else in the pipeline works offline.
