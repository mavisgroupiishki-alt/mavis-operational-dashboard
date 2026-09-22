"""Pure presentation helpers for dashboard-owned key tasks."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Iterable
from zoneinfo import ZoneInfo


def parse_task_date(raw: Any, tz: ZoneInfo) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.strptime(str(raw)[:10], "%Y-%m-%d").replace(tzinfo=tz)
    except (TypeError, ValueError):
        return None


def monday(value: date) -> date:
    return value - timedelta(days=value.weekday())


def task_sort_key(task: dict[str, Any], now: datetime, tz: ZoneInfo):
    deadline = parse_task_date(task.get("deadline"), tz)
    created = str(task.get("created_at") or "")
    return (
        0 if deadline and deadline.date() < now.date() else 1,
        deadline.timestamp() if deadline else float("inf"),
        0 if task.get("priority") == "high" else 1,
        created,
        str(task.get("id") or ""),
    )


def task_reason(task: dict[str, Any], now: datetime, tz: ZoneInfo) -> str:
    deadline = parse_task_date(task.get("deadline"), tz)
    if deadline and deadline.date() < now.date():
        return "Просрочена"
    if deadline:
        return "Срок"
    if task.get("priority") == "high":
        return "Высокий приоритет"
    return "Без срока"


def task_payload(task: dict[str, Any], name: str, now: datetime, tz: ZoneInfo) -> dict[str, Any]:
    deadline = parse_task_date(task.get("deadline"), tz)
    return {
        "id": str(task.get("id") or ""),
        "title": str(task.get("title") or "Без названия"),
        "responsible": name,
        "responsible_id": str(task.get("responsible_id") or ""),
        "deadline": deadline.date().isoformat() if deadline else "",
        "created": str(task.get("created_at") or ""),
        "priority": "high" if task.get("priority") == "high" else "normal",
        "reason": task_reason(task, now, tz),
        "task_url": "",
    }


def build_key_tasks(
    tasks: Iterable[dict[str, Any]],
    members: list[dict[str, str]],
    now: datetime,
    timezone: str,
    limit: int = 5,
) -> dict[str, Any]:
    """Group manually created tasks by selected employee and deadline week."""
    tz = ZoneInfo(timezone)
    member_names = {str(row.get("id") or ""): str(row.get("name") or "") for row in members}
    source = [row for row in tasks if str(row.get("responsible_id") or "") in member_names]
    people = []
    weekly_people: dict[str, list[dict[str, Any]]] = {}
    all_tasks = []
    for member in members:
        user_id = str(member.get("id") or "")
        name = member_names.get(user_id) or "Без имени"
        person_tasks = [task for task in source if str(task.get("responsible_id") or "") == user_id]
        ranked = sorted(person_tasks, key=lambda task: task_sort_key(task, now, tz))
        payloads = [task_payload(task, name, now, tz) for task in ranked]
        people.append({"id": user_id, "name": name, "tasks": payloads[:limit], "active_count": len(payloads)})
        all_tasks.extend(payloads)
        weeks: dict[str, list[dict[str, Any]]] = {}
        for task in person_tasks:
            deadline = parse_task_date(task.get("deadline"), tz)
            if not deadline:
                continue
            weeks.setdefault(monday(deadline.date()).isoformat(), []).append(task)
        for key, rows in weeks.items():
            weekly_people.setdefault(key, []).append({
                "id": user_id,
                "name": name,
                "tasks": [task_payload(task, name, now, tz) for task in sorted(rows, key=lambda task: task_sort_key(task, now, tz))[:limit]],
                "active_count": len(rows),
            })

    by_week: dict[str, list[dict[str, Any]]] = {}
    no_deadline = []
    for task in all_tasks:
        deadline = parse_task_date(task.get("deadline"), tz)
        if not deadline:
            no_deadline.append(task)
            continue
        by_week.setdefault(monday(deadline.date()).isoformat(), []).append(task)
    for rows in by_week.values():
        rows.sort(key=lambda task: task_sort_key(task, now, tz))
    no_deadline.sort(key=lambda task: task_sort_key(task, now, tz))
    for key, rows in weekly_people.items():
        present = {row["id"] for row in rows}
        rows.extend({"id": member["id"], "name": member["name"], "tasks": [], "active_count": 0} for member in members if member["id"] not in present)
        rows.sort(key=lambda row: row["name"].casefold())
    return {"people": people, "weeks": by_week, "weekly_people": weekly_people, "no_deadline": no_deadline}
