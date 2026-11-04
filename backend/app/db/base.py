import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


def new_id() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    def __init__(self, **kwargs):
        # Assign ids at construction (not flush) so audit rows and links can reference them.
        for key, value in kwargs.items():
            setattr(self, key, value)
        if "id" in self.__mapper__.columns and getattr(self, "id", None) is None:
            self.id = new_id()


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def make_engine(url: str):
    kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
    return create_engine(url, **kwargs)


engine = make_engine(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
