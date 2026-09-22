# Manual Key Tasks and Durable Chat State Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the incorrectly implemented Bitrix task feed with manually created dashboard tasks, and prevent the dashboard chat draft and conversation from being lost on background refreshes or tab reloads.

**Architecture:** Keep the existing Bitrix user picker only for choosing responsible employees. Store dashboard-owned task records in the existing durable `Storage` KV backend and expose small CRUD endpoints. Persist the current tab's chat state in `sessionStorage`, with the DOM as a rendering target rather than the source of truth.

**Tech Stack:** Python, FastAPI, vanilla JavaScript, SQLite/Supabase KV, unittest.

## Global Constraints

- Key tasks are created, viewed and deleted only in the dashboard; do not create, modify, complete or delete Bitrix tasks.
- Employee selection may continue to use the existing read-only Bitrix user list.
- A destructive task delete must require a browser confirmation.
- Preserve task records in the existing configured durable storage backend.
- Keep chat contents only in the current browser tab using `sessionStorage`.

---

## File Structure

- Modify: `app/storage.py` — validate and persist dashboard-owned key-task records.
- Modify: `app/key_tasks.py` — group manual records by employee and week.
- Modify: `app/main.py` — replace the Bitrix task read path with manual task CRUD API routes.
- Modify: `app/static/app.js` — render task creation/deletion UI and durable chat state.
- Modify: `app/static/index.html` — add the key-task editor dialog.
- Modify: `app/static/styles.css` — small styles for task controls.
- Modify: `tests/test_key_tasks.py` — test manual task board grouping.
- Create: `tests/test_manual_key_task_storage.py` — test durable add/delete task storage.
- Modify: `tests/test_refresh_interaction_preservation.py` — assert persistent chat draft/history logic.

### Task 1: Persist manual key tasks

**Files:** `app/storage.py`, `tests/test_manual_key_task_storage.py`

- [ ] Write tests that create a task, read it back, delete it and reject a blank title.
- [ ] Add `manual_key_tasks`, `add_manual_key_task` and `remove_manual_key_task` storage methods using the existing KV backend.
- [ ] Run focused storage tests.

### Task 2: Serve and group dashboard-owned tasks

**Files:** `app/key_tasks.py`, `app/main.py`, `tests/test_key_tasks.py`

- [ ] Update the pure board builder to accept manual records and preserve their deadline, priority and owner.
- [ ] Add `POST /api/key-tasks` and `DELETE /api/key-tasks/{task_id}`.
- [ ] Make `GET /api/key-tasks` read durable manual records without calling Bitrix task APIs.
- [ ] Run the task tests.

### Task 3: Restore manual controls and durable chat state

**Files:** `app/static/app.js`, `app/static/index.html`, `app/static/styles.css`, `tests/test_refresh_interaction_preservation.py`

- [ ] Add task creation UI with title, responsible employee, due date and priority.
- [ ] Add per-task delete control with explicit confirmation.
- [ ] Keep the selected employees separately editable.
- [ ] Store chat open state, draft and recent history in `sessionStorage`; update the stored draft on every keystroke and render from this state after refresh.
- [ ] Run frontend source-contract tests and syntax checks.

### Task 4: Verify end-to-end contracts

**Files:** all changed files

- [ ] Run `python -m unittest discover -s tests -v` using the project Python environment.
- [ ] Run `python -m py_compile app/main.py app/storage.py app/key_tasks.py`.
- [ ] Run `git diff --check` and inspect the diff to confirm that no user files are touched.
