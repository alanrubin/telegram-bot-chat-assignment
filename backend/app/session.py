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

    async def claim(self, chat_id: int) -> bool:
        """Bind ``chat_id`` as the active participant if allowed.

        Returns True if ``chat_id`` is (now) the active chat, False if it is rejected
        because another chat already holds the slot or a different chat is pinned.
        """
        async with self._lock:
            # A configured pin overrides everything: only the allowed chat may bind.
            if self._allowed_chat_id is not None and chat_id != self._allowed_chat_id:
                return False
            if self._active_chat_id is None:
                self._active_chat_id = chat_id
                return True
            return self._active_chat_id == chat_id

    def is_active(self, chat_id: int) -> bool:
        """True if ``chat_id`` is the currently bound chat."""
        return self._active_chat_id == chat_id

    async def reset(self) -> None:
        """Clear the bound chat so a new participant can claim the slot."""
        async with self._lock:
            self._active_chat_id = None
