"""FastAPI entrypoint. Run with: uvicorn app.main:app --reload"""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db.database import init_db
from app.routers import chat, interactions

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="AI-First CRM - HCP Log Interaction API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router)
app.include_router(interactions.router)


@app.on_event("startup")
def on_startup() -> None:
    init_db()  # creates tables if missing; run `python -m app.db.seed` for demo data


@app.get("/health")
def health():
    return {"status": "ok"}
