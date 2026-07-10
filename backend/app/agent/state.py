"""Graph state. One thread_id = one in-progress interaction draft; LangGraph's
checkpointer persists this between separate invoke() calls, which is how
conversation memory works WITHOUT needing an internal agent loop."""
import operator
from typing import Annotated, Any, Optional, TypedDict


class AgentState(TypedDict):
    messages: Annotated[list[dict], operator.add]  # running chat history (persisted)
    draft: dict[str, Any]  # current InteractionDraft as a plain dict (persisted)
    pending_tool_calls: list  # ToolCall objects from this turn's LLM call
    tool_results: list  # normalized results after execute_tools_node
    reply: str  # final assistant reply for this turn
    provider_used: str  # "groq" | "gemini" | "" - which LLM actually answered this turn
    # Tracks the last unresolved search_hcp/search_material disambiguation (tool +
    # candidate names) so a repeated identical ambiguous match next turn can be
    # auto-escalated to force_new instead of asking the same question forever -
    # a safety net for when the model doesn't set force_new itself. None when
    # nothing is pending.
    pending_search: Optional[dict]
