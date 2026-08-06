# Methods

## Design and question

This is a secondary analysis of repeated cross-sectional Stack Overflow
Developer Survey public-use CSVs. The 2023-2025 data provide
denominator-aware context; the main analysis uses 2025 only.

The primary question is: among current AI-tool users, how much classification
information about daily versus less-frequent reported use is carried by
favorable stance, accuracy trust, and respondent context?

The goal is construct separation and contemporaneous classification, not
causal estimation or forward prediction.

## Samples

The 2025 public CSV contains 49,191 rows; 33,720 answered `AISelect`, and
33,231 also answered `AISent` and `AIAcc`. The primary sample is the 26,102
current users within those complete cases. Its daily-use prevalence is 59.9%.

Of the complete cases, 25,698 (77.3%) are professional developers. Of primary
current users, 20,760 (79.5%) are professional developers. No survey weights
are available.

## Outcome and descriptive analysis

The primary outcome is daily versus weekly, monthly, or infrequent current
use. Non-users and respondents who only plan to use AI are excluded from the
primary analysis.

Daily-use proportions are reported across all six stance categories with 95%
Wilson intervals. The categories are not forced to be linear: unsure current
users report slightly more daily use than indifferent current users. A
stance-by-trust matrix reports rates and cell sizes.

## Predictive comparisons

Seven logistic specifications use one-hot categorical representations for the
stance and trust items:

1. majority baseline;
2. stance only;
3. trust only;
4. demographic/context variables;
5. context + trust;
6. context + stance;
7. context + trust + stance.

The main table uses the same five stratified folds (shuffle seed 42). Reported
metrics are accuracy, balanced accuracy, ROC AUC, log loss, and Brier score.
Preprocessing occurs within each fold: median imputation and standardization
for numeric variables; most-frequent imputation and one-hot encoding for
categorical variables.

## Repeated-split comparison

The six non-baseline models are evaluated on 50 matched stratified 80/20
splits. Comparisons use the same held-out respondents within each repetition.
The empirical 2.5th and 97.5th percentiles summarize split-to-split
variability; they are not a population-confidence interval for the survey
sampling process.

## Grouped and subgroup checks

To probe geographic memorization, five-fold `GroupKFold` validation uses
country as the grouping variable across the 173 countries represented in the
primary complete-case sample. Each country appears in only one test fold.
Country is passed to the preprocessing pipeline as a raw categorical field;
infrequent-category handling is therefore learned inside each training fold.
Professional current users are analyzed separately with identical model
definitions. These are robustness checks, not claims of population
representativeness or formal measurement invariance.

## Held-out calibration and importance

An 80/20 stratified split (seed 42) evaluates the complete model. The release
reports ROC AUC, accuracy, log loss, Brier score, calibration intercept,
calibration slope, and mean absolute predicted-versus-observed gap across
deciles. Raw-column permutation importance repeats 20 permutations. Because
predictors are correlated, importance is interpreted jointly with nested-model
comparisons.

## Alternative outcomes and samples

Sensitivity analyses include:

- the full complete-case sample with daily use versus all other answers;
- weekly-or-more versus less use or non-use;
- any current use versus non-use;
- current use or plans versus no plans; and
- professional current users only.

Broader outcomes produce stronger discrimination by stance. This supports
robustness but also raises criterion proximity because the stance item asks
about using AI tools in the development workflow. The current-user frequency
comparison is therefore primary.

## Interpretation

The analysis cannot determine whether stance precedes use, follows experience
with use, reflects usefulness or role fit, or partly rationalizes established
behavior. Both predictors and outcome are contemporaneous self-reports.
Common-method bias, selection into the voluntary survey, item routing, and
complete-case selection remain. Neither stance nor trust is a validated
multi-item scale.
