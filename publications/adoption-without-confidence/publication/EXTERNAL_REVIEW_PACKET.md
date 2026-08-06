# External Review Packet

## What is being reviewed

This package makes one central, bounded claim:

> Among current AI-tool users in the 2025 Stack Overflow Developer Survey, favorable stance carries substantially more information about reported daily versus less-frequent use than accuracy trust does.

The analysis does not claim that favorable stance causes use, that increasing sentiment will increase adoption, or that Stack Overflow respondents represent all developers.

## Requested replication checks

Please attempt to reproduce:

1. The primary current-user sample of 26,102 respondents.
2. The six reported daily-use percentages by favorable stance.
3. Five-fold cross-validated AUC of 0.758 for stance alone and 0.669 for trust alone.
4. AUC of 0.704 for context plus trust, 0.790 for context plus stance, and 0.793 for the complete model.
5. The matched repeated-split comparison showing stance beating trust in all 50 splits.
6. The professional-current-user and country-grouped robustness checks.
7. The held-out calibration metrics.

## Requested adversarial review

Please challenge:

- whether the current-user restriction meaningfully reduces criterion proximity;
- whether any recode or routing decision creates mechanical separation;
- whether country grouping, complete-case selection, or professional status changes the conclusion;
- whether the article uses classification language accurately;
- whether any practical implication exceeds the evidence;
- whether the novelty statement is appropriately narrow;
- whether any denominator or citation is misleading.

## Reviewer response template

**Replication status:** Reproduced / Partially reproduced / Not reproduced  
**Material errors found:**  
**Claims that should be narrowed:**  
**Alternative explanations that deserve more emphasis:**  
**Code or documentation issues:**  
**Recommendation:** Publish / Publish with revisions / Do not publish  

## Files to begin with

- `publication/BLOG_POST.md`
- `outputs/Adoption_Without_Confidence_Open_Research_Note_2026.pdf`
- `docs/SECOND_THIRD_LOOK_AUDIT.md`
- `docs/CLAIM_LEDGER.md`
- `docs/METHODS.md`
- `analysis/sentiment_deep_dive.py`
- `outputs/sentiment/`

