import math

import numpy as np
import pandas as pd
import pytest

import tune_attention
from anchor_attention.protocol import COLUMNS, DEFAULT_PROTOCOL
from attention_eval import (
    Alarm,
    Run,
    TrackerConfig,
    calibrate,
    episode_counts,
    evaluate,
    frame_features,
    load_session,
    phase_runs,
    replay,
    roc_curve,
    signal_roc,
    sweep,
    tied_for_best,
    usable_sessions,
)
from synthetic import generate

BASE = TrackerConfig()


@pytest.fixture(scope="module")
def synthetic_path(tmp_path_factory):
    path = tmp_path_factory.mktemp("data") / "synthetic-1.csv"
    generate(seed=1).to_csv(path, index=False, float_format="%.5f")
    return path


@pytest.fixture(scope="module")
def session(synthetic_path):
    return load_session(synthetic_path)


@pytest.fixture(scope="module")
def calibrated_at(session):
    return {session.name: calibrate(session, BASE)[1]}


def test_synthetic_sessions_are_reproducible():
    pd.testing.assert_frame_equal(generate(seed=3), generate(seed=3))
    assert not generate(seed=3).equals(generate(seed=4))


def test_loading_a_recording_keeps_every_row_and_step(session):
    assert len(session.readings) == len(session.frame)
    runs = phase_runs(session.frame)
    assert [r.phase for r in runs] == [p.name for p in DEFAULT_PROTOCOL]
    assert [r.label for r in runs] == [p.label for p in DEFAULT_PROTOCOL]


def test_missing_columns_are_reported(tmp_path):
    path = tmp_path / "bad.csv"
    pd.DataFrame({"t_ms": [0]}).to_csv(path, index=False)
    with pytest.raises(ValueError, match="missing columns"):
        load_session(path)


def test_calibration_recovers_the_resting_pose(session):
    baseline, calibrated_at = calibrate(session, BASE)
    expected = np.array([0.0, math.sin(math.radians(-8)), math.cos(math.radians(-8))])
    assert math.degrees(math.acos(float(baseline["forward"] @ expected))) < 3
    assert baseline["gaze_h"] == pytest.approx(0.5, abs=0.05)
    assert 2000 < calibrated_at < 6000


def test_a_recording_with_no_face_cannot_be_calibrated(tmp_path):
    frame = generate(seed=0)
    frame["present"] = 0
    path = tmp_path / "empty.csv"
    frame.to_csv(path, index=False)
    kept, _, skipped = usable_sessions([load_session(path)], BASE)
    assert kept == [] and skipped == ["empty"]


def test_roc_curve_extremes():
    labels = np.array([0, 0, 0, 1, 1, 1], dtype=bool)
    assert roc_curve(np.array([0.1, 0.2, 0.3, 0.7, 0.8, 0.9]), labels)[2] == pytest.approx(1.0)
    assert roc_curve(np.array([0.9, 0.8, 0.7, 0.3, 0.2, 0.1]), labels)[2] == pytest.approx(0.0)
    noise = np.random.default_rng(0)
    big = noise.random(4000)
    assert roc_curve(big, noise.random(4000) > 0.5)[2] == pytest.approx(0.5, abs=0.05)


def test_head_angle_separates_synthetic_away_frames(session):
    features = frame_features(session, BASE)
    assert features["usable"].sum() > 100
    assert signal_roc([features])["head angle"][2] > 0.7


def test_episode_counts_score_alarms_against_labelled_steps():
    runs = [
        Run(0, 10000, "attentive", "look-at-screen"),
        Run(10000, 20000, "away", "phone"),
        Run(20000, 30000, "attentive", "look-at-screen"),
    ]
    alarms = [Alarm(emitted_ms=15000, since_ms=10000, reason="head-turned"), Alarm(28000, 26000, "no-face")]
    counts = episode_counts(runs, alarms, calibrated_at=2000)
    assert (counts["away_steps"], counts["detected"]) == (1, 1)
    assert counts["false_alarms"] == 1
    assert counts["latencies_ms"] == [5000]
    assert counts["quiet_ms"] == 8000 + 10000


def test_an_alarm_for_an_episode_that_began_in_an_away_step_counts_even_if_it_fires_later():
    runs = [Run(0, 10000, "attentive", "a"), Run(10000, 16000, "away", "b"), Run(16000, 30000, "attentive", "c")]
    counts = episode_counts(runs, [Alarm(emitted_ms=17000, since_ms=12000, reason="x")], calibrated_at=0)
    assert counts["detected"] == 1 and counts["false_alarms"] == 0


def test_current_settings_catch_the_synthetic_away_steps(session, calibrated_at):
    result = evaluate([session], BASE, calibrated_at)
    assert result["away_steps"] == 5
    assert result["recall"] == 1.0
    assert result["false_alarms"] == 0


def test_a_too_short_alert_time_turns_quick_glances_into_false_alarms(session, calibrated_at):
    from dataclasses import replace

    eager = evaluate([session], replace(BASE, away_threshold_ms=1500), calibrated_at)
    assert eager["false_alarms"] > 0
    assert eager["median_delay_s"] < evaluate([session], BASE, calibrated_at)["median_delay_s"]


def test_sweep_ranks_best_first_and_penalises_false_alarms(session, calibrated_at):
    grid = {"angle_threshold_deg": [25, 30], "away_threshold_ms": [1500, 5000]}
    table = sweep([session], calibrated_at, grid, BASE, false_alarm_weight=0.5)
    assert list(table["score"]) == sorted(table["score"], reverse=True)
    assert len(table) == 4
    assert table.iloc[0]["away_threshold_ms"] == 5000  # 1500ms alarms on the glances


def test_ties_go_to_the_combination_closest_to_the_current_settings(session, calibrated_at):
    grid = {"angle_threshold_deg": [20, 30, 40], "away_threshold_ms": [3000, 5000]}
    table = sweep([session], calibrated_at, grid, BASE)
    assert tied_for_best(table) > 1
    best = table.iloc[0]
    assert (best["angle_threshold_deg"], best["away_threshold_ms"]) == (BASE.angle_threshold_deg, BASE.away_threshold_ms)


def test_replay_reports_when_each_episode_began(session):
    alarms = replay(session, BASE)
    assert alarms and all(a.emitted_ms >= a.since_ms + BASE.away_threshold_ms for a in alarms)


def test_command_line_writes_report_and_plots(synthetic_path, tmp_path):
    out = tmp_path / "out"
    assert tune_attention.main([str(synthetic_path), "--out", str(out), "--quick"]) == 0
    for name in ("report.md", "sweep.csv", "roc.png", "timeline-synthetic-1.png"):
        assert (out / name).exists(), name
    report = (out / "report.md").read_text(encoding="utf-8")
    assert "Current settings vs tuned" in report and "Caveats" in report


def test_command_line_rejects_missing_files(tmp_path):
    assert tune_attention.main([str(tmp_path / "nope.csv"), "--out", str(tmp_path)]) == 1


def test_columns_match_the_recorder():
    assert set(COLUMNS) <= set(generate(seed=0).columns)
