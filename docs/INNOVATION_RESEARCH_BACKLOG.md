# Shopify Automation Lab — Customer-Pain Innovation Backlog

**Status:** future research/design backlog, not a list of proven competitor defects.
**Principle:** differentiate our app by solving *validated, recurring* problems users report about inventory/supplier synchronization apps. Avoid adding features that distract from V2 safety verification.

## Research method (after the V2 release candidate is stable)

1. Collect recent publicly available competitor app reviews and user/community feedback, with links, dates, category, and product version when available.
2. Separate objective, reproducible defects from individual preferences or one-off support situations. Never assume a review is representative.
3. Cluster recurring pain points by severity, number of independent reports, store/business impact, and ability to verify.
4. Translate each validated issue into a small proposed feature, measurable acceptance criteria, and threat model.
5. Prioritize evidence-backed fixes that improve merchant trust: clear error explanations, predictable billing, undo/reconciliation, data transparency, onboarding, API usage, inventory freshness, and supplier discrepancy reporting.
6. Prototype one feature at a time, run tests against realistic store data, and record whether it actually resolves the reported pain.

## Research hypotheses to investigate (NOT confirmed complaints)

| Hypothesis to investigate | Candidate response | Earliest appropriate stage |
|---|---|---|
| Users struggle to understand why a sync was blocked | Explainable per-SKU decision trail and remediation guidance | After V2 operational validation |
| Unexpected inventory changes damage store trust | Dry-run preview, pinned scopes, CAS, rollback/reconciliation evidence | Core V2 safety (already underway) |
| Supplier integrations fail silently or recover badly | Reliable recovery journal, explicit unknown outcome status, safe resume | V2.8C / V2.9 |
| Monitoring tools become noisy | Context-aware notification grouping and severity controls | After V2.0.0 |
| Multi-store setup or pricing confuses merchants | Guided setup, store isolation and transparent usage reporting | SaaS / multi-store stage |

Research must precede claims about any named competitor or verified market demand.
