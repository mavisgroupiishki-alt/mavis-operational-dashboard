"""Live monthly report for the Bitrix project \"Акты Счета\"."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping


ACTS_PROJECT_ID = 36
EXPERTS = (
    "Елизавета Горбатова",
    "Екатерина Николаева",
    "Ольга Панькова",
    "Владислав Климков",
    "Данила Канцен",
    "Иоланта Кананович",
)


def valid_month(value: str, fallback: str) -> str:
    return value if re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", str(value or "")) else fallback


def _clean(value: object) -> str:
    return " ".join(str(value or "").split())


def _name_key(value: object) -> str:
    return _clean(value).lower().replace("ё", "е")


def _stage_name(stage: Mapping[str, object]) -> str:
    return _clean(stage.get("title") or stage.get("TITLE") or stage.get("name") or stage.get("NAME"))


def linked_deal_id(task: Mapping[str, object]) -> str:
    """Read a Bitrix deal link from either of the task CRM-link fields."""
    for field in ("UF_CRM_TASK_DEAL", "UF_CRM_TASK", "ufCrmTaskDeal", "ufCrmTask"):
        value = task.get(field)
        if isinstance(value, (list, tuple)):
            value = value[0] if value else ""
        match = re.search(r"(?:^|[^A-Z0-9])D_(\d+)(?:$|[^0-9])", str(value or ""), re.IGNORECASE)
        if match:
            return match.group(1)
    return ""


def _close_month(task: Mapping[str, object]) -> str:
    return str(task.get("ACTS_DEAL_CLOSEDATE") or task.get("actsDealClosedate") or "")[:7]


def build_acts_experts_report(
    tasks: Iterable[Mapping[str, object]],
    users: Mapping[str, str],
    stages: Iterable[Mapping[str, object]],
    month: str,
    portal: str,
) -> dict:
    """Group current-month tasks by creator, excluding CRM month mismatches."""
    stage_names = {
        str(stage.get("id") or stage.get("ID") or ""): _stage_name(stage)
        for stage in stages
    }
    people = {
        _name_key(name): {
            "name": name, "total": 0, "scan": 0, "archive": 0,
            "scan_tasks": [], "archive_tasks": [], "pending": [], "crm_mismatch": [],
        }
        for name in EXPERTS
    }
    for task in tasks:
        created_at = str(task.get("CREATED_DATE") or task.get("createdDate") or "")
        if not created_at.startswith(month):
            continue
        creator_id = str(task.get("CREATED_BY") or task.get("createdBy") or "")
        person = people.get(_name_key(users.get(creator_id, "")))
        title = _clean(task.get("TITLE") or task.get("title"))
        if not person or not title:
            continue
        stage_id = str(task.get("STAGE_ID") or task.get("stageId") or "0")
        stage = stage_names.get(stage_id) or ("Без стадии" if stage_id == "0" else f"Стадия {stage_id}")
        normalized_stage = _name_key(stage)
        task_id = str(task.get("ID") or task.get("id") or "")
        task_row = {
            "id": task_id,
            "title": title,
            "stage": stage,
            "created_at": created_at,
            "deal_id": linked_deal_id(task),
            "deal_close_date": str(task.get("ACTS_DEAL_CLOSEDATE") or ""),
            "url": f"{portal}/workgroups/group/{ACTS_PROJECT_ID}/tasks/task/view/{task_id}/" if task_id else "",
        }
        if (close_month := _close_month(task)) and close_month != month:
            person["crm_mismatch"].append(task_row)
            continue
        person["total"] += 1
        if normalized_stage == "скан есть":
            person["scan"] += 1
            person["scan_tasks"].append(task_row)
        elif normalized_stage == "архив":
            person["archive"] += 1
            person["archive_tasks"].append(task_row)
        else:
            person["pending"].append(task_row)
    experts = []
    for row in people.values():
        for key in ("scan_tasks", "archive_tasks", "pending", "crm_mismatch"):
            row[key].sort(key=lambda task: (task["created_at"], task["id"]))
        experts.append({
            **row,
            "no_confirmation": len(row["pending"]),
            "crm_mismatch_count": len(row["crm_mismatch"]),
        })
    return {"ok": True, "month": month, "project_id": ACTS_PROJECT_ID, "experts": experts}
