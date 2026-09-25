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


TASK_STATUSES = (
    ("new", "Новая"),
    ("in_progress", "В работе"),
    ("review", "На проверке"),
    ("done", "Завершена"),
)


def build_task_workspace(
    tasks: Iterable[dict[str, Any]],
    profiles: Iterable[dict[str, Any]],
    projects: Iterable[dict[str, Any]],
    legacy_members: Iterable[dict[str, Any]],
    now: datetime,
    timezone: str,
) -> dict[str, Any]:
    """Build a stable, dashboard-only task workspace response.

    Old key-task rows have Bitrix user ids. They remain readable as archived
    people rather than being silently discarded when the workspace launches.
    """
    tz = ZoneInfo(timezone)
    profile_rows = [dict(row) for row in profiles]
    people = {str(row.get("id") or ""): dict(row) for row in profile_rows}
    for row in legacy_members:
        person_id = str(row.get("id") or "").strip()
        if person_id and person_id not in people:
            people[person_id] = {"id": person_id, "name": str(row.get("name") or "Без имени"), "active": False, "legacy": True}
    projects_by_id = {str(row.get("id") or ""): dict(row) for row in projects}
    out = []
    for source in tasks:
        row = dict(source)
        responsible_id = str(row.get("responsible_id") or "").strip()
        executor_ids = [str(value).strip() for value in row.get("executor_ids") or [] if str(value).strip()]
        if not executor_ids and responsible_id:
            executor_ids = [responsible_id]
        related_ids = list(dict.fromkeys([responsible_id, *executor_ids]))
        for person_id in related_ids:
            if person_id and person_id not in people:
                people[person_id] = {"id": person_id, "name": row.get("legacy_responsible_name") or "Сотрудник", "active": False, "legacy": True}
        deadline = parse_task_date(row.get("deadline"), tz)
        status = str(row.get("status") or "in_progress")
        status = status if status in dict(TASK_STATUSES) else "in_progress"
        project_id = str(row.get("project_id") or "")
        project = projects_by_id.get(project_id)
        def person_payload(person_id: str) -> dict[str, Any]:
            person = people.get(person_id) or {"id": person_id, "name": "Сотрудник", "active": False}
            return {"id": person_id, "name": str(person.get("name") or "Сотрудник"), "active": bool(person.get("active")), "dismissed": not bool(person.get("active")) and not bool(person.get("legacy"))}
        out.append({
            "id": str(row.get("id") or ""),
            "title": str(row.get("title") or "Без названия"),
            "description": str(row.get("description") or ""),
            "priority": "high" if row.get("priority") == "high" else "normal",
            "status": status,
            "status_label": dict(TASK_STATUSES)[status],
            "deadline": deadline.date().isoformat() if deadline else "",
            "is_overdue": bool(deadline and deadline.date() < now.date() and status != "done"),
            "project_id": project_id,
            "project": {"id": project_id, "name": str(project.get("name") or "Без проекта"), "archived": bool(project.get("archived"))} if project else None,
            "responsible": person_payload(responsible_id) if responsible_id else None,
            "executors": [person_payload(person_id) for person_id in executor_ids],
            "created_at": str(row.get("created_at") or ""),
            "updated_at": str(row.get("updated_at") or row.get("created_at") or ""),
            "created_by_profile_id": str(row.get("created_by_profile_id") or ""),
        })
    out.sort(key=lambda item: (item["status"] == "done", not item["is_overdue"], item["deadline"] or "9999-12-31", item["title"].casefold()))
    return {
        "tasks": out,
        "profiles": profile_rows,
        "people": sorted(people.values(), key=lambda row: str(row.get("name") or "").casefold()),
        "projects": [dict(row) for row in projects],
        "statuses": [{"id": key, "name": name} for key, name in TASK_STATUSES],
    }
