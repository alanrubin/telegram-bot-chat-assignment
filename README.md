# Senior Full-Stack Developer – Home Assignment

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

- The Telegram bot token should be configured manualy in the backend.

---

## Communication Between Frontend and Backend

- The communication mechanism is up to you  
  (e.g. WebSockets, long polling, Server-Sent Events, etc.)
- The chosen approach should be justified by simplicity and correctness
- Real-time or near-real-time behavior is expected

---

## Technical Requirements

- **Frontend:** React.js
- **Backend:** FastAPI (Python)
- Code should be clean, readable, and maintainable
- Assumptions and trade-offs should be documented

---

## Prerequisites

- Node.js (18+ recommended)
- Python 3.10+
- Telegram account
- Telegram Bot Token (created via BotFather)

---

## Setup Instructions

### Backend

Bash
```bash
cd backend
python -m venv venv
source venv/bin/activate
uvicorn app.main:app --reload
```

### Frontend

Bash
```bash
cd frontend
npm install
npm run dev
```

### Docker Setup (Optional but Recommended)

For a streamlined setup, you can run the entire system using Docker Compose. This ensures all dependencies and environment configurations are handled automatically.

1. **Build and start the containers:**
   ```bash
   docker-compose up --build
