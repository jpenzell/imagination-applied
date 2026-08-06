# Publication codebook

This codebook covers the variables in the released analysis. Earlier
exploratory recodes for agents, AI complexity, and learning routes are not part
of the publication model.

## Primary outcome: `Daily`

Source: `AISelect`

Within current users, `Daily = 1` for `Yes, I use AI tools daily`; weekly,
monthly, and infrequent current use are coded `0`. Non-users and respondents
who plan to use AI are excluded from the primary analysis.

This is reported frequency, not product telemetry, workflow quality, or
productivity.

## Favorable stance: `AISent`

Source: `AISent`

| Response | Display order |
|---|---:|
| Very unfavorable | 0 |
| Unfavorable | 1 |
| Unsure | 2 |
| Indifferent | 3 |
| Favorable | 4 |
| Very favorable | 5 |

The survey item asks how favorable the respondent's stance is toward using AI
tools as part of the development workflow. The primary models use one-hot
categorical indicators. The numeric order is used only for sorting tables and
figures, not to impose equal spacing or one linear log-odds increment.

## Accuracy trust: `AIAcc`

Source: `AIAcc`

| Response | Display order |
|---|---:|
| Highly distrust | 0 |
| Somewhat distrust | 1 |
| Neither trust nor distrust | 2 |
| Somewhat trust | 3 |
| Highly trust | 4 |

The survey item asks about trust in the accuracy of AI output. The primary
models use categorical indicators. It is not treated as a synonym for
favorable stance.

## Analytic samples

| Sample | n | Role |
|---|---:|---|
| 2025 public CSV | 49,191 | Source rows |
| Answered AI-use item | 33,720 | Response denominator |
| Complete use, stance, and trust | 33,231 | Full sensitivity sample |
| Current users in complete cases | 26,102 | Primary sample |
| Professional developers in complete cases | 25,698 | Composition check |
| Professional current users | 20,760 | Robustness sample |

The positive-class daily-use rate is 59.9% in the primary sample and 47.1% in
the full complete-case sample.

## Demographic/context variables

The broader logistic models use:

- numeric: work experience and years coding;
- categorical: age, professional-developer status, employment group, primary
  role, organization-size bucket, work mode, perceived AI threat, and country
  group.

The 20 most frequent countries are retained in ordinary cross-validation; all
others are grouped as `Other`. Missing numeric values are median-imputed within
the pipeline. Missing categorical values are most-frequent-imputed.
Categorical predictors are one-hot encoded with rare levels grouped by a
minimum frequency of 50.

## Deliberate exclusions

The primary model excludes AI-agent use, workflow integration, AI task
complexity, AI-frustration items, coding-learning routes, and other downstream
behavioral variables. Those fields may be consequences or close proxies of
current use.

`AILearnHow` asks how respondents learned to code in the past year. It is not
an AI-onboarding or structured-AI-training measure and does not support a
training claim.
