"""Typed, versioned decision rules (FR-23 to FR-26).

* Exactly ONE DecisionRule is active. Its newest RuleVersion is the live configuration.
* A RuleVersion is never edited: saving creates version N+1 (FR-25).
* Routing for a case uses the version stored on its assessment (BR-08), see Step 7.
"""
from pydantic import BaseModel, Field, ValidationError, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import DecisionRule, RuleVersion

DEFAULT_RULE_NAME = "standard_credit_policy"

DEFAULT_CONFIG = {
    "max_auto_approval_limit": 50000.0,        # analysts may finalise up to this amount
    "manager_escalation_limit": 200000.0,      # above this, a manager must decide
    "high_risk_score_threshold": 0.65,         # AI risk at/above this escalates
    "max_dti_ratio": 0.50,                     # debt / income above this escalates
    "min_bureau_score": 650,                   # bureau score below this escalates (feature 2)
    "dual_approval_override_limit": 500000.0,  # overrides above this need a 2nd manager (feature 3)
    "sla_pending_hours": 48,                   # alert if a case waits longer (feature 8)
    "allow_withdrawal_submitted": True,
}


class RuleConfig(BaseModel):
    max_auto_approval_limit: float = Field(gt=0, le=100_000_000)
    manager_escalation_limit: float = Field(gt=0, le=100_000_000)
    high_risk_score_threshold: float = Field(gt=0, lt=1)
    max_dti_ratio: float = Field(gt=0, le=5)
    min_bureau_score: int = Field(ge=300, le=900)
    dual_approval_override_limit: float = Field(gt=0, le=100_000_000)
    sla_pending_hours: int = Field(ge=1, le=720)
    allow_withdrawal_submitted: bool

    @model_validator(mode="after")
    def no_contradictions(self):   # FR-24
        if self.max_auto_approval_limit > self.manager_escalation_limit:
            raise ValueError("max_auto_approval_limit cannot be greater than manager_escalation_limit")
        if self.dual_approval_override_limit < self.max_auto_approval_limit:
            raise ValueError("dual_approval_override_limit cannot be below max_auto_approval_limit")
        return self


def validate_config(raw: dict) -> dict:
    try:
        return RuleConfig(**raw).model_dump()
    except ValidationError as exc:
        details = [{"field": ".".join(str(p) for p in e["loc"]) or "rule_configuration",
                    "message": str(e["msg"]).removeprefix("Value error, ")} for e in exc.errors()]
        raise AppError(422, "INVALID_RULE_CONFIGURATION", "Rule configuration is invalid or contradictory.", details)
    except TypeError:
        raise AppError(422, "INVALID_RULE_CONFIGURATION", "rule_configuration must be an object.")


def latest_version(db: Session, rule_id) -> RuleVersion | None:
    return db.scalars(select(RuleVersion).where(RuleVersion.rule_id == rule_id)
                      .order_by(RuleVersion.version_number.desc())).first()


def get_active_rule_version(db: Session) -> RuleVersion:
    rule = db.scalars(select(DecisionRule).where(DecisionRule.is_active.is_(True))).first()
    rv = latest_version(db, rule.rule_id) if rule else None
    if rv is None:
        raise AppError(409, "NO_ACTIVE_RULE", "No active decision rule is configured. Ask an administrator.")
    return rv