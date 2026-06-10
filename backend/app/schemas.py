"""Pydantic models for chat messages and the WebSocket wire protocol.

A single ``Message`` shape is shared by both directions. Frames exchanged over the
WebSocket are discriminated by a ``type`` field so the client can ``switch`` on it; field
names (``direction``, ``timestamp``, ``activeChat``) are aligned with what the frontend
consumes. Datetimes serialize to ISO-8601 via pydantic's JSON encoding.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

Direction = Literal["incoming", "outgoing"]


class Message(BaseModel):
    """A single chat message, ordered by ``id``.

    ``id`` is a monotonically increasing integer assigned at the single broadcast point,
    which is what guarantees message ordering (see DECISIONS.md). ``timestamp`` is the time
    the message was sent — for incoming messages this is Telegram's ``message.date``.
    """

    id: int
    text: str
    timestamp: datetime
    direction: Direction
    sender: str


# --- Client -> server frames ---

class SendCommand(BaseModel):
    """An outgoing message typed by the user in the web UI."""

    type: Literal["send"]
    text: str


# --- Server -> client frames ---

class HistoryFrame(BaseModel):
    """Full current-session history, sent immediately on (re)connect."""

    type: Literal["history"] = "history"
    messages: list[Message]


class MessageFrame(BaseModel):
    """A single new message broadcast to all connected clients."""

    type: Literal["message"] = "message"
    message: Message


class StatusFrame(BaseModel):
    """Connection/session status for the UI (drives the status dot and send-enabled state)."""

    type: Literal["status"] = "status"
    connected: bool
    activeChat: bool


class ErrorFrame(BaseModel):
    """A non-fatal error surfaced to the client (e.g. send failed, no active chat)."""

    type: Literal["error"] = "error"
    detail: str
