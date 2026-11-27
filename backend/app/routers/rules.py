"""FR-23 to FR-26: admins create, version and activate decision rules.
Analysts and managers may READ the active rule so the UI can explain routing."""
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.core.errors import conflict, not_found
from app.db import get_db
from app.models import DecisionRule, RoleName, RuleVersion, User
from app.schemas.rules import RuleCreateIn, RuleUpdateIn
from app.services import audit
from app.services.rules_engine import get_active_rule_version, latest_version, validate_config
from app.services.serializers import iso, serialize_rule_version

router = APIRouter(prefix="/rules", tags=["rules"])
ADMIN = require_roles(RoleName.ADMIN)


def _rule_dict(db: Session, r: DecisionRule) -> dict:
    latest = latest_version(db, r.rule_id)
    count = db.scalar(select(func.count()).select_from(RuleVersion).where(RuleVersion.rule_id == r.rule_id))
    return {"rule_id": str(r.rule_id), "rule_name": r.rule_name, "description": r.description,
            "is_active": r.is_active, "created_at": iso(r.created_at), "version_count": count,
            "latest_version": serialize_rule_version(latest) if latest else None}


def _deactivate_others(db: Session, keep_id) -> None:
    for other in db.scalars(select(DecisionRule).where(DecisionRule.is_active.is_(True),
                                                       DecisionRule.rule_id != keep_id)).all():
        other.is_active = False


@router.get("")
def list_rules(user: User = Depends(ADMIN), db: Session = Depends(get_db)):
    return [_rule_dict(db, r) for r in db.scalars(select(DecisionRule).order_by(DecisionRule.created_at)).all()]


@router.get("/active")
def active_rule(user: User = Depends(require_roles(RoleName.ANALYST, RoleName.MANAGER, RoleName.ADMIN)),
                db: Session = Depends(get_db)):
    rv = get_active_rule_version(db)
    return {"rule_name": db.get(DecisionRule, rv.rule_id).rule_name, **serialize_rule_version(rv)}


@router.post("", status_code=201)
def create_rule(body: RuleCreateIn, user: User = Depends(ADMIN), db: Session = Depends(get_db)):
    if db.scalars(select(DecisionRule).where(DecisionRule.rule_name == body.rule_name)).first():
        raise conflict("RULE_NAME_IN_USE", "A rule with this name already exists.")
    config = validate_config(body.rule_configuration)
    rule = DecisionRule(rule_name=body.rule_name, description=body.description, is_active=body.activate,
                        created_by_user_id=user.user_id)
    db.add(rule)
    db.flush()
    if body.activate:
        _deactivate_others(db, rule.rule_id)
    db.add(RuleVersion(rule_id=rule.rule_id, version_number=1, rule_configuration=config,
                       created_by_user_id=user.user_id))
    audit.log_event(db, "RULE_CREATED", f"Rule '{rule.rule_name}' v1 created", actor_user_id=user.user_id)
    db.commit()
    return _rule_dict(db, rule)


@router.put("/{rule_id}")
def update_rule(rule_id: uuid.UUID, body: RuleUpdateIn, user: User = Depends(ADMIN), db: Session = Depends(get_db)):
    """Saving never edits a version: it adds version N+1 (FR-25)."""
    rule = db.get(DecisionRule, rule_id)
    if rule is None:
        raise not_found("Rule")
    config = validate_config(body.rule_configuration)
    latest = latest_version(db, rule_id)
    if latest and latest.rule_configuration == config and body.description in (None, rule.description):
        raise conflict("NO_CHANGES", "The configuration is identical to the current version.")
    if body.description is not None:
        rule.description = body.description
    number = (latest.version_number if latest else 0) + 1
    db.add(RuleVersion(rule_id=rule_id, version_number=number, rule_configuration=config,
                       created_by_user_id=user.user_id))
    changed = {k: (latest.rule_configuration.get(k) if latest else None, v)
               for k, v in config.items() if not latest or latest.rule_configuration.get(k) != v}
    audit.log_event(db, "RULE_UPDATED", f"Rule '{rule.rule_name}' saved as v{number}; changed: {changed}",
                    actor_user_id=user.user_id)
    db.commit()
    return _rule_dict(db, rule)


@router.patch("/{rule_id}/activate")
def activate_rule(rule_id: uuid.UUID, user: User = Depends(ADMIN), db: Session = Depends(get_db)):
    """FR-26: exactly one active rule. Activating one switches the others off; history is kept."""
    rule = db.get(DecisionRule, rule_id)
    if rule is None:
        raise not_found("Rule")
    if rule.is_active:
        raise conflict("ALREADY_ACTIVE", "This rule is already active.")
    rule.is_active = True
    _deactivate_others(db, rule.rule_id)
    audit.log_event(db, "RULE_ACTIVATED", f"Rule '{rule.rule_name}' activated", actor_user_id=user.user_id)
    db.commit()
    return _rule_dict(db, rule)


@router.get("/{rule_id}/versions")
def rule_versions(rule_id: uuid.UUID, user: User = Depends(ADMIN), db: Session = Depends(get_db)):
    if db.get(DecisionRule, rule_id) is None:
        raise not_found("Rule")
    versions = db.scalars(select(RuleVersion).where(RuleVersion.rule_id == rule_id)
                          .order_by(RuleVersion.version_number.desc())).all()
    return [serialize_rule_version(v) for v in versions]