"""Generate SYNTHETIC labelled sessions in the same format as real recordings.

For testing the analysis pipeline before real data exists. The poses below are
assumptions about how people move, so anything measured on this data says
nothing about how well the detector works on real people. Tune on recordings from
`python -m anchor_attention.record`.

    python synthetic.py --out data/synthetic-1.csv --seed 1
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from anchor_attention.protocol import COLUMNS, DEFAULT_PROTOCOL  # noqa: E402

FPS = 8
RAMP_S = 0.6  # a step's pose is reached gradually, like a real head turning

# (yaw degrees, pitch degrees, gaze_h, gaze_v, face visible). Pitch -8 stands for a
# webcam that sits a little below eye level.
SCREEN = (0.0, -8.0, 0.50, 0.50, True)
POSES = {
    "glance-left": (35.0, -8.0, 0.72, 0.50, True),
    "glance-right": (-35.0, -8.0, 0.28, 0.50, True),
    "head-left": (50.0, -8.0, 0.70, 0.50, True),
    "eyes-only-right": (2.0, -8.0, 0.12, 0.50, True),
    "eyes-only-left": (-2.0, -8.0, 0.88, 0.50, True),
    "phone": (0.0, -55.0, 0.50, 0.85, True),
    "leave-frame": (0.0, -8.0, 0.50, 0.50, False),
}


def _forward(yaw_deg: float, pitch_deg: float) -> tuple[float, float, float]:
    yaw, pitch = math.radians(yaw_deg), math.radians(pitch_deg)
    return (math.sin(yaw) * math.cos(pitch), math.sin(pitch), math.cos(yaw) * math.cos(pitch))


def generate(seed: int = 0, protocol=DEFAULT_PROTOCOL, fps: int = FPS) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    previous = SCREEN
    frame_index = 0
    blink_frames_left = 0

    for phase in protocol:
        target = POSES.get(phase.name, SCREEN)
        for i in range(int(phase.seconds * fps)):
            ramp = min(1.0, (i / fps) / RAMP_S)
            yaw, pitch, gaze_h, gaze_v = (p + (t - p) * ramp for p, t in zip(previous[:4], target[:4]))
            present = target[4] if ramp >= 0.5 else previous[4]
            t_s = frame_index / fps

            if phase.name == "read":  # eyes wander over the page
                gaze_h += 0.08 * math.sin(2 * math.pi * t_s / 4)
                gaze_v += 0.06 * math.sin(2 * math.pi * t_s / 5 + 1)

            if blink_frames_left > 0:
                blink_frames_left -= 1
                blinking = True
            elif rng.random() < 0.03:
                blink_frames_left = int(rng.integers(0, 2))
                blinking = True
            else:
                blinking = False

            if present:
                fx, fy, fz = _forward(yaw + rng.normal(0, 3), pitch + rng.normal(0, 3))
                row = [fx, fy, fz, gaze_h + rng.normal(0, 0.03), gaze_v + rng.normal(0, 0.04)]
            else:
                row = [np.nan] * 5
            rows.append([int(t_s * 1000), int(present), *row, int(blinking and present), phase.label, phase.name])
            frame_index += 1
        previous = target

    return pd.DataFrame(rows, columns=COLUMNS)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    generate(args.seed).to_csv(args.out, index=False, float_format="%.5f")
    print(f"Wrote synthetic session to {args.out}")


if __name__ == "__main__":
    main()
