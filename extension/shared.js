// Shared constants and helpers used by background.js, content.js, and popup.js.
// Loaded as a plain (non-module) script everywhere so these stay on the global scope.

const MSG = {
  START_SESSION: 'START_SESSION',
  END_SESSION: 'END_SESSION',
  GET_SESSION: 'GET_SESSION',
  PAGE_CONTEXT: 'PAGE_CONTEXT',
  SHOW_INTERVENTION: 'SHOW_INTERVENTION',
  RETURN_TO_GOAL: 'RETURN_TO_GOAL',
  KEEP_BROWSING: 'KEEP_BROWSING',
  SESSION_UPDATED: 'SESSION_UPDATED',
  SIMULATE_DRIFT: 'SIMULATE_DRIFT',

  // Attention detection: popup -> background
  SIMULATE_AWAY: 'SIMULATE_AWAY',
  RECALIBRATE_ATTENTION: 'RECALIBRATE_ATTENTION',
  // background -> offscreen document (sent with target: 'offscreen')
  ATTENTION_START: 'ATTENTION_START',
  ATTENTION_STOP: 'ATTENTION_STOP',
  ATTENTION_RECALIBRATE: 'ATTENTION_RECALIBRATE',
  // offscreen document -> background
  ATTENTION_STATUS: 'ATTENTION_STATUS',
  ATTENTION_STATE: 'ATTENTION_STATE',
  ATTENTION_AWAY: 'ATTENTION_AWAY',
  ATTENTION_RETURNED: 'ATTENTION_RETURNED',
  // background -> content script
  SHOW_ATTENTION_WARNING: 'SHOW_ATTENTION_WARNING',
  HIDE_ATTENTION_WARNING: 'HIDE_ATTENTION_WARNING',
};

const DRIFT = {
  LOW: 'LOW',
  MEDIUM: 'MEDIUM',
  HIGH: 'HIGH',
};

const STORAGE_KEY = 'anchor_session';
const SETTINGS_KEY = 'anchor_settings';

// Optional local Python attention server (see server/). Only an extension page
// or the service worker talks to it; the address never leaves this machine.
const PYTHON_ENGINE_WS_URL = 'ws://127.0.0.1:8765/attention/ws';
const PYTHON_ENGINE_HEALTH_URL = 'http://127.0.0.1:8765/health';

// Webcam attention detection tuning. Head direction is measured as the angle
// between where the face points now and where it pointed during calibration
// (the first couple of seconds of a session), so a webcam that sits below eye
// level doesn't count as "looking away".
const ATTENTION_CONFIG = {
  awayThresholdMs: 5000, // looking away this long triggers the warning
  angleThresholdDeg: 20, // head turned this far from the calibrated pose = away (tuned in analysis/)
  calibrationMs: 2500, // how long to sample the "looking at the screen" pose
  minCalibrationSamples: 3,
  returnFrames: 2, // consecutive attentive readings needed to end an away episode
};

// How many consecutive HIGH-drift pages in a row before we interrupt the user.
// This mirrors the README's point that a single unrelated page shouldn't trigger
// a check-in -- we're looking for a sustained pattern of moving away from the goal.
const CONSECUTIVE_HIGH_DRIFT_THRESHOLD = 2;

// Minimum time between intervention popups so we don't spam the user.
const INTERVENTION_COOLDOWN_MS = 60_000;

/**
 * NOTE for Person 2 (AI / Drift Logic):
 * This is a placeholder for the real embedding + semantic similarity pipeline.
 * It exists so the rest of the extension (session tracking, intervention UI,
 * summary) can be built and demoed before the real backend is ready.
 *
 * Replace the body of this function with a call to your API, e.g.:
 *   const res = await fetch(`${API_BASE}/drift`, { method: 'POST', body: JSON.stringify({ goal, pageContext }) });
 *   const { score } = await res.json();
 *   return score;
 *
 * Keep the signature (goal, pageContext) -> Promise<number in [0, 1]> so nothing
 * else has to change.
 */
async function computeDriftScoreStub(goal, pageContext) {
  const goalWords = tokenize(goal);
  const pageWords = tokenize(`${pageContext.title} ${pageContext.description} ${pageContext.text}`);

  if (goalWords.size === 0 || pageWords.size === 0) return 0.5;

  let overlap = 0;
  goalWords.forEach((word) => {
    if (pageWords.has(word)) overlap += 1;
  });

  const rawScore = overlap / goalWords.size;
  // Blend with a mild baseline so completely-unrelated-but-not-junk pages don't
  // instantly bottom out at 0, which would make the stub feel too jumpy in demos.
  return Math.max(0, Math.min(1, rawScore * 0.85 + 0.1));
}

const STOPWORDS = new Set([
  'this', 'that', 'with', 'from', 'have', 'your', 'about', 'what', 'when',
  'there', 'their', 'which', 'would', 'could', 'should', 'into', 'than', 'then', 'here',
]);

function tokenize(str) {
  return new Set(
    (str || '')
      .toLowerCase()
      .replace(/[^a-z0-9\s]/g, ' ')
      .split(/\s+/)
      .filter((w) => w.length > 3 && !STOPWORDS.has(w))
  );
}

/**
 * NOTE for Person 2: replace these thresholds once real similarity scores are
 * tuned against the demo path. Higher score = more aligned with the goal.
 */
function classifyScore(score) {
  if (score >= 0.6) return DRIFT.LOW;
  if (score >= 0.35) return DRIFT.MEDIUM;
  return DRIFT.HIGH;
}

function generateId() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

function getSession() {
  return new Promise((resolve) => {
    chrome.storage.local.get([STORAGE_KEY], (res) => resolve(res[STORAGE_KEY] || null));
  });
}

function setSession(session) {
  return new Promise((resolve) => {
    chrome.storage.local.set({ [STORAGE_KEY]: session }, () => resolve(session));
  });
}

function getSettings() {
  return new Promise((resolve) => {
    chrome.storage.local.get([SETTINGS_KEY], (res) => {
      resolve({ attentionEnabled: false, attentionEngine: 'browser', ...(res[SETTINGS_KEY] || {}) });
    });
  });
}

async function setSettings(patch) {
  const next = { ...(await getSettings()), ...patch };
  return new Promise((resolve) => {
    chrome.storage.local.set({ [SETTINGS_KEY]: next }, () => resolve(next));
  });
}

function summarizeAttention(attention) {
  if (!attention || !attention.enabled) return null;
  const closed = (attention.events || []).filter((e) => e.durationMs != null);
  return {
    awayCount: closed.length,
    totalAwayMs: closed.reduce((sum, e) => sum + e.durationMs, 0),
    longestAwayMs: closed.reduce((max, e) => Math.max(max, e.durationMs), 0),
  };
}

function buildSummary(session) {
  const events = session.events || [];
  const counts = { LOW: 0, MEDIUM: 0, HIGH: 0 };
  events.forEach((e) => {
    counts[e.classification] = (counts[e.classification] || 0) + 1;
  });
  const avgScore = events.length
    ? events.reduce((sum, e) => sum + e.score, 0) / events.length
    : null;

  return {
    goal: session.goal,
    startedAt: session.startedAt,
    endedAt: session.endedAt,
    durationMs: (session.endedAt || Date.now()) - session.startedAt,
    totalPages: events.length,
    counts,
    avgScore,
    events,
    attention: summarizeAttention(session.attention),
  };
}
