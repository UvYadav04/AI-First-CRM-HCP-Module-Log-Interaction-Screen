"""Thin, NON-CYCLIC LangGraph graph: extract -> execute_tools -> respond -> END.
Deliberately not a ReAct loop - there's nothing to iterate on within a turn,
the model just needs to pick tool(s) once. Conversation memory across turns
comes from the MemorySaver checkpointer keyed by thread_id, not from looping
inside a single invocation. See prompt.py / provider.py for the LLM side.

Per-node timing logs added so a slow turn can be traced to a specific stage
(LLM call vs DB-backed tool calls vs response formatting) instead of just
"the whole thing is slow". provider_used is also tracked through state so
the API response can say which model actually answered (groq vs the gemini
fallback) without digging through server logs.

respond_node uses an LLM to phrase the confirmation naturally (see
_compose_reply) rather than a robotic field-name dump. Earlier version of
this hallucinated invented details (a fake interaction type, a fake
sentiment, a product nobody mentioned) because it was only given tool
message text like "Logged: interaction_type." with no actual value - asked
to "sound natural" with nothing to be natural ABOUT, the model filled the
gap with plausible fiction. Two fixes now: (1) tools.py's messages carry the
real field=value pairs, not just field names, so the composer has something
true to work with, and (2) the composer prompt explicitly forbids stating
anything not present in that data. A deterministic fallback still covers a
provider outage."""
import logging
import time

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from app.agent.state import AgentState
from app.agent.tool_executor import safe_execute_tool
from app.agent.tools import TOOL_SCHEMAS
from app.db.database import SessionLocal
from app.llm.prompt import build_system_prompt
from app.llm.provider import LLMProviderError, provider

logger = logging.getLogger("agent_graph")


def extract_node(state: AgentState) -> dict:
    """One LLM call: understand the latest message, decide which tool(s) to call.
    A message with nothing actionable in it (small talk, "remember this for
    later", anything not covered by the 6 tools) is expected to come back
    with zero tool_calls and just a conversational `reply` - that's not a
    failure case, it's handled below in respond_node."""
    started = time.perf_counter()
    system_prompt = build_system_prompt(state["draft"])
    try:
        result = provider.generate(system_prompt, state["messages"], TOOL_SCHEMAS)
    except LLMProviderError:
        logger.error("extract_node: both providers failed after %.2fs", time.perf_counter() - started)
        return {
            "pending_tool_calls": [],
            "reply": "Sorry, I'm having trouble reaching the AI service right now. Please try again in a moment.",
            "provider_used": "",
        }
    logger.info(
        "extract_node: %.2fs, %d tool call(s) via %s",
        time.perf_counter() - started,
        len(result.tool_calls),
        result.provider_used,
    )
    return {"pending_tool_calls": result.tool_calls, "reply": result.reply, "provider_used": result.provider_used}


def _execution_order(call) -> int:
    return 0 if call.name == "clear_field" else 1


_SEARCH_TOOLS = ("search_hcp", "search_material")


def execute_tools_node(state: AgentState) -> dict:
    """Run each requested tool through the safe wrapper; merge draft updates in order.
    If the LLM didn't call anything (see extract_node's docstring), this is a
    clean no-op - draft/tool_results just pass through unchanged.

    Also guards against a repeated-disambiguation loop: if a search_hcp/
    search_material call lands on the exact same set of candidates we already
    asked the rep about last turn, and the model didn't pass force_new, that's
    treated as an implicit rejection and auto re-run with force_new=True. This
    doesn't rely on the model reliably recognizing "none of those" phrasing
    every time - it's a hard backstop against ever asking the same question
    more than twice."""
    started = time.perf_counter()
    draft = dict(state["draft"])
    results = []
    pending_search = state.get("pending_search")
    next_pending_search = None
    db = SessionLocal()
    ordered_calls = sorted(state["pending_tool_calls"], key=_execution_order)
    try:
        for call in ordered_calls:
            tool_started = time.perf_counter()
            outcome = safe_execute_tool(call.name, call.arguments, draft, db)

            if (
                outcome.get("ok")
                and outcome.get("data")
                and call.name in _SEARCH_TOOLS
                and pending_search
                and pending_search.get("tool") == call.name
                and not call.arguments.get("force_new")
                and set(outcome["data"]) == set(pending_search.get("candidates") or [])
            ):
                logger.info("%s: same disambiguation repeated, auto-escalating to force_new", call.name)
                outcome = safe_execute_tool(call.name, {**call.arguments, "force_new": True}, draft, db)

            logger.info("tool %s: %.2fs, ok=%s", call.name, time.perf_counter() - tool_started, outcome.get("ok"))
            if outcome.get("ok") and outcome.get("updated_draft") is not None:
                draft = outcome["updated_draft"]
            if outcome.get("data") and call.name in _SEARCH_TOOLS:
                next_pending_search = {"tool": call.name, "candidates": outcome["data"]}
            results.append({"tool": call.name, **outcome})
    finally:
        db.close()
    logger.info("execute_tools_node: %.2fs total, %d tool(s)", time.perf_counter() - started, len(results))
    return {"draft": draft, "tool_results": results, "pending_search": next_pending_search}


_RESPONSE_SYSTEM_PROMPT = """You just took actions in a pharma CRM chat via tools, based on what \
the rep said. Write ONE short, natural reply confirming what happened - like a helpful colleague \
speaking out loud, not a system log.

STRICT: only state facts that literally appear in the notes below. Never add a product name, \
sentiment, interaction type, person, or any other detail that isn't explicitly given to you - if \
the notes just say a field was set, mention that field's actual value, nothing more. If a tool is \
asking the rep to pick one of several options, keep that question intact and precise. If something \
failed, mention it briefly without jargon. No preamble, no markdown - just the reply text."""


def _fixed_fallback_reply(model_note: str, tool_results: list[dict]) -> str:
    """The original deterministic composer - used only if the LLM composer call
    fails, so a provider outage degrades reply quality rather than losing it.
    Every word here is copied verbatim from a tool's own message, so it can
    never state anything ungrounded."""
    notes = [r["message"] for r in tool_results if r.get("ok") and r.get("message")]
    errors = [r["error"] for r in tool_results if not r.get("ok")]
    reply = model_note
    if notes:
        reply = (reply + " " + " ".join(notes)).strip()
    if errors:
        reply = (reply + " (Note: " + "; ".join(errors) + ")").strip()
    return reply or "Done."


def _compose_reply(model_note: str, tool_results: list[dict]) -> str:
    """Turn the turn's tool outcomes into one natural reply via an LLM call.
    Grounding matters here: each tool_results message already carries the
    actual field=value pairs that changed (see tools.py's _describe_changes),
    not just field names - so the composer has real facts to paraphrase
    instead of having to invent plausible-sounding ones. Skipped entirely
    when no tools ran (pure small talk) - extract_node's own reply already
    covers that case, no need for a second LLM call."""
    if not tool_results:
        return model_note or "I didn't quite catch anything actionable there - could you tell me a bit more, or what you'd like to log?"

    lines = [f"- {r['tool']}: {r.get('message') or r.get('error') or ('done' if r.get('ok') else 'failed')}" for r in tool_results]
    context = "What just happened this turn (the ONLY facts you may state):\n" + "\n".join(lines)
    if model_note:
        context += f"\n\nModel's own note to weave in if useful (also just a fact, don't embellish it): {model_note}"

    try:
        composed = provider.generate_text(_RESPONSE_SYSTEM_PROMPT, context).strip()
        if composed:
            return composed
    except LLMProviderError as e:
        logger.warning("respond_node: composer LLM failed, using fixed fallback: %s", e)
    return _fixed_fallback_reply(model_note, tool_results)


def respond_node(state: AgentState) -> dict:
    """Compose the final assistant message via an LLM pass over this turn's
    tool outcomes (see _compose_reply) so replies sound natural instead of
    robotic, with a deterministic fallback if that call fails."""
    started = time.perf_counter()
    reply = _compose_reply((state.get("reply") or "").strip(), state["tool_results"])
    logger.info("respond_node: %.2fs", time.perf_counter() - started)
    return {
        "messages": [{"role": "assistant", "content": reply}],
        "reply": reply,
    }


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("extract", extract_node)
    graph.add_node("execute_tools", execute_tools_node)
    graph.add_node("respond", respond_node)

    graph.set_entry_point("extract")
    graph.add_edge("extract", "execute_tools")
    graph.add_edge("execute_tools", "respond")
    graph.add_edge("respond", END)

    return graph.compile(checkpointer=MemorySaver())


agent_graph = build_graph()
