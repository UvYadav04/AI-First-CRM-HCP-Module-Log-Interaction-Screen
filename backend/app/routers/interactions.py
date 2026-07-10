"""Plain REST, not agent tools. Hitting 'Log' is a normal form submit once
the draft looks right - the LLM's job is done by the time this is called."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.agent.graph import agent_graph
from app.db.database import get_db
from app.db.models import Interaction
from app.schemas.chat import CommitRequest

router = APIRouter(prefix="/interactions", tags=["interactions"])

_VALID_COLUMNS = set(Interaction.__table__.columns.keys())


@router.post("")
def commit_interaction(req: CommitRequest, db: Session = Depends(get_db)):
    config = {"configurable": {"thread_id": req.thread_id}}
    snapshot = agent_graph.get_state(config)
    draft = snapshot.values.get("draft", {}) if snapshot.values else {}
    if not draft:
        raise HTTPException(400, "Nothing has been logged on this thread yet.")

    row = Interaction(**{k: v for k, v in draft.items() if k in _VALID_COLUMNS})
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "saved": draft}


@router.get("/{interaction_id}")
def get_interaction(interaction_id: int, db: Session = Depends(get_db)):
    row = db.get(Interaction, interaction_id)
    if not row:
        raise HTTPException(404, "Not found")
    return row
