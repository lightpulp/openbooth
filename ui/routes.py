import hashlib
import json
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

from core import CONFIG, frame_path, new_session, photo_count

router = APIRouter()
STATIC = Path(__file__).parent / "static"


def _version():
    """Changes whenever the settings or the frame change, so open pages know to reload."""
    raw = json.dumps(CONFIG, sort_keys=True, default=str) + str(frame_path().stat().st_mtime_ns)
    return hashlib.md5(raw.encode()).hexdigest()[:10]


@router.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@router.get("/config")
def get_config():
    cam = CONFIG.get("camera", {})
    return {
        "event_text": CONFIG.get("event_text", "Photobooth"),
        "countdown_seconds": int(CONFIG.get("countdown_seconds", 10)),
        "photos": photo_count(),                       # = number of windows in the chosen frame
        "camera_mode": cam.get("mode", "browser"),
        "browser_device_hint": cam.get("browser_device_hint", ""),
        "printer_mode": CONFIG.get("printer", {}).get("mode", "pdf"),
        "version": _version(),
    }


@router.post("/session")
def create_session():
    return {"session_id": new_session()}