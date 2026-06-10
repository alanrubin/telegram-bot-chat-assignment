import { useState } from "react";
import "./index.css";

function App() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");

  const sendMessage = () => {
    if (!input.trim()) return;

    setMessages((prev) => [
      ...prev,
      {
        id: crypto.randomUUID(),
        text: input,
        timestamp: new Date().toISOString(),
        direction: "outgoing",
      },
    ]);

    setInput("");
  };

  return (
    <div className="chat-page">
      <div className="chat-container">
        <header className="chat-header">
          <h2>Telegram Chat</h2>
        </header>

        <div className="chat-messages">
          {messages.map((msg) => (
            <div
              key={msg.id}
              className={`chat-message outgoing`}
            >
              <div className="chat-bubble">
                <div className="chat-text">{msg.text}</div>
                <div className="chat-timestamp">
                  {new Date(msg.timestamp).toLocaleTimeString()}
                </div>
              </div>
            </div>
          ))}
        </div>

        <div className="chat-input">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Type a message..."
            onKeyDown={(e) => e.key === "Enter" && sendMessage()}
          />
          <button onClick={sendMessage}>Send</button>
        </div>
      </div>
    </div>
  );
}

export default App;
