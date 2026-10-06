"""4 photos + your frame (printing/frame.png) -> one strip -> duplicated on an A4 sheet.
A4 @ 300 DPI = 2480x3508 px. Cut the printed sheet down the middle -> 2 identical strips.

frame.png rules (the file can be any size, e.g. a full A4 page with the strip on it):
  - the strip is found automatically (everything that isn't fully transparent is the strip)
  - the 4 photo windows must be FULLY TRANSPARENT holes; photos are placed behind the frame
  - stickers/characters that overlap a window stay on top of the photo (they must be opaque)
  - text, date and credits are baked into the PNG (config.yaml event_text / theme are not used for drawing)
"""
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

W, H = 2480, 3508
STRIP_W = W // 2                        # 1240
SAFE = 50                               # L3250 leaves ~3 mm (35 px) unprintable on A4
PHOTOS = 4
PAD = 4                                 # photo extends 4 px under the frame so no white gap shows
FRAME_PATH = Path(__file__).parent / "frame.png"


def _font(size):
    for name in ("arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf", "Helvetica.ttc"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default(size=size)


@lru_cache(maxsize=2)
def _prepare(mtime):
    """Crop the strip out of frame.png, scale it to fit half of the A4 sheet, find the 4 windows.
    Cached per file-modified-time, so editing frame.png is picked up without restarting."""
    frame = Image.open(FRAME_PATH).convert("RGBA")
    box = frame.getchannel("A").point(lambda p: 255 if p > 0 else 0).getbbox()
    if box is None:
        raise ValueError("frame.png is completely transparent")
    frame = frame.crop(box)
    scale = min((STRIP_W - 2 * SAFE) / frame.width, (H - 2 * SAFE) / frame.height)
    frame = frame.resize((round(frame.width * scale), round(frame.height * scale)), Image.LANCZOS)

    hole = (np.array(frame.getchannel("A")) < 128).astype(np.uint8)
    _, _, stats, _ = cv2.connectedComponentsWithStats(hole, connectivity=4)
    min_area = 0.01 * frame.width * frame.height
    windows = [(int(x), int(y), int(w), int(h)) for x, y, w, h, area in stats[1:]
               if area >= min_area and x > 0 and y > 0 and x + w < frame.width and y + h < frame.height]
    windows.sort(key=lambda b: b[1])                              # top to bottom = photo 1..4
    if len(windows) != PHOTOS:
        raise ValueError(f"frame.png needs exactly {PHOTOS} transparent photo windows, found {len(windows)}")
    return frame, windows


def build_sheet(photos, text="", date_text="", theme=None):
    """photos: 4 file paths or PIL images. text/date_text/theme are unused (baked into frame.png).
    Returns the A4 sheet as a PIL image."""
    imgs = []
    for p in photos:
        try:
            imgs.append(p.convert("RGB") if isinstance(p, Image.Image) else Image.open(p).convert("RGB"))
        except OSError as e:
            raise ValueError(f"Can't read photo {p}: {e}")
    if len(imgs) != PHOTOS:
        raise ValueError(f"Expected {PHOTOS} photos, got {len(imgs)}")
    try:
        frame, windows = _prepare(FRAME_PATH.stat().st_mtime)
    except FileNotFoundError:
        raise ValueError(f"Frame not found: {FRAME_PATH}")
    except OSError as e:
        raise ValueError(f"Can't read frame.png: {e}")

    layer = Image.new("RGBA", frame.size, "white")                # photos go BEHIND the frame
    for img, (x, y, w, h) in zip(imgs, windows):
        x0, y0 = max(x - PAD, 0), max(y - PAD, 0)
        x1, y1 = min(x + w + PAD, frame.width), min(y + h + PAD, frame.height)
        layer.paste(ImageOps.fit(img, (x1 - x0, y1 - y0), Image.LANCZOS), (x0, y0))   # center-crop, no stretching
    strip = Image.alpha_composite(layer, frame).convert("RGB")

    sheet = Image.new("RGB", (W, H), "white")
    ox, oy = (STRIP_W - strip.width) // 2, (H - strip.height) // 2
    sheet.paste(strip, (ox, oy))
    sheet.paste(strip, (STRIP_W + ox, oy))
    d = ImageDraw.Draw(sheet)
    for y in range(0, H, 40):                                     # dashed cut guide in the gutter
        d.line([(STRIP_W, y), (STRIP_W, y + 20)], fill=(185, 185, 185), width=2)
    return sheet