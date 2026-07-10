"""The single source of truth for what fields exist on the form. The agent,
the tool schemas, and the DB model all derive from this list so nobody can
silently invent a field that doesn't exist on screen."""
import typing
from typing import Optional

from pydantic import BaseModel


class InteractionDraft(BaseModel):
    hcp_id: Optional[int] = None
    hcp_name: Optional[str] = None
    interaction_type: Optional[str] = None
    date: Optional[str] = None
    time: Optional[str] = None
    attendees: Optional[list[str]] = None
    topics_discussed: Optional[str] = None
    materials_shared: Optional[list[str]] = None
    samples_distributed: Optional[list[str]] = None
    sentiment: Optional[str] = None
    outcomes: Optional[str] = None
    followup_actions: Optional[str] = None


def _is_list_annotation(annotation) -> bool:
    args = typing.get_args(annotation) or (annotation,)
    return any(typing.get_origin(a) is list for a in args)


FIELD_NAMES = list(InteractionDraft.model_fields.keys())
SENTIMENT_VALUES = ["Positive", "Neutral", "Negative"]
INTERACTION_TYPES = ["Meeting", "Call", "Email", "Conference"]

# Fields that must always be a list. Derived from the model itself (not
# hardcoded) so it can't drift out of sync if the schema changes later.
LIST_FIELDS = {
    name for name, info in InteractionDraft.model_fields.items() if _is_list_annotation(info.annotation)
}
