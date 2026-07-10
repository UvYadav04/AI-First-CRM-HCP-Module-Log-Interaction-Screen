"""Request/response shapes for the chat + commit endpoints."""
from pydantic import BaseModel


class ChatRequest(BaseModel):
    thread_id: str
    message: str


class CommitRequest(BaseModel):
    thread_id: str
