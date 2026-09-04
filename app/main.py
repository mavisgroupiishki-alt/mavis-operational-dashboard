import asyncio
import hashlib
import json
import secrets
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .bitrix import BitrixClient
from .metrics import build_snapshot, filter_prod_details, filter_sales_details
from .demo import demo_snapshot
from .settings import settings
from .storage import Storage

STATIC = Path(__file__).parent / "static"
storage = Storage(settings.data_dir / "mavis_dashboard_v2.sqlite3")
client = BitrixClient(settings.bitrix_webhook)

cache = {}
detail_cache = {}
cache_time = {}
locks = {}
subscribers = set()
refresh_trigger = asyncio.Event()
last_error = None
sync_tasks = {}


def current_month():
    return datetime.now(ZoneInfo(settings.timezone)).strftime("%Y-%m")


def auth_hash():
    return hashlib.sha256((settings.view_password or "").encode()).hexdigest()


def is_public_path(path: str):
    return path in {"/login", "/health"} or path.startswith("/static/")


async def ensure_snapshot(month: str, period: str, force=False):
    global last_error
    key = (month, period)
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
                snap = await build_snapshot(client, month, period, settings.timezone)
                details = snap.pop("_details", {})
            cache[key] = snap
            detail_cache[key] = details
            cache_time[key] = time.monotonic()
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
            await ensure_snapshot(current_month(), "month", force=True)
            await broadcast({"type": "refresh", "month": current_month()})
        except Exception:
            pass


def schedule_snapshot(month: str, period: str, force: bool=False):
    key=(month,period)
    t=sync_tasks.get(key)
    if t and not t.done():
        return t
    async def runner():
        try:
            await ensure_snapshot(month,period,force=force)
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


app = FastAPI(title="MAVIS Operational Dashboard", version="2.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.middleware("http")
async def optional_password(request: Request, call_next):
    if not settings.view_password or is_public_path(request.url.path):
        return await call_next(request)
    if request.cookies.get("mavis_view") == auth_hash():
        return await call_next(request)
    if request.url.path.startswith("/api/") or request.url.path == "/events":
        return JSONResponse({"detail": "AUTH_REQUIRED"}, status_code=401)
    return RedirectResponse("/login", status_code=302)


@app.get("/login", response_class=HTMLResponse)
async def login_page():
    if not settings.view_password:
        return RedirectResponse("/")
    return HTMLResponse("""
<!doctype html><html lang='ru'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>MAVIS · Вход</title><style>body{margin:0;background:#0c0f13;color:#f1f4f6;font-family:system-ui;display:grid;place-items:center;height:100vh}.box{width:min(390px,90vw);background:#12171d;border:1px solid #27303a;border-radius:16px;padding:26px}h1{margin:5px 0 18px;font-size:25px}label{display:block;color:#8f9aa6;font-size:12px;margin-bottom:7px}input{width:100%;box-sizing:border-box;background:#0c1116;border:1px solid #27303a;color:white;padding:12px;border-radius:9px}button{width:100%;margin-top:12px;padding:12px;border:0;border-radius:9px;font-weight:700}</style></head>
<body><form class='box' method='post'><div style='font-size:11px;letter-spacing:.16em;color:#8f9aa6'>MAVIS GROUP</div><h1>Операционный дашборд</h1><label>Пароль доступа</label><input name='password' type='password' autofocus><button>Открыть</button></form></body></html>
""")


@app.post("/login")
async def login(password: str = Form(...)):
    if not settings.view_password or secrets.compare_digest(password, settings.view_password):
        r = RedirectResponse("/", status_code=303)
        r.set_cookie("mavis_view", auth_hash(), httponly=True, secure=True, samesite="lax", max_age=60*60*24*30)
        return r
    return RedirectResponse("/login?error=1", status_code=303)


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


@app.get("/health")
async def health():
    return {"ok": True, "bitrix_configured": bool(settings.bitrix_webhook), "last_error": last_error, "version": "2.1.0"}


@app.get("/api/snapshot")
async def api_snapshot(month: str = Query(default=""), period: str = Query(default="month", pattern="^(month|this_week|last_week)$")):
    month = month or current_month()
    key=(month,period)
    # Stale-while-revalidate: если хоть один snapshot уже есть, отдаём его мгновенно.
    if key in cache:
        ttl=60 if month==current_month() else 600
        stale=time.monotonic()-cache_time.get(key,0)>=ttl
        if stale:
            schedule_snapshot(month,period,force=True)
        return {**cache[key], "plans": storage.plan_dict(month), "syncing": bool(sync_tasks.get(key) and not sync_tasks[key].done())}
    # Первый расчёт запускаем в фоне и НЕ держим HTTP-запрос открытым минутами.
    schedule_snapshot(month,period,force=False)
    return JSONResponse({
        "ok": False, "loading": True, "month_key": month, "period": period,
        "message": "Первичная синхронизация Bitrix выполняется в фоне"
    }, status_code=202)


@app.get("/api/drilldown")
async def drilldown(
    scope: str,
    metric: str,
    month: str = "",
    period: str = "month",
    period_type: str = "current",
    manager: str | None = None,
    group: str | None = None,
    source: str | None = None,
    product: str | None = None,
    expert: str | None = None,
    stage: str | None = None,
    reason: str | None = None,
    week: int | None = None,
):
    month = month or current_month()
    await ensure_snapshot(month, period)
    key=(month,period)
    details=detail_cache.get(key,{})
    if scope == "sales":
        rows=filter_sales_details(details.get("sales",{}), metric, period_type, manager, group, source, product, week, stage)
    elif scope == "production":
        rows=filter_prod_details(details.get("production",{}), metric, expert, product, stage, reason)
    else:
        raise HTTPException(400,"scope должен быть sales или production")
    # Ограничиваем размер ответа, но отдаем общее число.
    rows=sorted(rows,key=lambda r:(r.get("close") or r.get("created") or "", r.get("id") or ""),reverse=True)
    return {"count":len(rows),"rows":rows[:1000]}


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
