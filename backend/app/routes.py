"""HTTP and WebSocket routes.

The WebSocket at ``/ws`` is the single full-duplex channel between the browser and the
backend (see D1). On connect a client receives the current status and the full message
history; thereafter it sends ``{"type":"send","text":...}`` frames, which are forwarded to
the bound Telegram chat. Incoming Telegram messages and the server-authoritative echo of
outgoing ones are pushed to every connected client by the ConnectionManager.

Client failures are surfaced, not swallowed (see D8): malformed frames, empty text, no bound
chat, and Telegram send errors all return an ``error`` frame; a disconnect simply deregisters
the client.
"""

import logging

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.schemas import ErrorFrame, SendCommand, StatusFrame
from app.telegram_service import NoActiveChatError

logger = logging.getLogger("app.routes")

router = APIRouter()


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.post("/session/reset")
async def reset_session(request: Request):
    """Unbind the current participant so a new chat can claim the slot."""
    await request.app.state.session.reset()
    await request.app.state.manager.broadcast_status(connected=True, active_chat=False)
    return {"status": "reset"}


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    manager = websocket.app.state.manager
    session = websocket.app.state.session
    telegram = websocket.app.state.telegram

    await websocket.accept()
    await manager.connect(websocket)
    try:
        # Initial sync: current status, then the full session history.
        await websocket.send_text(
            StatusFrame(connected=True, activeChat=session.has_active_chat).model_dump_json()
        )
        await manager.send_history(websocket)

        while True:
            raw = await websocket.receive_text()
            await _handle_client_message(raw, websocket, telegram)
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        logger.exception("Unexpected WebSocket error; closing connection")
        manager.disconnect(websocket)


async def _handle_client_message(raw: str, websocket: WebSocket, telegram) -> None:
    """Parse and act on one inbound frame, surfacing any problem as an error frame."""
    try:
        command = SendCommand.model_validate_json(raw)
    except (ValidationError, ValueError):
        await _send_error(websocket, "Invalid message format.")
        return

    text = command.text.strip()
    if not text:
        await _send_error(websocket, "Cannot send an empty message.")
        return

    try:
        await telegram.send_to_active(text)
    except NoActiveChatError:
        await _send_error(
            websocket,
            "No active Telegram chat yet. Wait for the participant to start the conversation.",
        )
    except Exception:
        logger.exception("Failed to deliver message to Telegram")
        await _send_error(websocket, "Failed to send your message. Please try again.")


async def _send_error(websocket: WebSocket, detail: str) -> None:
    await websocket.send_text(ErrorFrame(detail=detail).model_dump_json())
