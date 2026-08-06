# Release notes - 3.1.0

## Open-publication release

Version 3.1.0 is a corrective maintenance release for the open research note
and blog package introduced in 3.0.0.

## Corrective changes in 3.1.0

- Modeled `AIAcc` categorically in every specification, matching the methods
  and codebook.
- Replaced the precomputed top-country field with raw `Country`; infrequent
  category handling is now learned inside each training fold.
- Corrected the 2023 trust denominator to current users only (n=38,888):
  trust is 48.2% and distrust is 24.2%.
- Derived the 2023-2025 context table directly from the verified official
  CSVs rather than hard-coding trend values.
- Described the geographic robustness check accurately as five-fold
  country-grouped validation, and described repeated-split endpoints as
  split percentiles rather than a population-confidence interval.

- Added a publication-ready long-form blog article in Markdown, HTML, and
  editable Word formats.
- Repackaged the validated technical report as an Open Research Note without
  changing its statistical claims.
- Added web-ready figures, figure captions, and full alt text.
- Added launch copy, newsletter copy, social metadata, pull quotes, and
  evidence-bounded responses to likely criticism.
- Added an independent replication packet and final publishing checklist.
- Designated the blog as the accessible narrative and the Open Research Note
  as the technical evidence base.

The analysis code, denominators, results, and robustness findings are unchanged
from version 2.0.0.

## Publication decision

This version is publishable as a careful secondary analysis, not as proof that
attitude causes adoption. The main result survived a stricter current-user
comparison, categorical modeling, matched repeated splits, professional-only
analysis, country-grouped validation, alternative outcomes, and held-out
calibration checks.

## What changed after the second and third review

- Made current AI-tool users (n=26,102) the primary sample, reducing the
  mechanical separation between users and non-users.
- Changed the primary outcome to daily versus less-frequent current use.
- Modeled all stance and trust responses categorically instead of assuming
  equal spacing or a linear ordinal effect.
- Exposed the small nonmonotonic reversal between unsure and indifferent.
- Added 50 matched repeated-split comparisons; stance outperformed trust in
  all 50 on ROC AUC and log loss.
- Added professional-current-user and five-fold country-grouped checks.
- Added held-out calibration, Brier score, and raw-column permutation
  importance.
- Added broader-outcome checks and explicitly treated their stronger results
  as both robustness evidence and a criterion-proximity warning.
- Quantified sample composition: 77.3% of the complete-case sample and 79.5%
  of the primary current-user sample are professional developers.
- Removed the ordinal odds-ratio headline and the unsupported phrase
  "missing measurement dimension."
- Rewrote the report, executive brief, carousel, codebook, methods, claim
  ledger, and editorial audit around the narrower claim.

## Publishable headline

> Among current AI-tool users in the 2025 Stack Overflow survey, favorable
> stance carries substantially more information about reported daily use than
> accuracy trust, although the cross-sectional result does not establish which
> came first.

## Language to avoid

Do not say stance causes adoption, that raising sentiment will raise use, that
the item is a validated psychological scale, or that the voluntary Stack
Overflow sample represents all developers. Do not call the model predictive in
the forward-looking sense; it is cross-validated classification of a
contemporaneous self-report.
