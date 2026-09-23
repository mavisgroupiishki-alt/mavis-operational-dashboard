import asyncio
import time

from fastapi import Query
from fastapi.responses import JSONResponse

from . import main as core

app = core.app

# v3.1.8 — weekly production plans can override monthly pacing.
# The old implementation swallowed background errors and the browser retried
# every 2.5 seconds forever. Keep a per-period failure state and surface it.
sync_errors = {}
sync_started = {}
SYNC_ERROR_COOLDOWN_SECONDS = 30


def _key(month: str, period: str, custom_start: str = "", custom_end: str = ""):
    return (month, period, custom_start or "", custom_end or "")


def schedule_snapshot(month: str, period: str, force: bool = False, custom_start: str = "", custom_end: str = ""):
    key = _key(month, period, custom_start, custom_end)
    task = core.sync_tasks.get(key)
    if task and not task.done():
        return task

    async def runner():
        sync_started[key] = time.monotonic()
        try:
            await core.ensure_snapshot(
                month,
                period,
                force=force,
                custom_start=custom_start,
                custom_end=custom_end,
            )
            sync_errors.pop(key, None)
            await core.broadcast({"type": "refresh", "month": month, "period": period})
        except Exception as exc:
            sync_errors[key] = {
                "message": str(exc) or exc.__class__.__name__,
                "at": time.monotonic(),
            }
            await core.broadcast({"type": "sync_error", "month": month, "period": period})
        finally:
            sync_started.pop(key, None)
            core.sync_tasks.pop(key, None)

    task = asyncio.create_task(runner())
    core.sync_tasks[key] = task
    return task


# Functions in app.main resolve this global at request time.
core.schedule_snapshot = schedule_snapshot

# Replace the old /api/snapshot route with an error-aware implementation.
app.router.routes[:] = [
    route for route in app.router.routes
    if getattr(route, "path", None) != "/api/snapshot"
]


@app.get("/api/snapshot")
async def api_snapshot(
    month: str = Query(default=""),
    period: str = Query(default="month", pattern="^(month|this_week|last_week|custom)$"),
    custom_start: str = "",
    custom_end: str = "",
    compact: bool = False,
):
    month = month or core.current_month()
    key = _key(month, period, custom_start, custom_end)

    if period == "custom" and (not custom_start or not custom_end):
        return JSONResponse(
            {"detail": "Для своего периода укажи дату начала и дату окончания"},
            status_code=400,
        )

    # 1) Valid RAM snapshot: return immediately, refresh in background if stale.
    if key in core.cache:
        ttl = 60 if month == core.current_month() else 600
        stale = time.monotonic() - core.cache_time.get(key, 0) >= ttl
        derived = bool(core.cache[key].get("derived_from_month_snapshot"))
        if stale:
            # Calendar ranges are projections of the monthly source snapshot.
            # Refresh that one source, never start an expensive exact-range
            # Bitrix job or persist arbitrary date combinations.
            if derived:
                schedule_snapshot(month, "month", force=True)
            else:
                schedule_snapshot(
                    month, period, force=True,
                    custom_start=custom_start, custom_end=custom_end
                )
        result = {
            **await core.operational_snapshot(
                core.cache[key], core.detail_cache.get(key, {}), month, compact=compact
            ),
            "syncing": bool(core.sync_tasks.get((month, "month", "", "")) and not core.sync_tasks[(month, "month", "", "")].done()) if derived else bool(core.sync_tasks.get(key) and not core.sync_tasks[key].done()),
        }
        return core.compact_snapshot_payload(result) if compact else result

    # 2) After Render restart, use persistent snapshot before asking Bitrix.
    if period == "month" and await core.warm_snapshot_from_storage(month, period, custom_start, custom_end):
        schedule_snapshot(
            month, period, force=True,
            custom_start=custom_start, custom_end=custom_end
        )
        result = {
            **await core.operational_snapshot(
                core.cache[key], core.detail_cache.get(key, {}), month, compact=compact
            ),
            "syncing": True,
            "cached_snapshot": True,
        }
        return core.compact_snapshot_payload(result) if compact else result

    # 3) A calendar range inside the selected month is derived from the
    # ready monthly detail snapshot. No additional Bitrix synchronisation is
    # needed merely because the user changed dates.
    if await core.derive_snapshot_from_month_cache(month, period, custom_start, custom_end):
        result = {
            **await core.operational_snapshot(
                core.cache[key], core.detail_cache.get(key, {}), month, compact=compact
            ),
            "syncing": False,
            "derived_from_month_snapshot": True,
        }
        return core.compact_snapshot_payload(result) if compact else result

    # 4) Already running: report progress, never create a duplicate task.
    task = core.sync_tasks.get(key)
    if task and not task.done():
        started = sync_started.get(key, time.monotonic())
        elapsed = max(0, int(time.monotonic() - started))
        return JSONResponse(
            {
                "ok": False,
                "loading": True,
                "month_key": month,
                "period": period,
                "elapsed_seconds": elapsed,
                "message": "Первичная синхронизация Bitrix выполняется в фоне",
            },
            status_code=202,
        )

    # 5) Previous background calculation failed. Show its real error for a
    # cooldown instead of silently restarting the same failed calculation.
    failure = sync_errors.get(key)
    if failure:
        age = time.monotonic() - float(failure.get("at") or 0)
        if age < SYNC_ERROR_COOLDOWN_SECONDS:
            return JSONResponse(
                {
                    "ok": False,
                    "loading": False,
                    "month_key": month,
                    "period": period,
                    "error": failure.get("message") or "Ошибка синхронизации Bitrix",
                    "retry_after_seconds": max(
                        1, int(SYNC_ERROR_COOLDOWN_SECONDS - age)
                    ),
                },
                status_code=503,
            )
        sync_errors.pop(key, None)

    schedule_snapshot(
        month, period, force=False,
        custom_start=custom_start, custom_end=custom_end
    )
    return JSONResponse(
        {
            "ok": False,
            "loading": True,
            "month_key": month,
            "period": period,
            "elapsed_seconds": 0,
            "message": "Первичная синхронизация Bitrix выполняется в фоне",
        },
        status_code=202,
    )


# Make backend diagnostics match the frontend build.
app.router.routes[:] = [
    route for route in app.router.routes
    if getattr(route, "path", None) != "/health"
]


@app.get("/health")
async def health():
    return {
        "ok": True,
        "bitrix_configured": bool(core.settings.bitrix_webhook),
        "last_error": core.last_error,
        "version": "3.1.14",
        "storage": core.storage.backend_name,
        "supabase_configured": bool(
            core.settings.supabase_url and core.settings.supabase_key
        ),
        "storage_error": core.storage.last_remote_error or "",
        "active_syncs": len(
            [task for task in core.sync_tasks.values() if not task.done()]
        ),
        "sync_errors": len(sync_errors),
    }
