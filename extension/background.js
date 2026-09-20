// Service worker: owns session state, runs the drift check (scored by backend/) on each
// page context report, decides when to trigger an intervention, and manages
// the webcam attention monitor (which lives in an offscreen document).
importScripts('shared.js');

let interventionCooldownUntil = 0;
let offscreenCreating = null;
let attentionWarningTabId = null;

// Page reports and attention events can arrive at the same time and both
// read-modify-write the stored session, so run those cycles one at a time.
let sessionQueue = Promise.resolve();

function enqueue(task) {
  const run = sessionQueue.then(task);
  sessionQueue = run.catch(() => {});
  return run;
}

// `mutator` gets the stored session and returns it (to save) or null (to skip).
function updateSession(mutator) {
  return enqueue(async () => {
    const session = await getSession();
    if (!session) return null;
    const next = await mutator(session);
    if (next) await setSession(next);
    return next || null;
  });
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  handleMessage(message, sender)
    .then(sendResponse)
    .catch((err) => {
      console.error('[Anchor] background error handling', message?.type, err);
      sendResponse(null);
    });
  return true; // keep the message channel open for the async response
});

async function handleMessage(message, sender) {
  switch (message.type) {
    case MSG.START_SESSION:
      return startSession(message.goal, message.attentionEnabled);
    case MSG.END_SESSION:
      return endSession();
    case MSG.GET_SESSION:
      return getSession();
    case MSG.PAGE_CONTEXT:
      return handlePageContext(message.payload, sender);
    case MSG.KEEP_BROWSING:
      return keepBrowsing();
    case MSG.RETURN_TO_GOAL:
      return returnToGoal(sender);
    case MSG.SIMULATE_DRIFT:
      return simulateDrift();
    case MSG.SIMULATE_AWAY:
      return simulateAway();
    case MSG.RECALIBRATE_ATTENTION:
      return recalibrateAttention();
    case MSG.ATTENTION_STATUS:
      return handleAttentionStatus(message);
    case MSG.ATTENTION_STATE:
      return handleAttentionState(message);
    case MSG.ATTENTION_AWAY:
      return handleAttentionAway(message);
    case MSG.ATTENTION_RETURNED:
      return handleAttentionReturned(message);
    default:
      return null;
  }
}

async function startSession(goal, attentionEnabled) {
  await stopAttentionMonitor();
  closeAwayWindows();

  const enabled = !!attentionEnabled;
  const session = {
    id: generateId(),
    goal: (goal || '').trim(),
    startedAt: Date.now(),
    endedAt: null,
    active: true,
    events: [],
    lastAnchorUrl: null,
    consecutiveHigh: 0,
    attention: {
      enabled,
      status: enabled ? 'starting' : 'off', // camera pipeline: off | starting | active | error
      state: null, // user: calibrating | attentive | away
      error: null,
      events: [], // { start, end, durationMs, reason } -- no video, just timings
    },
  };
  interventionCooldownUntil = 0;
  await enqueue(() => setSession(session));

  if (enabled) startAttentionMonitor();
  return session;
}

async function endSession() {
  const endedAt = Date.now();
  const session = await updateSession((s) => {
    if (!s.active) return s;
    s.active = false;
    s.endedAt = endedAt;
    if (s.attention) {
      closeOpenAwayEvent(s.attention, endedAt);
      s.attention.status = 'off';
      s.attention.state = null;
    }
    return s;
  });

  await stopAttentionMonitor();
  dismissAttentionWarning(null);
  return session ? buildSummary(session) : null;
}

async function handlePageContext(pageContext, sender) {
  const current = await getSession();
  if (!current || !current.active) return null;

  const { score, source } = await scorePage(current.goal, pageContext, current.id);
  const classification = classifyScore(score);

  const event = {
    timestamp: Date.now(),
    url: pageContext.url,
    title: pageContext.title,
    score,
    source, // 'semantic' (backend) or 'keyword' (in-browser fallback)
    classification,
  };

  let intervene = false;
  const session = await updateSession((s) => {
    if (s.id !== current.id || !s.active) return null;

    s.events.push(event);
    if (classification === DRIFT.LOW) {
      s.lastAnchorUrl = pageContext.url;
      s.consecutiveHigh = 0;
    } else if (classification === DRIFT.HIGH) {
      s.consecutiveHigh = (s.consecutiveHigh || 0) + 1;
    } else {
      s.consecutiveHigh = 0;
    }

    intervene =
      s.consecutiveHigh >= CONSECUTIVE_HIGH_DRIFT_THRESHOLD && Date.now() > interventionCooldownUntil;
    return s;
  });
  if (!session) return null;

  notifyPopup(session);

  if (intervene && sender.tab && sender.tab.id != null) {
    interventionCooldownUntil = Date.now() + INTERVENTION_COOLDOWN_MS;
    sendToTab(sender.tab.id, {
      type: MSG.SHOW_INTERVENTION,
      payload: { goal: session.goal, event, lastAnchorUrl: session.lastAnchorUrl },
    });
  }

  return { score, classification };
}

// The simulate buttons are pressed in the popup, which may itself be open as a
// tab (the toolbar icon can be hidden by policy). Target the web page the user
// was last on and bring it forward so the result is actually visible.
async function demoTargetTab() {
  const tabs = await chrome.tabs.query({ url: ['http://*/*', 'https://*/*'] });
  tabs.sort((a, b) => (b.lastAccessed || 0) - (a.lastAccessed || 0));
  const tab = tabs[0];
  if (!tab) return null;

  await chrome.tabs.update(tab.id, { active: true });
  await chrome.windows.update(tab.windowId, { focused: true });
  return tab.id;
}

// Demo/testing helper wired to the popup's "simulate drift" button: pushes a
// synthetic HIGH-drift page into the current session so the intervention flow
// can be shown on demand without waiting on real navigation.
async function simulateDrift() {
  const score = 0.1;
  const classification = classifyScore(score);
  const event = {
    timestamp: Date.now(),
    url: 'anchor://simulated-drift',
    title: 'Simulated distraction page',
    score,
    classification,
  };

  let intervene = false;
  const session = await updateSession((s) => {
    if (!s.active) return null;
    s.events.push(event);
    s.consecutiveHigh = (s.consecutiveHigh || 0) + 1;
    intervene = s.consecutiveHigh >= CONSECUTIVE_HIGH_DRIFT_THRESHOLD;
    return s;
  });
  if (!session) return null;

  notifyPopup(session);

  if (intervene) {
    const tabId = await demoTargetTab();
    if (tabId != null) {
      interventionCooldownUntil = Date.now() + INTERVENTION_COOLDOWN_MS;
      sendToTab(tabId, {
        type: MSG.SHOW_INTERVENTION,
        payload: { goal: session.goal, event, lastAnchorUrl: session.lastAnchorUrl },
      });
    }
  }

  return { score, classification };
}

async function keepBrowsing() {
  return updateSession((s) => {
    s.consecutiveHigh = 0;
    return s;
  });
}

async function returnToGoal(sender) {
  let target = null;
  await updateSession((s) => {
    if (!s.lastAnchorUrl) return null;
    target = s.lastAnchorUrl;
    s.consecutiveHigh = 0;
    return s;
  });

  if (!target) return false;
  if (sender.tab && sender.tab.id != null) {
    chrome.tabs.update(sender.tab.id, { url: target });
  }
  return true;
}

// ---------------------------------------------------------------------------
// Attention detection (webcam)
// ---------------------------------------------------------------------------

function attentionActive(session) {
  return !!(session.active && session.attention && session.attention.enabled);
}

function closeOpenAwayEvent(attention, end) {
  const open = attention.events.find((e) => e.end === null);
  if (open) {
    open.end = end;
    open.durationMs = end - open.start;
  }
}

async function ensureOffscreenDocument() {
  const contexts = await chrome.runtime.getContexts({ contextTypes: ['OFFSCREEN_DOCUMENT'] });
  if (contexts.length > 0) return;

  offscreenCreating ??= chrome.offscreen
    .createDocument({
      url: 'attention/attention.html',
      reasons: ['USER_MEDIA'],
      justification:
        'Detect when the user looks away from the screen using the webcam. Video is processed on-device and never stored or uploaded.',
    })
    .finally(() => {
      offscreenCreating = null;
    });
  await offscreenCreating;
}

// The offscreen page may still be loading right after it is created, so retry
// until something answers.
async function sendToOffscreen(message, attempts = 10) {
  for (let i = 0; i < attempts; i++) {
    const response = await new Promise((resolve) => {
      chrome.runtime.sendMessage({ ...message, target: 'offscreen' }, (res) => {
        void chrome.runtime.lastError;
        resolve(res);
      });
    });
    if (response) return response;
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  return null;
}

async function startAttentionMonitor() {
  try {
    await ensureOffscreenDocument();
    const response = await sendToOffscreen({ type: MSG.ATTENTION_START, config: ATTENTION_CONFIG });
    if (!response) throw new Error('offscreen document did not respond');
  } catch (err) {
    console.error('[Anchor] could not start attention monitor', err);
    await handleAttentionStatus({ status: 'error', error: 'camera-error' });
  }
}

async function stopAttentionMonitor() {
  try {
    const contexts = await chrome.runtime.getContexts({ contextTypes: ['OFFSCREEN_DOCUMENT'] });
    if (contexts.length === 0) return;
    await sendToOffscreen({ type: MSG.ATTENTION_STOP }, 1);
    await chrome.offscreen.closeDocument();
  } catch (err) {
    console.error('[Anchor] could not stop attention monitor', err);
  }
}

async function recalibrateAttention() {
  const response = await sendToOffscreen({ type: MSG.ATTENTION_RECALIBRATE }, 1);
  return !!response;
}

async function handleAttentionStatus({ status, error }) {
  const session = await updateSession((s) => {
    if (!attentionActive(s)) return null;
    s.attention.status = status;
    s.attention.error = status === 'error' ? error || 'camera-error' : null;
    if (status !== 'active') s.attention.state = null;
    return s;
  });
  if (!session) return null;

  notifyPopup(session);
  // Nothing useful is running after an error, so release the model and camera.
  if (status === 'error') await stopAttentionMonitor();
  return true;
}

async function handleAttentionState({ state }) {
  const session = await updateSession((s) => {
    if (!attentionActive(s) || s.attention.status !== 'active') return null;
    s.attention.state = state;
    return s;
  });
  if (session) notifyPopup(session);
  return true;
}

async function handleAttentionAway({ since, reason }) {
  const session = await updateSession((s) => {
    if (!attentionActive(s)) return null;
    s.attention.state = 'away';
    if (!s.attention.events.some((e) => e.start === since)) {
      s.attention.events.push({ start: since, end: null, durationMs: null, reason });
    }
    return s;
  });
  if (!session) return null;

  notifyPopup(session);
  showAttentionWarning(session.goal, since);
  return true;
}

async function handleAttentionReturned({ since, until }) {
  let awayMs = null;
  const session = await updateSession((s) => {
    if (!attentionActive(s)) return null;
    const episode = s.attention.events.find((e) => e.start === since && e.end === null);
    if (episode) {
      episode.end = until;
      episode.durationMs = until - since;
      awayMs = episode.durationMs;
    }
    s.attention.state = 'attentive';
    return s;
  });
  if (!session) return null;

  notifyPopup(session);
  dismissAttentionWarning(awayMs);
  return true;
}

// Demo/testing helper wired to the popup's "simulate look-away" link: records
// a short away episode and runs the warning through its full cycle without
// needing a camera.
async function simulateAway() {
  const SIMULATED_AWAY_MS = 6000;
  const end = Date.now();
  const session = await updateSession((s) => {
    if (!attentionActive(s)) return null;
    s.attention.events.push({
      start: end - SIMULATED_AWAY_MS,
      end,
      durationMs: SIMULATED_AWAY_MS,
      reason: 'simulated',
    });
    return s;
  });
  if (!session) return null;

  notifyPopup(session);
  openAwayWindow(end - SIMULATED_AWAY_MS);
  const tabId = await demoTargetTab();
  if (tabId != null) {
    attentionWarningTabId = tabId;
    const large = await browserIsFullscreen();
    sendToTab(tabId, {
      type: MSG.SHOW_ATTENTION_WARNING,
      payload: { goal: session.goal, since: end - SIMULATED_AWAY_MS, large },
    });
  }
  setTimeout(() => dismissAttentionWarning(SIMULATED_AWAY_MS), SIMULATED_AWAY_MS);
  return true;
}

const WARNING_PAGE = chrome.runtime.getURL('attention/warning.html');
// Opening size only; the page then grows itself to about 70% of the screen (warning.js).
const WARNING_WINDOW = { width: 900, height: 600 };
let closeAwayTimer = null;

// Where to show the in-page banner: the active tab if it is a web page, otherwise
// the web page the user was last on (the active tab may be the popup, a new-tab
// page, or chrome://, none of which can show it).
async function warningTabId() {
  const [active] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  if (active && /^https?:/.test(active.url || '')) return active.id;

  const pages = await chrome.tabs.query({ url: ['http://*/*', 'https://*/*'] });
  pages.sort((a, b) => (b.lastAccessed || 0) - (a.lastAccessed || 0));
  return pages.length ? pages[0].id : null;
}

// On macOS a full-screen window is its own Space, so opening a separate focused
// window switches away from it (or drops the browser out of full screen). The
// same goes for a full-screen video. Those cases get an in-page warning instead.
async function browserIsFullscreen() {
  try {
    return (await chrome.windows.getLastFocused()).state === 'fullscreen';
  } catch {
    return false;
  }
}

// You can't see a banner while you're looking away, so also open a small
// pop-up window in front of everything. It works whatever tab is active (the
// popup, a new-tab page, chrome://) and plays a chime.
async function openAwayWindow(since) {
  try {
    clearTimeout(closeAwayTimer); // a leftover "close it" timer must not close this new warning
    if ((await chrome.tabs.query({ url: `${WARNING_PAGE}*` })).length > 0) return; // already showing

    // A full-screen browser gets a big in-page warning instead (see showAttentionWarning).
    if (await browserIsFullscreen()) return;

    // Centre it over the browser window it will appear in front of, if we can tell where that is.
    let position = {};
    const current = await chrome.windows.getLastFocused();
    if (current.state !== 'minimized' && current.left != null && current.width != null) {
      position = {
        left: Math.max(0, Math.round(current.left + (current.width - WARNING_WINDOW.width) / 2)),
        top: Math.max(0, Math.round(current.top + 80)),
      };
    }
    await chrome.windows.create({
      url: `${WARNING_PAGE}?since=${since}`,
      type: 'popup',
      focused: true,
      ...WARNING_WINDOW,
      ...position,
    });
  } catch (err) {
    console.warn('[Anchor] could not open the warning window:', err);
  }
}

async function closeAwayWindows() {
  clearTimeout(closeAwayTimer);
  const tabs = await chrome.tabs.query({ url: `${WARNING_PAGE}*` });
  await Promise.all(tabs.map((tab) => chrome.windows.remove(tab.windowId).catch(() => {})));
}

async function showAttentionWarning(goal, since) {
  openAwayWindow(since);
  const tabId = await warningTabId();
  if (tabId == null) return;
  attentionWarningTabId = tabId;
  // Full screen: no separate window, so make the in-page warning large and loud.
  const large = await browserIsFullscreen();
  sendToTab(tabId, { type: MSG.SHOW_ATTENTION_WARNING, payload: { goal, since, large } });
}

// awayMs = null removes the warning immediately; otherwise it briefly shows a
// "welcome back" state first so the user actually sees it after looking back.
async function dismissAttentionWarning(awayMs) {
  if (awayMs == null) {
    closeAwayWindows();
  } else {
    chrome.runtime.sendMessage({ type: MSG.HIDE_ATTENTION_WARNING, payload: { awayMs } }, () => void chrome.runtime.lastError);
    closeAwayTimer = setTimeout(closeAwayWindows, 6000); // in case the window doesn't close itself
  }

  const tabId = attentionWarningTabId ?? (await warningTabId());
  attentionWarningTabId = null;
  if (tabId == null) return;
  sendToTab(tabId, { type: MSG.HIDE_ATTENTION_WARNING, payload: { awayMs } });
}

// The offscreen document (and camera) does not survive a browser restart or an
// extension reload, so a stored "active" camera status would be stale. Mark it
// off rather than silently turning the camera back on.
async function markAttentionOffIfNotRunning() {
  const contexts = await chrome.runtime.getContexts({ contextTypes: ['OFFSCREEN_DOCUMENT'] });
  if (contexts.length > 0) return;

  await updateSession((s) => {
    if (!attentionActive(s) || s.attention.status === 'off') return null;
    s.attention.status = 'off';
    s.attention.state = null;
    return s;
  });
}

chrome.runtime.onStartup.addListener(markAttentionOffIfNotRunning);
chrome.runtime.onInstalled.addListener(markAttentionOffIfNotRunning);

// ---------------------------------------------------------------------------

function sendToTab(tabId, message) {
  chrome.tabs.sendMessage(tabId, message, () => {
    // No content script on that tab (chrome:// pages, tab closed) -- ignore.
    void chrome.runtime.lastError;
  });
}

function notifyPopup(session) {
  chrome.runtime.sendMessage({ type: MSG.SESSION_UPDATED, payload: session }, () => {
    // No popup open to receive it -- chrome sets lastError, just swallow it.
    void chrome.runtime.lastError;
  });
}
