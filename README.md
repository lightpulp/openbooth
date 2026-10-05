# Photobooth

Takes 4 photos (countdown before each), builds a 4x6 sheet with two identical strips, and "prints" it as a PDF.

## Run

Requires Python 3.10+.

```bash
python -m venv venv
venv\Scripts\activate          # Mac/Linux: source venv/bin/activate
pip install -r requirements.txt



uvicorn main:app --reload # Main run command
```

Open **http://localhost:8000** (must be `localhost`) and allow the camera.
Output goes to `sessions/<id>/` (`raw_1-4.jpg`, `final_4x6.png`, `print.pdf`).

Edit `config.yaml` to change text, date, countdown, camera or printer, then restart the server.

## Paths

| Path | What it does |
|---|---|
| `main.py` | Starts the app and plugs in the 3 parts |
| `core.py` | Loads `config.yaml`, creates session folders, validates and saves photos |
| `config.yaml` | All settings (event text, countdown, camera mode, printer mode) |
| `ui/routes.py` | `GET /` page, `GET /config`, `POST /session` |
| `ui/static/` | The web page: `index.html` (screens), `style.css` (look), `app.js` (countdown, camera, flow, errors) |
| `camera/routes.py` | `POST /camera/upload` (browser photo), `POST /camera/capture` and `GET /camera/stream` (Python camera), `GET /camera/photo` (thumbnails) |
| `camera/opencv_cam.py` | Python camera control, used only when `camera.mode: opencv` |
| `printing/routes.py` | `POST /printing/print/{id}` composes and prints, `GET /printing/pdf/{id}`; `send_to_printer()` is where the Epson code goes |
| `printing/composer.py` | Pillow layout: 4 photos + text into a strip, duplicated onto a 4x6 sheet |
| `sessions/` | Runtime photos and PDFs (gitignored, created automatically) |

## Switching to the real hardware

- **DSLR/phone as a webcam:** set `camera.browser_device_hint` in `config.yaml` to part of its name (see camera names in the browser console, F12).
- **Python-controlled camera:** set `camera.mode: opencv` and `camera.index`.
- **Epson L3250:** fill in `send_to_printer()` in `printing/routes.py` and set `printer.mode`.