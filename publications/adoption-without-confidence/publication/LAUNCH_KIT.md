# Publication Launch Kit

## Canonical publication

**Blog title:** The Developers Using AI Without Trusting It  
**Subtitle:** What 26,102 current users in Stack Overflow's 2025 survey reveal about adoption, sentiment, and calibrated skepticism  
**Recommended URL slug:** `developers-using-ai-without-trusting-it`  
**Primary CTA:** Read the open research note and inspect the reproducibility package.

## Search and social metadata

**SEO title:** Developers Are Using AI Without Trusting It | Josh Penzell  
**Meta description:** A secondary analysis of 26,102 current AI-tool users finds favorable stance toward AI carries substantially more information about daily use than trust in output accuracy.  
**Open Graph title:** Developers Are Using AI Without Trusting It  
**Open Graph description:** Trust in accuracy is not the same thing as willingness to use AI. New analysis of Stack Overflow's 2025 survey separates the two.  
**Suggested social image text:** `AI USE ≠ AI TRUST`

## Primary LinkedIn post

Developers do not need to trust AI output to use AI every day.

That is the most interesting result I found after reanalyzing Stack Overflow's 2025 Developer Survey.

Among 26,102 current AI-tool users, daily use ranged from 18.8% among people with a very unfavorable stance toward AI to 88.1% among the very favorable.

But confidence in output accuracy told us much less.

In cross-validation:

- Favorable stance alone: AUC 0.758
- Accuracy trust alone: AUC 0.669
- Context + stance: AUC 0.790
- Context + trust: AUC 0.704

Even among current users who *highly distrusted* AI accuracy, daily use ranged from 17.7% to 85.1% across the stance categories.

This does **not** prove that favorable sentiment causes adoption. Use may shape stance. The stance question is also closer to the behavior than the accuracy question is.

But it does show that trust, favorability, use, and calibrated reliance are not interchangeable.

The organizational goal should not be maximum trust. It should be useful, appropriately skeptical, well-verified use.

I published the full analysis as an open research note, with code, robustness checks, denominators, and the strongest counterarguments included.

[BLOG LINK]

[RESEARCH NOTE / REPOSITORY LINK]

#AI #AIAdoption #FutureOfWork #SoftwareDevelopment #OrganizationalChange

## Short LinkedIn version

AI adoption may not have a trust problem. It may have a measurement problem.

Among 26,102 current AI-tool users in Stack Overflow's 2025 survey, favorable stance classified daily use substantially better than trust in output accuracy.

That does not make trust irrelevant—and it does not prove causation. It means “Do people trust AI?” and “Does AI have a place in their workflow?” are different questions.

The goal is not maximum trust. It is calibrated reliance.

[BLOG LINK]

## Newsletter teaser

**Subject:** Developers are using AI without trusting it

If trust were the price of admission, the AI boom would make no sense. I analyzed 26,102 current AI-tool users in Stack Overflow's 2025 Developer Survey and found that favorable stance toward AI carried substantially more information about daily use than confidence in output accuracy. The result survives multiple robustness checks—but it also has a strong counterargument. Here is what the data show, what they do not show, and why organizations should stop treating adoption and trust as the same metric.

## Pull quotes

1. “The goal should not be maximum trust. It should be calibrated reliance.”
2. “Accuracy trust alone is an incomplete account of how people orient toward using AI.”
3. “Access is not adoption. Favoring use is not trusting output. Frequent use is not calibrated reliance.”
4. “Some of the people most skeptical of AI accuracy were also among its most frequent users.”
5. “Trust may govern how people use AI more than whether they use it.”

## Figure captions and alt text

### Figure 1 — Daily use by favorable stance

**Caption:** Reported daily use among 26,102 current AI-tool users rises sharply across favorable-stance categories. The middle categories are not perfectly ordered.

**Alt text:** Bar chart showing daily AI use at 18.8% for very unfavorable current users, 20.1% for unfavorable, 34.0% for unsure, 31.5% for indifferent, 62.0% for favorable, and 88.1% for very favorable.

### Figure 2 — Model comparison

**Caption:** Five-fold cross-validated ROC AUC for classifying daily versus less-frequent use among current AI-tool users.

**Alt text:** Bar chart showing ROC AUC of 0.758 for stance alone, 0.669 for trust alone, 0.627 for context alone, 0.704 for context plus trust, 0.790 for context plus stance, and 0.793 for the complete model.

## Responses to likely comments

### “Isn't this tautological?”

Partly—and the research note says so directly. Favoring AI use is closer to use frequency than trusting output accuracy is. The contribution is the size and stability of that contrast even after restricting the analysis to current users, not the discovery that attitude and behavior are related.

### “Correlation is not causation.”

Correct. The analysis is cross-sectional and makes no causal claim. Use may create favorable stance, stance may influence use, or both may be shaped by usefulness, role fit, policy, and experience.

### “AUC does not prove business importance.”

Also correct. AUC measures classification within this sample. Accuracy trust may be crucial for safety, verification, and over-reliance even though it adds little information about frequency after stance is known.

### “Stack Overflow respondents are not all developers.”

Correct. This is a voluntary sample. The paper reports sample-specific estimates, separates professional developers as a robustness check, and does not claim population prevalence.

### “Why call it stance instead of sentiment?”

Stack Overflow calls the item sentiment, but it is a single question about favoring AI use in the workflow—not a validated multi-item affect scale. “Favorable stance” is the more precise analytic label.

### “So should organizations make people more positive about AI?”

The data do not support that intervention. They support measuring stance, trust, behavior, verification burden, and outcomes separately—and testing changes longitudinally.

## Release-day sequence

1. Publish the blog post.
2. Publish the repository and immutable release.
3. Upload or link the open research note.
4. Replace every `[BLOG LINK]` and `[RESEARCH NOTE / REPOSITORY LINK]` placeholder.
5. Post the primary LinkedIn copy with Figure 1 or the carousel.
6. Pin a comment linking directly to methods and code.
7. Invite replication and corrections.

## Correction statement

This is an open research note. Corrections, replication attempts, and methodological criticism are welcome. Material revisions will be documented in the repository release notes and reflected in the versioned research note.

