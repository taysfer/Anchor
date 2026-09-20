// Content script: extracts basic page context, reports it to the background
// worker on load and on SPA navigation, and renders the intervention modal
// when asked to.
(function anchorContentScript() {
  let lastUrl = location.href;
  let modalShown = false;
  let toast = null; // the attention warning currently on screen, if any

  init();

  function init() {
    reportPageContext();
    patchHistoryForSpaNav();

    chrome.runtime.onMessage.addListener((message) => {
      if (message.type === MSG.SHOW_INTERVENTION) {
        showIntervention(message.payload);
      } else if (message.type === MSG.SHOW_ATTENTION_WARNING) {
        showAttentionWarning(message.payload);
      } else if (message.type === MSG.HIDE_ATTENTION_WARNING) {
        hideAttentionWarning(message.payload);
      }
    });
  }

  // Many high-drift destinations (YouTube, social feeds) are single-page apps
  // that change the URL via history.pushState instead of a full navigation,
  // so a normal page-load-only content script would miss them.
  function patchHistoryForSpaNav() {
    const wrap = (fn) =>
      function patched(...args) {
        const result = fn.apply(this, args);
        onUrlMayHaveChanged();
        return result;
      };
    history.pushState = wrap(history.pushState);
    history.replaceState = wrap(history.replaceState);
    window.addEventListener('popstate', onUrlMayHaveChanged);
  }

  function onUrlMayHaveChanged() {
    if (location.href === lastUrl) return;
    lastUrl = location.href;
    modalShown = false;
    // Give the SPA a beat to update the title/DOM before we read it.
    setTimeout(reportPageContext, 700);
  }

  function reportPageContext() {
    const pageContext = extractPageContext();
    sendToBackground({ type: MSG.PAGE_CONTEXT, payload: pageContext });
  }

  function extractPageContext() {
    const description =
      document.querySelector('meta[name="description"]')?.content ||
      document.querySelector('meta[property="og:description"]')?.content ||
      '';
    const text = (document.body?.innerText || '').slice(0, 2000);
    return {
      url: location.href,
      title: document.title || '',
      description,
      text,
    };
  }

  function sendToBackground(message) {
    return new Promise((resolve) => chrome.runtime.sendMessage(message, resolve));
  }

  function showIntervention(payload) {
    if (modalShown) return;
    modalShown = true;

    const host = document.createElement('div');
    host.id = 'anchor-intervention-host';
    document.documentElement.appendChild(host);
    const shadow = host.attachShadow({ mode: 'open' });

    const style = document.createElement('style');
    style.textContent = MODAL_CSS;
    shadow.appendChild(style);

    const wrapper = document.createElement('div');
    wrapper.className = 'anchor-overlay';
    wrapper.innerHTML = `
      <div class="anchor-card" role="dialog" aria-modal="true">
        <div class="anchor-card__title">Still what you came here for?</div>
        <div class="anchor-card__goal">You said you wanted to: <strong>${escapeHtml(payload.goal)}</strong></div>
        <div class="anchor-card__body">Your recent browsing has been moving away from that.</div>
        <div class="anchor-card__actions">
          <button type="button" class="anchor-btn anchor-btn--primary" data-action="return">Return to goal</button>
          <button type="button" class="anchor-btn" data-action="keep">Keep browsing</button>
        </div>
      </div>
    `;
    shadow.appendChild(wrapper);

    wrapper.querySelector('[data-action="return"]').addEventListener('click', () => {
      sendToBackground({ type: MSG.RETURN_TO_GOAL });
      teardown();
    });
    wrapper.querySelector('[data-action="keep"]').addEventListener('click', () => {
      sendToBackground({ type: MSG.KEEP_BROWSING });
      teardown();
    });

    function teardown() {
      host.remove();
      modalShown = false;
    }
  }

  // Banner shown when the webcam notices the user looking away. Small and
  // non-blocking normally; with payload.large (a full-screen browser, where a
  // separate warning window would pull the user out of full screen) it fills the
  // page with a pulsing red screen, a running away-timer and a repeating chime.
  function showAttentionWarning(payload) {
    removeAttentionToast();

    const host = document.createElement('div');
    host.id = 'anchor-attention-host';
    document.documentElement.appendChild(host);
    const shadow = host.attachShadow({ mode: 'open' });

    const style = document.createElement('style');
    style.textContent = TOAST_CSS;
    shadow.appendChild(style);

    const card = document.createElement('div');
    card.className = payload.large ? 'anchor-toast anchor-toast--large' : 'anchor-toast';
    card.setAttribute('role', 'status');
    card.innerHTML = `
      <div class="anchor-toast__body">
        <div class="anchor-toast__title">Still with us?</div>
        <div class="anchor-toast__text">Looks like you looked away from the screen. You were working on: <strong>${escapeHtml(payload.goal)}</strong></div>
        <div class="anchor-toast__timer"></div>
      </div>
      <button type="button" class="anchor-toast__close">${payload.large ? 'I am back' : 'Dismiss'}</button>
    `;
    shadow.appendChild(card);
    card.querySelector('.anchor-toast__close').addEventListener('click', removeAttentionToast);

    toast = { host, card, goal: payload.goal, hideTimer: null, timerId: null, chimeId: null };

    if (payload.large) {
      const timerEl = card.querySelector('.anchor-toast__timer');
      const since = payload.since || Date.now();
      const tick = () => {
        timerEl.textContent = `Away for ${formatClock(Date.now() - since)}`;
      };
      tick();
      toast.timerId = setInterval(tick, 1000);
      chime();
      toast.chimeId = setInterval(chime, 6000); // someone looking away can easily miss one
    }
  }

  // With awayMs, swap to a short "welcome back" state (hiding it the instant the
  // user looks back would mean they never see it); without, remove it now.
  function hideAttentionWarning(payload) {
    if (!toast) return;
    const awayMs = payload && payload.awayMs;
    if (awayMs == null) {
      removeAttentionToast();
      return;
    }

    clearInterval(toast.timerId);
    clearInterval(toast.chimeId);
    toast.card.classList.add('anchor-toast--back');
    toast.card.querySelector('.anchor-toast__title').textContent = 'Welcome back';
    toast.card.querySelector('.anchor-toast__text').textContent =
      `You were away for ${formatAway(awayMs)}. Back to: ${toast.goal}`;
    clearTimeout(toast.hideTimer);
    toast.hideTimer = setTimeout(removeAttentionToast, 4000);
  }

  function removeAttentionToast() {
    if (!toast) return;
    clearTimeout(toast.hideTimer);
    clearInterval(toast.timerId);
    clearInterval(toast.chimeId);
    toast.host.remove();
    toast = null;
  }

  function formatClock(ms) {
    const total = Math.max(0, Math.round(ms / 1000));
    return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`;
  }

  // A soft two-note chime. Best effort: a page may block audio it hasn't been
  // interacted with, in which case the red screen is the warning.
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
      // No audio available.
    }
  }

  function formatAway(ms) {
    const totalSec = Math.max(1, Math.round(ms / 1000));
    if (totalSec < 60) return `${totalSec}s`;
    return `${Math.floor(totalSec / 60)}m ${totalSec % 60}s`;
  }

  function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str || '';
    return div.innerHTML;
  }

  const TOAST_CSS = `
    :host { all: initial; }
    .anchor-toast {
      position: fixed;
      top: 16px;
      left: 50%;
      transform: translateX(-50%);
      z-index: 2147483647;
      width: min(440px, 92vw);
      display: flex;
      align-items: center;
      gap: 12px;
      background: #ffffff;
      color: #14161a;
      border: 1px solid #e4e6eb;
      border-left: 4px solid #e0a90b;
      border-radius: 10px;
      padding: 12px 14px;
      box-shadow: 0 8px 30px rgba(0, 0, 0, 0.18);
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      animation: anchor-toast-in 200ms ease-out;
    }
    .anchor-toast--back { border-left-color: #2fa860; }
    .anchor-toast__timer { display: none; }
    .anchor-toast--large {
      inset: 0;
      transform: none;
      width: auto;
      flex-direction: column;
      justify-content: center;
      gap: 28px;
      text-align: center;
      background: #b3261e;
      color: #ffffff;
      border: none;
      border-radius: 0;
      padding: 32px;
      animation: anchor-away-pulse 2.4s ease-in-out infinite;
    }
    .anchor-toast--large.anchor-toast--back { background: #1f7a45; animation: none; }
    .anchor-toast--large .anchor-toast__body { flex: none; }
    .anchor-toast--large .anchor-toast__title { font-size: 44px; margin-bottom: 14px; }
    .anchor-toast--large .anchor-toast__text { font-size: 20px; color: rgba(255, 255, 255, 0.9); }
    .anchor-toast--large .anchor-toast__timer {
      display: block;
      margin-top: 18px;
      font-size: 28px;
      font-weight: 700;
      font-variant-numeric: tabular-nums;
    }
    .anchor-toast--large .anchor-toast__close { font-size: 16px; padding: 10px 22px; }
    @keyframes anchor-away-pulse {
      0%, 100% { background: #b3261e; }
      50% { background: #d93a2f; }
    }
    .anchor-toast__body { flex: 1; min-width: 0; }
    .anchor-toast__title {
      font-size: 14px;
      font-weight: 700;
      margin-bottom: 2px;
    }
    .anchor-toast__text {
      font-size: 12.5px;
      color: #5b616b;
      line-height: 1.4;
    }
    .anchor-toast__close {
      flex-shrink: 0;
      border: 1px solid #d7dbe0;
      background: #ffffff;
      color: #14161a;
      font-size: 12px;
      font-weight: 600;
      padding: 6px 10px;
      border-radius: 6px;
      cursor: pointer;
    }
    .anchor-toast__close:hover { background: #f2f4f7; }
    @keyframes anchor-toast-in {
      from { opacity: 0; transform: translate(-50%, -8px); }
      to { opacity: 1; transform: translate(-50%, 0); }
    }
  `;

  const MODAL_CSS = `
    :host { all: initial; }
    .anchor-overlay {
      position: fixed;
      inset: 0;
      z-index: 2147483647;
      display: flex;
      align-items: center;
      justify-content: center;
      background: rgba(15, 17, 21, 0.55);
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      animation: anchor-fade-in 150ms ease-out;
    }
    .anchor-card {
      width: min(360px, 90vw);
      background: #ffffff;
      border-radius: 14px;
      padding: 22px 22px 18px;
      box-shadow: 0 12px 40px rgba(0, 0, 0, 0.25);
      color: #14161a;
    }
    .anchor-card__title {
      font-size: 17px;
      font-weight: 700;
      margin-bottom: 10px;
    }
    .anchor-card__goal {
      font-size: 13px;
      color: #3a3f47;
      background: #f2f4f7;
      border-radius: 8px;
      padding: 8px 10px;
      margin-bottom: 10px;
      line-height: 1.4;
    }
    .anchor-card__body {
      font-size: 13px;
      color: #5b616b;
      margin-bottom: 18px;
      line-height: 1.4;
    }
    .anchor-card__actions {
      display: flex;
      gap: 8px;
    }
    .anchor-btn {
      flex: 1;
      border: 1px solid #d7dbe0;
      background: #ffffff;
      color: #14161a;
      font-size: 13px;
      font-weight: 600;
      padding: 9px 10px;
      border-radius: 8px;
      cursor: pointer;
    }
    .anchor-btn:hover { background: #f2f4f7; }
    .anchor-btn--primary {
      background: #2f6fed;
      border-color: #2f6fed;
      color: #ffffff;
    }
    .anchor-btn--primary:hover { background: #2660d0; }
    @keyframes anchor-fade-in {
      from { opacity: 0; }
      to { opacity: 1; }
    }
  `;
})();
