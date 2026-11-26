"""Small helpers shared by all model files."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import mapped_column

# JSONB on PostgreSQL (fast, indexable), plain JSON elsewhere
JSONType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def uuid_pk():
    """UUID primary key, generated in Python (BR-06)."""
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4)