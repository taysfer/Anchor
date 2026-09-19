import { AttentionTracker, forwardAxisFromMatrix, angleBetweenDeg } from '../attention/attention-core.js';

const CONFIG = { awayThresholdMs: 5000, angleThresholdDeg: 30, calibrationMs: 2500, minCalibrationSamples: 3, returnFrames: 2 };
const failures = [];
let passed = 0;

function check(name, cond, detail) {
  if (cond) passed += 1;
  else failures.push(`${name}${detail !== undefined ? ' => ' + JSON.stringify(detail) : ''}`);
}

const rad = (d) => (d * Math.PI) / 180;
const facing = (deg) => ({ present: true, forward: [Math.sin(rad(deg)), 0, Math.cos(rad(deg))] });
const noFace = { present: false };

// Feeds `reading` every 500ms from t0 (inclusive) to t0+durationMs (inclusive).
function feed(tracker, reading, t0, durationMs) {
  const events = [];
  for (let t = t0; t <= t0 + durationMs; t += 500) events.push(...tracker.update(reading, t).map((e) => ({ ...e, t })));
  return events;
}
const types = (events) => events.map((e) => e.type + (e.state ? ':' + e.state : ''));

// Calibrated tracker at t=0..2500, looking straight at the camera.
function calibrated() {
  const tr = new AttentionTracker(CONFIG);
  const ev = feed(tr, facing(0), 0, 2500);
  return { tr, ev };
}

// T1: calibration
{
  const { tr, ev } = calibrated();
  check('T1 calibration emits attentive state', types(ev).join() === 'state:attentive', types(ev));
  check('T1 state is attentive', tr.state === 'attentive');
}

// T1b: no-face frames before the first face do not consume calibration time
{
  const tr = new AttentionTracker(CONFIG);
  const ev1 = feed(tr, noFace, 0, 20000);
  check('T1b no events while nobody is present', ev1.length === 0, ev1);
  const ev2 = feed(tr, facing(0), 20500, 2000);
  check('T1b still calibrating before calibrationMs of face time', tr.state === 'calibrating' && ev2.length === 0, { state: tr.state, ev2 });
  const ev3 = feed(tr, facing(0), 22500, 1000);
  check('T1b calibrates after enough face time', tr.state === 'attentive', { state: tr.state, ev3 });
}

// T2: a short glance away produces no events
{
  const { tr } = calibrated();
  const glance = feed(tr, facing(60), 3000, 3000); // 3.5s of head turned
  const back = feed(tr, facing(0), 6500, 1500);
  check('T2 glance < threshold produces no events', glance.length === 0 && back.length === 0, { glance, back });
}

// T3: sustained head turn -> away at exactly the threshold, with the right start time
{
  const { tr } = calibrated();
  const ev = feed(tr, facing(45), 3000, 5000);
  const away = ev.find((e) => e.type === 'away');
  check('T3 away event emitted', !!away, ev);
  check('T3 away reports first away frame as start', away && away.since === 3000, away);
  check('T3 away reason is head-turned', away && away.reason === 'head-turned', away);
  check('T3 away fires at threshold, not before', away && away.t === 8000, away);
  check('T3 state is away', tr.state === 'away');
}

// T4: one stray attentive frame does not end the episode; two do
{
  const { tr } = calibrated();
  feed(tr, facing(45), 3000, 5000); // away since 3000
  const blip = feed(tr, facing(0), 8500, 0);
  const still = feed(tr, facing(45), 9000, 1000);
  check('T4 single attentive frame does not return', blip.length === 0 && still.length === 0, { blip, still });
  const back = feed(tr, facing(0), 10500, 500);
  const ret = back.find((e) => e.type === 'returned');
  check('T4 returns after consecutive attentive frames', !!ret && ret.since === 3000, back);
  check('T4 returned duration spans the episode', ret && ret.durationMs === ret.until - 3000, ret);
  check('T4 back to attentive', tr.state === 'attentive');
}

// T5: face leaving the frame counts as away
{
  const { tr } = calibrated();
  const ev = feed(tr, noFace, 3000, 5000);
  const away = ev.find((e) => e.type === 'away');
  check('T5 no-face away', !!away && away.reason === 'no-face', ev);
}

// T6: angle threshold
{
  const a = calibrated().tr;
  const under = feed(a, facing(29), 3000, 8000);
  check('T6 29 degrees is not away', under.length === 0, under);
  const b = calibrated().tr;
  const over = feed(b, facing(31), 3000, 5000);
  check('T6 31 degrees is away', over.some((e) => e.type === 'away'), over);
}

// T6b: looking down/up (pitch) also counts, and calibration offsets are respected
{
  const tr = new AttentionTracker(CONFIG);
  const tilted = { present: true, forward: [0, Math.sin(rad(-15)), Math.cos(rad(-15))] }; // webcam-below-eye-level pose
  feed(tr, tilted, 0, 2500);
  const same = feed(tr, tilted, 3000, 8000);
  check('T6b calibrated off-axis pose is not away', same.length === 0, same);
  const phone = { present: true, forward: [0, Math.sin(rad(-15 - 40)), Math.cos(rad(-15 - 40))] }; // looks 40 degrees further down
  const down = feed(tr, phone, 11500, 5000);
  check('T6b looking down 40 degrees from baseline is away', down.some((e) => e.type === 'away'), down);
}

// T7: recalibrate mid-episode
{
  const { tr } = calibrated();
  feed(tr, facing(45), 3000, 5000);
  const ev = tr.recalibrate(9000);
  check('T7 recalibrate closes the episode then restarts calibration', types(ev).join() === 'returned,state:calibrating', types(ev));
  const cal = feed(tr, facing(45), 9500, 3000);
  check('T7 new pose becomes the baseline', tr.state === 'attentive', { state: tr.state, cal });
  const after = feed(tr, facing(45), 12500, 8000);
  check('T7 new pose is no longer away', after.length === 0, after);
}

// T8: matrix helpers
{
  const ident = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1];
  const f0 = forwardAxisFromMatrix(ident);
  check('T8 identity forward is +z', f0[0] === 0 && f0[1] === 0 && f0[2] === 1, f0);
  const c = Math.cos(rad(40)), s = Math.sin(rad(40));
  // column-major rotation about Y by 40 degrees, uniformly scaled by 3 with a translation
  const rotY = [3 * c, 0, -3 * s, 0, 0, 3, 0, 0, 3 * s, 0, 3 * c, 0, 10, 20, 30, 1];
  const f40 = forwardAxisFromMatrix(rotY);
  check('T8 scaled rotation is 40 degrees from identity', Math.abs(angleBetweenDeg(f0, f40) - 40) < 1e-6, angleBetweenDeg(f0, f40));
  check('T8 angle of identical vectors is 0', angleBetweenDeg(f0, f0) === 0);
}

document.title = failures.length ? `FAIL(${failures.length}/${failures.length + passed}): ${failures.join(' ;; ')}` : `PASS: ${passed} checks`;
