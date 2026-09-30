"""Shared, durable workflow stages for dashboard-owned tasks."""

from __future__ import annotations

from typing import Any


_DEFAULT_ROWS = (
    ("backlog", "Бэклог", "backlog", True),
    ("new", "Новая", "workflow", False),
    ("planned", "Запланирована", "workflow", False),
    ("in_progress", "В работе", "workflow", False),
    ("waiting", "Ожидание", "workflow", False),
    ("review", "На проверке", "workflow", False),
    ("ready", "Готово", "workflow", False),
    ("done", "Завершена", "done", True),
)


def default_task_statuses() -> list[dict[str, Any]]:
    return [
        {
            "id": status_id,
            "name": name,
            "kind": kind,
            "protected": protected,
            "auto_assign_profile_id": "task-profile-ira" if status_id == "review" else "",
            "sla_days": 2 if status_id == "review" else 0,
        }
        for status_id, name, kind, protected in _DEFAULT_ROWS
    ]


def normalize_task_statuses(value: Any) -> list[dict[str, Any]]:
    """Keep manually configured stages valid and preserve the two system stages."""
    if not isinstance(value, list):
        return default_task_statuses()
    defaults = {row["id"]: row for row in default_task_statuses()}
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in value:
        if not isinstance(source, dict):
            continue
        status_id = str(source.get("id") or "").strip()[:120]
        name = str(source.get("name") or "").strip()[:120]
        if not status_id or not name or status_id in seen:
            continue
        seen.add(status_id)
        base = defaults.get(status_id)
        try:
            sla_days = int(source.get("sla_days") or (2 if status_id == "review" else 0))
        except (TypeError, ValueError):
            sla_days = 0
        rows.append({
            "id": status_id,
            "name": name,
            "kind": base["kind"] if base else "workflow",
            "protected": bool(base and base["protected"]),
            "auto_assign_profile_id": str(
                source["auto_assign_profile_id"] if "auto_assign_profile_id" in source else (base or {}).get("auto_assign_profile_id") or ""
            ).strip()[:160],
            "sla_days": max(0, min(365, sla_days)),
        })
    if not rows:
        return default_task_statuses()
    for system_id in ("backlog", "done"):
        if system_id not in seen:
            rows.append(defaults[system_id])
    backlog = next(row for row in rows if row["id"] == "backlog")
    done = next(row for row in rows if row["id"] == "done")
    middle = [row for row in rows if row["id"] not in {"backlog", "done"}]
    return [backlog, *middle, done]
