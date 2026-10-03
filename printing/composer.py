"""4 photos + text -> 2x6 strip -> duplicated onto a 4x6 sheet (300 DPI = 1200x1800 px)."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

W, H = 1200, 1800
STRIP_W = W // 2
MARGIN, GAP = 30, 20
PHOTO_W = STRIP_W - 2 * MARGIN      # 540
PHOTO_H = PHOTO_W * 2 // 3          # 360 (3:2 landscape)


def _font(size):
    for name in ("arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf", "Helvetica.ttc"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default(size=size)


def _centered(draw, text, cx, y, size):
    font = _font(size)
    while draw.textlength(text, font=font) > PHOTO_W and size > 14:   # shrink to fit
        size -= 2
        font = _font(size)
    draw.text((cx, y), text, font=font, fill="black", anchor="mt")


def build_sheet(photo_paths, text, date_text):
    strip = Image.new("RGB", (STRIP_W, H), "white")
    draw = ImageDraw.Draw(strip)
    y = MARGIN
    for p in photo_paths:
        try:
            img = Image.open(p).convert("RGB")
        except OSError as e:
            raise ValueError(f"Can't read {Path(p).name}: {e}")
        strip.paste(ImageOps.fit(img, (PHOTO_W, PHOTO_H), Image.LANCZOS), (MARGIN, y))
        y += PHOTO_H + GAP
    _centered(draw, text, STRIP_W // 2, y + 10, 56)
    _centered(draw, date_text, STRIP_W // 2, y + 110, 40)

    sheet = Image.new("RGB", (W, H), "white")
    sheet.paste(strip, (0, 0))
    sheet.paste(strip, (STRIP_W, 0))
    ImageDraw.Draw(sheet).line([(STRIP_W, 0), (STRIP_W, H)], fill=(200, 200, 200), width=2)  # cut guide
    return sheet
