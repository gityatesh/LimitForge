"""The application state machine and the assessment flow (FR-08, FR-11..16, BR-03, BR-05, BR-09).

Functions here only ADD to the session. Routers commit once per request, so a state change,
its assessment and its audit rows are saved together or not at all (NFR-10).
"""
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import conflict
from app.models import AppStatus as S
from app.models import Assessment, BureauReport, CreditApplication, CustomerProfile, RuleVersion, User
from app.services import audit
from app.services.alerts import raise_alert
from app.services.clients import (
    BureauRequest, LimitForgeRequest, ServiceError, call_bureau, call_limitforge,
)
from app.services.rules_engine import evaluate_routing, get_active_rule_version

# The ONLY allowed moves. Anything else -> HTTP 409 (FR-16).
TRANSITIONS: dict[str | None, set[str]] = {
    None: {S.DRAFT, S.SUBMITTED},
    S.DRAFT: {S.SUBMITTED, S.WITHDRAWN},
    S.SUBMITTED: {S.UNDER_REVIEW, S.WITHDRAWN},
    S.UNDER_REVIEW: {S.NEEDS_INFORMATION, S.APPROVED, S.REJECTED, S.PENDING_SECOND_APPROVAL},
    S.NEEDS_INFORMATION: {S.UNDER_REVIEW, S.WITHDRAWN},
    # maker-checker: 2nd manager confirms (final) or declines (back to where it came from)
    S.PENDING_SECOND_APPROVAL: {S.APPROVED, S.REJECTED, S.UNDER_REVIEW, S.UNDER_APPEAL},
    S.REJECTED: {S.UNDER_APPEAL},                      # once only; checked in the appeal service
    S.UNDER_APPEAL: {S.APPROVED, S.REJECTED, S.PENDING_SECOND_APPROVAL},
    S.APPROVED: set(),
    S.WITHDRAWN: set(),
}

LABELS = {
    S.DRAFT: "Draft", S.SUBMITTED: "Submitted", S.UNDER_REVIEW: "Under Review",
    S.NEEDS_INFORMATION: "Needs Information", S.PENDING_SECOND_APPROVAL: "Pending Second Approval",
    S.APPROVED: "Approved", S.REJECTED: "Rejected", S.UNDER_APPEAL: "Under Appeal", S.WITHDRAWN: "Withdrawn",
}


def can_transition(current: str | None, new: str) -> bool:
    return new in TRANSITIONS.get(current, set())


def assert_transition(current: str | None, new: str) -> None:
    if not can_transition(current, new):
        raise conflict("INVALID_STATE_TRANSITION",
                       f"Cannot move an application from {LABELS.get(current, 'new')} to {LABELS.get(new, new)}.")


def change_state(db: Session, app: CreditApplication, new_state: str, actor: User | None,
                 event_type: str, description: str) -> None:
    previous = app.application_status
    assert_transition(previous, new_state)
    app.application_status = new_state
    app.updated_at = datetime.now(timezone.utc)
    db.flush()   # make sure the application row exists before the audit row points at it
    audit.log_event(db, event_type, description, actor_user_id=actor.user_id if actor else None,
                    application_id=app.application_id, previous_state=previous, new_state=new_state)


# ------------------------------------------------------------------ assessment
def latest_assessment(db: Session, application_id: uuid.UUID) -> Assessment | None:
    return db.scalars(select(Assessment).where(Assessment.application_id == application_id)
                      .order_by(Assessment.assessed_at.desc())).first()


def latest_bureau(db: Session, application_id: uuid.UUID) -> BureauReport | None:
    return db.scalars(select(BureauReport).where(BureauReport.application_id == application_id)
                      .order_by(BureauReport.pulled_at.desc())).first()


def _call_both(lf_req: LimitForgeRequest, bu_req: BureauRequest):
    """Call LimitForge and the bureau AT THE SAME TIME (two threads).
    Total wait = the slower of the two, not the sum. Each result is either a response or a ServiceError."""
    def safe(fn, req):
        try:
            return fn(req)
        except ServiceError as exc:
            return exc
    with ThreadPoolExecutor(max_workers=2) as pool:
        lf_future = pool.submit(safe, call_limitforge, lf_req)
        bu_future = pool.submit(safe, call_bureau, bu_req)
        return lf_future.result(), bu_future.result()


def run_assessment(db: Session, app: CreditApplication, profile: CustomerProfile, actor: User | None,
                   reason: str = "submission") -> tuple[Assessment, BureauReport]:
    """Pull the bureau report + AI assessment and store both. Never raises on service failure (FR-14)."""
    rv = get_active_rule_version(db)
    actor_id = actor.user_id if actor else None
    lf_out, bu_out = _call_both(
        LimitForgeRequest(
            application_id=str(app.application_id), requested_credit_limit=float(app.requested_credit_limit),
            annual_income=float(profile.annual_income), monthly_expenses=float(profile.monthly_expenses),
            existing_debt=float(profile.existing_debt), employment_status=profile.employment_status,
            credit_history_months=int(profile.credit_history_months)),
        BureauRequest(
            customer_reference=profile.customer_reference, annual_income=float(profile.annual_income),
            existing_debt=float(profile.existing_debt), employment_status=profile.employment_status,
            credit_history_months=int(profile.credit_history_months)),
    )

    # --- bureau result
    if isinstance(bu_out, ServiceError):
        bureau = BureauReport(application_id=app.application_id, provider="FinoraMockBureau",
                              report_status="FAILED", error_detail=str(bu_out))
        audit.log_event(db, "BUREAU_FAILED", f"Bureau pull failed ({reason}): {bu_out}",
                        actor_user_id=actor_id, application_id=app.application_id)
        raise_alert(db, "BUREAU_FAILED", f"Credit bureau failed: {bu_out}", "CRITICAL", app.application_id)
    else:
        bureau = BureauReport(application_id=app.application_id, provider=bu_out.provider, report_status="COMPLETED",
                              bureau_score=bu_out.bureau_score, score_band=bu_out.score_band,
                              active_accounts=bu_out.active_accounts, delinquencies_24m=bu_out.delinquencies_24m,
                              enquiries_6m=bu_out.enquiries_6m)
        audit.log_event(db, "BUREAU_PULLED", f"Bureau report ({reason}): score {bu_out.bureau_score} "
                        f"({bu_out.score_band})", actor_user_id=actor_id, application_id=app.application_id)
    db.add(bureau)

    # --- AI result
    if isinstance(lf_out, ServiceError):
        assessment = Assessment(application_id=app.application_id, rule_version_id=rv.rule_version_id,
                                model_name="limitforge-ensemble", model_version="unknown",
                                assessment_status="FAILED", error_detail=str(lf_out))
        audit.log_event(db, "ASSESSMENT_FAILED", f"LimitForge failed ({reason}): {lf_out}. Held for human review.",
                        actor_user_id=actor_id, application_id=app.application_id)
        raise_alert(db, "ASSESSMENT_FAILED", f"LimitForge assessment failed: {lf_out}", "CRITICAL",
                    app.application_id)
    else:
        assessment = Assessment(
            application_id=app.application_id, rule_version_id=rv.rule_version_id, model_name=lf_out.model_name,
            model_version=lf_out.model_version, assessment_status="COMPLETED",
            spending_forecast=lf_out.spending_forecast, risk_score=lf_out.risk_score,
            risk_category=lf_out.risk_category, recommended_credit_limit=lf_out.recommended_credit_limit,
            recommendation=lf_out.recommendation, reason_codes=[r.model_dump() for r in lf_out.reason_codes])
        audit.log_event(db, "ASSESSMENT_COMPLETED",
                        f"Advisory assessment ({reason}): risk {lf_out.risk_score:.2f} {lf_out.risk_category}, "
                        f"recommended {lf_out.recommended_credit_limit:,.0f} ({lf_out.recommendation}), "
                        f"rules v{rv.version_number}", actor_user_id=actor_id, application_id=app.application_id)
        if lf_out.risk_score >= rv.rule_configuration["high_risk_score_threshold"]:
            raise_alert(db, "HIGH_RISK_APPLICATION", f"High-risk application ({lf_out.risk_score:.2f}).",
                        "WARNING", app.application_id)
    db.add(assessment)
    db.flush()
    return assessment, bureau


def routing_for(db: Session, app: CreditApplication) -> tuple[Assessment | None, BureauReport | None, dict]:
    """Routing uses the rule version stored on the LATEST assessment (BR-08)."""
    assessment = latest_assessment(db, app.application_id)
    bureau = latest_bureau(db, app.application_id)
    rv = db.get(RuleVersion, assessment.rule_version_id) if assessment else get_active_rule_version(db)
    routing = evaluate_routing(app, app.customer_profile, assessment, bureau, rv.rule_configuration)
    routing["rule_version_number"] = rv.version_number
    routing["dual_approval_override_limit"] = rv.rule_configuration["dual_approval_override_limit"]
    return assessment, bureau, routing