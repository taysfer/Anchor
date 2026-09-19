# analysis

Tools for measuring how well the attention detector works and tuning its thresholds from real, labelled recordings.

```
record (server/)  ->  data/*.csv  ->  tune_attention.py  ->  output/report.md + plots
```

## 1. Record sessions

The recorder walks you through a script (look at the screen, turn your head away, move only your eyes, look at your phone, lean out of frame, quick glances...), so every frame is labelled by the step you were on with no manual annotation. It beeps at each step because you will be looking away from the screen.

```powershell
cd server
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m anchor_attention.record --out ..\analysis\data\me-1.csv
```

(The first three lines are one-time setup. If `activate` is blocked by PowerShell's execution policy, run `Set-ExecutionPolicy -Scope Process Bypass` first. Use Python 3.11; MediaPipe only publishes wheels for some versions.)

It takes about two minutes. Only numbers are written (face direction, gaze ratios, blink flag); no images or video are saved. `data/` is git-ignored since it is a record of your head and eye movements.

Record several sessions: different lighting, different distances from the screen, glasses on and off, and ideally different people. A handful of takes from one person on one camera will overfit.

The default script has only a few short "reading" stretches, so it says little about false alarms. Also record a few minutes of ordinary work to see whether natural eye movement ever looks like looking away:

```powershell
python -m anchor_attention.record --out ..\analysis\data\work-1.csv --protocol work
```

Tune with these and the default-script recordings together (a work-only recording has no away steps, so it only contributes false-alarm counts).

## 2. Tune

```powershell
cd ..\analysis
pip install -r requirements.txt
python tune_attention.py data\*.csv --out output
```

(Run this in the same activated environment from step 1, or any environment with these requirements installed.)

(`--quick` tries a much smaller grid.) The output folder gets:

| File | What it shows |
| --- | --- |
| `report.md` | Current settings vs tuned settings, the ten best combinations, and how to apply the result |
| `sweep.csv` | Every threshold combination that was tried, with recall, false alarms, and delay |
| `roc.png` | How well each raw signal (head angle, horizontal gaze, vertical gaze) separates looking away from looking at the screen |
| `timeline-*.png` | Each recording's signals over time with the alarms the current and tuned settings raise, for checking that the numbers make sense |

### How it is scored

Recordings are replayed through the real `AttentionTracker` (the same code the server runs), once per combination of head-angle threshold, horizontal and vertical gaze thresholds, and how long you must be away before an alert.

* **recall**: the fraction of `away` steps that raised an alert
* **false alarms**: alerts whose episode began during an `attentive` or `glance` step (quick glances are shorter than the alert time and should not alert)
* **score** = recall - 0.5 x false alarms per quiet minute (`--false-alarm-weight` changes the trade-off)
* **ties** go to the combination closest to the current settings, and the report says how many tied

Frames just after a step change and frames mid-blink are not scored, and neither is the calibration period.

## Synthetic data

`synthetic.py` generates fake sessions in the same format, so the pipeline can be tested before real recordings exist:

```powershell
python synthetic.py --out data\synthetic-1.csv --seed 1
```

It encodes assumptions about how people move, so numbers measured on it say nothing about real accuracy. Do not report results from it.

## Tests

```powershell
python -m pytest
```
