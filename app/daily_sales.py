"""Bounded, read-only daily Sales report sourced directly from Bitrix24."""

import asyncio
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .metrics import (
    DEAL_SELECT,
    F_DEAL_CLIENT_TYPE,
    LEAD_SELECT,
    enum_label,
    source_name,
    stage_name,
    user_name,
)

def daily_bounds(value: str, timezone: str) -> tuple[datetime, datetime]:
    """Return a timezone-aware half-open interval for an ISO calendar day."""
    selected = date.fromisoformat(str(value or "")[:10])
    tz = ZoneInfo(timezone)
    start = datetime.combine(selected, time.min, tzinfo=tz)
    return start, start + timedelta(days=1)


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None
    return result if result >= 0 else None


def call_direction(activity: dict[str, Any]) -> str:
    """Normalize the documented Bitrix activity direction without guessing."""
    raw = str(activity.get("DIRECTION") or "").strip().upper()
    if raw in {"1", "IN", "INCOMING", "I"}:
        return "incoming"
    if raw in {"2", "OUT", "OUTGOING", "O"}:
        return "outgoing"
    return "unknown"


def statistic_direction(statistic: dict[str, Any]) -> str:
    """Normalize telephony statistics call types (not CRM activity directions)."""
    raw = str(statistic.get("CALL_TYPE") or "").strip()
    if raw == "1":
        return "outgoing"
    if raw in {"2", "3"}:
        return "incoming"
    return "unknown"


def statistic_as_call(statistic: dict[str, Any]) -> dict[str, Any]:
    """Make a telephony statistic consumable by the presentation aggregator."""
    return {
        "RESPONSIBLE_ID": statistic.get("PORTAL_USER_ID"),
        "DIRECTION": statistic_direction(statistic),
        "CALL_DURATION": statistic.get("CALL_DURATION"),
    }


def duration_seconds(activity: dict[str, Any]) -> float | None:
    """Read known Bitrix duration fields; unknown unit/value stays unavailable."""
    raw = activity.get("DURATION")
    if raw in (None, ""):
        raw = activity.get("CALL_DURATION")
    seconds = _number(raw)
    if seconds is None:
        return None
    unit = str(activity.get("DURATION_TYPE") or "").strip().lower()
    if unit in {"minute", "minutes", "min", "m"}:
        seconds *= 60
    elif unit in {"hour", "hours", "h"}:
        seconds *= 3600
    return seconds


def _availability(value: Any) -> tuple[list[dict[str, Any]], dict[str, str]]:
    if isinstance(value, Exception):
        return [], {"status": "unavailable"}
    if not isinstance(value, list):
        return [], {"status": "unavailable"}
    return [row for row in value if isinstance(row, dict)], {"status": "online"}


def _counter_rows(counter: Counter[str]) -> list[dict[str, Any]]:
    return [
        {"name": name, "count": count}
        for name, count in sorted(counter.items(), key=lambda row: (-row[1], row[0].casefold()))
    ]


def _nested_rows(values: dict[str, Counter[str]], child_key: str) -> list[dict[str, Any]]:
    rows = []
    for name in sorted(values, key=lambda item: item.casefold()):
        children = _counter_rows(values[name])
        rows.append({"name": name, "count": sum(row["count"] for row in children), child_key: children})
    return rows


def summarize_daily_sales(
    leads: list[dict[str, Any]],
    deals: list[dict[str, Any]],
    activities: list[dict[str, Any]],
    meta: dict[str, Any],
) -> dict[str, Any]:
    """Return presentation-safe aggregates for one already-filtered CRM day."""
    lead_sources: Counter[str] = Counter()
    lead_managers: dict[str, Counter[str]] = defaultdict(Counter)
    for lead in leads:
        source = str(source_name(meta, lead) or "Прочее")
        manager = str(user_name(meta, lead.get("ASSIGNED_BY_ID")) or "Не указан")
        lead_sources[source] += 1
        lead_managers[manager][source] += 1

    deal_sources: Counter[str] = Counter()
    deal_stages: dict[str, Counter[str]] = defaultdict(Counter)
    deal_managers: dict[str, Counter[str]] = defaultdict(Counter)
    for deal in deals:
        category_id = int(deal.get("CATEGORY_ID") or 0)
        source = str(source_name(meta, deal, category_id == 20) or "Прочее")
        entity = "DEAL_STAGE" if category_id == 0 else f"DEAL_STAGE_{category_id}"
        stage = str(stage_name(meta, deal.get("STAGE_ID"), entity) or "Не указана")
        manager = str(user_name(meta, deal.get("ASSIGNED_BY_ID")) or "Не указан")
        client_type = enum_label(meta, F_DEAL_CLIENT_TYPE, deal.get(F_DEAL_CLIENT_TYPE)) or "Не указан"
        deal_sources[source] += 1
        deal_stages[stage][source] += 1
        deal_managers[manager][str(client_type)] += 1

    calls_by_manager: dict[str, dict[str, float | int]] = defaultdict(
        lambda: {
            "incoming_count": 0, "outgoing_count": 0,
            "incoming_seconds": 0.0, "outgoing_seconds": 0.0,
            "unclassified_count": 0, "without_duration_count": 0,
        }
    )
    unclassified = 0
    without_duration = 0
    for activity in activities:
        manager = str(user_name(meta, activity.get("RESPONSIBLE_ID")) or "Не указан")
        direction = call_direction(activity)
        duration = duration_seconds(activity)
        row = calls_by_manager[manager]
        if direction == "unknown":
            row["unclassified_count"] += 1
            unclassified += 1
        else:
            row[f"{direction}_count"] += 1
            if duration is None:
                row["without_duration_count"] += 1
                without_duration += 1
            else:
                row[f"{direction}_seconds"] += duration

    call_rows = []
    for manager in sorted(calls_by_manager, key=lambda item: item.casefold()):
        row = calls_by_manager[manager]
        call_rows.append({
            "name": manager,
            "incoming_count": int(row["incoming_count"]),
            "outgoing_count": int(row["outgoing_count"]),
            "incoming_minutes": round(float(row["incoming_seconds"]) / 60, 1),
            "outgoing_minutes": round(float(row["outgoing_seconds"]) / 60, 1),
            "unclassified_count": int(row["unclassified_count"]),
            "without_duration_count": int(row["without_duration_count"]),
        })

    return {
        "leads": {
            "total": len(leads),
            "by_source": _counter_rows(lead_sources),
            "by_manager_source": _nested_rows(lead_managers, "sources"),
        },
        "deals": {
            "total": len(deals),
            "by_source": _counter_rows(deal_sources),
            "by_stage_source": _nested_rows(deal_stages, "sources"),
            "by_stage": _counter_rows(Counter({stage: sum(sources.values()) for stage, sources in deal_stages.items()})),
            "by_manager_client_type": _nested_rows(deal_managers, "client_types"),
        },
        "calls": {
            "total": len(activities),
            "by_manager": call_rows,
            "unclassified_count": unclassified,
            "without_duration_count": without_duration,
            "time_basis": "Дата начала звонка в телефонии Bitrix24",
        },
        "funnel": {
            "status": "not_available",
            "note": "Исторический остаток воронки на конец дня не показан: текущие карточки не являются подтверждённым снимком прошлого дня.",
        },
    }


async def build_daily_sales_report(client: Any, selected_date: str, timezone: str) -> dict[str, Any]:
    """Load one calendar day from Bitrix and make partial availability explicit."""
    start, end = daily_bounds(selected_date, timezone)
    lead_task = client.lead_list({">=DATE_CREATE": start.isoformat(), "<DATE_CREATE": end.isoformat()}, LEAD_SELECT)
    sales_deals_task = client.deal_list({"CATEGORY_ID": 0, ">=DATE_CREATE": start.isoformat(), "<DATE_CREATE": end.isoformat()}, DEAL_SELECT)
    reanimation_deals_task = client.deal_list({"CATEGORY_ID": 20, ">=DATE_CREATE": start.isoformat(), "<DATE_CREATE": end.isoformat()}, DEAL_SELECT)
    activities_task = client.list_all("voximplant.statistic.get", {
        "FILTER": {">=CALL_START_DATE": start.isoformat(), "<CALL_START_DATE": end.isoformat()},
        "SORT": "CALL_START_DATE",
        "ORDER": "ASC",
    })
    leads_result, sales_deals_result, reanimation_deals_result, activities_result, meta_result = await asyncio.gather(
        lead_task, sales_deals_task, reanimation_deals_task, activities_task, client.meta(), return_exceptions=True
    )
    if isinstance(meta_result, Exception) or not isinstance(meta_result, dict):
        raise RuntimeError("CRM metadata unavailable")
    leads, leads_availability = _availability(leads_result)
    sales_deals, sales_deals_availability = _availability(sales_deals_result)
    reanimation_deals, reanimation_deals_availability = _availability(reanimation_deals_result)
    deals = list({str(row.get("ID") or index): row for index, row in enumerate(sales_deals + reanimation_deals)}.values())
    deals_availability = {"status": "online"} if (
        sales_deals_availability["status"] == "online" and reanimation_deals_availability["status"] == "online"
    ) else {"status": "partial", "note": "Не все воронки сделок доступны"}
    statistics, calls_availability = _availability(activities_result)
    activities = [statistic_as_call(row) for row in statistics]
    report = summarize_daily_sales(leads, deals, activities, meta_result)
    report.update({
        "ok": True,
        "date": start.date().isoformat(),
        "generated_at": datetime.now(ZoneInfo(timezone)).isoformat(),
        "source": "Bitrix24 CRM (read-only)",
        "availability": {
            "leads": leads_availability,
            "deals": deals_availability,
            "calls": calls_availability,
        },
    })
    return report
