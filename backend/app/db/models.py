"""SQLAlchemy models: hcps + materials are the search catalogs, interactions
is where a draft finally lands once the rep hits 'Log'."""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class HCP(Base):
    __tablename__ = "hcps"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    specialty: Mapped[str] = mapped_column(String(120))
    affiliation: Mapped[str] = mapped_column(String(160))


class Material(Base):
    __tablename__ = "materials"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(160), index=True)
    type: Mapped[str] = mapped_column(String(40))  # brochure / reprint / PI / leave-behind
    product_name: Mapped[str] = mapped_column(String(120))
    approved: Mapped[bool] = mapped_column(Boolean, default=True)


class Interaction(Base):
    __tablename__ = "interactions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hcp_id: Mapped[int | None] = mapped_column(ForeignKey("hcps.id"), nullable=True)
    hcp_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    interaction_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    time: Mapped[str | None] = mapped_column(String(20), nullable=True)
    attendees: Mapped[list | None] = mapped_column(JSON, nullable=True)
    topics_discussed: Mapped[str | None] = mapped_column(Text, nullable=True)
    materials_shared: Mapped[list | None] = mapped_column(JSON, nullable=True)
    samples_distributed: Mapped[list | None] = mapped_column(JSON, nullable=True)
    sentiment: Mapped[str | None] = mapped_column(String(20), nullable=True)
    outcomes: Mapped[str | None] = mapped_column(Text, nullable=True)
    followup_actions: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    thread_id: Mapped[str] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
