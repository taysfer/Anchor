import json

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import app as server

EXTENSION_ORIGIN = {"origin": "chrome-extension://abcdefghijklmnopabcdefghijklmnop"}


class FakeMonitor:
    instances = []

    def __init__(self, model_path, source, on_event):
        self.on_event = on_event
        self.started_with = None
        self.stopped = False
        self.recalibrated = False
        FakeMonitor.instances.append(self)

    def start(self, config):
        self.started_with = config
        self.on_event({"type": "status", "status": "active"})
        self.on_event({"type": "state", "state": "calibrating"})

    def stop(self, timeout=5.0):
        self.stopped = True

    def request_recalibrate(self):
        self.recalibrated = True


@pytest.fixture(autouse=True)
def fake_monitor(monkeypatch):
    FakeMonitor.instances = []
    monkeypatch.setattr(server, "AttentionMonitor", FakeMonitor)
    monkeypatch.setattr(server, "_active_monitor", None)
    monkeypatch.delenv("ANCHOR_ALLOWED_ORIGINS", raising=False)


@pytest.fixture
def client():
    return TestClient(server.app)


def send(ws, **message):
    ws.send_text(json.dumps(message))


def test_health(client):
    body = client.get("/health").json()
    assert body["ok"] is True and body["service"] == "anchor-attention"


def test_websites_cannot_connect(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/attention/ws", headers={"origin": "https://evil.example"}):
            pass
    assert FakeMonitor.instances == []


def test_allowed_origins_env_locks_to_one_extension(client, monkeypatch):
    monkeypatch.setenv("ANCHOR_ALLOWED_ORIGINS", "chrome-extension://onlythisone")
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/attention/ws", headers=EXTENSION_ORIGIN):
            pass


def test_start_streams_events_and_passes_config(client):
    with client.websocket_connect("/attention/ws", headers=EXTENSION_ORIGIN) as ws:
        send(ws, type="start", config={"awayThresholdMs": 3000})
        assert ws.receive_json() == {"type": "status", "status": "active"}
        assert ws.receive_json() == {"type": "state", "state": "calibrating"}
    assert FakeMonitor.instances[0].started_with.away_threshold_ms == 3000


def test_bad_config_reports_error_and_starts_nothing(client):
    with client.websocket_connect("/attention/ws", headers=EXTENSION_ORIGIN) as ws:
        send(ws, type="start", config={"awayThresholdMs": -1})
        assert ws.receive_json() == {"type": "status", "status": "error", "error": "bad-config"}
    assert FakeMonitor.instances == []


def test_recalibrate_and_stop_reach_the_monitor(client):
    with client.websocket_connect("/attention/ws", headers=EXTENSION_ORIGIN) as ws:
        send(ws, type="start", config={})
        ws.receive_json(), ws.receive_json()
        send(ws, type="recalibrate")
        send(ws, type="stop")
        send(ws, type="start", config={})  # round trip so the earlier messages have been handled
        ws.receive_json()
    first = FakeMonitor.instances[0]
    assert first.recalibrated and first.stopped


def test_disconnecting_releases_the_camera(client):
    with client.websocket_connect("/attention/ws", headers=EXTENSION_ORIGIN) as ws:
        send(ws, type="start", config={})
        ws.receive_json()
    assert FakeMonitor.instances[0].stopped


def test_a_second_connection_takes_over_the_camera(client):
    with client.websocket_connect("/attention/ws", headers=EXTENSION_ORIGIN) as first:
        send(first, type="start", config={})
        first.receive_json()
        with client.websocket_connect("/attention/ws", headers=EXTENSION_ORIGIN) as second:
            send(second, type="start", config={})
            second.receive_json()
            assert FakeMonitor.instances[0].stopped
            assert not FakeMonitor.instances[1].stopped
