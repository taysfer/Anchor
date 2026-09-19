import math
from types import SimpleNamespace

import numpy as np

from anchor_attention.overlay import RED, draw_overlay, to_pixel
from anchor_attention.tracker import AttentionTracker, Reading, TrackerConfig

FRAME = np.zeros((480, 640, 3), dtype=np.uint8)


def facing(deg=0.0):
    yaw = math.radians(deg)
    return Reading(present=True, forward=np.array([math.sin(yaw), 0.0, math.cos(yaw)]), gaze_h=0.5, gaze_v=0.5)


def fake_landmarks():
    return [SimpleNamespace(x=0.3 + 0.4 * (i % 20) / 20, y=0.3 + 0.4 * (i % 37) / 37) for i in range(478)]


def calibrated_tracker():
    tracker = AttentionTracker(TrackerConfig())
    for t in range(0, 2501, 500):
        tracker.update(facing(0), t)
    assert tracker.state == "attentive"
    return tracker


def test_mirrored_pixels_flip_horizontally():
    point = SimpleNamespace(x=0.25, y=0.5)
    assert to_pixel(point, 640, 480, mirror=False) == (160, 240)
    assert to_pixel(point, 640, 480, mirror=True) == (480, 240)


def test_overlay_scales_the_frame_and_leaves_the_input_untouched():
    view = draw_overlay(FRAME, None, Reading(present=False), AttentionTracker(), now_ms=0, scale=1.5)
    assert view.shape == (720, 960, 3)
    assert FRAME.sum() == 0
    assert view.sum() > 0  # the heads-up display was drawn


def test_overlay_draws_while_calibrating_with_no_face():
    tracker = AttentionTracker()
    view = draw_overlay(FRAME, None, Reading(present=False), tracker, now_ms=1000, scale=1.0)
    assert view.shape == FRAME.shape


def test_overlay_draws_face_features_and_the_head_arrow():
    tracker = calibrated_tracker()
    reading = facing(15)
    tracker.update(reading, 3000)
    plain = draw_overlay(FRAME, None, reading, tracker, now_ms=3000, scale=1.0)
    with_face = draw_overlay(FRAME, fake_landmarks(), reading, tracker, now_ms=3000, scale=1.0)
    assert (with_face != plain).any()


def test_overlay_borders_the_frame_in_red_once_the_alert_has_fired():
    tracker = calibrated_tracker()
    for t in range(3000, 8501, 500):
        tracker.update(facing(45), t)
    assert tracker.state == "away"
    view = draw_overlay(FRAME, fake_landmarks(), facing(45), tracker, now_ms=8500, scale=1.0)
    assert tuple(view[240, 2]) == RED


def test_overlay_has_no_red_border_while_focused():
    tracker = calibrated_tracker()
    tracker.update(facing(0), 3000)
    view = draw_overlay(FRAME, fake_landmarks(), facing(0), tracker, now_ms=3000, scale=1.0)
    assert tuple(view[240, 2]) != RED
