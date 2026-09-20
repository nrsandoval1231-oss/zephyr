#!/usr/bin/env python3
"""reelscope - turn a highlight reel into readable, timestamped contact sheets.

Nothing here understands football. It just makes the footage viewable frame by
frame, at whatever sampling rate you ask for, with the source timecode burned
onto every tile so notes can cite an exact moment in the reel.

    python3 tools/reelscope.py reel/clip.mp4 --fps 2 --out /tmp/sheets
    python3 tools/reelscope.py reel/clip.mp4 --start 41.8 --end 59.8 --fps 6 \
        --cols 5 --rows 4 --tile-width 640

Needs ffmpeg. If it is not on PATH, `pip install imageio-ffmpeg` is enough -
the bundled binary is picked up automatically.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw, ImageFont

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
]


def find_ffmpeg():
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
    except ImportError:
        sys.exit("ffmpeg not found. Install it, or: pip install imageio-ffmpeg")
    return imageio_ffmpeg.get_ffmpeg_exe()


def load_font(size):
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def duration(ffmpeg, video):
    out = subprocess.run([ffmpeg, "-hide_banner", "-i", video],
                         capture_output=True, text=True).stderr
    for line in out.splitlines():
        if "Duration:" in line:
            hms = line.split("Duration:")[1].split(",")[0].strip()
            h, m, s = hms.split(":")
            return int(h) * 3600 + int(m) * 60 + float(s)
    sys.exit(f"could not read duration of {video}")


def scene_cuts(ffmpeg, video, threshold):
    """Timestamps where the picture changes hard - i.e. clip boundaries."""
    out = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", video, "-filter:v",
         f"select='gt(scene,{threshold})',showinfo", "-f", "null", "-"],
        capture_output=True, text=True).stderr
    cuts = []
    for line in out.splitlines():
        if "pts_time:" in line:
            cuts.append(float(line.split("pts_time:")[1].split()[0]))
    return cuts


def timecode(seconds):
    return f"{int(seconds // 60)}:{seconds % 60:06.3f}"


def extract(ffmpeg, video, start, end, fps, width, workdir, crop=None):
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error"]
    if start:
        cmd += ["-ss", str(start)]
    if end:
        cmd += ["-to", str(end)]
    chain = f"fps={fps}"
    if crop:
        chain += f",crop={crop}"
    chain += f",scale={width}:-2"
    cmd += ["-i", video, "-vf", chain,
            "-fps_mode", "passthrough", os.path.join(workdir, "f_%05d.png")]
    subprocess.run(cmd, check=True)
    return sorted(f for f in os.listdir(workdir) if f.startswith("f_"))


def build_sheets(frames, workdir, out_dir, start, fps, cols, rows, prefix):
    os.makedirs(out_dir, exist_ok=True)
    per_sheet = cols * rows
    font = None
    written = []
    for sheet_no, offset in enumerate(range(0, len(frames), per_sheet), start=1):
        chunk = frames[offset:offset + per_sheet]
        tiles = [Image.open(os.path.join(workdir, f)).convert("RGB") for f in chunk]
        tw, th = tiles[0].size
        if font is None:
            font = load_font(max(14, tw // 22))
        sheet = Image.new("RGB", (cols * tw, rows * th), "black")
        for i, tile in enumerate(tiles):
            stamp = timecode(start + (offset + i) / fps)
            draw = ImageDraw.Draw(tile)
            box = draw.textbbox((0, 0), stamp, font=font)
            draw.rectangle([0, 0, box[2] + 10, box[3] + 8], fill="black")
            draw.text((5, 2), stamp, fill="yellow", font=font)
            sheet.paste(tile, ((i % cols) * tw, (i // cols) * th))
        path = os.path.join(out_dir, f"{prefix}_{sheet_no:03d}.png")
        sheet.save(path)
        written.append(path)
    return written


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("video")
    p.add_argument("--out", default="reelscope_out", help="directory for the sheets")
    p.add_argument("--fps", type=float, default=2.0, help="frames sampled per second")
    p.add_argument("--start", type=float, default=0.0)
    p.add_argument("--end", type=float, default=None)
    p.add_argument("--cols", type=int, default=4)
    p.add_argument("--rows", type=int, default=4)
    p.add_argument("--tile-width", type=int, default=480)
    p.add_argument("--prefix", default="sheet")
    p.add_argument("--crop", default=None,
                   help="ffmpeg crop as W:H:X:Y on the 1920x1080 source, applied "
                        "before scaling - use it to zoom in on the ball")
    p.add_argument("--per-segment", type=int, metavar="N",
                   help="triage mode: detect segments, then sample N frames "
                        "evenly inside each one. Far cheaper than a flat scan "
                        "when a file holds dozens of separate plays.")
    p.add_argument("--cuts", action="store_true",
                   help="print detected clip boundaries and exit")
    p.add_argument("--cut-threshold", type=float, default=0.3)
    args = p.parse_args()

    ffmpeg = find_ffmpeg()

    if args.cuts:
        total = duration(ffmpeg, args.video)
        print(f"duration {timecode(total)} ({total:.2f}s)")
        prev = 0.0
        for cut in scene_cuts(ffmpeg, args.video, args.cut_threshold) + [total]:
            if cut - prev >= 1.0:          # ignore the frames inside a fade
                print(f"  segment {timecode(prev)} -> {timecode(cut)}  ({cut - prev:.2f}s)")
                prev = cut
        return

    if args.per_segment:
        total = duration(ffmpeg, args.video)
        cuts, prev, segs = scene_cuts(ffmpeg, args.video, args.cut_threshold), 0.0, []
        for cut in cuts + [total]:
            if cut - prev >= 1.0:
                segs.append((prev, cut))
                prev = cut
        os.makedirs(args.out, exist_ok=True)
        font = load_font(max(14, args.tile_width // 22))
        with tempfile.TemporaryDirectory() as workdir:
            tiles = []
            for n, (a, b) in enumerate(segs, start=1):
                for k in range(args.per_segment):
                    t = a + (b - a) * (k + 1) / (args.per_segment + 1)
                    f = os.path.join(workdir, f"s{n:03d}_{k}.png")
                    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error",
                                    "-y", "-ss", f"{t:.2f}", "-i", args.video,
                                    "-frames:v", "1", "-vf",
                                    f"scale={args.tile_width}:-2", f], check=True)
                    tiles.append((f, f"seg {n:02d}  {timecode(t)}  ({b - a:.0f}s)"))
            per = args.cols * args.rows
            for sheet_no, off in enumerate(range(0, len(tiles), per), start=1):
                chunk = tiles[off:off + per]
                ims = [Image.open(f).convert("RGB") for f, _ in chunk]
                tw, th = ims[0].size
                sheet = Image.new("RGB", (args.cols * tw, args.rows * th), "black")
                for i, (im, (_, cap)) in enumerate(zip(ims, chunk)):
                    d = ImageDraw.Draw(im)
                    box = d.textbbox((0, 0), cap, font=font)
                    d.rectangle([0, 0, box[2] + 10, box[3] + 8], fill="black")
                    d.text((5, 2), cap, fill="yellow", font=font)
                    sheet.paste(im, ((i % args.cols) * tw, (i // args.cols) * th))
                sheet.save(os.path.join(args.out, f"{args.prefix}_{sheet_no:03d}.png"))
        print(f"{len(segs)} segments, {len(tiles)} frames -> "
              f"{(len(tiles) + per - 1) // per} sheets in {args.out}")
        return

    with tempfile.TemporaryDirectory() as workdir:
        frames = extract(ffmpeg, args.video, args.start, args.end,
                         args.fps, args.tile_width, workdir, args.crop)
        if not frames:
            sys.exit("no frames extracted - check --start/--end")
        sheets = build_sheets(frames, workdir, args.out, args.start, args.fps,
                              args.cols, args.rows, args.prefix)
    print(f"{len(frames)} frames -> {len(sheets)} sheets in {args.out}")
    for s in sheets:
        print(f"  {s}")


if __name__ == "__main__":
    main()
