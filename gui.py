"""Photobooth launcher: Tkinter GUI + embedded FastAPI/Uvicorn server.

Place this file in the project root beside main.py, core.py, config.yaml,
and the ui/, camera/, and printing/ folders.

Development: python gui.py
Packaging: build this file with PyInstaller from the project root.
Frames (PNG) live in the 'frames' folder beside gui.py / the EXE.
"""
import importlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import yaml

PORT = 8000
URL = f"http://localhost:{PORT}"
DEFAULT_PRINTER = "(default printer)"
DEFAULT_CAMERA = "(browser default)"
PAPERS = ("A4", "A5", "A6", "Letter", "4x6", "5x7")      # keep in sync with printing/composer.py
FROZEN = bool(getattr(sys, "frozen", False))

# Writable files live beside gui.py in development, or beside the EXE when frozen.
APP_DIR = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent
# PyInstaller's temporary extraction folder contains bundled read-only assets.
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))
CONFIG_PATH = APP_DIR / "config.yaml"
FRAMES_DIR = APP_DIR / "frames"
CAMERAS_PATH = APP_DIR / "cameras.json"      # written by the booth page: cameras the browser can see

if not FROZEN:
    sys.path.insert(0, str(APP_DIR))


def load_cfg():
    """Load writable config beside the EXE/script, creating it from bundled defaults."""
    if not CONFIG_PATH.exists():
        bundled_config = BUNDLE_DIR / "config.yaml"
        if bundled_config.exists():
            shutil.copy2(bundled_config, CONFIG_PATH)
        else:
            CONFIG_PATH.write_text("{}\n", encoding="utf-8")
    with CONFIG_PATH.open(encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    if not isinstance(cfg, dict):
        raise ValueError("config.yaml must contain a YAML mapping/object.")
    return cfg


def save_cfg(cfg):
    temp_path = CONFIG_PATH.with_suffix(".tmp")
    with temp_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, sort_keys=False, allow_unicode=True)
    os.replace(temp_path, CONFIG_PATH)


def seed_frames():
    """Make sure frames/ exists and has at least the bundled default frame."""
    FRAMES_DIR.mkdir(parents=True, exist_ok=True)
    if not any(FRAMES_DIR.glob("*.png")):
        for src in (BUNDLE_DIR / "printing" / "frame.png", APP_DIR / "printing" / "frame.png"):
            if src.exists():
                shutil.copy2(src, FRAMES_DIR / "default.png")
                break


def read_cameras():
    try:
        return [str(x) for x in json.loads(CAMERAS_PATH.read_text(encoding="utf-8"))]
    except Exception:
        return []


def list_printers():
    try:
        if sys.platform == "win32":
            import win32print
            flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
            return sorted({item[2] for item in win32print.EnumPrinters(flags)})
        result = subprocess.run(
            ["lpstat", "-e"], capture_output=True, text=True, timeout=5, check=False
        )
        return sorted(line.strip() for line in result.stdout.splitlines() if line.strip())
    except Exception:
        return []


def open_path(path):
    path = str(path)
    if sys.platform == "win32":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def configure_core_paths(core):
    """Make core use persistent files beside the launcher, including in a frozen EXE."""
    core.ROOT = APP_DIR
    core.SESSIONS_DIR = APP_DIR / "sessions"
    core.SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    core.FRAMES_DIR = FRAMES_DIR
    FRAMES_DIR.mkdir(parents=True, exist_ok=True)
    # core.py loads CONFIG at import time; reload it from the persistent config path.
    core.CONFIG = core.load_config()


def reload_project_modules():
    """Reload config-dependent modules after stopping Uvicorn."""
    importlib.invalidate_caches()

    if "core" not in sys.modules:
        import core
        configure_core_paths(core)
        return

    import core
    importlib.reload(core)
    configure_core_paths(core)

    # Reload route modules after core so their `from core import ...` references refresh.
    for name in (
        "camera.opencv_cam",
        "camera.routes",
        "printing.composer",
        "printing.routes",
        "ui.routes",
    ):
        if name in sys.modules:
            importlib.reload(sys.modules[name])
        else:
            importlib.import_module(name)

    if "main" in sys.modules:
        importlib.reload(sys.modules["main"])
    else:
        importlib.import_module("main")


class Server:
    """Runs Uvicorn in a background thread; the Tkinter GUI stays responsive."""

    def __init__(self):
        self.srv = None
        self.thread = None

    def start(self):
        try:
            # Configure persistent paths/config before importing route modules.
            if "core" in sys.modules:
                reload_project_modules()
            else:
                import core
                configure_core_paths(core)
                for module_name in (
                    "camera.opencv_cam",
                    "camera.routes",
                    "printing.composer",
                    "printing.routes",
                    "ui.routes",
                    "main",
                ):
                    importlib.import_module(module_name)

            import uvicorn
            app = sys.modules["main"].app
            config = uvicorn.Config(
                app,
                host="127.0.0.1",
                port=PORT,
                log_config=None,
                loop="asyncio",
                http="h11",
                ws="none",
            )
            self.srv = uvicorn.Server(config)
            self.thread = threading.Thread(target=self.srv.run, daemon=True)
            self.thread.start()

            for _ in range(60):
                if self.srv.started:
                    return None
                if not self.thread.is_alive():
                    break
                time.sleep(0.1)
            return f"Server did not start. Is port {PORT} already in use?"
        except Exception as exc:
            return f"Server did not start: {exc}"

    def stop(self):
        if self.srv:
            self.srv.should_exit = True
        if self.thread:
            self.thread.join(timeout=5)
        self.srv = None
        self.thread = None

    def restart(self):
        self.stop()
        return self.start()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Photobooth")
        self.resizable(False, False)
        self.server = Server()
        try:
            self.cfg = load_cfg()
        except Exception as exc:
            messagebox.showerror("Configuration error", str(exc))
            self.destroy()
            raise
        seed_frames()
        self._build()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(300, self.restart)
        self.after(3000, self.poll_cameras)

    # ---------- layout helpers ----------
    def _box(self, title, row):
        box = ttk.LabelFrame(self, text=title)
        box.grid(row=row, column=0, sticky="ew", padx=10, pady=4)
        box.columnconfigure(1, weight=1)
        return box

    def _row(self, box, r, text, widget, *buttons):
        ttk.Label(box, text=text).grid(row=r, column=0, sticky="w", padx=8, pady=3)
        widget.grid(row=r, column=1, sticky="ew", padx=4)
        for i, (label, command) in enumerate(buttons):
            ttk.Button(box, text=label, command=command).grid(
                row=r, column=2 + i, padx=(2, 8 if i == len(buttons) - 1 else 2)
            )

    def _build(self):
        cam = self.cfg.get("camera") or {}
        lay = self.cfg.get("layout") or {}
        pr = self.cfg.get("printer") or {}
        self.camera = tk.StringVar(value=cam.get("browser_device_hint") or DEFAULT_CAMERA)
        self.frame = tk.StringVar(value=str(lay.get("frame", "default.png")))
        self.paper = tk.StringVar(value=str(lay.get("paper", "A4")))
        self.orient = tk.StringVar(value=str(lay.get("orientation", "portrait")))
        self.strips = tk.StringVar(value=str(lay.get("strips", 2)))
        self.mode = tk.StringVar(value=pr.get("mode", "pdf"))
        self.printer = tk.StringVar(value=pr.get("name") or DEFAULT_PRINTER)
        self.copies = tk.StringVar(value=str(pr.get("copies", 1)))
        self.countdown = tk.StringVar(value=str(self.cfg.get("countdown_seconds", 10)))
        self.info = tk.StringVar()
        self.sessions_dir = APP_DIR / "sessions"

        # --- server ---
        box = self._box("Server", 0)
        self.status = tk.Label(box, text="Starting...", anchor="w", fg="orange")
        self.status.grid(row=0, column=0, columnspan=4, sticky="w", padx=8, pady=(6, 2))
        url_entry = ttk.Entry(box, width=36)
        url_entry.insert(0, URL)
        url_entry.configure(state="readonly")
        self._row(box, 1, "Address", url_entry,
                  ("Open", lambda: webbrowser.open(URL)), ("Copy", self.copy_url))
        ttk.Button(box, text="Refresh server", command=self.restart).grid(
            row=2, column=0, columnspan=4, sticky="ew", padx=8, pady=(4, 8))

        # --- camera ---
        box = self._box("Camera", 1)
        self.camera_box = ttk.Combobox(box, textvariable=self.camera, state="readonly", width=34)
        self._row(box, 0, "Camera", self.camera_box, ("Rescan", self.refresh_cameras))
        tk.Label(box, fg="gray", anchor="w", justify="left", wraplength=440,
                 text="Cameras appear here after the booth page has been opened once and the "
                      "browser camera permission was allowed. The page switches to the chosen camera automatically."
                 ).grid(row=1, column=0, columnspan=4, sticky="w", padx=8, pady=(0, 6))

        # --- frame & layout ---
        box = self._box("Frame & layout", 2)
        self.frame_box = ttk.Combobox(box, textvariable=self.frame, state="readonly", width=34)
        self.frame_box.bind("<<ComboboxSelected>>", lambda e: self.update_info())
        self._row(box, 0, "Frame (PNG)", self.frame_box,
                  ("Upload...", self.upload_frame), ("Folder", lambda: self.open_dir(FRAMES_DIR)))
        tk.Label(box, textvariable=self.info, fg="gray", anchor="w", justify="left", wraplength=440
                 ).grid(row=1, column=0, columnspan=4, sticky="w", padx=8)
        self._row(box, 2, "Paper size", ttk.Combobox(box, textvariable=self.paper, values=PAPERS,
                                                    state="readonly", width=14))
        self._row(box, 3, "Orientation", ttk.Combobox(box, textvariable=self.orient,
                                                     values=("portrait", "landscape"), state="readonly", width=14))
        self._row(box, 4, "Strips per sheet", ttk.Spinbox(box, from_=1, to=8, textvariable=self.strips, width=6),
                  ("Preview layout", self.preview))

        # --- printing + session ---
        box = self._box("Printing & session", 3)
        self._row(box, 0, "Print mode", ttk.Combobox(box, textvariable=self.mode, values=("pdf", "epson"),
                                                    state="readonly", width=14))
        self.printer_box = ttk.Combobox(box, textvariable=self.printer, state="readonly", width=34)
        self._row(box, 1, "Printer", self.printer_box, ("Rescan", self.scan_printers))
        self._row(box, 2, "Copies", ttk.Spinbox(box, from_=1, to=10, textvariable=self.copies, width=6))
        self._row(box, 3, "Countdown (s)", ttk.Spinbox(box, from_=1, to=60, textvariable=self.countdown, width=6))
        session_entry = ttk.Entry(box, width=36)
        session_entry.insert(0, str(self.sessions_dir))
        session_entry.configure(state="readonly")
        self._row(box, 4, "Session folder", session_entry,
                  ("Open folder", lambda: self.open_dir(self.sessions_dir)))
        ttk.Button(box, text="Save && apply", command=self.apply).grid(
            row=5, column=0, columnspan=4, sticky="ew", padx=8, pady=(4, 8))

        tk.Label(self, fg="gray", anchor="w", justify="left", wraplength=480,
                 text=f"Config: {CONFIG_PATH}\nFrames: {FRAMES_DIR}"
                 ).grid(row=4, column=0, sticky="w", padx=10, pady=(2, 10))

        self.scan_printers()
        self.refresh_cameras()
        self.refresh_frames()

    # ---------- small actions ----------
    def set_status(self, text, color):
        self.status.configure(text=text, fg=color)

    def copy_url(self):
        self.clipboard_clear()
        self.clipboard_append(URL)

    def open_dir(self, path):
        Path(path).mkdir(parents=True, exist_ok=True)
        try:
            open_path(path)
        except Exception as exc:
            messagebox.showerror("Open folder", str(exc))

    def _composer(self):
        return importlib.import_module("printing.composer")

    # ---------- cameras ----------
    def refresh_cameras(self):
        values = [DEFAULT_CAMERA] + read_cameras()
        current = self.camera.get()
        if current not in values:
            values.append(current)                  # keep a saved choice even if it's unplugged right now
        if list(self.camera_box["values"]) != values:
            self.camera_box["values"] = values

    def poll_cameras(self):
        self.refresh_cameras()
        self.after(3000, self.poll_cameras)

    # ---------- printers ----------
    def scan_printers(self):
        names = list_printers()
        current = self.printer.get()
        if current and current != DEFAULT_PRINTER and current not in names:
            names.append(current)
        self.printer_box["values"] = [DEFAULT_PRINTER] + sorted(set(names))

    # ---------- frames ----------
    def refresh_frames(self, select=None):
        names = sorted(p.name for p in FRAMES_DIR.glob("*.png"))
        self.frame_box["values"] = names
        if select:
            self.frame.set(select)
        elif self.frame.get() not in names and names:
            self.frame.set(names[0])
        self.update_info()

    def update_info(self):
        try:
            n = self._composer().count_windows(FRAMES_DIR / self.frame.get())
            self.info.set(f"{n} photo window(s) found -> {n} photos per session")
        except Exception as exc:
            self.info.set(f"Frame problem: {exc}")

    def upload_frame(self):
        src = filedialog.askopenfilename(title="Choose a frame PNG", filetypes=[("PNG image", "*.png")])
        if not src:
            return
        dest = FRAMES_DIR / Path(src).name
        if dest.exists():
            dest = FRAMES_DIR / f"{dest.stem}_{int(time.time())}.png"
        shutil.copy2(src, dest)
        try:
            self._composer().count_windows(dest)
        except Exception as exc:
            dest.unlink(missing_ok=True)
            messagebox.showerror(
                "Frame not usable",
                f"{exc}\n\nThe PNG needs fully TRANSPARENT photo windows (and one strip on the canvas).")
            return
        self.refresh_frames(select=dest.name)

    def _fmt(self):
        strips = int(self.strips.get())
        if not 1 <= strips <= 8:
            raise ValueError("Strips per sheet must be between 1 and 8.")
        return {"frame": FRAMES_DIR / self.frame.get(), "paper": self.paper.get(),
                "orientation": self.orient.get(), "strips": strips}

    def preview(self):
        from PIL import Image, ImageDraw
        comp = self._composer()
        try:
            fmt = self._fmt()
            colors = ["#8ecae6", "#ffb703", "#90be6d", "#f28482"]
            photos = []
            for i in range(comp.count_windows(fmt["frame"])):
                im = Image.new("RGB", (1500, 1000), colors[i % 4])
                ImageDraw.Draw(im).text((750, 500), str(i + 1), fill="white", font=comp._font(400), anchor="mm")
                photos.append(im)
            sheet = comp.build_sheet(photos, fmt)
        except Exception as exc:
            messagebox.showerror("Preview", str(exc))
            return
        sheet.thumbnail((900, 800))
        tmp = APP_DIR / "preview.png"
        sheet.save(tmp)
        win = tk.Toplevel(self)
        win.title(f"Preview: {fmt['paper']} {fmt['orientation']}, {fmt['strips']} strip(s)")
        img = tk.PhotoImage(file=str(tmp))
        label = tk.Label(win, image=img)
        label.image = img
        label.pack()

    # ---------- save + restart ----------
    def apply(self):
        try:
            copies, countdown, fmt = int(self.copies.get()), int(self.countdown.get()), self._fmt()
            if not 1 <= copies <= 10 or not 1 <= countdown <= 60:
                raise ValueError("Copies must be 1-10 and countdown must be 1-60 seconds.")
            self._composer().count_windows(fmt["frame"])
        except Exception as exc:
            messagebox.showerror("Invalid setting", str(exc))
            return

        printer_name = self.printer.get()
        camera_name = self.camera.get()
        self.cfg["printer"] = {
            **(self.cfg.get("printer") or {}),
            "mode": self.mode.get(),
            "name": "" if printer_name == DEFAULT_PRINTER else printer_name,
            "copies": copies,
        }
        self.cfg["camera"] = {
            **(self.cfg.get("camera") or {}),
            "browser_device_hint": "" if camera_name == DEFAULT_CAMERA else camera_name,
        }
        self.cfg["layout"] = {"frame": self.frame.get(), "paper": fmt["paper"],
                              "orientation": fmt["orientation"], "strips": fmt["strips"]}
        self.cfg["countdown_seconds"] = countdown

        try:
            save_cfg(self.cfg)
        except OSError as exc:
            messagebox.showerror("Configuration", f"Could not write config.yaml:\n{exc}")
            return
        self.restart()

    def restart(self):
        self.set_status("Restarting...", "orange")
        self.update_idletasks()
        error = self.server.restart()
        if error:
            self.set_status("Not running", "red")
            messagebox.showerror("Server", error)
        else:
            self.set_status(f"Running at {URL} (open booth pages reload by themselves)", "green")

    def on_close(self):
        self.server.stop()
        self.destroy()


if __name__ == "__main__":
    App().mainloop()