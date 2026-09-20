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

W, H = 1920, 1080    # default canvas; an edit list can override via "canvas"
FADE = 0.12          # seconds of dip in/out on every cut

# Instagram Reels covers roughly the top 120px and bottom 340px of a 1080x1920
# frame with its own UI. Everything we draw stays between those.
IG_SAFE_TOP, IG_SAFE_BOTTOM = 120, 340
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


def make_label(clip, spec, path):
    """A transparent plate carrying the lower third (and, vertically, a header)."""
    brand = spec["brand"]
    canvas = spec.get("canvas", {})
    cw, ch = canvas.get("w", W), canvas.get("h", H)
    vertical = canvas.get("mode") == "vertical"

    accent = hex_rgba(brand["accent"])
    panel = hex_rgba(brand["panel"])

    situation = clip.get("situation") or clip.get("opponent", "")
    top_line = (f"{clip['opponent']}   ·   {clip['situation']}".upper()
                if clip.get("situation") else situation.upper())
    headline = clip["headline"]

    plate = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    draw = ImageDraw.Draw(plate)

    if vertical:
        # the 16:9 footage sits as a band in the middle of the tall frame; put
        # the name above it and the play label below, both inside the safe area
        band_h = int(cw * 9 / 16)
        band_top = (ch - band_h) // 2
        head = ImageFont.truetype(FONTS["bold"], 34)
        hw = draw.textlength(spec["header"], font=head)
        hy = band_top - 110
        draw.text(((cw - hw) / 2, hy), spec["header"],
                  font=head, fill=(236, 236, 240, 255))
        draw.rectangle([(cw - hw) / 2, hy + 52, (cw + hw) / 2, hy + 56], fill=accent)

        small = ImageFont.truetype(FONTS["book"], 30)
        big = ImageFont.truetype(FONTS["bold"], 52)
        pad_x, pad_y, gap = 36, 26, 14
        bw = cw - 96
        bh = 30 + gap + 52 + pad_y * 2
        x0 = 48
        y0 = band_top + band_h + 70
        draw.rectangle([x0, y0, x0 + bw, y0 + bh], fill=panel)
        draw.rectangle([x0, y0, x0 + 7, y0 + bh], fill=accent)
        draw.text((x0 + pad_x, y0 + pad_y), top_line,
                  font=small, fill=(196, 196, 204, 255))
        draw.text((x0 + pad_x, y0 + pad_y + 30 + gap), headline,
                  font=big, fill=(255, 255, 255, 255))
        assert y0 + bh < ch - IG_SAFE_BOTTOM, "label runs under Instagram's UI"
        plate.save(path)
        return

    small = ImageFont.truetype(FONTS["book"], 26)
    big = ImageFont.truetype(FONTS["bold"], 42)
    pad_x, pad_y, gap = 34, 22, 12
    tw = max(draw.textlength(top_line, font=small),
             draw.textlength(headline, font=big))
    bw = max(int(tw) + pad_x * 2 + 10, 560)
    bh = 26 + gap + 42 + pad_y * 2

    # sit the panel low and far enough left that it covers the source reel's
    # own "OPPONENT | PASS" tag rather than stacking on top of it
    x0, y0 = 24, ch - 26 - bh
    draw.rectangle([x0, y0, x0 + bw, y0 + bh], fill=panel)
    draw.rectangle([x0, y0, x0 + 6, y0 + bh], fill=accent)

    draw.text((x0 + pad_x, y0 + pad_y), top_line,
              font=small, fill=(196, 196, 204, 255))
    draw.text((x0 + pad_x, y0 + pad_y + 26 + gap), headline,
              font=big, fill=(255, 255, 255, 255))

    plate.save(path)


def make_endcard(spec, path):
    """A native vertical end card - no letterboxed 16:9 card on a Reel."""
    canvas = spec.get("canvas", {})
    cw, ch = canvas.get("w", W), canvas.get("h", H)
    accent = hex_rgba(spec["brand"]["accent"])

    card = Image.new("RGB", (cw, ch), (9, 9, 9))
    draw = ImageDraw.Draw(card)
    fonts = [ImageFont.truetype(FONTS["bold"], 74),
             ImageFont.truetype(FONTS["bold"], 38),
             ImageFont.truetype(FONTS["book"], 32),
             ImageFont.truetype(FONTS["book"], 28),
             ImageFont.truetype(FONTS["book"], 30)]
    y = ch // 2 - 190
    for line, font in zip(spec["endcard"]["lines"], fonts):
        if line:
            tw = draw.textlength(line, font=font)
            draw.text(((cw - tw) / 2, y), line, font=font,
                      fill=(255, 255, 255, 255) if font is fonts[0]
                      else (206, 206, 214, 255))
        y += font.size + 26
        if font is fonts[0]:
            draw.rectangle([cw / 2 - 60, y - 14, cw / 2 + 60, y - 10], fill=accent)
    card.save(path)


def cut(ffmpeg, src, clip, label_path, out_path, canvas=None):
    dur = round(clip["out"] - clip["in"], 3)
    fade_out = max(dur - FADE, 0)
    chain = (f"fade=t=in:st=0:d={FADE},"
             f"fade=t=out:st={fade_out}:d={FADE}")
    canvas = canvas or {}
    cw, chh = canvas.get("w", W), canvas.get("h", H)
    vertical = canvas.get("mode") == "vertical"

    # a blurred, darkened copy of the frame fills the tall canvas; cropping
    # 16:9 football footage to 9:16 would throw away most of the field
    fill = (f"[0:v]split=2[bg][fg];"
            f"[bg]scale={cw}:{chh}:force_original_aspect_ratio=increase,"
            f"crop={cw}:{chh},gblur=sigma=28,eq=brightness=-0.18[bgb];"
            # shave the strip carrying the source reel's own "OPPONENT | PASS"
            # tag; vertically our label sits below the band and can't cover it
            f"[fg]crop=iw:ih-80:0:0,scale={cw}:-2[fgs];"
            f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2,setsar=1[base];")

    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
           "-ss", str(clip["in"]), "-t", str(dur), "-i", src]
    if label_path:
        cmd += ["-i", label_path]
        graph = (fill + f"[base][1:v]overlay=0:0,{chain}[v]") if vertical \
            else f"[0:v][1:v]overlay=0:0,{chain}[v]"
        cmd += ["-filter_complex", graph, "-map", "[v]", "-map", "0:a"]
    elif vertical:
        cmd += ["-filter_complex", fill + f"[base]{chain}[v]",
                "-map", "[v]", "-map", "0:a"]
    else:
        cmd += ["-vf", chain, "-map", "0:v", "-map", "0:a"]
    cmd += ["-c:v", "libx264", "-crf", "21", "-preset", "medium",
            "-pix_fmt", "yuv420p", "-r", "30000/1001",
            "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
            "-video_track_timescale", "30000",
            out_path]
    subprocess.run(cmd, check=True)


def cut_still(ffmpeg, image, seconds, out_path):
    """Turn the end-card PNG into a clip with silent audio so concat matches."""
    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                    "-loop", "1", "-t", str(seconds), "-i", image,
                    "-f", "lavfi", "-t", str(seconds),
                    "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
                    "-vf", f"fade=t=in:st=0:d={FADE}",
                    "-c:v", "libx264", "-crf", "21", "-preset", "medium",
                    "-pix_fmt", "yuv420p", "-r", "30000/1001",
                    "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
                    "-video_track_timescale", "30000", out_path], check=True)


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
                make_label(clip, spec, label)
            part = os.path.join(work, f"part_{i:02d}.mp4")
            cut(ffmpeg, src, clip, label, part, spec.get("canvas"))
            parts.append(part)
            print(f"  cut {clip['id']}")

        if spec.get("endcard"):
            card = os.path.join(work, "endcard.png")
            make_endcard(spec, card)
            part = os.path.join(work, "part_zz.mp4")
            cut_still(ffmpeg, card, spec["endcard"]["seconds"], part)
            parts.append(part)
            print("  cut endcard")

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
