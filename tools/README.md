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
