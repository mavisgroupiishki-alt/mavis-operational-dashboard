import asyncio
import hashlib
import json
import copy
import math
import secrets
import time
from calendar import monthrange
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Form, HTTPException, Query, Request
import httpx
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .bitrix import BitrixClient
from .metrics import build_snapshot, build_trends_light, filter_prod_details, filter_sales_details
from .demo import demo_snapshot
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
jarvis_operations_cache = {}
jarvis_operations_cache_time = {}


def current_month():
    return datetime.now(ZoneInfo(settings.timezone)).strftime("%Y-%m")


def clean_revenue_period(month: str):
    try:
        year, number = (int(part) for part in month.split("-", 1))
        return f"{year:04d}-{number:02d}-01", f"{year:04d}-{number:02d}-{monthrange(year, number)[1]:02d}"
    except (TypeError, ValueError):
        return "", ""


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
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=False) as session:
            response = await session.get(
                settings.clean_revenue_url,
                params={"date_from": date_from, "date_to": date_to},
                headers={"Authorization": f"Bearer {settings.clean_revenue_token}", "Accept": "application/json"},
            )
        payload = response.json()
        value = float(payload.get("cleanRevenue"))
        if response.status_code != 200 or not payload.get("ok") or not math.isfinite(value):
            raise ValueError("invalid clean revenue response")
        result = {
            "status": "online",
            "value": round(value, 2),
            "date_from": str(payload.get("dateFrom") or date_from),
            "date_to": str(payload.get("dateTo") or date_to),
            "generated_at": str(payload.get("generatedAt") or ""),
        }
        clean_revenue_cache[month] = result
        clean_revenue_cache_time[month] = time.monotonic()
        return result
    except Exception:
        previous = clean_revenue_cache.get(month)
        if previous:
            return {**previous, "status": "stale"}
        return {"status": "unavailable", "value": None}


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


def auth_hash():
    return hashlib.sha256((settings.view_password or "").encode()).hexdigest()


def is_public_path(path: str):
    return path in {"/login", "/health"} or path.startswith("/static/")

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

def _apply_runtime(snap, details, month):
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
    all_rows=list(prod_details.get('dormant') or [])
    # Управленческий показатель «Зависшие» считается только из карточек,
    # чья предполагаемая дата закрытия попадает в выбранный период.
    expected_rows=list(prod_details.get('dormant_expected') or [])
    rows=[r for r in expected_rows if not selected or r.get('stage') in selected]
    p=x.get('production',{});k=p.get('kpi',{})
    k['dormant_all_count']=len(all_rows);k['dormant_all_amount']=round(sum(float(r.get('amount') or 0) for r in all_rows),2)
    k['dormant_count']=len(rows);k['dormant_amount']=round(sum(float(r.get('amount') or 0) for r in rows),2)
    k['dormant_expected_count']=len(rows)
    with_reason=[r for r in rows if r.get('stuck_reasons')]
    without_reason=[r for r in rows if not r.get('stuck_reasons')]
    k['dormant_with_reason_pct']=round(len(with_reason)/len(rows)*100,1) if rows else 0
    k['dormant_without_reason_count']=len(without_reason)
    p.setdefault('dormant',{})['with_reason_count']=len(with_reason);p['dormant']['with_reason_pct']=k['dormant_with_reason_pct']
    from collections import defaultdict
    acc=defaultdict(int)
    for r in rows:
        for reason in r.get('stuck_reasons') or []:acc[reason]+=1
    p['dormant']['reasons']=[{'name':a,'count':b,'pct':round(b/len(rows)*100,1) if rows else 0} for a,b in sorted(acc.items(),key=lambda t:(-t[1],t[0]))]
    return x


async def operational_snapshot(snap, details, month):
    x = _apply_runtime(snap, details, month)
    clean = await load_clean_revenue(month)
    x["clean_revenue"] = clean
    value = clean.get("value")
    metrics = ((x.get("sales") or {}).get("overall") or {}).get("total", {}).get("metrics")
    if value is not None and isinstance(metrics, dict):
        gross = float(metrics.get("sales_amount") or 0)
        sales = float(metrics.get("sales") or 0)
        metrics["gross_sales_amount"] = gross
        metrics["sales_amount"] = value
        metrics["net_revenue"] = value
        metrics["average_check"] = round(value / sales, 2) if sales else 0.0
    return x


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
            cache[key] = snap
            detail_cache[key] = details
            cache_time[key] = time.monotonic()
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
    month: str = Query(default=""),
    period: str = Query(default="month", pattern="^(month|this_week|last_week|custom)$"),
    custom_start: str = "",
    custom_end: str = "",
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
        return {**await operational_snapshot(cache[key], detail_cache.get(key,{}), month), "syncing": bool(sync_tasks.get(key) and not sync_tasks[key].done())}
    # Render memory is empty after restart/redeploy. Try durable Supabase snapshot
    # first and refresh Bitrix in background.
    if await warm_snapshot_from_storage(month,period,custom_start,custom_end):
        schedule_snapshot(month,period,force=True,custom_start=custom_start,custom_end=custom_end)
        return {**await operational_snapshot(cache[key],detail_cache.get(key,{}),month),"syncing":True,"cached_snapshot":True}

    schedule_snapshot(month,period,force=False,custom_start=custom_start,custom_end=custom_end)
    return JSONResponse({
        "ok": False, "loading": True, "month_key": month, "period": period,
        "message": "Первичная синхронизация Bitrix выполняется в фоне"
    }, status_code=202)


@app.get("/api/sales-calls")
async def api_sales_calls():
    return await load_jarvis_operations("sales-calls")


@app.get("/api/jarvis")
async def api_jarvis():
    """Expose only Jarvis's public HTTPS origin; the shared token stays server-side."""
    base_url = settings.jarvis_operations_url.rstrip("/")
    target = urlparse(base_url)
    if not base_url or target.scheme != "https" or not target.netloc:
        return JSONResponse({"ok": False, "status": "not_configured"}, status_code=503)
    return {"ok": True, "url": base_url}


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
        rows=filter_prod_details(details.get("production",{}), metric, expert, product, stage, reason)
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
