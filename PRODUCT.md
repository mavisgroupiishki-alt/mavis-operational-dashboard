# Product
<!-- impeccable:product-schema 1 -->

## Platform

Internal responsive web dashboard, installed as a PWA on iPhone or opened in a desktop browser.

## Users

MAVIS Group leaders, sales managers and production leads who use Bitrix24 every day to monitor sales, production, tasks and service quality.

## Product Purpose

Give the team one fast operational view of Bitrix24 data, manually managed plans and financial aggregates, with a direct path from a KPI to the underlying work item.

## Positioning

This is an operational command centre, not a presentation report: every section should make the next action clearer and preserve the existing Russian-language MAVIS dashboard visual system.

## Operating Context

The dashboard is checked throughout the working day on desktop and iPhone. Bitrix24 remains the source of operational records. Some targets, staffing lists and plans are intentionally edited in the dashboard and must survive refreshes and redeployments.

## Capabilities and Constraints

- FastAPI backend and vanilla JavaScript frontend deployed on Render.
- Bitrix24 is accessed server-side only.
- Persistent settings use Supabase when configured, with SQLite fallback.
- Financial aggregates come from the separate payment-schedule service.
- The assistant is read-only: it may analyse permitted dashboard/Bitrix data, but never creates, edits or deletes Bitrix entities.
- Credentials and incoming webhooks must never be exposed to the browser or committed to source control.

## Brand Commitments

- Existing MAVIS operational-dashboard visual identity: light blue background, restrained panels, strong dark type, Russian labels.
- Calm, information-dense screens with clear status and direct links to Bitrix items.
- Desktop and mobile parity for essential work.

## Evidence On Hand

- Existing deployed dashboard and user-provided screenshots.
- Existing Bitrix24-backed dashboard APIs and persistent plan/team settings.
- Existing MAVIS Bitrix assistant service configured with VibeCode AI credentials.

## Principles

- Show current, attributable facts before interpretation.
- Preserve manual plans and chosen people across refreshes and deployments.
- Keep loading non-blocking and local to the opened section.
- Make uncertainty explicit; do not invent CRM facts.
- Keep all AI actions read-only and bounded to approved data retrieval.

## Accessibility

- Keyboard-operable controls, visible focus states and semantic labels.
- Responsive layouts with no horizontal clipping on iPhone.
- Respect reduced-motion preferences.
