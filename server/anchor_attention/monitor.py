"""Background thread that reads the camera, analyses each frame, and reports events.

Events go to `on_event` as plain dicts (the same shapes the extension already
handles): status / state / away / returned. Video frames never leave this thread.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Callable

from .camera import CameraLost, NoCamera, frame_stream
from .gaze import FaceAnalyzer
from .tracker import AttentionTracker, TrackerConfig

log = logging.getLogger("anchor.attention")

TARGET_FPS = 8


def _now_ms() -> int:
    return int(time.time() * 1000)


class AttentionMonitor:
    """`source` is a camera index, or a video file path (loops; for testing/demos)."""

    def __init__(self, model_path: Path, source: int | str, on_event: Callable[[dict], None]) -> None:
        self._model_path = model_path
        self._source = source
        self._on_event = on_event
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._recalibrate = threading.Event()

    def start(self, config: TrackerConfig) -> None:
        if self._thread and self._thread.is_alive():
            raise RuntimeError("monitor already running")
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, args=(config,), daemon=True, name="anchor-attention")
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout)

    def request_recalibrate(self) -> None:
        self._recalibrate.set()

    def _error(self, code: str) -> None:
        self._on_event({"type": "status", "status": "error", "error": code})

    def _run(self, config: TrackerConfig) -> None:
        self._on_event({"type": "status", "status": "starting"})

        try:
            analyzer = FaceAnalyzer(self._model_path)
        except Exception:
            log.exception("could not load the face model")
            self._error("model-load-failed")
            return

        tracker = AttentionTracker(config)
        announced = False

        try:
            for frame in frame_stream(self._source, TARGET_FPS, self._stop):
                if not announced:
                    announced = True
                    self._on_event({"type": "status", "status": "active"})
                    self._on_event({"type": "state", "state": tracker.state})

                if self._recalibrate.is_set():
                    self._recalibrate.clear()
                    for event in tracker.recalibrate(_now_ms()):
                        self._on_event(event)

                reading = analyzer.analyze(frame, int(time.monotonic() * 1000))
                for event in tracker.update(reading, _now_ms()):
                    self._on_event(event)
        except NoCamera:
            self._error("no-camera")
        except CameraLost:
            self._error("camera-lost")
        except Exception:
            log.exception("attention monitoring failed")
            self._error("detection-failed")
        finally:
            analyzer.close()
