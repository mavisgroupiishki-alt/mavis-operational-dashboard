"""Deterministic, read-only task selection for the key-tasks dashboard."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Iterable
from zoneinfo import ZoneInfo


ACTIVE_STATUSES = {"1", "2", "3", "4"}
HIGH_PRIORITIES = {"2", "HIGH", "Y", "YES", "TRUE"}


def task_status(task: dict[str, Any]) -> str:
    return str(task.get("REAL_STATUS") or task.get("STATUS") or "").strip()


def is_active_task(task: dict[str, Any]) -> bool:
    return task_status(task) in ACTIVE_STATUSES


def is_high_priority(task: dict[str, Any]) -> bool:
    return str(task.get("PRIORITY") or "").strip().upper() in HIGH_PRIORITIES


def parse_task_date(raw: Any, tz: ZoneInfo) -> datetime | None:
    if not raw:
        return None
    value = str(raw).strip()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.strptime(value[:10], "%Y-%m-%d")
        except ValueError:
            return None
    return parsed.replace(tzinfo=tz) if parsed.tzinfo is None else parsed.astimezone(tz)


def monday(value: date) -> date:
    return value - timedelta(days=value.weekday())


def task_sort_key(task: dict[str, Any], now: datetime, tz: ZoneInfo):
    """Overdue -> nearest deadline -> high priority -> newest created -> stable id."""
    deadline = parse_task_date(task.get("DEADLINE"), tz)
    created = parse_task_date(task.get("CREATED_DATE"), tz)
    is_overdue = bool(deadline and deadline < now)
    deadline_value = deadline.timestamp() if deadline else float("inf")
    created_value = -(created.timestamp() if created else 0)
    return (
        0 if is_overdue else 1,
        deadline_value,
        0 if is_high_priority(task) else 1,
        created_value,
        str(task.get("ID") or task.get("id") or ""),
    )


def task_reason(task: dict[str, Any], now: datetime, tz: ZoneInfo) -> str:
    deadline = parse_task_date(task.get("DEADLINE"), tz)
    if deadline and deadline < now:
        return "Просрочена"
    if deadline:
        return "Ближайший дедлайн"
    if is_high_priority(task):
        return "Высокий приоритет"
    return "Без дедлайна"


def task_payload(task: dict[str, Any], name: str, portal: str, now: datetime, tz: ZoneInfo) -> dict[str, Any]:
    deadline = parse_task_date(task.get("DEADLINE"), tz)
    created = parse_task_date(task.get("CREATED_DATE"), tz)
    task_id = str(task.get("ID") or task.get("id") or "")
    return {
        "id": task_id,
        "title": str(task.get("TITLE") or "Без названия"),
        "responsible": name,
        "status": task_status(task),
        "deadline": deadline.isoformat() if deadline else "",
        "created": created.isoformat() if created else "",
        "group_id": str(task.get("GROUP_ID") or ""),
        "group_name": str(task.get("GROUP_NAME") or ""),
        "priority": "high" if is_high_priority(task) else "normal",
        "reason": task_reason(task, now, tz),
        "task_url": f"{portal}/company/personal/user/0/tasks/task/view/{task_id}/" if task_id else "",
    }


def build_key_tasks(
    rows_by_user: dict[str, Iterable[dict[str, Any]]],
    members: list[dict[str, str]],
    portal: str,
    now: datetime,
    timezone: str,
    limit: int = 5,
) -> dict[str, Any]:
    tz = ZoneInfo(timezone)
    people = []
    all_tasks = []
    weekly_people: dict[str, list[dict[str, Any]]] = {}
    for member in members:
        user_id = str(member.get("id") or "")
        name = str(member.get("name") or user_id or "Без имени")
        source = [task for task in rows_by_user.get(user_id, []) if is_active_task(task)]
        ranked = sorted(source, key=lambda task: task_sort_key(task, now, tz))[:limit]
        tasks = [task_payload(task, name, portal, now, tz) for task in ranked]
        people.append({"id": user_id, "name": name, "tasks": tasks, "active_count": len(source)})
        all_tasks.extend(tasks)
        by_member_week: dict[str, list[dict[str, Any]]] = {}
        for task in source:
            deadline = parse_task_date(task.get("DEADLINE"), tz)
            if not deadline:
                continue
            key = monday(deadline.date()).isoformat()
            by_member_week.setdefault(key, []).append(task)
        for key, week_rows in by_member_week.items():
            weekly_people.setdefault(key, []).append({
                "id": user_id,
                "name": name,
                "tasks": [task_payload(task, name, portal, now, tz) for task in sorted(week_rows, key=lambda task: task_sort_key(task, now, tz))[:limit]],
                "active_count": len(week_rows),
            })

    by_week: dict[str, list[dict[str, Any]]] = {}
    no_deadline = []
    for task in all_tasks:
        deadline = parse_task_date(task.get("deadline"), tz)
        if not deadline:
            no_deadline.append(task)
            continue
        key = monday(deadline.date()).isoformat()
        by_week.setdefault(key, []).append(task)
    for rows in by_week.values():
        rows.sort(key=lambda task: (task.get("deadline") or "", task.get("title") or ""))
    no_deadline.sort(key=lambda task: (task.get("priority") != "high", task.get("title") or ""))
    for key, rows in weekly_people.items():
        present = {row["id"] for row in rows}
        rows.extend({"id": member["id"], "name": member["name"], "tasks": [], "active_count": 0} for member in members if member["id"] not in present)
        rows.sort(key=lambda row: row["name"].casefold())
    return {"people": people, "weeks": by_week, "weekly_people": weekly_people, "no_deadline": no_deadline}
