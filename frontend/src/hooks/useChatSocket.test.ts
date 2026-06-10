import { StrictMode, createElement, type ReactNode } from "react";
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useChatSocket } from "./useChatSocket";

/** Minimal fake WebSocket we can drive from tests (open, push frames, close). */
class FakeWebSocket {
  static OPEN = 1;
  static instances: FakeWebSocket[] = [];

  readyState = 0;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  sent: string[] = [];

  constructor(public url: string) {
    FakeWebSocket.instances.push(this);
  }

  send(data: string) {
    this.sent.push(data);
  }

  close() {
    this.readyState = 3;
    this.onclose?.();
  }

  simulateOpen() {
    this.readyState = 1;
    this.onopen?.();
  }

  simulateMessage(frame: unknown) {
    this.onmessage?.({ data: JSON.stringify(frame) });
  }

  simulateRaw(data: string) {
    this.onmessage?.({ data });
  }
}

const latest = () => FakeWebSocket.instances[FakeWebSocket.instances.length - 1];

beforeEach(() => {
  FakeWebSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeWebSocket);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("useChatSocket", () => {
  it("marks connected on open and loads history", () => {
    const { result } = renderHook(() => useChatSocket());
    act(() => latest().simulateOpen());
    expect(result.current.connected).toBe(true);

    act(() =>
      latest().simulateMessage({
        type: "history",
        messages: [
          { id: 1, text: "a", timestamp: "t", direction: "incoming", sender: "X" },
        ],
      })
    );
    expect(result.current.messages).toHaveLength(1);
  });

  it("appends a broadcast message frame", () => {
    const { result } = renderHook(() => useChatSocket());
    act(() => latest().simulateOpen());
    act(() =>
      latest().simulateMessage({
        type: "message",
        message: { id: 2, text: "b", timestamp: "t", direction: "outgoing", sender: "You" },
      })
    );
    const all = result.current.messages;
    expect(all[all.length - 1]?.text).toBe("b");
  });

  it("tracks activeChat from a status frame", () => {
    const { result } = renderHook(() => useChatSocket());
    act(() => latest().simulateMessage({ type: "status", connected: true, activeChat: true }));
    expect(result.current.activeChat).toBe(true);
  });

  it("surfaces an error frame", () => {
    const { result } = renderHook(() => useChatSocket());
    act(() => latest().simulateMessage({ type: "error", detail: "oops" }));
    expect(result.current.error).toBe("oops");
  });

  it("ignores malformed frames without throwing", () => {
    const { result } = renderHook(() => useChatSocket());
    act(() => latest().simulateRaw("this is not json"));
    expect(result.current.messages).toHaveLength(0);
    expect(result.current.error).toBeNull();
  });

  it("sendMessage emits a send frame when open and refuses when closed", () => {
    const { result } = renderHook(() => useChatSocket());
    act(() => latest().simulateOpen());

    let ok = false;
    act(() => {
      ok = result.current.sendMessage("hi");
    });
    expect(ok).toBe(true);
    expect(JSON.parse(latest().sent[0])).toEqual({ type: "send", text: "hi" });

    latest().readyState = 3; // socket no longer open
    act(() => {
      ok = result.current.sendMessage("nope");
    });
    expect(ok).toBe(false);
    expect(latest().sent).toHaveLength(1);
  });

  it("reconnects after an unexpected close", () => {
    vi.useFakeTimers();
    const { unmount } = renderHook(() => useChatSocket());
    act(() => latest().simulateOpen());

    const before = FakeWebSocket.instances.length;
    act(() => latest().close()); // unexpected drop
    act(() => {
      vi.advanceTimersByTime(1000); // first backoff
    });

    expect(FakeWebSocket.instances.length).toBe(before + 1);
    unmount();
  });

  it("does not render a message twice if it is delivered twice (idempotent by id)", () => {
    const { result } = renderHook(() => useChatSocket());
    act(() => latest().simulateOpen());
    const frame = {
      type: "message",
      message: { id: 7, text: "once", timestamp: "t", direction: "incoming", sender: "X" },
    };
    act(() => latest().simulateMessage(frame));
    act(() => latest().simulateMessage(frame)); // duplicate delivery
    expect(result.current.messages).toHaveLength(1);
  });

  it("does not spawn a second connection when a replaced socket closes late (StrictMode)", () => {
    // StrictMode double-invokes effects (mount -> cleanup -> mount), reproducing the race
    // that previously left two live sockets and duplicated every message.
    vi.useFakeTimers();
    const wrapper = ({ children }: { children: ReactNode }) =>
      createElement(StrictMode, null, children);
    renderHook(() => useChatSocket(), { wrapper });

    // instances[0] was created then cleaned up; instances[1] is the live socket.
    expect(FakeWebSocket.instances.length).toBe(2);
    const replaced = FakeWebSocket.instances[0];

    // The replaced socket closing must NOT trigger a reconnect.
    act(() => replaced.onclose?.());
    act(() => vi.advanceTimersByTime(5000));

    expect(FakeWebSocket.instances.length).toBe(2);
  });
});
