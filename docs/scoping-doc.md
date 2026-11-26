# Engagement scoping: AI-assisted AML alert investigation

_How I'd scope this with a bank's Financial Crimes Compliance team in week one. Bracketed values are placeholders for discovery data._

## Problem
The transaction-monitoring system generates [N] alerts a month. Most are closed as legitimate after level-1 review, which takes about [X] minutes each, so the team is backlogged and SAR deadlines are tight. The goal is fewer analyst minutes per legitimate alert and better first drafts on real ones, without raising the risk of closing a real case.

## Pilot scope
| In | Out (for now) |
|---|---|
| Level-1 review for [2–3] alert types with the highest volume | Changing the detection rules or thresholds |
| Read-only evidence gathering from the case-management system, core banking and KYC | Any write access, account actions or customer contact |
| Recommend escalate/close with a verified rationale; SAR narrative drafts | Filing SARs or closing cases without a person |
| Sanctions screening explanations for analysts | Automatic clearing of sanctions hits |

## Success criteria (agreed before the data comes in)
- **Safety (gates):** 0 true-positive cases recommended for closure in a back-test on [N] historical alerts with known outcomes; 0 unverified numbers in any rationale or draft.
- **Efficiency:** analyst minutes per legitimate alert from [baseline] to [target]; share of legitimate alerts recommended for closure with an accepted rationale ≥ [X]%.
- **Quality:** SAR drafts rated "needs only minor edits" by investigators on ≥ [X]% of escalations; QA sampling of recommended closures finds 0 true positives.
- **Governance:** governance pack signed off by model risk and the BSA/AML Officer before shadow mode.

## Discovery questions
1. Which monitoring system and case-management tool? Can we get read-only APIs or a nightly extract?
2. Which alert types drive the most volume and the most "closed – no SAR" outcomes?
3. What do analysts check today on each alert type, and where do they lose the most time?
4. How are close decisions documented and QA-sampled today, and what sample rate does the BSA Officer want?
5. Where can the model run for this data (VPC, BAA/DPA, data residency), and what can be logged?
6. How does the bank's model risk function treat GenAI tools since SR 26-2, and who signs off?

## Plan
| Week | Milestone |
|---|---|
| 1–2 | Read-only data access; label [N] historical alerts with their final outcomes; agree the risk-tier floor with investigators |
| 3 | Back-test: rules baseline vs. model; gates in CI; first governance pack |
| 4–6 | Shadow mode: recommendations visible only to the project team; compare with analyst decisions daily |
| 7–8 | Assistive mode on one alert type: analysts see recommendations and drafts; QA samples every recommended closure |
| 9 | Readout to the BSA Officer: minutes saved, closure accuracy, SAR draft quality, decision on expansion |
