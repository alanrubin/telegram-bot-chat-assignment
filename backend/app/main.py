"""FastAPI application entrypoint.

Wires the in-memory store, the single-chat session, and the Telegram service together, and
manages the bot's lifecycle via the app lifespan: the bot starts long-polling on startup and
shuts down cleanly on exit. Shared singletons live on ``app.state`` so routes can reach them.

Reading settings here means a missing/invalid token fails fast at startup (see D6/D8).
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.session import ChatSession
from app.store import ConnectionManager, MessageStore
from app.telegram_service import TelegramService

settings = get_settings()
logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    store = MessageStore()
    manager = ConnectionManager(store)
    session = ChatSession(allowed_chat_id=settings.telegram_allowed_chat_id)
    telegram = TelegramService(settings.telegram_bot_token, session, manager)

    # Expose singletons to routes (added in the next phase).
    app.state.store = store
    app.state.manager = manager
    app.state.session = session
    app.state.telegram = telegram

    await telegram.start()
    logger.info("Application startup complete")
    try:
        yield
    finally:
        await telegram.stop()
        logger.info("Application shutdown complete")


app = FastAPI(title="Telegram Chat Backend", lifespan=lifespan)

# Tightened from the scaffold's wide-open "*" to the configured origins.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok"}
