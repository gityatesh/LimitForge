"""Trains LimitForge on SYNTHETIC data and saves models/limitforge.joblib.

Honest note (say this in the viva): we have no real bank data, so we generate 20,000 fake
applicants from a documented formula below. The model learns that formula. Its accuracy says
nothing about real credit risk. Finora only ever uses it as ADVICE (BR-03).

Run:  python train.py
"""
import os

import joblib
import numpy as np
from sklearn.ensemble import GradientBoostingClassifier, GradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, roc_auc_score
from sklearn.model_selection import train_test_split

from app.features import EMPLOYMENT_STATUSES, FEATURE_NAMES, build_features

MODEL_VERSION = "2.0.0"
SEED = 42          # fixed seed: training gives the SAME model every time (reproducible)
N = 20_000

EMP_PROBS = [0.55, 0.25, 0.12, 0.08]
BASE_INCOME = {"SALARIED": 900_000, "SELF_EMPLOYED": 1_100_000, "STUDENT": 150_000, "UNEMPLOYED": 80_000}
EMP_RISK = {"SALARIED": -0.4, "SELF_EMPLOYED": 0.0, "STUDENT": 0.6, "UNEMPLOYED": 1.3}


def generate(rng):
    emp = rng.choice(EMPLOYMENT_STATUSES, size=N, p=EMP_PROBS)
    income = np.array([rng.lognormal(np.log(BASE_INCOME[e]), 0.5) for e in emp])
    expenses = income / 12 * rng.uniform(0.15, 0.85, N)
    debt = income * rng.gamma(1.2, 0.25, N)
    history = rng.integers(0, 240, N)
    requested = income * rng.uniform(0.02, 0.6, N)

    X, defaulted, spend = [], [], []
    for i in range(N):
        x = build_features(requested[i], income[i], expenses[i], debt[i], emp[i], int(history[i]))
        # The "ground truth" risk formula the synthetic world follows
        logit = (-2.4 + 2.2 * x[2] + 2.0 * max(x[1] - 0.4, 0) + 1.8 * x[3]
                 - 0.12 * min(x[4], 15) + EMP_RISK[emp[i]])
        p_default = 1 / (1 + np.exp(-logit))
        X.append(x)
        defaulted.append(rng.random() < p_default)
        spend.append(expenses[i] * 0.45 + income[i] / 12 * 0.05 + rng.normal(0, expenses[i] * 0.05))
    return np.array(X), np.array(defaulted, dtype=int), np.maximum(np.array(spend), 0)


def main():
    rng = np.random.default_rng(SEED)
    X, y, spend = generate(rng)
    Xtr, Xte, ytr, yte, str_, ste = train_test_split(X, y, spend, test_size=0.2, random_state=SEED)

    risk_model = GradientBoostingClassifier(random_state=SEED, n_estimators=150, max_depth=3).fit(Xtr, ytr)
    spend_model = GradientBoostingRegressor(random_state=SEED, n_estimators=150, max_depth=3).fit(Xtr, str_)

    auc = roc_auc_score(yte, risk_model.predict_proba(Xte)[:, 1])
    mae = mean_absolute_error(ste, spend_model.predict(Xte))
    # "Reference applicant" for reason codes: the typical LOW-risk applicant in the training data
    low_risk = Xtr[risk_model.predict_proba(Xtr)[:, 1] < 0.2]
    reference = np.median(low_risk, axis=0)
    reference[5:9] = [1, 0, 0, 0]  # reference employment = salaried

    print(f"[train] synthetic hold-out AUC = {auc:.3f}, spending MAE = {mae:,.0f}")
    os.makedirs("models", exist_ok=True)
    joblib.dump({
        "risk_model": risk_model, "spend_model": spend_model, "feature_names": FEATURE_NAMES,
        "reference": reference, "model_name": "limitforge-ensemble", "model_version": MODEL_VERSION,
        "metrics": {"synthetic_holdout_auc": round(auc, 4), "spending_mae": round(mae, 2)},
    }, "models/limitforge.joblib")
    print("[train] saved models/limitforge.joblib")


if __name__ == "__main__":
    main()