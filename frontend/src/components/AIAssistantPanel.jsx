// Right panel: the ONLY way the rep interacts with the form. Sends a
// message, streams the reply back (loader while thinking, tokens as they
// arrive), and retries once on a dropped connection (see api/client.js).
import { useEffect, useRef, useState } from "react";
import { useDispatch, useSelector } from "react-redux";
import { sendMessage } from "../store/chatThunks.js";
import ChatMessage from "./ChatMessage.jsx";
import Loader from "./Loader.jsx";

export default function AIAssistantPanel() {
  const dispatch = useDispatch();
  const { messages, status } = useSelector((state) => state.chat);
  const [input, setInput] = useState("");
  const listRef = useRef(null);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, status]);

  const busy = status === "thinking" || status === "streaming";

  const handleSend = () => {
    if (!input.trim() || busy) return;
    dispatch(sendMessage(input));
    setInput("");
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="panel chat-panel">
      <div className="panel-header">
        <div>
          <h2>🩺 AI Assistant</h2>
          <p className="hint">Log interaction details here via chat</p>
        </div>
      </div>

      <div className="chat-messages" ref={listRef}>
        {messages.map((m) => (
          <ChatMessage key={m.id} role={m.role} content={m.content} />
        ))}
        {status === "thinking" && <Loader label="Assistant is thinking" />}
      </div>

      <div className="chat-input-row">
        <textarea
          rows={2}
          placeholder="Describe interaction..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={busy}
        />
        <button className="btn btn-primary" onClick={handleSend} disabled={busy || !input.trim()}>
          {busy ? "..." : "Log"}
        </button>
      </div>
    </div>
  );
}
