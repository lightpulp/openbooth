"""Python-side camera (laptop cam, or DSLR/phone in "webcam" mode).
Only used when camera.mode is "opencv" in config.yaml."""
import sys
import threading
import time

import cv2


class CameraError(Exception):
    pass


class OpenCVCamera:
    def __init__(self, index=0):
        self.index = index
        self.cap = None
        self.lock = threading.Lock()   # OpenCV isn't thread-safe

    def _read(self):
        """Open the camera if needed and return one frame."""
        if self.cap is None or not self.cap.isOpened():
            backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
            self.cap = cv2.VideoCapture(self.index, backend)
            if not self.cap.isOpened():
                raise CameraError(f"Cannot open camera #{self.index}. Connected? Used by another app?")
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
            for _ in range(5):          # let auto-exposure settle
                self.cap.read()
        ok, frame = self.cap.read()
        if not ok or frame is None:
            self.cap.release()
            self.cap = None             # reopen on next call
            raise CameraError("Camera returned no image.")
        return frame

    def capture(self):
        """One full-quality JPEG, as bytes."""
        with self.lock:
            frame = self._read()
        return cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 95])[1].tobytes()

    def stream(self):
        """Live preview: yields MJPEG chunks (~30 fps)."""
        while True:
            try:
                with self.lock:
                    frame = self._read()
            except CameraError:
                break
            jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])[1].tobytes()
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpg + b"\r\n"
            time.sleep(0.03)
