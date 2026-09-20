const views = {
  start: document.getElementById('view-start'),
  active: document.getElementById('view-active'),
  summary: document.getElementById('view-summary'),
};

const attentionToggle = document.getElementById('attention-toggle');

const ATTENTION_ERROR_TEXT = {
  'permission-denied': 'Camera access needed',
  'no-camera': 'No camera found',
  'camera-busy': 'Camera is in use by another app',
  'camera-lost': 'Camera disconnected',
  'model-load-failed': 'Attention model failed to load',
  'detection-failed': 'Attention detection stopped',
  'bad-config': 'Attention settings were rejected',
};

let tickTimer = null;

markStandaloneIfNotPopup();
init();

// When this page is opened as a normal tab (e.g. via chrome-extension://.../popup.html
// for testing, since this profile's toolbar puzzle-piece icon is policy-hidden) instead
// of the real toolbar popup, expand the layout to fill the page instead of staying at
// the small fixed popup width.
function markStandaloneIfNotPopup() {
  const isRealPopup =
    !!chrome.extension?.getViews && chrome.extension.getViews({ type: 'popup' }).includes(window);
  if (!isRealPopup) {
    document.body.classList.add('standalone');
  }
}

async function init() {
  const session = await send({ type: MSG.GET_SESSION });

  if (session && session.active) {
    renderActive(session);
  } else if (session && session.endedAt) {
    renderSummary(buildSummary(session));
  } else {
    renderStart();
  }

  chrome.runtime.onMessage.addListener((message) => {
    if (message.type === MSG.SESSION_UPDATED && message.payload.active) {
      renderActive(message.payload);
    }
  });

  document.getElementById('start-btn').addEventListener('click', onStart);
  document.getElementById('end-btn').addEventListener('click', onEnd);
  document.getElementById('new-session-btn').addEventListener('click', renderStart);
  document.getElementById('simulate-btn').addEventListener('click', onSimulateDrift);
  document.getElementById('simulate-away-btn').addEventListener('click', onSimulateAway);
  document.getElementById('recalibrate-btn').addEventListener('click', onRecalibrate);
  document.getElementById('camera-grant-btn').addEventListener('click', openCameraPermissionPage);
  document.getElementById('attention-grant-btn').addEventListener('click', openCameraPermissionPage);

  const settings = await getSettings();
  attentionToggle.checked = settings.attentionEnabled;
  attentionToggle.addEventListener('change', async () => {
    await setSettings({ attentionEnabled: attentionToggle.checked });
    refreshCameraStatus();
  });
  refreshCameraStatus();
  refreshBackendStatus();

  document.getElementById('goal-input').addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      onStart();
    }
  });
}

function send(message) {
  return new Promise((resolve) => chrome.runtime.sendMessage(message, resolve));
}

function showView(name) {
  Object.entries(views).forEach(([key, el]) => {
    el.hidden = key !== name;
  });
  document.title = 'Anchor';
}

function renderStart() {
  showView('start');
  document.getElementById('goal-input').value = '';
  stopTick();
  refreshCameraStatus();
  refreshBackendStatus();
  document.getElementById('goal-input').focus();
}

async function onStart() {
  const goal = document.getElementById('goal-input').value.trim();
  if (!goal) return;
  const session = await send({
    type: MSG.START_SESSION,
    goal,
    attentionEnabled: attentionToggle.checked,
  });
  renderActive(session);
}

function renderActive(session) {
  showView('active');
  document.getElementById('active-goal').textContent = session.goal;
  renderEventsList(document.getElementById('events-list'), session.events.slice(-6).reverse());
  updatePill(session);
  renderAttention(session.attention);
  startTick(session);
  refreshBackendStatus();
}

// Pages are scored by the backend (semantic similarity) when it is running and
// by in-browser keyword matching otherwise; say which one is in effect.
async function refreshBackendStatus() {
  const dot = document.getElementById('backend-dot');
  const text = document.getElementById('backend-text');
  const box = document.getElementById('backend-status');

  let running = false;
  try {
    const response = await fetch(API_HEALTH_URL, { signal: AbortSignal.timeout(1500) });
    running = response.ok && (await response.json()).service === 'anchor-api';
  } catch {
    // Not running or unreachable.
  }

  dot.className = `attention-dot attention-dot--${running ? 'ok' : 'warn'}`;
  text.textContent = running ? 'Semantic matching' : 'Keyword matching';
  box.title = running
    ? 'Connected to the Anchor alignment server'
    : 'Alignment server not running, so pages are matched by keywords in the browser. Start it with the steps in the README for better accuracy.';
}

// Camera permission is granted per extension origin from a visible tab
// (the popup itself closes as soon as Chrome's prompt takes focus).
async function refreshCameraStatus() {
  const box = document.getElementById('camera-status');
  const text = document.getElementById('camera-status-text');
  const grantBtn = document.getElementById('camera-grant-btn');

  box.hidden = !attentionToggle.checked;
  if (!attentionToggle.checked) return;

  let state = 'unknown';
  try {
    const permission = await navigator.permissions.query({ name: 'camera' });
    state = permission.state;
    permission.onchange = refreshCameraStatus;
  } catch {
    // Permission state isn't readable; fall back to offering the grant page.
  }

  box.classList.toggle('option__camera--ok', state === 'granted');
  box.classList.toggle('option__camera--bad', state === 'denied');
  grantBtn.hidden = state === 'granted';

  if (state === 'granted') {
    text.textContent = 'Camera ready';
  } else if (state === 'denied') {
    text.textContent = 'Camera is blocked for Anchor';
    grantBtn.textContent = 'How to fix';
  } else {
    text.textContent = 'Camera access needed';
    grantBtn.textContent = 'Grant camera access';
  }
}

function openCameraPermissionPage() {
  chrome.tabs.create({ url: chrome.runtime.getURL('attention/camera-permission.html') });
}

function renderAttention(attention) {
  // The popup is often left open as a tab, so it shows the warning too.
  const away = !!(attention && attention.enabled && attention.status === 'active' && attention.state === 'away');
  document.getElementById('away-banner').hidden = !away;
  document.title = away ? 'Looking away! - Anchor' : 'Anchor';

  const row = document.getElementById('attention-row');
  if (!attention || !attention.enabled) {
    row.hidden = true;
    return;
  }
  row.hidden = false;

  const dot = document.getElementById('attention-dot');
  const text = document.getElementById('attention-text');
  const grantBtn = document.getElementById('attention-grant-btn');
  const recalibrateBtn = document.getElementById('recalibrate-btn');

  let label;
  let tone = ''; // '', 'ok', 'warn', 'bad'
  if (attention.status === 'error') {
    label = ATTENTION_ERROR_TEXT[attention.error] || 'Camera unavailable';
    tone = 'bad';
  } else if (attention.status === 'starting') {
    label = 'Starting camera…';
    tone = 'warn';
  } else if (attention.status === 'active') {
    if (attention.state === 'away') {
      label = 'Looking away';
      tone = 'bad';
    } else if (attention.state === 'attentive') {
      label = 'Focused';
      tone = 'ok';
    } else {
      label = 'Calibrating — look at your screen';
      tone = 'warn';
    }
  } else {
    label = 'Camera off';
  }

  text.textContent = `Attention: ${label}`;
  dot.className = `attention-dot${tone ? ` attention-dot--${tone}` : ''}`;
  grantBtn.hidden = !(
    attention.status === 'error' &&
    attention.error === 'permission-denied'
  );
  recalibrateBtn.hidden = attention.status !== 'active';
}

function onSimulateAway() {
  return send({ type: MSG.SIMULATE_AWAY });
}

function onRecalibrate() {
  send({ type: MSG.RECALIBRATE_ATTENTION });
}

function updatePill(session) {
  const last = session.events[session.events.length - 1];
  const pill = document.getElementById('status-pill');
  if (!last) {
    pill.textContent = 'Getting started…';
    pill.className = 'status-pill';
    return;
  }
  pill.textContent = last.classification;
  pill.className = `status-pill status-pill--${last.classification.toLowerCase()}`;
}

function onSimulateDrift() {
  return send({ type: MSG.SIMULATE_DRIFT });
}

function startTick(session) {
  stopTick();
  const tick = () => {
    document.getElementById('status-time').textContent = formatDuration(Date.now() - session.startedAt);
  };
  tick();
  tickTimer = setInterval(tick, 1000);
}

function stopTick() {
  if (tickTimer) clearInterval(tickTimer);
  tickTimer = null;
}

async function onEnd() {
  const summary = await send({ type: MSG.END_SESSION });
  stopTick();
  renderSummary(summary);
}

function renderSummary(summary) {
  showView('summary');
  document.getElementById('summary-goal').textContent = summary.goal;

  const { counts, totalPages, durationMs } = summary;
  document.getElementById('summary-stats').innerHTML = `
    <div class="stat"><span class="stat__value">${totalPages}</span><span class="stat__label">Pages</span></div>
    <div class="stat"><span class="stat__value">${formatDuration(durationMs)}</span><span class="stat__label">Duration</span></div>
    <div class="stat"><span class="stat__value">${counts.HIGH || 0}</span><span class="stat__label">Alerts</span></div>
  `;

  const attentionCard = document.getElementById('attention-summary');
  const attention = summary.attention;
  attentionCard.hidden = !attention;
  if (attention) {
    document.getElementById('attention-summary-text').textContent =
      attention.awayCount === 0
        ? 'You stayed focused on the screen the whole session.'
        : `Looked away ${attention.awayCount} ${attention.awayCount === 1 ? 'time' : 'times'}, ` +
          `${formatDuration(attention.totalAwayMs)} in total (longest ${formatDuration(attention.longestAwayMs)}).`;
  }

  renderEventsList(document.getElementById('summary-events'), [...summary.events].reverse());
}

function renderEventsList(el, events) {
  el.innerHTML = '';
  if (!events.length) {
    el.innerHTML = '<li class="events__empty">No pages tracked yet</li>';
    return;
  }
  events.forEach((e) => {
    const li = document.createElement('li');
    li.className = `event event--${e.classification.toLowerCase()}`;
    li.innerHTML = `
      <div class="event__row">
        <span class="event__title">${escapeHtml(e.title || e.url)}</span>
        <span class="event__score">${Math.round(e.score * 100)}%</span>
      </div>
      <div class="event__meta">${escapeHtml(getDomain(e.url))} &middot; ${formatRelativeTime(e.timestamp)}</div>
    `;
    el.appendChild(li);
  });
}

function getDomain(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return url || '';
  }
}

function formatRelativeTime(timestamp) {
  const diffSec = Math.max(0, Math.floor((Date.now() - timestamp) / 1000));
  if (diffSec < 60) return `${diffSec}s ago`;
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  return `${diffHr}h ago`;
}

function formatDuration(ms) {
  const totalSec = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(totalSec / 60).toString().padStart(2, '0');
  const s = (totalSec % 60).toString().padStart(2, '0');
  return `${m}:${s}`;
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str || '';
  return div.innerHTML;
}
