# Second and third look: adversarial audit

## Verdict

Publish, with the revised title and boundary language. The defensible result is
not that sentiment causes adoption. It is that, among current AI-tool users in
this voluntary 2025 survey, a categorical favorable-stance item distinguishes
daily from less-frequent use much more strongly than a categorical
accuracy-trust item.

The contribution is narrower than the original framing. It is best described
as a distinct secondary analysis, not as a proven first or a new general law.

## What survived

| Test | Result | Reading |
|---|---|---|
| Current-user endpoint rates | 18.8% very unfavorable; 88.1% very favorable | Large separation remains after non-users are removed. |
| Five-fold CV | Stance AUC 0.758; trust 0.669 | Stance classifies current-use frequency better. |
| Incremental models | Context + trust 0.704; context + stance 0.790; full 0.793 | Stance adds a lot; trust adds a little, so trust is not irrelevant. |
| 50 matched splits | Mean stance-over-trust AUC difference 0.087; 2.5th-97.5th split percentiles 0.076 to 0.098; positive in 50/50 | The ranking is not a lucky split. |
| Professional current users | Stance 0.763; trust 0.675; full 0.791 | The result is not driven by non-professional respondents. |
| Country-grouped CV | Stance 0.756; trust 0.665; full 0.789 across 173 countries | Country-level leakage does not explain the pattern. |
| High-distrust current users | 17.7% daily at very unfavorable; 85.1% at very favorable | Accuracy distrust and favorable stance are not interchangeable. |
| Held-out full model | AUC 0.789; log loss 0.540; Brier 0.181; calibration slope 0.960 | Discrimination is accompanied by reasonable calibration. |

## What did not survive unchanged

1. **All-respondent headline.** The 3.4%-to-85.7% gradient mixes current users
   with non-users. It is now sensitivity evidence, not the primary claim.
2. **Linear ordinal effect.** Unsure current users report more daily use than
   indifferent current users (34.0% versus 31.5%). Categorical modeling replaces
   the single linear odds ratio.
3. **"Missing measurement dimension."** Two one-item self-reports do not
   establish latent dimensions. The release says analytically distinct.
4. **Broad novelty.** Stack Overflow and others already discuss high adoption
   alongside low trust. The defensible novelty is the exact current-user
   comparison of favorable stance with accuracy trust.
5. **Causal or managerial lever language.** Reverse causality, rationalization,
   perceived usefulness, task fit, and organizational context can all produce
   the observed association.

## Strongest counters

### Counter 1: the variables are semantically close

`AISent` asks whether respondents favor using AI tools in the workflow, while
the outcome asks how frequently they use those tools. Strong classification is
therefore not surprising and may partly be tautological.

**Response:** This objection is valid and limits novelty. The current-user
frequency comparison weakens, but does not eliminate, the overlap. The paper's
value is the empirical contrast with accuracy trust, not surprise at a
stance-use association.

### Counter 2: use may create the stance

Daily users may become favorable after useful experiences, or rationalize
their established habits.

**Response:** The data cannot order the variables in time. The release makes no
directional claim.

### Counter 3: predictive language can overstate the design

Cross-validation evaluates classification within one contemporaneous survey,
not future adoption in another population.

**Response:** The revised text uses "classification information" and reports
cross-validation and calibration without claiming operational forecasting.

### Counter 4: voluntary and incomplete response

Only 68.5% of 2025 CSV rows answered the use item, no weights are available,
and Stack Overflow respondents are not a probability sample of all developers.

**Response:** The publication treats all rates as sample-specific and reports
the complete denominator flow.

### Counter 5: single items are weak construct measures

One favorable-stance item and one accuracy-trust item may have unequal
reliability or breadth.

**Response:** The release compares survey items, not validated scales, and does
not infer a full psychology of adoption.

### Counter 6: broader outcomes look "too good"

Stance AUC rises to 0.864 for current use versus non-use and 0.915 for current
use or plans versus no plans.

**Response:** Those results are deliberately not the headline. They demonstrate
robustness while sharpening the criterion-proximity concern.

## Publication conditions

- Lead with the n=26,102 current-user result.
- Use "favorable stance," not generic "sentiment."
- Say "reported daily use" and "cross-validated classification."
- Keep the unsure/indifferent reversal visible.
- State that trust adds a small amount beyond stance and context.
- Avoid "first," "causes," "drives," "lever," and population-general claims.
- Present the full-sample gradient only as context or sensitivity evidence.

Under those conditions, the package is ready for an informed public audience.
