# AI-First CRM — HCP Log Interaction (Frontend)

React + Redux Toolkit split-screen UI. The left panel (`InteractionForm`) is
entirely read-only — every field is `disabled`, on purpose, with no
`onChange` handlers anywhere in that file. The only way data gets onto the
form is via the right panel (`AIAssistantPanel`), which streams to the
backend's `/chat/stream` SSE endpoint and dispatches the returned draft into
Redux.

## Setup

```bash
cd frontend
npm install
cp .env.example .env   # set VITE_API_BASE_URL if the backend isn't on :8000
npm run dev
```

Backend must be running first (see `../backend/README.md`).

## How a chat turn flows

1. User types in `AIAssistantPanel` and hits **Log** (or Enter).
2. `sendMessage` thunk (`src/store/chatThunks.js`) posts to `/chat/stream`
   and reads the SSE response manually via `fetch` + `ReadableStream` —
   native `EventSource` can't send a POST body, which this endpoint needs.
3. A `status: thinking` event shows the typing-dots loader
   (`components/Loader.jsx`) before any text arrives.
4. `token` events stream the reply in word by word for a live-typing feel.
5. A `final` event carries the updated form draft + raw tool results;
   `setDraft` pushes it into `interactionSlice`, which is what
   `InteractionForm` renders — the form updates itself, the user never
   touches it directly.
6. If `suggest_followup` was one of the tools called, its suggestions render
   in the yellow "AI Suggested Follow-ups" box.

Once the rep is happy with the draft, **Save Interaction** (top of the form
panel) calls `POST /interactions` to commit it to the database — this is a
plain REST call, not a chat message, matching the backend design where
committing to MySQL isn't one of the 6 LangGraph tools.

## Error handling

`src/api/client.js` retries the initial connection once on a network
failure before giving up; a failed stream surfaces as a chat bubble with a
plain-language error instead of a silent failure or a stuck loader.

## Not wired up in this build

"Summarize from Voice Note" appears in the mockup but has no working tool
behind it here — it's shown greyed out for visual fidelity to the spec
rather than removed outright.
