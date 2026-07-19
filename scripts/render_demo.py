#!/usr/bin/env python3
"""Render the README demo GIF: a synthetic Claude Code terminal next to a
bulb whose glow follows the session states. Pure Pillow frames piped to
ffmpeg, no camera involved.

Usage: ./venv/bin/python scripts/render_demo.py
Writes assets/demo.gif and assets/demo.mp4.
"""

import math
import os
import shutil
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 880, 460
FPS = 12
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "assets")
FRAMES = os.path.join(BASE, ".demo-frames")

BG = (13, 13, 17)
PANEL = (22, 22, 26)
PANEL_EDGE = (42, 42, 50)
TEXT = (222, 222, 228)
MUTED = (130, 130, 142)

COLORS = {
    "idle": (34, 197, 94),
    "thinking": (245, 158, 11),
    "tool-done": (59, 130, 246),
    "waiting": (239, 68, 68),
    "error": (239, 68, 68),
}

# (state, duration_s, terminal line appended when the beat starts)
SCRIPT = [
    ("idle",      2.0, "$ claude"),
    ("thinking",  1.4, "> ship the thing"),
    ("tool-done", 0.9, "  Bash(git status) done"),
    ("thinking",  1.0, None),
    ("tool-done", 0.7, "  Edit(glow.py) done"),
    ("thinking",  0.8, None),
    ("tool-done", 0.7, "  Bash(pytest) passed"),
    ("idle",      2.2, "  turn complete"),
    ("waiting",   4.6, "  ? approval needed - bulb pulls you back"),
    ("thinking",  1.0, "> approved, go"),
    ("tool-done", 0.8, None),
    ("idle",      2.4, "  done. room is green again"),
]

CAPTIONS = {
    "idle": "idle - dim green",
    "thinking": "tool running - amber",
    "tool-done": "tool finished - blue",
    "waiting": "needs you - red, pulsing",
    "error": "error - solid red",
}


def font(size, bold=False):
    try:
        return ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", size,
                                  index=1 if bold else 0)
    except OSError:
        return ImageFont.load_default()


def beat_at(t):
    """Return (state, seconds_into_beat, visible_terminal_lines)."""
    lines, acc = [], 0.0
    for state, dur, line in SCRIPT:
        if line is not None and t >= acc:
            lines.append((line, state))
        if acc <= t < acc + dur:
            return state, t - acc, lines
        acc += dur
    last = SCRIPT[-1]
    return last[0], 0.0, lines


def brightness(state, into):
    if state == "waiting":
        return 0.45 + 0.55 * (0.5 + 0.5 * math.sin(into * 2 * math.pi / 0.9))
    return {"idle": 0.4, "thinking": 0.95, "tool-done": 0.85, "error": 0.9}[state]


def draw_frame(t):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    state, into, lines = beat_at(t)
    color = COLORS[state]
    level = brightness(state, into)

    # terminal panel
    d.rounded_rectangle([36, 36, 520, H - 64], radius=10, fill=PANEL,
                        outline=PANEL_EDGE, width=2)
    for i, c in enumerate(((255, 95, 86), (255, 189, 46), (39, 201, 63))):
        d.ellipse([58 + i * 22, 52, 70 + i * 22, 64], fill=c)
    d.text((90 + 3 * 22, 50), "claude code", font=font(13), fill=MUTED)

    mono = font(15)
    y = 84
    for line, st in lines[-12:]:
        col = TEXT if line.startswith(("$", ">")) else MUTED
        if "approval" in line:
            col = COLORS["waiting"]
        d.text((60, y), line[:52], font=mono, fill=col)
        y += 24

    # cursor block
    if int(t * 2) % 2 == 0:
        d.rectangle([60, y + 2, 69, y + 18], fill=(90, 90, 100))

    # bulb: soft glow via blurred circles on an overlay
    cx, cy, r = 700, 190, 46
    glow = Image.new("RGB", (W, H), (0, 0, 0))
    g = ImageDraw.Draw(glow)
    gr = int(r + 90 * level)
    g.ellipse([cx - gr, cy - gr, cx + gr, cy + gr],
              fill=tuple(int(c * 0.55 * level) for c in color))
    glow = glow.filter(ImageFilter.GaussianBlur(38))
    img = Image.composite(Image.blend(img, glow, 0.85), img,
                          glow.convert("L").point(lambda p: min(255, p * 3)))
    d = ImageDraw.Draw(img)

    core = tuple(int(60 + (c - 60) * level) for c in color)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=core)
    hl = int(r * 0.45)
    d.ellipse([cx - hl - 10, cy - hl - 14, cx + hl - 10, cy + hl - 14],
              fill=tuple(min(255, int(c * 1.25 + 40)) for c in core))
    # lamp base
    d.rounded_rectangle([cx - 16, cy + r - 4, cx + 16, cy + r + 26],
                        radius=6, fill=(50, 50, 58))

    # caption
    cap = CAPTIONS[state]
    cf = font(17, bold=True)
    cw = d.textlength(cap, font=cf)
    d.rounded_rectangle([700 - cw / 2 - 16, 300, 700 + cw / 2 + 16, 336],
                        radius=8, fill=(24, 24, 30))
    d.text((700 - cw / 2, 308), cap, font=cf, fill=color)

    d.text((36, H - 44), "claude-glow  -  your room tells you what Claude Code is doing",
           font=font(14), fill=MUTED)
    return img


def main():
    total = sum(d for _, d, _ in SCRIPT)
    n = int(total * FPS)
    shutil.rmtree(FRAMES, ignore_errors=True)
    os.makedirs(FRAMES)
    os.makedirs(OUT, exist_ok=True)
    for i in range(n):
        draw_frame(i / FPS).save(os.path.join(FRAMES, "f_%04d.png" % i))
    print("rendered %d frames (%.1fs at %dfps)" % (n, total, FPS))

    gif = os.path.join(OUT, "demo.gif")
    mp4 = os.path.join(OUT, "demo.mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS),
                    "-i", os.path.join(FRAMES, "f_%04d.png"),
                    "-vf", "split[a][b];[a]palettegen=max_colors=128[p];[b][p]paletteuse=dither=bayer",
                    "-loop", "0", gif], check=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS),
                    "-i", os.path.join(FRAMES, "f_%04d.png"),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "24", mp4],
                   check=True)
    shutil.rmtree(FRAMES, ignore_errors=True)
    for p in (gif, mp4):
        print("%s  %.1f MB" % (p, os.path.getsize(p) / 1e6))


if __name__ == "__main__":
    sys.exit(main())
