"""The 6 LangGraph tools. Each impl takes (draft, args, db) and returns a
dict the executor normalizes - never raises for expected/user-facing cases,
only for genuine bugs (which tool_executor catches anyway).

Note on schema design: log_interaction/edit_interaction originally took a
nested `fields: {...}` / `patch: {...}` object. Groq's constrained decoding
kept rejecting that shape and generating flat top-level arguments instead
(`{"sentiment": "Negative", "topics_discussed": "..."}` directly, no
wrapper) - so the schema below now matches what the model actually wants to
produce: explicit named, optional properties, no free-form nested object."""
import json
import logging
import re
from difflib import get_close_matches
from typing import Optional

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.models import HCP, Material
from app.llm.provider import provider
from app.schemas.interaction import FIELD_NAMES, INTERACTION_TYPES, LIST_FIELDS, SENTIMENT_VALUES

logger = logging.getLogger("agent_tools")

# hcp_name/hcp_id/materials_shared are only ever set by search_hcp / search_material
# (which resolve to a real DB row) - log_interaction/edit_interaction are blocked
# from writing them directly so a raw, unresolved string can never land in the draft.
RESOLVED_ONLY_FIELDS = {"hcp_id", "hcp_name", "materials_shared"}

LOGGABLE_FIELDS = [f for f in FIELD_NAMES if f not in RESOLVED_ONLY_FIELDS]

# ---- per-tool argument schemas, validated by tool_executor before running ----


class LogInteractionArgs(BaseModel):
    interaction_type: Optional[str] = None
    date: Optional[str] = None
    time: Optional[str] = None
    attendees: Optional[list[str]] = None
    topics_discussed: Optional[str] = None
    samples_distributed: Optional[list[str]] = None
    sentiment: Optional[str] = None
    outcomes: Optional[str] = None
    followup_actions: Optional[str] = None


class EditInteractionArgs(LogInteractionArgs):
    """Same fields as log_interaction - the distinction is purely about
    intent (new info vs. correcting something already logged), not shape."""


class ClearFieldArgs(BaseModel):
    field: str


class SuggestFollowupArgs(BaseModel):
    pass


class SearchHCPArgs(BaseModel):
    query: str
    force_new: bool = False
    # True only when the rep is explicitly replacing the already-recorded
    # primary HCP (not just mentioning another person present).
    is_correction: bool = False


class SearchMaterialArgs(BaseModel):
    query: str
    force_new: bool = False


ARG_SCHEMAS = {
    "log_interaction": LogInteractionArgs,
    "edit_interaction": EditInteractionArgs,
    "clear_field": ClearFieldArgs,
    "suggest_followup": SuggestFollowupArgs,
    "search_hcp": SearchHCPArgs,
    "search_material": SearchMaterialArgs,
}

# Shared JSON-schema properties for log_interaction / edit_interaction - every
# field is optional and independent, no wrapper object, so the model can just
# emit whichever ones it has information for. Groq's strict tool-call mode
# fills in every declared property regardless of "required", using null for
# ones it has nothing to say about - so type must explicitly allow null, or
# it 400s with "expected string, but got null". enum lists get None added
# for the same reason.
_LOGGABLE_PROPERTIES = {
    "interaction_type": {"type": ["string", "null"], "enum": INTERACTION_TYPES + [None]},
    "date": {"type": ["string", "null"], "description": "e.g. 2025-04-19"},
    "time": {"type": ["string", "null"], "description": "e.g. 14:30"},
    "attendees": {"type": ["array", "null"], "items": {"type": "string"}},
    "topics_discussed": {"type": ["string", "null"]},
    "samples_distributed": {"type": ["array", "null"], "items": {"type": "string"}},
    "sentiment": {"type": ["string", "null"], "enum": SENTIMENT_VALUES + [None]},
    "outcomes": {"type": ["string", "null"]},
    "followup_actions": {"type": ["string", "null"]},
}

# ---- Groq/OpenAI-style tool schemas sent to the LLM ----

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "log_interaction",
            "description": "Log a new interaction. Set only the fields mentioned; leave others out.",
            "parameters": {"type": "object", "properties": _LOGGABLE_PROPERTIES, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_interaction",
            "description": "Correct/update already-logged fields; leaves everything else untouched.",
            "parameters": {"type": "object", "properties": _LOGGABLE_PROPERTIES, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "clear_field",
            "description": "Blank out a single field the rep wants removed.",
            "parameters": {
                "type": "object",
                "properties": {"field": {"type": "string", "enum": FIELD_NAMES}},
                "required": ["field"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "suggest_followup",
            "description": "Generate suggested next-step follow-up actions from the current draft.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_hcp",
            "description": "Resolve an HCP name mentioned - the only way hcp_name/hcp_id get set. "
            "Safe to call for every doctor named: if a primary HCP is already recorded, extra names "
            "are auto-added to attendees instead of replacing it. Pass is_correction=true only when "
            "the rep is explicitly replacing the recorded HCP. force_new=true if the rep rejected "
            "the suggested matches.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "force_new": {
                        "type": "boolean",
                        "description": "true only if the rep explicitly rejected the previously suggested matches",
                    },
                    "is_correction": {
                        "type": "boolean",
                        "description": "true only if replacing the already-recorded primary HCP",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_material",
            "description": "Resolve a material/brochure shared - the only way materials_shared gets "
            "set. Same force_new escape hatch as search_hcp.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "force_new": {
                        "type": "boolean",
                        "description": "true only if the rep explicitly rejected the previously suggested matches",
                    },
                },
                "required": ["query"],
            },
        },
    },
]


def _coerce_value(key: str, value):
    """The LLM doesn't always respect field types - e.g. it may hand back a
    plain string for a list field like materials_shared instead of a
    single-item list. Normalize here so a type slip never reaches the
    frontend as a crash (it previously did: items.map is not a function)."""
    if key in LIST_FIELDS:
        if value is None:
            return None
        if isinstance(value, list):
            return [str(v) for v in value]
        return [str(value)]
    return value


def _merge_fields(draft: dict, incoming: dict) -> tuple[dict, list[str]]:
    """Only accept known, non-resolved-only fields with valid enum values -
    silently drop hallucinated keys, bad enum values, and any attempt to set
    hcp_name/hcp_id/materials_shared directly. A None/omitted value means
    "the model had nothing to say about this field" and must NOT overwrite
    whatever's already in the draft - only clear_field is allowed to blank
    something out on purpose."""
    updated = dict(draft)
    changed = []
    for key, value in incoming.items():
        if value is None:
            continue
        if key not in FIELD_NAMES or key in RESOLVED_ONLY_FIELDS:
            continue
        if key == "sentiment" and value not in SENTIMENT_VALUES:
            continue
        if key == "interaction_type" and value not in INTERACTION_TYPES:
            continue
        updated[key] = _coerce_value(key, value)
        changed.append(key)
    return updated, changed


def _describe_changes(updated: dict, changed: list[str]) -> str:
    """Render actual field=value pairs for the confirmation message - never
    just field names - so the rep sees exactly what got recorded without
    needing an LLM to paraphrase it (and without the hallucination risk that
    comes with that: an LLM asked to "describe naturally" what changed, given
    only field names and no values, will invent plausible-sounding ones)."""
    parts = []
    for key in changed:
        value = updated.get(key)
        if isinstance(value, list):
            value = ", ".join(value) if value else "(none)"
        parts.append(f"{key}: {value}")
    return "; ".join(parts)


def _tokens(text: str) -> list[str]:
    return [t for t in re.split(r"[^\w]+", text.lower()) if t]


def _token_match(query: str, candidate: str) -> bool:
    """True if every word in the query appears somewhere in the candidate,
    in any order. Plain substring matching (candidate.contains(query)) fails
    for anything with a word in between - "Dr. Smith" is not a substring of
    "Dr. Emily Smith", but every token of "Dr. Smith" IS present in it."""
    q_tokens = _tokens(query)
    if not q_tokens:
        return False
    candidate_lower = candidate.lower()
    return all(t in candidate_lower for t in q_tokens)


def log_interaction(draft: dict, args: dict, db: Session) -> dict:
    updated, changed = _merge_fields(draft, args)
    if not changed:
        return {"updated_draft": draft, "message": "I didn't catch anything I could log - could you rephrase?"}
    return {"updated_draft": updated, "message": f"Logged - {_describe_changes(updated, changed)}."}


def edit_interaction(draft: dict, args: dict, db: Session) -> dict:
    updated, changed = _merge_fields(draft, args)
    if not changed:
        return {"updated_draft": draft, "message": "I couldn't match that to a known field - be more specific?"}
    return {"updated_draft": updated, "message": f"Updated - {_describe_changes(updated, changed)}."}


def clear_field(draft: dict, args: dict, db: Session) -> dict:
    field = args["field"]
    if field not in FIELD_NAMES:
        return {"updated_draft": draft, "message": f"'{field}' isn't a field on this form."}
    updated = dict(draft)
    updated[field] = None
    return {"updated_draft": updated, "message": f"Cleared {field}."}


_FOLLOWUP_SYSTEM_PROMPT = """You are a pharma sales-ops assistant. A field rep just logged an HCP \
interaction - given its full details below, suggest 2-3 concrete next-step follow-up actions.

Be specific: name the HCP, reference the actual topic/product discussed, give a realistic \
timeframe. Avoid generic filler like "follow up soon". If sentiment was negative, consider things \
like escalation or addressing a concern raised, not just another meeting.

Respond with ONLY a JSON array of short strings - no prose, no markdown fences, nothing else.
Example: ["Schedule a follow-up meeting with Dr. Sharma in 2 weeks to review Prodo-X dosing \
questions", "Email the OncoBoost Phase III reprint she asked about"]"""


def _safe_json_list(raw: str) -> list[str]:
    """The model is asked for a bare JSON array but may still wrap it in
    prose or markdown fences - extract and parse defensively, never raise."""
    if not raw:
        return []
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.split("\n", 1)[-1] if "\n" in text else text
    start, end = text.find("["), text.rfind("]")
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return []
    if isinstance(parsed, list):
        return [str(item).strip() for item in parsed if str(item).strip()]
    return []


def _rule_based_followup_suggestions(draft: dict) -> list[str]:
    """Fallback used only if the LLM call fails - keeps this tool working
    (in a degraded, generic way) even when both providers are down."""
    suggestions = []
    if draft.get("sentiment") == "Positive":
        suggestions.append("Schedule a follow-up meeting in 2 weeks")
    if draft.get("materials_shared"):
        suggestions.append("Send supporting clinical data by email")
    if draft.get("sentiment") == "Negative":
        suggestions.append("Flag for manager review before next visit")
    if not suggestions:
        suggestions.append("Schedule a check-in call next month")
    return suggestions


def suggest_followup(draft: dict, args: dict, db: Session) -> dict:
    """LLM-driven: hands the full logged interaction to the model and asks
    for tailored next steps, instead of picking from a fixed canned list.
    Falls back to the old rule-based suggestions if the LLM call fails, so
    a provider outage degrades this tool rather than breaking it outright."""
    meaningful = {k: v for k, v in draft.items() if v}
    if not meaningful:
        return {
            "updated_draft": draft,
            "message": "There's nothing logged yet to base a follow-up on - tell me about the interaction first.",
        }

    try:
        interaction_summary = json.dumps(meaningful, indent=2)
        raw = provider.generate_text(_FOLLOWUP_SYSTEM_PROMPT, f"Interaction so far:\n{interaction_summary}")
        suggestions = _safe_json_list(raw)[:3]
        if not suggestions:
            raise ValueError("LLM returned no usable suggestions")
    except Exception as e:  # noqa: BLE001 - degrade to rule-based, never fail the tool call
        logger.warning("LLM follow-up suggestion failed, using rule-based fallback: %s", e)
        suggestions = _rule_based_followup_suggestions(draft)

    updated = dict(draft)
    updated["followup_actions"] = "; ".join(suggestions)
    return {
        "updated_draft": updated,
        "message": "Suggested follow-ups: " + "; ".join(suggestions),
        "data": suggestions,
    }


def _add_attendee(updated: dict, name: str) -> dict:
    attendees = list(updated.get("attendees") or [])
    if name.lower() not in [a.lower() for a in attendees]:
        attendees.append(name)
    updated["attendees"] = attendees
    return updated


def search_hcp(draft: dict, args: dict, db: Session) -> dict:
    """Resolve against the DB when possible (so known HCPs get a real
    hcp_id and a clean canonical name). If nobody matches, don't block the
    rep - the name they gave is accepted as-is, just without a DB-backed
    hcp_id. force_new skips matching entirely - used when the rep already
    rejected the suggested matches from a previous call.

    Only one hcp_name (the primary HCP actually visited/called) is allowed
    per interaction. If a primary is already recorded and this call resolves
    to a DIFFERENT person, it's treated as an extra attendee instead of
    overwriting the primary - unless is_correction=true, meaning the rep is
    explicitly replacing the earlier one. This is a structural safeguard so
    a model mistake (calling search_hcp for someone who should've just been
    an attendee) can't silently clobber the recorded HCP."""
    query = args["query"]
    is_correction = bool(args.get("is_correction"))
    existing_primary = (draft.get("hcp_name") or "").strip()

    def _resolve_or_reroute(updated: dict, hcp_id, resolved_name: str, found_msg: str) -> dict:
        if existing_primary and not is_correction and existing_primary.lower() != resolved_name.lower():
            updated = _add_attendee(updated, resolved_name)
            return {
                "updated_draft": updated,
                "message": f"{existing_primary} is already the recorded HCP for this interaction - "
                f"added {resolved_name} to attendees instead.",
            }
        updated["hcp_id"] = hcp_id
        updated["hcp_name"] = resolved_name
        return {"updated_draft": updated, "message": found_msg}

    if args.get("force_new"):
        name = query.strip()
        return _resolve_or_reroute(dict(draft), None, name, f"Got it - recording '{name}' as the HCP.")

    all_hcps = db.query(HCP).all()
    rows = [h for h in all_hcps if _token_match(query, h.name)]
    if not rows:
        names = [h.name for h in all_hcps]
        close = get_close_matches(query, names, n=3, cutoff=0.65)
        rows = [h for h in all_hcps if h.name in close]

    if not rows:
        name = query.strip()
        return _resolve_or_reroute(
            dict(draft), None, name, f"'{query}' isn't in the system yet - added as a new HCP for this interaction."
        )

    if len(rows) == 1:
        return _resolve_or_reroute(
            dict(draft), rows[0].id, rows[0].name, f"Found {rows[0].name} ({rows[0].specialty})."
        )

    options = ", ".join(f"{r.name} ({r.specialty})" for r in rows[:5])
    return {
        "updated_draft": draft,
        "message": f"Multiple matches: {options}. Which one did you mean?",
        "data": [r.name for r in rows],
    }


def search_material(draft: dict, args: dict, db: Session) -> dict:
    """Same philosophy as search_hcp: resolve to the approved catalog when
    there's a match, but don't refuse to log something just because it's
    not in the local list yet - accept it as given, flagged as unapproved
    rather than silently pretending it matched the catalog. force_new skips
    matching, same escape hatch as search_hcp."""
    query = args["query"]
    updated = dict(draft)
    existing = list(updated.get("materials_shared") or [])

    if args.get("force_new"):
        material_name = query.strip()
        if material_name not in existing:
            existing.append(material_name)
        updated["materials_shared"] = existing
        return {"updated_draft": updated, "message": f"Got it - added '{query}' as given."}

    all_materials = db.query(Material).all()
    rows = [m for m in all_materials if _token_match(query, m.title)]
    if not rows:
        titles = [m.title for m in all_materials]
        close = get_close_matches(query, titles, n=3, cutoff=0.65)
        rows = [m for m in all_materials if m.title in close]

    if not rows:
        material_name = query.strip()
        if material_name not in existing:
            existing.append(material_name)
        updated["materials_shared"] = existing
        return {
            "updated_draft": updated,
            "message": f"'{query}' isn't in the approved catalog yet - added it as given.",
        }

    if rows[0].title not in existing:
        existing.append(rows[0].title)
    updated["materials_shared"] = existing
    return {"updated_draft": updated, "message": f"Added material: {rows[0].title}."}


TOOL_IMPLEMENTATIONS = {
    "log_interaction": log_interaction,
    "edit_interaction": edit_interaction,
    "clear_field": clear_field,
    "suggest_followup": suggest_followup,
    "search_hcp": search_hcp,
    "search_material": search_material,
}
