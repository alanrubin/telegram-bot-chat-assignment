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
import secrets

from fastapi import APIRouter, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.config import get_settings
from app.schemas import ErrorFrame, SendCommand
from app.telegram_service import NoActiveChatError

logger = logging.getLogger("app.routes")

router = APIRouter()


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.post("/session/reset")
async def reset_session(
    request: Request, x_reset_token: str | None = Header(default=None)
):
    """Unbind the current participant so a new chat can claim the slot.

    State-changing and otherwise unauthenticated, so it is gated behind a shared secret: the
    ``X-Reset-Token`` header must match ``SESSION_RESET_TOKEN``. When no token is configured
    the endpoint is disabled. Requiring a custom header also blocks cross-site CSRF (it can't
    be sent cross-origin without a CORS preflight the origin allowlist rejects), and the token
    itself stops anyone who can reach the port from hijacking the session via reset.
    """
    expected = get_settings().session_reset_token
    if not expected:
        raise HTTPException(status_code=403, detail="Session reset is disabled.")
    if x_reset_token is None or not secrets.compare_digest(x_reset_token, expected):
        raise HTTPException(status_code=403, detail="Invalid or missing reset token.")

    await request.app.state.session.reset()
    # Clear the previous participant's conversation so a new chat starts a clean session
    # (and connected clients see an empty history), then mark no active chat.
    await request.app.state.manager.reset_history()
    await request.app.state.manager.broadcast_status(connected=True, active_chat=False)
    return {"status": "reset"}


def _origin_allowed(websocket: WebSocket) -> bool:
    """Reject cross-site WebSocket handshakes (CSWSH).

    The CORS middleware only guards HTTP requests, and WebSockets are exempt from the browser
    same-origin policy, so without this check any cross-origin page could open ``/ws``, read
    the full history, and send messages to the bound chat. A browser always sends an ``Origin``
    header on the handshake, so a present-but-disallowed origin is a cross-origin page and is
    refused. A missing origin is a non-browser client (tests/CLI), which is not a CSWSH vector.
    """
    origin = websocket.headers.get("origin")
    if origin is None:
        return True
    return origin in get_settings().cors_origins_list


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    manager = websocket.app.state.manager
    session = websocket.app.state.session
    telegram = websocket.app.state.telegram

    if not _origin_allowed(websocket):
        logger.warning("Rejected WebSocket handshake from origin %s", websocket.headers.get("origin"))
        await websocket.close(code=1008)  # policy violation
        return

    await websocket.accept()
    try:
        # Register + send initial status and history atomically (no message can interleave).
        await manager.connect_and_sync(websocket, active_chat=session.has_active_chat)

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
