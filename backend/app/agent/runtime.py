"""Runs the accountability graph: picks the checkpointer, starts and resumes threads."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.types import Command
from sqlalchemy.orm import Session

from app.agent.graph import AgentContext, build_graph
from app.agent.workflow import thread_for
from app.config import get_settings
from app.db.models import ReportingRequest

log = logging.getLogger(__name__)

_checkpointer: BaseCheckpointSaver | None = None
_compiled = None


def _make_checkpointer() -> BaseCheckpointSaver:
    url = get_settings().database_url
    if url.startswith("postgresql"):
        from langgraph.checkpoint.postgres import PostgresSaver
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool

        conninfo = url.replace("postgresql+psycopg://", "postgresql://", 1)
        pool = ConnectionPool(conninfo, max_size=5, kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row})
        saver = PostgresSaver(pool)
        saver.setup()
        return saver
    from langgraph.checkpoint.sqlite import SqliteSaver

    db_path = url.removeprefix("sqlite:///")
    path = Path(db_path).with_suffix(".checkpoints.sqlite") if db_path else Path("checkpoints.sqlite")
    return SqliteSaver(sqlite3.connect(path, check_same_thread=False))


def set_checkpointer(saver: BaseCheckpointSaver | None) -> None:
    """Test hook: use an in-memory saver."""
    global _checkpointer, _compiled
    _checkpointer, _compiled = saver, None


def graph():
    global _checkpointer, _compiled
    if _compiled is None:
        if _checkpointer is None:
            _checkpointer = _make_checkpointer()
        _compiled = build_graph().compile(checkpointer=_checkpointer)
    return _compiled


def _config(db: Session, req: ReportingRequest) -> dict:
    return {"configurable": {"thread_id": thread_for(db, req).graph_thread_id}}


def start_cycle(db: Session, req: ReportingRequest) -> None:
    """Run the graph up to its first pause. Idempotent: an existing thread is left alone."""
    db.flush()
    cfg = _config(db, req)
    if graph().get_state(cfg).created_at is None:
        graph().invoke({"request_id": req.id}, cfg, context=AgentContext(db=db))


def dispatch(db: Session, req: ReportingRequest, event: dict) -> None:
    """Resume the paused graph with an NGO action."""
    start_cycle(db, req)
    cfg = _config(db, req)
    if not graph().get_state(cfg).next:
        log.info("Reporting request %s graph already finished; ignoring %s", req.id, event.get("type"))
        return
    graph().invoke(Command(resume=event), cfg, context=AgentContext(db=db))
