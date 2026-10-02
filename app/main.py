import asyncio
import hashlib
import hmac
import json
import copy
import math
import re
import secrets
import time
from calendar import monthrange
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Form, HTTPException, Query, Request
import httpx
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .bitrix import BitrixClient
from .metrics import DEAL_SELECT, F_DEAL_CLIENT_TYPE, build_snapshot, build_trends_light, derive_production_period, enum_label, filter_prod_details, filter_sales_details, month_bounds, parse_dt, period_bounds, production_weekly_dynamics, sales_block, source_name, user_name, week_of_month
from .nps import NPS_GROUP_ID, aggregate_automatic_nps, previous_calendar_week
from .recovery import SEPTEMBER_2026_DORMANT_BASELINE, restore_confirmed_september_dormant_baseline, restore_missing_production_plan
from .demo import demo_snapshot
from .key_tasks import build_key_tasks, build_task_workspace
from .acts_experts import ACTS_PROJECT_ID, build_acts_experts_report, valid_month as valid_acts_month
from .settings import settings
from .storage import Storage

STATIC = Path(__file__).parent / "static"
storage = Storage(settings.data_dir / "mavis_dashboard_v2.sqlite3", settings.supabase_url, settings.supabase_key)
client = BitrixClient(settings.bitrix_webhook)

cache = {}
detail_cache = {}
cache_time = {}
locks = {}
subscribers = set()
refresh_trigger = asyncio.Event()
last_error = None
sync_tasks = {}
trend_cache = {}
trend_cache_time = {}
clean_revenue_cache = {}
clean_revenue_cache_time = {}
clean_revenue_tasks = {}
clean_revenue_failures = {}
CLEAN_REVENUE_REFRESH_SECONDS = 60
CLEAN_REVENUE_FAILURE_COOLDOWN_SECONDS = 300
previous_month_refresh_at = 0.0
PREVIOUS_MONTH_REFRESH_SECONDS = 60 * 60
DERIVED_RANGE_CACHE_LIMIT = 8
derived_range_cache_time = {}
jarvis_operations_cache = {}
jarvis_operations_cache_time = {}
automatic_nps_cache = {}
automatic_nps_cache_time = {}
automatic_nps_tasks = {}
AUTOMATIC_NPS_REFRESH_SECONDS = 15 * 60
KEY_TASKS_REFRESH_SECONDS = 5 * 60
KEY_TASKS_PERSISTED_STALE_SECONDS = 24 * 60 * 60
key_task_cache = {}
key_task_cache_time = {}
key_task_refresh_tasks = {}
task_link_deal_cache = {}
task_link_deal_cache_time = {}
TASK_LINK_DEAL_REFRESH_SECONDS = 5 * 60
key_task_users_cache = []
key_task_users_cache_time = 0.0
communication_gap_cache = {}
COMMUNICATION_GAP_REFRESH_SECONDS = 5 * 60
COMMUNICATION_GAP_DAYS = 14
acts_experts_cache = {}
acts_experts_cache_time = {}
ACTS_EXPERTS_REFRESH_SECONDS = 60


def current_month():
    return datetime.now(ZoneInfo(settings.timezone)).strftime("%Y-%m")


async def load_acts_experts(month: str, force: bool = False) -> dict:
    """Return the live Acts project report without mixing it into KPI snapshot work."""
    selected_month = valid_acts_month(month, current_month())
    cached = acts_experts_cache.get(selected_month)
    if not force and cached and time.monotonic() - acts_experts_cache_time.get(selected_month, 0) < ACTS_EXPERTS_REFRESH_SECONDS:
        return cached
    stages_payload, tasks, meta = await asyncio.gather(
        client.call("task.stages.get", {"entityId": ACTS_PROJECT_ID}),
        client.acts_tasks_for_month(ACTS_PROJECT_ID, selected_month),
        client.meta(),
    )
    stages = stages_payload.get("result") or []
    if isinstance(stages, dict):
        stages = list(stages.values())
    report = build_acts_experts_report(tasks, meta.get("users") or {}, stages, selected_month, client.portal)
    report["generated_at"] = datetime.now(ZoneInfo(settings.timezone)).isoformat()
    report["refresh_seconds"] = ACTS_EXPERTS_REFRESH_SECONDS
    acts_experts_cache[selected_month] = report
    acts_experts_cache_time[selected_month] = time.monotonic()
    return report


def _key_task_cache_key(members):
    return ",".join(sorted(str(row.get("id") or "") for row in members if row.get("id")))


def _bitrix_deal_id_from_task_link(raw_url: str) -> str:
    """Return an ID only for a deal URL from this dashboard's Bitrix portal."""
    try:
        link = urlparse(str(raw_url or "").strip())
        portal = urlparse(client.portal)
    except (TypeError, ValueError):
        return ""
    if link.scheme not in {"http", "https"} or not link.hostname or link.hostname != portal.hostname:
        return ""
    match = re.search(r"/crm/deal/(?:details|show)/(\d+)(?:/|$)", link.path, re.IGNORECASE)
    return match.group(1) if match else ""


def _task_deal_preview(deal: dict, stage_names: dict[str, str], contact_names: dict[str, str]) -> dict:
    raw_amount = deal.get("OPPORTUNITY") or 0
    try:
        amount = float(raw_amount)
    except (TypeError, ValueError):
        amount = 0.0
    if not math.isfinite(amount):
        amount = 0.0
    contact_id = str(deal.get("CONTACT_ID") or "")
    client_name = str(deal.get("COMPANY_TITLE") or "").strip() or contact_names.get(contact_id, "")
    return {
        "id": str(deal.get("ID") or ""),
        "client": client_name or str(deal.get("TITLE") or "Сделка Bitrix24"),
        "amount": round(amount, 2),
        "stage": str(stage_names.get(str(deal.get("STAGE_ID") or "")) or deal.get("STAGE_ID") or "Не указана"),
    }


async def enrich_task_workspace_deal_links(workspace: dict) -> dict:
    """Attach small live CRM previews without making task loading depend on Bitrix."""
    tasks = list(workspace.get("tasks") or [])
    link_ids = {
        _bitrix_deal_id_from_task_link(link.get("url"))
        for task in tasks for link in (task.get("links") or [])
        if isinstance(link, dict)
    }
    link_ids.discard("")
    if not link_ids:
        return workspace
    now = time.monotonic()
    previews = {
        deal_id: task_link_deal_cache[deal_id]
        for deal_id in link_ids
        if deal_id in task_link_deal_cache
        and now - task_link_deal_cache_time.get(deal_id, 0) < TASK_LINK_DEAL_REFRESH_SECONDS
    }
    missing = sorted(link_ids - previews.keys())
    if missing:
        try:
            deals, meta = await asyncio.wait_for(asyncio.gather(
                client.deal_list({"@ID": missing}, ["ID", "TITLE", "OPPORTUNITY", "STAGE_ID", "COMPANY_TITLE", "CONTACT_ID"]),
                client.meta(),
            ), timeout=6)
            contact_ids = sorted({str(deal.get("CONTACT_ID") or "") for deal in deals or [] if not str(deal.get("COMPANY_TITLE") or "").strip() and deal.get("CONTACT_ID")})
            contact_names = {}
            if contact_ids:
                contacts = await asyncio.wait_for(client.list_all("crm.contact.list", {
                    "filter": {"@ID": contact_ids}, "select": ["ID", "NAME", "LAST_NAME", "SECOND_NAME"],
                }), timeout=4)
                contact_names = {
                    str(contact.get("ID") or ""): " ".join(str(contact.get(field) or "").strip() for field in ("NAME", "SECOND_NAME", "LAST_NAME")).strip()
                    for contact in contacts or []
                }
            stage_names = (meta or {}).get("statuses") or {}
            for deal in deals or []:
                deal_id = str(deal.get("ID") or "")
                if deal_id in link_ids:
                    preview = _task_deal_preview(deal, stage_names, contact_names)
                    previews[deal_id] = preview
                    task_link_deal_cache[deal_id] = preview
                    task_link_deal_cache_time[deal_id] = now
        except Exception:
            # A CRM delay must not make the task workspace blank. Cached previews
            # remain available; uncached cards continue to show their direct link.
            pass
    for task in tasks:
        links = []
        for link in task.get("links") or []:
            if not isinstance(link, dict):
                continue
            deal_id = _bitrix_deal_id_from_task_link(link.get("url"))
            links.append({**link, **({"deal": previews[deal_id]} if deal_id in previews else {})})
        task["links"] = links
    return workspace


async def key_task_available_users():
    """Small, cached user list for the manual task-owner picker."""
    global key_task_users_cache, key_task_users_cache_time
    if key_task_users_cache and time.monotonic() - key_task_users_cache_time < 15 * 60:
        return list(key_task_users_cache)
    users = await client.list_all("user.get", {"FILTER": {"ACTIVE": True}})
    output = []
    for user in users or []:
        user_id = str(user.get("ID") or "").strip()
        name = " ".join(part for part in [user.get("NAME"), user.get("LAST_NAME")] if part).strip()
        if user_id and name:
            output.append({"id": user_id, "name": name})
    key_task_users_cache = sorted(output, key=lambda row: row["name"].casefold())
    key_task_users_cache_time = time.monotonic()
    return list(key_task_users_cache)


async def refresh_key_tasks(members, cache_key):
    """Compatibility cache refresh for dashboard-owned key tasks."""
    try:
        now = datetime.now(ZoneInfo(settings.timezone))
        payload = {
            "ok": True,
            "generated_at": now.isoformat(),
            "members": members,
            **build_key_tasks(storage.manual_key_tasks(), members, now, settings.timezone),
        }
        key_task_cache[cache_key] = payload
        key_task_cache_time[cache_key] = time.monotonic()
        await asyncio.to_thread(storage.set_key_task_cache, cache_key, payload)
        await broadcast({"type": "key-tasks"})
        return payload
    finally:
        key_task_refresh_tasks.pop(cache_key, None)


def schedule_key_tasks_refresh(members, cache_key):
    task = key_task_refresh_tasks.get(cache_key)
    if task and not task.done():
        return task
    task = asyncio.create_task(refresh_key_tasks(members, cache_key))
    key_task_refresh_tasks[cache_key] = task
    return task


def _automatic_nps_key(as_of=None):
    as_of = as_of or datetime.now(ZoneInfo(settings.timezone))
    return previous_calendar_week(as_of, settings.timezone)[0].date().isoformat()


def _automatic_nps_empty(as_of=None, status="updating"):
    week_start, week_end = previous_calendar_week(as_of, settings.timezone)
    return {
        "status": status,
        "date_basis": "created_date",
        "week_start": week_start.date().isoformat(),
        "week_end": (week_end - timedelta(days=1)).date().isoformat(),
        "overall": {"value": None, "count": 0},
        "experts": {},
        "fetched_task_count": 0,
        "completed_task_count": 0,
        "created_in_week_count": 0,
        "excluded_without_score": 0,
        "unmatched_expert_count": 0,
    }


def cached_automatic_nps(as_of=None):
    cached = automatic_nps_cache.get(_automatic_nps_key(as_of))
    return dict(cached) if isinstance(cached, dict) else _automatic_nps_empty(as_of)


def schedule_automatic_nps_refresh(as_of=None):
    as_of = as_of or datetime.now(ZoneInfo(settings.timezone))
    key = _automatic_nps_key(as_of)
    task = automatic_nps_tasks.get(key)
    if task and not task.done():
        return task
    if key in automatic_nps_cache and time.monotonic() - automatic_nps_cache_time.get(key, 0) < AUTOMATIC_NPS_REFRESH_SECONDS:
        return None

    async def runner():
        try:
            week_start, week_end = previous_calendar_week(as_of, settings.timezone)
            tasks = await client.tasks_for_group(NPS_GROUP_ID, week_start, week_end)
            result = aggregate_automatic_nps(tasks or [], as_of, settings.timezone)
            for expert in result["experts"].values():
                for task_row in expert["tasks"]:
                    task_row["task_url"] = f"{client.portal}/workgroups/group/{NPS_GROUP_ID}/tasks/task/view/{task_row['id']}/"
            automatic_nps_cache[key] = result
            automatic_nps_cache_time[key] = time.monotonic()
            await broadcast({"type": "refresh", "automatic_nps": key})
        except Exception:
            previous = automatic_nps_cache.get(key)
            if isinstance(previous, dict):
                automatic_nps_cache[key] = {**previous, "status": "stale"}
            else:
                automatic_nps_cache[key] = _automatic_nps_empty(as_of, status="unavailable")
            automatic_nps_cache_time[key] = time.monotonic()
        finally:
            automatic_nps_tasks.pop(key, None)

    task = asyncio.create_task(runner())
    automatic_nps_tasks[key] = task
    return task


def prewarm_months(month: str) -> list[tuple[str, str]]:
    """The two periods users can open without a calendar selection."""
    year, number = (int(part) for part in month.split("-", 1))
    if number == 1:
        year, number = year - 1, 12
    else:
        number -= 1
    return [(month, "month"), (f"{year:04d}-{number:02d}", "month")]


def clean_revenue_period(month: str):
    try:
        year, number = (int(part) for part in month.split("-", 1))
        return f"{year:04d}-{number:02d}-01", f"{year:04d}-{number:02d}-{monthrange(year, number)[1]:02d}"
    except (TypeError, ValueError):
        return "", ""


def clean_revenue_overdue_rows(payload: dict) -> list[dict]:
    """Normalize finance-ledger arrears before exposing them to the browser."""
    portal = client.portal if str(client.webhook or "").startswith("https://") else ""
    rows = []
    for source in payload.get("overdueScheduleRows") or []:
        if not isinstance(source, dict):
            continue
        deal_id = str(source.get("dealId") or "").strip()
        schedule_id = str(source.get("scheduleId") or "").strip()
        pay_date = str(source.get("date") or "")[:10]
        try:
            remaining = float(source.get("remaining"))
            planned = float(source.get("planned") or 0)
            bank_confirmed = float(source.get("bankConfirmed") or 0)
            manual_confirmed = float(source.get("manualConfirmed") or 0)
        except (TypeError, ValueError):
            continue
        values = (remaining, planned, bank_confirmed, manual_confirmed)
        if not (deal_id.isdigit() and schedule_id and pay_date and remaining > 0 and all(math.isfinite(value) for value in values)):
            continue
        rows.append({
            "deal_id": deal_id,
            "deal_title": str(source.get("dealTitle") or f"Сделка №{deal_id}")[:500],
            "stage": str(source.get("stageName") or "—")[:500],
            "date": pay_date,
            "planned": round(max(0.0, planned), 2),
            "bank_confirmed": round(max(0.0, bank_confirmed), 2),
            "manual_confirmed": round(max(0.0, manual_confirmed), 2),
            "remaining": round(max(0.0, remaining), 2),
            "url": f"{portal}/crm/deal/details/{deal_id}/" if portal else "",
        })
    return sorted(rows, key=lambda row: (row["date"], row["deal_title"], row["deal_id"]))


def clean_revenue_deal_rows(payload: dict) -> list[dict]:
    """Normalize exact per-deal values emitted by the payment schedule."""
    rows = []
    for source in payload.get("dealRevenueRows") or []:
        if not isinstance(source, dict):
            continue
        deal_id = str(source.get("dealId") or "").strip()
        try:
            bank_confirmed = float(source.get("bankConfirmed") or 0)
            manual_confirmed = float(source.get("manualConfirmed") or 0)
            contractor_applied = float(source.get("contractorApplied") or 0)
            clean_revenue = float(source.get("cleanRevenue") or 0)
        except (TypeError, ValueError):
            continue
        values = (bank_confirmed, manual_confirmed, contractor_applied, clean_revenue)
        if not (deal_id.isdigit() and all(math.isfinite(value) for value in values)):
            continue
        rows.append({
            "deal_id": deal_id,
            "deal_title": str(source.get("dealTitle") or f"Сделка №{deal_id}")[:500],
            "bank_confirmed": round(bank_confirmed, 2),
            "manual_confirmed": round(manual_confirmed, 2),
            "contractor_applied": round(contractor_applied, 2),
            "clean_revenue": round(clean_revenue, 2),
        })
    return sorted(rows, key=lambda row: (row["deal_title"], row["deal_id"]))


def clean_revenue_payment_rows(payload: dict) -> list[dict]:
    """Normalize dated payment-ledger rows for the net weekly breakdown."""
    rows = []
    for source in payload.get("paymentRevenueRows") or []:
        if not isinstance(source, dict):
            continue
        deal_id = str(source.get("dealId") or "").strip()
        payment_date = str(source.get("date") or "")[:10]
        try:
            datetime.strptime(payment_date, "%Y-%m-%d")
            bank_confirmed = float(source.get("bankConfirmed") or 0)
            manual_confirmed = float(source.get("manualConfirmed") or 0)
            contractor_applied = float(source.get("contractorApplied") or 0)
            clean_revenue = float(source.get("cleanRevenue") or 0)
        except (TypeError, ValueError):
            continue
        values = (bank_confirmed, manual_confirmed, contractor_applied, clean_revenue)
        if not (deal_id.isdigit() and all(math.isfinite(value) for value in values)):
            continue
        rows.append({
            "deal_id": deal_id,
            "deal_title": str(source.get("dealTitle") or f"Сделка №{deal_id}")[:500],
            "date": payment_date,
            "bank_confirmed": round(bank_confirmed, 2),
            "manual_confirmed": round(manual_confirmed, 2),
            "contractor_applied": round(contractor_applied, 2),
            "clean_revenue": round(clean_revenue, 2),
        })
    return sorted(rows, key=lambda row: (row["date"], row["deal_title"], row["deal_id"]))


async def enrich_clean_revenue_deal_rows(month: str, rows: list[dict]) -> list[dict]:
    """Attach the dashboard's exact sales-group classification to ledger rows."""
    if not rows:
        return []
    month_start, _, _, _ = month_bounds(month, settings.timezone)
    deal_ids = list(dict.fromkeys(row["deal_id"] for row in rows))
    try:
        meta = await client.meta()
        raw_deals = []
        for offset in range(0, len(deal_ids), 50):
            raw_deals.extend(await client.deal_list({"@ID": deal_ids[offset:offset + 50]}, DEAL_SELECT) or [])
        deals = {str(deal.get("ID") or ""): deal for deal in raw_deals}
    except Exception:
        # Financial values stay valid even if the CRM lookup is briefly down;
        # the browser will show them as not yet classified instead of guessing.
        deals = {}
        meta = {}

    enriched = []
    for row in rows:
        deal = deals.get(row["deal_id"]) or {}
        created = parse_dt(deal.get("DATE_CREATE"), month_start.tzinfo)
        category_id = int(deal.get("CATEGORY_ID") or 0) if deal else None
        source = source_name(meta, deal) if deal else ""
        client_type = enum_label(meta, F_DEAL_CLIENT_TYPE, deal.get(F_DEAL_CLIENT_TYPE)) if deal else ""
        source_missing = not str(deal.get("SOURCE_ID") or "").strip() and not str(deal.get("SOURCE_DESCRIPTION") or "").strip()
        group = sales_block(client_type, source, source_missing=source_missing) if category_id == 0 else "Не распределено"
        period_type = "current" if created and month_start <= created else "previous"
        enriched.append({
            **row,
            "group": group if deal else "Не распределено",
            "period_type": period_type,
            "manager": user_name(meta, deal.get("ASSIGNED_BY_ID")) if deal else "",
            "source": source,
            "client_type": client_type or "Не указан",
            "url": f"{client.portal}/crm/deal/details/{row['deal_id']}/" if deal else "",
        })
    return enriched


async def load_clean_revenue(month: str):
    """Fetch the single financial source of truth without exposing it to the browser."""
    if not settings.clean_revenue_url or not settings.clean_revenue_token:
        return {"status": "not_configured", "value": None}
    target = urlparse(settings.clean_revenue_url)
    if target.scheme != "https" or not target.netloc:
        return {"status": "invalid_configuration", "value": None}
    date_from, date_to = clean_revenue_period(month)
    if not date_from:
        return {"status": "invalid_period", "value": None}
    cached = clean_revenue_cache.get(month)
    if cached and time.monotonic() - clean_revenue_cache_time.get(month, 0) < 60:
        return cached
    try:
        # The payment ledger reconciles stage history and contractor allocations.
        # It is materially heavier than the regular KPI snapshot, but its result
        # is cached below, so allow the first monthly calculation to finish.
        async with httpx.AsyncClient(timeout=75.0, follow_redirects=False) as session:
            response = await session.get(
                settings.clean_revenue_url,
                params={"date_from": date_from, "date_to": date_to, "include_overdue": "0"},
                headers={"Authorization": f"Bearer {settings.clean_revenue_token}", "Accept": "application/json"},
            )
        try:
            payload = response.json()
        except ValueError:
            return {"status": "unavailable", "value": None, "reason": "source_invalid_json"}
        if response.status_code != 200:
            source_reason = str(payload.get("reason") or "")
            source_method = str(payload.get("method") or "")
            safe_methods = {"batch", "crm.category.list", "crm.deal.list", "crm.stagehistory.list", "entity.item.get"}
            if source_reason == "BitrixCallError" and source_method in safe_methods:
                safe_suffix = f"_bitrix_{source_method.replace('.', '_')}"
            else:
                safe_suffix = f"_{source_reason.lower()}" if source_reason in {"RuntimeError", "HTTPError", "ConnectionError", "Timeout"} else ""
            return {"status": "unavailable", "value": None, "reason": f"source_http_{response.status_code}{safe_suffix}"}
        if not isinstance(payload, dict):
            return {"status": "unavailable", "value": None, "reason": "source_invalid_payload"}
        value = float(payload.get("cleanRevenue"))
        contractor_amount = float(payload.get("contractorAmount"))
        if not payload.get("ok") or not math.isfinite(value) or not math.isfinite(contractor_amount):
            return {"status": "unavailable", "value": None, "reason": "source_invalid_payload"}
        deal_revenue_rows = await enrich_clean_revenue_deal_rows(month, clean_revenue_deal_rows(payload))
        payment_revenue_rows = await enrich_clean_revenue_deal_rows(month, clean_revenue_payment_rows(payload))
        result = {
            "status": "online",
            "value": round(value, 2),
            "contractor_amount": round(contractor_amount, 2),
            # The confirmed incoming amount is deliberately derived from the
            # same ledger values shown to the user: clean revenue already has
            # the contractor reserve deducted, so adding it back reconciles
            # the two financial cards exactly.
            "incoming_amount": round(value + contractor_amount, 2),
            "date_from": str(payload.get("dateFrom") or date_from),
            "date_to": str(payload.get("dateTo") or date_to),
            "generated_at": str(payload.get("generatedAt") or ""),
            "overdue_schedule_available": isinstance(payload.get("overdueScheduleRows"), list),
            "overdue_schedule_rows": clean_revenue_overdue_rows(payload),
            "deal_revenue_available": isinstance(payload.get("dealRevenueRows"), list),
            # Exact schedule-ledger net revenue, connected to the deal and
            # classified by the same rules as the sales dashboard.
            "deal_revenue_rows": deal_revenue_rows,
            "payment_revenue_available": isinstance(payload.get("paymentRevenueRows"), list),
            "payment_revenue_rows": payment_revenue_rows,
        }
        clean_revenue_cache[month] = result
        clean_revenue_cache_time[month] = time.monotonic()
        return result
    except httpx.TimeoutException:
        return {"status": "unavailable", "value": None, "reason": "source_timeout"}
    except httpx.HTTPError:
        return {"status": "unavailable", "value": None, "reason": "source_network_error"}
    except (TypeError, ValueError):
        return {"status": "unavailable", "value": None, "reason": "source_invalid_payload"}
    except Exception:
        previous = clean_revenue_cache.get(month)
        if previous:
            return {**previous, "status": "stale"}
        return {"status": "unavailable", "value": None, "reason": "source_unexpected_error"}


def _clean_revenue_storage_key(month: str) -> str:
    return f"clean_revenue_cache:{month}"


def cached_clean_revenue(month: str) -> dict:
    """Return the last validated finance result without blocking a request."""
    cached = clean_revenue_cache.get(month)
    if isinstance(cached, dict) and cached.get("status") in {"online", "stale"}:
        return dict(cached)
    return {"status": "updating", "value": None, "contractor_amount": None}


def schedule_clean_revenue_refresh(month: str):
    """Refresh finance once in background; never make an API response wait."""
    task = clean_revenue_tasks.get(month)
    if task and not task.done():
        return task
    cached_at = clean_revenue_cache_time.get(month, 0)
    if clean_revenue_cache.get(month) and time.monotonic() - cached_at < CLEAN_REVENUE_REFRESH_SECONDS:
        return None
    failure = clean_revenue_failures.get(month)
    if failure and time.monotonic() - failure["at"] < CLEAN_REVENUE_FAILURE_COOLDOWN_SECONDS:
        return None

    async def runner():
        try:
            # Storage uses a synchronous Supabase client. Hydrate it away from
            # the event loop, then keep serving that last confirmed value while
            # the financial source recalculates in the background.
            if month not in clean_revenue_cache:
                saved = await asyncio.to_thread(storage.get_setting, _clean_revenue_storage_key(month), {})
                if isinstance(saved, dict) and saved.get("status") == "online":
                    clean_revenue_cache[month] = {
                        **{key: value for key, value in saved.items() if key != "saved_at"},
                        "cached_snapshot": True,
                    }
                    clean_revenue_cache_time[month] = 0
                    await broadcast({"type": "refresh", "month": month})
            result = await load_clean_revenue(month)
            if isinstance(result, dict) and result.get("status") == "online":
                clean_revenue_cache[month] = result
                clean_revenue_cache_time[month] = time.monotonic()
                clean_revenue_failures.pop(month, None)
                await asyncio.to_thread(storage.set_setting, _clean_revenue_storage_key(month), {
                    **result, "saved_at": datetime.now(ZoneInfo(settings.timezone)).isoformat(),
                })
                await broadcast({"type": "refresh", "month": month})
            else:
                clean_revenue_failures[month] = {
                    "at": time.monotonic(),
                    "reason": str((result or {}).get("reason") or "source_unavailable"),
                }
                previous = clean_revenue_cache.get(month)
                if isinstance(previous, dict) and previous.get("value") is not None:
                    clean_revenue_cache[month] = {
                        **previous,
                        "status": "stale",
                        "last_attempt": datetime.now(ZoneInfo(settings.timezone)).isoformat(),
                    }
                    await broadcast({"type": "refresh", "month": month})
        finally:
            clean_revenue_tasks.pop(month, None)

    task = asyncio.create_task(runner())
    clean_revenue_tasks[month] = task
    return task


async def load_jarvis_operations(resource: str, params: dict[str, str] | None = None):
    """Proxy a bounded read-only Jarvis payload so its token never reaches the browser."""
    allowed = {"sales-calls", "crm-audit", "marketing", "reactivation-recommendations"}
    if resource not in allowed:
        return {"ok": False, "status": "invalid_resource"}
    if not settings.jarvis_operations_url or not settings.jarvis_operations_token:
        return {"ok": False, "status": "not_configured"}
    target = urlparse(settings.jarvis_operations_url)
    if target.scheme != "https" or not target.netloc:
        return {"ok": False, "status": "invalid_configuration"}
    cache_key = resource + ":" + json.dumps(params or {}, sort_keys=True)
    cached = jarvis_operations_cache.get(cache_key)
    if cached and time.monotonic() - jarvis_operations_cache_time.get(cache_key, 0) < 60:
        return cached
    try:
        url = settings.jarvis_operations_url.rstrip("/") + f"/api/integrations/operations/{resource}"
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=False) as session:
            async with session.stream(
                "GET", url, params=params or {}, headers={"Authorization": f"Bearer {settings.jarvis_operations_token}", "Accept": "application/json"}
            ) as response:
                if response.status_code != 200 or int(response.headers.get("Content-Length") or 0) > 2 * 1024 * 1024:
                    raise ValueError("invalid Jarvis response")
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 2 * 1024 * 1024:
                        raise ValueError("Jarvis response too large")
        payload = json.loads(raw)
        if not isinstance(payload, dict) or not payload.get("ok"):
            raise ValueError("invalid Jarvis payload")
        result = {"ok": True, "status": "online", "data": payload}
        jarvis_operations_cache[cache_key] = result
        jarvis_operations_cache_time[cache_key] = time.monotonic()
        return result
    except Exception:
        previous = jarvis_operations_cache.get(cache_key)
        if previous:
            return {**previous, "status": "stale"}
        return {"ok": False, "status": "unavailable"}


async def reactivate_jarvis_deal(deal_id: str):
    """Forward one confirmed action to Jarvis without exposing its token."""
    if not deal_id.isdigit():
        raise HTTPException(400, "Некорректный ID сделки")
    if not settings.jarvis_operations_url or not settings.jarvis_operations_token:
        raise HTTPException(503, "Интеграция Jarvis не настроена")
    target = urlparse(settings.jarvis_operations_url)
    if target.scheme != "https" or not target.netloc:
        raise HTTPException(503, "Некорректная настройка Jarvis")
    url = (
        settings.jarvis_operations_url.rstrip("/")
        + f"/api/integrations/operations/reactivation-recommendations/{deal_id}/reactivate"
    )
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as session:
            response = await session.post(
                url,
                headers={"Authorization": f"Bearer {settings.jarvis_operations_token}", "Accept": "application/json"},
                json={"actor": "dashboard-full-access"},
            )
        payload = response.json()
    except Exception as exc:
        raise HTTPException(503, "Jarvis временно недоступен") from exc
    if response.status_code != 200 or not isinstance(payload, dict) or not payload.get("ok"):
        message = payload.get("error") if isinstance(payload, dict) else "Перенос не подтверждён Jarvis"
        raise HTTPException(409, str(message or "Перенос не подтверждён Jarvis"))
    jarvis_operations_cache.pop("reactivation-recommendations:{}", None)
    jarvis_operations_cache_time.pop("reactivation-recommendations:{}", None)
    return payload


async def _recent_call_activities(owner_type_id: int, owner_ids: list[str], since: datetime):
    """Return recent call activities for a bounded set of CRM owners.

    Activity history can be much larger than the sales funnel.  Querying only
    active sales deals and their companies keeps the assistant's read-only
    context small while still answering the manager's follow-up question.
    """
    unique_ids = list(dict.fromkeys(str(value) for value in owner_ids if str(value).strip()))
    if not unique_ids:
        return []
    fields = ["ID", "OWNER_ID", "OWNER_TYPE_ID", "TYPE_ID", "CREATED", "LAST_UPDATED", "COMPLETED"]

    async def load_chunk(chunk):
        return await client.list_all("crm.activity.list", {
            "order": {"CREATED": "DESC", "ID": "DESC"},
            "filter": {
                "TYPE_ID": 2,
                "OWNER_TYPE_ID": owner_type_id,
                "OWNER_ID": chunk,
                "COMPLETED": "Y",
                ">=CREATED": since.isoformat(),
            },
            "select": fields,
        }) or []

    rows = await asyncio.gather(*(load_chunk(unique_ids[offset:offset + 50]) for offset in range(0, len(unique_ids), 50)))
    return [row for group in rows for row in group if isinstance(row, dict)]


async def load_sales_communication_gaps(now: datetime | None = None):
    """Build an exact, compact answer to "which active companies were not called".

    A company is in the gap list only when it has an open deal in the sales
    funnel and neither that deal nor the company itself has a CRM call activity
    during the last 14 days.  The check intentionally uses live CRM activities,
    rather than the dashboard's sales snapshot or the one-day Jarvis feed.
    """
    now = now or datetime.now(ZoneInfo(settings.timezone))
    cache_key = now.date().isoformat()
    cached = communication_gap_cache.get(cache_key)
    if cached and time.monotonic() - cached[0] < COMMUNICATION_GAP_REFRESH_SECONDS:
        return copy.deepcopy(cached[1])

    since = now - timedelta(days=COMMUNICATION_GAP_DAYS)
    try:
        deals = await client.deal_list({"CATEGORY_ID": 0, "CLOSED": "N"}, [
            "ID", "TITLE", "COMPANY_ID", "ASSIGNED_BY_ID", "STAGE_ID",
        ]) or []
        company_deals = {}
        without_company = 0
        for deal in deals:
            company_id = str(deal.get("COMPANY_ID") or "").strip()
            if not company_id:
                without_company += 1
                continue
            company_deals.setdefault(company_id, []).append(deal)

        company_ids = list(company_deals)
        company_rows = []
        for offset in range(0, len(company_ids), 50):
            company_rows.extend(await client.list_all("crm.company.list", {
                "order": {"ID": "ASC"},
                "filter": {"@ID": company_ids[offset:offset + 50]},
                "select": ["ID", "TITLE"],
            }) or [])
        company_names = {
            str(row.get("ID") or ""): str(row.get("TITLE") or f"Компания {row.get('ID')}")
            for row in company_rows if isinstance(row, dict) and row.get("ID")
        }

        deal_calls, company_calls, meta = await asyncio.gather(
            _recent_call_activities(2, [str(deal.get("ID") or "") for deal in deals], since),
            _recent_call_activities(4, company_ids, since),
            client.meta(),
        )
        recent_company_ids = set()
        deal_company = {
            str(deal.get("ID") or ""): company_id
            for company_id, rows in company_deals.items() for deal in rows
        }
        for activity in deal_calls:
            company_id = deal_company.get(str(activity.get("OWNER_ID") or ""))
            if company_id:
                recent_company_ids.add(company_id)
        for activity in company_calls:
            company_id = str(activity.get("OWNER_ID") or "")
            if company_id in company_deals:
                recent_company_ids.add(company_id)

        gaps = []
        stage_labels = (meta.get("status_by_entity") or {}).get("DEAL_STAGE") or {}
        for company_id, rows in company_deals.items():
            if company_id in recent_company_ids:
                continue
            primary = rows[0]
            manager_id = primary.get("ASSIGNED_BY_ID")
            gaps.append({
                "company_id": company_id,
                "company": company_names.get(company_id) or f"Компания {company_id}",
                "active_deals": len(rows),
                "deal_id": str(primary.get("ID") or ""),
                "deal_title": str(primary.get("TITLE") or ""),
                "manager": user_name(meta, manager_id),
                "stage": stage_labels.get(str(primary.get("STAGE_ID") or "")) or str(primary.get("STAGE_ID") or ""),
                "url": f"{client.portal}/crm/deal/details/{primary.get('ID')}/" if primary.get("ID") else "",
            })
        gaps.sort(key=lambda row: (row["manager"], row["company"].casefold(), row["company_id"]))
        result = {
            "status": "online",
            "checked_at": now.isoformat(),
            "days_without_call": COMMUNICATION_GAP_DAYS,
            "active_companies": len(company_deals),
            "active_deals_without_company": without_company,
            "companies_without_call_count": len(gaps),
            "companies_without_call": gaps[:80],
            "scope_note": (
                "Проверены только компании с активными сделками отдела продаж. "
                "Компания попадает в список, если в CRM нет завершённого звонка (активность TYPE_ID=2) "
                "по её активной сделке или по самой компании за последние 14 дней."
            ),
        }
    except Exception:
        result = {
            "status": "unavailable",
            "days_without_call": COMMUNICATION_GAP_DAYS,
            "scope_note": "История звонков CRM временно недоступна; число компаний не рассчитано.",
        }
    communication_gap_cache[cache_key] = (time.monotonic(), copy.deepcopy(result))
    return result


SNAPSHOT_SCHEMA_VERSION = "sales-tail-v3"


def persistent_snapshot_key(month: str, period: str, custom_start: str = "", custom_end: str = ""):
    return "|".join([SNAPSHOT_SCHEMA_VERSION,month,period,custom_start or "",custom_end or ""])


async def warm_snapshot_from_storage(month: str, period: str, custom_start: str = "", custom_end: str = ""):
    key=(month,period,custom_start or "",custom_end or "")
    if key in cache and key in detail_cache:return True
    pkey=persistent_snapshot_key(month,period,custom_start,custom_end)
    try:
        saved, saved_details = await asyncio.gather(
            asyncio.to_thread(storage.snapshot_cache,pkey),
            asyncio.to_thread(storage.detail_snapshot_cache,pkey),
        )
    except Exception:
        return False
    snap=(saved or {}).get("snapshot") if isinstance(saved,dict) else None
    details=(saved_details or {}).get("details") if isinstance(saved_details,dict) else None
    if not isinstance(snap,dict) or not snap.get("ok"):return False
    cache[key]=snap
    cache_time[key]=0
    detail_cache[key]=details if isinstance(details,dict) else {}
    return True

async def warm_details_from_storage(month: str, period: str, custom_start: str = "", custom_end: str = ""):
    key=(month,period,custom_start or "",custom_end or "")
    existing=detail_cache.get(key)
    if isinstance(existing,dict) and existing:
        return True
    pkey=persistent_snapshot_key(month,period,custom_start,custom_end)
    try:
        saved=await asyncio.to_thread(storage.detail_snapshot_cache,pkey)
    except Exception:
        return False
    details=(saved or {}).get("details") if isinstance(saved,dict) else None
    if not isinstance(details,dict) or not details:
        return False
    detail_cache[key]=details
    return True


async def derive_snapshot_from_month_cache(month: str, period: str, custom_start: str = "", custom_end: str = ""):
    """Populate an in-month range from the ready monthly snapshot.

    A custom period needs no new Bitrix request: sales are monthly by
    definition and the production reducer works from the persisted monthly
    detail rows.  Returning ``False`` preserves the existing full-sync path
    for a missing base snapshot or for cross-month dates.
    """
    if period == "month":
        return False
    key = (month, period, custom_start or "", custom_end or "")
    base_key = (month, "month", "", "")
    if base_key not in cache and not await warm_snapshot_from_storage(month, "month"):
        return False
    base_snapshot = cache.get(base_key)
    base_details = detail_cache.get(base_key)
    production_details = base_details.get("production") if isinstance(base_details, dict) else None
    # A legacy KPI-only snapshot cannot be safely reduced to a calendar range.
    # Fall through to a normal background sync rather than inventing zeroes.
    if not isinstance(base_snapshot, dict) or not isinstance(production_details, dict) or not production_details:
        return False
    derived = derive_production_period(
        month, period, settings.timezone,
        base_snapshot.get("production") or {},
        production_details,
        custom_start, custom_end,
    )
    if derived is None:
        return False
    production, production_details = derived
    period_start, period_end, _ = period_bounds(month, period, settings.timezone, custom_start, custom_end)
    # Sales are monthly and immutable here; keep their large drill-down tree by
    # reference instead of cloning it for every calendar click.
    snapshot = {**base_snapshot, **{
        "period": period,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "production": production,
        "sync_seconds": 0.0,
        "derived_from_month_snapshot": True,
    }}
    details = {**base_details, "production": production_details}
    cache[key] = snapshot
    detail_cache[key] = details
    cache_time[key] = cache_time.get(base_key, time.monotonic())
    derived_range_cache_time[key] = time.monotonic()
    _trim_derived_range_cache()
    return True


def _trim_derived_range_cache():
    while len(derived_range_cache_time) > DERIVED_RANGE_CACHE_LIMIT:
        oldest = min(derived_range_cache_time, key=derived_range_cache_time.get)
        derived_range_cache_time.pop(oldest, None)
        cache.pop(oldest, None)
        detail_cache.pop(oldest, None)
        cache_time.pop(oldest, None)


def invalidate_derived_ranges(month: str):
    for key in list(derived_range_cache_time):
        if key[0] == month:
            derived_range_cache_time.pop(key, None)
            cache.pop(key, None)
            detail_cache.pop(key, None)
            cache_time.pop(key, None)


FULL_ACCESS = "full"
MARKETER_ACCESS = "marketer"
ACCESS_COOKIE = "mavis_access"


def auth_hash():
    """Backward-compatible value for existing owner sessions."""
    return hashlib.sha256((settings.view_password or "").encode()).hexdigest()


def access_control_enabled():
    return bool(settings.view_password or settings.marketer_password)


def session_token(role: str):
    if role not in {FULL_ACCESS, MARKETER_ACCESS} or not settings.dashboard_session_secret:
        return ""
    signature = hmac.new(
        settings.dashboard_session_secret.encode("utf-8"),
        f"mavis-dashboard:{role}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{role}.{signature}"


def request_access_role(request: Request):
    if not access_control_enabled():
        return FULL_ACCESS
    token = str(request.cookies.get(ACCESS_COOKIE) or "")
    for role in (FULL_ACCESS, MARKETER_ACCESS):
        expected = session_token(role)
        if expected and secrets.compare_digest(token, expected):
            return role
    # Existing owner sessions keep working when marketer access is enabled.
    if settings.view_password and secrets.compare_digest(
        str(request.cookies.get("mavis_view") or ""), auth_hash()
    ):
        return FULL_ACCESS
    return ""


def is_marketer(request: Request):
    return getattr(request.state, "dashboard_access", "") == MARKETER_ACCESS


def require_full_access(request: Request):
    if is_marketer(request):
        raise HTTPException(403, "Доступ к операционным данным закрыт для роли «Маркетолог»")


def anonymize_for_marketer(value):
    """Preserve dashboard shape while removing all non-marketing payload values."""
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return None
    if isinstance(value, str):
        return ""
    if isinstance(value, list):
        return [anonymize_for_marketer(item) for item in value]
    if isinstance(value, dict):
        return {key: anonymize_for_marketer(item) for key, item in value.items()}
    return None


def marketer_snapshot(snapshot):
    """Keep navigation metadata, redact every non-marketing dashboard datum."""
    metadata = {
        key: snapshot.get(key)
        for key in (
            "ok", "month_key", "period", "period_label", "generatedAt",
            "generated_at", "updated_at", "syncing", "cached_snapshot", "derived_from_month_snapshot",
        )
        if key in snapshot
    }
    redacted = {
        key: anonymize_for_marketer(value)
        for key, value in snapshot.items()
        if key not in metadata
    }
    return {
        **redacted,
        **metadata,
        "access": {"role": MARKETER_ACCESS, "masked": True},
    }


def is_public_path(path: str):
    return path in {"/login", "/logout", "/health", "/manifest.webmanifest", "/service-worker.js", "/api/bitrix/event"} or path.startswith("/static/")


def marketer_allowed_path(path: str):
    return path in {"/", "/api/snapshot", "/api/marketing", "/events"}

def _default_dormant_stages(available):
    if not available:return []
    out=[]
    for s in available:
        n=str(s).strip().lower()
        if 'черн' in n: continue
        if 'в производство' in n: continue
        if 'возврат' in n and 'потенциаль' not in n: continue
        out.append(s)
    return out

def _dormant_stages(available):
    eligible = _default_dormant_stages(available)
    eligible_set = set(eligible)
    raw=storage.get_setting('dormant_stages','').strip()
    if raw:
        try:
            vals=json.loads(raw)
            if isinstance(vals,list):
                cleaned=[v for v in vals if v in eligible_set]
                if cleaned:
                    return cleaned
        except:
            pass
    return eligible


def _capture_dormant_baseline(month, details, observed_at=None):
    """Persist the first-day stuck-deal cohort without overwriting it later."""
    existing = storage.dormant_baseline(month)
    if existing:
        return existing
    if month == "2026-09":
        storage.set_dormant_baseline(month, SEPTEMBER_2026_DORMANT_BASELINE)
        return SEPTEMBER_2026_DORMANT_BASELINE
    observed_at = observed_at or datetime.now(ZoneInfo(settings.timezone))
    if month != observed_at.strftime("%Y-%m") or observed_at.day != 1:
        return {}
    rows = ((details or {}).get("production") or {}).get("dormant") or []
    baseline = {
        "baseline_date": observed_at.date().isoformat(),
        "count": len(rows),
        "ids": sorted({str(row.get("id")) for row in rows if row.get("id")}),
        "source": "automatic_first_day",
    }
    storage.set_dormant_baseline(month, baseline)
    return baseline


def _stuck_flow(month, details, observed_at=None):
    observed_at = observed_at or datetime.now(ZoneInfo(settings.timezone))
    baseline = storage.dormant_baseline(month)
    prod = (details or {}).get("production") or {}
    current_rows = list(prod.get("dormant") or [])
    baseline_ids = {str(value) for value in (baseline.get("ids") or [])}

    def only_baseline(rows):
        # September's original list is unavailable, so its confirmed totals use
        # all completions from the first day. Future cohorts are exact by ID.
        rows = list(rows or [])
        return [row for row in rows if str(row.get("id")) in baseline_ids] if baseline_ids else rows

    def delta(value, start):
        change = int(value) - int(start)
        return {"value": change, "pct": round(change / start * 100, 1) if start else None}

    current_count = len(current_rows)
    to_returns = only_baseline(prod.get("dormant_to_return"))
    to_production = only_baseline(prod.get("dormant_to_production"))
    base_count = int(baseline.get("count") or 0)
    confirmed_returns = baseline.get("confirmed_to_return_count")
    confirmed_production = baseline.get("confirmed_to_production_count")

    def confirmed_total(confirmed, rows):
        """Extend a manually reconciled total without recounting its history.

        September's first-day cohort was unavailable, so its first transition
        totals were confirmed by hand.  The confirmation has an explicit
        cut-off: subsequent Bitrix history rows are new work and must increase
        the tile, while older rows would only duplicate the hand count.
        """
        if confirmed is None:
            return len(rows)
        cutoff = parse_dt(baseline.get("confirmed_through"), observed_at.tzinfo)
        if not cutoff:
            return int(confirmed)
        additions = [
            row for row in rows
            if (completed_at := parse_dt(row.get("completion_at"), observed_at.tzinfo))
            and completed_at > cutoff
        ]
        return int(confirmed) + len(additions)
    # The September cohort was reconciled manually because its first-day list
    # is no longer available.  Preserve that confirmed result and add only
    # transitions made after the reconciliation date.
    returns_count = confirmed_total(confirmed_returns, to_returns)
    production_count = confirmed_total(confirmed_production, to_production)
    return {
        "available": bool(baseline),
        "baseline_date": baseline.get("baseline_date") or f"{month}-01",
        "as_of": observed_at.date().isoformat(),
        "baseline_count": base_count,
        "current_count": current_count,
        "to_returns_count": returns_count,
        "to_production_count": production_count,
        "current_delta": delta(current_count, base_count),
        "returns_delta": delta(returns_count, 0),
        "production_delta": delta(production_count, 0),
        "exact_cohort": bool(baseline_ids),
    }

def _apply_runtime(snap, details, month, compact=False):
    if compact:
        # The hub only needs a handful of sales metrics.  Copy just the path
        # that receives the finance overlay and keep drill-down arrays shared.
        sales_source = snap.get("sales") or {}
        sales = dict(sales_source)
        overall = dict(sales.get("overall") or {})
        total = dict(overall.get("total") or {})
        total["metrics"] = dict(total.get("metrics") or {})
        overall["total"] = total
        sales["overall"] = overall
        x = {**snap, "sales": sales, "production": copy.deepcopy(snap.get("production") or {})}
    else:
        x=copy.deepcopy(snap)
    x['plans']=storage.plan_dict(month)
    x['team']=storage.team()
    x['comments']=storage.comments(month)
    x['manual_nps']=storage.manual_nps(month)
    x['storage_backend']=storage.backend_name
    traffic_assignments=storage.get_setting('sales_source_overrides',{})
    if not isinstance(traffic_assignments,dict): traffic_assignments={}
    x['traffic_config']={
        'assignments':traffic_assignments,
        'groups':['Холодные продажи','Входящий трафик продажи','Повторные продажи по базе','Прочее'],
        'available_sources':(x.get('sales') or {}).get('available_sources') or []
    }
    available=x.get('available_dormant_stages') or []
    selected=_dormant_stages(available)
    x['dormant_config']={'selected_stages':selected,'available_stages':available}
    prod_details=(details or {}).get('production') or {}
    p=x.get('production',{});k=p.get('kpi',{})
    # Old persisted snapshots predate the weekly production block. Rebuild it
    # from their detail rows so a redeploy does not show an empty weekly view.
    month_start=month_bounds(month,settings.timezone)[0]
    for row in prod_details.get('closed') or []:
        row.setdefault('close_week',week_of_month(parse_dt(row.get('close'),month_start.tzinfo),month_start))
    p['weekly']=production_weekly_dynamics(list(prod_details.get('closed') or []),month_start)
    all_rows=list(prod_details.get('dormant') or [])
    p['stuck_flow'] = _stuck_flow(month, details)
    # Управленческий показатель «Зависшие» считается только из карточек,
    # чья предполагаемая дата закрытия попадает в выбранный период.
    expected_rows=list(prod_details.get('dormant_expected') or [])
    rows=[r for r in expected_rows if not selected or r.get('stage') in selected]
    k['dormant_all_count']=len(all_rows);k['dormant_all_amount']=round(sum(float(r.get('amount') or 0) for r in all_rows),2)
    k['dormant_count']=len(rows);k['dormant_amount']=round(sum(float(r.get('amount') or 0) for r in rows),2)
    k['dormant_expected_count']=len(rows)
    all_with_reason=[r for r in all_rows if r.get('stuck_reasons')]
    with_reason=[r for r in rows if r.get('stuck_reasons')]
    without_reason=[r for r in rows if not r.get('stuck_reasons')]
    k['dormant_all_with_reason_count']=len(all_with_reason)
    k['dormant_all_with_reason_amount']=round(sum(float(r.get('amount') or 0) for r in all_with_reason),2)
    k['dormant_with_reason_count']=len(with_reason)
    k['dormant_with_reason_amount']=round(sum(float(r.get('amount') or 0) for r in with_reason),2)
    k['dormant_with_reason_pct']=round(len(with_reason)/len(rows)*100,1) if rows else 0
    k['dormant_without_reason_count']=len(without_reason)
    active_rows=list(prod_details.get('active') or [])
    month_end=month_bounds(month,settings.timezone)[1]
    active_with_reason=[r for r in active_rows if r.get('stuck_reasons')]
    active_expected_month=[r for r in active_rows if (value:=parse_dt(r.get('expected_close'),month_start.tzinfo)) and month_start<=value<month_end]
    active_with_reason_expected_month=[r for r in active_with_reason if (value:=parse_dt(r.get('expected_close'),month_start.tzinfo)) and month_start<=value<month_end]
    k['active_stuck_with_reason_count']=len(active_with_reason)
    k['active_stuck_with_reason_amount']=round(sum(float(r.get('amount') or 0) for r in active_with_reason),2)
    k['active_stuck_with_reason_pct']=round(len(active_with_reason)/len(active_rows)*100,1) if active_rows else 0
    k['active_stuck_with_reason_expected_month_count']=len(active_with_reason_expected_month)
    k['active_stuck_with_reason_expected_month_amount']=round(sum(float(r.get('amount') or 0) for r in active_with_reason_expected_month),2)
    k['active_stuck_with_reason_expected_month_pct']=round(len(active_with_reason_expected_month)/len(active_expected_month)*100,1) if active_expected_month else 0
    from collections import defaultdict
    def reason_rows(items, denominator):
        acc=defaultdict(lambda:{'count':0,'amount':0.0})
        for row in items:
            for reason in row.get('stuck_reasons') or []:
                acc[reason]['count']+=1
                acc[reason]['amount']+=float(row.get('amount') or 0)
        return [{'name':name,'count':value['count'],'amount':round(value['amount'],2),'pct':round(value['count']/denominator*100,1) if denominator else 0} for name,value in sorted(acc.items(),key=lambda t:(-t[1]['count'],t[0]))]
    p['dormant']={
        **p.get('dormant',{}),
        'all_with_reason_count':len(all_with_reason),
        'all_with_reason_amount':k['dormant_all_with_reason_amount'],
        'with_reason_count':len(with_reason),
        'with_reason_amount':k['dormant_with_reason_amount'],
        'with_reason_pct':k['dormant_with_reason_pct'],
        'reasons':reason_rows(rows,len(rows)),
        'all_reasons':reason_rows(all_rows,len(all_rows)),
    }
    p['active_stuck']={
        **p.get('active_stuck',{}),
        'all_reasons':reason_rows(active_with_reason,len(active_rows)),
        'expected_month_reasons':reason_rows(active_with_reason_expected_month,len(active_expected_month)),
        'all_count':len(active_rows),
        'expected_month_count':len(active_expected_month),
        'expected_month_rule':'Предполагаемая дата закрытия попадает в выбранный месяц',
    }
    return x


async def operational_snapshot(snap, details, month, compact=False):
    x = _apply_runtime(snap, details, month, compact=compact)
    # Finance reconciliation may take much longer than the CRM snapshot.
    # Always render with the last valid result and update that card in the
    # background instead of delaying the whole dashboard.
    finance = cached_clean_revenue(month)
    schedule_clean_revenue_refresh(month)
    # Keep the dashboard-side contract safe for a cached/source response that
    # predates incoming_amount. This is the financial total displayed as
    # "Общая сумма поступлений": clean revenue + contractors.
    if finance.get("status") in {"online", "stale"}:
        try:
            finance.setdefault(
                "incoming_amount",
                round(float(finance["value"]) + float(finance["contractor_amount"]), 2),
            )
        except (KeyError, TypeError, ValueError):
            pass
    x["clean_revenue"] = finance
    x["automatic_nps"] = cached_automatic_nps()
    schedule_automatic_nps_refresh()
    return x


def compact_snapshot_payload(snapshot):
    """Keep the first screen small; sales drill-down data is fetched on demand."""
    result = {key: value for key, value in snapshot.items() if key != "sales"}
    sales = snapshot.get("sales")
    if not isinstance(sales, dict):
        return {**result, "sales": sales} if "sales" in snapshot else result

    compact = {
        key: sales[key]
        for key in ("overall", "stages", "active_deals_count", "sale_filter", "classification", "available_sources")
        if key in sales
    }
    managers = []
    for manager in sales.get("managers") or []:
        if not isinstance(manager, dict):
            continue
        item = {"name": manager.get("name")}
        total = manager.get("total")
        if isinstance(total, dict):
            item["total"] = {"metrics": copy.deepcopy(total.get("metrics") or {})}
        managers.append(item)
    compact["managers"] = managers
    compact["details_loaded"] = False
    result["sales"] = compact
    return result


async def ensure_snapshot(month: str, period: str, force=False, custom_start: str = "", custom_end: str = ""):
    global last_error
    key = (month, period, custom_start or "", custom_end or "")
    ttl = 60 if month == current_month() else 300
    if not force and key in cache and time.monotonic() - cache_time.get(key, 0) < ttl:
        return cache[key]
    lock = locks.setdefault(key, asyncio.Lock())
    async with lock:
        if not force and key in cache and time.monotonic() - cache_time.get(key, 0) < ttl:
            return cache[key]
        try:
            if settings.demo_mode:
                snap = demo_snapshot(month, period)
                details = {"sales":{"leads":[],"deals":[]},"production":{}}
            else:
                source_overrides=storage.get_setting('sales_source_overrides',{})
                if not isinstance(source_overrides,dict): source_overrides={}
                snap = await build_snapshot(client, month, period, settings.timezone, custom_start, custom_end, source_overrides=source_overrides)
                details = snap.pop("_details", {})
                _capture_dormant_baseline(month, details)
            cache[key] = snap
            detail_cache[key] = details
            cache_time[key] = time.monotonic()
            if period == "month" and not custom_start and not custom_end:
                invalidate_derived_ranges(month)
            pkey=persistent_snapshot_key(month,period,custom_start,custom_end)
            # Persist both KPI snapshot and drilldown rows. This keeps
            # расшифровки usable immediately after Render redeploy.
            await asyncio.gather(
                asyncio.to_thread(storage.set_snapshot_cache,pkey,copy.deepcopy(snap)),
                asyncio.to_thread(storage.set_detail_snapshot_cache,pkey,copy.deepcopy(details)),
            )
            last_error = None
            return snap
        except Exception as e:
            last_error = str(e)
            if key in cache:
                old = dict(cache[key])
                old["ok"] = False
                old["error"] = str(e)
                return old
            raise


async def broadcast(payload):
    dead = []
    for q in list(subscribers):
        try:
            q.put_nowait(payload)
        except Exception:
            dead.append(q)
    for q in dead:
        subscribers.discard(q)


async def refresh_loop():
    global previous_month_refresh_at
    # Один стартовый snapshot. Недельные периоды грузятся только по запросу пользователя.
    # Полная страховочная сверка выполняется реже; события Bitrix могут триггерить её раньше.
    while True:
        try:
            await asyncio.wait_for(refresh_trigger.wait(), timeout=max(settings.refresh_seconds, 300))
            refresh_trigger.clear()
            await asyncio.sleep(0.8)
        except asyncio.TimeoutError:
            pass
        try:
            month = current_month()
            current, previous = prewarm_months(month)
            current_task = schedule_snapshot(*current, force=True)
            if current_task:
                await current_task
            schedule_clean_revenue_refresh(month)
            schedule_automatic_nps_refresh()
            # Jarvis retains its own one-hour recommendation cache. Calling it
            # from the existing dashboard heartbeat keeps the reactivation
            # queue warm even before a manager opens the Sales section.
            await load_jarvis_operations("reactivation-recommendations")
            if time.monotonic() - previous_month_refresh_at >= PREVIOUS_MONTH_REFRESH_SECONDS:
                previous_task = schedule_snapshot(*previous, force=True)
                if previous_task:
                    await previous_task
                previous_month_refresh_at = time.monotonic()
            await broadcast({"type": "refresh", "month": month})
        except Exception:
            pass


def schedule_snapshot(month: str, period: str, force: bool=False, custom_start: str = "", custom_end: str = ""):
    key=(month,period,custom_start or "",custom_end or "")
    t=sync_tasks.get(key)
    if t and not t.done():
        return t
    async def runner():
        try:
            await ensure_snapshot(month,period,force=force,custom_start=custom_start,custom_end=custom_end)
            await broadcast({"type":"refresh","month":month,"period":period})
        except Exception:
            pass
        finally:
            sync_tasks.pop(key,None)
    t=asyncio.create_task(runner())
    sync_tasks[key]=t
    return t


@asynccontextmanager
async def lifespan(app: FastAPI):
    # The September production plan was captured before the temporary /tmp
    # database was wiped. Restore it once on the persistent disk, without ever
    # replacing a plan subsequently entered through the dashboard.
    restore_missing_production_plan(storage)
    restore_confirmed_september_dormant_baseline(storage)
    # Не блокируем запуск сервера тяжелой первой синхронизацией.
    task = asyncio.create_task(refresh_loop())
    refresh_trigger.set()
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    except Exception:
        pass
    await client.close()


app = FastAPI(title="MAVIS Operational Dashboard", version="2.9.4", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.middleware("http")
async def optional_password(request: Request, call_next):
    if is_public_path(request.url.path):
        return await call_next(request)
    role = request_access_role(request)
    if role:
        request.state.dashboard_access = role
        if role == MARKETER_ACCESS and not marketer_allowed_path(request.url.path):
            return JSONResponse(
                {"detail": "Доступ к этому разделу закрыт для роли «Маркетолог»"},
                status_code=403,
            )
        return await call_next(request)
    if request.url.path.startswith("/api/") or request.url.path == "/events":
        return JSONResponse({"detail": "AUTH_REQUIRED"}, status_code=401)
    return RedirectResponse("/login", status_code=302)


@app.get("/login", response_class=HTMLResponse)
async def login_page():
    if not access_control_enabled():
        return RedirectResponse("/")
    return HTMLResponse("""
<!doctype html><html lang='ru'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>MAVIS · Вход</title><style>body{margin:0;background:#0c0f13;color:#f1f4f6;font-family:system-ui;display:grid;place-items:center;height:100vh}.box{width:min(390px,90vw);background:#12171d;border:1px solid #27303a;border-radius:16px;padding:26px}h1{margin:5px 0 18px;font-size:25px}label{display:block;color:#8f9aa6;font-size:12px;margin-bottom:7px}input{width:100%;box-sizing:border-box;background:#0c1116;border:1px solid #27303a;color:white;padding:12px;border-radius:9px}button{width:100%;margin-top:12px;padding:12px;border:0;border-radius:9px;font-weight:700}</style></head>
<body><form class='box' method='post'><div style='font-size:11px;letter-spacing:.16em;color:#8f9aa6'>MAVIS GROUP</div><h1>Операционный дашборд</h1><label>Пароль доступа</label><input name='password' type='password' autofocus><button>Открыть</button></form></body></html>
""")


@app.post("/login")
async def login(password: str = Form(...)):
    if not access_control_enabled():
        return RedirectResponse("/", status_code=303)
    role = ""
    if settings.view_password and secrets.compare_digest(password, settings.view_password):
        role = FULL_ACCESS
    elif settings.marketer_password and secrets.compare_digest(password, settings.marketer_password):
        role = MARKETER_ACCESS
    if role:
        token = session_token(role)
        if not token and settings.marketer_password:
            return HTMLResponse("Доступ временно не настроен: добавьте DASHBOARD_SESSION_SECRET", status_code=503)
        r = RedirectResponse("/", status_code=303)
        if token:
            r.set_cookie(ACCESS_COOKIE, token, httponly=True, secure=True, samesite="lax", max_age=60*60*24*30)
            r.delete_cookie("mavis_view")
        else:
            r.set_cookie("mavis_view", auth_hash(), httponly=True, secure=True, samesite="lax", max_age=60*60*24*30)
        return r
    return RedirectResponse("/login?error=1", status_code=303)


@app.post("/logout")
async def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(ACCESS_COOKIE)
    response.delete_cookie("mavis_view")
    return response


@app.middleware("http")
async def no_cache_frontend(request: Request, call_next):
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

@app.get("/")
async def index():
    return FileResponse(
        STATIC / "index.html",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get("/manifest.webmanifest")
async def manifest():
    return FileResponse(
        STATIC / "manifest.webmanifest",
        media_type="application/manifest+json",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/service-worker.js")
async def service_worker():
    return FileResponse(
        STATIC / "service-worker.js",
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"},
    )


@app.get("/health")
async def health():
    return {
        "ok": True,
        "bitrix_configured": bool(settings.bitrix_webhook),
        "last_error": last_error,
        "version": "2.9.3",
        "storage": storage.backend_name,
        "supabase_configured": bool(settings.supabase_url and settings.supabase_key),
        "storage_error": storage.last_remote_error or "",
    }


@app.get("/api/snapshot")
async def api_snapshot(
    request: Request,
    month: str = Query(default=""),
    period: str = Query(default="month", pattern="^(month|this_week|last_week|custom)$"),
    custom_start: str = "",
    custom_end: str = "",
    compact: bool = False,
):
    month = month or current_month()
    key=(month,period,custom_start or "",custom_end or "")
    if period == "custom" and (not custom_start or not custom_end):
        return JSONResponse({"detail":"Для своего периода укажи дату начала и дату окончания"},status_code=400)
    # Stale-while-revalidate: если snapshot есть, отдаём его мгновенно.
    if key in cache:
        ttl=60 if month==current_month() else 600
        stale=time.monotonic()-cache_time.get(key,0)>=ttl
        if stale:
            schedule_snapshot(month,period,force=True,custom_start=custom_start,custom_end=custom_end)
        result = {**await operational_snapshot(cache[key], detail_cache.get(key,{}), month), "syncing": bool(sync_tasks.get(key) and not sync_tasks[key].done())}
        if is_marketer(request):
            result = marketer_snapshot(result)
        return compact_snapshot_payload(result) if compact else result
    # Render memory is empty after restart/redeploy. Try durable Supabase snapshot
    # first and refresh Bitrix in background.
    if await warm_snapshot_from_storage(month,period,custom_start,custom_end):
        schedule_snapshot(month,period,force=True,custom_start=custom_start,custom_end=custom_end)
        result = {**await operational_snapshot(cache[key],detail_cache.get(key,{}),month),"syncing":True,"cached_snapshot":True}
        if is_marketer(request):
            result = marketer_snapshot(result)
        return compact_snapshot_payload(result) if compact else result

    schedule_snapshot(month,period,force=False,custom_start=custom_start,custom_end=custom_end)
    return JSONResponse({
        "ok": False, "loading": True, "month_key": month, "period": period,
        "message": "Первичная синхронизация Bitrix выполняется в фоне"
    }, status_code=202)


@app.get("/api/sales-section")
async def api_sales_section(
    month: str = Query(default=""),
    period: str = Query(default="month", pattern="^(month|this_week|last_week|custom)$"),
    custom_start: str = "",
    custom_end: str = "",
):
    """Return the heavy sales tree only when the user opens the sales section."""
    month = month or current_month()
    key = (month, period, custom_start or "", custom_end or "")
    if period == "custom" and (not custom_start or not custom_end):
        return JSONResponse({"detail": "Для своего периода укажи дату начала и дату окончания"}, status_code=400)
    if key not in cache:
        derived = await derive_snapshot_from_month_cache(month, period, custom_start, custom_end)
        warmed = period == "month" and await warm_snapshot_from_storage(month, period, custom_start, custom_end)
        if not derived and not warmed:
            schedule_snapshot(month, period, force=False, custom_start=custom_start, custom_end=custom_end)
            return JSONResponse({"ok": False, "loading": True, "message": "Детализация продаж готовится в фоне"}, status_code=202)
    if key not in detail_cache:
        await warm_details_from_storage(month, period, custom_start, custom_end)
    sales = _apply_runtime(cache[key], detail_cache.get(key, {}), month).get("sales") or {}
    return {"ok": True, "month_key": month, "period": period, "sales": sales}


@app.get("/api/sales-calls")
async def api_sales_calls():
    return await load_jarvis_operations("sales-calls")


@app.get("/api/reactivation-recommendations")
async def api_reactivation_recommendations(request: Request):
    require_full_access(request)
    return await load_jarvis_operations("reactivation-recommendations")


@app.post("/api/reactivation-recommendations/{deal_id}/reactivate")
async def api_reactivate_recommendation(deal_id: str, request: Request):
    require_full_access(request)
    return await reactivate_jarvis_deal(deal_id)


@app.get("/api/jarvis")
async def api_jarvis():
    """Build a short-lived signed Jarvis entry URL; the shared token stays server-side."""
    base_url = settings.jarvis_operations_url.rstrip("/")
    target = urlparse(base_url)
    if not base_url or target.scheme != "https" or not target.netloc or not settings.jarvis_operations_token:
        return JSONResponse({"ok": False, "status": "not_configured"}, status_code=503)
    issued_at = int(time.time())
    signature = hmac.new(
        settings.jarvis_operations_token.encode("utf-8"),
        f"mavis-dashboard-embed:{issued_at}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return {"ok": True, "url": f"{base_url}/dashboard-embed?{urlencode({'ts': issued_at, 'sig': signature})}"}


@app.get("/api/crm-audit")
async def api_crm_audit():
    return await load_jarvis_operations("crm-audit")


@app.get("/api/marketing")
async def api_marketing(month: str = ""):
    return await load_jarvis_operations("marketing", {"month": month or current_month()})


@app.get("/api/acts-experts")
async def api_acts_experts(month: str = "", force: bool = False):
    try:
        return await load_acts_experts(month or current_month(), force=force)
    except Exception:
        return JSONResponse({"ok": False, "error": "acts_experts_unavailable"}, status_code=503)


@app.get("/api/drilldown")
async def drilldown(
    scope: str, metric: str, month: str = "", period: str = "month", period_type: str = "current",
    manager: str | None = None, group: str | None = None, source: str | None = None, product: str | None = None,
    expert: str | None = None, stage: str | None = None, reason: str | None = None, week: int | None = None, day: int | None = None,
    custom_start: str = "", custom_end: str = "", offset: int = 0, limit: int = 500,
):
    month = month or current_month(); key=(month,period,custom_start or "",custom_end or "")
    if key not in detail_cache or not detail_cache.get(key):
        restored=await warm_details_from_storage(month,period,custom_start,custom_end)
        if not restored:
            schedule_snapshot(month,period,force=False,custom_start=custom_start,custom_end=custom_end)
            return JSONResponse({
                "loading":True,
                "message":"Расшифровка восстанавливается в фоне"
            },status_code=202)
    details=detail_cache.get(key,{})
    if scope == "sales":
        rows=filter_sales_details(details.get("sales",{}), metric, period_type, manager, group, source, product, week, stage, day)
    elif scope == "production":
        rows=filter_prod_details(details.get("production",{}), metric, expert, product, stage, reason, week, day)
        if metric.startswith('dormant') or metric=='dormant_count':
            selected=_dormant_stages((cache.get(key,{}) or {}).get('available_dormant_stages') or [])
            if selected:rows=[r for r in rows if r.get('stage') in selected]
    else: raise HTTPException(400,"scope должен быть sales или production")
    rows=sorted(rows,key=lambda r:(r.get("close") or r.get("created") or "", r.get("id") or ""),reverse=True)
    limit=max(20,min(int(limit),1000));offset=max(0,int(offset))
    return {"count":len(rows),"offset":offset,"limit":limit,"rows":rows[offset:offset+limit]}



class TeamBody(BaseModel):
    role: str
    name: str
    admin_key: str = ""

class KeyTaskMemberBody(BaseModel):
    id: str
    name: str
    admin_key: str = ""

class KeyTaskBody(BaseModel):
    title: str
    responsible_id: str = ""
    deadline: str = ""
    priority: str = "normal"
    project_id: str = ""
    executor_ids: list[str] = []
    watcher_ids: list[str] = []
    status: str = "new"
    description: str = ""
    links: list[dict[str, str]] = []
    created_by_profile_id: str = ""
    recurrence: str = "none"
    backlog: bool = False
    planned_hours: float = 0
    actual_hours: float = 0

class KeyTaskPatchBody(BaseModel):
    title: str | None = None
    responsible_id: str | None = None
    deadline: str | None = None
    priority: str | None = None
    project_id: str | None = None
    executor_ids: list[str] | None = None
    watcher_ids: list[str] | None = None
    status: str | None = None
    description: str | None = None
    links: list[dict[str, str]] | None = None
    recurrence: str | None = None
    backlog: bool | None = None
    planned_hours: float | None = None
    actual_hours: float | None = None
    archived: bool | None = None
    changed_by_profile_id: str = ""

class KeyTaskBulkBody(BaseModel):
    task_ids: list[str]
    status: str | None = None
    deadline: str | None = None
    responsible_id: str | None = None
    add_executor_id: str | None = None
    changed_by_profile_id: str = ""

class TaskCommentBody(BaseModel):
    text: str
    author_profile_id: str

class TaskProfileBody(BaseModel):
    name: str
    role: str = ""

class TaskProfilePatchBody(BaseModel):
    name: str | None = None
    role: str | None = None

class TaskProjectBody(BaseModel):
    name: str

class TaskProjectPatchBody(BaseModel):
    archived: bool

class TaskStatusBody(BaseModel):
    name: str

class TaskStatusPatchBody(BaseModel):
    name: str | None = None
    auto_assign_profile_id: str | None = None
    sla_days: int | None = None

class TaskStatusDeleteBody(BaseModel):
    move_to_status_id: str

class TaskTemplateBody(BaseModel):
    name: str
    title: str
    description: str
    priority: str = "normal"

class TaskSavedViewBody(BaseModel):
    name: str
    profile_id: str
    filters: dict[str, str] = {}

class DashboardChatBody(BaseModel):
    question: str
    month: str = ""
    period: str = "month"
    history: list[dict[str, str]] = []

class CommentBody(BaseModel):
    month: str
    scope: str
    metric: str
    comment: str = ""

class NpsBody(BaseModel):
    month: str
    expert: str
    value: float
    note: str = ""
    admin_key: str = ""

class DormantConfigBody(BaseModel):
    stages: list[str]
    admin_key: str = ""


def _active_task_profile(profile_id: str, required: bool = True):
    profile_id = str(profile_id or "").strip()
    profile = next((row for row in storage.task_profiles() if row.get("id") == profile_id and row.get("active")), None)
    if required and not profile:
        raise HTTPException(400, "Выберите активный рабочий профиль")
    return profile


def _apply_task_stage_automation(before: dict, values: dict, status_by_id: dict[str, dict]):
    """Apply a configured stage owner while retaining chosen executors."""
    target_status = str(values.get("status") or "")
    if not target_status or target_status == str(before.get("status") or ""):
        return None
    assignee_id = str((status_by_id.get(target_status) or {}).get("auto_assign_profile_id") or "")
    if not assignee_id:
        return None
    assignee = _active_task_profile(assignee_id)
    values["responsible_id"] = assignee["id"]
    executors = values.get("executor_ids")
    if executors is None:
        executors = before.get("executor_ids") or []
    values["executor_ids"] = list(dict.fromkeys([*executors, assignee["id"]]))
    return assignee


def _task_change_events(before: dict, after: dict, profiles: list[dict], projects: list[dict], statuses: list[dict] | None = None):
    names = {str(row.get("id") or ""): str(row.get("role") or row.get("name") or "Сотрудник") for row in profiles}
    project_names = {str(row.get("id") or ""): str(row.get("name") or "Без проекта") for row in projects}
    status_names = {str(row.get("id") or ""): str(row.get("name") or "") for row in statuses or []}
    recurrence_names = {"none": "Не повторяется", "weekly": "Каждую неделю", "monthly": "Каждый месяц"}
    events = []
    if before.get("title") != after.get("title"):
        events.append(f"Переименована: «{after.get('title') or 'Без названия'}»")
    if before.get("project_id") != after.get("project_id"):
        events.append(f"Проект: {project_names.get(str(after.get('project_id') or ''), 'Без проекта')}")
    if before.get("responsible_id") != after.get("responsible_id"):
        events.append(f"Ответственный: {names.get(str(after.get('responsible_id') or ''), 'Не назначен')}")
    if list(before.get("executor_ids") or []) != list(after.get("executor_ids") or []):
        assignees = [names.get(str(value), "Сотрудник") for value in after.get("executor_ids") or []]
        events.append(f"Исполнители: {', '.join(assignees) or 'Не назначены'}")
    if list(before.get("watcher_ids") or []) != list(after.get("watcher_ids") or []):
        watchers = [names.get(str(value), "Сотрудник") for value in after.get("watcher_ids") or []]
        events.append(f"Наблюдатели: {', '.join(watchers) or 'Не назначены'}")
    if before.get("deadline") != after.get("deadline"):
        events.append(f"Срок: {after.get('deadline') or 'без срока'}")
    if before.get("priority") != after.get("priority"):
        events.append(f"Приоритет: {'Высокий' if after.get('priority') == 'high' else 'Обычный'}")
    if before.get("status") != after.get("status"):
        events.append(f"Статус: {status_names.get(after.get('status'), 'В работе')}")
    if before.get("description") != after.get("description"):
        events.append("Обновлено описание")
    if list(before.get("links") or []) != list(after.get("links") or []):
        events.append("Обновлены связанные ссылки")
    if before.get("recurrence") != after.get("recurrence"):
        events.append(f"Повторение: {recurrence_names.get(after.get('recurrence'), 'Не повторяется')}")
    if float(before.get("planned_hours") or 0) != float(after.get("planned_hours") or 0):
        events.append(f"План трудозатрат: {after.get('planned_hours') or 0:g} ч")
    if float(before.get("actual_hours") or 0) != float(after.get("actual_hours") or 0):
        events.append(f"Факт трудозатрат: {after.get('actual_hours') or 0:g} ч")
    if bool(before.get("archived_at")) != bool(after.get("archived_at")):
        events.append("Задача перенесена в архив" if after.get("archived_at") else "Задача возвращена из архива")
    return events

@app.get('/api/team')
async def get_team(): return storage.team()

@app.post('/api/team')
async def add_team(body: TeamBody):
    if settings.admin_key and not secrets.compare_digest(body.admin_key,settings.admin_key):raise HTTPException(403,'Неверный ADMIN_KEY')
    storage.add_team_member(body.role,body.name);return {'ok':True,'team':storage.team()}

@app.delete('/api/team')
async def del_team(role:str,name:str,admin_key:str=''):
    if settings.admin_key and not secrets.compare_digest(admin_key,settings.admin_key):raise HTTPException(403,'Неверный ADMIN_KEY')
    storage.remove_team_member(role,name);return {'ok':True,'team':storage.team()}


@app.get('/api/key-tasks/team')
async def get_key_task_team():
    return {"ok": True, "members": storage.key_task_team(), "users": await key_task_available_users()}


@app.post('/api/key-tasks/team')
async def add_key_task_team_member(body: KeyTaskMemberBody):
    if settings.admin_key and not secrets.compare_digest(body.admin_key, settings.admin_key):
        raise HTTPException(403, 'Неверный ADMIN_KEY')
    users = await key_task_available_users()
    valid = next((row for row in users if row["id"] == str(body.id)), None)
    if not valid:
        raise HTTPException(400, 'Пользователь не найден среди активных пользователей Bitrix')
    storage.add_key_task_member(valid["id"], valid["name"])
    return {"ok": True, "members": storage.key_task_team()}


@app.delete('/api/key-tasks/team')
async def delete_key_task_team_member(user_id: str, admin_key: str = ''):
    if settings.admin_key and not secrets.compare_digest(admin_key, settings.admin_key):
        raise HTTPException(403, 'Неверный ADMIN_KEY')
    storage.remove_key_task_member(user_id)
    return {"ok": True, "members": storage.key_task_team()}


@app.get('/api/key-tasks')
async def get_key_tasks():
    now = datetime.now(ZoneInfo(settings.timezone))
    workspace = build_task_workspace(
        storage.workspace_tasks(), storage.task_profiles(), storage.task_projects(),
        storage.key_task_team(), now, settings.timezone, storage.task_statuses(),
    )
    await enrich_task_workspace_deal_links(workspace)
    return {
        "ok": True,
        "generated_at": now.isoformat(),
        **workspace,
        "templates": storage.task_templates(),
        "saved_views": storage.task_saved_views(),
    }


@app.post('/api/key-tasks')
async def add_key_task(body: KeyTaskBody):
    active_profiles = {row["id"] for row in storage.task_profiles() if row.get("active")}
    active_projects = {row["id"] for row in storage.task_projects() if not row.get("archived")}
    status_ids = {row["id"] for row in storage.task_statuses()}
    if body.project_id and body.project_id not in active_projects:
        raise HTTPException(400, 'Выберите активный проект')
    if body.status not in status_ids:
        raise HTTPException(400, 'Выберите существующий этап')
    if not str(body.description or '').strip():
        raise HTTPException(400, 'Добавьте описание задачи')
    is_backlog = body.backlog or body.status == "backlog"
    if not is_backlog and not body.deadline:
        raise HTTPException(400, 'Укажите срок или отметьте задачу как бэклог')
    if not body.responsible_id:
        raise HTTPException(400, 'Выберите ответственного')
    if body.responsible_id and body.responsible_id not in active_profiles:
        raise HTTPException(400, 'Выберите активный рабочий профиль')
    if any(value not in active_profiles for value in body.executor_ids):
        raise HTTPException(400, 'У одного из исполнителей нет активного рабочего профиля')
    if any(value not in active_profiles for value in body.watcher_ids):
        raise HTTPException(400, 'У одного из наблюдателей нет активного рабочего профиля')
    author = _active_task_profile(body.created_by_profile_id, required=bool(body.created_by_profile_id))
    try:
        task = storage.add_workspace_task(body.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    storage.add_task_activity(task["id"], "Задача создана", (author or {}).get("id", ""), (author or {}).get("name", "Команда"), "created")
    await broadcast({"type": "key-tasks"})
    return {"ok": True, "task": task}


@app.patch('/api/key-tasks/{task_id}')
async def patch_key_task(task_id: str, body: KeyTaskPatchBody):
    values = body.model_dump(exclude_none=True)
    changed_by_profile_id = str(values.pop("changed_by_profile_id", "") or "")
    active_profiles = {row["id"] for row in storage.task_profiles() if row.get("active")}
    active_projects = {row["id"] for row in storage.task_projects() if not row.get("archived")}
    statuses = storage.task_statuses()
    status_by_id = {row["id"]: row for row in statuses}
    if values.get("project_id") and values["project_id"] not in active_projects:
        raise HTTPException(400, 'Выберите активный проект')
    if values.get("status") and values["status"] not in status_by_id:
        raise HTTPException(400, 'Выберите существующий этап')
    if values.get("responsible_id") and values["responsible_id"] not in active_profiles:
        raise HTTPException(400, 'Выберите активный рабочий профиль')
    if any(value not in active_profiles for value in values.get("executor_ids") or []):
        raise HTTPException(400, 'У одного из исполнителей нет активного рабочего профиля')
    if any(value not in active_profiles for value in values.get("watcher_ids") or []):
        raise HTTPException(400, 'У одного из наблюдателей нет активного рабочего профиля')
    before = storage.workspace_task(task_id)
    if not before:
        raise HTTPException(404, 'Задача не найдена')
    author = _active_task_profile(changed_by_profile_id, required=bool(changed_by_profile_id))
    auto_assignee = _apply_task_stage_automation(before, values, status_by_id)
    try:
        task = storage.update_workspace_task(task_id, values)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not task:
        raise HTTPException(404, 'Задача не найдена')
    for text in _task_change_events(before, task, storage.task_profiles(), storage.task_projects(), statuses):
        storage.add_task_activity(task_id, text, (author or {}).get("id", ""), (author or {}).get("name", "Команда"))
    if auto_assignee:
        storage.add_task_activity(task_id, f"Автодействие этапа: ответственным назначен {auto_assignee.get('role') or auto_assignee.get('name')}", (author or {}).get("id", ""), (author or {}).get("name", "Команда"), "automation")
    next_task = None
    if before.get("status") != "done" and task.get("status") == "done":
        next_task = storage.create_next_recurrence_task(task_id)
        if next_task:
            storage.add_task_activity(task_id, f"Создан следующий экземпляр со сроком {next_task['deadline']}", (author or {}).get("id", ""), (author or {}).get("name", "Команда"), "recurrence")
            storage.add_task_activity(next_task["id"], f"Создана повторяющаяся задача из «{task['title']}»", (author or {}).get("id", ""), (author or {}).get("name", "Команда"), "created")
    await broadcast({"type": "key-tasks"})
    return {"ok": True, "task": task, "next_task": next_task}


@app.post('/api/key-tasks/bulk')
async def bulk_update_key_tasks(body: KeyTaskBulkBody):
    task_ids = list(dict.fromkeys(str(value or "").strip() for value in body.task_ids if str(value or "").strip()))
    if not task_ids or len(task_ids) > 100:
        raise HTTPException(400, 'Выберите от 1 до 100 задач')
    if body.status == 'done':
        raise HTTPException(400, 'Завершайте задачи по одной: для каждой требуется фактическое время')
    if not any(value is not None and value != "" for value in (body.status, body.deadline, body.responsible_id, body.add_executor_id)):
        raise HTTPException(400, 'Выберите хотя бы одно массовое изменение')
    active_profiles = {row["id"] for row in storage.task_profiles() if row.get("active")}
    statuses = storage.task_statuses()
    status_by_id = {row["id"]: row for row in statuses}
    if body.status and body.status not in status_by_id:
        raise HTTPException(400, 'Выберите существующий этап')
    if body.responsible_id and body.responsible_id not in active_profiles:
        raise HTTPException(400, 'Выберите активного ответственного')
    if body.add_executor_id and body.add_executor_id not in active_profiles:
        raise HTTPException(400, 'Выберите активного исполнителя')
    if body.deadline:
        try:
            datetime.strptime(body.deadline, '%Y-%m-%d')
        except ValueError as exc:
            raise HTTPException(400, 'Срок должен быть в формате YYYY-MM-DD') from exc
    if body.status:
        auto_profile_id = str((status_by_id.get(body.status) or {}).get('auto_assign_profile_id') or '')
        if auto_profile_id:
            _active_task_profile(auto_profile_id)
    before_rows = [storage.workspace_task(task_id) for task_id in task_ids]
    if any(row is None for row in before_rows):
        raise HTTPException(404, 'Одна из задач не найдена')
    if any(row.get('archived') for row in before_rows):
        raise HTTPException(400, 'Архивные задачи нельзя менять массово')
    author = _active_task_profile(body.changed_by_profile_id, required=bool(body.changed_by_profile_id))
    changed = []
    for before in before_rows:
        values = {}
        if body.status:
            values['status'] = body.status
            values['backlog'] = body.status == 'backlog'
        if body.deadline:
            values['deadline'] = body.deadline
        if body.responsible_id:
            values['responsible_id'] = body.responsible_id
        if body.add_executor_id:
            values['executor_ids'] = list(dict.fromkeys([*(before.get('executor_ids') or []), body.add_executor_id]))
        auto_assignee = _apply_task_stage_automation(before, values, status_by_id)
        try:
            task = storage.update_workspace_task(before['id'], values)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        for text in _task_change_events(before, task, storage.task_profiles(), storage.task_projects(), statuses):
            storage.add_task_activity(task['id'], text, (author or {}).get('id', ''), (author or {}).get('name', 'Команда'))
        storage.add_task_activity(task['id'], 'Массовое изменение', (author or {}).get('id', ''), (author or {}).get('name', 'Команда'), 'bulk')
        if auto_assignee:
            storage.add_task_activity(task['id'], f"Автодействие этапа: ответственным назначен {auto_assignee.get('role') or auto_assignee.get('name')}", (author or {}).get('id', ''), (author or {}).get('name', 'Команда'), 'automation')
        changed.append(task)
    await broadcast({"type": "key-tasks"})
    return {"ok": True, "tasks": changed}


@app.get('/api/key-tasks/{task_id}/activity')
async def get_key_task_activity(task_id: str):
    if not storage.workspace_task(task_id):
        raise HTTPException(404, 'Задача не найдена')
    return {
        "ok": True,
        "comments": sorted(storage.task_comments(task_id), key=lambda row: row.get("created_at") or "", reverse=True),
        "activity": sorted(storage.task_activity(task_id), key=lambda row: row.get("created_at") or "", reverse=True),
    }


@app.post('/api/key-tasks/{task_id}/comments')
async def add_key_task_comment(task_id: str, body: TaskCommentBody):
    if not storage.workspace_task(task_id):
        raise HTTPException(404, 'Задача не найдена')
    author = _active_task_profile(body.author_profile_id)
    try:
        comment = storage.add_task_comment(task_id, body.text, author["id"], author["name"])
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    storage.add_task_activity(task_id, "Добавлен комментарий", author["id"], author["name"], "comment")
    await broadcast({"type": "key-tasks"})
    return {"ok": True, "comment": comment}


@app.delete('/api/key-tasks/{task_id}')
async def delete_key_task(task_id: str):
    if not storage.remove_manual_key_task(task_id):
        raise HTTPException(404, 'Задача не найдена')
    await broadcast({"type": "key-tasks"})
    return {"ok": True}


@app.post('/api/key-tasks/profiles')
async def add_task_profile(body: TaskProfileBody):
    try:
        profile = storage.add_task_profile(body.name, body.role)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await broadcast({"type": "key-tasks"})
    return {"ok": True, "profile": profile}


@app.patch('/api/key-tasks/profiles/{profile_id}')
async def patch_task_profile(profile_id: str, body: TaskProfilePatchBody):
    try:
        profile = storage.update_task_profile(profile_id, body.name, body.role)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not profile:
        raise HTTPException(404, 'Сотрудник не найден')
    await broadcast({"type": "key-tasks"})
    return {"ok": True, "profile": profile}


@app.delete('/api/key-tasks/profiles/{profile_id}')
async def delete_task_profile(profile_id: str):
    profile = storage.deactivate_task_profile(profile_id)
    if not profile:
        raise HTTPException(404, 'Сотрудник не найден')
    await broadcast({"type": "key-tasks"})
    return {"ok": True, "profile": profile}


@app.post('/api/key-tasks/projects')
async def add_task_project(body: TaskProjectBody):
    try:
        project = storage.add_task_project(body.name)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await broadcast({"type": "key-tasks"})
    return {"ok": True, "project": project}


@app.patch('/api/key-tasks/projects/{project_id}')
async def patch_task_project(project_id: str, body: TaskProjectPatchBody):
    project = storage.archive_task_project(project_id, body.archived)
    if not project:
        raise HTTPException(404, 'Проект не найден')
    await broadcast({"type": "key-tasks"})
    return {"ok": True, "project": project}


@app.post('/api/key-tasks/statuses')
async def add_task_status(body: TaskStatusBody):
    try:
        status = storage.add_task_status(body.name)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await broadcast({"type": "key-tasks"})
    return {"ok": True, "status": status}


@app.patch('/api/key-tasks/statuses/{status_id}')
async def patch_task_status(status_id: str, body: TaskStatusPatchBody):
    values = body.model_dump(exclude_none=True)
    assignee_id = values.get("auto_assign_profile_id")
    if assignee_id:
        _active_task_profile(assignee_id)
    try:
        status = storage.update_task_status(status_id, **values)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not status:
        raise HTTPException(404, 'Этап не найден')
    await broadcast({"type": "key-tasks"})
    return {"ok": True, "status": status}


@app.delete('/api/key-tasks/statuses/{status_id}')
async def delete_task_status(status_id: str, body: TaskStatusDeleteBody):
    try:
        status = storage.remove_task_status(status_id, body.move_to_status_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not status:
        raise HTTPException(404, 'Этап не найден')
    await broadcast({"type": "key-tasks"})
    return {"ok": True}


@app.get('/api/key-tasks/templates')
async def get_task_templates():
    return {"ok": True, "templates": storage.task_templates()}


@app.post('/api/key-tasks/templates')
async def add_task_template(body: TaskTemplateBody):
    try:
        template = storage.add_task_template(body.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await broadcast({"type": "key-tasks"})
    return {"ok": True, "template": template}


@app.delete('/api/key-tasks/templates/{template_id}')
async def delete_task_template(template_id: str):
    if not storage.remove_task_template(template_id):
        raise HTTPException(404, 'Шаблон не найден')
    await broadcast({"type": "key-tasks"})
    return {"ok": True}


@app.post('/api/key-tasks/views')
async def add_task_saved_view(body: TaskSavedViewBody):
    _active_task_profile(body.profile_id)
    try:
        view = storage.add_task_saved_view(body.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await broadcast({"type": "key-tasks"})
    return {"ok": True, "view": view}


@app.delete('/api/key-tasks/views/{view_id}')
async def delete_task_saved_view(view_id: str, profile_id: str):
    if not storage.remove_task_saved_view(view_id, profile_id):
        raise HTTPException(404, 'Представление не найдено')
    await broadcast({"type": "key-tasks"})
    return {"ok": True}


async def _dashboard_chat_context(month: str, period: str):
    """Only approved, compact operational facts are sent to the AI gateway."""
    key = (month, period, "", "")
    snapshot = cache.get(key) or {}
    details = detail_cache.get(key) or {}
    sales = snapshot.get("sales") or {}
    production = snapshot.get("production") or {}
    production_rows = (details.get("production") or {})
    active = list(production_rows.get("active") or [])[:80]
    stuck = []
    for row in active:
        reasons = row.get("stuck_reasons") or []
        if not reasons:
            continue
        deal_id = str(row.get("id") or "")
        stuck.append({
            "id": deal_id,
            "title": str(row.get("title") or ""),
            "stage": str(row.get("stage") or ""),
            "reason": reasons,
            "expected_close": str(row.get("expected_close") or ""),
            "amount": float(row.get("amount") or 0),
            "expert": str(row.get("expert") or ""),
            "url": f"{client.portal}/crm/deal/details/{deal_id}/" if deal_id else "",
        })
    team = storage.key_task_team()
    task_cache_key = _key_task_cache_key(team)
    tasks = key_task_cache.get(task_cache_key) or {}
    communications = await load_sales_communication_gaps()
    return {
        "period": {"month": month, "kind": period},
        "sales": {
            "total": ((sales.get("overall") or {}).get("total") or {}).get("metrics") or {},
            "stages": sales.get("stages") or [],
        },
        "production": {
            "kpi": production.get("kpi") or {},
            "active_stuck_with_reason": stuck,
        },
        "key_tasks": {
            "generated_at": tasks.get("generated_at") or "",
            "people": tasks.get("people") or [],
        },
        "communications": communications,
        "scope_note": "Это read-only агрегаты, компактный список активных сделок и проверка звонков по активным компаниям продаж. Если данных нет в контексте, нужно сказать об этом, а не предполагать.",
    }


@app.post('/api/dashboard-chat')
async def dashboard_chat(body: DashboardChatBody):
    question = str(body.question or "").strip()
    if not question:
        raise HTTPException(400, 'Напишите вопрос')
    if len(question) > 900:
        raise HTTPException(400, 'Вопрос слишком длинный — до 900 символов')
    if not settings.assistant_chat_url or not settings.dashboard_chat_token:
        return JSONResponse({"ok": False, "error": "Защищённый AI-шлюз ещё не подключён"}, status_code=503)
    target = urlparse(settings.assistant_chat_url)
    if target.scheme != "https" or not target.netloc:
        return JSONResponse({"ok": False, "error": "Некорректный адрес AI-шлюза"}, status_code=503)
    month = body.month or current_month()
    history = []
    for item in body.history[-6:]:
        role = str(item.get("role") or "")
        text = str(item.get("content") or "").strip()
        if role in {"user", "assistant"} and text:
            history.append({"role": role, "content": text[:1400]})
    payload = {"question": question, "history": history, "context": await _dashboard_chat_context(month, body.period)}
    try:
        async with httpx.AsyncClient(timeout=45.0, follow_redirects=False) as session:
            response = await session.post(
                f"{settings.assistant_chat_url.rstrip('/')}/api/dashboard-chat",
                headers={"Authorization": f"Bearer {settings.dashboard_chat_token}", "Content-Type": "application/json"},
                json=payload,
            )
        data = response.json()
    except (httpx.HTTPError, ValueError):
        return JSONResponse({"ok": False, "error": "AI-шлюз временно недоступен"}, status_code=503)
    if response.status_code != 200 or not data.get("ok"):
        return JSONResponse({"ok": False, "error": str(data.get("error") or "Не удалось получить ответ AI")}, status_code=503)
    return {"ok": True, "answer": data.get("answer") or "", "facts": data.get("facts") or [], "recommendations": data.get("recommendations") or [], "links": data.get("links") or []}

@app.put('/api/comment')
async def save_comment(body: CommentBody):
    storage.set_comment(body.month,body.scope,body.metric,body.comment);return {'ok':True,'comments':storage.comments(body.month)}

@app.put('/api/nps')
async def save_nps(body: NpsBody):
    if settings.admin_key and not secrets.compare_digest(body.admin_key,settings.admin_key):raise HTTPException(403,'Неверный ADMIN_KEY')
    if body.value<0 or body.value>10:raise HTTPException(400,'NPS должен быть от 0 до 10')
    storage.add_manual_nps(body.month,body.expert,body.value,body.note)
    return {'ok':True,'manual_nps':storage.manual_nps(body.month)}

@app.delete('/api/nps')
async def delete_nps(month:str, entry_id:str, admin_key:str=''):
    if settings.admin_key and not secrets.compare_digest(admin_key,settings.admin_key):raise HTTPException(403,'Неверный ADMIN_KEY')
    storage.delete_manual_nps(month, entry_id)
    return {'ok':True,'manual_nps':storage.manual_nps(month)}

@app.put('/api/dormant-config')
async def save_dormant_config(body: DormantConfigBody):
    if settings.admin_key and not secrets.compare_digest(body.admin_key,settings.admin_key):raise HTTPException(403,'Неверный ADMIN_KEY')
    storage.set_setting('dormant_stages',json.dumps(body.stages,ensure_ascii=False));return {'ok':True,'stages':body.stages}


class TrafficConfigBody(BaseModel):
    assignments: dict[str, str]
    admin_key: str = ""

@app.get('/api/traffic-config')
async def get_traffic_config():
    value=storage.get_setting('sales_source_overrides',{})
    if not isinstance(value,dict): value={}
    return {'ok':True,'assignments':value}

@app.put('/api/traffic-config')
async def save_traffic_config(body: TrafficConfigBody):
    if settings.admin_key and not secrets.compare_digest(body.admin_key,settings.admin_key):
        raise HTTPException(403,'Неверный ADMIN_KEY')
    allowed={'Холодные продажи','Входящий трафик продажи','Повторные продажи по базе','Прочее','__ignore__'}
    cleaned={}
    for source,group in (body.assignments or {}).items():
        source=str(source or '').strip()
        group=str(group or '').strip()
        if not source or not group:
            continue
        if group not in allowed:
            raise HTTPException(400,f'Некорректная группа для источника {source}')
        cleaned[source]=group
    storage.set_setting('sales_source_overrides',cleaned)
    for k in list(cache_time):
        cache_time[k]=0
    schedule_snapshot(current_month(),'month',force=True)
    await broadcast({'type':'traffic-config'})
    return {'ok':True,'assignments':cleaned}

@app.get('/api/dynamics')
async def dynamics(month:str='',months:int=6):
    month=month or current_month();months=max(3,min(int(months),12));key=(month,months)
    if key in trend_cache and time.monotonic()-trend_cache_time.get(key,0)<600:return {'ok':True,'rows':trend_cache[key]}
    rows=await build_trends_light(client,month,months,settings.timezone)
    trend_cache[key]=rows;trend_cache_time[key]=time.monotonic();return {'ok':True,'rows':rows}

class PlanBody(BaseModel):
    month: str
    scope: str
    context_type: str = "overall"
    context_key: str = ""
    values: dict[str, float]
    admin_key: str = ""


@app.get("/api/plans")
async def plans(month: str = ""):
    month=month or current_month()
    return {"month":month,"rows":storage.get_plans(month),"dict":storage.plan_dict(month)}


@app.put("/api/plans")
async def save_plans(body: PlanBody):
    if settings.admin_key and not secrets.compare_digest(body.admin_key, settings.admin_key):
        raise HTTPException(403,"Неверный ADMIN_KEY")
    if body.scope not in {"sales","production"}:
        raise HTTPException(400,"Некорректный scope")
    storage.set_plans(body.month,body.scope,body.context_type,body.context_key,body.values)
    await broadcast({"type":"plans","month":body.month})
    return {"ok":True,"dict":storage.plan_dict(body.month)}


@app.post("/api/refresh")
async def manual_refresh(admin_key: str = ""):
    if settings.admin_key and not secrets.compare_digest(admin_key, settings.admin_key):
        raise HTTPException(403,"Неверный ADMIN_KEY")
    refresh_trigger.set()
    return {"ok":True}


@app.post("/api/bitrix/event")
async def bitrix_event(request: Request, token: str = ""):
    if settings.event_token and not secrets.compare_digest(token, settings.event_token):
        raise HTTPException(403,"Неверный token")
    raw=(await request.body()).decode("utf-8",errors="replace")
    form=parse_qs(raw)
    event=(form.get("event") or [""])[0]
    entity_id=(form.get("data[FIELDS][ID]") or form.get("data[ID]") or [""])[0]
    # Инвалидируем только текущий месяц. Bitrix получает ответ сразу.
    m=current_month()
    for k in list(cache_time):
        if k[0]==m:
            cache_time[k]=0
    refresh_trigger.set()
    return {"ok":True,"event":event,"entity_id":entity_id}


@app.get("/events")
async def events():
    async def gen():
        q=asyncio.Queue(maxsize=50)
        subscribers.add(q)
        try:
            yield "event: hello\ndata: {}\n\n"
            while True:
                try:
                    item=await asyncio.wait_for(q.get(),timeout=20)
                    yield f"event: update\ndata: {json.dumps(item,ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield "event: ping\ndata: {}\n\n"
        finally:
            subscribers.discard(q)
    return StreamingResponse(gen(),media_type="text/event-stream",headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})
