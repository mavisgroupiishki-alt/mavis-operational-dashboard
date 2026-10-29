"""Bounded read-only data loader for one authenticated Bitrix employee."""

import asyncio
import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from .daily_sales import daily_bounds, duration_seconds
from .metrics import DEAL_SELECT, F_DEAL_CLIENT_TYPE


SUCCESSFUL_CALL_SECONDS = 60
SUCCESSFUL_CALL_DAILY_TARGET = 50
TERMINAL_TASK_STATUSES = {"5", "6", "7"}


def _deal_url(portal: str, deal_id: Any) -> str:
    return f"{portal}/crm/deal/details/{deal_id}/" if str(deal_id or "").isdigit() else ""


def _task_url(portal: str, task_id: Any) -> str:
    return f"{portal}/company/personal/user/0/tasks/task/view/{task_id}/" if str(task_id or "").isdigit() else ""


def _linked_deal_ids(task: dict[str, Any]) -> set[str]:
    values = [task.get("UF_CRM_TASK_DEAL"), task.get("UF_CRM_TASK")]
    return {match for value in values for match in re.findall(r"D_(\d+)", str(value or ""))}


def _task_is_open(task: dict[str, Any]) -> bool:
    return str(task.get("REAL_STATUS") or task.get("STATUS") or "") not in TERMINAL_TASK_STATUSES


def _date_before(value: Any, now: datetime) -> bool:
    raw = str(value or "").strip()
    if not raw:
        return False
    try:
        normalized = raw.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=now.tzinfo)
        return parsed < now
    except ValueError:
        return False


async def build_personal_workday(client: Any, user_id: str, report_date: str, timezone: str) -> dict[str, Any]:
    """Return only the employee's own source rows and honest availability."""
    start, end = daily_bounds(report_date, timezone)
    now = datetime.now(ZoneInfo(timezone))
    calls_task = client.list_all("voximplant.statistic.get", {
        "FILTER": {">=CALL_START_DATE": start.isoformat(), "<CALL_START_DATE": end.isoformat()},
        "SORT": "CALL_START_DATE", "ORDER": "ASC",
    })
    tasks_task = client.tasks_for_responsible(user_id, limit=300)
    sales_deals_task = client.deal_list({"CATEGORY_ID": 0, "ASSIGNED_BY_ID": user_id, "CLOSED": "N"}, DEAL_SELECT)
    reanimation_deals_task = client.deal_list({"CATEGORY_ID": 20, "ASSIGNED_BY_ID": user_id, "CLOSED": "N"}, DEAL_SELECT)
    calls_result, tasks_result, sales_result, reanimation_result = await asyncio.gather(
        calls_task, tasks_task, sales_deals_task, reanimation_deals_task, return_exceptions=True
    )

    availability = {
        "calls": "online" if isinstance(calls_result, list) else "unavailable",
        "tasks": "online" if isinstance(tasks_result, list) else "unavailable",
        "deals": "online" if isinstance(sales_result, list) and isinstance(reanimation_result, list) else "unavailable",
        "stage_sla": "not_configured",
        "iso_suot_registry": "not_configured",
    }
    calls = [row for row in calls_result if isinstance(row, dict) and str(row.get("PORTAL_USER_ID") or "") == str(user_id)] if isinstance(calls_result, list) else []
    successful = [row for row in calls if (duration_seconds({"CALL_DURATION": row.get("CALL_DURATION")}) or 0) >= SUCCESSFUL_CALL_SECONDS]
    tasks = [row for row in tasks_result if isinstance(row, dict)] if isinstance(tasks_result, list) else []
    open_tasks = [row for row in tasks if _task_is_open(row)]
    overdue_tasks = [row for row in open_tasks if _date_before(row.get("DEADLINE"), now)]
    deals = []
    if isinstance(sales_result, list):
        deals.extend(row for row in sales_result if isinstance(row, dict))
    if isinstance(reanimation_result, list):
        deals.extend(row for row in reanimation_result if isinstance(row, dict))
    deals = list({str(row.get("ID") or index): row for index, row in enumerate(deals)}.values())
    portal = str(getattr(client, "portal", "")).rstrip("/")
    linked_open_task_deals = {deal_id for task in open_tasks for deal_id in _linked_deal_ids(task)}
    overdue_deals = [row for row in deals if _date_before(row.get("CLOSEDATE"), now)]
    without_task = [row for row in deals if str(row.get("ID") or "") not in linked_open_task_deals]
    missing_source = [row for row in deals if not str(row.get("SOURCE_ID") or "").strip()]
    missing_client_type = [row for row in deals if not str(row.get(F_DEAL_CLIENT_TYPE) or "").strip()]

    def deal_row(row: dict[str, Any]) -> dict[str, str]:
        return {"id": str(row.get("ID") or ""), "title": str(row.get("TITLE") or "Без названия"), "stage": str(row.get("STAGE_ID") or ""), "url": _deal_url(portal, row.get("ID"))}

    return {
        "ok": True,
        "date": start.date().isoformat(),
        "user_id": str(user_id),
        "generated_at": now.isoformat(),
        "availability": availability,
        "calls": {
            "total": len(calls),
            "successful_from_minute": len(successful),
            "target": SUCCESSFUL_CALL_DAILY_TARGET,
            "remaining": max(0, SUCCESSFUL_CALL_DAILY_TARGET - len(successful)),
            "rule": "Успешный звонок — запись Bitrix с длительностью не менее 60 секунд.",
        },
        "tasks": {
            "open_count": len(open_tasks),
            "overdue_count": len(overdue_tasks),
            "overdue": [{"id": str(row.get("ID") or ""), "title": str(row.get("TITLE") or "Без названия"), "deadline": str(row.get("DEADLINE") or ""), "url": _task_url(portal, row.get("ID"))} for row in overdue_tasks[:50]],
        },
        "deals": {
            "active_count": len(deals),
            "overdue_count": len(overdue_deals),
            "without_open_task_count": len(without_task),
            "missing_source_count": len(missing_source),
            "missing_client_type_count": len(missing_client_type),
            "overdue": [deal_row(row) for row in overdue_deals[:50]],
            "without_open_task": [deal_row(row) for row in without_task[:50]],
            "missing_source": [deal_row(row) for row in missing_source[:50]],
            "missing_client_type": [deal_row(row) for row in missing_client_type[:50]],
        },
        "stage_sla": {"status": "not_configured", "message": "Карта сроков этапов Bitrix ещё не подключена."},
        "iso_suot": {"status": "not_configured", "message": "Реестр ИСО/СУОТ ещё не подключён; подсказки о допродаже не формируются."},
    }
