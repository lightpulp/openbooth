"""Shared config + session helpers used by all three parts."""
import io
import re
import uuid
from datetime import datetime
from pathlib import Path

import yaml
from fastapi import HTTPException
from PIL import Image, UnidentifiedImageError

ROOT = Path(__file__).parent
SESSIONS_DIR = ROOT / "sessions"
SESSIONS_DIR.mkdir(exist_ok=True)
PHOTOS = 4
MAX_UPLOAD = 15 * 1024 * 1024
_SID = re.compile(r"^\d{8}_[0-9a-f]{8}$")

# --- black-border trimming (cameras / webcam apps that letterbox or pillarbox the video) ---
TRIM_BLACK = True       # set False to keep frames exactly as the camera sent them
BLACK_LEVEL = 20        # a row/column counts as "black bar" if its average brightness (0-255) is below this
TRIM_EXTRA = 6          # also cut this many px inside the bar edge, to remove soft/blurry bar edges


def load_config() -> dict:
    try:
        with open(ROOT / "config.yaml", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        raise RuntimeError("config.yaml not found next to main.py")
    except yaml.YAMLError as e:
        raise RuntimeError(f"config.yaml is invalid: {e}")


CONFIG = load_config()


def new_session() -> str:
    sid = f"{datetime.now():%Y%m%d}_{uuid.uuid4().hex[:8]}"
    (SESSIONS_DIR / sid).mkdir(parents=True)
    return sid


def session_dir(sid: str) -> Path:
    if not _SID.match(sid):
        raise HTTPException(400, "Invalid session id")
    d = SESSIONS_DIR / sid
    if not d.is_dir():
        raise HTTPException(404, "Session not found. Please start again.")
    return d


def check_index(n: int) -> None:
    if not 1 <= n <= PHOTOS:
        raise HTTPException(400, f"Photo number must be 1-{PHOTOS}")


def _content_range(profile: Image.Image, length: int):
    """profile is a 1-pixel-wide/tall image of average brightness per row/column.
    Returns (start, end) of the part that is brighter than BLACK_LEVEL, or None if all black."""
    mask = profile.point(lambda p: 255 if p > BLACK_LEVEL else 0)
    box = mask.getbbox()
    if box is None:
        return None
    return (box[1], box[3]) if profile.size[0] == 1 else (box[0], box[2])


def trim_black_borders(img: Image.Image) -> Image.Image:
    """Cut away solid black bars around the picture (top/bottom/left/right).
    Averaging whole rows/columns means a few noisy pixels in a bar can't fool it,
    and a dark subject in the middle of the frame is never cut."""
    w, h = img.size
    gray = img.convert("L")
    rows = _content_range(gray.resize((1, h), Image.BOX), h)    # average brightness of every row
    cols = _content_range(gray.resize((w, 1), Image.BOX), w)    # average brightness of every column
    if rows is None or cols is None:
        return img                                              # fully dark frame: leave untouched
    top, bottom = rows
    left, right = cols
    if top > 0:
        top += TRIM_EXTRA
    if left > 0:
        left += TRIM_EXTRA
    if bottom < h:
        bottom -= TRIM_EXTRA
    if right < w:
        right -= TRIM_EXTRA
    # nothing worth cutting, or the cut would remove most of the picture -> keep the original
    if (top, left, bottom, right) == (0, 0, h, w):
        return img
    if (right - left) < w * 0.5 or (bottom - top) < h * 0.5:
        return img
    return img.crop((left, top, right, bottom))


def save_photo(sid: str, n: int, data: bytes) -> Path:
    """Validate image bytes and store as sessions/<sid>/raw_<n>.jpg."""
    d = session_dir(sid)
    check_index(n)
    if not data:
        raise HTTPException(400, "Empty image received")
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "Image too large")
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
        img = img.convert("RGB")
    except (UnidentifiedImageError, OSError):
        raise HTTPException(400, "File is not a valid image")
    if TRIM_BLACK:
        img = trim_black_borders(img)
    path = d / f"raw_{n}.jpg"
    img.save(path, quality=95)
    return path