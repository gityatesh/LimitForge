"""Append-only, hash-chained audit log (FR-21, FR-27, feature 4).

Each row stores   hash = SHA-256(prev_hash + its own content).
Change ANY old row and its hash no longer matches, and every later row's prev_hash breaks too.
verify_chain() walks the whole log and reports the first broken row.
"""
import hashlib
import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import AuditEvent

GENESIS_HASH = "0" * 64          # the "previous hash" of the very first row
_CHAIN_LOCK_ID = 727001          # any fixed number; used to queue concurrent writers


def _content_hash(prev_hash: str, seq: int, actor, app_id, event_type, prev_state, new_state, desc, ts) -> str:
    payload = json.dumps(
        {
            "seq": seq, "actor": str(actor) if actor else None, "application": str(app_id) if app_id else None,
            "type": event_type, "from": prev_state, "to": new_state, "desc": desc,
            "ts": ts.astimezone(timezone.utc).isoformat(),
        },
        sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256((prev_hash + payload).encode()).hexdigest()


def log_event(
    db: Session,
    event_type: str,
    description: str,
    actor_user_id: uuid.UUID | None = None,
    application_id: uuid.UUID | None = None,
    previous_state: str | None = None,
    new_state: str | None = None,
) -> AuditEvent:
    """Adds one audit row to the CURRENT transaction (the caller commits)."""
    # Only one transaction at a time may append, so two requests can't both grab the same "last hash".
    # The lock is released automatically at COMMIT/ROLLBACK.
    db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _CHAIN_LOCK_ID})
    last = db.scalars(select(AuditEvent).order_by(AuditEvent.sequence_number.desc()).limit(1)).first()
    seq = (last.sequence_number + 1) if last else 1
    prev_hash = last.hash if last else GENESIS_HASH
    ts = datetime.now(timezone.utc)
    ev = AuditEvent(
        sequence_number=seq, actor_user_id=actor_user_id, application_id=application_id,
        event_type=event_type, previous_state=previous_state, new_state=new_state,
        event_description=description, timestamp=ts, prev_hash=prev_hash,
        hash=_content_hash(prev_hash, seq, actor_user_id, application_id, event_type,
                           previous_state, new_state, description, ts),
    )
    db.add(ev)
    db.flush()  # so the next log_event in this same transaction sees this row as "last"
    return ev


def verify_chain(db: Session) -> dict:
    """Recompute every hash in order. Returns {"valid": bool, "checked": n, "first_broken_sequence": ...}."""
    prev = GENESIS_HASH
    checked = 0
    for ev in db.scalars(select(AuditEvent).order_by(AuditEvent.sequence_number)).yield_per(1000):
        expected = _content_hash(prev, ev.sequence_number, ev.actor_user_id, ev.application_id, ev.event_type,
                                 ev.previous_state, ev.new_state, ev.event_description, ev.timestamp)
        if ev.prev_hash != prev or ev.hash != expected:
            return {"valid": False, "checked": checked, "first_broken_sequence": ev.sequence_number}
        prev = ev.hash
        checked += 1
    return {"valid": True, "checked": checked, "first_broken_sequence": None}