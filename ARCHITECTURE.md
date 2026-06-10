# Architecture

A web-based chat that bridges a single remote Telegram participant and a browser UI, with a
FastAPI backend owning the Telegram bot. This document describes the system shape; the
reasoning behind each choice lives in [`DECISIONS.md`](DECISIONS.md).

## Components

| Component | Tech | Responsibility |
|-----------|------|----------------|
| Frontend | React 18 + Vite | Chat UI: render incoming/outgoing messages, send input, show connection status. |
| Backend | FastAPI (Python) | Owns the Telegram bot, enforces the single-chat rule, bridges messages to/from browsers over WebSocket. |
| Telegram bot | python-telegram-bot (long-polling) | Receives messages from the participant and delivers outgoing messages. |

## Data flow

```
   Human on Telegram          FastAPI backend ("the bot")              React UI (browser)
   (phone / desktop)          python-telegram-bot + WebSocket

   types "hi" ───────► Telegram ──(long-poll getUpdates)──► update arrives
                                                            │ check chat.id vs bound chat
                                                            │   (ChatSession + asyncio.Lock)
                                                            ▼ accepted
                                                     store + broadcast ──(WS push)──► INCOMING bubble
                                                            ▲
   sees reply ◄─────── Telegram ◄── bot.send_message(chat_id, text) ◄── FastAPI ◄─(WS)─ Send click
                                                                                        OUTGOING bubble
```

Every message — incoming and outgoing — passes through a single `broadcast()` call on one
asyncio event loop and is appended to one in-memory list. That single chokepoint is the
**ordering guarantee** (insertion order = canonical order; each message gets a monotonic id),
and the `asyncio.Lock` on the chat claim is the **concurrency guarantee**. No database, queue,
or broker is involved — state is in-memory and session-only.

## Single active chat

The bot starts unbound. The first Telegram chat to message it claims the only slot; all other
chats receive one polite rejection and are dropped. Setting `TELEGRAM_ALLOWED_CHAT_ID` pins a
specific chat instead. State resets on backend restart. See D2 in the decisions doc.

## Transport & message contract

Communication is a single WebSocket (`/ws`). Messages are JSON frames with a `type`
discriminator:

```
Message  { id:int, text:str, timestamp:ISO-8601, direction:"incoming"|"outgoing", sender:str }

Client → server:  { "type":"send",    "text":"..." }
Server → client:  { "type":"history", "messages":[...] }       # full session, sent on connect
                  { "type":"message", "message":{...} }        # a single new message
                  { "type":"status",  "connected":bool, "activeChat":bool }
                  { "type":"error",   "detail":"..." }
```

The frontend is server-authoritative: a sent message is rendered only after the backend
confirms delivery to Telegram and broadcasts it back, so all browser tabs stay consistent.

## Resilience

The backend keeps polling Telegram regardless of the browser. A client that goes offline
reconnects with capped backoff and receives a full `history` replay, so it loses no messages
while the backend is up. Sending is disabled (with the draft preserved) while disconnected.
If the backend itself restarts, in-memory history is lost — acceptable per the assignment.

## Security note

The bot uses Telegram **long-polling**, so the backend only makes *outbound* connections to
Telegram and exposes **no inbound public URL**. This suits a security-sensitive deployment:
there is no internet-reachable, discoverable endpoint to track or attack, and the backend can
run within a closed/internal network. Note that messages still transit Telegram's third-party
servers, so Telegram remains a trust dependency regardless of transport (see D3 in
[`DECISIONS.md`](DECISIONS.md)).

## Module layout

```
backend/
  app/
    main.py             # FastAPI app, lifespan (start/stop the bot), router mount, CORS
    config.py           # pydantic-settings: TELEGRAM_BOT_TOKEN (required), allowed chat id, CORS
    schemas.py          # pydantic models: Message + WebSocket frame envelopes
    telegram_service.py # python-telegram-bot Application lifecycle, incoming handler, send()
    session.py          # ChatSession: active chat id + asyncio.Lock + claim/reset
    store.py            # MessageStore + ConnectionManager: in-memory list + WS set + broadcast()
    routes.py           # /ws WebSocket endpoint, /health, optional /session/reset
  tests/                # pytest: single-chat logic, message routing, WebSocket (Telegram mocked)

frontend/
  src/
    App.jsx             # chat UI
    hooks/useChatSocket.js  # WebSocket lifecycle: connect, parse frames, reconnect, send
    index.css           # styling (incoming/outgoing bubbles, status, input)

docker-compose.yml      # backend + frontend (nginx) on one origin
```

## Running

See the project [`README.md`](README.md) for setup, the BotFather token steps, local run, and
`docker-compose up` instructions.
