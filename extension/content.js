// Content script: extracts basic page context, reports it to the background
// worker on load and on SPA navigation, and renders the intervention modal
// when asked to.
(function anchorContentScript() {
  let lastUrl = location.href;
  let modalShown = false;

  init();

  function init() {
    reportPageContext();
    patchHistoryForSpaNav();

    chrome.runtime.onMessage.addListener((message) => {
      if (message.type === MSG.SHOW_INTERVENTION) {
        showIntervention(message.payload);
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

  function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str || '';
    return div.innerHTML;
  }

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
