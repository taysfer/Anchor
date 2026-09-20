import numpy as np
import pytest

from anchor_attention.camera import NoCamera, frame_stream
from anchor_attention.protocol import (
    ATTENTIVE,
    AWAY,
    COLUMNS,
    DEFAULT_PROTOCOL,
    GLANCE,
    PROTOCOLS,
    QUICK_PROTOCOL,
    format_row,
    phase_at,
    total_seconds,
)
from anchor_attention.tracker import Reading


def test_phase_lookup_follows_the_script():
    assert phase_at(QUICK_PROTOCOL, 0).name == "calibrate"
    assert phase_at(QUICK_PROTOCOL, 2.99).name == "calibrate"
    assert phase_at(QUICK_PROTOCOL, 3.0).name == "look-away"
    assert phase_at(QUICK_PROTOCOL, 9.99).name == "look-at-screen"
    assert phase_at(QUICK_PROTOCOL, 10.0) is None
    assert total_seconds(QUICK_PROTOCOL) == 10


@pytest.mark.parametrize("name", sorted(PROTOCOLS))
def test_every_step_has_a_valid_label_and_a_prompt(name):
    for phase in PROTOCOLS[name]:
        assert phase.label in (ATTENTIVE, AWAY, GLANCE)
        assert phase.prompt and phase.seconds > 0


def test_default_script_calibrates_first_and_keeps_glances_shorter_than_the_alert_time():
    assert DEFAULT_PROTOCOL[0].label == ATTENTIVE and DEFAULT_PROTOCOL[0].seconds >= 3
    assert all(p.seconds < 5 for p in DEFAULT_PROTOCOL if p.label == GLANCE)
    assert all(p.seconds > 5 for p in DEFAULT_PROTOCOL if p.label == AWAY)


def test_rows_match_the_csv_columns():
    reading = Reading(present=True, forward=np.array([0.0, 0.0, 1.0]), gaze_h=0.5, gaze_v=0.25, blinking=True)
    row = format_row(1234, reading, DEFAULT_PROTOCOL[0])
    assert len(row) == len(COLUMNS)
    assert dict(zip(COLUMNS, row)) == {
        "t_ms": 1234, "present": 1, "fx": "0.00000", "fy": "0.00000", "fz": "1.00000",
        "gaze_h": "0.50000", "gaze_v": "0.25000", "blinking": 1, "label": "attentive", "phase": "calibrate",
    }


def test_a_missing_face_writes_empty_fields_not_zeros():
    row = dict(zip(COLUMNS, format_row(0, Reading(present=False), DEFAULT_PROTOCOL[0])))
    assert row["present"] == 0
    assert (row["fx"], row["gaze_h"]) == ("", "")


def test_an_unopenable_source_is_reported():
    with pytest.raises(NoCamera):
        next(frame_stream("does-not-exist.mp4", fps=8))
