# Design Decisions & Trade-offs

This document records the significant engineering decisions I made while building this
system, the alternatives I weighed, and why I selected the approach I did. The assignment
is explicitly judged on *architecture, clarity, and engineering judgment*, so I have tried
to make my reasoning — and the trade-offs I accepted — visible rather than implicit.

Each decision lists the options I considered with their advantages and disadvantages,
followed by the choice I made and the reasoning grounded in the assignment's requirements.

---

## D1 — Frontend ↔ Backend transport: **WebSocket**

The assignment leaves the transport to me but asks that it be justified by *simplicity and
correctness*, with near-real-time behavior.

**Options I considered**

- **WebSocket** — a single full-duplex channel.
  - ✅ The conversation is inherently bidirectional (the UI sends messages *and* the
    backend pushes incoming Telegram messages); one channel maps 1:1 onto that.
  - ✅ Lowest latency; first-class support in FastAPI/Starlette.
  - ➖ I need a small client-side reconnect routine (no built-in auto-reconnect).
- **SSE + POST** — Server-Sent Events for server→client, a separate POST for client→server.
  - ✅ SSE has native auto-reconnect and a `Last-Event-ID` resume mechanism.
  - ➖ Two transports for one logical channel — more moving parts to wire and explain.
- **Long polling** — the client repeatedly polls for new messages.
  - ✅ Trivially supported everywhere; resilient to drops.
  - ➖ Higher latency and more awkward to implement correctly; no real upside here.

**My choice: WebSocket.** For a live, bidirectional chat it is the most direct model — one
full-duplex channel that mirrors the chat semantics with the least code. The only thing I
give up is built-in reconnection, which I handle with a small backoff routine on the client
(see D7). I judged that a single, well-understood channel is both simpler *and* more correct
for this use case than running two coordinated transports.

---

## D2 — "Single active chat" enforcement: **first-claims with optional configured override**

The bot must accept only one active Telegram chat. Telegram itself does not enforce this —
any user who finds the bot can message it — so this is a policy my backend must implement.

**Options I considered**

- **Configured `chat_id` only** — pin the allowed chat via an environment variable.
  - ✅ Fully deterministic; no shared mutable state; impossible to race.
  - ➖ I must know the chat id in advance and edit config + restart to test; a reviewer has
    extra setup before anything works.
- **First-claims only** — the first chat to message the bot dynamically claims the slot.
  - ✅ Zero pre-configuration; trivial to demo.
  - ➖ No deterministic path for a scripted demo where I want a specific account bound.
- **Hybrid (first-claims + optional override)** — first-claims by default, but an optional
  `TELEGRAM_ALLOWED_CHAT_ID` pins it when set.
  - ✅ Best of both: zero-config to try, deterministic when I want control.
  - ➖ A little more logic than either pure option.

**My choice: the hybrid.** It models the requirement directly: the bot starts unbound, the
first chat to message it claims the single slot, and every other chat receives one polite
rejection and is dropped (never reaching the UI). When `TELEGRAM_ALLOWED_CHAT_ID` is set,
only that chat may bind, which gives me a deterministic demo. The claim is a read-then-write
("if unbound, bind to me"), so I guard it with an `asyncio.Lock` to make the invariant
race-free regardless of update scheduling — this is exactly the "concurrency handled safely"
the assignment calls for. Reset is by backend restart (state is session-only); an optional
`POST /session/reset` is a natural extension I noted but did not consider required.

---

## D3 — Telegram library & update mechanism: **python-telegram-bot, long-polling**

**Library options**

- **python-telegram-bot (PTB)** — mature, async-native, batteries-included.
  - ✅ Manages the `getUpdates` offset cursor, retries, de-duplication, and typed parsing;
    its handler model maps cleanly to "when a message arrives, do X"; widely recognized.
  - ➖ I adopt its `Application` lifecycle and start/stop it in sync with FastAPI.
- **aiogram** — also excellent and async-native, more opinionated (routers + FSM).
  - ✅ Great ergonomics for complex multi-step conversational flows.
  - ➖ The router/FSM machinery is unused for a single plain-text chat — ceremony for no gain.
- **Raw `httpx`** — hand-rolled `getUpdates` loop.
  - ✅ Proves end-to-end understanding of the protocol; zero extra dependencies.
  - ➖ ~100 lines of error-prone offset/retry/timeout/parse plumbing that reinvents a
    well-tested wheel — the kind of thing that looks clever but costs correctness.

**My choice: python-telegram-bot.** It lets the code I write be about *my* design (the
single-chat rule, the bridge, ordering) instead of protocol bookkeeping. I run its
`Application` as a task managed by FastAPI's `lifespan` — same event loop, no extra threads
or processes.

**Update mechanism: long-polling (`getUpdates`), not webhooks.**

- **Long-polling** — ✅ needs only *outbound* connectivity, so it works identically on a
  laptop and inside Docker with no public URL; PTB tracks the offset so no update is missed
  or duplicated; latency is sub-second. Crucially for a **security-sensitive deployment**, it
  exposes **no inbound endpoint** — the backend can run inside a closed/internal network with
  no internet-reachable, discoverable URL to track or attack. ➖ the process must stay running
  to poll.
- **Webhook** — ✅ the production-grade choice for high scale, slightly more efficient.
  ➖ requires a public HTTPS endpoint (a tunnel like ngrok locally), which breaks the
  one-command `docker-compose up` experience **and** creates an inbound, internet-facing
  attack surface that must be hardened and is externally discoverable.

I chose long-polling. Beyond being fully self-contained for a reviewer, it is the better fit
for a security-sensitive environment: the bot reaches *out* to Telegram rather than exposing
an inbound public URL, so the backend has no externally reachable endpoint and can live
entirely within an internal network. For these reasons I would keep long-polling even in a
production deployment of this kind; a webhook would only be worth revisiting in a non-sensitive,
high-throughput context.

**Honest caveat:** long-polling removes the *inbound* exposure, but it does not make the
system end-to-end private — messages still transit Telegram's third-party servers, which see
their content. Telegram is therefore a trust dependency regardless of the update mechanism;
that is a platform-level consideration, separate from the transport choice made here.

---

## D4 — Frontend Docker packaging: **multi-stage build → nginx**

**Options I considered**

- **Multi-stage build → nginx** — `node` builds static assets, `nginx:alpine` serves them.
  - ✅ Small final image (the node toolchain is discarded); nginx reverse-proxies `/ws` and
    `/api` to the backend, so the browser talks to a *single origin* and CORS/WS-origin
    issues disappear; the reviewer hits one port; production-shaped.
  - ➖ A slightly longer Dockerfile plus a small `nginx.conf`.
- **Vite dev server in the container** — ship `npm run dev`.
  - ✅ Simpler Dockerfile, hot-reload.
  - ➖ It is the development server in a nominally deployable artifact, and it needs separate
    CORS handling; less polished.

**My choice: multi-stage → nginx.** The single-origin reverse proxy alone removes an entire
class of CORS and WebSocket-origin friction, and the result resembles how I would actually
ship a frontend. The extra Dockerfile complexity is small and worth it.

**Security note (origin validation).** Single-origin serving fixes the *legitimate* client,
but it does not by itself stop a *malicious* cross-origin page: WebSockets are exempt from the
browser same-origin policy and the CORS middleware only guards HTTP, so a hostile page could
otherwise open `/ws` and read history or send messages (cross-site WebSocket hijacking). The
`/ws` handshake therefore explicitly validates the `Origin` header against `CORS_ORIGINS` and
refuses a present-but-disallowed origin (a missing origin is a non-browser client, not a CSWSH
vector). The companion `POST /session/reset` is gated behind the `SESSION_RESET_TOKEN` shared
secret, and inbound message frames are length-capped (4096 chars, Telegram's own limit) to
bound per-message memory.

---

## D5 — Echo model: **server-authoritative**

When the user sends a message from the UI, when and how does it appear in the message list?

**Options I considered**

- **Server-authoritative** — the UI sends to the backend; the backend sends to Telegram and
  then broadcasts the message back to *all* connected clients, which render it.
  - ✅ One source of truth → no duplicates, no ordering drift across tabs; only messages that
    genuinely went out are ever displayed.
  - ➖ A few tens of milliseconds of latency before the sender sees their own message.
- **Optimistic** — the UI renders the message immediately on click, before confirmation.
  - ✅ Feels instant.
  - ➖ Risks showing a message that failed to send, and duplication/ordering drift when
    multiple tabs reconcile the later broadcast.

**My choice: server-authoritative.** In a chat the few-millisecond delay is imperceptible,
and in exchange I get a clean single source of truth that makes the ordering guarantee
trivial (see below) and eliminates the dup/ordering bugs optimistic rendering invites.

---

## D6 — Configuration loading: **pydantic-settings**

The bot token is configured manually in the backend.

**Options I considered**

- **pydantic-settings (`BaseSettings`)** — reads env + `.env`, typed and validated.
  - ✅ Fails fast at startup with a clear error if the token is missing; self-documents the
    whole config surface in one file; idiomatic FastAPI.
  - ➖ One extra dependency.
- **`os.environ`** — read variables directly.
  - ✅ Zero dependencies.
  - ➖ No validation; a missing token fails late and vaguely; no single config surface.

**My choice: pydantic-settings.** Failing fast and loudly on a missing/invalid token is
exactly what I want for a manually-configured secret, and it is barely more code. The token
lives only in `backend/.env` (git-ignored); a committed `.env.example` documents the shape.

---

## D7 — Client offline / reconnect resilience: **full history replay + disable-and-preserve-draft**

The README states the chat need only show the current session and may be inconsistent, which
sets a deliberately modest bar for resilience. My guiding principle is that **the backend is
the source of truth and keeps the conversation alive regardless of the browser** — the bot
keeps polling Telegram even with no client connected, and the browser is a view that resyncs.

**Receiving while the browser is offline.** Messages that arrive during an outage still reach
the backend and are stored. I considered two catch-up mechanisms:

- **Full history replay on (re)connect** — the server sends the entire session list.
  - ✅ Simple, stateless on the client, always correct at session scale.
  - ➖ Resends all messages (trivial here).
- **Incremental catch-up via last-seen id** — the client sends its highest id; the server
  replays only newer messages.
  - ✅ More efficient, avoids re-rendering the whole list.
  - ➖ More state and code on both ends.

I chose **full history replay** — at session scale the cost is negligible and the simplicity
and correctness are worth more than the efficiency. Incremental resume is a clean future
enhancement.

**Sending while offline.** I considered:

- **Disable + preserve draft** — Send/input disabled while disconnected, the typed text kept.
  - ✅ Predictable; no stale or duplicate sends; honest about connectivity.
  - ➖ The user cannot "send" until reconnected.
- **Queue + flush on reconnect** — let the user send offline; flush when reconnected.
  - ✅ More forgiving UX.
  - ➖ Risks stale/duplicate sends, ordering ambiguity, and reconciliation against the
    server-authoritative broadcast.

I chose **disable + preserve draft.** Under a server-authoritative model, silently sending a
message minutes later is surprising and error-prone; disabling Send with a clear status
indicator and keeping the draft is the more honest and predictable behavior.

**Accepted limitation (permitted by the README):** if the *backend* restarts during an
outage, the in-memory history is lost and a reconnecting client sees an empty/partial
session. Persistence (a database) would remove this, but the README explicitly allows
session-only, possibly-inconsistent state, so I kept persistence out of scope.

**WebSocket lifecycle hardening.** The reconnect logic has to be robust to a socket being
torn down and recreated — both from genuine network drops and from React 18 StrictMode, which
double-invokes effects (mount → cleanup → mount) in development. A naive "intentional close"
flag is unsafe here, because a socket's `close` event fires asynchronously: the first socket's
`onclose` can run *after* the remount, and a shared flag would have been reset by then,
spawning a second live connection that duplicates every message. I guard against this on two
levels:

- **A stale socket can never reconnect.** On cleanup the socket's handlers are detached before
  it is closed, and `onclose` ignores any socket that is no longer the current one
  (`socketRef.current !== socket`). So only one live connection exists at a time.
- **Rendering is idempotent by message id.** Appending a `message` is a no-op if a message
  with that id is already present, so even a double-delivery cannot render twice.

(In development this churn also surfaced a harmless `EPIPE` warning from the Vite dev proxy —
writing to a backend socket that had just closed; the single-socket invariant quiets it.
Production serves the build through nginx, not the Vite proxy.)

---

## D8 — Error-handling philosophy: **fail fast on config, isolate per-event, surface to the UI**

I treated error handling as a design concern built in from the start, not bolted on.

**Options I weighed (in spirit)**

- **Swallow / log-only** — ✅ simplest; ➖ users get no feedback when a send fails and
  inconsistencies are silent.
- **Let exceptions propagate** — ➖ one bad update or a dead socket could crash the poll loop
  or block the broadcast fan-out.
- **Fail fast on config, isolate per-event, surface to the UI** — the approach I chose.

**What this means concretely**

- Missing/invalid token fails fast at boot (pydantic-settings + a one-time `getMe` validation
  call), so the app never runs as a silently-dead bot.
- A PTB error handler logs an exception from any single update and lets the poll loop
  continue — one malformed update cannot take the bot down.
- A failed `bot.send_message` is *not* broadcast; instead an `error` frame goes back to the
  originating client and the failure is logged — preserving the server-authoritative
  invariant that only genuinely-sent messages appear.
- The WebSocket layer catches disconnects and deregisters cleanly, prunes dead sockets so one
  dead client cannot block the fan-out, and validates every inbound frame, replying with an
  `error` frame on malformed/unknown input rather than dropping the connection.
- Logging uses Python's `logging` (INFO for lifecycle, WARNING for rejected chats/sends,
  ERROR for exceptions with context) rather than `print`.

I chose this so that failures are **visible and contained**: misconfiguration is caught
immediately, transient/per-event errors never escalate into a crash, and the user is told
when something they did (a send) did not succeed.

---

## D9 — Code comments: **moderate, "explain the why"**

**Options I considered**

- **Minimal / self-documenting** — rely on names + this document.
  - ✅ Leanest. ➖ Less guidance on Telegram-specific subtleties for a future reader.
- **Moderate / explain the why** — docstrings on modules and public functions/classes, plus
  targeted inline comments only where intent is non-obvious.
  - ✅ Clean and readable while explaining the genuinely tricky parts.
  - ➖ A little more text to maintain.
- **Heavy / teaching-oriented** — verbose explanatory comments throughout.
  - ✅ Maximal explanation. ➖ Clutter; can read as junior.

**My choice: moderate.** I comment the *why*, not the *what*: docstrings stating each
module's and public function's purpose and contract, and inline notes only where intent is
not obvious from the code — the Telegram mechanics (long-poll offset, `chat_id`,
`message.date`), the `asyncio.Lock` claim race, and the single `broadcast()` ordering
chokepoint. Clear names and this document carry the rest.

---

## D10 — Frontend language: **TypeScript**

**Options I considered**

- **TypeScript** — typed React.
  - ✅ The frontend's main risk is drifting from the backend's WebSocket message contract.
    TypeScript lets me model the server frames as a discriminated union that mirrors the
    backend pydantic schemas, so the compiler catches shape mismatches and makes the
    `switch` over frame types exhaustive. Vite transpiles TS with no extra build tooling, and
    a `tsc --noEmit` step in the build enforces types.
  - ➖ A little config (a `tsconfig.json`) and hand-written types to maintain.
- **Plain JavaScript** — what the scaffold shipped.
  - ✅ Zero config; the README only asks for React.js.
  - ➖ No compile-time guarantee that client and server agree on the message shape; easier to
    let the contract drift silently.

**My choice: TypeScript.** At this size the cost is tiny and the payoff is a type-safe message
contract end-to-end — the client's frame types mirror the server's pydantic models, which is
exactly where a bug would otherwise hide. I kept the types hand-written to match the backend;
auto-generating them from the OpenAPI/JSON schema was considered and judged over-engineering
for this scope.

---

## D11 — Testing strategy: **layered, deterministic, no external dependencies**

I test each layer where its risk concentrates, and keep everything deterministic — no real
Telegram and no network — so the suite is fast and reproducible.

- **Backend (pytest, Telegram mocked):** unit tests for the single-chat invariant
  (claim/reject/override/reset + the concurrency lock) and the message store (ordering,
  fan-out, dead-client pruning), plus integration tests of the WebSocket bridge via FastAPI's
  `TestClient` (connect → status + history, send → forward + broadcast, error frames,
  multi-client fan-out). This is where the hard logic lives, so it gets the most coverage.
- **Frontend (Vitest + React Testing Library):** the `useChatSocket` hook against a mocked
  `WebSocket` (frame handling, `sendMessage` gating, reconnect) and `App` rendering/gating —
  including a regression guard that incoming vs outgoing messages render distinctly.
- **End-to-end (Playwright, WebSocket mocked in-browser):** one smoke that drives the real UI
  through connect → incoming → send → outgoing, using `page.routeWebSocket` so it needs no
  backend and no Telegram. Deterministic and dependency-free.

**Out of scope (a documented follow-up, not built):** a full-stack e2e against
`docker compose` with a real Telegram round-trip. Telegram is an external dependency that
can't be driven deterministically in CI without standing up a fake Bot API server; the cost
and flakiness aren't justified for this assignment, and the mocked-WebSocket e2e already
exercises the full client flow.

---

## Cross-cutting: state management, concurrency & message ordering

Because every message — incoming and outgoing — funnels through a single `broadcast()` call
on one asyncio event loop and is appended to one in-memory list in call order, **insertion
order is the canonical order** and each message gets a monotonically increasing integer id at
that point. There is no separate sorting step and no need to reconcile timestamps. That single
chokepoint, plus the `asyncio.Lock` on the chat claim, is how I satisfy the assignment's
requirement to handle state, concurrency, and ordering safely — without introducing a
database, queue, or external broker.

---

## Assumptions & limitations

- **Session-only, in-memory state** — message history is lost on backend restart; a single
  backend replica is assumed. (Explicitly permitted by the README.)
- **Text messages only** — no media, attachments, edits, or reactions.
- **"Active" = the chat currently bound to the session** — Telegram exposes no online/offline
  signal for a chat, so "active connection" means the bound chat, not a live presence.
- **Multiple browser tabs** are all views of the one Telegram session and stay consistent via
  history replay + broadcast.
- **Long-polling, not webhooks** — chosen for self-contained local setup; webhooks would be
  the production choice behind a real domain.

---

## Explicitly out of scope (to avoid over-engineering)

Persistence/database, Redis/message queues, authentication, multiple rooms/participants,
media/attachments, webhooks + public tunnel, frontend state-management libraries, and
multi-replica orchestration. Each is a conscious omission given the assignment's scope, noted
here rather than silently dropped.
