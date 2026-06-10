"""Shared test fixtures and helpers.

Telegram and the network are never touched here — these tests exercise the pure domain
logic (single-chat session, message store, fan-out) with an in-memory fake client.

Helpers (timestamp factory, fake clients) are exposed as fixtures so test modules can use
them via dependency injection without importing from this file.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.session import ChatSession
from app.store import ConnectionManager, MessageStore

_BASE_TIME = datetime(2026, 6, 10, 12, 0, 0, tzinfo=timezone.utc)


def _ts(seconds: int = 0) -> datetime:
    """A deterministic timestamp, offset by ``seconds`` from a fixed base."""
    return _BASE_TIME + timedelta(seconds=seconds)


class FakeClient:
    """A stand-in for a WebSocket client; records every payload it receives."""

    def __init__(self) -> None:
        self.received: list[str] = []

    async def send_text(self, data: str) -> None:
        self.received.append(data)


class DeadClient:
    """A client whose send always fails, to test dead-socket pruning."""

    async def send_text(self, data: str) -> None:
        raise ConnectionError("socket closed")


@pytest.fixture
def session() -> ChatSession:
    return ChatSession()


@pytest.fixture
def store() -> MessageStore:
    return MessageStore()


@pytest.fixture
def manager(store: MessageStore) -> ConnectionManager:
    return ConnectionManager(store)


@pytest.fixture
def ts():
    """The deterministic timestamp factory: ``ts(seconds)``."""
    return _ts


@pytest.fixture
def new_client():
    """A factory that creates a fresh recording client: ``new_client()``."""
    return FakeClient


@pytest.fixture
def dead_client() -> DeadClient:
    return DeadClient()
