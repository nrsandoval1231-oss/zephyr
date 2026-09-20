#!/usr/bin/env python3
"""recut - build a highlight reel from an edit list.

Reads reel/editlist.json, cuts each clip out of the source, burns a lower-third
label onto the plays, and concatenates the result.

    python3 tools/recut.py                     # build it
    python3 tools/recut.py --dry-run           # print the plan and stop

The label art is drawn with Pillow and composited with ffmpeg's overlay filter,
because the ffmpeg builds that ship with imageio-ffmpeg have no drawtext.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw, ImageFont

W, H = 1920, 1080
FADE = 0.12          # seconds of dip in/out on every cut
FONTS = {
    "bold": "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "book": "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
}


def find_ffmpeg():
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
    except ImportError:
        sys.exit("ffmpeg not found. Install it, or: pip install imageio-ffmpeg")
    return imageio_ffmpeg.get_ffmpeg_exe()


def hex_rgba(value):
    value = value.lstrip("#")
    if len(value) == 6:
        value += "FF"
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4, 6))


def make_label(clip, brand, path):
    """A transparent 1920x1080 plate carrying the lower third."""
    accent = hex_rgba(brand["accent"])
    panel = hex_rgba(brand["panel"])

    top_line = f"{clip['opponent']}   ·   {clip['situation']}".upper()
    headline = clip["headline"]

    small = ImageFont.truetype(FONTS["book"], 26)
    big = ImageFont.truetype(FONTS["bold"], 42)

    plate = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(plate)

    pad_x, pad_y, gap = 34, 22, 12
    tw = max(draw.textlength(top_line, font=small),
             draw.textlength(headline, font=big))
    bw = max(int(tw) + pad_x * 2 + 10, 560)
    bh = 26 + gap + 42 + pad_y * 2

    # sit the panel low and far enough left that it covers the source reel's
    # own "OPPONENT | PASS" tag rather than stacking on top of it
    x0, y0 = 24, H - 26 - bh
    draw.rectangle([x0, y0, x0 + bw, y0 + bh], fill=panel)
    draw.rectangle([x0, y0, x0 + 6, y0 + bh], fill=accent)

    draw.text((x0 + pad_x, y0 + pad_y), top_line,
              font=small, fill=(196, 196, 204, 255))
    draw.text((x0 + pad_x, y0 + pad_y + 26 + gap), headline,
              font=big, fill=(255, 255, 255, 255))

    plate.save(path)


def cut(ffmpeg, src, clip, label_path, out_path):
    dur = round(clip["out"] - clip["in"], 3)
    fade_out = max(dur - FADE, 0)
    chain = (f"fade=t=in:st=0:d={FADE},"
             f"fade=t=out:st={fade_out}:d={FADE}")

    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
           "-ss", str(clip["in"]), "-t", str(dur), "-i", src]
    if label_path:
        cmd += ["-i", label_path,
                "-filter_complex", f"[0:v][1:v]overlay=0:0,{chain}[v]",
                "-map", "[v]", "-map", "0:a"]
    else:
        cmd += ["-vf", chain, "-map", "0:v", "-map", "0:a"]
    cmd += ["-c:v", "libx264", "-crf", "21", "-preset", "medium",
            "-pix_fmt", "yuv420p", "-r", "30000/1001",
            "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
            "-video_track_timescale", "30000",
            out_path]
    subprocess.run(cmd, check=True)


def write_description(spec, path):
    """Chapter timestamps that actually match the cut."""
    lines = [
        "Zephyr Kreye | QB | Anna Coyotes (TX) | Class of 2027",
        """H/W: 6'5" | 220 lbs | Jersey #17""",
        "",
        "Timestamps:",
    ]
    t = 0.0
    for clip in spec["clips"]:
        if clip.get("opponent"):
            lines.append(f"{int(t // 60)}:{int(t % 60):02d} "
                         f"{clip['headline']} (vs {clip['opponent']})")
        t += clip["out"] - clip["in"]
    lines += [
        "",
        "Hudl profile: https://www.hudl.com/profile/20145851/Zephyr-Kreye",
        "Full games: Add a no-login Hudl or unlisted YouTube link before publishing",
        "Contact: zephyrkreye17@gmail.com | @ZephyrKreye",
    ]
    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--editlist", default="reel/editlist.json")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--description", metavar="PATH",
                   help="also write a YouTube/Hudl description with chapter "
                        "timestamps derived from the edit list")
    args = p.parse_args()

    spec = json.load(open(args.editlist))
    src, out = spec["source"], spec["output"]
    clips = spec["clips"]

    total = sum(c["out"] - c["in"] for c in clips)
    plays = [c for c in clips if c.get("opponent")]
    print(f"{len(clips)} clips ({len(plays)} plays), {total:.1f}s -> {out}")
    for c in clips:
        tag = c.get("headline", c["id"])
        print(f"  {c['in']:7.2f} -> {c['out']:7.2f}  ({c['out'] - c['in']:5.2f}s)  {tag}")
    if args.dry_run:
        return

    if args.description:
        write_description(spec, args.description)
        print(f"wrote {args.description}")

    ffmpeg = find_ffmpeg()
    with tempfile.TemporaryDirectory() as work:
        parts = []
        for i, clip in enumerate(clips):
            label = None
            if clip.get("opponent"):
                label = os.path.join(work, f"label_{i:02d}.png")
                make_label(clip, spec["brand"], label)
            part = os.path.join(work, f"part_{i:02d}.mp4")
            cut(ffmpeg, src, clip, label, part)
            parts.append(part)
            print(f"  cut {clip['id']}")

        manifest = os.path.join(work, "parts.txt")
        with open(manifest, "w") as fh:
            for part in parts:
                fh.write(f"file '{part}'\n")

        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                        "-f", "concat", "-safe", "0", "-i", manifest,
                        "-c", "copy", "-movflags", "+faststart", out], check=True)

    size = os.path.getsize(out) / 1e6
    print(f"wrote {out} ({size:.1f} MB)")


if __name__ == "__main__":
    main()
