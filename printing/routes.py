import os
import subprocess
import sys
import tempfile
from datetime import datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from PIL import Image, ImageDraw

from core import CONFIG, PHOTOS, session_dir
from printing.composer import _font, build_sheet

router = APIRouter(prefix="/printing")


def _printer_cfg():
    return CONFIG.get("printer", {})


def _date_text():
    d = str(CONFIG.get("event_date", "auto"))
    if d.lower() == "auto":
        now = datetime.now()
        return f"{now:%B} {now.day}, {now.year}"
    return d


def _print_windows(sheet, name, copies):
    """Windows: send the image to the printer through the driver (uses its saved defaults)."""
    try:
        import win32print
        import win32ui
        from PIL import ImageWin
    except ImportError:
        raise HTTPException(500, "pywin32 is not installed. Run: pip install pywin32")
    name = name or win32print.GetDefaultPrinter()
    installed = [p[2] for p in win32print.EnumPrinters(2 | 4)]
    if name not in installed:
        raise HTTPException(503, f"Printer '{name}' not found. Installed printers: {installed}")
    try:
        for _ in range(copies):
            dc = win32ui.CreateDC()
            dc.CreatePrinterDC(name)
            try:
                pw, ph = dc.GetDeviceCaps(8), dc.GetDeviceCaps(10)       # printable width/height
                scale = min(pw / sheet.width, ph / sheet.height)
                w, h = int(sheet.width * scale), int(sheet.height * scale)
                x, y = (pw - w) // 2, (ph - h) // 2
                dc.StartDoc("Photobooth")
                dc.StartPage()
                ImageWin.Dib(sheet).draw(dc.GetHandleOutput(), (x, y, x + w, y + h))
                dc.EndPage()
                dc.EndDoc()
            finally:
                dc.DeleteDC()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(503, f"Printer error: {e}")


def _print_cups(sheet, name, copies):
    """Mac/Linux: CUPS 'lp' command."""
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.close()
    try:
        sheet.save(tmp.name)
        cmd = ["lp", "-n", str(copies), "-o", "media=A4", "-o", "fit-to-page"]
        if name:
            cmd += ["-d", name]
        subprocess.run(cmd + [tmp.name], check=True, capture_output=True, text=True, timeout=30)
    except FileNotFoundError:
        raise HTTPException(503, "'lp' command not found. Is CUPS installed?")
    except subprocess.CalledProcessError as e:
        raise HTTPException(503, f"Printer error: {e.stderr.strip() or e}")
    except subprocess.TimeoutExpired:
        raise HTTPException(503, "Printer did not respond in time.")
    finally:
        os.remove(tmp.name)


def send_to_printer(sheet, copies):
    """Returns True if paper was sent to a printer, False in PDF-only mode."""
    cfg = _printer_cfg()
    mode = cfg.get("mode", "pdf")
    if mode == "pdf":
        return False
    if mode == "epson":
        (_print_windows if sys.platform == "win32" else _print_cups)(sheet, cfg.get("name", ""), copies)
        return True
    raise HTTPException(500, f"Unknown printer mode '{mode}' in config.yaml")


@router.post("/finish/{sid}")
def finish(sid: str, print_it: bool = False):
    """Always saves PNG + PDF. Prints the A4 sheet only if print_it is true."""
    d = session_dir(sid)
    paths = [d / f"raw_{i}.jpg" for i in range(1, PHOTOS + 1)]
    missing = [p.name for p in paths if not p.exists()]
    if missing:
        raise HTTPException(400, f"Missing photos: {', '.join(missing)}")
    try:
        sheet = build_sheet(paths, CONFIG.get("event_text", ""), _date_text(), CONFIG.get("theme"))
        sheet.save(d / "final_a4.png")
        sheet.save(d / "print.pdf", "PDF", resolution=300.0)       # A4, always saved
    except (ValueError, OSError) as e:
        raise HTTPException(500, f"Could not build the sheet: {e}")

    printed = False
    if print_it:
        try:
            printed = send_to_printer(sheet, int(_printer_cfg().get("copies", 1)))
        except HTTPException as e:
            raise HTTPException(e.status_code, f"Photos saved, but printing failed: {e.detail}")
    return {"ok": True, "printed": printed, "pdf_url": f"/printing/pdf/{sid}"}


@router.post("/test")
def test_print():
    """Prints a sample sheet (no camera needed). Call it from http://localhost:8000/docs"""
    photos = []
    for i, c in enumerate(["#8ecae6", "#ffb703", "#90be6d", "#f28482"], 1):
        im = Image.new("RGB", (1500, 1000), c)
        ImageDraw.Draw(im).text((750, 500), str(i), fill="white", font=_font(400), anchor="mm")
        photos.append(im)
    sheet = build_sheet(photos, "TEST PRINT", _date_text(), CONFIG.get("theme"))
    return {"ok": True, "printed": send_to_printer(sheet, 1)}


@router.get("/pdf/{sid}")
def get_pdf(sid: str):
    p = session_dir(sid) / "print.pdf"
    if not p.exists():
        raise HTTPException(404, "No PDF for this session yet")
    return FileResponse(p, media_type="application/pdf")
