import { useEffect, useRef, useState } from "react";
import { useChatSocket } from "./hooks/useChatSocket";
import "./index.css";

function App() {
  const { messages, connected, activeChat, error, clearError, sendMessage } =
    useChatSocket();
  const [input, setInput] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to the latest message whenever the list grows.
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length]);

  const canSend = connected && activeChat;

  const handleSend = () => {
    const text = input.trim();
    if (!text || !canSend) return;
    // Server-authoritative: the message renders when it returns as a broadcast frame.
    if (sendMessage(text)) {
      setInput("");
      clearError();
    }
  };

  const statusLabel = !connected
    ? "Disconnected — reconnecting…"
    : activeChat
    ? "Connected"
    : "Waiting for a Telegram participant…";

  const statusClass = !connected ? "offline" : activeChat ? "online" : "idle";

  return (
    <div className="chat-page">
      <div className="chat-container">
        <header className="chat-header">
          <h2>Telegram Chat</h2>
          <div className="chat-status">
            <span className={`status-dot ${statusClass}`} />
            <span className="status-label">{statusLabel}</span>
          </div>
        </header>

        <div className="chat-messages">
          {messages.map((msg) => (
            <div key={msg.id} className={`chat-message ${msg.direction}`}>
              <div className="chat-bubble">
                <div className="chat-text">{msg.text}</div>
                <div className="chat-timestamp">
                  {new Date(msg.timestamp).toLocaleTimeString()}
                </div>
              </div>
            </div>
          ))}
          <div ref={messagesEndRef} />
        </div>

        {error && (
          <div className="chat-error" role="alert">
            {error}
          </div>
        )}

        <div className="chat-input">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={canSend ? "Type a message…" : "Waiting for connection…"}
            onKeyDown={(e) => e.key === "Enter" && handleSend()}
            disabled={!canSend}
          />
          <button onClick={handleSend} disabled={!canSend || !input.trim()}>
            Send
          </button>
        </div>
      </div>
    </div>
  );
}

export default App;
