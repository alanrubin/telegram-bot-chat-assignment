import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import App from "./App";
import { useChatSocket, type ChatSocket } from "./hooks/useChatSocket";

vi.mock("./hooks/useChatSocket");
const mockedUseChatSocket = vi.mocked(useChatSocket);

function setup(overrides: Partial<ChatSocket> = {}) {
  const sendMessage = vi.fn(() => true);
  const clearError = vi.fn();
  mockedUseChatSocket.mockReturnValue({
    messages: [],
    connected: true,
    activeChat: true,
    error: null,
    clearError,
    sendMessage,
    ...overrides,
  });
  render(<App />);
  return { sendMessage, clearError };
}

describe("App", () => {
  it("renders incoming and outgoing messages with distinguishing classes", () => {
    setup({
      messages: [
        { id: 1, text: "hi there", timestamp: "2026-06-10T12:00:00Z", direction: "incoming", sender: "Alan" },
        { id: 2, text: "hello back", timestamp: "2026-06-10T12:01:00Z", direction: "outgoing", sender: "You" },
      ],
    });

    expect(screen.getByText("hi there").closest(".chat-message")).toHaveClass("incoming");
    expect(screen.getByText("hello back").closest(".chat-message")).toHaveClass("outgoing");
  });

  it("disables input and send when not connected / no active chat", () => {
    setup({ connected: false, activeChat: false });
    expect(screen.getByPlaceholderText("Waiting for connection…")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
  });

  it("sends the typed text on button click when ready", () => {
    const { sendMessage } = setup();
    const input = screen.getByPlaceholderText("Type a message…");
    fireEvent.change(input, { target: { value: "hello" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(sendMessage).toHaveBeenCalledWith("hello");
  });

  it("sends on Enter key", () => {
    const { sendMessage } = setup();
    const input = screen.getByPlaceholderText("Type a message…");
    fireEvent.change(input, { target: { value: "via enter" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(sendMessage).toHaveBeenCalledWith("via enter");
  });

  it("shows an error notice when the hook reports one", () => {
    setup({ error: "Failed to send your message." });
    expect(screen.getByRole("alert")).toHaveTextContent("Failed to send your message.");
  });
});
