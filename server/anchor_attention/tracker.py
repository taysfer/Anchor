"""Attention state machine.

Python counterpart of extension/attention/attention-core.js, extended with gaze:
a person counts as "away" when their face is gone, their head is turned, their
eyes are closed for a while, or their eyes are pointed well off where they
were during calibration.

No camera or model access here, so it can be tested with synthetic readings.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Reading:
    """One frame's worth of face information."""

    present: bool
    forward: np.ndarray | None = None  # unit vector the face points along
    gaze_h: float | None = None  # iris position across the eye, 0.5 = centred
    gaze_v: float | None = None  # iris position between the lids, 0.5 = centred
    blinking: bool = False


@dataclass(frozen=True)
class TrackerConfig:
    away_threshold_ms: float = 5000  # away this long triggers the warning
    angle_threshold_deg: float = 20.0  # head turned this far from calibration = away
    gaze_h_threshold: float = 0.10  # iris moved this far sideways from calibration = away
    gaze_v_threshold: float = 0.25  # iris moved this far up/down from calibration = away
    gaze_smooth_ms: float = 1000  # gaze is median-filtered over this window before thresholding (0 = off)
    calibration_ms: float = 2500
    min_calibration_samples: int = 3
    return_frames: int = 2  # consecutive attentive readings needed to end an episode
    eyes_closed_ms: float = 2000  # eyes shut this long stops counting as a blink

    @classmethod
    def from_dict(cls, data: dict) -> "TrackerConfig":
        """Build from the extension's ATTENTION_CONFIG (camelCase) keys."""
        mapping = {
            "awayThresholdMs": ("away_threshold_ms", float),
            "angleThresholdDeg": ("angle_threshold_deg", float),
            "calibrationMs": ("calibration_ms", float),
            "minCalibrationSamples": ("min_calibration_samples", int),
            "returnFrames": ("return_frames", int),
        }
        kwargs = {py: cast(data[js]) for js, (py, cast) in mapping.items() if js in data}
        config = cls(**kwargs)
        if config.away_threshold_ms <= 0 or config.calibration_ms < 0 or config.return_frames < 1:
            raise ValueError("invalid tracker config")
        return config


def angle_between_deg(a: np.ndarray, b: np.ndarray) -> float:
    return math.degrees(math.acos(float(np.clip(np.dot(a, b), -1.0, 1.0))))


def _state_event(state: str) -> dict:
    return {"type": "state", "state": state}


class AttentionTracker:
    def __init__(self, config: TrackerConfig | None = None) -> None:
        self.config = config or TrackerConfig()
        self._reset()

    def _reset(self) -> None:
        self.state = "calibrating"  # calibrating | attentive | away
        self._samples: list[Reading] = []
        self._calibration_start: float | None = None
        self._base_forward: np.ndarray | None = None
        self._base_h: float | None = None
        self._base_v: float | None = None
        self._away_since: float | None = None
        self._warned = False
        self._attentive_streak = 0
        self._closed_since: float | None = None
        self._gaze_window: deque = deque()  # (time, gaze_h, gaze_v) of recent open-eyed frames
        self.live: dict = {}  # what the latest frame measured, for live displays (see _assess)

    def away_for_ms(self, now_ms: float) -> float:
        """How long the current away stretch has lasted (0 if the person is attentive)."""
        return 0.0 if self._away_since is None else now_ms - self._away_since

    def calibration_progress(self, now_ms: float) -> float:
        if self.state != "calibrating":
            return 1.0
        if self._calibration_start is None or self.config.calibration_ms <= 0:
            return 0.0
        return min(1.0, (now_ms - self._calibration_start) / self.config.calibration_ms)

    @property
    def baseline(self) -> dict | None:
        """The calibrated 'looking at the screen' pose, or None while calibrating."""
        if self._base_forward is None:
            return None
        return {"forward": self._base_forward, "gaze_h": self._base_h, "gaze_v": self._base_v}

    def recalibrate(self, now_ms: float) -> list[dict]:
        """Start over, treating the current pose as 'looking at the screen'."""
        events: list[dict] = []
        if self._warned and self._away_since is not None:
            events.append(self._returned_event(now_ms))
        self._reset()
        events.append(_state_event(self.state))
        return events

    def update(self, reading: Reading, now_ms: float) -> list[dict]:
        if self.state == "calibrating":
            return self._calibrate(reading, now_ms)

        verdict, reason = self._assess(reading, now_ms)
        if verdict == "neutral":  # mid-blink: says nothing either way
            return []

        events: list[dict] = []
        if verdict == "away":
            self._attentive_streak = 0
            if self._away_since is None:
                self._away_since = now_ms
            if not self._warned and now_ms - self._away_since >= self.config.away_threshold_ms:
                self._warned = True
                self.state = "away"
                events.append({"type": "away", "since": int(self._away_since), "reason": reason})
                events.append(_state_event("away"))
            return events

        # Require a few attentive readings in a row so one stray frame mid-episode
        # doesn't reset the away timer or end the episode early.
        self._attentive_streak += 1
        if self._attentive_streak >= self.config.return_frames and self._away_since is not None:
            if self._warned:
                events.append(self._returned_event(now_ms))
                self.state = "attentive"
                events.append(_state_event("attentive"))
            self._away_since = None
            self._warned = False
        return events

    def _returned_event(self, now_ms: float) -> dict:
        since = int(self._away_since)
        until = int(now_ms)
        return {"type": "returned", "since": since, "until": until, "durationMs": until - since}

    def _assess(self, reading: Reading, now_ms: float) -> tuple[str, str | None]:
        cfg = self.config
        live = self.live = {"head_deg": None, "gaze_h": None, "gaze_v": None}

        if not reading.present:
            self._closed_since = None
            return "away", "no-face"

        if reading.forward is not None and self._base_forward is not None:
            live["head_deg"] = angle_between_deg(reading.forward, self._base_forward)
            if live["head_deg"] > cfg.angle_threshold_deg:
                self._closed_since = None
                return "away", "head-turned"

        if reading.blinking:
            if self._closed_since is None:
                self._closed_since = now_ms
            if now_ms - self._closed_since >= cfg.eyes_closed_ms:
                return "away", "eyes-closed"
            return "neutral", None
        self._closed_since = None

        gaze_h, gaze_v = self._smoothed_gaze(reading, now_ms)
        live["gaze_h"], live["gaze_v"] = gaze_h, gaze_v
        if gaze_h is not None and self._base_h is not None:
            if abs(gaze_h - self._base_h) > cfg.gaze_h_threshold:
                return "away", "eyes-off-screen"
        if gaze_v is not None and self._base_v is not None:
            if abs(gaze_v - self._base_v) > cfg.gaze_v_threshold:
                return "away", "eyes-off-screen"

        return "attentive", None

    def _smoothed_gaze(self, reading: Reading, now_ms: float) -> tuple[float | None, float | None]:
        """Median of the recent gaze readings, so tracking flicker doesn't break up a steady look."""
        if self.config.gaze_smooth_ms <= 0:
            return reading.gaze_h, reading.gaze_v

        window = self._gaze_window
        window.append((now_ms, reading.gaze_h, reading.gaze_v))
        while now_ms - window[0][0] > self.config.gaze_smooth_ms:
            window.popleft()

        def median(values: list[float]) -> float | None:
            if not values:
                return None
            ordered = sorted(values)  # windows are a handful of frames; much cheaper than numpy here
            middle = len(ordered) // 2
            return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2

        return median([h for _, h, _ in window if h is not None]), median([v for _, _, v in window if v is not None])

    def _calibrate(self, reading: Reading, now_ms: float) -> list[dict]:
        if not reading.present or reading.forward is None or reading.blinking:
            return []
        if self._calibration_start is None:
            self._calibration_start = now_ms
        self._samples.append(reading)

        cfg = self.config
        long_enough = now_ms - self._calibration_start >= cfg.calibration_ms
        if not (long_enough and len(self._samples) >= cfg.min_calibration_samples):
            return []

        forward = np.mean([r.forward for r in self._samples], axis=0)
        self._base_forward = forward / (np.linalg.norm(forward) or 1.0)
        horizontal = [r.gaze_h for r in self._samples if r.gaze_h is not None]
        vertical = [r.gaze_v for r in self._samples if r.gaze_v is not None]
        self._base_h = float(np.mean(horizontal)) if horizontal else None
        self._base_v = float(np.mean(vertical)) if vertical else None
        self._samples = []
        self.state = "attentive"
        return [_state_event("attentive")]
