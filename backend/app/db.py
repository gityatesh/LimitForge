"""Database engine + session. Every request gets its own session (see get_db)."""
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    """Parent class of every table."""


engine = create_engine(settings.database_url, pool_pre_ping=True, pool_size=20, max_overflow=30)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()