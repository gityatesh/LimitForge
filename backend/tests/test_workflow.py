"""Step 7 unit tests: the state machine (FR-16, BR-05) and routing (RBAC Condition 1, feature 2).
No database, no HTTP: pure logic (NFR-12)."""
import itertools
from types import SimpleNamespace

import pytest

from app.core.errors import AppError
from app.models import AppStatus as S
from app.services.rules_engine import DEFAULT_CONFIG, evaluate_routing
from app.services.workflow import TRANSITIONS, assert_transition, can_transition

VALID = {
    (None, S.DRAFT), (None, S.SUBMITTED),
    (S.DRAFT, S.SUBMITTED), (S.DRAFT, S.WITHDRAWN),
    (S.SUBMITTED, S.UNDER_REVIEW), (S.SUBMITTED, S.WITHDRAWN),
    (S.UNDER_REVIEW, S.NEEDS_INFORMATION), (S.UNDER_REVIEW, S.APPROVED), (S.UNDER_REVIEW, S.REJECTED),
    (S.UNDER_REVIEW, S.PENDING_SECOND_APPROVAL),
    (S.NEEDS_INFORMATION, S.UNDER_REVIEW), (S.NEEDS_INFORMATION, S.WITHDRAWN),
    (S.PENDING_SECOND_APPROVAL, S.APPROVED), (S.PENDING_SECOND_APPROVAL, S.REJECTED),
    (S.PENDING_SECOND_APPROVAL, S.UNDER_REVIEW), (S.PENDING_SECOND_APPROVAL, S.UNDER_APPEAL),
    (S.REJECTED, S.UNDER_APPEAL),
    (S.UNDER_APPEAL, S.APPROVED), (S.UNDER_APPEAL, S.REJECTED), (S.UNDER_APPEAL, S.PENDING_SECOND_APPROVAL),
}
ALL_PAIRS = list(itertools.product([None, *S.ALL], S.ALL))


def test_transition_table_is_exactly_the_designed_one():
    assert {(a, b) for a, bs in TRANSITIONS.items() for b in bs} == VALID


@pytest.mark.parametrize("src,dst", [p for p in ALL_PAIRS if p not in VALID], ids=str)
def test_every_other_transition_is_409(src, dst):
    with pytest.raises(AppError) as exc:
        assert_transition(src, dst)
    assert exc.value.status_code == 409


@pytest.mark.parametrize("src", [s for s in S.ALL if s not in (S.UNDER_REVIEW, S.PENDING_SECOND_APPROVAL,
                                                                 S.UNDER_APPEAL)])
def test_final_decisions_only_from_review_states(src):
    assert not can_transition(src, S.APPROVED)


def test_approved_and_withdrawn_are_dead_ends():
    assert TRANSITIONS[S.APPROVED] == TRANSITIONS[S.WITHDRAWN] == set()


# ---------------- routing ----------------
def case(requested=30000, income=1_200_000, debt=100_000, ai="COMPLETED", risk=0.1, bureau="COMPLETED", score=760):
    app = SimpleNamespace(requested_credit_limit=requested)
    profile = SimpleNamespace(annual_income=income, existing_debt=debt)
    a = SimpleNamespace(assessment_status=ai, risk_score=risk if ai == "COMPLETED" else None)
    b = SimpleNamespace(report_status=bureau, bureau_score=score if bureau == "COMPLETED" else None)
    return evaluate_routing(app, profile, a, b, DEFAULT_CONFIG)


def test_small_safe_case_analyst_can_decide():
    r = case()
    assert r["analyst_can_decide"] and not r["escalation_required"]


def test_medium_amount_needs_manager_but_is_not_escalated():
    r = case(requested=120_000)
    assert not r["analyst_can_decide"] and not r["escalation_required"]


@pytest.mark.parametrize("kwargs,flag_text", [
    ({"requested": 250_000}, "escalation limit"),
    ({"risk": 0.8}, "AI risk"),
    ({"income": 100_000, "debt": 90_000}, "Debt-to-income"),
    ({"score": 600}, "Bureau score 600"),
    ({"score": None}, "No credit history"),
    ({"bureau": "FAILED"}, "bureau report unavailable"),
    ({"ai": "FAILED"}, "No completed AI assessment"),
])
def test_each_escalation_reason(kwargs, flag_text):
    r = case(**kwargs)
    assert r["escalation_required"] and not r["analyst_can_decide"]
    assert any(flag_text.lower() in reason.lower() for reason in r["reasons"])