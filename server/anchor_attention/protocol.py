"""The scripted routine used to record labelled attention sessions.

Recording follows a fixed script (look at the screen, look away, ...), so every
frame gets a ground-truth label without any manual annotation. Pure data and
helpers; no camera or model imports, so the analysis tools can use it too.
"""

from __future__ import annotations

from dataclasses import dataclass

from .tracker import Reading

COLUMNS = ["t_ms", "present", "fx", "fy", "fz", "gaze_h", "gaze_v", "blinking", "label", "phase"]

# label meanings:
#   attentive - looking at the screen; should never raise an alert
#   away      - genuinely not looking; should raise an alert once it lasts long enough
#   glance    - a quick look away that is shorter than the alert time; should NOT alert
ATTENTIVE, AWAY, GLANCE = "attentive", "away", "glance"


@dataclass(frozen=True)
class Phase:
    name: str
    label: str
    seconds: float
    prompt: str


DEFAULT_PROTOCOL = (
    Phase("calibrate", ATTENTIVE, 5, "Look at the middle of your screen"),
    Phase("read", ATTENTIVE, 12, "Read or scroll normally; glance at the corners of the screen"),
    Phase("glance-left", GLANCE, 3, "Quick glance to your left, then straight back"),
    Phase("look-at-screen", ATTENTIVE, 8, "Look at the screen"),
    Phase("head-left", AWAY, 9, "Turn your head and look to your left"),
    Phase("look-at-screen", ATTENTIVE, 8, "Look at the screen"),
    Phase("eyes-only-right", AWAY, 9, "Keep your head still; move only your eyes far to the right"),
    Phase("look-at-screen", ATTENTIVE, 8, "Look at the screen"),
    Phase("phone", AWAY, 9, "Look down at your phone or lap"),
    Phase("look-at-screen", ATTENTIVE, 8, "Look at the screen"),
    Phase("glance-right", GLANCE, 3, "Quick glance to your right, then straight back"),
    Phase("look-at-screen", ATTENTIVE, 8, "Look at the screen"),
    Phase("eyes-only-left", AWAY, 9, "Keep your head still; move only your eyes far to the left"),
    Phase("look-at-screen", ATTENTIVE, 8, "Look at the screen"),
    Phase("leave-frame", AWAY, 9, "Lean out of the camera's view"),
    Phase("look-at-screen", ATTENTIVE, 8, "Look at the screen"),
)

QUICK_PROTOCOL = (
    Phase("calibrate", ATTENTIVE, 3, "Look at the middle of your screen"),
    Phase("look-away", AWAY, 4, "Look away from the screen"),
    Phase("look-at-screen", ATTENTIVE, 3, "Look back at the screen"),
)

# Five minutes of ordinary work with no away steps, for measuring false alarms
# (does natural reading/typing/scrolling ever look like looking away?).
WORK_PROTOCOL = (
    Phase("calibrate", ATTENTIVE, 5, "Look at the middle of your screen"),
    Phase("work", ATTENTIVE, 295, "Work normally (read, type, scroll). Don't stare or perform; just act naturally"),
)

PROTOCOLS = {"default": DEFAULT_PROTOCOL, "quick": QUICK_PROTOCOL, "work": WORK_PROTOCOL}


def total_seconds(protocol) -> float:
    return sum(phase.seconds for phase in protocol)


def phase_at(protocol, elapsed_s: float) -> Phase | None:
    """The phase in progress `elapsed_s` seconds in, or None once the script is over."""
    end = 0.0
    for phase in protocol:
        end += phase.seconds
        if elapsed_s < end:
            return phase
    return None


def _num(value: float | None) -> str:
    return "" if value is None else f"{value:.5f}"


def format_row(t_ms: int, reading: Reading, phase: Phase) -> list:
    forward = reading.forward if reading.forward is not None else (None, None, None)
    return [
        t_ms,
        int(reading.present),
        *(_num(v) for v in forward),
        _num(reading.gaze_h),
        _num(reading.gaze_v),
        int(reading.blinking),
        phase.label,
        phase.name,
    ]
