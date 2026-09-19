"""Turns a camera frame into a Reading: face presence, head direction, gaze, blink.

Same signals as antoinelame/GazeTracking (horizontal/vertical pupil ratio,
blink detection), but built on MediaPipe's Face Landmarker instead of dlib. The
model already tracks the iris, so there is no pupil thresholding step and no C++
build toolchain to install, and it also provides head pose.

Frames are only held in memory while being analysed; nothing is saved or sent.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision

from .tracker import Reading

# Landmark indices in MediaPipe's 478-point face model (468+ are the iris).
# "Right"/"left" are the subject's own eyes.
RIGHT_EYE = {"outer": 33, "inner": 133, "upper": 159, "lower": 145, "iris": 468}
LEFT_EYE = {"outer": 263, "inner": 362, "upper": 386, "lower": 374, "iris": 473}

BLINK_SCORE = 0.5


def gaze_ratios(landmarks) -> tuple[float | None, float | None]:
    """Where the irises sit inside the eyes, averaged over both eyes.

    horizontal: 0.0 = iris at the image-left corner of the eye, 1.0 = image-right
                corner, 0.5 = centred. From the subject's point of view, higher
                means looking to their left.
    vertical:   0.0 = iris against the upper lid, 1.0 = against the lower lid.
    """
    horizontals, verticals = [], []
    for eye in (RIGHT_EYE, LEFT_EYE):
        if eye["iris"] >= len(landmarks):
            return None, None  # model returned no iris landmarks
        corner_a, corner_b = landmarks[eye["outer"]], landmarks[eye["inner"]]
        left_x, right_x = sorted((corner_a.x, corner_b.x))
        upper, lower = landmarks[eye["upper"]], landmarks[eye["lower"]]
        iris = landmarks[eye["iris"]]

        if right_x - left_x > 1e-6:
            horizontals.append((iris.x - left_x) / (right_x - left_x))
        if lower.y - upper.y > 1e-6:
            verticals.append((iris.y - upper.y) / (lower.y - upper.y))

    horizontal = float(np.mean(horizontals)) if horizontals else None
    vertical = float(np.mean(verticals)) if verticals else None
    return horizontal, vertical


def is_blinking(blendshapes) -> bool:
    scores = {c.category_name: c.score for c in blendshapes}
    both = [scores.get("eyeBlinkLeft"), scores.get("eyeBlinkRight")]
    if any(s is None for s in both):
        return False
    return float(np.mean(both)) > BLINK_SCORE


def forward_axis(matrix) -> np.ndarray:
    """The direction the face points, from the 4x4 head pose matrix.

    The third column is the face's depth axis. The matrix includes scale, so
    normalise it.
    """
    axis = np.asarray(matrix, dtype=float)[:3, 2]
    return axis / (np.linalg.norm(axis) or 1.0)


class FaceAnalyzer:
    def __init__(self, model_path: Path | str) -> None:
        options = vision.FaceLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=str(model_path)),
            running_mode=vision.RunningMode.VIDEO,
            num_faces=1,
            output_face_blendshapes=True,
            output_facial_transformation_matrixes=True,
        )
        self._landmarker = vision.FaceLandmarker.create_from_options(options)
        self._last_timestamp_ms = -1
        self.last_landmarks = None  # the latest frame's face landmarks, for drawing a live overlay

    def analyze(self, frame_bgr: np.ndarray, timestamp_ms: int) -> Reading:
        # MediaPipe rejects any timestamp that isn't strictly greater than the last
        # one, and clocks like Windows' time.monotonic() only tick every ~15 ms, so
        # two quick calls can otherwise arrive with the same value.
        timestamp_ms = max(timestamp_ms, self._last_timestamp_ms + 1)
        self._last_timestamp_ms = timestamp_ms

        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result = self._landmarker.detect_for_video(image, timestamp_ms)

        self.last_landmarks = result.face_landmarks[0] if result.face_landmarks else None
        if not result.face_landmarks:
            return Reading(present=False)

        horizontal, vertical = gaze_ratios(result.face_landmarks[0])
        matrices = result.facial_transformation_matrixes
        return Reading(
            present=True,
            forward=forward_axis(matrices[0]) if matrices else None,
            gaze_h=horizontal,
            gaze_v=vertical,
            blinking=bool(result.face_blendshapes) and is_blinking(result.face_blendshapes[0]),
        )

    def close(self) -> None:
        self._landmarker.close()
