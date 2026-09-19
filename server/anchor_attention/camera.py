"""Frame source shared by the live monitor and the session recorder."""

from __future__ import annotations

import sys
import threading
import time
from typing import Iterator

import cv2
import numpy as np

MAX_GRAB_FAILURES = 30


class NoCamera(Exception):
    """The camera (or video file) could not be opened."""


class CameraLost(Exception):
    """The source stopped delivering frames."""


def open_capture(source: int | str) -> cv2.VideoCapture | None:
    if isinstance(source, int) and sys.platform == "win32":
        capture = cv2.VideoCapture(source, cv2.CAP_DSHOW)  # opens much faster than the default
    else:
        capture = cv2.VideoCapture(source)
    if not capture.isOpened():
        capture.release()
        return None
    capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return capture


def frame_stream(source: int | str, fps: float, stop: threading.Event | None = None) -> Iterator[np.ndarray]:
    """Yield BGR frames at about `fps` until `stop` is set.

    Video files play at their own speed and loop. Raises NoCamera if the source
    can't be opened and CameraLost if a camera stops delivering frames.
    """
    capture = open_capture(source)
    if capture is None:
        raise NoCamera(str(source))

    is_file = isinstance(source, str)
    file_frame_delay = 1.0 / (capture.get(cv2.CAP_PROP_FPS) or 25.0)
    interval = 1.0 / fps
    last_yielded = 0.0
    failures = 0

    try:
        while not (stop is not None and stop.is_set()):
            if not capture.grab():
                if is_file:
                    # Some formats (raw MJPEG) can't seek, so loop by reopening.
                    capture.release()
                    capture = open_capture(source)
                    if capture is None:
                        raise CameraLost(str(source))
                    continue
                failures += 1
                if failures >= MAX_GRAB_FAILURES:
                    raise CameraLost(str(source))
                time.sleep(0.05)
                continue
            failures = 0
            if is_file:
                time.sleep(file_frame_delay)

            now = time.monotonic()
            if now - last_yielded < interval:
                continue
            last_yielded = now

            ok, frame = capture.retrieve()
            if ok:
                yield frame
    finally:
        if capture is not None:
            capture.release()
