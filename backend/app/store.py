"""In-memory message history and WebSocket fan-out.

``MessageStore`` keeps the current-session messages and assigns each a monotonically
increasing ``id``. ``ConnectionManager`` tracks the connected web clients and is the single
point through which every message is recorded and broadcast.

That single ``record_and_broadcast`` chokepoint — guarded by an ``asyncio.Lock`` — is what
guarantees ordering: messages are appended to one list and fanned out to clients in one
atomic step, so insertion order is the canonical order and per-client delivery order matches
it (see DECISIONS.md). State is in-memory and session-only; it resets on restart.

Clients are duck-typed: any object with an async ``send_text(str)`` method works, which keeps
this module decoupled from FastAPI's ``WebSocket`` and easy to unit-test with a fake client.
"""

import asyncio
from datetime import datetime
from typing import Protocol

from app.schemas import Direction, HistoryFrame, Message, MessageFrame


class Client(Protocol):
    async def send_text(self, data: str) -> None: ...


class MessageStore:
    """Ordered, in-memory, session-only message history."""

    def __init__(self) -> None:
        self._messages: list[Message] = []
        self._next_id = 1

    def add(self, *, text: str, direction: Direction, sender: str, timestamp: datetime) -> Message:
        """Append a message, assigning the next monotonic id. Returns the stored message."""
        message = Message(
            id=self._next_id,
            text=text,
            timestamp=timestamp,
            direction=direction,
            sender=sender,
        )
        self._next_id += 1
        self._messages.append(message)
        return message

    @property
    def messages(self) -> list[Message]:
        """A copy of the full history, in insertion (canonical) order."""
        return list(self._messages)

    def __len__(self) -> int:
        return len(self._messages)


class ConnectionManager:
    """Tracks connected clients and is the single record-and-broadcast chokepoint."""

    def __init__(self, store: MessageStore) -> None:
        self._store = store
        self._clients: set[Client] = set()
        self._lock = asyncio.Lock()

    async def connect(self, client: Client) -> None:
        self._clients.add(client)

    def disconnect(self, client: Client) -> None:
        self._clients.discard(client)

    @property
    def client_count(self) -> int:
        return len(self._clients)

    async def record_and_broadcast(
        self, *, text: str, direction: Direction, sender: str, timestamp: datetime
    ) -> Message:
        """Record a message and fan it out to all clients as one ordered, atomic step."""
        async with self._lock:
            message = self._store.add(
                text=text, direction=direction, sender=sender, timestamp=timestamp
            )
            await self._fan_out(MessageFrame(message=message).model_dump_json())
            return message

    async def send_history(self, client: Client) -> None:
        """Send the full session history to a single (usually freshly-connected) client."""
        await client.send_text(HistoryFrame(messages=self._store.messages).model_dump_json())

    async def _fan_out(self, payload: str) -> None:
        """Send a payload to every client, pruning any whose send fails (dead sockets)."""
        for client in list(self._clients):
            try:
                await client.send_text(payload)
            except Exception:
                # A dead/closed socket must not block delivery to the others.
                self._clients.discard(client)
