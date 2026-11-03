# MAVIS_CABINET_DRILLDOWN_20261103
"""Bounded, read-only data loader for one authenticated Bitrix employee."""

import asyncio
import re
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .daily_sales import daily_bounds, duration_seconds
from .metrics import DEAL_SELECT, LEAD_SELECT, F_DEAL_CLIENT_TYPE, F_SERVICE, money, month_bounds, preplan_stage_ids, stage_name, successful_sale_stage_ids

SUCCESSFUL_CALL_SECONDS = 60
SUCCESSFUL_CALL_DAILY_TARGET = 50
PERSONAL_DEAL_SELECT = [*DEAL_SELECT, "ACTIVITY_NEXT_TIME", "ACTIVITY_COUNTER", "COMMENTS"]
CRM_ACTIVITY_SELECT = ["ID", "OWNER_ID", "OWNER_TYPE_ID", "TYPE_ID", "COMPLETED", "DEADLINE", "SUBJECT", "DESCRIPTION", "CREATED", "LAST_UPDATED"]
CONTACT_WORDS = ("связ", "перезвон", "позвон", "набрать", "контакт")
SHORT_DATE = re.compile(r"(?<!\d)([0-3]?\d)[./-]([01]?\d)(?:[./-](20\d{2}|\d{2}))?(?!\d)")


def _deal_url(portal: str, deal_id: Any) -> str:
    return f"{portal}/crm/deal/details/{deal_id}/" if str(deal_id or "").isdigit() else ""


def _parse_datetime(value: Any, timezone: ZoneInfo) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone) if parsed.tzinfo is None else parsed.astimezone(timezone)


def _owner_id(activity: dict[str, Any]) -> str:
    return str(activity.get("OWNER_ID") or activity.get("ownerId") or "").strip()


def _activity_row(activity: dict[str, Any], deal: dict[str, Any], portal: str) -> dict[str, str]:
    subject = str(activity.get("SUBJECT") or activity.get("DESCRIPTION") or "Запланированное действие").strip()
    return {"id": str(activity.get("ID") or ""), "title": f"{str(deal.get('TITLE') or 'Сделка')} — {subject}", "deadline": str(activity.get("DEADLINE") or ""), "url": _deal_url(portal, deal.get("ID"))}


def _comment_follow_up_date(value: Any, reference: date) -> date | None:
    """Use only an explicit contact promise, never an arbitrary date in text."""
    for sentence in re.split(r"[\n!?;]+", str(value or "")):
        if not any(word in sentence.lower() for word in CONTACT_WORDS):
            continue
        match = SHORT_DATE.search(sentence)
        if not match:
            continue
        day, month, raw_year = match.groups()
        year = int(raw_year) if raw_year and len(raw_year) == 4 else reference.year
        if raw_year and len(raw_year) == 2:
            year = 2000 + int(raw_year)
        try:
            parsed = date(year, int(month), int(day))
        except ValueError:
            continue
        if not raw_year and parsed > reference + timedelta(days=180):
            parsed = date(year - 1, int(month), int(day))
        return parsed
    return None


async def _deal_activities(client: Any, deal_ids: list[str], completed: str, *, call_only: bool = False) -> tuple[list[dict[str, Any]], bool]:
    unique_ids = list(dict.fromkeys(str(value) for value in deal_ids if str(value).isdigit()))
    if not unique_ids:
        return [], True

    async def load_chunk(chunk: list[str]):
        filters: dict[str, Any] = {"OWNER_TYPE_ID": 2, "OWNER_ID": chunk, "COMPLETED": completed}
        if call_only:
            filters["TYPE_ID"] = 2
        return await client.list_all("crm.activity.list", {"order": {"DEADLINE": "ASC", "ID": "DESC"}, "filter": filters, "select": CRM_ACTIVITY_SELECT}, limit=500)

    groups = await asyncio.gather(*(load_chunk(unique_ids[offset:offset + 50]) for offset in range(0, len(unique_ids), 50)), return_exceptions=True)
    if any(isinstance(group, Exception) or not isinstance(group, list) for group in groups):
        return [], False
    return [row for group in groups for row in group if isinstance(row, dict)], True


async def build_personal_workday(client: Any, user_id: str, report_date: str, timezone: str) -> dict[str, Any]:
    """Return one manager's CRM facts; a CRM activity is the source of a deal's next action."""
    start, end = daily_bounds(report_date, timezone)
    zone = ZoneInfo(timezone)
    now = datetime.now(zone)
    month_start, month_end, _, month_key = month_bounds(report_date[:7], timezone)
    calls_task = client.list_all("voximplant.statistic.get", {"FILTER": {">=CALL_START_DATE": start.isoformat(), "<CALL_START_DATE": end.isoformat()}, "SORT": "CALL_START_DATE", "ORDER": "ASC"})
    sales_task = client.deal_list({"CATEGORY_ID": 0, "ASSIGNED_BY_ID": user_id, "CLOSED": "N"}, PERSONAL_DEAL_SELECT)
    reanimation_task = client.deal_list({"CATEGORY_ID": 20, "ASSIGNED_BY_ID": user_id, "CLOSED": "N"}, PERSONAL_DEAL_SELECT)
    meta_task = client.meta()
    leads_task = client.lead_list({"ASSIGNED_BY_ID": user_id, ">=DATE_CREATE": month_start.isoformat(), "<DATE_CREATE": month_end.isoformat()}, LEAD_SELECT)
    won_task = client.deal_list({"CATEGORY_ID": 0, "ASSIGNED_BY_ID": user_id, ">=CLOSEDATE": month_start.isoformat(), "<CLOSEDATE": month_end.isoformat()}, PERSONAL_DEAL_SELECT)
    created_task = client.deal_list({"CATEGORY_ID": 0, "ASSIGNED_BY_ID": user_id, ">=DATE_CREATE": month_start.isoformat(), "<DATE_CREATE": month_end.isoformat()}, PERSONAL_DEAL_SELECT)
    calls_result, sales_result, reanimation_result, meta_result, leads_result, won_result, created_result = await asyncio.gather(calls_task, sales_task, reanimation_task, meta_task, leads_task, won_task, created_task, return_exceptions=True)

    calls = [row for row in calls_result if isinstance(row, dict) and str(row.get("PORTAL_USER_ID") or "") == str(user_id)] if isinstance(calls_result, list) else []
    successful = [row for row in calls if (duration_seconds({"CALL_DURATION": row.get("CALL_DURATION")}) or 0) >= SUCCESSFUL_CALL_SECONDS]
    deals = [row for result in (sales_result, reanimation_result) if isinstance(result, list) for row in result if isinstance(row, dict)]
    deals = list({str(row.get("ID") or index): row for index, row in enumerate(deals)}.values())
    deal_by_id = {str(row.get("ID") or ""): row for row in deals}
    portal = str(getattr(client, "portal", "")).rstrip("/")
    open_activities, activities_online = await _deal_activities(client, list(deal_by_id), "N")
    open_by_deal: dict[str, list[dict[str, Any]]] = {}
    for activity in open_activities:
        if (owner := _owner_id(activity)) in deal_by_id:
            open_by_deal.setdefault(owner, []).append(activity)

    def deadline(activity: dict[str, Any]) -> datetime | None:
        return _parse_datetime(activity.get("DEADLINE"), zone)

    overdue_activities = [row for row in open_activities if (due := deadline(row)) and due < now]
    today_activities = [row for row in open_activities if (due := deadline(row)) and due.date() == now.date()]
    next_workday = now.date() + timedelta(days=1)
    while next_workday.weekday() >= 5:
        next_workday += timedelta(days=1)
    tomorrow_activities = [row for row in open_activities if (due := deadline(row)) and due.date() == next_workday]
    without_activity = [row for row in deals if str(row.get("ID") or "") not in open_by_deal] if activities_online else []
    promise_candidates = {deal_id: promised for deal_id, deal in deal_by_id.items() if deal_id not in open_by_deal if (promised := _comment_follow_up_date(deal.get("COMMENTS"), now.date())) and promised <= now.date()}
    completed_calls, calls_online = await _deal_activities(client, list(promise_candidates), "Y", call_only=True)
    last_call_by_deal: dict[str, datetime] = {}
    for activity in completed_calls:
        created = _parse_datetime(activity.get("CREATED") or activity.get("LAST_UPDATED"), zone)
        owner = _owner_id(activity)
        if created and (owner not in last_call_by_deal or created > last_call_by_deal[owner]):
            last_call_by_deal[owner] = created

    meta = meta_result if isinstance(meta_result, dict) else {}
    stages: dict[str, dict[str, Any]] = {}
    for deal in deals:
        label = stage_name(meta, deal.get("STAGE_ID"), "DEAL_STAGE")
        entry = stages.setdefault(label, {"name": label, "stage_id": str(deal.get("STAGE_ID") or ""), "count": 0, "amount": 0.0})
        entry["count"] += 1
        entry["amount"] += money(deal)
    preplan = [deal for deal in deals if str(deal.get("STAGE_ID") or "") in preplan_stage_ids(meta)]
    won = [deal for deal in won_result if isinstance(deal, dict) and str(deal.get("STAGE_ID") or "") in successful_sale_stage_ids(meta)] if isinstance(won_result, list) else []
    created_sales = [deal for deal in created_result if isinstance(deal, dict)] if isinstance(created_result, list) else []
    conversion_percent = round(len(won) / len(created_sales) * 100, 1) if created_sales else None
    missing_source = [deal for deal in deals if not str(deal.get("SOURCE_ID") or "").strip()]
    missing_client_type = [deal for deal in deals if not str(deal.get(F_DEAL_CLIENT_TYPE) or "").strip()]
    iso_suot_candidates = [deal for deal in deals if not str(deal.get(F_SERVICE) or "").strip()]

    def deal_row(deal: dict[str, Any]) -> dict[str, str]:
        return {"id": str(deal.get("ID") or ""), "title": str(deal.get("TITLE") or "Без названия"), "stage": str(deal.get("STAGE_ID") or ""), "stage_name": stage_name(meta, deal.get("STAGE_ID"), "DEAL_STAGE"), "amount": round(money(deal), 2), "source": str(deal.get("SOURCE_ID") or ""), "created": str(deal.get("DATE_CREATE") or ""), "close_date": str(deal.get("CLOSEDATE") or ""), "url": _deal_url(portal, deal.get("ID"))}

    priorities = []
    for activity in overdue_activities:
        if (deal := deal_by_id.get(_owner_id(activity))) is None:
            continue
        due = deadline(activity)
        priorities.append({**deal_row(deal), "priority": "Просрочено CRM-дело", "due": due.date().isoformat() if due else "", "reason": f"Связаться в первую очередь: срок {due.strftime('%d.%m') if due else 'истёк'} — {str(activity.get('SUBJECT') or 'без темы')}"})
    if activities_online and calls_online:
        for deal_id, promised in promise_candidates.items():
            if (last_call := last_call_by_deal.get(deal_id)) and last_call.date() >= promised:
                continue
            priorities.append({**deal_row(deal_by_id[deal_id]), "priority": "Обещанный контакт не подтверждён", "due": promised.isoformat(), "reason": f"В комментарии обещано связаться {promised.strftime('%d.%m')}; открытого дела и звонка после этой даты нет."})
    priorities.sort(key=lambda row: (row["priority"] != "Обещанный контакт не подтверждён", row["due"], row["title"]))

    return {
        "ok": True, "date": start.date().isoformat(), "user_id": str(user_id), "profile": {"name": str((meta.get("users") or {}).get(str(user_id)) or f"Сотрудник {user_id}")}, "generated_at": now.isoformat(),
        "availability": {"calls": "online" if isinstance(calls_result, list) else "unavailable", "tasks": "online" if activities_online else "unavailable", "comment_follow_up": "online" if activities_online and calls_online else "unavailable", "stage_sla": "not_configured", "iso_suot_registry": "needs_connection"},
        "calls": {"successful_records": [{"id": str(call.get("ID") or ""), "title": "Звонок " + str(call.get("PHONE_NUMBER") or call.get("CALL_START_DATE") or ""), "created": str(call.get("CALL_START_DATE") or ""), "duration_seconds": int(float(call.get("CALL_DURATION") or 0))} for call in successful[:150]], "total": len(calls), "successful_from_minute": len(successful), "target": SUCCESSFUL_CALL_DAILY_TARGET, "remaining": max(0, SUCCESSFUL_CALL_DAILY_TARGET - len(successful)), "rule": "Успешный звонок — запись Bitrix с длительностью не менее 60 секунд."},
        "tasks": {"open_count": len(open_activities) if activities_online else None, "overdue_count": len(overdue_activities) if activities_online else None, "today_count": len(today_activities) if activities_online else None, "tomorrow_count": len(tomorrow_activities) if activities_online else None, "tomorrow_date": next_workday.isoformat(), "today": [_activity_row(row, deal_by_id[_owner_id(row)], portal) for row in today_activities[:12] if _owner_id(row) in deal_by_id], "tomorrow": [_activity_row(row, deal_by_id[_owner_id(row)], portal) for row in tomorrow_activities[:12] if _owner_id(row) in deal_by_id], "overdue": [_activity_row(row, deal_by_id[_owner_id(row)], portal) for row in overdue_activities[:50] if _owner_id(row) in deal_by_id]},
        "deals": {"active": [deal_row(deal) for deal in deals], "preplan": [deal_row(deal) for deal in preplan], "won": [deal_row(deal) for deal in won], "created": [deal_row(deal) for deal in created_sales], "active_count": len(deals), "overdue_count": len({_owner_id(row) for row in overdue_activities}) if activities_online else None, "without_open_task_count": len(without_activity) if activities_online else None, "missing_source_count": len(missing_source), "missing_client_type_count": len(missing_client_type), "missing_source": [deal_row(deal) for deal in missing_source], "missing_client_type": [deal_row(deal) for deal in missing_client_type], "overdue": [deal_row(deal_by_id[_owner_id(row)]) for row in overdue_activities[:50] if _owner_id(row) in deal_by_id], "without_open_task": [deal_row(row) for row in without_activity[:50]], "priorities": priorities[:50], "stages": sorted(stages.values(), key=lambda row: (-int(row["count"]), str(row["name"]))), "preplan_count": len(preplan), "preplan_amount": round(sum(money(row) for row in preplan), 2), "fact_count": len(won), "fact_amount": round(sum(money(row) for row in won), 2), "conversion": {"created_count": len(created_sales), "won_count": len(won), "percent": conversion_percent, "definition": "Успешные сделки, закрытые в месяце / сделки, созданные в месяце. Это показатель периода, а не когортная конверсия одной даты создания."}},
        "leads": {"month_count": len(leads_result) if isinstance(leads_result, list) else 0, "month": [{"id": str(lead.get("ID") or ""), "title": str(lead.get("TITLE") or "Лид"), "created": str(lead.get("DATE_CREATE") or ""), "source": str(lead.get("SOURCE_ID") or ""), "url": f"{portal}/crm/lead/details/{lead.get('ID')}/" if str(lead.get("ID") or "").isdigit() else ""} for lead in leads_result if isinstance(lead, dict)] if isinstance(leads_result, list) else []},
        "stage_sla": {"status": "not_configured", "message": "Карта сроков этапов Bitrix ещё не подключена."},
        "iso_suot": {"status": "needs_connection", "message": "Реестр ИСО/СУОТ ещё не подключён к кабинету. Ниже — только сделки без заполненной услуги, а не вывод о потребности клиента.", "candidates": [deal_row(row) for row in iso_suot_candidates[:12]]}, "month": month_key,
    }
