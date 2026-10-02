# MAVIS Operational Dashboard Constitution

## Principles

### I. Source fidelity
The dashboard MUST show the agreed source metrics and labels without silently replacing them with inferred metrics.

### II. Read-only integrations and explicit CRM actions
All external CRM and analytics integrations MUST be read-only and MUST keep credentials on the server. The sole exception is an explicitly approved, authenticated user action with a narrow server-side allowlist. Such an action MUST validate the current CRM state before changing it and MUST write an audit record with the entity, destination, time and actor.

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
- AI may analyse approved server-side context but MUST NOT create, edit, close or move Bitrix entities. An authenticated user may invoke a distinct approved action that changes a Bitrix entity only after server-side validation and audit logging.

## Workflow
- Add focused tests for every integration payload before changing the dashboard view.
- Verify server payloads and browser rendering before deployment.
- Verify desktop and iPhone presentation for every new operational section.

## Governance
This constitution has priority over implementation choices. A change to a principle requires a version update.

**Version**: 1.3.0 | **Ratified**: 2026-09-10 | **Last Amended**: 2026-10-02
