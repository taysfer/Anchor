"""Tune the attention thresholds against labelled recordings.

    python tune_attention.py data/*.csv --out output

Writes to the output folder:
    report.md      what was measured, the best thresholds, and how they compare to the current ones
    sweep.csv      every threshold combination that was tried
    roc.png        how well each raw signal separates "away" from "attentive" frames
    timeline-*.png each recording's signals with the alarms the current and tuned settings raise
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from attention_eval import (  # noqa: E402
    DEFAULT_GRID,
    TrackerConfig,
    evaluate,
    frame_features,
    load_session,
    phase_runs,
    replay,
    signal_roc,
    sweep,
    tied_for_best,
    usable_sessions,
)

QUICK_GRID = {
    "angle_threshold_deg": [25, 30, 35],
    "gaze_h_threshold": [0.15, 0.20, 0.25],
    "gaze_v_threshold": [0.20, 0.25, 0.30],
    "gaze_smooth_ms": [0, 1000],
    "away_threshold_ms": [4000, 5000],
}

TUNED = ["angle_threshold_deg", "gaze_h_threshold", "gaze_v_threshold", "gaze_smooth_ms", "away_threshold_ms"]
RUN_COLORS = {"away": "#d63b32", "glance": "#e0a90b"}


def _pct(value: float) -> str:
    return "n/a" if pd.isna(value) else f"{value:.0%}"


def _num(value: float, digits: int = 2) -> str:
    return "n/a" if pd.isna(value) else f"{value:.{digits}f}"


def _table(headers: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines)


def _result_row(label: str, config_values: dict, result: dict) -> list[str]:
    return [
        label,
        f"{config_values['angle_threshold_deg']:g}",
        f"{config_values['gaze_h_threshold']:g}",
        f"{config_values['gaze_v_threshold']:g}",
        f"{config_values['gaze_smooth_ms'] / 1000:g}s",
        f"{config_values['away_threshold_ms'] / 1000:g}s",
        f"{int(result['detected'])}/{int(result['away_steps'])} ({_pct(result['recall'])})",
        str(int(result["false_alarms"])),
        _num(result["false_alarms_per_min"]),
        _num(result["median_delay_s"], 1) + "s",
    ]


RESULT_HEADERS = ["", "head angle", "gaze h", "gaze v", "gaze smoothing", "away after", "away steps caught", "false alarms", "per min", "median delay"]


def plot_roc(curves: dict, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(5.5, 5))
    for name, (fpr, tpr, auc) in curves.items():
        ax.plot(fpr, tpr, label=f"{name} (AUC {auc:.2f})")
    ax.plot([0, 1], [0, 1], "--", color="#aaaaaa", label="chance")
    ax.set_xlabel("false positive rate (attentive frames flagged)")
    ax.set_ylabel("true positive rate (away frames flagged)")
    ax.set_title("Which signal separates looking away?")
    ax.legend(loc="lower right")
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def plot_timeline(session, features: pd.DataFrame, current, tuned, current_alarms, tuned_alarms, path: Path) -> None:
    t = features["t_ms"] / 1000
    fig, axes = plt.subplots(3, 1, sharex=True, figsize=(11, 7))
    signals = [
        ("head_deg", "head angle (deg)", current.angle_threshold_deg, tuned.angle_threshold_deg, 90),
        ("gaze_h_dev", "horizontal gaze shift", current.gaze_h_threshold, tuned.gaze_h_threshold, 0.6),
        ("gaze_v_dev", "vertical gaze shift", current.gaze_v_threshold, tuned.gaze_v_threshold, 0.8),
    ]
    for ax, (column, title, now_threshold, tuned_threshold, ceiling) in zip(axes, signals):
        ax.plot(t, features[column].clip(upper=ceiling), color="#333333", linewidth=0.9)
        ax.axhline(now_threshold, color="#888888", linestyle="--", linewidth=1, label=f"current threshold {now_threshold:g}")
        ax.axhline(tuned_threshold, color="#2fa860", linewidth=1, label=f"tuned threshold {tuned_threshold:g}")
        for run in phase_runs(session.frame):
            if run.label in RUN_COLORS:
                ax.axvspan(run.start_ms / 1000, run.end_ms / 1000, color=RUN_COLORS[run.label], alpha=0.15, linewidth=0)
        ax.set_ylabel(title)
        ax.legend(loc="upper right", fontsize=8)
    for alarm in current_alarms:
        axes[0].axvline(alarm.emitted_ms / 1000, color="#888888", linestyle="--", linewidth=1.5)
    for alarm in tuned_alarms:
        axes[0].axvline(alarm.emitted_ms / 1000, color="#2fa860", linewidth=1.5)
    axes[0].set_title(f"{session.name}: red = away step, amber = quick glance; vertical lines = alarms (dashed current, green tuned)")
    axes[-1].set_xlabel("seconds")
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("paths", nargs="+", type=Path, help="recording CSV files")
    parser.add_argument("--out", type=Path, default=Path("output"))
    parser.add_argument("--quick", action="store_true", help="try a much smaller grid")
    parser.add_argument("--false-alarm-weight", type=float, default=0.5, help="score = recall - weight * false alarms per minute")
    args = parser.parse_args(argv)

    try:
        loaded = [load_session(path) for path in args.paths]
    except (OSError, ValueError) as error:
        print(f"Could not read recordings: {error}", file=sys.stderr)
        return 1

    base = TrackerConfig()
    sessions, calibrated_at, skipped = usable_sessions(loaded, base)
    if not sessions:
        print("None of the recordings had enough face time to calibrate on.", file=sys.stderr)
        return 1

    args.out.mkdir(parents=True, exist_ok=True)
    features = [frame_features(s, base) for s in sessions]
    curves = signal_roc(features)
    plot_roc(curves, args.out / "roc.png")

    grid = QUICK_GRID if args.quick else DEFAULT_GRID
    table = sweep(sessions, calibrated_at, grid, base, args.false_alarm_weight)
    table.to_csv(args.out / "sweep.csv", index=False)

    current_result = evaluate(sessions, base, calibrated_at)
    best_row = table.iloc[0]
    best_values = {name: best_row[name] for name in TUNED}
    best = replace(base, **{k: (int(v) if k == "away_threshold_ms" else float(v)) for k, v in best_values.items()})

    for session, feature in zip(sessions, features):
        plot_timeline(
            session, feature, base, best, replay(session, base), replay(session, best), args.out / f"timeline-{session.name}.png"
        )

    total_steps = int(best_row["away_steps"])
    report = [
        "# Attention threshold tuning",
        "",
        f"Recordings: {len(sessions)} ({', '.join(s.name for s in sessions)}); {total_steps} labelled away steps in total.",
        f"Grid: {len(table)} combinations. Score = recall - {args.false_alarm_weight:g} x false alarms per quiet minute.",
    ]
    if skipped:
        report.append(f"Skipped (never calibrated, no face found): {', '.join(skipped)}.")

    ties = tied_for_best(table)
    if ties > 1:
        report.append(
            f"{ties} of {len(table)} combinations tie for the best score. The one closest to the current settings is shown as "
            "'tuned'; the data cannot tell these apart, so record more (especially quick glances near the alert time) or pick from `sweep.csv`."
        )

    report += [
        "",
        "## Current settings vs tuned",
        "",
        _table(
            RESULT_HEADERS,
            [
                _result_row("current", {n: getattr(base, n) for n in TUNED}, current_result),
                _result_row("tuned", best_values, best_row.to_dict()),
            ],
        ),
        "",
        "## Ten best combinations",
        "",
        _table(RESULT_HEADERS, [_result_row(f"#{i + 1}", row, row) for i, row in table.head(10).iterrows()]),
        "",
        "## How well each signal separates away frames",
        "",
        _table(["signal", "AUC"], [[name, _num(auc)] for name, (_, _, auc) in curves.items()]),
        "",
        "AUC 1.0 means the signal alone perfectly separates looking away from looking at the screen; 0.5 is chance. See `roc.png`.",
        "",
        "## Applying the result",
        "",
        f"* `extension/shared.js` `ATTENTION_CONFIG`: `angleThresholdDeg: {best.angle_threshold_deg:g}`, `awayThresholdMs: {best.away_threshold_ms}`",
        f"* `server/anchor_attention/tracker.py` `TrackerConfig`: `gaze_h_threshold={best.gaze_h_threshold:g}`, `gaze_v_threshold={best.gaze_v_threshold:g}`, `gaze_smooth_ms={best.gaze_smooth_ms:g}` (the in-browser engine has no gaze signal)",
        "",
        "## Caveats",
        "",
        "* This is only as good as the recordings. A handful of short sessions from one person on one camera will overfit; record more, in different lighting and sitting positions, before trusting the numbers.",
        "* Steps are scripted, so real distractions (long, slow, half-hearted) are underrepresented.",
        "* Frames right after a step change and frames mid-blink are not scored.",
    ]
    (args.out / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")

    print(f"Current: {current_result['detected']}/{current_result['away_steps']} away steps caught, {current_result['false_alarms']} false alarms")
    print(f"Tuned:   {int(best_row['detected'])}/{total_steps} away steps caught, {int(best_row['false_alarms'])} false alarms")
    print(f"Report written to {args.out / 'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
