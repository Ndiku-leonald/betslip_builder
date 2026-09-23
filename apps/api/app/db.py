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
    settings = get_settings()
    if url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}}
    return {
        "pool_size": settings.db_pool_size,
        "max_overflow": settings.db_max_overflow,
        "pool_timeout": settings.db_pool_timeout,
        "pool_recycle": settings.db_pool_recycle,
    }


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
