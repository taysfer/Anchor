"""Draws what the tracker sees on top of a camera frame.

Face outline, eyes, irises, a head-direction arrow (measured from your calibrated
"looking at the screen" pose), live bars for head angle / gaze / the away timer
against their thresholds, and the current state. Used by the live preview.
"""

from __future__ import annotations

import math

import cv2
import numpy as np

from .tracker import AttentionTracker, Reading

# Landmark indices in MediaPipe's 478-point face model.
FACE_OVAL = [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379, 378, 400, 377, 152,
             148, 176, 149, 150, 136, 172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109]
RIGHT_EYE = [33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246]
LEFT_EYE = [362, 382, 381, 380, 374, 373, 390, 249, 263, 466, 388, 387, 386, 385, 384, 398]
IRISES = {"right": (468, [469, 470, 471, 472]), "left": (473, [474, 475, 476, 477])}
NOSE_TIP = 1

# BGR
GREEN, AMBER, RED = (110, 200, 90), (40, 190, 245), (70, 70, 235)
WHITE, GRAY, DARK = (240, 240, 240), (150, 150, 150), (25, 25, 25)


def to_pixel(landmark, width: int, height: int, mirror: bool) -> tuple[int, int]:
    x = 1.0 - landmark.x if mirror else landmark.x
    return int(x * width), int(landmark.y * height)


def _level_color(value: float | None, limit: float) -> tuple:
    if value is None:
        return GRAY
    ratio = value / limit if limit else 0.0
    return GREEN if ratio < 0.7 else AMBER if ratio < 1.0 else RED


def _text(img, text: str, origin: tuple[int, int], scale: float = 0.6, color=WHITE, thickness: int = 1) -> None:
    # Shadow via offset copies with identical font settings. A thicker "outline" pass renders
    # wider than the fill in newer OpenCV, so the two drift apart along longer strings.
    x, y = origin
    for dx, dy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
        cv2.putText(img, text, (x + dx, y + dy), cv2.FONT_HERSHEY_SIMPLEX, scale, DARK, thickness, cv2.LINE_AA)
    cv2.putText(img, text, origin, cv2.FONT_HERSHEY_SIMPLEX, scale, color, thickness, cv2.LINE_AA)


def _bar(img, x: int, y: int, width: int, value: float | None, limit: float, label: str, readout: str) -> None:
    """A bar that fills toward twice the limit, with a marker where the alert threshold sits."""
    _text(img, label, (x, y - 6), 0.5, WHITE)
    _text(img, readout, (x + width - 8 * len(readout) - 4, y - 6), 0.5, WHITE)
    cv2.rectangle(img, (x, y), (x + width, y + 10), (70, 70, 70), -1)
    if value is not None and limit:
        fill = int(min(value / (2 * limit), 1.0) * width)
        cv2.rectangle(img, (x, y), (x + fill, y + 10), _level_color(value, limit), -1)
    marker = x + width // 2
    cv2.line(img, (marker, y - 3), (marker, y + 13), WHITE, 2)


def _state_style(tracker: AttentionTracker, reading: Reading, now_ms: float) -> tuple[str, tuple]:
    if tracker.state == "calibrating":
        return f"CALIBRATING {int(tracker.calibration_progress(now_ms) * 100)}%", AMBER
    if tracker.state == "away":
        return "LOOKING AWAY", RED
    if not reading.present:
        return "NO FACE", AMBER
    if tracker.away_for_ms(now_ms) > 0:
        return "DRIFTING...", AMBER
    return "FOCUSED", GREEN


def draw_overlay(
    frame: np.ndarray,
    landmarks,
    reading: Reading,
    tracker: AttentionTracker,
    now_ms: float,
    mirror: bool = True,
    scale: float = 1.5,
) -> np.ndarray:
    """Return an annotated copy of `frame` (the input is not modified)."""
    view = cv2.flip(frame, 1) if mirror else frame.copy()
    if scale != 1.0:
        view = cv2.resize(view, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
    height, width = view.shape[:2]
    cfg = tracker.config
    state_text, state_color = _state_style(tracker, reading, now_ms)
    baseline = tracker.baseline
    live = tracker.live or {}

    if landmarks:
        def pt(i):
            return to_pixel(landmarks[i], width, height, mirror)

        oval = np.array([pt(i) for i in FACE_OVAL], np.int32)
        cv2.polylines(view, [oval], True, DARK, 4, cv2.LINE_AA)  # dark under-stroke keeps it visible on light backgrounds
        cv2.polylines(view, [oval], True, WHITE, 2, cv2.LINE_AA)
        for eye in (RIGHT_EYE, LEFT_EYE):
            cv2.polylines(view, [np.array([pt(i) for i in eye], np.int32)], True, state_color, 2, cv2.LINE_AA)
        if len(landmarks) > 477:
            for center, ring in IRISES.values():
                cx, cy = pt(center)
                radius = int(np.mean([math.hypot(pt(i)[0] - cx, pt(i)[1] - cy) for i in ring]))
                cv2.circle(view, (cx, cy), max(radius, 2), state_color, 2, cv2.LINE_AA)
                cv2.circle(view, (cx, cy), 2, WHITE, -1, cv2.LINE_AA)

        if reading.forward is not None and baseline is not None:
            # How far the face points from where it pointed when calibrated; zero length = looking at the screen.
            dx = float(reading.forward[0] - baseline["forward"][0])
            dy = -float(reading.forward[1] - baseline["forward"][1])  # camera y is up, image y is down
            if mirror:
                dx = -dx
            start = pt(NOSE_TIP)
            end = (int(start[0] + dx * 0.45 * height), int(start[1] + dy * 0.45 * height))
            cv2.arrowedLine(view, start, end, _level_color(live.get("head_deg"), cfg.angle_threshold_deg), 3,
                            cv2.LINE_AA, tipLength=0.25)

    # Heads-up display
    panel_w, panel_h = 280, 232
    overlay = view.copy()
    cv2.rectangle(overlay, (10, 10), (10 + panel_w, 10 + panel_h), DARK, -1)
    cv2.addWeighted(overlay, 0.6, view, 0.4, 0, view)

    _text(view, state_text, (22, 44), 0.9, state_color, 2)

    head = live.get("head_deg")
    _bar(view, 22, 78, panel_w - 24, head, cfg.angle_threshold_deg, "head turn",
         "-" if head is None else f"{head:.0f} / {cfg.angle_threshold_deg:.0f} deg")

    def gaze_shift(key: str, base_key: str):
        value, base = live.get(key), (baseline or {}).get(base_key)
        return None if value is None or base is None else abs(value - base)

    horizontal, vertical = gaze_shift("gaze_h", "gaze_h"), gaze_shift("gaze_v", "gaze_v")
    _bar(view, 22, 116, panel_w - 24, horizontal, cfg.gaze_h_threshold, "eyes sideways",
         "-" if horizontal is None else f"{horizontal:.2f} / {cfg.gaze_h_threshold:.2f}")
    _bar(view, 22, 154, panel_w - 24, vertical, cfg.gaze_v_threshold, "eyes up/down",
         "-" if vertical is None else f"{vertical:.2f} / {cfg.gaze_v_threshold:.2f}")

    away_s = tracker.away_for_ms(now_ms) / 1000
    limit_s = cfg.away_threshold_ms / 1000
    _bar(view, 22, 192, panel_w - 24, away_s if away_s > 0 else 0.0, limit_s, "away timer", f"{away_s:.1f} / {limit_s:.0f} s")

    if reading.present and reading.blinking:
        _text(view, "blink", (width - 80, 34), 0.6, WHITE)
    _text(view, "r: recalibrate   q: quit", (16, height - 14), 0.5, WHITE)

    if tracker.state == "away":
        cv2.rectangle(view, (0, 0), (width - 1, height - 1), RED, 8)
    return view
