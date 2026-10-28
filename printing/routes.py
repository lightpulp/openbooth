import os
import subprocess
import sys
import tempfile

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from PIL import Image, ImageDraw

from core import CONFIG, photo_count, print_format, session_dir
from printing.composer import PAPERS, _font, build_sheet

router = APIRouter(prefix="/printing")


def _printer_cfg():
    return CONFIG.get("printer", {})


def _make_dc(name, fmt):
    """Windows: printer device context asking the driver for the chosen paper + orientation.
    Falls back to the driver's saved defaults if the driver refuses."""
    import win32con
    import win32gui
    import win32print
    import win32ui
    w_mm, h_mm, code = PAPERS[fmt["paper"]]
    try:
        h = win32print.OpenPrinter(name)
        try:
            dm = win32print.GetPrinter(h, 2)["pDevMode"]
        finally:
            win32print.ClosePrinter(h)
        if code:
            dm.PaperSize = code
            dm.Fields |= win32con.DM_PAPERSIZE
        else:                                                    # 4x6 / 5x7: custom size in 0.1 mm
            dm.PaperSize = 256
            dm.PaperWidth, dm.PaperLength = round(w_mm * 10), round(h_mm * 10)
            dm.Fields |= win32con.DM_PAPERSIZE | win32con.DM_PAPERWIDTH | win32con.DM_PAPERLENGTH
        dm.Orientation = win32con.DMORIENT_LANDSCAPE if fmt["orientation"] == "landscape" else win32con.DMORIENT_PORTRAIT
        dm.Fields |= win32con.DM_ORIENTATION
        return win32ui.CreateDCFromHandle(win32gui.CreateDC("WINSPOOL", name, dm))
    except Exception as e:
        print(f"[printer] could not set paper/orientation ({e}); using the driver defaults")
        dc = win32ui.CreateDC()
        dc.CreatePrinterDC(name)
        return dc


def _print_windows(sheet, name, copies, fmt):
    try:
        import win32print
        from PIL import ImageWin
    except ImportError:
        raise HTTPException(500, "pywin32 is not installed. Run: pip install pywin32")
    name = name or win32print.GetDefaultPrinter()
    installed = [p[2] for p in win32print.EnumPrinters(2 | 4)]
    if name not in installed:
        raise HTTPException(503, f"Printer '{name}' not found. Installed printers: {installed}")
    try:
        for _ in range(copies):
            dc = _make_dc(name, fmt)
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


def _print_cups(sheet, name, copies, fmt):
    """Mac/Linux: CUPS 'lp'."""
    w, h, _ = PAPERS[fmt["paper"]]
    media = fmt["paper"] if fmt["paper"] in ("A4", "A5", "A6", "Letter") else f"Custom.{w}x{h}mm"
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.close()
    try:
        sheet.save(tmp.name)
        cmd = ["lp", "-n", str(copies), "-o", f"media={media}", "-o", "fit-to-page"]
        if fmt["orientation"] == "landscape":
            cmd += ["-o", "orientation-requested=4"]
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


def send_to_printer(sheet, copies, fmt):
    """Returns True if paper was sent to a printer, False in PDF-only mode."""
    cfg = _printer_cfg()
    mode = cfg.get("mode", "pdf")
    if mode == "pdf":
        return False
    if mode == "epson":
        name = cfg.get("name", "")
        print(f"[printer] sending {fmt['paper']} {fmt['orientation']} sheet to '{name or 'default printer'}' x{copies}")
        (_print_windows if sys.platform == "win32" else _print_cups)(sheet, name, copies, fmt)
        return True
    raise HTTPException(500, f"Unknown printer mode '{mode}' in config.yaml")


@router.post("/finish/{sid}")
def finish(sid: str, print_it: bool = False):
    """Always saves PNG + PDF. Prints the sheet only if print_it is true."""
    d = session_dir(sid)
    paths = [d / f"raw_{i}.jpg" for i in range(1, photo_count() + 1)]
    missing = [p.name for p in paths if not p.exists()]
    if missing:
        raise HTTPException(400, f"Missing photos: {', '.join(missing)}")
    fmt = print_format()
    try:
        sheet = build_sheet(paths, fmt)
        sheet.save(d / "final_sheet.png")
        sheet.save(d / "print.pdf", "PDF", resolution=300.0)       # always saved
    except (ValueError, OSError) as e:
        raise HTTPException(500, f"Could not build the sheet: {e}")

    printed = False
    if print_it:
        try:
            printed = send_to_printer(sheet, int(_printer_cfg().get("copies", 1)), fmt)
        except HTTPException as e:
            raise HTTPException(e.status_code, f"Photos saved, but printing failed: {e.detail}")
    return {"ok": True, "printed": printed, "pdf_url": f"/printing/pdf/{sid}"}


@router.post("/test")
def test_print():
    """Prints a sample sheet (no camera needed). Call it from http://localhost:8000/docs"""
    photos = []
    for i, c in enumerate(["#8ecae6", "#ffb703", "#90be6d", "#f28482"] * 3, 1):
        if i > photo_count():
            break
        im = Image.new("RGB", (1500, 1000), c)
        ImageDraw.Draw(im).text((750, 500), str(i), fill="white", font=_font(400), anchor="mm")
        photos.append(im)
    fmt = print_format()
    try:
        sheet = build_sheet(photos, fmt)
    except ValueError as e:
        raise HTTPException(500, str(e))
    return {"ok": True, "printed": send_to_printer(sheet, 1, fmt)}


@router.get("/pdf/{sid}")
def get_pdf(sid: str):
    p = session_dir(sid) / "print.pdf"
    if not p.exists():
        raise HTTPException(404, "No PDF for this session yet")
    return FileResponse(p, media_type="application/pdf")