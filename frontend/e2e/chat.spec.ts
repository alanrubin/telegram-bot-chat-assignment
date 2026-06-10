import { expect, test, type WebSocketRoute } from "@playwright/test";

// Drives the full UI flow with the backend WebSocket mocked entirely in the browser:
// the mock acts as a server-authoritative backend (echoes sends back as outgoing messages).
test("incoming and outgoing messages render via a mocked WebSocket", async ({ page }) => {
  let serverWs: WebSocketRoute | undefined;

  await page.routeWebSocket("**/ws", (ws) => {
    serverWs = ws;
    // Initial sync: a bound participant + empty history.
    ws.send(JSON.stringify({ type: "status", connected: true, activeChat: true }));
    ws.send(JSON.stringify({ type: "history", messages: [] }));
    // Echo outgoing sends back, as the real server does.
    ws.onMessage((message) => {
      const frame = JSON.parse(String(message));
      if (frame.type === "send") {
        ws.send(
          JSON.stringify({
            type: "message",
            message: {
              id: 2,
              text: frame.text,
              timestamp: new Date().toISOString(),
              direction: "outgoing",
              sender: "You",
            },
          })
        );
      }
    });
  });

  await page.goto("/");

  // Active chat -> input enabled.
  const input = page.getByPlaceholder("Type a message…");
  await expect(input).toBeEnabled();

  // Incoming Telegram message (pushed by the mock) shows as a left bubble.
  await serverWs!.send(
    JSON.stringify({
      type: "message",
      message: {
        id: 1,
        text: "hi from telegram",
        timestamp: new Date().toISOString(),
        direction: "incoming",
        sender: "Alan",
      },
    })
  );
  await expect(page.locator(".chat-message.incoming .chat-text")).toHaveText(
    "hi from telegram"
  );

  // Outgoing: type + send -> echoed back as a right bubble.
  await input.fill("hello e2e");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.locator(".chat-message.outgoing .chat-text")).toHaveText("hello e2e");
});
