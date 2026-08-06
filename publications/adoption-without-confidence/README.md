# Adoption Without Confidence? — Open Release

Reproducible analysis and publication assets for:

> **Adoption Without Confidence? Favorable Stance, Accuracy Trust, and
> Reported AI-Use Frequency in the 2025 Stack Overflow Survey**  
> Josh Penzell, Imagination Applied Open Research Series (2026)

The project uses the 2023-2025 Stack Overflow Developer Survey public CSVs for
descriptive context. The primary analysis compares daily with less-frequent use
among 26,102 current AI-tool users who answered the 2025 use, stance, and
accuracy-trust items.

## The contribution

Stack Overflow has already reported the broad headline that AI use rose while
trust weakened. This project asks a narrower question: among people already
using AI tools, does favorable stance carry different information about
reported use frequency than accuracy trust?

- Daily use ranges from 18.8% among very unfavorable current users to 88.1%
  among very favorable current users.
- The six categories are modeled categorically. The middle categories are not
  perfectly monotonic: unsure respondents report more daily use than
  indifferent respondents (34.0% versus 31.5%).
- Five-fold cross-validated ROC AUC is 0.758 for stance alone and 0.669 for
  trust alone.
- Adding stance to context + trust raises AUC from 0.704 to 0.793; adding trust
  to context + stance raises it from 0.790 to 0.793.
- The stance advantage appears in all 50 matched repeated-split comparisons,
  in professional-current-user and country-grouped checks, and alongside good
  held-out calibration.
- The result is associative. The items are single self-reports, the outcome is
  self-reported frequency, and favorable stance may partly reflect experience,
  usefulness, role fit, or rationalization after use.

## Repository map

```text
analysis/
  config.py                 Data paths and integrity metadata
  sentiment_deep_dive.py    Primary analysis and robustness checks
  build_carousel.py         Eight-page LinkedIn carousel

data/
  README_data.md            Official downloads and full SHA-256 hashes
  2023/ 2024/ 2025/         Place public CSVs here; files are not distributed

docs/
  METHODS.md                Model, denominator, and robustness details
  CODEBOOK.md               Publication-variable definitions
  DENOMINATORS.md           Cross-year denominator reconciliation
  CLAIM_LEDGER.md           What the evidence does and does not support
  EDITORIAL_AUDIT.md        Disposition of claims from the earlier draft
  SECOND_THIRD_LOOK_AUDIT.md Adversarial review and publication decision

outputs/
  sentiment/                Machine-readable results and figures
  Adoption_Without_Confidence_Open_Research_Note_2026.*
  Adoption_Without_Confidence_Research_Report_2026.*
  Favorable_Stance_Is_Not_Accuracy_Trust_Executive_Brief_2026.*
  Favorable_Stance_Is_Not_Accuracy_Trust_LinkedIn_Carousel_2026.pdf

publication/
  BLOG_POST.md              Canonical publication-ready article
  LAUNCH_KIT.md             Metadata, social copy, alt text, and responses
  EXTERNAL_REVIEW_PACKET.md Independent replication and critique request
  PUBLISHING_CHECKLIST.md   Release and correction checklist
  *.docx / *.html           Editable and web-ready blog formats
  assets/                   Web-ready figures

publication_source/
  build_publication.py      Word report and executive-brief builder
```

## Reproduce

Python 3.12 was used for the released run.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python analysis/verify_data.py
python analysis/sentiment_deep_dive.py
python publication_source/build_publication.py
python analysis/build_carousel.py
python publication/build_public_assets.py
```

By default, the analysis expects each public CSV at
`data/<year>/survey_results_public.csv`. To keep the source data elsewhere, set
`STACKOVERFLOW_DATA_ROOT` to a directory containing the `2023`, `2024`, and
`2025` folders.

## Interpretation boundary

The primary outcome is daily versus less-frequent reported use among current
AI-tool users. The analysis does not observe telemetry, task quality,
productivity, tool reliability, employer policy, or temporal ordering.
Predictive discrimination within a cross-section is not a causal effect.

Broader outcomes that include non-users produce stronger stance discrimination.
That is evidence of robustness, but it is also a criterion-proximity warning:
the stance item explicitly asks about using AI in the workflow. The
current-user comparison is therefore the primary and more conservative test.

## Data and license

Code is released under the MIT License. Stack Overflow survey data are not
redistributed; download them from the official archive and follow Stack
Overflow's terms. Full file hashes appear in `data/README_data.md`.

## Citation

```text
Penzell, J. (2026). Adoption Without Confidence? Favorable Stance, Accuracy
Trust, and Reported AI-Use Frequency in the 2025 Stack Overflow Survey.
Imagination Applied Open Research Series.
```
