# Implementation Plan

1. Add durable `key_task_team` storage and Bitrix task/user query helpers.
2. Implement a cached FastAPI key-tasks API with month/week filters and deterministic ranking.
3. Add a hub card, standalone section, employee picker, task list and mobile styles.
4. Add a small chat panel that calls a protected read-only gateway in the existing assistant service. Gateway authentication will use a dedicated server-side shared token configured at deployment; no secret is copied to browser code.
5. Implement bounded assistant tools for aggregates and permitted drill-downs, plus tests and browser verification.

## Risk controls

- Limit task retrieval to selected users and active statuses.
- Limit chat context size and allow only fixed server-side query types.
- Render deployment/configuration is a separate user-authorised step after local verification.
