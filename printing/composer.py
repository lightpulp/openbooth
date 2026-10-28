"""Builds the printable sheet: your frame PNG + photos, repeated `strips` times on the chosen paper.

Frame PNG rules (any size, e.g. a full-page canvas with ONE strip on it):
  - the strip is everything that isn't fully transparent
  - every photo window is a FULLY TRANSPARENT hole (photos go behind the frame)
  - stickers overlapping a window must be opaque (they stay on top of the photo)
  - number of windows = number of photos per session
"""
import math
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

DPI = 300
SAFE = 50       # px kept free around every strip (printers can't print the very edge)
PAD = 4         # photo extends 4 px under the frame so no white gap shows
# name: (width_mm, height_mm, Windows DMPAPER code or None) - portrait sizes
PAPERS = {"A4": (210, 297, 9), "A5": (148, 210, 11), "A6": (105, 148, 70),
          "Letter": (215.9, 279.4, 1), "4x6": (101.6, 152.4, None), "5x7": (127, 177.8, None)}


def _font(size):
    for name in ("arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf", "Helvetica.ttc"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default(size=size)


def sheet_size(paper, orientation):
    """Sheet size in pixels at 300 DPI."""
    if paper not in PAPERS:
        raise ValueError(f"Unknown paper size '{paper}'. Choose from: {', '.join(PAPERS)}")
    w, h = (round(mm / 25.4 * DPI) for mm in PAPERS[paper][:2])
    if orientation == "landscape":
        return h, w
    if orientation == "portrait":
        return w, h
    raise ValueError("Orientation must be 'portrait' or 'landscape'")


@lru_cache(maxsize=4)
def _base(path, mtime):
    """Load the frame, crop to the strip, find the photo windows (ordered rows top->bottom, left->right)."""
    try:
        frame = Image.open(path).convert("RGBA")
    except FileNotFoundError:
        raise ValueError(f"Frame not found: {path}")
    except OSError as e:
        raise ValueError(f"Can't read frame {Path(path).name}: {e}")
    box = frame.getchannel("A").point(lambda p: 255 if p > 0 else 0).getbbox()
    if box is None:
        raise ValueError(f"{Path(path).name} is completely transparent")
    frame = frame.crop(box)
    hole = (np.array(frame.getchannel("A")) < 128).astype(np.uint8)
    _, _, stats, _ = cv2.connectedComponentsWithStats(hole, connectivity=4)
    min_area = 0.01 * frame.width * frame.height
    wins = [(int(x), int(y), int(w), int(h)) for x, y, w, h, a in stats[1:]
            if a >= min_area and x > 0 and y > 0 and x + w < frame.width and y + h < frame.height]
    if not wins:
        raise ValueError(f"{Path(path).name} has no transparent photo windows")
    wins.sort(key=lambda b: b[1] + b[3] / 2)
    row_gap, rows, cur = 0.5 * min(b[3] for b in wins), [], [wins[0]]
    for b in wins[1:]:
        if (b[1] + b[3] / 2) - (cur[0][1] + cur[0][3] / 2) > row_gap:
            rows.append(cur)
            cur = [b]
        else:
            cur.append(b)
    rows.append(cur)
    return frame, [b for r in rows for b in sorted(r, key=lambda b: b[0])]


def count_windows(path):
    """How many photos this frame needs."""
    path = str(path)
    try:
        mtime = Path(path).stat().st_mtime_ns
    except OSError:
        raise ValueError(f"Frame not found: {path}")
    return len(_base(path, mtime)[1])


@lru_cache(maxsize=4)
def _scaled(path, mtime, W, H, strips):
    """Pick the grid (columns x rows) that makes the strips biggest, then scale the frame to fit one cell."""
    frame, windows = _base(path, mtime)
    best = None
    for cols in range(1, strips + 1):
        rows = -(-strips // cols)
        s = min((W / cols - 2 * SAFE) / frame.width, (H / rows - 2 * SAFE) / frame.height)
        if best is None or s > best[0] * 1.0001:
            best = (s, cols, rows)
    s, cols, rows = best
    if s <= 0:
        raise ValueError("Too many strips for this paper size")
    size = (max(1, round(frame.width * s)), max(1, round(frame.height * s)))
    strip = frame.resize(size, Image.LANCZOS)
    sx, sy = size[0] / frame.width, size[1] / frame.height
    wins = [(math.floor(x * sx), math.floor(y * sy), math.ceil((x + w) * sx), math.ceil((y + h) * sy))
            for x, y, w, h in windows]
    return strip, wins, cols, rows


def build_sheet(photos, fmt):
    """photos: file paths or PIL images (one per frame window).
    fmt: {"frame": Path, "paper": "A4", "orientation": "portrait", "strips": 2}. Returns a PIL image."""
    W, H = sheet_size(fmt["paper"], fmt["orientation"])
    strips = int(fmt["strips"])
    if not 1 <= strips <= 8:
        raise ValueError("Strips must be between 1 and 8")
    path = str(fmt["frame"])
    try:
        mtime = Path(path).stat().st_mtime_ns
    except OSError:
        raise ValueError(f"Frame not found: {path}")
    strip, wins, cols, rows = _scaled(path, mtime, W, H, strips)

    imgs = []
    for p in photos:
        try:
            imgs.append(p.convert("RGB") if isinstance(p, Image.Image) else Image.open(p).convert("RGB"))
        except OSError as e:
            raise ValueError(f"Can't read photo {p}: {e}")
    if len(imgs) != len(wins):
        raise ValueError(f"This frame has {len(wins)} photo windows but {len(imgs)} photos were given")

    layer = Image.new("RGBA", strip.size, "white")                # photos go BEHIND the frame
    for img, (x0, y0, x1, y1) in zip(imgs, wins):
        x0, y0 = max(x0 - PAD, 0), max(y0 - PAD, 0)
        x1, y1 = min(x1 + PAD, strip.width), min(y1 + PAD, strip.height)
        layer.paste(ImageOps.fit(img, (x1 - x0, y1 - y0), Image.LANCZOS), (x0, y0))   # center-crop, no stretching
    one = Image.alpha_composite(layer, strip).convert("RGB")

    sheet = Image.new("RGB", (W, H), "white")
    cw, ch = W // cols, H // rows
    for i in range(strips):
        r, c = divmod(i, cols)
        sheet.paste(one, (c * cw + (cw - one.width) // 2, r * ch + (ch - one.height) // 2))
    d = ImageDraw.Draw(sheet)                                     # dashed cut guides between strips
    for c in range(1, cols):
        for y in range(0, H, 40):
            d.line([(c * cw, y), (c * cw, y + 20)], fill=(185, 185, 185), width=2)
    for r in range(1, rows):
        for x in range(0, W, 40):
            d.line([(x, r * ch), (x + 20, r * ch)], fill=(185, 185, 185), width=2)
    return sheet