from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def resolve_database_url(url: str) -> str:
    if url.startswith("sqlite:///./"):
        project_root = Path(__file__).resolve().parents[3]
        return f"sqlite:///{(project_root / url.removeprefix('sqlite:///./')).as_posix()}"
    return url


def _engine_kwargs(url: str) -> dict:
    return {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}


_settings = get_settings()
_database_url = resolve_database_url(_settings.database_url)
engine = create_engine(_database_url, pool_pre_ping=True, future=True, **_engine_kwargs(_database_url))
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
