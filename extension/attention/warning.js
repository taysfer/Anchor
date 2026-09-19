// The pop-up window shown when the user has looked away (opened by background.js).
const since = Number(new URLSearchParams(location.search).get('since')) || Date.now();
const timerEl = document.getElementById('warning-timer');
const REPEAT_CHIME_MS = 6000;
let timerId = null;
let chimeId = null;

document.getElementById('warning-dismiss').addEventListener('click', closeWindow);

chrome.runtime.sendMessage({ type: MSG.GET_SESSION }, (session) => {
  void chrome.runtime.lastError;
  if (session) document.getElementById('warning-goal').textContent = session.goal;
});

chrome.runtime.onMessage.addListener((message) => {
  if (message.type !== MSG.HIDE_ATTENTION_WARNING) return;
  const awayMs = message.payload && message.payload.awayMs;
  if (awayMs == null) {
    closeWindow();
    return;
  }
  // The user is back: say so briefly before closing, so they see it.
  clearInterval(timerId);
  clearInterval(chimeId);
  document.getElementById('warning').classList.add('warning--back');
  document.getElementById('warning-title').textContent = 'Welcome back';
  document.getElementById('warning-text').textContent = 'Glad you’re back to it.';
  timerEl.textContent = `You were away for ${formatAway(awayMs)}`;
  setTimeout(closeWindow, 3000);
});

function tick() {
  timerEl.textContent = `Away for ${formatAway(Date.now() - since)}`;
}
tick();
timerId = setInterval(tick, 1000);

// Repeat the chime until they look back: someone looking away can easily miss one.
chime();
chimeId = setInterval(chime, REPEAT_CHIME_MS);

enlarge();

function formatAway(ms) {
  const total = Math.max(0, Math.round(ms / 1000));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`;
}

function closeWindow() {
  chrome.windows.getCurrent((win) => {
    if (win) chrome.windows.remove(win.id);
  });
}

// Make the window big (about 70% of the screen, centred) so it is hard to miss
// from the corner of an eye, however far away the user has looked.
function enlarge() {
  const width = Math.round(screen.availWidth * 0.7);
  const height = Math.round(screen.availHeight * 0.62);
  const left = Math.round((screen.availLeft || 0) + (screen.availWidth - width) / 2);
  const top = Math.round((screen.availTop || 0) + (screen.availHeight - height) / 2);
  chrome.windows.getCurrent((win) => {
    if (win) chrome.windows.update(win.id, { width, height, left, top, focused: true });
  });
}

// A soft two-note chime, since the whole point is that you are looking elsewhere.
// Best effort: the browser may block audio that starts without a user gesture.
function chime() {
  try {
    const context = new AudioContext();
    const note = (frequency, startAt) => {
      const oscillator = context.createOscillator();
      const gain = context.createGain();
      const start = context.currentTime + startAt;
      oscillator.frequency.value = frequency;
      gain.gain.setValueAtTime(0.0001, start);
      gain.gain.exponentialRampToValueAtTime(0.35, start + 0.03);
      gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.5);
      oscillator.connect(gain).connect(context.destination);
      oscillator.start(start);
      oscillator.stop(start + 0.55);
    };
    if (context.state === 'suspended') context.resume();
    note(660, 0);
    note(880, 0.3);
    setTimeout(() => context.close(), 1500);
  } catch {
    // No audio available; the window itself is the warning.
  }
}
