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
    path = d / f"raw_{n}.jpg"
    img.save(path, quality=95)
    return path
