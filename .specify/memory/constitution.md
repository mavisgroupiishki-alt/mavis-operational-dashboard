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

### V. Durable operating configuration
Plans, selected employees and other manual dashboard settings MUST use durable storage and MUST NOT be replaced by refreshes or deployments.

### VI. Fast, bounded reads
New detail sections MUST load only their required Bitrix data, retain a last-known-good cache where feasible, and avoid unbounded CRM exports to AI.

### VII. Server-enforced access
Role restrictions MUST be applied before a response leaves the server; browser-only hiding is not access control.

## Constraints
- Bitrix secrets and URLs with tokens MUST stay in environment variables.
- Existing sales and production calculations are out of scope for the CRM audit feature.
- The CRM audit is a presentation of the agreed table, not a new Health Score model.
- AI may analyse approved server-side context but MUST NOT create, edit, close or move Bitrix entities without a distinct approved feature.

## Workflow
- Add focused tests for every integration payload before changing the dashboard view.
- Verify server payloads and browser rendering before deployment.
- Verify desktop and iPhone presentation for every new operational section.

## Governance
This constitution has priority over implementation choices. A change to a principle requires a version update.

**Version**: 1.2.0 | **Ratified**: 2026-09-10 | **Last Amended**: 2026-09-24
