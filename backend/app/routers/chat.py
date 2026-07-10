"""SSE chat endpoint. Sends a 'thinking' status immediately (drives the UI
loader), streams the reply word-by-word for a live typing feel, then a
final event with the updated form draft for the client to render. The final
event also carries provider_used so it's visible right in the network tab
which model actually answered (groq vs the gemini fallback), no server log
digging required."""
import asyncio
import json
import logging

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from app.agent.graph import agent_graph
from app.schemas.chat import ChatRequest

logger = logging.getLogger("chat_router")
router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/stream")
async def chat_stream(req: ChatRequest):
    async def event_gen():
        yield {"event": "status", "data": "thinking"}

        config = {"configurable": {"thread_id": req.thread_id}}
        try:
            snapshot = agent_graph.get_state(config)
            draft = snapshot.values.get("draft", {}) if snapshot.values else {}
            result = agent_graph.invoke(
                {"messages": [{"role": "user", "content": req.message}], "draft": draft},
                config=config,
            )
        except Exception as e:  # noqa: BLE001 - never let a bad turn kill the stream
            logger.exception("chat turn failed")
            yield {"event": "error", "data": f"Sorry, something went wrong. Please try again. ({e})"}
            yield {"event": "status", "data": "done"}
            return

        reply = result.get("reply", "")
        for word in reply.split(" "):
            yield {"event": "token", "data": word + " "}
            await asyncio.sleep(0.02)  # cheap typing effect for the UI

        yield {
            "event": "final",
            "data": json.dumps(
                {
                    "draft": result.get("draft", {}),
                    "tool_results": result.get("tool_results", []),
                    "provider_used": result.get("provider_used", ""),
                }
            ),
        }
        yield {"event": "status", "data": "done"}

    return EventSourceResponse(event_gen())
