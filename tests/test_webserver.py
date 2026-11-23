"""Real HTTP tests for the web server (visualizer + remote phone chat), not mocks of the code
under test - same approach used to verify the crystal-sphere visualizer during development."""
import json
import queue
import threading
import urllib.error
import urllib.request

import pytest

from assistant import config
from assistant.webserver import WebVisualizer


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setattr(config, "REMOTE_ACCESS", False)   # tests bind to 127.0.0.1 regardless
    rq = queue.Queue()
    v = WebVisualizer(port=0, open_browser=False, request_queue=rq)
    v.start()
    assert v._ok, "server failed to start"
    yield v, rq
    v.stop()


def _get(v, path):
    return urllib.request.urlopen(f"http://127.0.0.1:{v.port}{path}", timeout=5)


def _post(v, path, payload):
    req = urllib.request.Request(
        f"http://127.0.0.1:{v.port}{path}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    return urllib.request.urlopen(req, timeout=5)


def test_chat_page_is_served(server):
    v, rq = server
    r = _get(v, "/chat")
    html = r.read().decode()
    assert r.status == 200 and "Jarvis" in html and 'id="bar"' in html


def test_chat_assets_are_served(server):
    v, rq = server
    css = _get(v, "/chat.css").read().decode()
    js = _get(v, "/chat.js").read().decode()
    assert "#bar" in css
    assert "api/message" in js and "SpeechRecognition" in js


def test_message_roundtrips_through_the_queue(server):
    """A POST should enqueue (text, confidence, respond) and wait for respond() to be called -
    exactly how main.py's loop will drive it, just with a fake backend here."""
    v, rq = server

    def fake_backend():
        text, conf, respond = rq.get(timeout=5)
        assert text == "what time is it" and conf == 1.0
        respond("It is 3:45 PM.")

    threading.Thread(target=fake_backend, daemon=True).start()
    r = _post(v, "/api/message", {"text": "what time is it"})
    assert json.loads(r.read()) == {"reply": "It is 3:45 PM."}


def test_empty_message_is_rejected(server):
    v, rq = server
    with pytest.raises(urllib.error.HTTPError) as e:
        _post(v, "/api/message", {"text": "  "})
    assert e.value.code == 400


def test_message_without_a_wired_queue_returns_503(monkeypatch):
    """When the visualizer runs without remote access (the default), /api/message must not hang
    or crash - it should clearly say this instance isn't wired up for it."""
    monkeypatch.setattr(config, "REMOTE_ACCESS", False)
    v = WebVisualizer(port=0, open_browser=False, request_queue=None)
    v.start()
    try:
        with pytest.raises(urllib.error.HTTPError) as e:
            _post(v, "/api/message", {"text": "hello"})
        assert e.value.code == 503
    finally:
        v.stop()


def test_slow_backend_times_out_instead_of_hanging_forever(server, monkeypatch):
    """Nobody ever drains the queue / calls respond() - the HTTP client must still get an answer,
    not hang forever. Shrink the real timeout so the test itself stays fast."""
    from assistant.webserver import _Handler
    monkeypatch.setattr(_Handler, "REPLY_TIMEOUT", 0.2)
    v, rq = server   # nothing reads from rq, so the handler's result.get() will time out
    with pytest.raises(urllib.error.HTTPError) as e:
        _post(v, "/api/message", {"text": "hello"})
    assert e.value.code == 504


def test_remote_access_binds_to_every_interface(monkeypatch):
    """REMOTE_ACCESS=1 must bind 0.0.0.0 (phone-reachable); off (default) stays 127.0.0.1-only."""
    monkeypatch.setattr(config, "REMOTE_ACCESS", True)
    v = WebVisualizer(port=0, open_browser=False, request_queue=queue.Queue())
    v.start()
    try:
        assert v._ok and v._server.server_address[0] == "0.0.0.0"
    finally:
        v.stop()
