"""Evaluate and tune the attention thresholds against labelled recordings.

Recordings come from `python -m anchor_attention.record` (see server/). Every row
is labelled by the scripted step being performed:

    attentive  looking at the screen        -> must not alert
    away       genuinely not looking        -> should alert once it lasts long enough
    glance     a quick look away            -> must not alert (shorter than the alert time)

Two levels of evaluation:

* frame level: how well each raw signal (head angle, eye gaze) separates
  attentive frames from away frames (ROC curves)
* episode level: replay the recording through the real AttentionTracker with a
  given config and count detected away steps, false alarms, and detection delay
"""

from __future__ import annotations

import itertools
import sys
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from anchor_attention.protocol import ATTENTIVE, AWAY, COLUMNS, GLANCE  # noqa: E402
from anchor_attention.tracker import AttentionTracker, Reading, TrackerConfig  # noqa: E402

# People are still moving for a moment after each step changes, so frames this
# soon after a change aren't held against the detector.
GUARD_MS = 1500


@dataclass
class Session:
    name: str
    frame: pd.DataFrame
    readings: list[Reading]

    @property
    def times(self) -> list[int]:
        return self.frame["t_ms"].tolist()


@dataclass(frozen=True)
class Run:
    start_ms: int
    end_ms: int
    label: str
    phase: str


@dataclass(frozen=True)
class Alarm:
    emitted_ms: int
    since_ms: int
    reason: str


def load_session(path: Path | str) -> Session:
    frame = pd.read_csv(path)
    missing = set(COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError(f"{path}: missing columns {sorted(missing)}")
    frame["present"] = frame["present"].astype(bool)
    frame["blinking"] = frame["blinking"].astype(bool)

    readings = []
    for row in frame.itertuples(index=False):
        if not row.present:
            readings.append(Reading(present=False))
            continue
        forward = np.array([row.fx, row.fy, row.fz], dtype=float)
        readings.append(
            Reading(
                present=True,
                forward=None if np.isnan(forward).any() else forward,
                gaze_h=None if pd.isna(row.gaze_h) else float(row.gaze_h),
                gaze_v=None if pd.isna(row.gaze_v) else float(row.gaze_v),
                blinking=bool(row.blinking),
            )
        )
    return Session(Path(path).stem, frame, readings)


def _run_ids(frame: pd.DataFrame) -> pd.Series:
    """Number consecutive rows that belong to the same scripted step."""
    key = frame["phase"].astype(str) + "|" + frame["label"].astype(str)
    return (key != key.shift()).cumsum()


def phase_runs(frame: pd.DataFrame) -> list[Run]:
    runs = []
    for _, group in frame.groupby(_run_ids(frame), sort=True):
        runs.append(
            Run(int(group["t_ms"].min()), int(group["t_ms"].max()), str(group["label"].iloc[0]), str(group["phase"].iloc[0]))
        )
    return runs


def calibrate(session: Session, config: TrackerConfig) -> tuple[dict | None, int | None]:
    """The baseline pose the tracker settles on, and when it finished calibrating."""
    tracker = AttentionTracker(config)
    for reading, t_ms in zip(session.readings, session.times):
        tracker.update(reading, t_ms)
        if tracker.state != "calibrating":
            return tracker.baseline, t_ms
    return None, None


# ---------------------------------------------------------------------------
# Frame level
# ---------------------------------------------------------------------------


def frame_features(session: Session, config: TrackerConfig) -> pd.DataFrame | None:
    """Per-frame deviation from the calibrated pose, plus which frames are fair to score.

    Frames without a face score as maximally deviant, since that is what "away" means.
    """
    baseline, calibrated_at = calibrate(session, config)
    if baseline is None:
        return None

    frame = session.frame
    forward = frame[["fx", "fy", "fz"]].to_numpy(dtype=float)
    absent = ~frame["present"].to_numpy() | np.isnan(forward).any(axis=1)

    head = np.degrees(np.arccos(np.clip(np.nan_to_num(forward) @ baseline["forward"], -1.0, 1.0)))
    head[absent] = 180.0

    def gaze_deviation(column: str, base: float | None) -> np.ndarray:
        if base is None:
            return np.zeros(len(frame))
        deviation = np.abs(frame[column].to_numpy(dtype=float) - base)
        deviation = np.nan_to_num(deviation, nan=0.0)  # unknown gaze is not evidence of looking away
        deviation[absent] = 1.0
        return deviation

    run_start = frame.groupby(_run_ids(frame))["t_ms"].transform("min")

    usable = (
        (frame["t_ms"] > calibrated_at)
        & (frame["t_ms"] - run_start >= GUARD_MS)
        & ~frame["blinking"]
        & frame["label"].isin([ATTENTIVE, AWAY])
    )
    return pd.DataFrame(
        {
            "t_ms": frame["t_ms"],
            "head_deg": head,
            "gaze_h_dev": gaze_deviation("gaze_h", baseline["gaze_h"]),
            "gaze_v_dev": gaze_deviation("gaze_v", baseline["gaze_v"]),
            "usable": usable.to_numpy(),
            "away": (frame["label"] == AWAY).to_numpy(),
        }
    )


def roc_curve(scores: np.ndarray, positives: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    """False/true positive rates for 'score >= threshold', and the area under the curve."""
    positives = positives.astype(bool)
    order = np.argsort(-scores, kind="stable")
    hits = positives[order]
    tpr = np.concatenate([[0.0], np.cumsum(hits) / max(hits.sum(), 1)])
    fpr = np.concatenate([[0.0], np.cumsum(~hits) / max((~hits).sum(), 1)])
    return fpr, tpr, float(np.sum(np.diff(fpr) * (tpr[1:] + tpr[:-1]) / 2))


def signal_roc(features: list[pd.DataFrame]) -> dict[str, tuple[np.ndarray, np.ndarray, float]]:
    """ROC for each raw signal over all sessions' usable frames."""
    usable = pd.concat([f[f["usable"]] for f in features], ignore_index=True)
    return {
        name: roc_curve(usable[column].to_numpy(), usable["away"].to_numpy())
        for name, column in (("head angle", "head_deg"), ("gaze horizontal", "gaze_h_dev"), ("gaze vertical", "gaze_v_dev"))
    }


# ---------------------------------------------------------------------------
# Episode level
# ---------------------------------------------------------------------------


def replay(session: Session, config: TrackerConfig) -> list[Alarm]:
    tracker = AttentionTracker(config)
    alarms = []
    for reading, t_ms in zip(session.readings, session.times):
        for event in tracker.update(reading, t_ms):
            if event["type"] == "away":
                alarms.append(Alarm(t_ms, event["since"], event["reason"]))
    return alarms


def episode_counts(runs: list[Run], alarms: list[Alarm], calibrated_at: int) -> dict:
    """Score alarms against the labelled steps.

    An alarm is correct if the episode it reports began during an away step; an
    away step is detected if at least one correct alarm covers it.
    """
    away_runs = [r for r in runs if r.label == AWAY and r.end_ms > calibrated_at]

    def covers(alarm: Alarm, run: Run) -> bool:
        return run.start_ms - GUARD_MS <= alarm.since_ms <= run.end_ms

    latencies_ms, detected = [], 0
    for run in away_runs:
        hits = [a for a in alarms if covers(a, run)]
        if hits:
            detected += 1
            latencies_ms.append(min(a.emitted_ms for a in hits) - run.start_ms)

    correct = sum(any(covers(a, r) for r in away_runs) for a in alarms)
    quiet_ms = sum(
        max(0, r.end_ms - max(r.start_ms, calibrated_at)) for r in runs if r.label in (ATTENTIVE, GLANCE)
    )
    return {
        "away_steps": len(away_runs),
        "detected": detected,
        "alarms": len(alarms),
        "false_alarms": len(alarms) - correct,
        "quiet_ms": quiet_ms,
        "latencies_ms": latencies_ms,
    }


def evaluate(sessions: list[Session], config: TrackerConfig, calibrated_at: dict[str, int]) -> dict:
    totals = {"away_steps": 0, "detected": 0, "alarms": 0, "false_alarms": 0, "quiet_ms": 0}
    latencies: list[int] = []
    for session in sessions:
        counts = episode_counts(phase_runs(session.frame), replay(session, config), calibrated_at[session.name])
        for key in totals:
            totals[key] += counts[key]
        latencies += counts["latencies_ms"]

    quiet_min = totals["quiet_ms"] / 60000
    return {
        "recall": totals["detected"] / totals["away_steps"] if totals["away_steps"] else float("nan"),
        "false_alarms": totals["false_alarms"],
        "false_alarms_per_min": totals["false_alarms"] / quiet_min if quiet_min else float("nan"),
        "median_delay_s": float(np.median(latencies)) / 1000 if latencies else float("nan"),
        "detected": totals["detected"],
        "away_steps": totals["away_steps"],
    }


def usable_sessions(sessions: list[Session], base: TrackerConfig) -> tuple[list[Session], dict[str, int], list[str]]:
    """Drop sessions the tracker could never calibrate on (no face), and say which."""
    kept, calibrated_at, skipped = [], {}, []
    for session in sessions:
        _, when = calibrate(session, base)
        if when is None:
            skipped.append(session.name)
        else:
            kept.append(session)
            calibrated_at[session.name] = when
    return kept, calibrated_at, skipped


DEFAULT_GRID = {
    "angle_threshold_deg": [20, 25, 30, 35, 40],
    "gaze_h_threshold": [0.10, 0.15, 0.20, 0.25, 0.30],
    "gaze_v_threshold": [0.15, 0.20, 0.25, 0.30, 0.40],
    "gaze_smooth_ms": [0, 500, 1000, 1500],
    "away_threshold_ms": [3000, 4000, 5000, 6000],
}


def sweep(
    sessions: list[Session],
    calibrated_at: dict[str, int],
    grid: dict[str, list],
    base: TrackerConfig | None = None,
    false_alarm_weight: float = 0.5,
) -> pd.DataFrame:
    """Evaluate every combination in `grid`, best first.

    score = recall - false_alarm_weight * false alarms per quiet minute

    Ties (common on small or easy datasets) go to the combination closest to
    `base`: without evidence that a change helps, don't change the settings.
    """
    base = base or TrackerConfig()
    names = list(grid)
    rows = []
    for values in itertools.product(*(grid[n] for n in names)):
        config = replace(base, **dict(zip(names, values)))
        result = evaluate(sessions, config, calibrated_at)
        rows.append({**dict(zip(names, values)), **result})

    table = pd.DataFrame(rows)
    table["score"] = table["recall"] - false_alarm_weight * table["false_alarms_per_min"]
    spans = {n: (max(grid[n]) - min(grid[n])) or 1 for n in names}
    table["distance_from_current"] = sum(abs(table[n] - getattr(base, n)) / spans[n] for n in names)

    table["_score_rounded"] = table["score"].round(3)
    table = table.sort_values(
        ["_score_rounded", "distance_from_current", "median_delay_s"], ascending=[False, True, True], ignore_index=True
    )
    return table.drop(columns="_score_rounded")


def tied_for_best(table: pd.DataFrame) -> int:
    """How many combinations score the same as the best one (to 3 decimals)."""
    return int((table["score"].round(3) == round(table.iloc[0]["score"], 3)).sum())
