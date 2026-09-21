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
FADE = 0.12          # dip up from black at the top and out at the tail

# A purple bleed instead of a cut to black: cross-dissolve A into B while
# blooming the brand colour on a bell curve that peaks mid-transition, so it
# never lands on a flat block of purple. Commas would be eaten by the
# filtergraph parser, so the per-plane target is a quadratic through the three
# YUV values of #653397 - (0,75) (1,167) (2,146) - instead of nested if().
PURPLE_YUV_BY_PLANE = "(-56.5*PLANE*PLANE+148.5*PLANE+75)"
BLEED = 0.38         # peak strength of the colour bloom, 0-1


def bleed_expr(strength=BLEED):
    bell = f"({strength}*4*P*(1-P))"
    mix = "(A*P+B*(1-P))"
    return f"{mix}*(1-{bell})+{PURPLE_YUV_BY_PLANE}*{bell}"

# Instagram Reels covers roughly the top 120px and bottom 340px of a 1080x1920
# frame with its own UI. Everything we draw stays between those.
IG_SAFE_TOP, IG_SAFE_BOTTOM = 120, 340

# The source reel burns its own "OPPONENT | PASS" tag into the bottom-left
# corner, so every play arrived carrying two labels. Shave that strip and
# reframe to fill - about 8% of a blow-up, which is invisible on a wide
# football shot and cheaper than trying to paint the tag out.
TAG_STRIP = 80


def frame_chain(clip, cw, ch):
    """Fit a clip to the canvas, shaving the burnt-in tag when it has one."""
    if clip.get("detag", True):
        return (f"[0:v]crop=iw:ih-{TAG_STRIP}:0:0,scale=-2:{ch}:flags=lanczos,"
                f"crop={cw}:{ch}:(iw-{cw})/2:0,setsar=1[base];")
    # clips pulled straight from Hudl are 720p and carry no corner tag
    # An external Hudl pull arrives at 720p; lanczos plus a light unsharp
    # recovers some of the edge detail the blow-up costs. Title cards come in
    # at full size and must not be touched at all, or the burnt-in text shifts
    # out from under the stamps drawn at fixed positions.
    sharpen = ",unsharp=5:5:0.7:3:3:0.3" if clip.get("source") else ""
    return (f"[0:v]scale={cw}:{ch}:flags=lanczos:"
            f"force_original_aspect_ratio=increase,"
            f"crop={cw}:{ch}{sharpen},setsar=1[base];")
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


def make_label(clip, spec, path, layer="all"):
    """A transparent plate: layer "static" never fades, "anim" fades for cuts."""
    brand = spec["brand"]
    canvas = spec.get("canvas", {})
    cw, ch = canvas.get("w", W), canvas.get("h", H)
    vertical = canvas.get("mode") == "vertical"
    accent, panel = hex_rgba(brand["accent"]), hex_rgba(brand["panel"])

    # one line, nothing else: who they played, plus down and distance where a
    # scoreboard in the footage actually gives it
    line = clip.get("opponent") or ""
    if clip.get("down"):
        line = f"{line}   ·   {clip['down']}"
    line = line.upper()

    plate = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    draw = ImageDraw.Draw(plate)

    if layer != "anim" and not vertical and not clip.get("no_scrim"):
        # a light gradient at the foot of the frame - enough to seat the label
        # and knock back the source reel's own tag without dimming the sideline
        sc = brand.get("scrim", {})
        band, peak = int(sc.get("height", 190)), int(sc.get("alpha", 105))
        for i in range(band):
            y = ch - band + i
            draw.rectangle([0, y, cw, y + 1],
                           fill=(6, 6, 8, int(peak * (i / band) ** 1.5)))

    if layer != "anim":
        for st in clip.get("stamps", []):
            draw.text((st["x"], st["y"]), st["text"],
                      font=ImageFont.truetype(FONTS[st.get("font", "bold")],
                                              st["size"]),
                      fill=tuple(st["color"]))

    if layer == "static" or not clip.get("opponent"):
        plate.save(path)
        return

    if vertical:
        band_h = int(cw * 9 / 16)
        band_top = (ch - band_h) // 2
        head = ImageFont.truetype(FONTS["bold"], 34)
        hw = draw.textlength(spec["header"], font=head)
        hy = band_top - 110
        draw.text(((cw - hw) / 2, hy), spec["header"],
                  font=head, fill=(236, 236, 240, 255))
        draw.rectangle([(cw - hw) / 2, hy + 52, (cw + hw) / 2, hy + 56],
                       fill=accent)
        font = ImageFont.truetype(FONTS["bold"], 46)
        x0, y0 = 54, band_top + band_h + 80
    else:
        font = ImageFont.truetype(FONTS["bold"], 42)
        x0, y0 = 54, ch - 104

    # no filled panel - a thin accent rule and the text itself, so the label
    # sits on the picture instead of boxing a hole in it
    bh = font.size + 10
    draw.rectangle([x0, y0, x0 + 6, y0 + bh], fill=accent)
    tx, ty = x0 + 24, y0 + 2
    for dx, dy in ((2, 2), (1, 3), (3, 1)):
        draw.text((tx + dx, ty + dy), line, font=font, fill=(0, 0, 0, 150))
    draw.text((tx, ty), line, font=font, fill=(255, 255, 255, 255))

    if vertical:
        safe = canvas.get("safe_bottom", IG_SAFE_BOTTOM)
        assert y0 + bh < ch - safe, (
            f"label bottom {y0 + bh} runs into the reserved {safe}px at the "
            f"foot of a {cw}x{ch} frame")
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


def cut(ffmpeg, src, clip, label_path, out_path, canvas=None, trans=0.0):
    src = clip.get("source", src)
    dur = round(clip["out"] - clip["in"], 3)
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
            f"[fg]{'crop=iw:ih-80:0:0,' if clip.get('detag', True) else ''}"
            f"scale={cw}:-2:flags=lanczos[fgs];")
    fill += f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2,setsar=1[base];"

    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
           "-ss", str(clip["in"]), "-t", str(dur), "-i", src]

    if label_path:
        static_path, label_path = label_path
        cmd += ["-loop", "1", "-framerate", "30000/1001", "-t", str(dur),
                "-i", static_path]
        cmd += ["-loop", "1", "-framerate", "30000/1001", "-t", str(dur),
                "-i", label_path]
        if clip.get("opponent") and trans:
            # hold the label clear of both crossfades, or two of them ghost
            # through each other while the clips are dissolving
            hold_in, hold_out = trans, max(dur - trans - 0.3, trans + 0.1)
            lbl = (f"[2:v]format=rgba,"
                   f"fade=t=in:st={hold_in:.2f}:d=0.3:alpha=1,"
                   f"fade=t=out:st={hold_out:.2f}:d=0.3:alpha=1[lbl];")
        else:
            lbl = "[2:v]format=rgba[lbl];"
        base = fill if vertical else frame_chain(clip, cw, chh)
        graph = (base + "[1:v]format=rgba[stat];" + lbl
                 + "[base][stat]overlay=0:0:shortest=1[withstat];"
                 + "[withstat][lbl]overlay=0:0:shortest=1[v]")
        cmd += ["-filter_complex", graph, "-map", "[v]", "-map", "0:a"]
    elif vertical:
        cmd += ["-filter_complex", fill + "[base]null[v]",
                "-map", "[v]", "-map", "0:a"]
    else:
        cmd += ["-filter_complex", frame_chain(clip, cw, chh) + "[base]null[v]",
                "-map", "[v]", "-map", "0:a"]

    cmd += ["-c:v", "libx264", "-crf", "16", "-preset", "medium",
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
                    "-vf", "null",
                    "-c:v", "libx264", "-crf", "16", "-preset", "medium",
                    "-pix_fmt", "yuv420p", "-r", "30000/1001",
                    "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
                    "-video_track_timescale", "30000", out_path], check=True)


def clip_starts(spec):
    """Where each clip lands once the crossfade overlap is taken out."""
    d = float(spec.get("transition", {}).get("duration", 0.5))
    t, out = 0.0, []
    for i, c in enumerate(spec["clips"]):
        out.append(t)
        t += (c["out"] - c["in"]) - (d if i < len(spec["clips"]) - 1 else 0)
    return out


def assemble(ffmpeg, parts, lengths, spec, out):
    """Chain the clips together with the purple-bleed crossfade.

    Folds two clips at a time instead of building one giant filter graph:
    a single xfade chain over many inputs holds every decoded frame of
    every input in memory at once and gets OOM-killed on small machines.
    Intermediate passes use a fast preset; the final pass is the real
    quality encode.
    """
    tr = spec.get("transition", {})
    d = float(tr.get("duration", 0.5))
    style = tr.get("style", "bleed")

    xf = (f"xfade=transition=custom:expr='{bleed_expr()}'" if style == "bleed"
          else f"xfade=transition={style}")

    work = tempfile.mkdtemp(prefix="assemble_")
    acc, acc_len = parts[0], lengths[0]
    total = sum(lengths) - d * (len(parts) - 1)
    try:
        for i in range(1, len(parts)):
            last = i == len(parts) - 1
            step = os.path.join(work, f"step_{i:02d}.mp4")
            offset = acc_len - d
            vg = f"[0:v][1:v]{xf}:duration={d}:offset={offset:.3f}[vx]"
            ag = f"[0:a][1:a]acrossfade=d={d}:c1=tri:c2=tri[ax]"
            if last:
                # lift up from black at the top, settle out at the tail
                vg += (f";[vx]fade=t=in:st=0:d=0.45,"
                       f"fade=t=out:st={total - 0.6:.3f}:d=0.6[vout]")
                ag += f";[ax]afade=t=out:st={total - 0.6:.3f}:d=0.6[aout]"
                vlab, alab = "[vout]", "[aout]"
            else:
                vlab, alab = "[vx]", "[ax]"
            cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                   "-i", acc, "-i", parts[i],
                   "-filter_complex", vg + ";" + ag,
                   "-map", vlab, "-map", alab,
                   "-c:v", "libx264",
                   "-crf", "21" if last else "18",
                   "-preset", "medium" if last else "fast",
                   "-pix_fmt", "yuv420p", "-r", "30000/1001",
                   "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2"]
            if last:
                cmd += ["-movflags", "+faststart", out]
            else:
                cmd += [step]
            subprocess.run(cmd, check=True)
            acc = out if last else step
            acc_len = acc_len + lengths[i] - d
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return total


def write_description(spec, path):
    """Chapter timestamps that actually match the cut."""
    lines = [
        "Zephyr Kreye | QB | Anna Coyotes (TX) | Class of 2027",
        """H/W: 6'5" | 220 lbs | Jersey #17""",
        "2026 (through 4 games): 851 pass yds, 10 TD, 1 INT | "
        "63 rush yds, 4 TD",
        "Testing: 20yd shuttle 4.66 | L-drill 7.63 | "
        "Broad jump 9'1 | Triple broad 28'4",
        "",
        "Timestamps:",
    ]
    d = float(spec.get("transition", {}).get("duration", 0.5))
    for clip, t in zip(spec["clips"], clip_starts(spec)):
        if clip.get("headline"):
            who = f" (vs {clip['opponent']})" if clip.get("opponent") else ""
            lines.append(f"{int(t // 60)}:{int(t % 60):02d} "
                         f"{clip['headline']}{who}")
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
    p.add_argument("--out", help="override the edit list's output path")
    p.add_argument("--canvas", metavar="WxH",
                   help="override the canvas, e.g. 1080x1350 for a 4:5 feed "
                        "post. Keeps one edit list driving every aspect ratio.")
    p.add_argument("--description", metavar="PATH",
                   help="also write a YouTube/Hudl description with chapter "
                        "timestamps derived from the edit list")
    args = p.parse_args()

    spec = json.load(open(args.editlist))
    if args.canvas:
        w, h = (int(v) for v in args.canvas.lower().split("x"))
        spec.setdefault("canvas", {}).update({"w": w, "h": h})
        # a 4:5 feed post is not covered by the Reels button stack
        if h < w * 16 / 9:
            spec["canvas"].setdefault("safe_bottom", 100)
    if args.out:
        spec["output"] = args.out
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
        parts, lengths = [], []
        for i, clip in enumerate(clips):
            stat = os.path.join(work, f"static_{i:02d}.png")
            anim = os.path.join(work, f"label_{i:02d}.png")
            make_label(clip, spec, stat, layer="static")
            make_label(clip, spec, anim, layer="anim")
            label = (stat, anim)
            part = os.path.join(work, f"part_{i:02d}.mp4")
            cut(ffmpeg, src, clip, label, part, spec.get("canvas"),
                float(spec.get("transition", {}).get("duration", 0.5)))
            parts.append(part)
            lengths.append(round(clip["out"] - clip["in"], 3))
            print(f"  cut {clip['id']}")

        if spec.get("endcard"):
            card = os.path.join(work, "endcard.png")
            make_endcard(spec, card)
            part = os.path.join(work, "part_zz.mp4")
            cut_still(ffmpeg, card, spec["endcard"]["seconds"], part)
            parts.append(part)
            lengths.append(float(spec["endcard"]["seconds"]))
            print("  cut endcard")

        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        final = assemble(ffmpeg, parts, lengths, spec, out)
        print(f"  assembled {len(parts)} clips -> {final:.1f}s")

    size = os.path.getsize(out) / 1e6
    print(f"wrote {out} ({size:.1f} MB)")


if __name__ == "__main__":
    main()
