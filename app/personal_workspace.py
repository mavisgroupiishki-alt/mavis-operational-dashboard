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
PERSONAL_DEAL_SELECT = [*DEAL_SELECT, "COMPANY_ID", "COMPANY_TITLE", "ACTIVITY_NEXT_TIME", "ACTIVITY_COUNTER", "COMMENTS", "DATE_MODIFY", "MOVED_TIME"]
CRM_ACTIVITY_SELECT = ["ID", "OWNER_ID", "OWNER_TYPE_ID", "TYPE_ID", "COMPLETED", "DEADLINE", "SUBJECT", "DESCRIPTION", "CREATED", "LAST_UPDATED"]
CONTACT_WORDS = ("связ", "перезвон", "позвон", "набрать", "контакт")
SHORT_DATE = re.compile(r"(?<!\d)([0-3]?\d)[./-]([01]?\d)(?:[./-](20\d{2}|\d{2}))?(?!\d)")
DOCUMENT_WORDS = ("бис", "разреш", "лиценз", "аттестат", "документ")


def _stage_sla_rule(stage_name_value: str) -> tuple[str, int | None]:
    """Map the supplied sales regulation to a CRM stage name, conservatively."""
    value = re.sub(r"\s+", " ", str(stage_name_value or "").casefold().replace("ё", "е"))
    if "новая сделка" in value:
        return "До конца рабочего дня", 0
    if "кп отправ" in value:
        return "Не более 2 дней", 2
    if "в работе" in value:
        return "Не более 3 дней", 3
    if "возраж" in value or "договор" in value:
        return "Не более 5 дней", 5
    if "ожида" in value and "оплат" in value:
        return "Не более 7 дней", 7
    if "предплан" in value and "недел" in value:
        return "До конца текущей недели", None
    return "", None


def _stage_sla_state(stage_name_value: str, moved_at: datetime | None, now: datetime) -> dict[str, Any] | None:
    rule, max_days = _stage_sla_rule(stage_name_value)
    if not rule or not moved_at:
        return None
    if max_days == 0:
        deadline = moved_at.replace(hour=23, minute=59, second=59, microsecond=0)
    elif max_days is None:
        deadline = moved_at.replace(hour=23, minute=59, second=59, microsecond=0) + timedelta(days=4 - moved_at.weekday())
    else:
        deadline = moved_at + timedelta(days=max_days)
    return {
        "rule": rule,
        "limit_days": max_days,
        "started_at": moved_at.isoformat(),
        "deadline": deadline.isoformat(),
        "breached": now > deadline,
        "actual_hours": max(0.0, round((now - moved_at).total_seconds() / 3600, 1)),
        "actual_days": max(0.0, round((now - moved_at).total_seconds() / 86400, 1)),
        "overdue_hours": max(0.0, round((now - deadline).total_seconds() / 3600, 1)),
        "remaining_hours": round((deadline - now).total_seconds() / 3600, 1),
    }


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


def _workspace_period(report_date: str, period: str, timezone: str) -> tuple[datetime, datetime, str, int]:
    """Return a bounded reporting range and the matching successful-call norm."""
    day_start, day_end = daily_bounds(report_date, timezone)
    if period == "month":
        start, end, _, _ = month_bounds(report_date[:7], timezone)
        label = "месяц"
    elif period == "week":
        monday = day_start.date() - timedelta(days=day_start.weekday())
        start, _ = daily_bounds(monday.isoformat(), timezone)
        end = start + timedelta(days=7)
        label = "неделя"
    else:
        start, end, label = day_start, day_end, "день"
    workdays = sum(1 for offset in range((end.date() - start.date()).days) if (start.date() + timedelta(days=offset)).weekday() < 5)
    return start, end, label, max(1, workdays) * SUCCESSFUL_CALL_DAILY_TARGET


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


def _document_deadline(value: Any, reference: date) -> date | None:
    """Return only an explicit near-term document date from CRM text."""
    for sentence in re.split(r"[\n!?;]+", str(value or "")):
        lowered = sentence.casefold().replace("ё", "е")
        if not any(word in lowered for word in DOCUMENT_WORDS):
            continue
        match = SHORT_DATE.search(sentence)
        if not match:
            continue
        day, month, raw_year = match.groups()
        year = int(raw_year) if raw_year and len(raw_year) == 4 else reference.year
        if raw_year and len(raw_year) == 2:
            year = 2000 + int(raw_year)
        try:
            result = date(year, int(month), int(day))
        except ValueError:
            continue
        if not raw_year and result < reference - timedelta(days=30):
            result = date(year + 1, int(month), int(day))
        if reference <= result <= reference + timedelta(days=30):
            return result
    return None


def _call_deal_id(call: dict[str, Any]) -> str:
    for key in ("CRM_ENTITY_ID", "CRM_ENTITY", "OWNER_ID", "DEAL_ID"):
        value = str(call.get(key) or "").strip()
        if value.isdigit():
            return value
    return ""


def _is_deferred_demand_stage(stage_name_value: Any) -> bool:
    value = re.sub(r"\s+", " ", str(stage_name_value or "").casefold().replace("ё", "е"))
    return "отлож" in value and "спрос" in value


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


async def build_personal_workday(client: Any, user_id: str, report_date: str, timezone: str, period: str = "day") -> dict[str, Any]:
    """Return one manager's CRM facts; a CRM activity is the source of a deal's next action."""
    start, end, period_label, call_target = _workspace_period(report_date, period, timezone)
    zone = ZoneInfo(timezone)
    now = datetime.now(zone)
    month_start, month_end, _, month_key = month_bounds(report_date[:7], timezone)
    calls_task = client.list_all("voximplant.statistic.get", {"FILTER": {">=CALL_START_DATE": start.isoformat(), "<CALL_START_DATE": end.isoformat()}, "SORT": "CALL_START_DATE", "ORDER": "ASC"})
    sales_task = client.deal_list({"CATEGORY_ID": 0, "ASSIGNED_BY_ID": user_id, "CLOSED": "N"}, PERSONAL_DEAL_SELECT)
    reanimation_task = client.deal_list({"CATEGORY_ID": 20, "ASSIGNED_BY_ID": user_id, "CLOSED": "N"}, PERSONAL_DEAL_SELECT)
    meta_task = client.meta()
    # The daily cabinet controls the manager's unprocessed inbox, not every
    # lead that happened to be created this month. Bitrix's standard NEW
    # status is the only source for this number.
    leads_task = client.lead_list({"ASSIGNED_BY_ID": user_id, "STATUS_ID": "NEW"}, LEAD_SELECT)
    won_task = client.deal_list({"CATEGORY_ID": 0, "ASSIGNED_BY_ID": user_id, ">=CLOSEDATE": month_start.isoformat(), "<CLOSEDATE": month_end.isoformat()}, PERSONAL_DEAL_SELECT)
    created_task = client.deal_list({"CATEGORY_ID": 0, "ASSIGNED_BY_ID": user_id, ">=DATE_CREATE": month_start.isoformat(), "<DATE_CREATE": month_end.isoformat()}, PERSONAL_DEAL_SELECT)
    calls_result, sales_result, reanimation_result, meta_result, leads_result, won_result, created_result = await asyncio.gather(calls_task, sales_task, reanimation_task, meta_task, leads_task, won_task, created_task, return_exceptions=True)

    calls = [row for row in calls_result if isinstance(row, dict) and str(row.get("PORTAL_USER_ID") or "") == str(user_id)] if isinstance(calls_result, list) else []
    successful = [row for row in calls if (duration_seconds({"CALL_DURATION": row.get("CALL_DURATION")}) or 0) >= SUCCESSFUL_CALL_SECONDS]
    deals = [row for result in (sales_result, reanimation_result) if isinstance(result, list) for row in result if isinstance(row, dict)]
    deals = list({str(row.get("ID") or index): row for index, row in enumerate(deals)}.values())
    deal_by_id = {str(row.get("ID") or ""): row for row in deals}
    portal = str(getattr(client, "portal", "")).rstrip("/")
    open_result, completed_result = await asyncio.gather(
        _deal_activities(client, list(deal_by_id), "N"),
        _deal_activities(client, list(deal_by_id), "Y"),
    )
    open_activities, activities_online = open_result
    completed_activities, completed_online = completed_result
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
    deferred_demand_ids = {
        deal_id for deal_id, deal in deal_by_id.items()
        if _is_deferred_demand_stage(stage_name(meta_result if isinstance(meta_result, dict) else {}, deal.get("STAGE_ID"), "DEAL_STAGE"))
    }
    # Deferred demand has a stricter workflow. It is evaluated later with the
    # Jarvis call agreement, rather than treating any old CRM comment as proof.
    promise_candidates = {
        deal_id: promised for deal_id, deal in deal_by_id.items()
        if deal_id not in deferred_demand_ids and deal_id not in open_by_deal
        if (promised := _comment_follow_up_date(deal.get("COMMENTS"), now.date())) and promised <= now.date()
    }
    last_touch_by_deal: dict[str, datetime] = {}
    recent_touches_by_deal: dict[str, list[dict[str, str]]] = {}
    for activity in completed_activities:
        created = _parse_datetime(activity.get("LAST_UPDATED") or activity.get("CREATED"), zone)
        owner = _owner_id(activity)
        if created and (owner not in last_touch_by_deal or created > last_touch_by_deal[owner]):
            last_touch_by_deal[owner] = created
        if owner not in deal_by_id or not created:
            continue
        note = re.sub(r"\s+", " ", str(activity.get("DESCRIPTION") or activity.get("SUBJECT") or "").strip())[:900]
        if not note:
            continue
        recent_touches_by_deal.setdefault(owner, []).append({
            "at": created.isoformat(), "kind": str(activity.get("TYPE_ID") or "activity"), "note": note,
        })
    for touches in recent_touches_by_deal.values():
        touches.sort(key=lambda row: row["at"], reverse=True)

    meta = meta_result if isinstance(meta_result, dict) else {}
    stages: dict[str, dict[str, Any]] = {}
    for deal in deals:
        label = stage_name(meta, deal.get("STAGE_ID"), "DEAL_STAGE")
        entry = stages.setdefault(label, {"name": label, "stage_id": str(deal.get("STAGE_ID") or ""), "count": 0, "amount": 0.0})
        entry["count"] += 1
        entry["amount"] += money(deal)
    preplan = [deal for deal in deals if str(deal.get("STAGE_ID") or "") in preplan_stage_ids(meta)]
    successful_stage_ids = successful_sale_stage_ids(meta)
    won = [deal for deal in won_result if isinstance(deal, dict) and str(deal.get("STAGE_ID") or "") in successful_stage_ids] if isinstance(won_result, list) else []
    created_sales = [deal for deal in created_result if isinstance(deal, dict)] if isinstance(created_result, list) else []
    # This is a cohort conversion.  A deal created this month becomes a sale
    # when it is now in a successful stage; it is not compared to an unrelated
    # list of deals closed in the month.
    created_won = [deal for deal in created_sales if str(deal.get("STAGE_ID") or "") in successful_stage_ids]
    conversion_percent = round(len(created_won) / len(created_sales) * 100, 1) if created_sales else None
    missing_source = [deal for deal in deals if not str(deal.get("SOURCE_ID") or "").strip()]
    missing_client_type = [deal for deal in deals if not str(deal.get(F_DEAL_CLIENT_TYPE) or "").strip()]
    iso_suot_candidates = [deal for deal in deals if not str(deal.get(F_SERVICE) or "").strip()]

    def deal_row(deal: dict[str, Any]) -> dict[str, Any]:
        label = stage_name(meta, deal.get("STAGE_ID"), "DEAL_STAGE")
        stage_sla = _stage_sla_state(label, _parse_datetime(deal.get("MOVED_TIME"), zone), now)
        deal_id = str(deal.get("ID") or "")
        last_touch = last_touch_by_deal.get(deal_id)
        return {"id": deal_id, "title": str(deal.get("TITLE") or "Без названия"), "company": str(deal.get("COMPANY_TITLE") or ""), "company_id": str(deal.get("COMPANY_ID") or ""), "stage": str(deal.get("STAGE_ID") or ""), "stage_name": label, "amount": round(money(deal), 2), "source": str(deal.get("SOURCE_ID") or ""), "service": str(deal.get(F_SERVICE) or ""), "created": str(deal.get("DATE_CREATE") or ""), "close_date": str(deal.get("CLOSEDATE") or ""), "comments": str(deal.get("COMMENTS") or ""), "url": _deal_url(portal, deal.get("ID")), "stage_sla": stage_sla, "last_touch_at": last_touch.isoformat() if last_touch else "", "recent_touches": recent_touches_by_deal.get(deal_id, [])[:3]}

    sla_breaches = [row for deal in deals if (row := deal_row(deal)).get("stage_sla") and row["stage_sla"].get("breached")]

    priorities = []
    for activity in overdue_activities:
        if (deal := deal_by_id.get(_owner_id(activity))) is None:
            continue
        due = deadline(activity)
        priorities.append({**deal_row(deal), "priority": "Просрочено CRM-дело", "due": due.date().isoformat() if due else "", "reason": f"Связаться в первую очередь: срок {due.strftime('%d.%m') if due else 'истёк'} — {str(activity.get('SUBJECT') or 'без темы')}"})
    if activities_online and completed_online:
        for deal_id, promised in promise_candidates.items():
            if (last_touch := last_touch_by_deal.get(deal_id)) and last_touch.date() >= promised:
                continue
            priorities.append({**deal_row(deal_by_id[deal_id]), "priority": "Обещанный контакт не подтверждён", "due": promised.isoformat(), "reason": f"В комментарии обещано связаться {promised.strftime('%d.%m')}; открытого дела и звонка после этой даты нет."})
    no_touch_cutoff = now - timedelta(days=7)
    week_without_touch = []
    if completed_online:
        for deal in deals:
            row = deal_row(deal)
            created = _parse_datetime(deal.get("DATE_CREATE") or deal.get("MOVED_TIME"), zone)
            last_touch = last_touch_by_deal.get(row["id"])
            if created and created > no_touch_cutoff:
                continue
            if last_touch and last_touch >= no_touch_cutoff:
                continue
            row["priority"] = "7 дней без касания"
            row["due"] = (last_touch or created or no_touch_cutoff).date().isoformat()
            row["reason"] = "По сделке нет подтверждённого завершённого касания 7 дней. После проверки руководитель может передать её другому менеджеру."
            week_without_touch.append(row)
            priorities.append(row)
    priorities.sort(key=lambda row: (row["priority"] != "Обещанный контакт не подтверждён", row["due"], row["title"]))

    active_rows = [deal_row(deal) for deal in deals]
    deferred_demand = [row for row in active_rows if row["id"] in deferred_demand_ids]
    scheduled_deal_ids = {
        deal_id for deal_id, items in open_by_deal.items()
        if any(deadline(item) is not None for item in items)
    }
    stage_durations: dict[str, dict[str, Any]] = {}
    for row in active_rows:
        sla = row.get("stage_sla") or {}
        actual = sla.get("actual_days")
        if not isinstance(actual, (int, float)):
            continue
        entry = stage_durations.setdefault(row["stage_name"], {
            "stage": row["stage_name"], "count": 0, "actual_total": 0.0,
            "limit_days": sla.get("limit_days"), "rule": sla.get("rule") or "Норма не задана",
            "breached_count": 0,
        })
        entry["count"] += 1
        entry["actual_total"] += float(actual)
        entry["breached_count"] += 1 if sla.get("breached") else 0
    stage_averages = []
    for entry in stage_durations.values():
        average_days = round(entry.pop("actual_total") / entry["count"], 1)
        stage_averages.append({**entry, "average_days": average_days})
    stage_averages.sort(key=lambda row: (-int(row["breached_count"]), -float(row["average_days"]), row["stage"]))

    linked_successful_calls = [call for call in successful if _call_deal_id(call) in deal_by_id]
    calls_with_next_step = 0
    for call in linked_successful_calls:
        call_at = _parse_datetime(call.get("CALL_START_DATE"), zone)
        activities = open_by_deal.get(_call_deal_id(call), [])
        if any(
            deadline(activity) is not None and (
                call_at is None or (_parse_datetime(activity.get("CREATED"), zone) or datetime.min.replace(tzinfo=zone)) >= call_at
            )
            for activity in activities
        ):
            calls_with_next_step += 1
    call_to_next_step = {
        "successful_linked_calls": len(linked_successful_calls),
        "with_next_step": calls_with_next_step,
        "percent": round(calls_with_next_step / len(linked_successful_calls) * 100, 1) if linked_successful_calls else None,
        "definition": "Среди успешных звонков, связанных со сделкой, доля тех, после которых в CRM есть открытое дело с датой. Звонки без связи со сделкой не учитываются.",
    }

    document_deadlines = []
    for row in active_rows:
        due = _document_deadline(" ".join((row.get("title") or "", row.get("comments") or "")), now.date())
        if due:
            document_deadlines.append({
                **row, "document_due": due.isoformat(), "days_left": (due - now.date()).days,
                "reason": f"В CRM указан срок документа / БИС: {due.strftime('%d.%m.%Y')}. Проверьте продление и свяжитесь с клиентом.",
            })
    document_deadlines.sort(key=lambda row: (int(row["days_left"]), row["title"]))

    return {
        "ok": True, "date": start.date().isoformat(), "period": period, "period_label": period_label, "period_start": start.date().isoformat(), "period_end": (end - timedelta(microseconds=1)).date().isoformat(), "user_id": str(user_id), "profile": {"name": str((meta.get("users") or {}).get(str(user_id)) or f"Сотрудник {user_id}")}, "generated_at": now.isoformat(),
        "availability": {"calls": "online" if isinstance(calls_result, list) else "unavailable", "tasks": "online" if activities_online else "unavailable", "comment_follow_up": "online" if activities_online and completed_online else "unavailable", "deferred_demand": "pending_call_analysis", "stage_sla": "online", "iso_suot_registry": "needs_connection"},
        "calls": {"successful_records": [{"id": str(call.get("ID") or ""), "title": "Звонок " + str(call.get("PHONE_NUMBER") or call.get("CALL_START_DATE") or ""), "created": str(call.get("CALL_START_DATE") or ""), "duration_seconds": int(float(call.get("CALL_DURATION") or 0))} for call in successful[:150]], "total": len(calls), "successful_from_minute": len(successful), "target": call_target, "remaining": max(0, call_target - len(successful)), "rule": "Успешный звонок — запись Bitrix с длительностью не менее 60 секунд."},
        "tasks": {"open_count": len(open_activities) if activities_online else None, "overdue_count": len(overdue_activities) if activities_online else None, "today_count": len(today_activities) if activities_online else None, "tomorrow_count": len(tomorrow_activities) if activities_online else None, "tomorrow_date": next_workday.isoformat(), "today": [_activity_row(row, deal_by_id[_owner_id(row)], portal) for row in today_activities[:12] if _owner_id(row) in deal_by_id], "tomorrow": [_activity_row(row, deal_by_id[_owner_id(row)], portal) for row in tomorrow_activities[:12] if _owner_id(row) in deal_by_id], "overdue": [_activity_row(row, deal_by_id[_owner_id(row)], portal) for row in overdue_activities[:50] if _owner_id(row) in deal_by_id]},
        "deals": {
            "active": active_rows, "deferred_demand": deferred_demand, "preplan": [deal_row(deal) for deal in preplan],
            "won": [deal_row(deal) for deal in won], "created": [deal_row(deal) for deal in created_sales],
            "created_won": [deal_row(deal) for deal in created_won], "active_count": len(deals),
            "target_active_count": 70, "needed_to_target": max(0, 70 - len(deals)),
            "overdue_count": len({_owner_id(row) for row in overdue_activities}) if activities_online else None,
            "without_open_task_count": len(without_activity) if activities_online else None,
            "missing_source_count": len(missing_source), "missing_client_type_count": len(missing_client_type),
            "missing_source": [deal_row(deal) for deal in missing_source],
            "missing_client_type": [deal_row(deal) for deal in missing_client_type],
            "overdue": [deal_row(deal_by_id[_owner_id(row)]) for row in overdue_activities[:50] if _owner_id(row) in deal_by_id],
            "without_open_task": [deal_row(row) for row in without_activity[:50]],
            "week_without_touch": week_without_touch[:50], "priorities": priorities[:50],
            "stages": sorted(stages.values(), key=lambda row: (-int(row["count"]), str(row["name"]))),
            "preplan_count": len(preplan), "preplan_amount": round(sum(money(row) for row in preplan), 2),
            "fact_count": len(won), "fact_amount": round(sum(money(row) for row in won), 2),
            "next_step": {
                "scheduled_count": len(scheduled_deal_ids) if activities_online else None,
                "active_count": len(deals),
                "percent": round(len(scheduled_deal_ids) / len(deals) * 100, 1) if activities_online and deals else None,
                "definition": "Активная сделка с открытым CRM-делом, у которого задана конкретная дата.",
            },
            "stage_averages": stage_averages, "document_deadlines": document_deadlines[:50],
            "call_to_next_step": call_to_next_step,
            "conversion": {"created_count": len(created_sales), "won_count": len(created_won), "percent": conversion_percent, "definition": "Из сделок, созданных в выбранном месяце, сколько уже находится в успешной стадии. Продажи, закрытые в этом месяце, показаны отдельно в «План / факт»."},
        },
        "leads": {"month_count": len(leads_result) if isinstance(leads_result, list) else 0, "month": [{"id": str(lead.get("ID") or ""), "title": str(lead.get("TITLE") or "Лид"), "created": str(lead.get("DATE_CREATE") or ""), "source": str(lead.get("SOURCE_ID") or ""), "url": f"{portal}/crm/lead/details/{lead.get('ID')}/" if str(lead.get("ID") or "").isdigit() else ""} for lead in leads_result if isinstance(lead, dict)] if isinstance(leads_result, list) else [], "definition": "Новые необработанные лиды: только лиды менеджера на стадии «Новые» прямо сейчас."},
        "stage_sla": {"status": "online", "message": "Срок считается от фактического перехода сделки на этап (MOVED_TIME). Сделки без этой даты не помечаются как нарушившие срок.", "breached_count": len(sla_breaches), "breached": sla_breaches[:50]},
        "iso_suot": {"status": "needs_connection", "message": "Реестр ИСО/СУОТ ещё не подключён к кабинету. Ниже — только сделки без заполненной услуги, а не вывод о потребности клиента.", "candidates": [deal_row(row) for row in iso_suot_candidates[:12]]}, "month": month_key,
    }
