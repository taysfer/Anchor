"""Watch the attention tracker work, live.

    python -m anchor_attention.preview

Opens a window showing your camera with the tracker's view drawn on top: face,
irises, a head-direction arrow, and bars for head turn, eye gaze and the away
timer against their thresholds. Keys: r = recalibrate (look at the screen first),
q or Esc = quit. The video stays in this window; nothing is saved or sent.

The thresholds shown are the defaults in TrackerConfig, which match the extension.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2

from .camera import CameraLost, NoCamera, frame_stream
from .config import MODEL_PATH, camera_source
from .gaze import FaceAnalyzer
from .overlay import draw_overlay
from .tracker import AttentionTracker, TrackerConfig

WINDOW = "Anchor attention preview"
PREVIEW_FPS = 15  # smoother than the 8 fps the live server uses


def run(source: int | str, mirror: bool, scale: float, snapshot: Path | None, snapshot_after_s: float) -> None:
    analyzer = FaceAnalyzer(MODEL_PATH)
    tracker = AttentionTracker(TrackerConfig())
    frames = frame_stream(source, PREVIEW_FPS)
    started = time.monotonic()
    try:
        for frame in frames:
            now_ms = int(time.time() * 1000)
            reading = analyzer.analyze(frame, int(time.monotonic() * 1000))
            tracker.update(reading, now_ms)
            view = draw_overlay(frame, analyzer.last_landmarks, reading, tracker, now_ms, mirror=mirror, scale=scale)

            if snapshot is not None:
                if time.monotonic() - started >= snapshot_after_s:
                    cv2.imwrite(str(snapshot), view)
                    return
                continue

            cv2.imshow(WINDOW, view)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27) or cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                return
            if key == ord("r"):
                tracker.recalibrate(now_ms)
    finally:
        frames.close()
        analyzer.close()
        cv2.destroyAllWindows()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", default=None, help="camera index or video file (default: ANCHOR_CAMERA_SOURCE or 0)")
    parser.add_argument("--no-mirror", action="store_true", help="show the camera's raw view instead of a mirror")
    parser.add_argument("--scale", type=float, default=1.5, help="window size multiplier (default 1.5)")
    parser.add_argument("--snapshot", type=Path, help="save one annotated frame to this file and exit (for testing)")
    parser.add_argument("--snapshot-after", type=float, default=4.0, help="seconds to run before the snapshot (default 4)")
    args = parser.parse_args(argv)

    source = camera_source() if args.source is None else (int(args.source) if args.source.isdigit() else args.source)
    try:
        run(source, not args.no_mirror, args.scale, args.snapshot, args.snapshot_after)
    except NoCamera:
        print("Could not open the camera. Is another app using it?", file=sys.stderr)
        return 1
    except CameraLost:
        print("The camera stopped delivering frames.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
