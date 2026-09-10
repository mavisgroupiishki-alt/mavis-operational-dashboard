# MAVIS Operational Dashboard Constitution

## Principles

### I. Source fidelity
The dashboard MUST show the agreed source metrics and labels without silently replacing them with inferred metrics.

### II. Read-only integrations
All external CRM and analytics integrations MUST be read-only and MUST keep credentials on the server.

### III. Explainable operational data
Every attention item MUST retain its source date, problem, priority, scope, and a direct CRM link when one exists.

### IV. Honest availability
Unavailable data MUST be shown as unavailable; it MUST NOT be rendered as zero or fabricated.

## Constraints
- Bitrix secrets and URLs with tokens MUST stay in environment variables.
- Existing sales and production calculations are out of scope for the CRM audit feature.
- The CRM audit is a presentation of the agreed table, not a new Health Score model.

## Workflow
- Add focused tests for every integration payload before changing the dashboard view.
- Verify server payloads and browser rendering before deployment.

## Governance
This constitution has priority over implementation choices. A change to a principle requires a version update.

**Version**: 1.0.0 | **Ratified**: 2026-09-10 | **Last Amended**: 2026-09-10
