"""Photobooth launcher: Tkinter GUI + embedded FastAPI/Uvicorn server.

Place this file in the project root beside main.py, core.py, config.yaml,
and the ui/, camera/, and printing/ folders.

Development: python gui.py
Packaging: build this file with PyInstaller from the project root.
"""
import importlib
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
FROZEN = bool(getattr(sys, "frozen", False))

# Writable files live beside gui.py in development, or beside the EXE when frozen.
APP_DIR = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent
# PyInstaller's temporary extraction folder contains bundled read-only assets.
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))
CONFIG_PATH = APP_DIR / "config.yaml"

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

        self._build()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(300, self.restart)

    def _build(self):
        printer_cfg = self.cfg.get("printer") or {}
        self.mode = tk.StringVar(value=printer_cfg.get("mode", "pdf"))
        self.printer = tk.StringVar(value=printer_cfg.get("name") or DEFAULT_PRINTER)
        self.copies = tk.StringVar(value=str(printer_cfg.get("copies", 1)))
        self.countdown = tk.StringVar(value=str(self.cfg.get("countdown_seconds", 10)))
        self.sessions_dir = APP_DIR / "sessions"

        server_box = ttk.LabelFrame(self, text="Server")
        server_box.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 4))
        server_box.columnconfigure(0, weight=1)

        self.status = tk.Label(server_box, text="Starting...", anchor="w", fg="orange")
        self.status.grid(row=0, column=0, columnspan=3, sticky="w", padx=8, pady=(6, 2))

        url_entry = ttk.Entry(server_box, width=36)
        url_entry.insert(0, URL)
        url_entry.configure(state="readonly")
        url_entry.grid(row=1, column=0, sticky="ew", padx=8, pady=4)
        ttk.Button(server_box, text="Open", command=lambda: webbrowser.open(URL)).grid(
            row=1, column=1, padx=2
        )
        ttk.Button(server_box, text="Copy", command=self.copy_url).grid(
            row=1, column=2, padx=(2, 8)
        )
        ttk.Button(server_box, text="Refresh server", command=self.restart).grid(
            row=2, column=0, columnspan=3, sticky="ew", padx=8, pady=(4, 8)
        )

        cfg_box = ttk.LabelFrame(self, text="Configuration")
        cfg_box.grid(row=1, column=0, sticky="ew", padx=10, pady=4)
        cfg_box.columnconfigure(1, weight=1)

        ttk.Label(cfg_box, text="Print mode").grid(row=0, column=0, sticky="w", padx=8, pady=4)
        ttk.Combobox(
            cfg_box, textvariable=self.mode, values=("pdf", "epson"),
            state="readonly", width=14
        ).grid(row=0, column=1, sticky="w", padx=4)

        ttk.Label(cfg_box, text="Printer").grid(row=1, column=0, sticky="w", padx=8, pady=4)
        self.printer_box = ttk.Combobox(
            cfg_box, textvariable=self.printer, state="readonly", width=32
        )
        self.printer_box.grid(row=1, column=1, sticky="ew", padx=4)
        ttk.Button(cfg_box, text="Rescan", command=self.scan_printers).grid(
            row=1, column=2, padx=(2, 8)
        )

        ttk.Label(cfg_box, text="Copies").grid(row=2, column=0, sticky="w", padx=8, pady=4)
        ttk.Spinbox(cfg_box, from_=1, to=10, textvariable=self.copies, width=6).grid(
            row=2, column=1, sticky="w", padx=4
        )

        ttk.Label(cfg_box, text="Countdown (s)").grid(
            row=3, column=0, sticky="w", padx=8, pady=4
        )
        ttk.Spinbox(cfg_box, from_=1, to=60, textvariable=self.countdown, width=6).grid(
            row=3, column=1, sticky="w", padx=4
        )

        ttk.Label(cfg_box, text="Session folder").grid(
            row=4, column=0, sticky="w", padx=8, pady=4
        )
        # Read-only path for the sessions directory used by core.py.
        self.session_entry = ttk.Entry(cfg_box, width=36)
        self.session_entry.insert(0, str(self.sessions_dir))
        self.session_entry.configure(state="readonly")
        self.session_entry.grid(row=4, column=1, sticky="ew", padx=4)
        ttk.Button(cfg_box, text="Open folder", command=self.open_sessions).grid(
            row=4, column=2, padx=(2, 8)
        )

        ttk.Button(cfg_box, text="Save && apply", command=self.apply).grid(
            row=5, column=0, columnspan=3, sticky="ew", padx=8, pady=(4, 8)
        )

        details = (
            f"Config: {CONFIG_PATH}\n"
            "Photos are saved to the session folder shown above. "
            "Changing this folder is not supported by the current core.py."
        )
        tk.Label(
            self, text=details, fg="gray", anchor="w", justify="left", wraplength=480
        ).grid(row=2, column=0, sticky="w", padx=10, pady=(2, 10))

        self.scan_printers()

    def set_status(self, text, color):
        self.status.configure(text=text, fg=color)

    def copy_url(self):
        self.clipboard_clear()
        self.clipboard_append(URL)

    def open_sessions(self):
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        try:
            open_path(self.sessions_dir)
        except Exception as exc:
            messagebox.showerror("Open folder", str(exc))

    def scan_printers(self):
        names = list_printers()
        current = self.printer.get()
        if current and current != DEFAULT_PRINTER and current not in names:
            names.append(current)
        self.printer_box["values"] = [DEFAULT_PRINTER] + sorted(set(names))

    def apply(self):
        try:
            copies = int(self.copies.get())
            countdown = int(self.countdown.get())
            if not 1 <= copies <= 10 or not 1 <= countdown <= 60:
                raise ValueError
        except ValueError:
            messagebox.showerror(
                "Invalid value",
                "Copies must be 1–10 and countdown must be 1–60 seconds.",
            )
            return

        printer_name = self.printer.get()
        self.cfg["printer"] = {
            **(self.cfg.get("printer") or {}),
            "mode": self.mode.get(),
            "name": "" if printer_name == DEFAULT_PRINTER else printer_name,
            "copies": copies,
        }
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
            self.set_status(f"Running at {URL} (refresh the browser tab)", "green")

    def on_close(self):
        self.server.stop()
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
