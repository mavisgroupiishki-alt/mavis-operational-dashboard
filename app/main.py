import asyncio
import hashlib
import hmac
import json
import copy
import math
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
from .metrics import build_snapshot, build_trends_light, derive_production_period, filter_prod_details, filter_sales_details, month_bounds, parse_dt, period_bounds, production_weekly_dynamics, week_of_month
from .nps import NPS_GROUP_ID, aggregate_automatic_nps, previous_calendar_week
from .recovery import SEPTEMBER_2026_DORMANT_BASELINE, restore_confirmed_september_dormant_baseline, restore_missing_production_plan
from .demo import demo_snapshot
from .key_tasks import build_key_tasks
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
key_task_users_cache = []
key_task_users_cache_time = 0.0


def current_month():
    return datetime.now(ZoneInfo(settings.timezone)).strftime("%Y-%m")


def _key_task_cache_key(members):
    return ",".join(sorted(str(row.get("id") or "") for row in members if row.get("id")))


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
                params={"date_from": date_from, "date_to": date_to},
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
    allowed = {"sales-calls", "crm-audit", "marketing"}
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


def persistent_snapshot_key(month: str, period: str, custom_start: str = "", custom_end: str = ""):
    return "|".join([month,period,custom_start or "",custom_end or ""])


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
    return path in {"/login", "/health", "/manifest.webmanifest", "/service-worker.js", "/api/bitrix/event"} or path.startswith("/static/")


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
    # The September cohort was reconciled manually because its first-day list
    # is no longer available. Keep those confirmed totals authoritative while
    # all cohorts with saved deal IDs continue to use live history.
    returns_count = int(confirmed_returns) if confirmed_returns is not None else len(to_returns)
    production_count = int(confirmed_production) if confirmed_production is not None else len(to_production)
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
    responsible_id: str
    deadline: str = ""
    priority: str = "normal"

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
    members = storage.key_task_team()
    now = datetime.now(ZoneInfo(settings.timezone))
    return {
        "ok": True,
        "generated_at": now.isoformat(),
        "members": members,
        "empty_team": not members,
        **build_key_tasks(storage.manual_key_tasks(), members, now, settings.timezone),
    }


@app.post('/api/key-tasks')
async def add_key_task(body: KeyTaskBody):
    members = {row["id"]: row for row in storage.key_task_team()}
    if body.responsible_id not in members:
        raise HTTPException(400, 'Сначала добавьте сотрудника в раздел «Ключевые задачи»')
    try:
        task = storage.add_manual_key_task(body.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await broadcast({"type": "key-tasks"})
    return {"ok": True, "task": task}


@app.delete('/api/key-tasks/{task_id}')
async def delete_key_task(task_id: str):
    if not storage.remove_manual_key_task(task_id):
        raise HTTPException(404, 'Задача не найдена')
    await broadcast({"type": "key-tasks"})
    return {"ok": True}


def _dashboard_chat_context(month: str, period: str):
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
        "scope_note": "Это read-only агрегаты и ограниченный список активных сделок. Если данных нет в контексте, нужно сказать об этом, а не предполагать.",
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
    payload = {"question": question, "history": history, "context": _dashboard_chat_context(month, body.period)}
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
