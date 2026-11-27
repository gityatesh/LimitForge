"""Role-aware views of an application.
Customers NEVER see AI outputs, bureau data, internal notes or override reasons (FR-09, BR-01)."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Appeal, AppStatus, ApprovalRequest, Assessment, Assignment, BureauReport, CreditApplication, Decision,
    ReviewNote, RoleName, RuleVersion, User,
)
from app.services.serializers import iso, num, serialize_profile, user_brief
from app.services.workflow import LABELS, routing_for

SYNTHETIC_NOTICE = ("Finora is an academic decision-support prototype. All data is synthetic. "
                    "Nothing here is a real or legally binding lending decision.")
ADVISORY_LABEL = "Advisory Model Recommendation"


def _decisions(db, app_id):
    return db.scalars(select(Decision).where(Decision.application_id == app_id).order_by(Decision.decided_at)).all()


def _appeal(db, app_id):
    return db.scalars(select(Appeal).where(Appeal.application_id == app_id)).first()


def can_withdraw(app: CreditApplication, config: dict | None) -> bool:
    if app.application_status in (AppStatus.DRAFT, AppStatus.NEEDS_INFORMATION):
        return True
    return app.application_status == AppStatus.SUBMITTED and bool(config and config.get("allow_withdrawal_submitted"))


def serialize_assessment(a: Assessment, rv_number: int | None) -> dict:
    return {
        "assessment_id": str(a.assessment_id), "label": ADVISORY_LABEL, "assessment_status": a.assessment_status,
        "model_name": a.model_name, "model_version": a.model_version, "rule_version_number": rv_number,
        "spending_forecast": num(a.spending_forecast), "risk_score": num(a.risk_score),
        "risk_category": a.risk_category, "recommended_credit_limit": num(a.recommended_credit_limit),
        "recommendation": a.recommendation, "reason_codes": a.reason_codes or [],
        "error_detail": a.error_detail, "assessed_at": iso(a.assessed_at),
    }


def serialize_bureau(b: BureauReport) -> dict:
    return {
        "bureau_report_id": str(b.bureau_report_id), "provider": b.provider, "report_status": b.report_status,
        "bureau_score": b.bureau_score, "score_band": b.score_band, "active_accounts": b.active_accounts,
        "delinquencies_24m": b.delinquencies_24m, "enquiries_6m": b.enquiries_6m,
        "error_detail": b.error_detail, "pulled_at": iso(b.pulled_at),
    }


def serialize_decision(d: Decision, staff: bool) -> dict:
    out = {"decision_stage": d.decision_stage, "decision_outcome": d.decision_outcome,
           "approved_credit_limit": num(d.approved_credit_limit), "customer_explanation": d.customer_explanation,
           "decided_at": iso(d.decided_at)}
    if staff:   # internal fields only for bank staff
        out.update({"is_override": d.is_override, "decision_reason": d.decision_reason,
                    "decided_by": user_brief(d.decided_by), "second_approver": user_brief(d.second_approver)})
    return out


def serialize_application_customer(db: Session, app: CreditApplication, config: dict | None) -> dict:
    info_requests = db.scalars(select(ReviewNote).where(ReviewNote.application_id == app.application_id,
                                                        ReviewNote.is_info_request.is_(True))
                               .order_by(ReviewNote.created_at)).all()
    decisions = _decisions(db, app.application_id)
    appeal = _appeal(db, app.application_id)
    return {
        "application_id": str(app.application_id),
        "application_status": app.application_status,
        "status_label": LABELS[app.application_status],
        "requested_credit_limit": num(app.requested_credit_limit),
        "application_purpose": app.application_purpose,
        "customer_response_note": app.customer_response_note,
        "submission_date": iso(app.submission_date),
        "updated_at": iso(app.updated_at),
        "info_requests": [{"message": n.note_text, "created_at": iso(n.created_at)} for n in info_requests],
        "decision": serialize_decision(decisions[-1], staff=False) if decisions else None,
        "appeal": None if appeal is None else {"appeal_status": appeal.appeal_status,
                                               "submitted_at": iso(appeal.submitted_at)},
        "can_withdraw": can_withdraw(app, config),
        "can_appeal": app.application_status == AppStatus.REJECTED and appeal is None,
        "notice": SYNTHETIC_NOTICE,
    }


def serialize_application_staff(db: Session, app: CreditApplication, viewer: User) -> dict:
    aid = app.application_id
    assessments = db.scalars(select(Assessment).where(Assessment.application_id == aid)
                             .order_by(Assessment.assessed_at.desc())).all()
    bureaus = db.scalars(select(BureauReport).where(BureauReport.application_id == aid)
                         .order_by(BureauReport.pulled_at.desc())).all()
    rv_numbers = {rv.rule_version_id: rv.version_number for rv in db.scalars(
        select(RuleVersion).where(RuleVersion.rule_version_id.in_(list({a.rule_version_id for a in assessments}))))}
    notes = db.scalars(select(ReviewNote).where(ReviewNote.application_id == aid).order_by(ReviewNote.created_at)).all()
    assignments = db.scalars(select(Assignment).where(Assignment.application_id == aid)
                             .order_by(Assignment.assigned_at)).all()
    pending = db.scalars(select(ApprovalRequest).where(ApprovalRequest.application_id == aid,
                                                       ApprovalRequest.request_status == "PENDING")).first()
    decisions = _decisions(db, aid)
    appeal = _appeal(db, aid)
    _, _, routing = routing_for(db, app)

    status = app.application_status
    is_analyst = viewer.role_name == RoleName.ANALYST
    is_manager = viewer.role_name == RoleName.MANAGER
    mine_or_free = (not is_analyst) or app.assigned_analyst_id in (None, viewer.user_id)
    reviewable = status in (AppStatus.UNDER_REVIEW, AppStatus.UNDER_APPEAL)

    return {
        "application_id": str(aid),
        "application_status": status,
        "status_label": LABELS[status],
        "requested_credit_limit": num(app.requested_credit_limit),
        "application_purpose": app.application_purpose,
        "customer_response_note": app.customer_response_note,
        "submission_date": iso(app.submission_date),
        "updated_at": iso(app.updated_at),
        "customer": {**user_brief(app.customer_profile.user), **serialize_profile(app.customer_profile)},
        "assigned_analyst": user_brief(app.assigned_analyst),
        "latest_assessment": serialize_assessment(assessments[0], rv_numbers.get(assessments[0].rule_version_id))
        if assessments else None,
        "assessments": [serialize_assessment(a, rv_numbers.get(a.rule_version_id)) for a in assessments],
        "latest_bureau_report": serialize_bureau(bureaus[0]) if bureaus else None,
        "bureau_reports": [serialize_bureau(b) for b in bureaus],
        "routing": routing,
        "review_notes": [{"review_note_id": str(n.review_note_id), "note_text": n.note_text,
                          "is_info_request": n.is_info_request, "author": user_brief(n.author),
                          "created_at": iso(n.created_at)} for n in notes],
        "assignments": [{"analyst": user_brief(a.analyst), "assigned_by": user_brief(a.assigned_by),
                         "assigned_at": iso(a.assigned_at), "assignment_status": a.assignment_status}
                        for a in assignments],
        "pending_second_approval": None if pending is None else {
            "approval_request_id": str(pending.approval_request_id), "proposed_by": user_brief(pending.proposed_by),
            "proposed_outcome": pending.proposed_outcome, "proposed_credit_limit": num(pending.proposed_credit_limit),
            "decision_reason": pending.decision_reason, "customer_explanation": pending.customer_explanation,
            "created_at": iso(pending.created_at)},
        "decisions": [serialize_decision(d, staff=True) for d in decisions],
        "appeal": None if appeal is None else {"appeal_reason": appeal.appeal_reason,
                                               "appeal_status": appeal.appeal_status,
                                               "submitted_at": iso(appeal.submitted_at)},
        "permissions": {
            "can_claim": status == AppStatus.SUBMITTED,
            "can_add_note": mine_or_free and status != AppStatus.DRAFT,
            "can_request_info": status == AppStatus.UNDER_REVIEW and mine_or_free,
            "can_reassess": status in (AppStatus.SUBMITTED, AppStatus.UNDER_REVIEW, AppStatus.NEEDS_INFORMATION,
                                       AppStatus.UNDER_APPEAL) and mine_or_free,
            "can_recommend": is_analyst and status == AppStatus.UNDER_REVIEW and mine_or_free,
            "can_decide": reviewable and (is_manager or (is_analyst and mine_or_free and routing["analyst_can_decide"]
                                                         and status == AppStatus.UNDER_REVIEW)),
            "can_override": is_manager and reviewable,
            "can_assign": is_manager and status not in AppStatus.CLOSED,
            "can_confirm_second_approval": is_manager and pending is not None
                                           and pending.proposed_by_user_id != viewer.user_id,
        },
        "notice": SYNTHETIC_NOTICE,
    }