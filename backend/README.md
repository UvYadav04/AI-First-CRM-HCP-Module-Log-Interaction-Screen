# AI-First CRM — HCP Log Interaction (Backend)

Backend for the "Log HCP Interaction" screen: the form is read-only, and is
only ever populated by talking to the AI assistant on the right. All chat
logic runs through a LangGraph graph backed by Groq (main) with Gemini as an
automatic fallback.

## Architecture in one paragraph

Each chat message triggers exactly ONE pass through a non-cyclic LangGraph
graph: `extract` (one LLM call decides which tool(s) to call, with
`parallel_tool_calls` enabled so a single compound message can produce
several tool calls at once) → `execute_tools` (runs them through a safe
wrapper, with `clear_field` always ordered first and a backstop that
auto-resolves a repeated identical disambiguation instead of looping) →
`respond` (an LLM composes a natural confirmation strictly grounded in what
the tools actually reported — it's given the real field=value pairs, not
just field names, and is explicitly forbidden from stating anything not
present in that data) → END. There's no agent loop across multiple LLM
calls — this is single-turn intent classification, not multi-step
reasoning. Conversation memory across turns comes from LangGraph's
`MemorySaver` checkpointer, keyed by `thread_id` — the client just keeps
sending the same `thread_id` for one logging session and the graph
automatically remembers everything said on it.

## The 6 tools

- `log_interaction` — extracts fields from a free-text description of a NEW interaction.
- `edit_interaction` — patches specific fields on what's already logged.
- `clear_field` — blanks a single field.
- `suggest_followup` — LLM-generated next-step suggestions from the current draft, with a rule-based fallback if the LLM call fails.
- `search_hcp` — resolves an HCP name against the seeded `hcps` table (token + fuzzy match, disambiguation when multiple match, `force_new` to accept an unmatched name as-is, `is_correction` to replace an already-recorded primary HCP rather than routing extra names to attendees).
- `search_material` — resolves a marketing material/brochure name against the seeded `materials` table, same `force_new` escape hatch.

`hcp_name`, `hcp_id`, and `materials_shared` are deliberately NOT fields on
`log_interaction`/`edit_interaction` — the only way they can be set is
through `search_hcp`/`search_material`, enforced by the tool schema itself
rather than by prompt instruction.

Hitting **Log** (final commit to the `interactions` table) is a plain REST
call (`POST /interactions`), not an agent tool — the LLM's job is done once
the draft looks right; committing it is a normal form submit.

## Model choice

The brief names `gemma2-9b-it` on Groq, which is deprecated. The project
went through two migrations as Groq's own model lineup changed underneath
it: `llama-3.3-70b-versatile` → `openai/gpt-oss-120b` → **`qwen/qwen3.6-27b`**
(current). The last move was specifically because `gpt-oss-120b` does not
support parallel tool calls on Groq, which silently broke multi-fact
single-message logging (a compound message could only ever produce one
tool call). `qwen/qwen3.6-27b` does support parallel tool calls.

Note: `qwen/qwen3.6-27b` is tagged "Preview" by Groq, which means it could
be pulled with limited notice. If that happens, set `GROQ_MODEL` (or edit
the default in `app/config.py`) to `llama-3.3-70b-versatile` — deprecated
but functional through 08/16/2026 — no other code changes needed.

Gemini 2.5 Flash is the automatic fallback if Groq errors, rate-limits, or
times out, with retries and exponential backoff on both providers before a
turn gives up and returns a clean error instead of crashing.

## Setup

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env   # fill in GROQ_API_KEY, GEMINI_API_KEY, DATABASE_URL
python -m app.db.seed  # creates tables + seeds ~12 HCPs and 7 materials
uvicorn app.main:app --reload
```

`DATABASE_URL` defaults to MySQL in `.env.example`, but any
SQLAlchemy-supported URL works — `sqlite:///./dev.db` is fine for quick
local testing without a MySQL server running (see the commented-out line in
`.env.example`).

Server runs at `http://localhost:8000` by default. Check `http://localhost:8000/health`.

## Endpoints

- `POST /chat/stream` — SSE stream. Body: `{"thread_id": str, "message": str}`.
  Emits `status` (thinking/done — drives the UI loader), `token` (chunked
  reply text — drives a typing effect), `final` (updated draft + raw tool
  results + `provider_used`), and `error` events.
- `POST /interactions` — commits the current draft for a `thread_id` to the DB.
- `GET /interactions/{id}` — fetch a committed interaction.

## Folder layout

```
app/
  config.py             settings from .env
  db/                   models, engine/session, seed data
  schemas/               pydantic models: form fields, chat request/response
  llm/                    provider.py (Groq+Gemini wrapper), prompt.py (system prompt)
  agent/                   state.py, tools.py, tool_executor.py, graph.py
  routers/                  chat.py (SSE), interactions.py (commit/get)
  main.py                    FastAPI app
```

## Security note

`.env` is gitignored and must never be committed. If you're forking or
resetting this repo, double-check `git ls-files | grep .env` comes back
empty before pushing.
