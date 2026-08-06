"""Publication analysis for favorable stance, accuracy trust, and AI use.

The primary analysis distinguishes daily from less-frequent use among
respondents who already report using AI tools. This restriction removes the
most direct user-versus-nonuser contrast from the headline result. Full-sample,
professional-status, alternative-outcome, country-grouped, calibration, and
repeated-split checks are retained as sensitivity analyses.

All results are same-wave associations and classification summaries. They are
not causal estimates or forecasts of behavior in a future survey or workplace.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.special import expit, logit
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    brier_score_loss,
    log_loss,
    roc_auc_score,
)
from sklearn.model_selection import (
    GroupKFold,
    RepeatedStratifiedKFold,
    StratifiedKFold,
    cross_validate,
    train_test_split,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from config import CSV_2023, CSV_2024, CSV_2025, check_data


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "sentiment"
OUT.mkdir(parents=True, exist_ok=True)
RANDOM_STATE = 42

USAGE_MAP = {
    "Yes, I use AI tools daily": 4,
    "Yes, I use AI tools weekly": 3,
    "Yes, I use AI tools monthly or infrequently": 2,
    "No, but I plan to soon": 1,
    "No, and I don't plan to": 0,
}
STANCE_ORDER = [
    "Very unfavorable",
    "Unfavorable",
    "Unsure",
    "Indifferent",
    "Favorable",
    "Very favorable",
]
STANCE_MAP = {label: score for score, label in enumerate(STANCE_ORDER)}
TRUST_ORDER = [
    "Highly distrust",
    "Somewhat distrust",
    "Neither trust nor distrust",
    "Somewhat trust",
    "Highly trust",
]
TRUST_MAP = {label: score for score, label in enumerate(TRUST_ORDER)}


def to_num(value):
    if pd.isna(value):
        return np.nan
    text = str(value).replace(",", "")
    if text == "Less than 1 year":
        return 0.5
    if text == "More than 50 years":
        return 51.0
    try:
        return float(text.split(";")[0])
    except ValueError:
        return np.nan


def employment_group(value):
    text = "" if pd.isna(value) else str(value)
    if "Student" in text:
        return "Student"
    if "Independent contractor" in text or "freelancer" in text:
        return "Independent"
    if "Employed" in text:
        return "Employed"
    if "Retired" in text:
        return "Retired"
    if "Not employed" in text:
        return "Not employed"
    return "Other/unknown"


def primary_role(value):
    text = "" if pd.isna(value) else str(value).lower()
    mapping = [
        ("full-stack", "Full-stack"),
        ("back-end", "Back-end"),
        ("front-end", "Front-end"),
        ("data scientist", "Data/ML"),
        ("machine learning", "Data/ML"),
        ("data engineer", "Data engineer"),
        ("devops", "DevOps/platform"),
        ("platform", "DevOps/platform"),
        ("manager", "Management"),
        ("executive", "Management"),
        ("architect", "Architect"),
        ("security", "Security"),
        ("mobile", "Mobile"),
        ("embedded", "Embedded"),
        ("qa", "QA/test"),
        ("test", "QA/test"),
        ("student", "Student"),
    ]
    for token, label in mapping:
        if token in text:
            return label
    return "Other"


def org_bucket(value):
    text = "" if pd.isna(value) else str(value)
    if "Just me" in text or "Less than 20" in text:
        return "Solo/micro"
    if "20 to 99" in text:
        return "Small"
    if "100 to 499" in text or "500 to 999" in text:
        return "Mid-market"
    if "1,000 to 4,999" in text or "5,000 to 9,999" in text:
        return "Large"
    if "10,000" in text or "More than" in text:
        return "Enterprise"
    return "Unknown"


def work_mode(value):
    text = "" if pd.isna(value) else str(value)
    if text == "Remote":
        return "Remote"
    if text == "In-person":
        return "In-person"
    if "Hybrid" in text:
        return "Hybrid"
    return "Unknown"


def three_year_context():
    """Derive descriptive trend values directly from verified survey CSVs."""
    rows = []
    for year, path in [(2023, CSV_2023), (2024, CSV_2024), (2025, CSV_2025)]:
        frame = pd.read_csv(path, low_memory=False)
        ai_respondents = frame["AISelect"].notna()
        if year < 2025:
            current_user = frame["AISelect"].eq("Yes")
        else:
            current_user = frame["AISelect"].isin(
                [
                    "Yes, I use AI tools daily",
                    "Yes, I use AI tools weekly",
                    "Yes, I use AI tools monthly or infrequently",
                ]
            )

        stance_answered = frame["AISent"].notna()
        favorable = frame["AISent"].isin(["Favorable", "Very favorable"])
        trust_column = "AIBen" if year == 2023 else "AIAcc"
        trust_answered_current = current_user & frame[trust_column].notna()
        trusting = frame[trust_column].isin(["Somewhat trust", "Highly trust"])
        distrusting = frame[trust_column].isin(
            ["Somewhat distrust", "Highly distrust"]
        )
        rows.append(
            {
                "year": year,
                "current_use_among_ai_respondents": (
                    100 * current_user.sum() / ai_respondents.sum()
                ),
                "favorable_stance": (
                    100 * favorable.sum() / stance_answered.sum()
                ),
                "trust_among_current_users": (
                    100
                    * (trusting & trust_answered_current).sum()
                    / trust_answered_current.sum()
                ),
                "distrust_among_current_users": (
                    100
                    * (distrusting & trust_answered_current).sum()
                    / trust_answered_current.sum()
                ),
                "trust_current_user_denominator": int(
                    trust_answered_current.sum()
                ),
            }
        )
    return pd.DataFrame(rows)


def wilson_interval(successes, total, alpha=0.05):
    if total == 0:
        return np.nan, np.nan
    z = 1.959963984540054
    if alpha != 0.05:
        raise ValueError("Only the 95% Wilson interval is implemented.")
    p = successes / total
    denominator = 1 + z**2 / total
    center = (p + z**2 / (2 * total)) / denominator
    half = z * np.sqrt((p * (1 - p) + z**2 / (4 * total)) / total) / denominator
    return center - half, center + half


def make_model(numeric_columns, categorical_columns):
    transformers = []
    if numeric_columns:
        transformers.append(
            (
                "numeric",
                Pipeline(
                    [
                        ("imputer", SimpleImputer(strategy="median")),
                        ("scaler", StandardScaler()),
                    ]
                ),
                numeric_columns,
            )
        )
    if categorical_columns:
        transformers.append(
            (
                "categorical",
                Pipeline(
                    [
                        ("imputer", SimpleImputer(strategy="most_frequent")),
                        (
                            "onehot",
                            OneHotEncoder(handle_unknown="ignore", min_frequency=50),
                        ),
                    ]
                ),
                categorical_columns,
            )
        )
    return Pipeline(
        [
            ("preprocessor", ColumnTransformer(transformers)),
            ("model", LogisticRegression(max_iter=3000, solver="lbfgs")),
        ]
    )


def rate_table(data, outcome_column="Daily"):
    rows = []
    for score, label in enumerate(STANCE_ORDER):
        subgroup = data[data["AISentScore"] == score]
        successes = int(subgroup[outcome_column].sum())
        total = len(subgroup)
        low, high = wilson_interval(successes, total)
        rows.append(
            {
                "favorable_stance": label,
                "stance_score": score,
                "n": total,
                "daily_n": successes,
                "daily_rate": successes / total if total else np.nan,
                "ci_low": low,
                "ci_high": high,
            }
        )
    return pd.DataFrame(rows)


def summarize_cv(name, model, X, y, cv):
    scores = cross_validate(
        model,
        X,
        y,
        cv=cv,
        scoring={
            "accuracy": "accuracy",
            "balanced_accuracy": "balanced_accuracy",
            "roc_auc": "roc_auc",
            "log_loss": "neg_log_loss",
            "brier": "neg_brier_score",
        },
        n_jobs=-1,
    )
    return {
        "model": name,
        "n": len(y),
        "prevalence": float(y.mean()),
        "accuracy_mean": float(scores["test_accuracy"].mean()),
        "accuracy_sd": float(scores["test_accuracy"].std(ddof=1)),
        "balanced_accuracy_mean": float(scores["test_balanced_accuracy"].mean()),
        "balanced_accuracy_sd": float(
            scores["test_balanced_accuracy"].std(ddof=1)
        ),
        "roc_auc_mean": float(scores["test_roc_auc"].mean()),
        "roc_auc_sd": float(scores["test_roc_auc"].std(ddof=1)),
        "log_loss_mean": float(-scores["test_log_loss"].mean()),
        "log_loss_sd": float(scores["test_log_loss"].std(ddof=1)),
        "brier_mean": float(-scores["test_brier"].mean()),
        "brier_sd": float(scores["test_brier"].std(ddof=1)),
    }


def model_table(data, y, specs, cv):
    rows = [
        {
            "model": "Majority baseline",
            "n": len(y),
            "prevalence": float(y.mean()),
            "accuracy_mean": float(max(y.mean(), 1 - y.mean())),
            "accuracy_sd": 0.0,
            "balanced_accuracy_mean": 0.5,
            "balanced_accuracy_sd": 0.0,
            "roc_auc_mean": 0.5,
            "roc_auc_sd": 0.0,
            "log_loss_mean": float(log_loss(y, np.repeat(y.mean(), len(y)))),
            "log_loss_sd": 0.0,
            "brier_mean": float(
                brier_score_loss(y, np.repeat(y.mean(), len(y)))
            ),
            "brier_sd": 0.0,
        }
    ]
    for name, (numeric, categorical) in specs.items():
        columns = numeric + categorical
        rows.append(
            summarize_cv(
                name,
                make_model(numeric, categorical),
                data[columns],
                y,
                cv,
            )
        )
    return pd.DataFrame(rows)


def calibration_summary(y_true, probabilities):
    clipped = np.clip(probabilities, 1e-6, 1 - 1e-6)
    logits = logit(clipped).reshape(-1, 1)
    calibration_model = LogisticRegression(
        C=1_000_000,
        solver="lbfgs",
        max_iter=3000,
    )
    calibration_model.fit(logits, y_true)
    bins = pd.qcut(probabilities, 10, duplicates="drop")
    check = (
        pd.DataFrame({"y": np.asarray(y_true), "p": probabilities, "bin": bins})
        .groupby("bin", observed=True)
        .agg(observed=("y", "mean"), predicted=("p", "mean"), n=("y", "size"))
    )
    weighted_gap = np.average(
        np.abs(check["observed"] - check["predicted"]),
        weights=check["n"],
    )
    return {
        "calibration_intercept": float(calibration_model.intercept_[0]),
        "calibration_slope": float(calibration_model.coef_[0, 0]),
        "mean_absolute_decile_gap": float(weighted_gap),
    }


def paired_repeated_split_comparison(data, y, specs):
    names = [
        "Context + trust",
        "Context + stance",
        "Context + trust + stance",
    ]
    cv = RepeatedStratifiedKFold(
        n_splits=5,
        n_repeats=10,
        random_state=719,
    )
    rows = []
    for split_id, (train_idx, test_idx) in enumerate(cv.split(data, y), start=1):
        row = {"split": split_id}
        for name in names:
            numeric, categorical = specs[name]
            columns = numeric + categorical
            estimator = make_model(numeric, categorical)
            estimator.fit(data.iloc[train_idx][columns], y.iloc[train_idx])
            probability = estimator.predict_proba(
                data.iloc[test_idx][columns]
            )[:, 1]
            key = name.lower().replace(" + ", "_").replace(" ", "_")
            row[f"{key}_auc"] = roc_auc_score(y.iloc[test_idx], probability)
            row[f"{key}_log_loss"] = log_loss(y.iloc[test_idx], probability)
        rows.append(row)
    scores = pd.DataFrame(rows)

    comparisons = []
    pairs = [
        ("Context + stance", "Context + trust"),
        ("Context + trust + stance", "Context + stance"),
    ]
    for left, right in pairs:
        left_key = left.lower().replace(" + ", "_").replace(" ", "_")
        right_key = right.lower().replace(" + ", "_").replace(" ", "_")
        auc_delta = scores[f"{left_key}_auc"] - scores[f"{right_key}_auc"]
        log_loss_improvement = (
            scores[f"{right_key}_log_loss"] - scores[f"{left_key}_log_loss"]
        )
        comparisons.append(
            {
                "comparison": f"{left} minus {right}",
                "splits": len(scores),
                "auc_delta_mean": float(auc_delta.mean()),
                "auc_delta_sd": float(auc_delta.std(ddof=1)),
                "auc_delta_2_5pct": float(np.quantile(auc_delta, 0.025)),
                "auc_delta_97_5pct": float(np.quantile(auc_delta, 0.975)),
                "auc_delta_positive_splits": int((auc_delta > 0).sum()),
                "log_loss_improvement_mean": float(
                    log_loss_improvement.mean()
                ),
                "log_loss_improvement_positive_splits": int(
                    (log_loss_improvement > 0).sum()
                ),
            }
        )
    return scores, pd.DataFrame(comparisons)


def main():
    check_data()
    raw = pd.read_csv(CSV_2025, low_memory=False)
    data = raw.copy()
    data["AIUsageScore"] = data["AISelect"].map(USAGE_MAP)
    data["AISentScore"] = data["AISent"].map(STANCE_MAP)
    data["AITrustScore"] = data["AIAcc"].map(TRUST_MAP)
    data["Daily"] = data["AIUsageScore"].eq(4).astype(int)
    data["WorkExpNum"] = data["WorkExp"].apply(to_num)
    data["YearsCodeNum"] = data["YearsCode"].apply(to_num)
    data["Professional"] = data["MainBranch"].eq(
        "I am a developer by profession"
    )
    data["EmploymentGroup"] = data["Employment"].apply(employment_group)
    data["PrimaryRole"] = data["DevType"].apply(primary_role)
    data["OrgBucket"] = data["OrgSize"].apply(org_bucket)
    data["WorkMode"] = data["RemoteWork"].apply(work_mode)

    answered_use = data[data["AIUsageScore"].notna()].copy()
    analytic = data.dropna(
        subset=["AIUsageScore", "AISentScore", "AITrustScore"]
    ).copy()
    current_users = analytic[analytic["AIUsageScore"] >= 2].copy()
    professional_current_users = current_users[
        current_users["Professional"]
    ].copy()
    highly_distrusting_current_users = current_users[
        current_users["AITrustScore"] == 0
    ].copy()

    item_incomplete = answered_use[
        ~answered_use.index.isin(analytic.index)
    ]
    sample_profile = pd.DataFrame(
        [
            ("2025 public CSV rows", len(raw), len(raw) / len(raw)),
            (
                "Answered AI-use item",
                len(answered_use),
                len(answered_use) / len(raw),
            ),
            (
                "Complete use, stance, and trust",
                len(analytic),
                len(analytic) / len(raw),
            ),
            (
                "Current AI users in complete-case sample",
                len(current_users),
                len(current_users) / len(analytic),
            ),
            (
                "Professional developers in complete-case sample",
                int(analytic["Professional"].sum()),
                float(analytic["Professional"].mean()),
            ),
            (
                "Professional developers among current users",
                len(professional_current_users),
                len(professional_current_users) / len(current_users),
            ),
            (
                "Excluded after answering AI-use item",
                len(item_incomplete),
                len(item_incomplete) / len(answered_use),
            ),
        ],
        columns=["sample", "n", "share_of_reference"],
    )
    sample_profile.to_csv(OUT / "sample_profile.csv", index=False)

    full_rates = rate_table(analytic)
    current_rates = rate_table(current_users)
    professional_current_rates = rate_table(professional_current_users)
    high_distrust_current_rates = rate_table(highly_distrusting_current_users)
    full_rates.to_csv(OUT / "full_sample_daily_use_by_stance.csv", index=False)
    current_rates.to_csv(
        OUT / "current_user_daily_use_by_stance.csv",
        index=False,
    )
    professional_current_rates.to_csv(
        OUT / "professional_current_user_daily_use_by_stance.csv",
        index=False,
    )
    high_distrust_current_rates.to_csv(
        OUT / "current_user_high_distrust_daily_use_by_stance.csv",
        index=False,
    )

    numeric_context = ["WorkExpNum", "YearsCodeNum"]
    categorical_context = [
        "Age",
        "Professional",
        "EmploymentGroup",
        "PrimaryRole",
        "OrgBucket",
        "WorkMode",
        "AIThreat",
        "Country",
    ]
    specs = {
        "Stance only": ([], ["AISent"]),
        "Trust only": ([], ["AIAcc"]),
        "Context": (numeric_context, categorical_context),
        "Context + trust": (
            numeric_context,
            categorical_context + ["AIAcc"],
        ),
        "Context + stance": (
            numeric_context,
            categorical_context + ["AISent"],
        ),
        "Context + trust + stance": (
            numeric_context,
            categorical_context + ["AIAcc", "AISent"],
        ),
    }
    cv = StratifiedKFold(
        n_splits=5,
        shuffle=True,
        random_state=RANDOM_STATE,
    )

    primary_y = current_users["Daily"].astype(int)
    full_y = analytic["Daily"].astype(int)
    professional_current_y = professional_current_users["Daily"].astype(int)
    primary_models = model_table(current_users, primary_y, specs, cv)
    full_models = model_table(analytic, full_y, specs, cv)
    professional_current_models = model_table(
        professional_current_users,
        professional_current_y,
        specs,
        cv,
    )
    primary_models.to_csv(
        OUT / "primary_current_user_model_comparison.csv",
        index=False,
    )
    full_models.to_csv(OUT / "full_sample_model_comparison.csv", index=False)
    professional_current_models.to_csv(
        OUT / "professional_current_user_model_comparison.csv",
        index=False,
    )

    repeated_scores, repeated_comparisons = paired_repeated_split_comparison(
        current_users,
        primary_y,
        specs,
    )
    repeated_scores.to_csv(OUT / "primary_repeated_cv_scores.csv", index=False)
    repeated_comparisons.to_csv(
        OUT / "primary_repeated_cv_comparisons.csv",
        index=False,
    )

    # Alternative outcome thresholds quantify both robustness and criterion
    # proximity. Stronger performance for adoption/nonadoption thresholds is
    # not interpreted as evidence that stance causes adoption.
    outcome_definitions = [
        (
            "full_complete_case",
            analytic,
            "daily_vs_all_other_answers",
            analytic["AIUsageScore"].eq(4).astype(int),
        ),
        (
            "full_complete_case",
            analytic,
            "weekly_or_more_vs_rest",
            analytic["AIUsageScore"].ge(3).astype(int),
        ),
        (
            "full_complete_case",
            analytic,
            "any_current_use_vs_nonuse",
            analytic["AIUsageScore"].ge(2).astype(int),
        ),
        (
            "full_complete_case",
            analytic,
            "current_or_plan_vs_no_plan",
            analytic["AIUsageScore"].ge(1).astype(int),
        ),
        (
            "current_users_only",
            current_users,
            "daily_vs_less_frequent_use",
            primary_y,
        ),
        (
            "professional_current_users_only",
            professional_current_users,
            "daily_vs_less_frequent_use",
            professional_current_y,
        ),
    ]
    robustness_rows = []
    selected_specs = [
        "Stance only",
        "Trust only",
        "Context + trust",
        "Context + stance",
        "Context + trust + stance",
    ]
    for sample_name, sample, outcome_name, target in outcome_definitions:
        for model_name in selected_specs:
            numeric, categorical = specs[model_name]
            columns = numeric + categorical
            result = summarize_cv(
                model_name,
                make_model(numeric, categorical),
                sample[columns],
                target,
                cv,
            )
            robustness_rows.append(
                {
                    "sample": sample_name,
                    "outcome": outcome_name,
                    **result,
                }
            )
    robustness = pd.DataFrame(robustness_rows)
    robustness.to_csv(
        OUT / "alternative_outcomes_and_samples.csv",
        index=False,
    )

    # Country-grouped folds use actual country as the grouping variable.
    grouped_sample = current_users[current_users["Country"].notna()].copy()
    grouped_y = grouped_sample["Daily"].astype(int)
    groups = grouped_sample["Country"]
    grouped_rows = []
    for model_name in ["Stance only", "Trust only", "Context + trust + stance"]:
        numeric, categorical = specs[model_name]
        columns = numeric + categorical
        scores = cross_validate(
            make_model(numeric, categorical),
            grouped_sample[columns],
            grouped_y,
            groups=groups,
            cv=GroupKFold(5),
            scoring={"roc_auc": "roc_auc", "log_loss": "neg_log_loss"},
            n_jobs=-1,
        )
        grouped_rows.append(
            {
                "model": model_name,
                "n": len(grouped_sample),
                "countries": int(groups.nunique()),
                "grouped_auc_mean": float(scores["test_roc_auc"].mean()),
                "grouped_auc_sd": float(scores["test_roc_auc"].std(ddof=1)),
                "grouped_log_loss_mean": float(
                    -scores["test_log_loss"].mean()
                ),
            }
        )
    pd.DataFrame(grouped_rows).to_csv(
        OUT / "primary_country_grouped_cv.csv",
        index=False,
    )

    # Held-out primary model, calibration, raw-column permutation importance,
    # and categorical model-standardized probabilities.
    full_numeric, full_categorical = specs["Context + trust + stance"]
    full_columns = full_numeric + full_categorical
    X_train, X_test, y_train, y_test = train_test_split(
        current_users[full_columns],
        primary_y,
        test_size=0.2,
        random_state=RANDOM_STATE,
        stratify=primary_y,
    )
    full_model = make_model(full_numeric, full_categorical)
    full_model.fit(X_train, y_train)
    probabilities = full_model.predict_proba(X_test)[:, 1]
    predictions = (probabilities >= 0.5).astype(int)
    heldout = {
        "sample": "current_users_only",
        "n_train": len(X_train),
        "n_test": len(X_test),
        "accuracy": float(accuracy_score(y_test, predictions)),
        "balanced_accuracy": float(
            balanced_accuracy_score(y_test, predictions)
        ),
        "roc_auc": float(roc_auc_score(y_test, probabilities)),
        "log_loss": float(log_loss(y_test, probabilities)),
        "brier": float(brier_score_loss(y_test, probabilities)),
        **calibration_summary(y_test, probabilities),
    }
    (OUT / "primary_heldout_metrics.json").write_text(
        json.dumps(heldout, indent=2),
        encoding="utf-8",
    )

    permutation = permutation_importance(
        full_model,
        X_test,
        y_test,
        scoring="roc_auc",
        n_repeats=20,
        random_state=RANDOM_STATE,
        n_jobs=-1,
    )
    permutation_results = pd.DataFrame(
        {
            "feature": full_columns,
            "mean_auc_decrease": permutation.importances_mean,
            "sd_auc_decrease": permutation.importances_std,
        }
    ).sort_values("mean_auc_decrease", ascending=False)
    permutation_results.to_csv(
        OUT / "primary_heldout_permutation_importance.csv",
        index=False,
    )

    adjusted_rows = []
    for score, label in enumerate(STANCE_ORDER):
        scenario = X_test.copy()
        scenario["AISent"] = label
        adjusted_rows.append(
            {
                "favorable_stance": label,
                "stance_score": score,
                "adjusted_mean_daily_probability": float(
                    full_model.predict_proba(scenario)[:, 1].mean()
                ),
            }
        )
    adjusted = pd.DataFrame(adjusted_rows)
    adjusted.to_csv(
        OUT / "primary_adjusted_probability_by_stance.csv",
        index=False,
    )

    # Current-user stance by trust matrix.
    rate_matrix = (
        current_users.pivot_table(
            values="Daily",
            index="AISent",
            columns="AIAcc",
            aggfunc="mean",
        )
        .reindex(index=STANCE_ORDER, columns=TRUST_ORDER)
    )
    count_matrix = (
        current_users.pivot_table(
            values="Daily",
            index="AISent",
            columns="AIAcc",
            aggfunc="count",
        )
        .reindex(index=STANCE_ORDER, columns=TRUST_ORDER)
    )
    matrix_rows = []
    for stance in STANCE_ORDER:
        for trust in TRUST_ORDER:
            matrix_rows.append(
                {
                    "favorable_stance": stance,
                    "accuracy_trust": trust,
                    "n": int(count_matrix.loc[stance, trust]),
                    "daily_rate": float(rate_matrix.loc[stance, trust]),
                }
            )
    pd.DataFrame(matrix_rows).to_csv(
        OUT / "primary_current_user_stance_by_trust.csv",
        index=False,
    )

    # Figures.
    plt.style.use("seaborn-v0_8-whitegrid")
    fig, ax = plt.subplots(figsize=(9, 5.2))
    ax.errorbar(
        current_rates["stance_score"],
        current_rates["daily_rate"] * 100,
        yerr=[
            (current_rates["daily_rate"] - current_rates["ci_low"]) * 100,
            (current_rates["ci_high"] - current_rates["daily_rate"]) * 100,
        ],
        marker="o",
        linewidth=2.2,
        capsize=4,
        label="Observed among current users",
        color="#235347",
    )
    ax.plot(
        adjusted["stance_score"],
        adjusted["adjusted_mean_daily_probability"] * 100,
        marker="s",
        linewidth=2.2,
        label="Context-adjusted probability",
        color="#E76F51",
    )
    ax.set_xticks(
        range(len(STANCE_ORDER)),
        STANCE_ORDER,
        rotation=15,
        ha="right",
    )
    ax.set_ylabel("Daily AI-tool use among current users (%)")
    ax.set_xlabel("Favorable stance toward using AI")
    ax.set_title(
        "Among current users, daily use varies sharply by favorable stance"
    )
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(OUT / "primary_current_user_stance_gradient.png", dpi=220)
    plt.close(fig)

    plot_models = primary_models[
        primary_models["model"].isin(
            [
                "Stance only",
                "Trust only",
                "Context",
                "Context + trust",
                "Context + stance",
                "Context + trust + stance",
            ]
        )
    ].sort_values("roc_auc_mean")
    fig, ax = plt.subplots(figsize=(9, 5.4))
    colors = [
        "#235347" if "stance" in name.lower() else "#9E9E9E"
        for name in plot_models["model"]
    ]
    bars = ax.barh(
        plot_models["model"],
        plot_models["roc_auc_mean"],
        xerr=plot_models["roc_auc_sd"],
        color=colors,
        capsize=3,
    )
    ax.axvline(0.5, color="#666666", linewidth=1, linestyle="--")
    ax.set_xlim(0.48, 0.83)
    ax.set_xlabel("Five-fold cross-validated ROC AUC")
    ax.set_title(
        "Favorable stance carries more frequency information than accuracy trust"
    )
    for bar, value in zip(bars, plot_models["roc_auc_mean"]):
        ax.text(
            value + 0.005,
            bar.get_y() + bar.get_height() / 2,
            f"{value:.3f}",
            va="center",
            fontsize=9,
        )
    fig.tight_layout()
    fig.savefig(OUT / "primary_current_user_model_auc.png", dpi=220)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 6.2))
    image = ax.imshow(rate_matrix.to_numpy() * 100, cmap="YlGn", vmin=0, vmax=95)
    ax.set_xticks(
        range(len(TRUST_ORDER)),
        TRUST_ORDER,
        rotation=20,
        ha="right",
    )
    ax.set_yticks(range(len(STANCE_ORDER)), STANCE_ORDER)
    ax.set_xlabel("Trust in AI-output accuracy")
    ax.set_ylabel("Favorable stance toward AI use")
    ax.set_title(
        "Among current users, stance separates daily from less-frequent use"
    )
    for row in range(len(STANCE_ORDER)):
        for col in range(len(TRUST_ORDER)):
            rate = rate_matrix.iloc[row, col]
            count = count_matrix.iloc[row, col]
            if pd.isna(rate):
                continue
            text_color = "white" if rate >= 0.62 else "#1F1F1F"
            ax.text(
                col,
                row,
                f"{rate * 100:.1f}%\n(n={int(count):,})",
                ha="center",
                va="center",
                fontsize=8.5,
                color=text_color,
            )
    colorbar = fig.colorbar(image, ax=ax, fraction=0.046, pad=0.04)
    colorbar.set_label("Daily AI-tool use among current users (%)")
    fig.tight_layout()
    fig.savefig(
        OUT / "primary_current_user_stance_trust_heatmap.png",
        dpi=220,
    )
    plt.close(fig)

    trend = three_year_context()
    trend.to_csv(OUT / "three_year_context.csv", index=False)
    fig, ax = plt.subplots(figsize=(9, 5.2))
    ax.plot(
        trend["year"],
        trend["current_use_among_ai_respondents"],
        marker="o",
        linewidth=2.4,
        label="Current use",
    )
    ax.plot(
        trend["year"],
        trend["favorable_stance"],
        marker="o",
        linewidth=2.4,
        label="Favorable stance",
    )
    ax.plot(
        trend["year"],
        trend["trust_among_current_users"],
        marker="o",
        linewidth=2.4,
        label="Trust among current users",
    )
    ax.set_xticks([2023, 2024, 2025])
    ax.set_ylim(30, 85)
    ax.set_ylabel("Respondents (%)")
    ax.set_title("Reported use rose while favorability and trust weakened")
    ax.legend(frameon=False, ncol=3, loc="lower left")
    ax.text(
        0,
        -0.19,
        "Repeated cross-sections; use wording changed. Trust uses the "
        "current-user denominator in every year.",
        transform=ax.transAxes,
        fontsize=8.5,
        color="#555555",
    )
    fig.tight_layout()
    fig.savefig(OUT / "three_year_context.png", dpi=220, bbox_inches="tight")
    plt.close(fig)

    summary = {
        "sample_profile": sample_profile.to_dict(orient="records"),
        "primary_current_user_rates": current_rates.to_dict(orient="records"),
        "full_sample_rates": full_rates.to_dict(orient="records"),
        "high_distrust_current_user_rates": high_distrust_current_rates.to_dict(
            orient="records"
        ),
        "primary_models": primary_models.to_dict(orient="records"),
        "full_sample_models": full_models.to_dict(orient="records"),
        "professional_current_user_models": professional_current_models.to_dict(
            orient="records"
        ),
        "paired_repeated_split_comparisons": repeated_comparisons.to_dict(
            orient="records"
        ),
        "heldout": heldout,
        "top_permutation_features": permutation_results.head(8).to_dict(
            orient="records"
        ),
        "adjusted_probabilities": adjusted.to_dict(orient="records"),
        "daily_rate_complete_case": float(full_y.mean()),
        "daily_rate_item_incomplete_after_use_answer": (
            float(item_incomplete["Daily"].mean())
            if len(item_incomplete)
            else np.nan
        ),
    }
    (OUT / "sentiment_analysis_summary.json").write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )

    print(f"Complete-case analytic sample: {len(analytic):,}")
    print(f"Primary current-user sample: {len(current_users):,}")
    print(f"Professional current-user sample: {len(professional_current_users):,}")
    print("\nPrimary rates:")
    print(current_rates[["favorable_stance", "n", "daily_rate", "ci_low", "ci_high"]])
    print("\nPrimary model comparison:")
    print(
        primary_models[
            ["model", "accuracy_mean", "roc_auc_mean", "log_loss_mean"]
        ]
    )
    print("\nRepeated-split comparisons:")
    print(repeated_comparisons)
    print("\nHeld-out metrics:")
    print(heldout)
    print(f"\nOutputs written to: {OUT}")


if __name__ == "__main__":
    main()
