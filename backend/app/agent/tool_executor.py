"""Safe wrapper around every tool call: validate args, run the impl, and
ALWAYS return a normalized {ok, ...} dict instead of letting anything raise
past this point - a bad LLM call must never crash a chat turn."""
import logging

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.agent.tools import ARG_SCHEMAS, TOOL_IMPLEMENTATIONS

logger = logging.getLogger("tool_executor")


def safe_execute_tool(name: str, arguments: dict, draft: dict, db: Session) -> dict:
    if name not in TOOL_IMPLEMENTATIONS:
        return {"ok": False, "error": f"Unknown tool '{name}'"}

    try:
        clean_args = ARG_SCHEMAS[name].model_validate(arguments).model_dump()
    except ValidationError as e:
        logger.warning("Bad args for %s: %s", name, e)
        return {"ok": False, "error": f"Invalid arguments for {name}: {e.errors()[0]['msg']}"}

    try:
        result = TOOL_IMPLEMENTATIONS[name](draft, clean_args, db)
        return {"ok": True, **result}
    except Exception as e:  # noqa: BLE001 - a broken tool must not crash the turn
        logger.exception("Tool %s failed", name)
        return {"ok": False, "error": f"{name} failed: {e}"}
