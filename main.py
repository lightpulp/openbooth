from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from camera.routes import router as camera_router
from printing.routes import router as printing_router
from ui.routes import router as ui_router

app = FastAPI(title="Photobooth")
app.include_router(ui_router)
app.include_router(camera_router)
app.include_router(printing_router)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "ui" / "static"), name="static")

# Run:  uvicorn main:app --reload      then open http://localhost:8000
