from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from anchor_attention.gaze import FaceAnalyzer, forward_axis, gaze_ratios, is_blinking

MODEL = Path(__file__).resolve().parents[2] / "extension" / "vendor" / "mediapipe" / "face_landmarker.task"


def landmarks_with(right, left):
    """478 dummy landmarks with the eye points we care about filled in.

    `right`/`left` map outer/inner/upper/lower/iris to (x, y).
    """
    points = [SimpleNamespace(x=0.0, y=0.0) for _ in range(478)]
    indices = {
        "right": {"outer": 33, "inner": 133, "upper": 159, "lower": 145, "iris": 468},
        "left": {"outer": 263, "inner": 362, "upper": 386, "lower": 374, "iris": 473},
    }
    for side, spec in (("right", right), ("left", left)):
        for name, (x, y) in spec.items():
            points[indices[side][name]] = SimpleNamespace(x=x, y=y)
    return points


def eye(left_x, right_x, iris_x, upper_y=0.40, lower_y=0.50, iris_y=0.45):
    return {
        "outer": (left_x, 0.45),
        "inner": (right_x, 0.45),
        "upper": ((left_x + right_x) / 2, upper_y),
        "lower": ((left_x + right_x) / 2, lower_y),
        "iris": (iris_x, iris_y),
    }


def test_centred_irises_read_as_centred():
    h, v = gaze_ratios(landmarks_with(eye(0.30, 0.40, 0.35), eye(0.60, 0.70, 0.65)))
    assert h == pytest.approx(0.5)
    assert v == pytest.approx(0.5)


def test_irises_toward_image_right_raise_the_horizontal_ratio():
    h, _ = gaze_ratios(landmarks_with(eye(0.30, 0.40, 0.38), eye(0.60, 0.70, 0.68)))
    assert h == pytest.approx(0.8)


def test_irises_toward_upper_lid_lower_the_vertical_ratio():
    _, v = gaze_ratios(landmarks_with(eye(0.30, 0.40, 0.35, iris_y=0.41), eye(0.60, 0.70, 0.65, iris_y=0.41)))
    assert v == pytest.approx(0.1)


def test_missing_iris_landmarks_give_no_gaze():
    assert gaze_ratios([SimpleNamespace(x=0.5, y=0.5)] * 468) == (None, None)


def category(name, score):
    return SimpleNamespace(category_name=name, score=score)


def test_blink_detection():
    assert is_blinking([category("eyeBlinkLeft", 0.9), category("eyeBlinkRight", 0.8)])
    assert not is_blinking([category("eyeBlinkLeft", 0.1), category("eyeBlinkRight", 0.2)])
    assert not is_blinking([category("jawOpen", 0.9)])


def test_forward_axis_ignores_scale_and_translation():
    matrix = np.array([[3, 0, 0, 10], [0, 3, 0, 20], [0, 0, 3, 30], [0, 0, 0, 1]], dtype=float)
    assert forward_axis(matrix) == pytest.approx([0, 0, 1])


@pytest.mark.skipif(not MODEL.exists(), reason="face model not bundled")
def test_analyzer_tolerates_repeated_and_backwards_timestamps():
    # Windows' monotonic clock ticks every ~15ms, so quick calls can share a timestamp.
    analyzer = FaceAnalyzer(MODEL)
    blank = np.zeros((480, 640, 3), dtype=np.uint8)
    try:
        for timestamp in (1000, 1000, 1000, 900, 1001):
            assert analyzer.analyze(blank, timestamp).present is False
    finally:
        analyzer.close()


@pytest.mark.skipif(not MODEL.exists(), reason="face model not bundled")
def test_analyzer_sees_no_face_in_an_empty_frame():
    analyzer = FaceAnalyzer(MODEL)
    try:
        reading = analyzer.analyze(np.zeros((480, 640, 3), dtype=np.uint8), 1000)
    finally:
        analyzer.close()
    assert reading.present is False
