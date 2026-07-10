// Left panel. Every field is read-only - per the brief, this form can ONLY
// change via tool calls the AI Assistant makes on the right. There is no
// onChange handler anywhere in this file on purpose.
import { useDispatch, useSelector } from "react-redux";
import { commitDraft } from "../store/interactionSlice.js";

const SENTIMENTS = ["Positive", "Neutral", "Negative"];

function Field({ label, children }) {
  return (
    <div className="field">
      <label>{label}</label>
      {children}
    </div>
  );
}

function ReadOnlyInput({ value, placeholder }) {
  return <input readOnly disabled value={value ?? ""} placeholder={placeholder} />;
}

function ReadOnlyTextarea({ value, placeholder, rows = 3 }) {
  return <textarea readOnly disabled value={value ?? ""} placeholder={placeholder} rows={rows} />;
}

function ChipList({ items, emptyLabel }) {
  // Defensive: the backend now coerces list fields, but this stays as a
  // second line of defense so a stray non-array value never crashes the
  // whole screen - it just renders as empty instead.
  const list = Array.isArray(items) ? items : items ? [items] : [];
  if (list.length === 0) {
    return <p className="chip-list-empty">{emptyLabel}</p>;
  }
  return (
    <div className="chip-list">
      {list.map((item, i) => (
        <span className="chip" key={`${item}-${i}`}>
          {item}
        </span>
      ))}
    </div>
  );
}

export default function InteractionForm() {
  const dispatch = useDispatch();
  const { draft, followupSuggestions, committing, committedId, commitError } = useSelector(
    (state) => state.interaction,
  );

  const attendees = Array.isArray(draft.attendees) ? draft.attendees.join(", ") : draft.attendees;

  return (
    <div className="panel form-panel">
      <div className="panel-header">
        <div>
          <h1>Log HCP Interaction</h1>
          <p className="hint">Populated automatically by the AI Assistant &rarr;</p>
        </div>
        <button
          className="btn btn-primary"
          disabled={committing || !draft || Object.keys(draft).length === 0}
          onClick={() => dispatch(commitDraft())}
        >
          {committing ? "Saving..." : "Save Interaction"}
        </button>
      </div>

      {committedId && <p className="status-banner status-banner--success">Saved as interaction #{committedId}</p>}
      {commitError && <p className="status-banner status-banner--error">{commitError}</p>}

      <div className="field-row">
        <Field label="HCP Name">
          <ReadOnlyInput value={draft.hcp_name} placeholder="Search or select HCP..." />
        </Field>
        <Field label="Interaction Type">
          <ReadOnlyInput value={draft.interaction_type} placeholder="Meeting" />
        </Field>
      </div>

      <div className="field-row">
        <Field label="Date">
          <ReadOnlyInput value={draft.date} placeholder="DD-MM-YYYY" />
        </Field>
        <Field label="Time">
          <ReadOnlyInput value={draft.time} placeholder="--:--" />
        </Field>
      </div>

      <Field label="Attendees">
        <ReadOnlyInput value={attendees} placeholder="Enter names or search..." />
      </Field>

      <Field label="Topics Discussed">
        <ReadOnlyTextarea value={draft.topics_discussed} placeholder="Enter key discussion points..." />
      </Field>
      <p className="hint hint--muted">🎙 Summarize from Voice Note (not wired up in this build)</p>

      <div className="field-row">
        <Field label="Materials Shared">
          <ChipList items={draft.materials_shared} emptyLabel="No materials added." />
        </Field>
        <Field label="Samples Distributed">
          <ChipList items={draft.samples_distributed} emptyLabel="No samples added." />
        </Field>
      </div>

      <Field label="Observed/Inferred HCP Sentiment">
        <div className="sentiment-row">
          {SENTIMENTS.map((s) => (
            <span key={s} className={`sentiment-pill ${draft.sentiment === s ? "sentiment-pill--active" : ""}`}>
              {s}
            </span>
          ))}
        </div>
      </Field>

      <Field label="Outcomes">
        <ReadOnlyTextarea value={draft.outcomes} placeholder="Key outcomes or agreements..." />
      </Field>

      <Field label="Follow-up Actions">
        <ReadOnlyTextarea value={draft.followup_actions} placeholder="Enter next steps or tasks..." rows={2} />
      </Field>

      {followupSuggestions.length > 0 && (
        <div className="suggestions">
          <p className="hint">AI Suggested Follow-ups:</p>
          <ul>
            {followupSuggestions.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
