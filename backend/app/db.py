from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import DateTime, Integer, JSON, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class ExperimentRun(Base):
    __tablename__ = "experiment_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    status: Mapped[str] = mapped_column(String(24), default="completed")
    result_type: Mapped[str] = mapped_column(String(24), default="simulation")
    workload_metadata: Mapped[dict[str, Any]] = mapped_column(JSON)
    config: Mapped[dict[str, Any]] = mapped_column(JSON)
    summary: Mapped[dict[str, Any]] = mapped_column(JSON)
    result_path: Mapped[str] = mapped_column(Text)


def database_url() -> str:
    return os.getenv("DATABASE_URL", "sqlite:///./data/hybridscale.db")


def make_engine(url: str | None = None):
    actual_url = url or database_url()
    if actual_url.startswith("sqlite:"):
        Path("data").mkdir(exist_ok=True)
        return create_engine(actual_url, connect_args={"check_same_thread": False})
    return create_engine(actual_url, pool_pre_ping=True)


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(engine)


def get_session():
    with SessionLocal() as session:
        yield session


def create_run(session: Session, *, run_id: str, workload_metadata: dict[str, Any], config: dict[str, Any], summary: dict[str, Any], result_path: str) -> ExperimentRun:
    run = ExperimentRun(
        id=run_id,
        workload_metadata=workload_metadata,
        config=config,
        summary=summary,
        result_path=result_path,
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def list_runs(session: Session, limit: int = 50) -> list[ExperimentRun]:
    return list(session.scalars(select(ExperimentRun).order_by(ExperimentRun.created_at.desc()).limit(limit)))
