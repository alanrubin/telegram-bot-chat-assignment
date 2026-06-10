# Senior Full-Stack Developer – Home Assignment

> **📐 Project documentation for reviewers**
> - **[ARCHITECTURE.md](ARCHITECTURE.md)** — how the system is built: components, the
>   message data-flow, the single-chat rule, the WebSocket contract, and the module layout.
> - **[DECISIONS.md](DECISIONS.md)** — the key engineering decisions and trade-offs (transport,
>   Telegram integration, single-chat enforcement, error handling, resilience, and more), with
>   the alternatives considered and why each choice was made.
>
> Start with `ARCHITECTURE.md` for the big picture, then `DECISIONS.md` for the reasoning.

## Overview

This assignment simulates a simplified real-world system that displays a web-based interface of a chat between a Telegram bot and a remote participant.

The system should consist:
- A **React.js frontend** that displays a chat UI
- A **FastAPI (Python) backend** that manages a Telegram bot
- A single Telegram chat connection that acts as the remote participant

The focus of this assignment is on **architecture, clarity, and engineering judgment**, not visual polish or feature overload.

---

## Functional Requirements

### 1. Chat UI

The frontend must display a chat interface between the bot and the remote Telegram participant.
It should include:

- A list of messages (incoming and outgoing)
- A text input for sending messages
- A send button (or Enter key support)

Each message must include:
- Message text
- Timestamp (time the message was sent)

The chat may not be consistent and may only present messages from the current session.

Incoming and outgoing messages should be visually distinguishable.

---

### 2. Telegram Bot Integration (Backend)

- The backend must manage a **Telegram bot instance**
- The bot must accept **only one active Telegram chat connection** (Should only accept interacting with one remote participant)
- Messages flow as follows:
  - Messages sent from the frontend are forwarded to the connected Telegram chat
  - Messages received by the Telegram bot are forwarded to the frontend as incoming messages

State management, concurrency handling, and message ordering should be handled safely.

---

### 3. Backend Configuration State

- The Telegram bot token should be configured manually in the backend.

---

## Communication Between Frontend and Backend

- The communication mechanism is up to you (e.g. WebSockets, long polling, Server-Sent Events, etc.)
- The chosen approach should be justified by simplicity and correctness
- Real-time or near-real-time behavior is expected

This implementation uses **WebSockets**; see [DECISIONS.md](DECISIONS.md) (D1) for the justification.

---

## Technical Requirements

- **Frontend:** React.js (implemented with TypeScript)
- **Backend:** FastAPI (Python)
- Code should be clean, readable, and maintainable
- Assumptions and trade-offs should be documented — see [DECISIONS.md](DECISIONS.md)

---

## Prerequisites

- **Python** 3.10+ (developed and Dockerised on 3.12)
- **Node.js** 18+ (Docker uses 20)
- A **Telegram account** and a **bot token** from BotFather (steps below)

---

## 1. Create a Telegram bot

1. In Telegram, open a chat with [@BotFather](https://t.me/BotFather).
2. Send `/newbot` and follow the prompts (choose a name and a unique `@username`).
3. BotFather replies with an **HTTP API token** like `7123456789:AAH8f...kQ2zR`. Copy it.

> A Telegram bot can only message users who have messaged it first. To start a session, open
> your new bot in Telegram and press **Start** (this sends `/start`).

---

## 2. Configure the backend

The token is read from `backend/.env` (never commit it — it is git-ignored).

```bash
cd backend
cp .env.example .env
# then edit .env and set TELEGRAM_BOT_TOKEN=<your token>
```

Optional settings (sensible defaults apply if unset): `TELEGRAM_ALLOWED_CHAT_ID` (pin a
specific chat as the only allowed participant), `CORS_ORIGINS`, `LOG_LEVEL`. See
`backend/.env.example`.

---

## 3. Run

### Option A — Docker (recommended, one command)

Requires Docker Desktop. With `backend/.env` in place:

```bash
docker compose up --build
```

Open **http://localhost:8080**. nginx serves the UI and reverse-proxies the WebSocket to the
backend, so the whole app is on a single origin.

### Option B — Without Docker (two terminals)

**Backend:**

```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload          # http://localhost:8000
```

(The backend fails fast on startup if `TELEGRAM_BOT_TOKEN` is missing or invalid.)

**Frontend:**

```bash
cd frontend
npm install
npm run dev                            # http://localhost:5173
```

The Vite dev server proxies `/ws` to the backend on port 8000, so the client code is identical
in dev and production.

---

## 4. Using it

1. Open the web UI — the status dot shows **“Waiting for a Telegram participant…”**.
2. From your Telegram account, open the bot and send a message (or `/start`). That chat
   **claims the single session slot**: the status turns green and the message appears in the UI
   as an incoming (left) bubble.
3. Type in the UI and press Enter / Send — it is delivered to your Telegram chat and shown as
   an outgoing (right) bubble.
4. Any **other** Telegram chat that messages the bot receives a polite rejection and is ignored
   (only one active connection). Restart the backend to release the slot.

---

## 5. Running the tests

**Backend** — single-chat rule, message routing/ordering, and the WebSocket bridge. Telegram
is mocked, so **no token or network is needed**:

```bash
cd backend
source venv/bin/activate               # if not already active
pytest                                 # 22 tests
```

**Frontend** — the `useChatSocket` hook (with a mocked WebSocket) and `App` rendering/gating,
via Vitest + React Testing Library:

```bash
cd frontend
npm test                               # 12 tests
```

**End-to-end** — a Playwright smoke that drives the UI with the WebSocket mocked in-browser
(no backend or Telegram needed). Install the browser once, then run:

```bash
cd frontend
npx playwright install chromium
npm run test:e2e
```

See [DECISIONS.md](DECISIONS.md) (D11) for the testing strategy and what is intentionally out
of scope.

---

## 6. End-to-end verification checklist

- `pytest` → all green.
- Send from Telegram → appears as an incoming (left) bubble with a timestamp.
- Send from the UI → arrives in Telegram and appears as an outgoing (right) bubble.
- Open a **second browser tab** → it loads history and receives new messages live.
- Message the bot from a **second Telegram account** → rejected, not shown in the UI.

---

## Project structure

```
backend/            FastAPI app + Telegram bot (app/), tests/, Dockerfile
frontend/           React + TypeScript (Vite), nginx.conf + Dockerfile
docker-compose.yml  backend + frontend (nginx) on one origin
ARCHITECTURE.md     system overview + data flow + module layout
DECISIONS.md        decisions, alternatives, and trade-offs
```
