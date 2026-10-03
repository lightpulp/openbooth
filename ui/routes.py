from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

from core import CONFIG, PHOTOS, new_session

router = APIRouter()
STATIC = Path(__file__).parent / "static"


@router.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@router.get("/config")
def get_config():
    cam = CONFIG.get("camera", {})
    return {
        "event_text": CONFIG.get("event_text", "Photobooth"),
        "countdown_seconds": int(CONFIG.get("countdown_seconds", 10)),
        "photos": PHOTOS,
        "camera_mode": cam.get("mode", "browser"),
        "browser_device_hint": cam.get("browser_device_hint", ""),
        "printer_mode": CONFIG.get("printer", {}).get("mode", "pdf"),
    }


@router.post("/session")
def create_session():
    return {"session_id": new_session()}
