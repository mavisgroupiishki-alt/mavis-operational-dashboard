# Feature: Key Tasks and Read-only Bitrix Assistant

**Status:** Approved for implementation
**Date:** 2026-09-22

## Goal

Add a standalone dashboard section named **«Ключевые задачи»**. It shows the five most important active Bitrix tasks for each manually selected employee, organised by calendar week and selected month. Add a compact read-only chat that can answer operational questions against approved Bitrix/dashboard aggregates.

## Confirmed requirements

1. The section is available from the main dashboard hub.
2. Leaders add employees manually from active Bitrix users. This selection persists independently from sales managers and production experts.
3. Tasks come from all Bitrix projects where a selected person is responsible.
4. The page supports a selected month and an explicit calendar week. It provides previous/current/next week navigation and a month overview split into weeks.
5. Each employee shows exactly the five highest-priority active tasks. Priority order: overdue first, then nearest deadline, then high priority.
6. Every task links to its Bitrix task card and visibly shows title, project when available, deadline/status and why it is prioritised.
7. The AI chat is read-only. It may answer questions about dashboard/Bitrix data, surface links to supporting deals/tasks and give recommendations. It must never modify Bitrix.
8. The existing VibeCode AI key stays in the existing assistant service; it is not exposed or copied into browser code.
9. New UI uses the existing MAVIS dashboard visual language and works on iPhone.

## Non-goals

- Creating, changing, completing or assigning Bitrix tasks/deals through chat.
- Sending unrestricted CRM dumps to AI.
- Replacing Jarvis or the existing production assistant.

## Acceptance criteria

- A selected user remains selected after refresh/redeploy.
- No task with completed, declined or deferred status appears in the active top-five list.
- The order is deterministic: overdue, deadline, high priority, then newest item as a tie-breaker.
- Month/weekly navigation does not reload unrelated dashboard sections.
- Chat reports a clear supported-scope or temporary-service message when data or AI is unavailable; it never silently fabricates facts.
- No secret is present in static JavaScript, rendered HTML, logs or git changes.
