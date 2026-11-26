"""Fixed sets of values. Stored in the database as plain text (VARCHAR)."""


class RoleName:
    CUSTOMER = "CUSTOMER"
    ANALYST = "ANALYST"
    MANAGER = "MANAGER"
    ADMIN = "ADMIN"
    ALL = (CUSTOMER, ANALYST, MANAGER, ADMIN)


class AppStatus:
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    NEEDS_INFORMATION = "NEEDS_INFORMATION"
    PENDING_SECOND_APPROVAL = "PENDING_SECOND_APPROVAL"   # maker-checker (feature 3)
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    UNDER_APPEAL = "UNDER_APPEAL"                         # appeal (feature 9)
    WITHDRAWN = "WITHDRAWN"

    ALL = (DRAFT, SUBMITTED, UNDER_REVIEW, NEEDS_INFORMATION, PENDING_SECOND_APPROVAL,
           APPROVED, REJECTED, UNDER_APPEAL, WITHDRAWN)
    # Still being worked on by the bank
    OPEN = (SUBMITTED, UNDER_REVIEW, NEEDS_INFORMATION, PENDING_SECOND_APPROVAL, UNDER_APPEAL)
    # No further moves (REJECTED can still go to UNDER_APPEAL once, checked in the workflow)
    CLOSED = (APPROVED, REJECTED, WITHDRAWN)


class AccountStatus:
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class EmploymentStatus:
    ALL = ("SALARIED", "SELF_EMPLOYED", "STUDENT", "UNEMPLOYED")


class ServiceStatus:
    """Result of calling an external service (LimitForge, bureau)."""
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class DecisionStage:
    INITIAL = "INITIAL"
    APPEAL = "APPEAL"