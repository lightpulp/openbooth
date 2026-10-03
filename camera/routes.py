from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from camera.opencv_cam import CameraError, OpenCVCamera
from core import CONFIG, check_index, save_photo, session_dir

router = APIRouter(prefix="/camera")
_camera = None


def get_camera():
    """Server-side camera. Swap/extend here when you add another camera type."""
    global _camera
    cfg = CONFIG.get("camera", {})
    if cfg.get("mode", "browser") != "opencv":
        raise HTTPException(400, "Server camera is off (camera.mode is 'browser').")
    if _camera is None:
        _camera = OpenCVCamera(int(cfg.get("index", 0)))
    return _camera


# browser mode: the page grabs the frame and uploads it
@router.post("/upload/{sid}/{n}")
async def upload(sid: str, n: int, file: UploadFile = File(...)):
    save_photo(sid, n, await file.read())
    return {"ok": True}


# opencv mode: Python grabs the frame
@router.post("/capture/{sid}/{n}")
def capture(sid: str, n: int):
    session_dir(sid)
    check_index(n)
    try:
        data = get_camera().capture()
    except CameraError as e:
        raise HTTPException(503, str(e))
    save_photo(sid, n, data)
    return {"ok": True}


# opencv mode: live preview
@router.get("/stream")
def stream():
    return StreamingResponse(get_camera().stream(),
                             media_type="multipart/x-mixed-replace; boundary=frame")


# thumbnails
@router.get("/photo/{sid}/{n}")
def photo(sid: str, n: int):
    check_index(n)
    p = session_dir(sid) / f"raw_{n}.jpg"
    if not p.exists():
        raise HTTPException(404, "Photo not found")
    return FileResponse(p)
