"""Turns raw applicant numbers into the features the model sees.
Used by BOTH training and serving, so the model always gets identical inputs."""
import numpy as np

EMPLOYMENT_STATUSES = ["SALARIED", "SELF_EMPLOYED", "STUDENT", "UNEMPLOYED"]

FEATURE_NAMES = [
    "log_income",            # 0  log(annual income), big incomes don't dominate
    "expense_ratio",         # 1  yearly expenses / income
    "dti_ratio",             # 2  existing debt / income
    "request_ratio",         # 3  requested limit / income
    "credit_history_years",  # 4
    "emp_salaried",          # 5  one-hot employment (5..8)
    "emp_self_employed",     # 6
    "emp_student",           # 7
    "emp_unemployed",        # 8
]

# Feature groups used to explain a score (reason codes). Each group = which columns + a plain-English label.
REASON_GROUPS = {
    "HIGH_DEBT_TO_INCOME": ([2], "Existing debt is high compared with income"),
    "HIGH_EXPENSE_RATIO": ([1], "Monthly expenses take a large share of income"),
    "LARGE_REQUEST_VS_INCOME": ([3], "Requested limit is large compared with income"),
    "SHORT_CREDIT_HISTORY": ([4], "Credit history is short"),
    "EMPLOYMENT_TYPE": ([5, 6, 7, 8], "Employment type carries higher risk"),
    "LOW_INCOME": ([0], "Income level is low"),
}


def build_features(requested_credit_limit: float, annual_income: float, monthly_expenses: float,
                   existing_debt: float, employment_status: str, credit_history_months: int) -> np.ndarray:
    income = max(float(annual_income), 1.0)          # avoid divide-by-zero
    emp = [1.0 if employment_status == s else 0.0 for s in EMPLOYMENT_STATUSES]
    return np.array([
        np.log1p(income),
        float(monthly_expenses) * 12.0 / income,
        float(existing_debt) / income,
        float(requested_credit_limit) / income,
        float(credit_history_months) / 12.0,
        *emp,
    ], dtype=float)