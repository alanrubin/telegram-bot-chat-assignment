"""Single active chat enforcement.

The bot may interact with exactly one remote Telegram participant at a time. Telegram does
not enforce this (any user can message the bot), so it is a policy implemented here:

- The session starts unbound. The first chat to message the bot claims the only slot.
- Any other chat is rejected (the caller replies once and drops the message).
- If ``allowed_chat_id`` is configured, only that chat may ever claim the slot.

``claim()`` is a read-then-write ("if unbound, bind to me"), so it is guarded by an
``asyncio.Lock`` to keep the invariant race-free even if two updates arrive concurrently
(see D2 in DECISIONS.md).
"""

import asyncio
from enum import Enum


class ClaimResult(Enum):
    """Outcome of a claim attempt, decided atomically under the lock."""

    CLAIMED = "claimed"  # this chat just became the active participant (a new binding)
    ALREADY_ACTIVE = "already_active"  # this chat already held the slot
    REJECTED = "rejected"  # another chat holds the slot, or a different chat is pinned


class ChatSession:
    def __init__(self, allowed_chat_id: int | None = None) -> None:
        # Optional pin: when set, only this chat id may ever bind.
        self._allowed_chat_id = allowed_chat_id
        self._active_chat_id: int | None = None
        self._lock = asyncio.Lock()

    @property
    def active_chat_id(self) -> int | None:
        """The currently bound chat id, or None if no chat has claimed the slot yet."""
        return self._active_chat_id

    @property
    def has_active_chat(self) -> bool:
        return self._active_chat_id is not None

    async def claim(self, chat_id: int) -> ClaimResult:
        """Bind ``chat_id`` as the active participant if allowed.

        Returns CLAIMED if this call newly bound the chat, ALREADY_ACTIVE if it was already
        the active chat, or REJECTED if another chat holds the slot / a different chat is
        pinned. The new-binding signal is computed under the same lock that mutates the
        state, so callers never have to read ``has_active_chat`` separately (which would be a
        race).
        """
        async with self._lock:
            # A configured pin overrides everything: only the allowed chat may bind.
            if self._allowed_chat_id is not None and chat_id != self._allowed_chat_id:
                return ClaimResult.REJECTED
            if self._active_chat_id is None:
                self._active_chat_id = chat_id
                return ClaimResult.CLAIMED
            return (
                ClaimResult.ALREADY_ACTIVE
                if self._active_chat_id == chat_id
                else ClaimResult.REJECTED
            )

    def is_active(self, chat_id: int) -> bool:
        """True if ``chat_id`` is the currently bound chat."""
        return self._active_chat_id == chat_id

    async def reset(self) -> None:
        """Clear the bound chat so a new participant can claim the slot."""
        async with self._lock:
            self._active_chat_id = None
