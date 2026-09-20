# Voiceover script — Zephyr Kreye coach reel

Timed to `Kreye_Zephyr_QB_Anna_2027_CoachReel_v2.mp4` (63.5s).
Each line is recorded **separately** and dropped at its own timecode —
do not record this as one continuous read, it will drift out of sync.

## Voice settings

- Model: `eleven_multilingual_v2`
- Stability **0.4** — deliberately low; high stability gives a flat corporate read, wrong for sports
- Similarity **0.75**, Style **0.45**
- Delivery: broadcast play-by-play. Lean on the bolded moments.

## Lines

| # | Drop at | Budget | Line |
|---|---------|--------|------|
| 1 | 0:00.0 | 6.0s | Zephyr Kreye. Six foot five, two hundred twenty pounds. Quarterback, Anna High School, class of twenty twenty-seven. |
| 2 | 0:05.8 | 12.2s | Anna backed up on their own goal line. Kreye takes it in his own end zone, pressure in his face, and lets it go. Nobody catches him. Ninety yards. Touchdown, Coyotes. |
| 3 | 0:17.4 | 5.5s | Edge comes free. Kreye slides left, throws across his body, on the money at the fifty. |
| 4 | 0:22.4 | 10.7s | First and ten at the twenty-nine. Kreye works right and finds number one in the flat. He's got blockers. Pylon. Touchdown. |
| 5 | 0:32.5 | 7.5s | Watch the clock in his head. Two seconds. Three. Still square, still climbing, and now he turns it loose. |
| 6 | 0:39.5 | 8.5s | Kreye takes his shot down the right boundary. Number two runs under it. Thirty yards, down inside the twenty. |
| 7 | 0:47.4 | 5.5s | Red zone, tight man coverage. He puts it where only his guy can get it. |
| 8 | 0:52.4 | 6.0s | Third and five. The pocket caves, but he will not go down. Steps up, and he's gone. |
| 9 | 0:57.8 | 6.0s | Zephyr Kreye. Number seventeen. Anna, Texas. Full film and contact below. |

## Copy-paste blocks

One block per clip. Render each, name the file after the clip id, and
`tools/voiceover.py` will place them automatically.

**intro** — 0:00.0

```
Zephyr Kreye. Six foot five, two hundred twenty pounds. Quarterback, Anna High School, class of twenty twenty-seven.
```

**p10** — 0:05.8

```
Anna backed up on their own goal line. Kreye takes it in his own end zone, pressure in his face, and lets it go. Nobody catches him. Ninety yards. Touchdown, Coyotes.
```

**p04** — 0:17.4

```
Edge comes free. Kreye slides left, throws across his body, on the money at the fifty.
```

**p09** — 0:22.4

```
First and ten at the twenty-nine. Kreye works right and finds number one in the flat. He's got blockers. Pylon. Touchdown.
```

**p01** — 0:32.5

```
Watch the clock in his head. Two seconds. Three. Still square, still climbing, and now he turns it loose.
```

**p08** — 0:39.5

```
Kreye takes his shot down the right boundary. Number two runs under it. Thirty yards, down inside the twenty.
```

**p11** — 0:47.4

```
Red zone, tight man coverage. He puts it where only his guy can get it.
```

**p02** — 0:52.4

```
Third and five. The pocket caves, but he will not go down. Steps up, and he's gone.
```

**outro** — 0:57.8

```
Zephyr Kreye. Number seventeen. Anna, Texas. Full film and contact below.
```

## Generating it

Never put the API key in a file in this repository — it is public.
Set it in the environment instead:

```powershell
$env:ELEVENLABS_API_KEY = "sk_..."
$env:ELEVENLABS_VOICE_ID = "..."
python tools\voiceover.py
```

