import math

import numpy as np
import pytest

from anchor_attention.tracker import AttentionTracker, Reading, TrackerConfig, angle_between_deg

CONFIG = TrackerConfig()  # 5s away, 20 degrees, 2.5s calibration, 2 return frames


def facing(deg, pitch_deg=0.0, gaze_h=0.5, gaze_v=0.5, blinking=False):
    yaw, pitch = math.radians(deg), math.radians(pitch_deg)
    forward = np.array([math.sin(yaw) * math.cos(pitch), math.sin(pitch), math.cos(yaw) * math.cos(pitch)])
    return Reading(present=True, forward=forward, gaze_h=gaze_h, gaze_v=gaze_v, blinking=blinking)


NO_FACE = Reading(present=False)


def feed(tracker, reading, t0, duration_ms, step=500):
    """Feed `reading` every `step` ms from t0 through t0 + duration (inclusive)."""
    events = []
    for t in range(t0, t0 + duration_ms + 1, step):
        events += [{**e, "t": t} for e in tracker.update(reading, t)]
    return events


def kinds(events):
    return [e["type"] + (":" + e["state"] if "state" in e else "") for e in events]


def calibrated(reading=None):
    tracker = AttentionTracker(CONFIG)
    events = feed(tracker, reading or facing(0), 0, 2500)
    return tracker, events


def test_calibration_completes_after_enough_face_time():
    tracker, events = calibrated()
    assert kinds(events) == ["state:attentive"]
    assert tracker.state == "attentive"


def test_no_face_time_does_not_count_toward_calibration():
    tracker = AttentionTracker(CONFIG)
    assert feed(tracker, NO_FACE, 0, 20000) == []
    assert feed(tracker, facing(0), 20500, 2000) == []
    assert tracker.state == "calibrating"
    feed(tracker, facing(0), 22500, 1000)
    assert tracker.state == "attentive"


def test_blinks_are_ignored_during_calibration():
    tracker = AttentionTracker(CONFIG)
    feed(tracker, facing(0, blinking=True), 0, 10000)
    assert tracker.state == "calibrating"


def test_short_glance_produces_no_events():
    tracker, _ = calibrated()
    assert feed(tracker, facing(60), 3000, 3000) == []
    assert feed(tracker, facing(0), 6500, 1500) == []


def test_sustained_head_turn_warns_at_threshold_with_correct_start():
    tracker, _ = calibrated()
    events = feed(tracker, facing(45), 3000, 5000)
    away = next(e for e in events if e["type"] == "away")
    assert away["since"] == 3000
    assert away["reason"] == "head-turned"
    assert away["t"] == 8000
    assert tracker.state == "away"


def test_one_attentive_frame_does_not_end_an_episode_but_two_do():
    tracker, _ = calibrated()
    feed(tracker, facing(45), 3000, 5000)
    assert feed(tracker, facing(0), 8500, 0) == []
    assert feed(tracker, facing(45), 9000, 1000) == []
    events = feed(tracker, facing(0), 10500, 500)
    returned = next(e for e in events if e["type"] == "returned")
    assert returned["since"] == 3000
    assert returned["durationMs"] == returned["until"] - 3000
    assert tracker.state == "attentive"


def test_leaving_the_frame_counts_as_away():
    tracker, _ = calibrated()
    events = feed(tracker, NO_FACE, 3000, 5000)
    assert next(e for e in events if e["type"] == "away")["reason"] == "no-face"


@pytest.mark.parametrize("deg,expect_away", [(19, False), (21, True)])
def test_head_angle_threshold(deg, expect_away):
    tracker, _ = calibrated()
    events = feed(tracker, facing(deg), 3000, 8000)
    assert any(e["type"] == "away" for e in events) is expect_away


def test_calibrated_off_axis_pose_is_not_away_but_looking_further_down_is():
    tracker = AttentionTracker(CONFIG)
    feed(tracker, facing(0, pitch_deg=-15), 0, 2500)  # webcam below eye level
    assert feed(tracker, facing(0, pitch_deg=-15), 3000, 8000) == []
    phone = feed(tracker, facing(0, pitch_deg=-55), 11500, 5000)
    assert any(e["type"] == "away" for e in phone)


def test_eyes_looking_well_off_the_screen_is_away_even_with_head_still():
    tracker, _ = calibrated()
    events = feed(tracker, facing(0, gaze_h=0.8), 3000, 5000)
    away = next(e for e in events if e["type"] == "away")
    assert away["reason"] == "eyes-off-screen"


def test_small_gaze_shift_is_not_away():
    tracker, _ = calibrated()
    assert feed(tracker, facing(0, gaze_h=0.58), 3000, 10000) == []


def test_vertical_gaze_shift_is_away():
    tracker, _ = calibrated()
    events = feed(tracker, facing(0, gaze_v=0.9), 3000, 5000)
    assert any(e["type"] == "away" for e in events)


def test_smoothing_keeps_a_noisy_steady_look_from_being_broken_up():
    # Eyes are off to the side, but the tracking drops back to centre for two quick frames now and then.
    pattern = [0.8] * 4 + [0.5] * 2 + [0.8] * 4

    def run(smooth_ms):
        tracker = AttentionTracker(TrackerConfig(gaze_smooth_ms=smooth_ms))
        feed(tracker, facing(0), 0, 2500)
        events, t = [], 3000
        for _ in range(4):
            for gaze in pattern:
                events += tracker.update(facing(0, gaze_h=gaze), t)
                t += 250
        return [e["type"] for e in events]

    assert "away" not in run(smooth_ms=0)  # every dip ends the episode before 5s
    assert "away" in run(smooth_ms=1000)


def test_smoothing_does_not_delay_detection_of_a_look_that_starts_and_stays():
    tracker = AttentionTracker(TrackerConfig(gaze_smooth_ms=1000))
    feed(tracker, facing(0), 0, 2500)
    away = next(e for e in feed(tracker, facing(0, gaze_h=0.8), 3000, 7000, step=250) if e["type"] == "away")
    assert away["since"] <= 3000 + 1000  # the median flips within about a second, not several


def test_gaze_is_measured_from_the_calibrated_baseline():
    tracker = AttentionTracker(CONFIG)
    feed(tracker, facing(0, gaze_h=0.6), 0, 2500)  # naturally off-centre eyes
    assert feed(tracker, facing(0, gaze_h=0.6), 3000, 10000) == []


def test_blinking_does_not_count_as_away():
    tracker, _ = calibrated()
    assert feed(tracker, facing(0, blinking=True), 3000, 1500) == []
    assert feed(tracker, facing(0), 5000, 3000) == []


def test_eyes_shut_for_long_enough_is_away():
    tracker, _ = calibrated()
    events = feed(tracker, facing(0, blinking=True), 3000, 12000)
    away = next(e for e in events if e["type"] == "away")
    assert away["reason"] == "eyes-closed"
    assert away["since"] == 5000  # closed at 3000, counted as away after the 2s blink allowance


def test_recalibrate_mid_episode_closes_it_and_adopts_the_new_pose():
    tracker, _ = calibrated()
    feed(tracker, facing(45), 3000, 5000)
    events = tracker.recalibrate(9000)
    assert kinds(events) == ["returned", "state:calibrating"]
    feed(tracker, facing(45), 9500, 3000)
    assert tracker.state == "attentive"
    assert feed(tracker, facing(45), 12500, 8000) == []


def test_live_readout_reports_what_the_last_frame_measured():
    tracker, _ = calibrated()
    assert tracker.calibration_progress(3000) == 1.0
    tracker.update(facing(12, gaze_h=0.56), 3000)
    assert tracker.live["head_deg"] == pytest.approx(12, abs=0.01)
    assert tracker.live["gaze_h"] == pytest.approx(0.56)
    assert tracker.away_for_ms(3000) == 0


def test_live_readout_tracks_the_away_timer_and_calibration_progress():
    tracker = AttentionTracker(CONFIG)
    assert tracker.calibration_progress(0) == 0.0
    tracker.update(facing(0), 1000)
    tracker.update(facing(0), 2250)
    assert tracker.calibration_progress(2250) == pytest.approx(0.5)

    tracker, _ = calibrated()
    tracker.update(facing(45), 3000)
    tracker.update(facing(45), 4500)
    assert tracker.away_for_ms(4500) == 1500
    assert tracker.live["head_deg"] == pytest.approx(45, abs=0.01)


def test_angle_between_identical_vectors_is_zero():
    v = np.array([0.0, 0.0, 1.0])
    assert angle_between_deg(v, v) == 0.0


def test_config_from_extension_keys():
    config = TrackerConfig.from_dict({"awayThresholdMs": 3000, "angleThresholdDeg": 25, "returnFrames": 3})
    assert (config.away_threshold_ms, config.angle_threshold_deg, config.return_frames) == (3000, 25, 3)
    assert config.calibration_ms == TrackerConfig().calibration_ms


@pytest.mark.parametrize("bad", [{"awayThresholdMs": 0}, {"returnFrames": 0}, {"awayThresholdMs": "soon"}])
def test_config_rejects_nonsense(bad):
    with pytest.raises(ValueError):
        TrackerConfig.from_dict(bad)
