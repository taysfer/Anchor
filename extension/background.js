// Service worker: owns session state, runs the (stubbed) drift check on each
// page context report, and decides when to trigger an intervention.
importScripts('shared.js');

let interventionCooldownUntil = 0;

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
      return startSession(message.goal);
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
    default:
      return null;
  }
}

async function startSession(goal) {
  const session = {
    id: generateId(),
    goal: (goal || '').trim(),
    startedAt: Date.now(),
    endedAt: null,
    active: true,
    events: [],
    lastAnchorUrl: null,
    consecutiveHigh: 0,
  };
  interventionCooldownUntil = 0;
  return setSession(session);
}

async function endSession() {
  const session = await getSession();
  if (!session) return null;
  session.active = false;
  session.endedAt = Date.now();
  await setSession(session);
  return buildSummary(session);
}

async function handlePageContext(pageContext, sender) {
  const session = await getSession();
  if (!session || !session.active) return null;

  const score = await computeDriftScoreStub(session.goal, pageContext);
  const classification = classifyScore(score);

  const event = {
    timestamp: Date.now(),
    url: pageContext.url,
    title: pageContext.title,
    score,
    classification,
  };
  session.events.push(event);

  if (classification === DRIFT.LOW) {
    session.lastAnchorUrl = pageContext.url;
    session.consecutiveHigh = 0;
  } else if (classification === DRIFT.HIGH) {
    session.consecutiveHigh = (session.consecutiveHigh || 0) + 1;
  } else {
    session.consecutiveHigh = 0;
  }

  await setSession(session);
  notifyPopup(session);

  const now = Date.now();
  const shouldIntervene =
    session.consecutiveHigh >= CONSECUTIVE_HIGH_DRIFT_THRESHOLD && now > interventionCooldownUntil;

  if (shouldIntervene && sender.tab && sender.tab.id != null) {
    interventionCooldownUntil = now + INTERVENTION_COOLDOWN_MS;
    chrome.tabs.sendMessage(sender.tab.id, {
      type: MSG.SHOW_INTERVENTION,
      payload: { goal: session.goal, event, lastAnchorUrl: session.lastAnchorUrl },
    });
  }

  return { score, classification };
}

async function keepBrowsing() {
  const session = await getSession();
  if (!session) return null;
  session.consecutiveHigh = 0;
  return setSession(session);
}

async function returnToGoal(sender) {
  const session = await getSession();
  if (!session || !session.lastAnchorUrl) return false;
  if (sender.tab && sender.tab.id != null) {
    chrome.tabs.update(sender.tab.id, { url: session.lastAnchorUrl });
  }
  session.consecutiveHigh = 0;
  await setSession(session);
  return true;
}

function notifyPopup(session) {
  chrome.runtime.sendMessage({ type: MSG.SESSION_UPDATED, payload: session }, () => {
    // No popup open to receive it -- chrome sets lastError, just swallow it.
    void chrome.runtime.lastError;
  });
}
