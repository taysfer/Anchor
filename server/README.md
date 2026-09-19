# server

Python backend for Anchor. Right now it contains the **attention server**: an eye-gaze and head-pose tracker that the extension can use instead of its built-in browser tracker. The semantic drift API (embeddings, similarity scoring) will live here too; until then the extension uses the keyword stub in `extension/shared.js`.

## Attention server

Modeled on [GazeTracking](https://github.com/antoinelame/GazeTracking) (pupil position gives a horizontal/vertical gaze ratio; a blink check ignores blinks), but built on MediaPipe's Face Landmarker instead of dlib. The model already tracks the iris, so there is no pupil-thresholding step and no C++ toolchain to install, and it also provides head pose.

A person counts as **away** when, for more than 5 seconds (tunable), their face is gone, their head is turned more than 20 degrees from where it was at the start, their eyes have been shut for over 2 seconds, or their eyes point away from where they were at the start (gaze is median-filtered over 1 second first, so tracking flicker doesn't break up a steady look). The first ~2.5 seconds of a session calibrate what "looking at the screen" means for you.

Compared with the in-browser engine it adds eye gaze, at the cost of running a local process.

### Run it

```powershell
cd server
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn app:app --host 127.0.0.1 --port 8765
```

Then in the extension popup: turn on **Watch for looking away**, choose **Python server**, and it should say "Python server connected". Tested with Python 3.11 and MediaPipe 1.0.1; MediaPipe only publishes wheels for some Python versions, so if `pip install` fails use 3.11. The face model is shared with the extension (`extension/vendor/mediapipe/face_landmarker.task`).

### Watch it track you, live

```powershell
python -m anchor_attention.preview
```

Opens a window with your camera (mirrored) and the tracker's view drawn on top: your face outline, eyes and irises, an arrow showing which way your head has turned from where you calibrated, and live bars for head turn, sideways and up/down eye movement, and the away timer, each against its alert threshold. The state (calibrating, focused, drifting, looking away) is shown at the top, and the frame gets a red border once the alert would fire. Keys: `r` recalibrate (look at the screen first), `q` or Esc to quit.

It runs the same detector and default thresholds as the server. The video stays in that window and is not saved or sent anywhere.

### Privacy and security

* Frames are analysed in memory and never saved or sent anywhere. Only small events (started looking away, came back) leave the analyser.
* The camera is only open while the extension is connected and a session has started. Ending the session, or closing the connection, releases it.
* The server binds to `127.0.0.1` and **rejects WebSocket connections that do not come from a `chrome-extension://` origin**, so websites you visit cannot connect to it and turn your camera on. To lock it to your own install, set `ANCHOR_ALLOWED_ORIGINS=chrome-extension://<your-extension-id>`.

### Configuration (environment variables)

| Variable | Default | Meaning |
| --- | --- | --- |
| `ANCHOR_CAMERA_SOURCE` | `0` | Camera index, or a path to a video file (loops; handy for testing and demos) |
| `ANCHOR_FACE_MODEL` | bundled model | Path to `face_landmarker.task` |
| `ANCHOR_ALLOWED_ORIGINS` | any `chrome-extension://` | Comma-separated exact origins to allow |

Head-angle, away-duration and calibration thresholds come from the extension's `ATTENTION_CONFIG` (`extension/shared.js`); the gaze thresholds are in `TrackerConfig` (`anchor_attention/tracker.py`).

### Protocol

One WebSocket per session at `ws://127.0.0.1:8765/attention/ws`.

Extension to server: `{"type": "start", "config": {...}}`, `{"type": "recalibrate"}`, `{"type": "stop"}`.

Server to extension: `{"type": "status", "status": "starting|active|error", "error": "..."}`, `{"type": "state", "state": "calibrating|attentive|away"}`, `{"type": "away", "since": <ms>, "reason": "no-face|head-turned|eyes-off-screen|eyes-closed"}`, `{"type": "returned", "since": <ms>, "until": <ms>, "durationMs": <ms>}`, and a `ping` every 20 seconds that keeps the extension's service worker awake. `GET /health` reports whether the server is up.

### Tests

```powershell
pip install -r requirements-dev.txt
python -m pytest
```

The gaze thresholds are starting values and have not been tuned against real recorded sessions. Record labelled sessions with `python -m anchor_attention.record --out ..\analysis\data\me-1.csv` and tune them with the tools in [analysis/](../analysis/README.md).
