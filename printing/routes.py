from datetime import datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from core import CONFIG, PHOTOS, session_dir
from printing.composer import build_sheet

router = APIRouter(prefix="/printing")


def send_to_printer(sheet, out_dir, copies):
    """The one place that changes when the Epson arrives."""
    mode = CONFIG.get("printer", {}).get("mode", "pdf")
    if mode == "pdf":
        try:   # 300 DPI -> exactly 4x6 in; one page per copy
            sheet.save(out_dir / "print.pdf", "PDF", resolution=300.0, save_all=True,
                       append_images=[sheet] * (max(copies, 1) - 1))
        except OSError as e:
            raise HTTPException(503, f"Could not write PDF: {e}")
        return {"pdf_url": f"/printing/pdf/{out_dir.name}"}
    # Later:  if mode == "epson":  ...send sheet to the printer here...
    raise HTTPException(500, f"Unknown printer mode '{mode}' in config.yaml")


@router.post("/print/{sid}")
def print_session(sid: str):
    d = session_dir(sid)
    paths = [d / f"raw_{i}.jpg" for i in range(1, PHOTOS + 1)]
    missing = [p.name for p in paths if not p.exists()]
    if missing:
        raise HTTPException(400, f"Missing photos: {', '.join(missing)}")

    date_text = str(CONFIG.get("event_date", "auto"))
    if date_text.lower() == "auto":
        now = datetime.now()
        date_text = f"{now:%B} {now.day}, {now.year}"
    try:
        sheet = build_sheet(paths, CONFIG.get("event_text", ""), date_text)
    except ValueError as e:
        raise HTTPException(500, str(e))
    sheet.save(d / "final_4x6.png")
    result = send_to_printer(sheet, d, int(CONFIG.get("printer", {}).get("copies", 1)))
    return {"ok": True, **result}


@router.get("/pdf/{sid}")
def get_pdf(sid: str):
    p = session_dir(sid) / "print.pdf"
    if not p.exists():
        raise HTTPException(404, "No PDF for this session yet")
    return FileResponse(p, media_type="application/pdf")
