# Editorial audit

The package was rebuilt around the strongest defensible finding rather than
cosmetically editing the earlier manuscript.

| Earlier element | Problem | Disposition |
|---|---|---|
| "Adoption up, trust down" as the novelty claim | Stack Overflow had already published the broad pattern. | Reframed as context; the contribution is the narrower stance-versus-trust comparison. |
| All respondents as the primary denominator | Much of the separation could reflect current users versus non-users. | Current users are now primary; the outcome is daily versus less-frequent use. |
| Linear ordinal stance effect and odds-ratio headline | Assumed equal spacing and obscured an unsure/indifferent reversal. | Primary models now use six categorical indicators; the odds-ratio headline was removed. |
| "Missing measurement dimension" | Too strong for two single survey items. | Replaced with "analytically distinct" and explicit construct-validity limits. |
| One five-fold CV run | Did not reveal split sensitivity. | Added 50 matched repeated splits and empirical percentile ranges. |
| Random-country folds | Could exploit stable country patterns. | Added five-fold country-grouped validation over 173 countries. |
| Sample described loosely as developers | The complete cases include non-professional respondents. | Quantified composition and added a professional-current-user analysis. |
| Structured AI-learning pathway claim | `AILearnHow` describes how respondents learned to code, not AI onboarding. | Removed. |
| Five behavioral archetypes | The forced five-cluster solution was not adequately supported. | Removed. |
| Association rules | Rules largely combined nearby or behaviorally entangled survey items. | Removed. |
| Random-forest Gini importance | Impurity importance can mislead with correlated predictors. | Replaced with nested categorical logistic comparisons and held-out raw-column permutation importance. |
| Cross-year trust headline | The trust-item denominator changed. | Harmonized to current users and labeled as repeated cross-sections. |
| Causal language | Cross-sectional self-reports do not establish temporal order. | Replaced with associative language and explicit reverse-causality and rationalization alternatives. |

The legacy exploratory scripts are intentionally excluded so stale claims
cannot be mistaken for the released analysis.
