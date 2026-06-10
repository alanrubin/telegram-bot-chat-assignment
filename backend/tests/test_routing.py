"""Message routing tests.

Two layers, both with Telegram mocked:
- Service routing (async): incoming messages from the bound chat are recorded + broadcast,
  other chats are rejected, and incoming/outgoing keep insertion order.
- WebSocket transport (sync, via TestClient): connect -> status + history; a client send is
  forwarded to Telegram and broadcast; errors are surfaced; broadcasts reach all clients.
"""

import json
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.session import ChatSession
from app.store import ConnectionManager, MessageStore
from app.telegram_service import TelegramService


def _make_service():
    session = ChatSession()
    manager = ConnectionManager(MessageStore())
    service = TelegramService("token", session, manager)
    service._bot = AsyncMock()  # stand in for the Telegram bot
    return service, session, manager


def _message_texts(client) -> list[str]:
    frames = [json.loads(p) for p in client.received]
    return [f["message"]["text"] for f in frames if f["type"] == "message"]


# --- Service routing (async, no FastAPI) -----------------------------------------------

async def test_incoming_from_bound_chat_is_recorded_and_broadcast(new_client, ts):
    service, _session, manager = _make_service()
    ws = new_client()
    await manager.connect(ws)

    msg = await service.handle_incoming(111, "hello", "Alan", ts(0))

    assert msg is not None and msg.direction == "incoming"
    assert _message_texts(ws) == ["hello"]


async def test_incoming_from_other_chat_is_rejected_and_not_broadcast(new_client, ts):
    service, session, manager = _make_service()
    await session.claim(111)  # chat 111 holds the slot
    ws = new_client()
    await manager.connect(ws)

    result = await service.handle_incoming(222, "intruder", "Bob", ts(0))

    assert result is None
    assert _message_texts(ws) == []          # nothing broadcast for the rejected chat
    service._bot.send_message.assert_awaited()  # a rejection reply was sent


async def test_outgoing_send_targets_bound_chat(ts):
    service, session, _manager = _make_service()
    await session.claim(111)

    out = await service.send_to_active("reply")

    assert out.direction == "outgoing"
    service._bot.send_message.assert_awaited_with(chat_id=111, text="reply")


async def test_messages_keep_insertion_order(new_client, ts):
    service, _session, manager = _make_service()
    ws = new_client()
    await manager.connect(ws)

    await service.handle_incoming(111, "in1", "Alan", ts(0))  # claims slot, id 1
    await service.send_to_active("out1")                       # id 2
    await service.handle_incoming(111, "in2", "Alan", ts(1))  # id 3

    assert _message_texts(ws) == ["in1", "out1", "in2"]


# --- WebSocket transport (sync, via TestClient) ----------------------------------------

@pytest.fixture
def client(monkeypatch):
    """A TestClient whose Telegram bot lifecycle is mocked (no network)."""
    import app.telegram_service as tg

    async def fake_start(self):
        self._bot = AsyncMock()

    async def fake_stop(self):
        pass

    monkeypatch.setattr(tg.TelegramService, "start", fake_start)
    monkeypatch.setattr(tg.TelegramService, "stop", fake_stop)

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


def test_ws_connect_receives_status_then_history(client):
    with client.websocket_connect("/ws") as ws:
        status = json.loads(ws.receive_text())
        history = json.loads(ws.receive_text())

    assert status["type"] == "status" and status["activeChat"] is False
    assert history["type"] == "history" and history["messages"] == []


def test_ws_send_forwards_to_telegram_and_broadcasts(client):
    from app.main import app

    # Arrange: a chat is already bound (set internal state directly for the test).
    app.state.session._active_chat_id = 111

    with client.websocket_connect("/ws") as ws:
        ws.receive_text()  # status
        ws.receive_text()  # history
        ws.send_text(json.dumps({"type": "send", "text": "hello"}))
        frame = json.loads(ws.receive_text())  # server-authoritative echo

    assert frame["type"] == "message"
    assert frame["message"]["direction"] == "outgoing"
    assert frame["message"]["text"] == "hello"
    app.state.telegram._bot.send_message.assert_awaited_with(chat_id=111, text="hello")


def test_ws_send_without_active_chat_returns_error(client):
    from app.main import app

    with client.websocket_connect("/ws") as ws:
        ws.receive_text()  # status
        ws.receive_text()  # history
        ws.send_text(json.dumps({"type": "send", "text": "hi"}))
        frame = json.loads(ws.receive_text())

    assert frame["type"] == "error"
    app.state.telegram._bot.send_message.assert_not_awaited()


def test_ws_malformed_frame_returns_error(client):
    with client.websocket_connect("/ws") as ws:
        ws.receive_text()  # status
        ws.receive_text()  # history
        ws.send_text("this is not json")
        frame = json.loads(ws.receive_text())

    assert frame["type"] == "error"


def test_ws_empty_text_returns_error(client):
    with client.websocket_connect("/ws") as ws:
        ws.receive_text()  # status
        ws.receive_text()  # history
        ws.send_text(json.dumps({"type": "send", "text": "   "}))
        frame = json.loads(ws.receive_text())

    assert frame["type"] == "error"


def test_ws_broadcast_reaches_all_clients(client):
    from app.main import app

    app.state.session._active_chat_id = 111

    with client.websocket_connect("/ws") as ws1, client.websocket_connect("/ws") as ws2:
        for ws in (ws1, ws2):
            ws.receive_text()  # status
            ws.receive_text()  # history
        ws1.send_text(json.dumps({"type": "send", "text": "yo"}))
        f1 = json.loads(ws1.receive_text())
        f2 = json.loads(ws2.receive_text())

    assert f1["message"]["text"] == "yo"
    assert f2["message"]["text"] == "yo"


# --- Security hardening: origin check, message size cap, reset token --------------------

def test_ws_overlong_text_returns_error(client):
    """A frame above the size cap is rejected as malformed and never reaches Telegram."""
    from app.main import app

    app.state.session._active_chat_id = 111

    with client.websocket_connect("/ws") as ws:
        ws.receive_text()  # status
        ws.receive_text()  # history
        ws.send_text(json.dumps({"type": "send", "text": "x" * 5000}))
        frame = json.loads(ws.receive_text())

    assert frame["type"] == "error"
    app.state.telegram._bot.send_message.assert_not_awaited()


def test_ws_rejects_disallowed_origin(client):
    """A cross-origin browser handshake (CSWSH) is refused before accept."""
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws", headers={"origin": "http://evil.example"}):
            pass


def test_ws_allows_configured_origin(client):
    """An allowlisted origin connects normally."""
    with client.websocket_connect(
        "/ws", headers={"origin": "http://localhost:5173"}
    ) as ws:
        status = json.loads(ws.receive_text())

    assert status["type"] == "status"


def test_reset_disabled_without_token(client):
    """With no SESSION_RESET_TOKEN configured the endpoint is disabled."""
    resp = client.post("/session/reset")
    assert resp.status_code == 403


def test_reset_requires_valid_token(client, monkeypatch):
    """When a token is configured, only a matching X-Reset-Token succeeds."""
    import app.routes as routes
    from app.config import Settings

    test_settings = Settings(telegram_bot_token="t", session_reset_token="s3cret")
    monkeypatch.setattr(routes, "get_settings", lambda: test_settings)

    assert client.post("/session/reset").status_code == 403
    assert (
        client.post("/session/reset", headers={"X-Reset-Token": "wrong"}).status_code
        == 403
    )
    ok = client.post("/session/reset", headers={"X-Reset-Token": "s3cret"})
    assert ok.status_code == 200 and ok.json()["status"] == "reset"
