#!/usr/bin/env python3
"""voiceover - narrate the recut with ElevenLabs, ducked under the crowd audio.

The VO copy lives in reel/editlist.json next to the cut points, one line per
clip. Each line is synthesized separately and anchored to its own clip's start,
so nothing drifts out of sync the way a single long read would.

    python3 tools/voiceover.py --script          # print copy + pacing, no calls
    python3 tools/voiceover.py --offline-test    # fake audio, proves the mix
    ELEVENLABS_API_KEY=... python3 tools/voiceover.py

NOTE: api.elevenlabs.io is blocked from some sandboxed environments. If the
synth step 403s at CONNECT, run this on a machine with open outbound HTTPS.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

API = "https://api.elevenlabs.io/v1/text-to-speech"
WPS_LIMIT = 3.2          # words/sec past which a broadcast read sounds rushed
# every branch of the graph must agree on rate/layout or amix and sidechaincompress
# quietly hand back mono at the wrong sample rate
FMT = "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo"


def find_ffmpeg():
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
    except ImportError:
        sys.exit("ffmpeg not found. Install it, or: pip install imageio-ffmpeg")
    return imageio_ffmpeg.get_ffmpeg_exe()


def starts(clips):
    """Absolute start offset of every clip inside the recut."""
    t, out = 0.0, {}
    for c in clips:
        out[c["id"]] = t
        t += c["out"] - c["in"]
    return out, t


def show_script(spec):
    offsets, total = starts(spec["clips"])
    print(f"{'clip':6} {'at':>6} {'secs':>5} {'words':>5} {'w/s':>5}  copy")
    for c in spec["clips"]:
        d = c["out"] - c["in"]
        w = len(c["vo"].split())
        rate = w / d
        flag = "" if rate <= WPS_LIMIT else "  <-- TIGHT"
        print(f"{c['id']:6} {offsets[c['id']]:6.1f} {d:5.1f} {w:5d} {rate:5.2f}  "
              f"{c['vo'][:58]}{flag}")
    print(f"\ntotal {total:.1f}s")


def synth(voice, text, path):
    """One ElevenLabs call -> one mp3."""
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        sys.exit("set ELEVENLABS_API_KEY")
    voice_id = os.environ.get("ELEVENLABS_VOICE_ID", voice["voice_id"])
    if voice_id.startswith("REPLACE_"):
        sys.exit("set ELEVENLABS_VOICE_ID, or put a real voice_id in editlist.json")

    body = json.dumps({
        "text": text,
        "model_id": voice["model_id"],
        "voice_settings": voice["voice_settings"],
    }).encode()
    url = f"{API}/{voice_id}?output_format={voice['output_format']}"
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "xi-api-key": key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    })
    try:
        with urllib.request.urlopen(req, timeout=120) as resp, open(path, "wb") as fh:
            shutil.copyfileobj(resp, fh)
    except urllib.error.HTTPError as e:
        sys.exit(f"ElevenLabs {e.code}: {e.read().decode('utf8', 'replace')[:400]}")
    except OSError as e:
        sys.exit(f"could not reach ElevenLabs ({e}). Outbound HTTPS blocked? "
                 "Run this on a machine with open network access.")


def fake(ffmpeg, text, path):
    """Placeholder tone the length of the read, for testing the mix offline."""
    dur = round(len(text.split()) / 2.8, 2)
    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", f"sine=frequency=220:duration={dur}",
                    "-af", "volume=0.35", path], check=True)


def mix(ffmpeg, video, tracks, voice, out):
    """Lay the VO over the recut and duck the source audio beneath it."""
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", video]
    for _, path in tracks:
        cmd += ["-i", path]

    parts, labels = [], []
    for i, (offset_ms, _) in enumerate(tracks, start=1):
        parts.append(f"[{i}:a]{FMT},adelay={offset_ms}|{offset_ms}[v{i}]")
        labels.append(f"[v{i}]")
    parts.append(f"{''.join(labels)}amix=inputs={len(tracks)}:normalize=0,"
                 f"apad,atrim=0:{voice['_total']}[vo]")
    parts.append("[vo]asplit=2[vo_mix][vo_key]")
    # sidechain the crowd audio against the VO so it dips only while he talks
    parts.append(f"[0:a]{FMT}[src];"
                 f"[src][vo_key]sidechaincompress="
                 f"threshold=0.03:ratio=9:attack=25:release=350:"
                 f"makeup=1:level_sc=1[ducked]")
    # loudnorm re-rates to 192k internally, so pin the format again on the way out
    parts.append("[ducked][vo_mix]amix=inputs=2:normalize=0,"
                 f"loudnorm=I=-15:TP=-1.5:LRA=11,{FMT}[aout]")

    cmd += ["-filter_complex", ";".join(parts),
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
            "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart", out]
    subprocess.run(cmd, check=True)


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--editlist", default="reel/editlist.json")
    p.add_argument("--out", default=None)
    p.add_argument("--script", action="store_true", help="print copy and pacing only")
    p.add_argument("--offline-test", action="store_true",
                   help="synthesize placeholder tones instead of calling the API")
    args = p.parse_args()

    spec = json.load(open(args.editlist))
    if args.script:
        show_script(spec)
        return

    video = spec["output"]
    if not os.path.exists(video):
        sys.exit(f"{video} not found - run tools/recut.py first")
    out = args.out or video.replace(".mp4", "_VO.mp4")

    ffmpeg = find_ffmpeg()
    offsets, total = starts(spec["clips"])
    voice = dict(spec["voice"], _total=round(total, 3))

    with tempfile.TemporaryDirectory() as work:
        tracks = []
        for c in spec["clips"]:
            if not c.get("vo"):
                continue
            path = os.path.join(work, f"{c['id']}.mp3" if not args.offline_test
                                else f"{c['id']}.wav")
            if args.offline_test:
                fake(ffmpeg, c["vo"], path)
            else:
                synth(voice, c["vo"], path)
                print(f"  voiced {c['id']}")
            tracks.append((int(offsets[c["id"]] * 1000), path))
        mix(ffmpeg, video, tracks, voice, out)

    size = os.path.getsize(out) / 1e6
    print(f"wrote {out} ({size:.1f} MB)"
          + ("  [placeholder tones, not speech]" if args.offline_test else ""))


if __name__ == "__main__":
    main()
