# AI-First CRM — HCP Log Interaction

![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=black)
![LangGraph](https://img.shields.io/badge/LangGraph-agent%20orchestration-1C3C3C)
![Groq](https://img.shields.io/badge/Groq-qwen3.6--27b-F55036?logo=groq&logoColor=white)
![Gemini](https://img.shields.io/badge/Gemini-2.5--flash%20fallback-4285F4?logo=googlegemini&logoColor=white)


## 1. About the app

- A "Log HCP Interaction" screen for a pharma field-rep CRM.
- Core rule: the form is **entirely read-only**. No field is ever typed into directly.
- The only way a field changes is by talking to an AI assistant in a chat panel.
- The assistant understands natural language, decides what the rep means, and calls backend tools that update the form live.
- A single message can update several fields at once — e.g. one sentence can set the HCP, the topic, and the sentiment together.
- Once the rep is happy with the draft, **Save Interaction** commits it to the database as a normal form submit — that step is not an AI action.

## 2. Frontend

- React 18 + Redux Toolkit, built with Vite.
- Split-screen layout: `InteractionForm` (left, read-only) and `AIAssistantPanel` (right, chat).
- Chat responses stream in word-by-word over Server-Sent Events, with a "thinking" loader while waiting.
- The form re-renders automatically whenever the backend confirms a field changed — no manual refresh, no direct edits.
- `src/api/client.js` handles the SSE stream manually (fetch + ReadableStream) since native `EventSource` can't POST.

## 3. Backend

- FastAPI + SQLAlchemy + Pydantic, MySQL by default (SQLite works too).
- LangGraph runs a 3-step, non-cyclic graph per message: **extract → execute_tools → respond**.
  - `extract` — one LLM call decides which tool(s) to call.
  - `execute_tools` — validates and runs each tool call against the database.
  - `respond` — composes a reply strictly from what the tools actually reported, so it can never claim something happened that didn't.
- 6 tools available to the assistant (brief required a minimum of 5):

  | Tool | Purpose |
  |---|---|
  | `log_interaction` | Extract fields from a free-text description of a NEW interaction |
  | `edit_interaction` | Correct/update fields already logged, leaving the rest untouched |
  | `clear_field` | Blank out a single field entirely |
  | `suggest_followup` | LLM-generated, HCP/topic-specific next-step suggestions |
  | `search_hcp` | Resolve an HCP name against the DB, with fuzzy matching and disambiguation |
  | `search_material` | Resolve a shared marketing material against the approved catalog |

- `hcp_name` and `materials_shared` can only be set via `search_hcp` / `search_material` — not a prompt rule, it's structurally absent from the other tools' schemas.
- LLM provider: Groq `qwen/qwen3.6-27b` as main, Gemini `gemini-2.5-flash` as an automatic fallback on error/timeout, with retries on both.
- Conversation memory comes from LangGraph's `MemorySaver` checkpointer, keyed by `thread_id`.

Full technical detail: [`backend/README.md`](backend/README.md) · [`frontend/README.md`](frontend/README.md)

## 4. How to run it

Requires Python 3.11+, Node 18+. MySQL is optional — SQLite works out of the box.

**Step 1 — Backend**
```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # fill in GROQ_API_KEY, GEMINI_API_KEY
python -m app.db.seed       # creates tables + seeds demo HCPs/materials
uvicorn app.main:app --reload
```
Backend runs at `http://localhost:8000`.

**Step 2 — Frontend** (new terminal)
```bash
cd frontend
npm install
cp .env.example .env        # VITE_API_BASE_URL, defaults to http://localhost:8000
npm run dev
```
Open the printed local URL (default `http://localhost:5173`).

**Step 3 — Try it**
Type a message like `"Met Dr. Sharma, positive sentiment, discussed Prodo-X"` in the chat and watch the form populate.

### Environment variables (`backend/.env`)

| Variable | Required | Notes |
|---|---|---|
| `GROQ_API_KEY` | Yes | Main LLM provider |
| `GEMINI_API_KEY` | Yes | Automatic fallback provider |
| `DATABASE_URL` | Yes | Any SQLAlchemy URL — MySQL example in `.env.example`, or `sqlite:///./dev.db` for zero-setup testing |
| `CORS_ORIGINS` | No | Defaults to the local Vite dev server |

**Never commit `.env`** — it's gitignored. Only `.env.example` (placeholder values) is tracked.

## Known deviations from the brief

- **Model substitution.** Brief names `gemma2-9b-it`, deprecated on Groq. Moved through `llama-3.3-70b-versatile` → `openai/gpt-oss-120b` → `qwen/qwen3.6-27b` as Groq's lineup changed (details in `backend/README.md`). Current model is tagged "Preview" by Groq — a one-line `.env` fallback to `llama-3.3-70b-versatile` is documented if it's ever pulled.
