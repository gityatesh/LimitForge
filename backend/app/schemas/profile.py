"""Input validation for the customer's financial profile (FR-05)."""
from typing import Literal

from pydantic import BaseModel, Field

EmploymentLiteral = Literal["SALARIED", "SELF_EMPLOYED", "STUDENT", "UNEMPLOYED"]


class ProfileIn(BaseModel):
    annual_income: float = Field(ge=0, le=9_999_999_999)
    monthly_expenses: float = Field(ge=0, le=9_999_999_999)
    existing_debt: float = Field(ge=0, le=9_999_999_999)
    employment_status: EmploymentLiteral
    credit_history_months: int = Field(ge=0, le=600)