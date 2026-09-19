const views = {
  start: document.getElementById('view-start'),
  active: document.getElementById('view-active'),
  summary: document.getElementById('view-summary'),
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
}

function send(message) {
  return new Promise((resolve) => chrome.runtime.sendMessage(message, resolve));
}

function showView(name) {
  Object.entries(views).forEach(([key, el]) => {
    el.hidden = key !== name;
  });
}

function renderStart() {
  showView('start');
  document.getElementById('goal-input').value = '';
  stopTick();
}

async function onStart() {
  const goal = document.getElementById('goal-input').value.trim();
  if (!goal) return;
  const session = await send({ type: MSG.START_SESSION, goal });
  renderActive(session);
}

function renderActive(session) {
  showView('active');
  document.getElementById('active-goal').textContent = session.goal;
  renderEventsList(document.getElementById('events-list'), session.events.slice(-6).reverse());
  updatePill(session);
  startTick(session);
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

  const { counts, totalPages, avgScore, durationMs } = summary;
  document.getElementById('summary-stats').innerHTML = `
    <div class="stat"><span class="stat__value">${totalPages}</span><span class="stat__label">Pages</span></div>
    <div class="stat"><span class="stat__value">${formatDuration(durationMs)}</span><span class="stat__label">Duration</span></div>
    <div class="stat"><span class="stat__value">${avgScore != null ? Math.round(avgScore * 100) + '%' : '—'}</span><span class="stat__label">Avg align</span></div>
    <div class="stat"><span class="stat__value">${counts.HIGH || 0}</span><span class="stat__label">Alerts</span></div>
  `;

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
      <span class="event__title">${escapeHtml(e.title || e.url)}</span>
      <span class="event__score">${Math.round(e.score * 100)}%</span>
    `;
    el.appendChild(li);
  });
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
