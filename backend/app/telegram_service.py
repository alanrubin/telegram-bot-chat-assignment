"""Telegram bot integration (python-telegram-bot, long-polling).

This service owns the bot lifecycle and bridges Telegram to the in-memory store:

- **Incoming** (Telegram -> app): a text message or ``/start`` from the bound participant is
  recorded and broadcast to web clients; messages from any other chat are rejected with a
  single polite reply and dropped (single-active-chat rule, see D2).
- **Outgoing** (app -> Telegram): ``send_to_active`` delivers a web-typed message to the bound
  chat. Only after Telegram accepts it is the message recorded and broadcast, so the UI never
  shows a message that failed to send (server-authoritative, see D5).

Updates are received via long-polling, which needs only outbound connectivity and exposes no
public URL (see D3). The bot runs on the same asyncio loop as FastAPI, started/stopped from the
app lifespan.

The message-handling logic (``handle_incoming``, ``send_to_active``) is separated from the
python-telegram-bot adapters so it can be unit-tested with a mocked bot.
"""

import logging
from datetime import datetime, timezone

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from app.schemas import Message
from app.session import ChatSession, ClaimResult
from app.store import ConnectionManager

logger = logging.getLogger("app.telegram")

WELCOME_TEXT = "You are now connected. Messages you send here will appear in the web chat."
REJECTION_TEXT = "This bot is currently in a session with another user. Please try again later."


class NoActiveChatError(RuntimeError):
    """Raised when an outgoing message is attempted before any chat has claimed the slot."""


class TelegramService:
    def __init__(self, token: str, session: ChatSession, manager: ConnectionManager) -> None:
        self._token = token
        self._session = session
        self._manager = manager
        self._app: Application | None = None
        # The bot used to send/reply. Set on start(); injectable in tests.
        self._bot = None

    # --- Lifecycle -------------------------------------------------------------------

    async def start(self) -> None:
        """Build the PTB application, validate the token, and begin long-polling."""
        self._app = Application.builder().token(self._token).build()
        self._app.add_handler(CommandHandler("start", self._on_start))
        self._app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_message))
        self._app.add_error_handler(self._on_error)

        await self._app.initialize()
        self._bot = self._app.bot
        me = await self._bot.get_me()  # validates the token -> fail fast on a bad token
        logger.info("Telegram bot @%s connected; starting long-polling", me.username)

        await self._app.start()
        await self._app.updater.start_polling()

    async def stop(self) -> None:
        """Stop polling and shut the bot down cleanly."""
        if self._app is None:
            return
        if self._app.updater is not None:
            await self._app.updater.stop()
        await self._app.stop()
        await self._app.shutdown()
        logger.info("Telegram bot stopped")

    # --- Core logic (mockable) -------------------------------------------------------

    async def handle_incoming(
        self, chat_id: int, text: str, sender: str, timestamp: datetime
    ) -> Message | None:
        """Apply the single-chat rule and, if accepted, record + broadcast the message."""
        if not await self._claim_or_reject(chat_id):
            return None
        return await self._manager.record_and_broadcast(
            text=text, direction="incoming", sender=sender, timestamp=timestamp
        )

    async def send_to_active(self, text: str) -> Message:
        """Send a web-typed message to the bound chat, then record + broadcast it.

        Raises NoActiveChatError if no chat is bound. Any error from Telegram propagates and
        the message is NOT recorded (server-authoritative).
        """
        chat_id = self._session.active_chat_id
        if chat_id is None:
            raise NoActiveChatError("No active Telegram chat to send to yet.")
        await self._bot.send_message(chat_id=chat_id, text=text)
        return await self._manager.record_and_broadcast(
            text=text,
            direction="outgoing",
            sender="You",
            timestamp=datetime.now(timezone.utc),
        )

    async def _claim_or_reject(self, chat_id: int) -> bool:
        """Bind the chat if allowed; otherwise reply once with a rejection and drop it."""
        result = await self._session.claim(chat_id)
        if result is ClaimResult.REJECTED:
            logger.warning("Rejected message from non-active chat %s", chat_id)
            await self._reply(chat_id, REJECTION_TEXT)
            return False
        if result is ClaimResult.CLAIMED:
            # The claim newly bound this chat (decided under the lock, no TOCTOU): tell
            # connected web clients so they can enable sending.
            logger.info("Chat %s claimed the active session slot", chat_id)
            await self._manager.broadcast_status(connected=True, active_chat=True)
        return True

    async def _reply(self, chat_id: int, text: str) -> None:
        try:
            await self._bot.send_message(chat_id=chat_id, text=text)
        except Exception:
            logger.exception("Failed to send reply to chat %s", chat_id)

    # --- python-telegram-bot adapters ------------------------------------------------

    async def _on_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat = update.effective_chat
        if chat is None:
            return
        if await self._claim_or_reject(chat.id):
            await self._reply(chat.id, WELCOME_TEXT)

    async def _on_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        chat = update.effective_chat
        if message is None or chat is None or not message.text:
            return
        sender = update.effective_user.first_name if update.effective_user else "Telegram"
        # Use Telegram's own send time (message.date), not our receive time.
        await self.handle_incoming(chat.id, message.text, sender, message.date)

    async def _on_error(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        # A failure on one update is logged and swallowed so the poll loop keeps running.
        logger.error("Error while handling update %s", update, exc_info=context.error)
