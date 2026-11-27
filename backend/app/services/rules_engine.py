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



def _f(v) -> float | None:
    return float(v) if v is not None else None


def evaluate_routing(application, profile, assessment, bureau, config: dict) -> dict:
    """Decide who may finalise this case, and WHY. Pure function: easy to unit-test.

    escalation_required  -> a Bank Manager must decide
    analyst_can_decide   -> an analyst may finalise (RBAC Condition 1)
    """
    requested = _f(application.requested_credit_limit) or 0.0
    income = _f(profile.annual_income) or 0.0
    debt = _f(profile.existing_debt) or 0.0
    dti = round(debt / income, 4) if income > 0 else None

    ai_ok = assessment is not None and assessment.assessment_status == "COMPLETED"
    risk = _f(assessment.risk_score) if ai_ok else None
    bureau_ok = bureau is not None and bureau.report_status == "COMPLETED"
    score = bureau.bureau_score if bureau_ok else None

    high_risk = risk is not None and risk >= config["high_risk_score_threshold"]
    dti_breach = dti is None or dti > config["max_dti_ratio"]
    bureau_breach = (not bureau_ok) or score is None or score < config["min_bureau_score"]

    reasons: list[str] = []
    if not ai_ok:
        reasons.append("No completed AI assessment (missing or FAILED)")
    if requested > config["manager_escalation_limit"]:
        reasons.append(f"Requested limit above manager escalation limit ({config['manager_escalation_limit']:,.0f})")
    if high_risk:
        reasons.append(f"AI risk {risk:.2f} at or above threshold {config['high_risk_score_threshold']}")
    if dti_breach:
        reasons.append(f"Debt-to-income {dti if dti is not None else 'n/a'} above maximum {config['max_dti_ratio']}")
    if not bureau_ok:
        reasons.append("Credit bureau report unavailable (FAILED)")
    elif score is None:
        reasons.append("No credit history at the bureau")
    elif score < config["min_bureau_score"]:
        reasons.append(f"Bureau score {score} below minimum {config['min_bureau_score']}")

    blockers = list(reasons)
    if requested > config["max_auto_approval_limit"]:
        blockers.append(f"Requested limit above analyst ceiling ({config['max_auto_approval_limit']:,.0f})")

    return {
        "escalation_required": bool(reasons),
        "analyst_can_decide": not blockers,
        "reasons": reasons,
        "analyst_blockers": blockers,
        "high_risk": high_risk,
        "dti_breach": dti_breach,
        "bureau_breach": bureau_breach,
        "assessment_completed": ai_ok,
        "bureau_completed": bureau_ok,
        "dti_ratio": dti,
    }