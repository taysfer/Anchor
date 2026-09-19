// Pure attention logic: turns per-frame face readings into "looked away" /
// "returned" events. No camera, DOM, or chrome.* access here so it can be unit
// tested with synthetic readings.
//
// A reading is { present: boolean, forward?: [x, y, z] } where `forward` is a
// unit vector for the direction the face points.

function normalize(v) {
  const len = Math.hypot(v[0], v[1], v[2]) || 1;
  return [v[0] / len, v[1] / len, v[2] / len];
}

export function angleBetweenDeg(a, b) {
  const dot = a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  return (Math.acos(Math.max(-1, Math.min(1, dot))) * 180) / Math.PI;
}

// MediaPipe's 4x4 face pose matrix is column-major, so indices 8-10 are the
// third column: the face's depth axis, i.e. the direction the face points.
export function forwardAxisFromMatrix(data) {
  return normalize([data[8], data[9], data[10]]);
}

export class AttentionTracker {
  constructor(config) {
    this.awayThresholdMs = config.awayThresholdMs;
    this.angleThresholdDeg = config.angleThresholdDeg;
    this.calibrationMs = config.calibrationMs;
    this.minCalibrationSamples = config.minCalibrationSamples;
    this.returnFrames = config.returnFrames;
    this._reset();
  }

  _reset() {
    this.state = 'calibrating'; // 'calibrating' | 'attentive' | 'away'
    this.baseline = null;
    this.calibrationSamples = [];
    this.calibrationStart = null;
    this.awaySince = null;
    this.warned = false;
    this.attentiveStreak = 0;
  }

  // Start over, treating the current pose as "looking at the screen".
  recalibrate(now) {
    const events = [];
    if (this.warned) {
      events.push({ type: 'returned', since: this.awaySince, until: now, durationMs: now - this.awaySince });
    }
    this._reset();
    events.push({ type: 'state', state: this.state });
    return events;
  }

  update(reading, now) {
    const events = [];

    if (this.state === 'calibrating') {
      this._calibrate(reading, now, events);
      return events;
    }

    const away = !reading.present || this._angleFromBaseline(reading) > this.angleThresholdDeg;

    if (away) {
      this.attentiveStreak = 0;
      if (this.awaySince === null) this.awaySince = now;
      if (!this.warned && now - this.awaySince >= this.awayThresholdMs) {
        this.warned = true;
        this.state = 'away';
        events.push({ type: 'away', since: this.awaySince, reason: reading.present ? 'head-turned' : 'no-face' });
        events.push({ type: 'state', state: 'away' });
      }
      return events;
    }

    // Require a few attentive readings in a row so one stray frame mid-episode
    // doesn't reset the away timer or end the episode early.
    this.attentiveStreak += 1;
    if (this.attentiveStreak >= this.returnFrames && this.awaySince !== null) {
      if (this.warned) {
        events.push({ type: 'returned', since: this.awaySince, until: now, durationMs: now - this.awaySince });
        this.state = 'attentive';
        events.push({ type: 'state', state: 'attentive' });
      }
      this.awaySince = null;
      this.warned = false;
    }
    return events;
  }

  _calibrate(reading, now, events) {
    if (!reading.present || !reading.forward) return;
    if (this.calibrationStart === null) this.calibrationStart = now;
    this.calibrationSamples.push(reading.forward);

    const longEnough = now - this.calibrationStart >= this.calibrationMs;
    if (longEnough && this.calibrationSamples.length >= this.minCalibrationSamples) {
      const sum = this.calibrationSamples.reduce(
        (acc, f) => [acc[0] + f[0], acc[1] + f[1], acc[2] + f[2]],
        [0, 0, 0]
      );
      this.baseline = normalize(sum);
      this.calibrationSamples = [];
      this.state = 'attentive';
      events.push({ type: 'state', state: 'attentive' });
    }
  }

  _angleFromBaseline(reading) {
    return reading.forward ? angleBetweenDeg(reading.forward, this.baseline) : 0;
  }
}
