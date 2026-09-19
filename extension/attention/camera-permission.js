const statusEl = document.getElementById('perm-status');
const detailEl = document.getElementById('perm-detail');
const retryBtn = document.getElementById('perm-retry');

retryBtn.addEventListener('click', requestCamera);
requestCamera();

async function requestCamera() {
  retryBtn.hidden = true;
  statusEl.className = 'perm__status';
  statusEl.textContent = 'Requesting camera access…';
  detailEl.textContent = '';

  try {
    const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
    stream.getTracks().forEach((track) => track.stop());
    statusEl.className = 'perm__status perm__status--ok';
    statusEl.textContent = 'Camera access granted.';
    detailEl.textContent = 'You can close this tab and start your session.';
  } catch (err) {
    statusEl.className = 'perm__status perm__status--error';
    statusEl.textContent = 'Camera access is not available.';
    detailEl.textContent = explain(err);
    retryBtn.hidden = false;
  }
}

function explain(err) {
  switch (err && err.name) {
    case 'NotAllowedError':
    case 'SecurityError':
      return (
        'The request was blocked or dismissed. Click Try again and choose Allow. If Chrome does ' +
        'not ask, camera access may be blocked for this extension in chrome://settings/content/camera, ' +
        'or by your organization’s browser policy.'
      );
    case 'NotFoundError':
    case 'DevicesNotFoundError':
      return 'No camera was found on this device.';
    case 'NotReadableError':
      return 'The camera is in use by another app. Close it and try again.';
    default:
      return `Something went wrong (${(err && err.name) || 'unknown error'}).`;
  }
}
