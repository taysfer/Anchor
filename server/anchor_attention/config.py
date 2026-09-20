"""Settings shared by the server and the recorder, read from the environment."""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

MODEL_PATH = Path(
    os.environ.get(
        "ANCHOR_FACE_MODEL",
        REPO_ROOT / "extension" / "vendor" / "mediapipe" / "face_landmarker.task",
    )
)


def camera_source() -> int | str:
    """A camera index, or the path of a video file (used for testing and demos)."""
    raw = os.environ.get("ANCHOR_CAMERA_SOURCE", "0")
    return int(raw) if raw.isdigit() else raw
