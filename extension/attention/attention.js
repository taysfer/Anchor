// Runs inside the offscreen document. Owns the webcam and the on-device face
// model. Frames are only ever read by the local model -- they are never drawn
// to a canvas, stored, or sent anywhere. All that leaves this file are small
// status/attention events sent to the background worker.
import { FilesetResolver, FaceLandmarker } from '../vendor/mediapipe/vision_bundle.mjs';
import { AttentionTracker, forwardAxisFromMatrix } from './attention-core.js';

const TICK_MS = 500;
const video = document.getElementById('camera');

let landmarkerPromise = null;
let landmarker = null;
let stream = null;
let tracker = null;
let timer = null;
let generation = 0; // bumped by every start/stop so stale async work can bail out

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.target !== 'offscreen') return;

  switch (message.type) {
    case MSG.ATTENTION_START:
      start(message.config);
      break;
    case MSG.ATTENTION_STOP:
      stop();
      break;
    case MSG.ATTENTION_RECALIBRATE:
      recalibrate();
      break;
    default:
      return;
  }
  sendResponse({ ok: true });
});

function report(message) {
  chrome.runtime.sendMessage(message, () => void chrome.runtime.lastError);
}

function reportError(error) {
  report({ type: MSG.ATTENTION_STATUS, status: 'error', error });
}

function loadLandmarker() {
  landmarkerPromise ??= (async () => {
    const fileset = await FilesetResolver.forVisionTasks(chrome.runtime.getURL('vendor/mediapipe/wasm'));
    return FaceLandmarker.createFromOptions(fileset, {
      baseOptions: {
        modelAssetPath: chrome.runtime.getURL('vendor/mediapipe/face_landmarker.task'),
        delegate: 'CPU',
      },
      runningMode: 'VIDEO',
      numFaces: 1,
      outputFacialTransformationMatrixes: true,
    });
  })().catch((err) => {
    landmarkerPromise = null;
    throw err;
  });
  return landmarkerPromise;
}

function cameraErrorCode(err) {
  switch (err && err.name) {
    case 'NotAllowedError':
    case 'SecurityError':
      return 'permission-denied';
    case 'NotFoundError':
    case 'DevicesNotFoundError':
      return 'no-camera';
    case 'NotReadableError':
      return 'camera-busy';
    default:
      return 'camera-error';
  }
}

async function start(config) {
  stop();
  const gen = generation;
  report({ type: MSG.ATTENTION_STATUS, status: 'starting' });

  try {
    landmarker = await loadLandmarker();
  } catch (err) {
    console.error('[Anchor] attention model failed to load', err);
    if (gen === generation) reportError('model-load-failed');
    return;
  }
  if (gen !== generation) return;

  let newStream;
  try {
    newStream = await navigator.mediaDevices.getUserMedia({
      // 320x240 was too small for the model to find a face at normal sitting distance.
      video: { width: 640, height: 480, facingMode: 'user' },
      audio: false,
    });
  } catch (err) {
    console.error('[Anchor] camera unavailable', err);
    if (gen === generation) reportError(cameraErrorCode(err));
    return;
  }
  if (gen !== generation) {
    newStream.getTracks().forEach((track) => track.stop());
    return;
  }

  stream = newStream;
  video.srcObject = stream;
  try {
    await video.play();
  } catch (err) {
    console.error('[Anchor] camera preview failed to start', err);
    if (gen === generation) {
      stop();
      reportError('camera-error');
    }
    return;
  }
  if (gen !== generation) return;

  stream.getVideoTracks()[0].addEventListener('ended', () => {
    if (gen !== generation) return;
    stop();
    reportError('camera-lost');
  });

  tracker = new AttentionTracker(config);
  report({ type: MSG.ATTENTION_STATUS, status: 'active' });
  report({ type: MSG.ATTENTION_STATE, state: tracker.state });
  timer = setInterval(tick, TICK_MS);
}

function stop() {
  generation += 1;
  clearInterval(timer);
  timer = null;
  tracker = null;
  if (stream) {
    stream.getTracks().forEach((track) => track.stop());
    stream = null;
  }
  video.srcObject = null;
}

function recalibrate() {
  if (!tracker) return;
  tracker.recalibrate(Date.now()).forEach(handleTrackerEvent);
}

function tick() {
  if (!tracker || video.readyState < 2) return;

  try {
    const result = landmarker.detectForVideo(video, performance.now());
    const present = result.faceLandmarks.length > 0;
    const matrix = result.facialTransformationMatrixes && result.facialTransformationMatrixes[0];
    const reading = {
      present,
      forward: present && matrix ? forwardAxisFromMatrix(matrix.data) : undefined,
    };
    tracker.update(reading, Date.now()).forEach(handleTrackerEvent);
  } catch (err) {
    console.error('[Anchor] face detection failed', err);
    stop();
    reportError('detection-failed');
  }
}

function handleTrackerEvent(event) {
  switch (event.type) {
    case 'state':
      report({ type: MSG.ATTENTION_STATE, state: event.state });
      break;
    case 'away':
      report({ type: MSG.ATTENTION_AWAY, since: event.since, reason: event.reason });
      break;
    case 'returned':
      report({ type: MSG.ATTENTION_RETURNED, since: event.since, until: event.until });
      break;
  }
}
