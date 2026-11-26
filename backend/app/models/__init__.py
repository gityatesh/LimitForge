"""Importing this package registers every table with SQLAlchemy (Alembic needs that)."""
from app.models.applications import Assessment, Assignment, BureauReport, CreditApplication, ReviewNote
from app.models.decisions import Appeal, ApprovalRequest, Decision
from app.models.enums import (
    AccountStatus, AppStatus, DecisionStage, EmploymentStatus, RoleName, ServiceStatus,
)
from app.models.rules import DecisionRule, RuleVersion
from app.models.system import Alert, AuditEvent, EmailOutbox, Notification
from app.models.users import BankStatement, CustomerProfile, PasswordResetToken, Role, User

__all__ = [
    "AccountStatus", "Alert", "Appeal", "AppStatus", "ApprovalRequest", "Assessment", "Assignment",
    "AuditEvent", "BankStatement", "BureauReport", "CreditApplication", "CustomerProfile", "Decision",
    "DecisionRule", "DecisionStage", "EmailOutbox", "EmploymentStatus", "Notification",
    "PasswordResetToken", "ReviewNote", "Role", "RoleName", "RuleVersion", "ServiceStatus", "User",
]