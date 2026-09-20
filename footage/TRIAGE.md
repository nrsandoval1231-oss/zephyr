# Hudl archive — triage

Every file scanned with `tools/reelscope.py --per-segment`, which detects clip
boundaries and samples frames inside each one. 173 segments looked at.

## Game film — usable

| File | Plays | Game |
|------|-------|------|
| `game-1-zephyr-kreye-vs-colleyville.mp4` | 10 | Colleyville Heritage, day, Anna in white (GCISD field) |
| `game-4-emerson.mp4` | 9 | Emerson, night, at Anna |
| `emerson-high-school.mp4` | 13 | Emerson |
| `67-yard-touchdown-pass-vs-colleyville-heritage.mp4` | 1 | **in the reel** |
| `40-yard-touchdown-pass-vs-brock.mp4` | 1 | **in the reel** |
| `29-yard-touchdown-pass-vs-panther-creek.mp4` | 1 | already in the reel |
| `90-yard-touchdown-pass-vs-emerson.mp4` | 1 | already in the reel |
| `anna-hs-package-long-b.mp4` from 3:36 | ~20 | mixed game / 7-on-7 |

The archive covers **four opponents**: Emerson, Colleyville Heritage, Panther
Creek, Brock. All four are already represented in the reel. More mining buys
more plays from the same four games, not new games.

## Not game film

| File | What it actually is |
|------|--------------------|
| `anna-hs-package-long-a.mp4` (9:12, 44 segments) | Spring practice and scrimmage. Indoor facility and outdoor practice fields, empty stands, mixed practice jerseys, coaches standing in the frame. |
| `zephyr-kreye-sp-highlight.mp4` (2:12, 15 segments) | Same — spring ball. |
| `zephyr-kreye-throws-testing.mp4` (3:31) | Indoor workout, shorts and t-shirt. |
| `anna-hs-package-long-b.mp4` to 3:35 (24 segments) | Combine testing session. |

Practice reps against your own defense don't evaluate a quarterback, so none of
this belongs in a coach reel. It is not worthless, though — see below.

## What the testing footage gave up

Package B carries on-screen measurables in segments 21–24:

- **20-yard shuttle 4.66**
- **L-drill 7.63**
- **Broad jump 9'1"**
- **Triple broad 28'4"**

Those are now in both description files. They close part of the stat-line gap
the play-by-play flagged; a season passing line is still missing.

## Resolution

Everything in `footage/hudl/` is 720p. The reel's original source is 1080p, so
the two Hudl clips added to the reel are upscaled and read slightly softer. If
Hudl will export 1080p, re-pull those two and rebuild.
