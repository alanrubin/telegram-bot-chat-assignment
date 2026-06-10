import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Manages the single WebSocket to the backend chat bridge.
 *
 * Connects on mount to a same-origin `/ws` (Vite proxies it to the backend in dev; nginx
 * proxies it in production), parses the type-tagged frames, and reconnects with capped
 * exponential backoff if the socket drops. The backend is the source of truth: outgoing
 * messages are not echoed locally — they arrive back as a broadcast `message` frame.
 */

export type Direction = "incoming" | "outgoing";

/** Mirrors the backend `Message` pydantic model (timestamp is an ISO-8601 string). */
export interface Message {
  id: number;
  text: string;
  timestamp: string;
  direction: Direction;
  sender: string;
}

/** The discriminated union of frames the server can push (mirrors backend schemas). */
type ServerFrame =
  | { type: "history"; messages: Message[] }
  | { type: "message"; message: Message }
  | { type: "status"; connected: boolean; activeChat: boolean }
  | { type: "error"; detail: string };

export interface ChatSocket {
  messages: Message[];
  connected: boolean;
  activeChat: boolean;
  error: string | null;
  clearError: () => void;
  /** Sends a `send` frame; returns false if the socket isn't open. */
  sendMessage: (text: string) => boolean;
}

const RECONNECT_BASE_MS = 1000;
const RECONNECT_MAX_MS = 15000;

function buildWsUrl(): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws`;
}

export function useChatSocket(): ChatSocket {
  const [messages, setMessages] = useState<Message[]>([]);
  const [connected, setConnected] = useState(false);
  const [activeChat, setActiveChat] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const socketRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const attemptsRef = useRef(0);
  const intentionalCloseRef = useRef(false);

  const connect = useCallback(() => {
    const socket = new WebSocket(buildWsUrl());
    socketRef.current = socket;

    socket.onopen = () => {
      setConnected(true);
      attemptsRef.current = 0;
    };

    socket.onmessage = (event: MessageEvent) => {
      let frame: ServerFrame;
      try {
        frame = JSON.parse(event.data) as ServerFrame;
      } catch {
        return; // ignore unparseable frames defensively
      }
      switch (frame.type) {
        case "history":
          setMessages(frame.messages ?? []);
          break;
        case "message":
          setMessages((prev) => [...prev, frame.message]);
          break;
        case "status":
          setActiveChat(Boolean(frame.activeChat));
          break;
        case "error":
          setError(frame.detail ?? "Something went wrong.");
          break;
        default:
          break; // unknown frame types are ignored
      }
    };

    socket.onclose = () => {
      setConnected(false);
      setActiveChat(false);
      if (intentionalCloseRef.current) return;
      // Reconnect with capped exponential backoff.
      const delay = Math.min(
        RECONNECT_BASE_MS * 2 ** attemptsRef.current,
        RECONNECT_MAX_MS
      );
      attemptsRef.current += 1;
      reconnectTimerRef.current = setTimeout(connect, delay);
    };

    socket.onerror = () => {
      socket.close(); // triggers onclose -> reconnect
    };
  }, []);

  useEffect(() => {
    intentionalCloseRef.current = false;
    connect();
    return () => {
      intentionalCloseRef.current = true;
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      socketRef.current?.close();
    };
  }, [connect]);

  const sendMessage = useCallback((text: string): boolean => {
    const socket = socketRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) return false;
    socket.send(JSON.stringify({ type: "send", text }));
    return true;
  }, []);

  const clearError = useCallback(() => setError(null), []);

  return { messages, connected, activeChat, error, clearError, sendMessage };
}
