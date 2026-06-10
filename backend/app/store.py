"""In-memory message history and WebSocket fan-out.

``MessageStore`` keeps the current-session messages and assigns each a monotonically
increasing ``id``. ``ConnectionManager`` tracks the connected web clients and is the single
point through which every message is recorded and broadcast.

That single chokepoint — guarded by an ``asyncio.Lock`` — is what guarantees ordering:
messages are appended to one list and fanned out to clients in one atomic step, so insertion
order is the canonical order and per-client delivery order matches it (see DECISIONS.md). A
newly-connecting client is registered *and* sent its initial status + history under the same
lock (``connect_and_sync``), so it can never receive a live message before, after a gap in,
or concurrently with its history snapshot. State is in-memory and session-only.

Clients are duck-typed: any object with an async ``send_text(str)`` method works, which keeps
this module decoupled from FastAPI's ``WebSocket`` and easy to unit-test with a fake client.
"""

import asyncio
import logging
from datetime import datetime
from typing import Protocol

from app.schemas import Direction, HistoryFrame, Message, MessageFrame, StatusFrame

logger = logging.getLogger("app.store")

# A single client's send is bounded so a stalled/backpressured socket cannot hold up the
# broadcast indefinitely; on timeout the client is treated as dead and pruned. (A fully
# non-blocking broadcaster would give each connection its own outbound queue + writer task;
# that is heavier than this session-scale app warrants — see DECISIONS.md.)
SEND_TIMEOUT_SECONDS = 5.0


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

    def clear(self) -> None:
        """Drop all messages. The id counter stays monotonic so ids are never reused."""
        self._messages.clear()

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
        """Register a client to receive broadcasts (without sending initial state)."""
        self._clients.add(client)

    async def connect_and_sync(self, client: Client, *, active_chat: bool) -> None:
        """Register a client and send it the current status + full history, atomically.

        Done under the broadcast lock so it is serialized against record_and_broadcast: the
        client is added and its snapshot is sent with no broadcast interleaving, so it never
        sees a message before its history, never misses one appended during connect, and is
        never written to by two coroutines at once.
        """
        async with self._lock:
            self._clients.add(client)
            await self._send_to(
                client,
                StatusFrame(connected=True, activeChat=active_chat).model_dump_json(),
            )
            await self._send_to(
                client, HistoryFrame(messages=self._store.messages).model_dump_json()
            )

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

    async def broadcast_status(self, *, connected: bool, active_chat: bool) -> None:
        """Tell all clients whether a Telegram participant is bound (enables/disables sending)."""
        async with self._lock:
            await self._fan_out(
                StatusFrame(connected=connected, activeChat=active_chat).model_dump_json()
            )

    async def reset_history(self) -> None:
        """Clear the session history and push the now-empty history to all clients."""
        async with self._lock:
            self._store.clear()
            await self._fan_out(HistoryFrame(messages=self._store.messages).model_dump_json())

    async def send_history(self, client: Client) -> None:
        """Send the full session history to a single client (helper; connect uses connect_and_sync)."""
        await self._send_to(client, HistoryFrame(messages=self._store.messages).model_dump_json())

    async def _fan_out(self, payload: str) -> None:
        """Send a payload to every client, pruning any whose send fails or stalls."""
        for client in list(self._clients):
            await self._send_to(client, payload)

    async def _send_to(self, client: Client, payload: str) -> None:
        """Send to one client with a timeout; on failure log and prune it (a dead/stalled
        socket must not silently disappear nor block the others)."""
        try:
            async with asyncio.timeout(SEND_TIMEOUT_SECONDS):
                await client.send_text(payload)
        except Exception as exc:
            logger.warning("Dropping unreachable web client: %r", exc)
            self._clients.discard(client)
