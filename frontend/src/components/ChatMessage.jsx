export default function ChatMessage({ role, content }) {
  const isUser = role === "user";
  return (
    <div className={`chat-message ${isUser ? "chat-message--user" : "chat-message--assistant"}`}>
      {content}
    </div>
  );
}
