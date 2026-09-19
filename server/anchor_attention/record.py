"""Record a labelled attention session to CSV for threshold tuning.

    python -m anchor_attention.record --out ../analysis/data/me-1.csv

You follow an on-screen script (look at the screen, look away, ...), so each row
is labelled by the step you were on. Only numbers are written (face direction,
gaze ratios, blink flag); no frames or images are saved.
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

from .camera import CameraLost, NoCamera, frame_stream
from .config import MODEL_PATH, camera_source
from .gaze import FaceAnalyzer
from .protocol import COLUMNS, PROTOCOLS, format_row, phase_at, total_seconds

RECORD_FPS = 8


def _beep() -> None:
    # You'll be looking away from the screen, so announce each step by sound.
    try:
        import winsound

        winsound.Beep(880, 150)
    except ImportError:
        print("\a", end="", flush=True)


def record(out_path: Path, source: int | str, protocol, beep: bool = True) -> dict:
    analyzer = FaceAnalyzer(MODEL_PATH)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Recording {total_seconds(protocol):.0f}s of steps. Sit where you normally work.")
    for n in (3, 2, 1):
        print(f"Starting in {n}...", flush=True)
        time.sleep(1)

    rows = faces = 0
    start = None
    current = None
    frames = frame_stream(source, RECORD_FPS)
    try:
        with out_path.open("w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(COLUMNS)
            for frame in frames:
                if start is None:
                    start = time.monotonic()
                elapsed = time.monotonic() - start
                phase = phase_at(protocol, elapsed)
                if phase is None:
                    break
                if phase is not current:
                    current = phase
                    print(f"[{phase.seconds:>4.0f}s] {phase.prompt}", flush=True)
                    if beep:
                        _beep()

                reading = analyzer.analyze(frame, int(time.monotonic() * 1000))
                writer.writerow(format_row(int(elapsed * 1000), reading, phase))
                rows += 1
                faces += reading.present
    finally:
        frames.close()
        analyzer.close()

    return {"rows": rows, "face_rate": faces / rows if rows else 0.0}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, required=True, help="CSV file to write")
    parser.add_argument("--protocol", choices=sorted(PROTOCOLS), default="default")
    parser.add_argument("--source", default=None, help="camera index or video file (default: ANCHOR_CAMERA_SOURCE or 0)")
    parser.add_argument("--no-beep", action="store_true")
    args = parser.parse_args(argv)

    source = camera_source() if args.source is None else (int(args.source) if args.source.isdigit() else args.source)
    try:
        result = record(args.out, source, PROTOCOLS[args.protocol], beep=not args.no_beep)
    except NoCamera:
        print("Could not open the camera. Is another app using it?", file=sys.stderr)
        return 1
    except CameraLost:
        print("The camera stopped delivering frames.", file=sys.stderr)
        return 1

    print(f"Wrote {result['rows']} rows to {args.out} (face found in {result['face_rate']:.0%} of frames).")
    if result["face_rate"] < 0.5:
        print("Warning: your face was found in under half the frames. Check lighting and camera position.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
