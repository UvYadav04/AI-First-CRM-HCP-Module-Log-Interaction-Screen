// Small typing/thinking indicator - the "loader" the brief asks for while
// the bot is working, shown before the first streamed token arrives.
export default function Loader({ label = "Assistant is thinking" }) {
  return (
    <div className="loader-row" role="status" aria-live="polite">
      <span className="loader-dots">
        <span></span>
        <span></span>
        <span></span>
      </span>
      <span className="loader-label">{label}</span>
    </div>
  );
}
