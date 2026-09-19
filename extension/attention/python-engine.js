// WebSocket client for the optional Python attention server (see server/).
// Loaded into the background service worker with importScripts().
//
// The server sends the same status/state/away/returned events the in-browser
// engine produces, so the rest of the extension doesn't care which one is used.
// Its periodic pings also keep the service worker from being put to sleep.

const PythonEngine = (() => {
  const MAX_RECONNECTS = 3;
  const RECONNECT_DELAY_MS = 2000;

  let socket = null;
  let wantOpen = false;
  let reconnects = 0;
  let startMessage = null;
  let handlers = null; // { onEvent(message), onFailure(errorCode) }

  function open() {
    socket = new WebSocket(PYTHON_ENGINE_WS_URL);

    socket.onopen = () => {
      reconnects = 0;
      socket.send(JSON.stringify(startMessage));
    };

    socket.onmessage = (event) => {
      let message;
      try {
        message = JSON.parse(event.data);
      } catch {
        return;
      }
      if (message.type !== 'ping') handlers.onEvent(message);
    };

    socket.onclose = () => {
      socket = null;
      if (!wantOpen) return;
      if (reconnects < MAX_RECONNECTS) {
        reconnects += 1;
        setTimeout(() => wantOpen && !socket && open(), RECONNECT_DELAY_MS);
      } else {
        wantOpen = false;
        handlers.onFailure('server-unreachable');
      }
    };
  }

  function stop() {
    wantOpen = false;
    if (!socket) return;
    const closing = socket;
    socket = null;
    try {
      closing.send(JSON.stringify({ type: 'stop' }));
    } catch {
      // Not connected yet; closing is enough.
    }
    closing.close();
  }

  return {
    start(config, newHandlers) {
      stop();
      handlers = newHandlers;
      startMessage = { type: 'start', config };
      wantOpen = true;
      reconnects = 0;
      open();
    },
    stop,
    recalibrate() {
      if (!socket || socket.readyState !== WebSocket.OPEN) return false;
      socket.send(JSON.stringify({ type: 'recalibrate' }));
      return true;
    },
    isActive() {
      return wantOpen;
    },
  };
})();
