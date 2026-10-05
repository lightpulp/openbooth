"""4 photos + frame -> one strip -> duplicated side by side on an A4 sheet.
A4 @ 300 DPI = 2480x3508 px. Cut the printed sheet down the middle -> 2 identical strips."""
import math
import random

from PIL import Image, ImageDraw, ImageFont, ImageOps

W, H = 2480, 3508
STRIP_W = W // 2                        # 1240
SAFE = 50                               # L3250 leaves ~3 mm (35 px) unprintable on A4
PHOTO_W, PHOTO_H, GAP = 960, 640, 50    # 3:2 landscape
PHOTO_X = (STRIP_W - PHOTO_W) // 2
PHOTO_Y0 = 170
DEFAULT_THEME = {"background": "#FFF4D6", "border": "#1D4E89", "accent": "#E4572E",
                 "dots": ["#F7B32B", "#E4572E", "#2A9D8F", "#1D4E89", "#EF476F"]}


def _font(size):
    for name in ("arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf", "Helvetica.ttc"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default(size=size)


def _text(d, text, cx, cy, size, fill, max_w=PHOTO_W - 60):
    font = _font(size)
    while d.textlength(text, font=font) > max_w and size > 14:   # shrink to fit
        size -= 2
        font = _font(size)
    d.text((cx, cy), text, font=font, fill=fill, anchor="mm")


# ---- small decorations ----
def star(d, cx, cy, r, fill):
    pts = [(cx + (r if i % 2 == 0 else r * .42) * math.sin(i * math.pi / 5),
            cy - (r if i % 2 == 0 else r * .42) * math.cos(i * math.pi / 5)) for i in range(10)]
    d.polygon(pts, fill=fill)


def heart(d, cx, cy, r, fill):
    d.ellipse((cx - r, cy - r, cx, cy), fill=fill)
    d.ellipse((cx, cy - r, cx + r, cy), fill=fill)
    d.polygon([(cx - r * .95, cy - r * .3), (cx + r * .95, cy - r * .3), (cx, cy + r)], fill=fill)


def apple(d, cx, cy, r):
    red = "#D62828"
    d.ellipse((cx - r, cy - r * .8, cx + r * .1, cy + r), fill=red)
    d.ellipse((cx - r * .1, cy - r * .8, cx + r, cy + r), fill=red)
    d.line((cx, cy - r * .7, cx + r * .1, cy - r * 1.3), fill="#6B4226", width=max(int(r * .12), 2))
    d.ellipse((cx + r * .1, cy - r * 1.3, cx + r * .75, cy - r * .95), fill="#2D9A4B")


def _strip(photos, text, date_text, theme):
    bg, border, accent, dots = theme["background"], theme["border"], theme["accent"], theme["dots"]
    strip = Image.new("RGB", (STRIP_W, H), "white")
    d = ImageDraw.Draw(strip)
    d.rounded_rectangle((SAFE, SAFE, STRIP_W - SAFE, H - SAFE), radius=60, fill=bg, outline=border, width=14)

    rnd = random.Random(7)                                    # confetti in the side gutters
    for _ in range(50):
        x = rnd.choice([rnd.randint(78, 108), rnd.randint(1132, 1162)])
        r = rnd.randint(6, 12)
        y = rnd.randint(160, 2900)
        d.ellipse((x - r, y - r, x + r, y + r), fill=rnd.choice(dots))
    for i, x in enumerate(range(200, 1060, 110)):             # top garland
        (star if i % 2 == 0 else heart)(d, x, 112, 26, dots[i % len(dots)])

    y = PHOTO_Y0
    for i, img in enumerate(photos):
        d.rounded_rectangle((PHOTO_X - 6, y - 6, PHOTO_X + PHOTO_W + 22, y + PHOTO_H + 22), radius=18, fill="#D9CFB8")  # soft shadow
        d.rounded_rectangle((PHOTO_X - 14, y - 14, PHOTO_X + PHOTO_W + 14, y + PHOTO_H + 14), radius=18, fill="white")
        strip.paste(ImageOps.fit(img, (PHOTO_W, PHOTO_H), Image.LANCZOS), (PHOTO_X, y))
        if i % 2 == 0:
            star(d, PHOTO_X + 10, y + 5, 52, dots[i % len(dots)])
        else:
            heart(d, PHOTO_X + PHOTO_W - 5, y + 5, 46, dots[(i + 2) % len(dots)])
        y += PHOTO_H + GAP

    d.rounded_rectangle((PHOTO_X, 2930, PHOTO_X + PHOTO_W, 3070), radius=40, fill=accent)   # ribbon
    _text(d, text, STRIP_W // 2, 3000, 90, "white")
    _text(d, date_text, STRIP_W // 2, 3130, 56, border)
    for i, x in enumerate((230, 430, 620, 810, 1010)):                                      # bottom row
        cy = 3290
        if i == 2:
            apple(d, x, cy, 55)
        else:
            (star if i in (0, 4) else heart)(d, x, cy, 42, dots[i % len(dots)])
    return strip


def build_sheet(photos, text, date_text, theme=None):
    """photos: 4 file paths or PIL images. Returns the A4 sheet as a PIL image."""
    imgs = []
    for p in photos:
        try:
            imgs.append(p.convert("RGB") if isinstance(p, Image.Image) else Image.open(p).convert("RGB"))
        except OSError as e:
            raise ValueError(f"Can't read photo {p}: {e}")
    strip = _strip(imgs, text, date_text, {**DEFAULT_THEME, **(theme or {})})
    sheet = Image.new("RGB", (W, H), "white")
    sheet.paste(strip, (0, 0))
    sheet.paste(strip, (STRIP_W, 0))
    d = ImageDraw.Draw(sheet)
    for y in range(0, H, 40):                                 # dashed cut guide
        d.line([(STRIP_W, y), (STRIP_W, y + 20)], fill=(185, 185, 185), width=2)
    return sheet
