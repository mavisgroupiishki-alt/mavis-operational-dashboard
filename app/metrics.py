import asyncio
import json
import math
import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parent
REFERENCE = json.loads((BASE_DIR / "reference_data.json").read_text(encoding="utf-8"))
PROD_NORMS = REFERENCE.get("production_norms", {})
SOURCE_MAP = REFERENCE.get("source_groups", {})

SALES_CATEGORY_IDS = [0, 20]
REANIMATION_CATEGORY_ID = 20
PROD_CATEGORY = 28
DORMANT_CATEGORY = 30

SALES_WON = "WON"
PROD_WON = "C28:WON"
PROD_RETURN = "C28:APOLOGY"
DORMANT_TO_PROD = "C30:WON"

F_SERVICE = "UF_CRM_1765113071"
F_EXPECTED_CLOSE = "UF_CRM_1765875991647"
F_PROD_START = "UF_CRM_1703225329"
F_RETURN_REASON = "UF_CRM_1764496013454"
F_STUCK_REASON_OLD = "UF_CRM_1764496088031"
F_STUCK_REASON_NEW = "UF_CRM_1785932240544"
F_SALES_MANAGER = "UF_CRM_1674809919"
F_SALES_LINK = "UF_CRM_1765117204"
F_PAID_OLD = "UF_CRM_1654754709"
F_PAID = "UF_CRM_1779453856340"
F_NET_REVENUE = "UF_CRM_1787226797"
F_OUR_AMOUNT = "UF_CRM_MPS_OUR_AMOUNT"
F_CONTRACTOR_COST = "UF_CRM_MPS_CONTRACTOR_COST"
F_PAYMENTS_TOTAL = "UF_CRM_MPS_PAYMENTS_TOTAL"
F_PAYMENT_REMAINDER = "UF_CRM_MPS_REMAINDER"
F_NEXT_PAYMENT = "UF_CRM_MPS_NEXT_DATE"
F_NPS = "UF_CRM_1781707277198"
F_ACT = "UF_CRM_1785928288816"

DEAL_SELECT = [
    "ID", "TITLE", "CATEGORY_ID", "STAGE_ID", "STAGE_SEMANTIC_ID", "OPPORTUNITY", "CURRENCY_ID",
    "DATE_CREATE", "DATE_MODIFY", "CLOSEDATE", "MOVED_TIME", "PREVIOUS_STAGE_ID", "ASSIGNED_BY_ID", "SOURCE_ID", "SOURCE_DESCRIPTION", "CLOSED",
    F_SERVICE, F_EXPECTED_CLOSE, F_PROD_START, F_RETURN_REASON, F_STUCK_REASON_OLD, F_STUCK_REASON_NEW,
    F_SALES_MANAGER, F_SALES_LINK, F_PAID_OLD, F_PAID, F_NET_REVENUE, F_OUR_AMOUNT,
    F_CONTRACTOR_COST, F_PAYMENTS_TOTAL, F_PAYMENT_REMAINDER, F_NEXT_PAYMENT, F_NPS, F_ACT,
]
LEAD_SELECT = [
    "ID", "TITLE", "STATUS_ID", "SOURCE_ID", "SOURCE_DESCRIPTION", "DATE_CREATE", "DATE_MODIFY",
    "ASSIGNED_BY_ID", "OPPORTUNITY", "CURRENCY_ID"
]

SALES_METRICS = [
    "leads", "qualified", "qualified_rate", "lead_to_deal_rate", "deals", "deal_amount",
    "sales", "sales_amount", "average_check", "deal_to_sale_rate", "products_per_deal",
    "products", "product_amount", "sold_products", "sold_product_amount", "average_product_check",
    "product_sale_rate", "paid_amount", "net_revenue"
]

PROD_METRICS = [
    "closed_amount", "closed_count", "new_count", "new_amount", "period_closed_count", "period_closed_amount",
    "new_to_success_pct", "avg_check", "capacity_count", "capacity_amount", "returns_count", "returns_amount",
    "avg_production_days", "avg_deviation_days", "within_norm_pct", "nps_avg", "act_share_pct",
    "dormant_count", "returned_to_production", "dormant_with_reason_pct"
]


def num(v: Any) -> float:
    if v in (None, "", False):
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, list):
        return sum(num(x) for x in v)
    s = str(v).strip().replace(" ", "").replace(",", ".")
    if "|" in s:
        s = s.split("|", 1)[0]
    try:
        return float(s)
    except Exception:
        return 0.0


def pct(a: float, b: float) -> float:
    return round(a / b * 100, 1) if b else 0.0


def parse_dt(v: Any, tz: Optional[ZoneInfo] = None) -> Optional[datetime]:
    if not v:
        return None
    if isinstance(v, datetime):
        d = v
    else:
        s = str(v).strip()
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            try:
                d = datetime.strptime(s[:10], "%Y-%m-%d")
            except Exception:
                return None
    if tz:
        if d.tzinfo is None:
            d = d.replace(tzinfo=tz)
        else:
            d = d.astimezone(tz)
    return d


def iso(d: datetime) -> str:
    return d.isoformat()


def money(d: Dict[str, Any]) -> float:
    return num(d.get("OPPORTUNITY"))


def month_bounds(month_key: str, tz_name: str) -> Tuple[datetime, datetime, datetime, str]:
    tz = ZoneInfo(tz_name)
    now = datetime.now(tz)
    try:
        y, m = [int(x) for x in month_key.split("-")]
    except Exception:
        y, m = now.year, now.month
    start = datetime(y, m, 1, tzinfo=tz)
    end = datetime(y + (m == 12), 1 if m == 12 else m + 1, 1, tzinfo=tz)
    prev1_month = m - 1
    prev1_year = y
    if prev1_month == 0:
        prev1_month = 12
        prev1_year -= 1
    prev2_month = prev1_month - 1
    prev2_year = prev1_year
    if prev2_month == 0:
        prev2_month = 12
        prev2_year -= 1
    previous_two_start = datetime(prev2_year, prev2_month, 1, tzinfo=tz)
    return start, end, previous_two_start, now.isoformat()


def period_bounds(month_key: str, period: str, tz_name: str, custom_start: str = "", custom_end: str = "") -> Tuple[datetime, datetime, str]:
    start, end, _, _ = month_bounds(month_key, tz_name)
    tz = ZoneInfo(tz_name)
    now = datetime.now(tz)
    if period == "custom" and custom_start and custom_end:
        try:
            a = datetime.strptime(custom_start[:10], "%Y-%m-%d").replace(tzinfo=tz)
            b_inclusive = datetime.strptime(custom_end[:10], "%Y-%m-%d").replace(tzinfo=tz)
            if b_inclusive < a:
                a, b_inclusive = b_inclusive, a
            b = b_inclusive + timedelta(days=1)
            return a, b, f"{a.strftime('%d.%m.%Y')}–{b_inclusive.strftime('%d.%m.%Y')}"
        except Exception:
            pass
    if period == "last_week":
        anchor = min(now, end - timedelta(seconds=1))
        monday = anchor.date() - timedelta(days=anchor.weekday())
        this_monday = datetime.combine(monday, datetime.min.time(), tzinfo=tz)
        return this_monday - timedelta(days=7), this_monday, "Прошедшая неделя"
    if period == "this_week":
        anchor = min(now, end - timedelta(seconds=1))
        monday = anchor.date() - timedelta(days=anchor.weekday())
        this_monday = datetime.combine(monday, datetime.min.time(), tzinfo=tz)
        return max(start, this_monday), min(end, this_monday + timedelta(days=7)), "Текущая неделя"
    return start, end, "Текущий месяц"


def month_diff(d: Optional[datetime], month_start: datetime) -> Optional[int]:
    if not d:
        return None
    return (d.year * 12 + d.month) - (month_start.year * 12 + month_start.month)


def week_of_month(d: Optional[datetime], month_start: datetime) -> int:
    if not d or d.year != month_start.year or d.month != month_start.month:
        return -1
    return min(4, max(0, (d.day - 1) // 7))


def business_days(a: Optional[datetime], b: Optional[datetime]) -> Optional[int]:
    if not a or not b:
        return None
    start, end = a.date(), b.date()
    if end < start:
        return 0
    n = 0
    d = start
    while d <= end:
        if d.weekday() < 5:
            n += 1
        d += timedelta(days=1)
    return n


def calendar_days(a: Optional[datetime], b: Optional[datetime]) -> Optional[int]:
    if not a or not b:
        return None
    return max(0, (b.date() - a.date()).days)


def norm_text(s: Any) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip().lower().replace("ё", "е"))


def source_group(name: str) -> str:
    n = norm_text(name)
    if "холод" in n:
        return "Холодный звонок"
    if re.search(r"реанимац|повтор|успешн.*клиент|передан.*эксперт|действующ", n):
        return "Из реанимации"
    if re.search(r"входящ|партнер|партнёр|яндекс|google|гугл|заявк.*сайт|органик|реклам|рекомендац|электрон.*почт|telegram|телеграм|tgapi|viber|вайбер|instagram|инстаграм|соцсет", n):
        return "Входящий звонок (прямой)"
    mapped = SOURCE_MAP.get(name)
    if mapped:
        return mapped
    return "Прочее"


def product_category(name: str) -> str:
    n = norm_text(name)
    if re.search(r"iso|исо|суот|систем.*менедж|внутрен.*аудит", n):
        return "Системы менеджмента"
    if re.search(r"специалист|обучен|повышен.*квалиф|удостовер|аттестац.*специал|подбор", n):
        return "Специалисты"
    if re.search(r"спк|свидетельств.*технич|аттестац.*организац|строител|смр|техкомпет|осп", n):
        return "Строительство"
    if "лиценз" in n:
        return "Лицензирование"
    if re.search(r"тр\s*тс|декларац|сертифик.*продук|сгр|техническ.*услов|\bту\b|белтпп|происхожд", n):
        return "Продукция"
    return "Не определено"


def match_norm_name(service: str) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    n = norm_text(service)
    aliases = [
        (r"^спк$|спк смр", "СПК"),
        (r"ик спк", "ИК СПК"),
        (r"расшир.*спк", "Расширение СПК"),
        (r"подтверж.*аттест", "Подтверждение Аттестация"),
        (r"аттестац.*спец", "Аттестация специалиста"),
        (r"аттестац", "Аттестация"),
        (r"период.*iso|период.*исо|ик исо", "ИК ИСО 9001"),
        (r"iso 27001|исо 27001", "ИСО 27001"),
        (r"iso 9001|исо 9001", "ИСО 9001"),
        (r"период.*суот|ик суот", "ИК СУОТ 45001"),
        (r"разработ.*суот", "Разработка СУОТ 45001"),
        (r"суот", "Сертификат СУОТ 45001"),
        (r"лиценз.*мчс", "Лицензия МЧС"),
        (r"лиценз.*мвд", "Лицензия МВД"),
        (r"лиценз.*гпн", "Лицензия ГПН"),
        (r"подбор.*подряд", "Подбор от подрядчика"),
        (r"подбор.*совмест", "Подбор совместителя"),
        (r"подбор", "Подбор"),
        (r"вступ.*сро", "Вступление в СРО"),
        (r"внес.*спец.*сро", "Внесение спецов СРО"),
        (r"осп|свароч", "ОСП"),
        (r"тех.*свидетель", "ТС (тех.свидетельство с последующим декларированием)"),
        (r"\bтр\b|тех регламент", "ТР базовый"),
        (r"\bту\b|тех.*услов", "ТУ (регистрация)"),
        (r"сертифик.*продук", "Сертификация продукции"),
        (r"консультац", "Консультация"),
    ]
    for pat, key in aliases:
        if re.search(pat, n):
            return key, PROD_NORMS.get(key)
    for key, spec in PROD_NORMS.items():
        if norm_text(key) == n:
            return key, spec
    return None, None


def enum_label(meta: Dict[str, Any], field: str, raw: Any) -> Any:
    if raw in (None, "", False):
        return None
    mp = (meta.get("enums") or {}).get(field, {})
    if isinstance(raw, list):
        return [mp.get(str(x), str(x)) for x in raw]
    return mp.get(str(raw), str(raw))


def source_name(meta: Dict[str, Any], entity: Dict[str, Any], reanimation=False) -> str:
    if reanimation:
        return "Из реанимации"
    sid = str(entity.get("SOURCE_ID") or "")
    return (meta.get("sources") or {}).get(sid) or entity.get("SOURCE_DESCRIPTION") or sid or "Прочее"


def user_name(meta: Dict[str, Any], uid: Any) -> str:
    return (meta.get("users") or {}).get(str(uid), str(uid or "Не указан"))


def stage_name(meta: Dict[str, Any], sid: Any, entity: Optional[str] = None) -> str:
    if entity:
        v=((meta.get("status_by_entity") or {}).get(entity) or {}).get(str(sid))
        if v: return v
    return (meta.get("statuses") or {}).get(str(sid), str(sid or "Не указана"))


def successful_sale_stage_ids(meta: Dict[str, Any]) -> set[str]:
    """Stages included in OP sales/revenue.

    Agreed logic:
    - 14. Предоплата получена
    - 15. Продажа успешна
    Revenue period is determined by CLOSEDATE, not MOVED_TIME.
    """
    stages = ((meta.get("status_by_entity") or {}).get("DEAL_STAGE") or {})
    result = set()
    for sid, name in stages.items():
        n = norm_text(name)
        if "предоплата получена" in n or "продажа успешна" in n:
            result.add(str(sid))
    return result


def pay_amount(d: Dict[str, Any]) -> float:
    return max(num(d.get(F_PAID)), num(d.get(F_PAID_OLD)), num(d.get(F_PAYMENTS_TOTAL)))


def make_deal_url(portal: str, deal_id: Any) -> str:
    return f"{portal}/crm/deal/details/{deal_id}/"


def make_lead_url(portal: str, lead_id: Any) -> str:
    return f"{portal}/crm/lead/details/{lead_id}/"


def aggregate_sales(records: Dict[str, List[Dict[str, Any]]], period_type="total", manager=None, group=None,
                    source=None, product_cat=None, month_start=None) -> Dict[str, Any]:
    leads = records["leads"]
    deals = records["deals"]

    def common(r):
        if manager and r.get("manager") != manager:
            return False
        if group and r.get("group") != group:
            return False
        if source and r.get("source") != source:
            return False
        return True

    lead_rows = []
    if period_type != "previous":
        lead_rows = [r for r in leads if common(r) and r.get("period_type") == "current"]
    qual_rows = [r for r in lead_rows if r.get("is_qualified")]

    deal_rows = [r for r in deals if common(r) and (period_type == "total" or r.get("period_type") == period_type)]
    if product_cat:
        deal_rows = [r for r in deal_rows if any(p.get("category") == product_cat for p in r.get("products", []))]

    sales_rows = [r for r in deal_rows if r.get("is_won") and r.get("sale_in_report_month")]

    products = []
    sold_products = []
    for d in deal_rows:
        for p in d.get("products", []):
            if product_cat and p.get("category") != product_cat:
                continue
            products.append({**p, "deal_id": d["id"], "deal_title": d["title"], "manager": d["manager"], "source": d["source"], "url": d["url"], "week": d.get("creation_week", -1)})
    for d in sales_rows:
        for p in d.get("products", []):
            if product_cat and p.get("category") != product_cat:
                continue
            sold_products.append({**p, "deal_id": d["id"], "deal_title": d["title"], "manager": d["manager"], "source": d["source"], "url": d["url"], "week": d.get("sale_week", -1)})

    conversion_deal_rows = deal_rows
    if period_type == "total":
        conversion_deal_rows = [r for r in deals if common(r) and r.get("period_type") == "current"]
        if product_cat:
            conversion_deal_rows = [r for r in conversion_deal_rows if any(p.get("category") == product_cat for p in r.get("products", []))]

    m = {
        "leads": len(lead_rows),
        "qualified": len(qual_rows),
        "qualified_rate": pct(len(qual_rows), len(lead_rows)),
        "lead_to_deal_rate": pct(len(conversion_deal_rows), len(qual_rows)),
        "deals": len(deal_rows),
        "deal_amount": round(sum(r["amount"] for r in deal_rows), 2),
        "sales": len(sales_rows),
        "sales_amount": round(sum(r["amount"] for r in sales_rows), 2),
        "average_check": round(sum(r["amount"] for r in sales_rows) / len(sales_rows), 2) if sales_rows else 0,
        "deal_to_sale_rate": pct(len(sales_rows), len(deal_rows)),
        "products_per_deal": round(sum(p["quantity"] for p in products) / len(deal_rows), 2) if deal_rows else 0,
        "products": round(sum(p["quantity"] for p in products), 2),
        "product_amount": round(sum(p["amount"] for p in products), 2),
        "sold_products": round(sum(p["quantity"] for p in sold_products), 2),
        "sold_product_amount": round(sum(p["amount"] for p in sold_products), 2),
        "average_product_check": round(sum(p["amount"] for p in sold_products) / sum(p["quantity"] for p in sold_products), 2) if sold_products and sum(p["quantity"] for p in sold_products) else 0,
        "product_sale_rate": pct(sum(p["quantity"] for p in sold_products), sum(p["quantity"] for p in products)),
        "paid_amount": round(sum(r.get("paid_amount", 0) for r in sales_rows), 2),
        "net_revenue": round(sum(r.get("net_revenue", 0) for r in sales_rows), 2),
    }

    weeks = {k: [0, 0, 0, 0, 0] for k in [
        "leads", "qualified", "deals", "deal_amount", "sales", "sales_amount", "products", "product_amount", "sold_products", "sold_product_amount"
    ]}
    for r in lead_rows:
        w = r.get("week", -1)
        if w >= 0:
            weeks["leads"][w] += 1
            if r.get("is_qualified"):
                weeks["qualified"][w] += 1
    for r in deal_rows:
        w = r.get("creation_week", -1)
        if w >= 0:
            weeks["deals"][w] += 1
            weeks["deal_amount"][w] += r["amount"]
            for p in r.get("products", []):
                if not product_cat or p.get("category") == product_cat:
                    weeks["products"][w] += p["quantity"]
                    weeks["product_amount"][w] += p["amount"]
    for r in sales_rows:
        w = r.get("sale_week", -1)
        if w >= 0:
            weeks["sales"][w] += 1
            weeks["sales_amount"][w] += r["amount"]
            for p in r.get("products", []):
                if not product_cat or p.get("category") == product_cat:
                    weeks["sold_products"][w] += p["quantity"]
                    weeks["sold_product_amount"][w] += p["amount"]
    weeks["qualified_rate"] = [pct(weeks["qualified"][i], weeks["leads"][i]) for i in range(5)]
    weeks["lead_to_deal_rate"] = [pct(weeks["deals"][i], weeks["qualified"][i]) for i in range(5)]
    return {"metrics": m, "weeks": weeks}


async def load_sales(client, month_key: str, meta: Dict[str, Any], tz_name: str):
    month_start, next_start, prev2_start, _ = month_bounds(month_key, tz_name)
    tz = ZoneInfo(tz_name)

    # СОГЛАСОВАННАЯ ЛОГИКА ОП ИЗ ФИНАЛЬНОГО ОТЧЁТА:
    # - отчётный период: сделки, созданные в выбранном месяце;
    # - хвост: сделки, созданные до начала месяца и не закрытые до начала месяца;
    # - продажа/выручка: текущая стадия «14. Предоплата получена»
    #   ИЛИ «15. Продажа успешна»;
    # - дата попадания в месяц: CLOSEDATE;
    # - сумма продажи: OPPORTUNITY.
    success_stage_ids = successful_sale_stage_ids(meta)

    deal_tasks = []
    # Сделки отчётного периода — созданные в месяце.
    for cid in SALES_CATEGORY_IDS:
        deal_tasks.append(client.deal_list({
            "CATEGORY_ID": cid,
            ">=DATE_CREATE": iso(month_start),
            "<DATE_CREATE": iso(next_start),
        }, DEAL_SELECT))

    # Хвост на начало месяца: старые сделки, которые всё ещё активны сейчас,
    # плюс сделки, закрытые после начала выбранного месяца. Дедупликация ниже.
    for cid in SALES_CATEGORY_IDS:
        deal_tasks.append(client.deal_list({
            "CATEGORY_ID": cid,
            "<DATE_CREATE": iso(month_start),
            "CLOSED": "N",
        }, DEAL_SELECT))
        deal_tasks.append(client.deal_list({
            "CATEGORY_ID": cid,
            "<DATE_CREATE": iso(month_start),
            ">=CLOSEDATE": iso(month_start),
        }, DEAL_SELECT))

    # Все продажи месяца берём отдельно по двум стадиям:
    # «Предоплата получена» и «Продажа успешна».
    # Период определяется по дате завершения сделки (CLOSEDATE).
    # Так в итог попадут и сделки хвоста любой давности.
    if success_stage_ids:
        for sid in success_stage_ids:
            deal_tasks.append(client.deal_list({
                "CATEGORY_ID": 0,
                "STAGE_ID": sid,
                ">=CLOSEDATE": iso(month_start),
                "<CLOSEDATE": iso(next_start),
            }, DEAL_SELECT))

    leads_task = client.lead_list({
        ">=DATE_CREATE": iso(month_start),
        "<DATE_CREATE": iso(next_start),
    }, LEAD_SELECT)

    results = await asyncio.gather(*deal_tasks, leads_task)
    leads_raw = results[-1] or []
    deals_raw = []
    for block in results[:-1]:
        deals_raw.extend(block or [])
    deals_raw = list({str(d.get("ID")): d for d in deals_raw}.values())
    rows_by_deal = await client.product_rows_many(deals_raw)

    success_stage_names = [
        name for sid, name in (((meta.get("status_by_entity") or {}).get("DEAL_STAGE") or {}).items())
        if str(sid) in success_stage_ids
    ]

    deals = []
    for d in deals_raw:
        cid = int(d.get("CATEGORY_ID") or 0)
        created = parse_dt(d.get("DATE_CREATE"), tz)
        close = parse_dt(d.get("CLOSEDATE"), tz)
        moved = parse_dt(d.get("MOVED_TIME"), tz)
        if created and month_start <= created < next_start:
            ptype = "current"
        elif created and created < month_start:
            ptype = "previous"
        else:
            ptype = "older"
        src = source_name(meta, d, cid == REANIMATION_CATEGORY_ID)
        deal_stage_name = stage_name(meta, d.get("STAGE_ID"), "DEAL_STAGE" if cid == 0 else f"DEAL_STAGE_{cid}")
        is_won = cid == 0 and str(d.get("STAGE_ID")) in success_stage_ids
        product_rows = []
        for p in rows_by_deal.get(str(d.get("ID")), []):
            name = p.get("productName") or p.get("PRODUCT_NAME") or p.get("PRODUCT_ID") or "Без названия"
            q = num(p.get("quantity", p.get("QUANTITY", 1))) or 1
            price = num(p.get("price", p.get("PRICE", 0)))
            product_rows.append({"name": str(name), "category": product_category(str(name)), "quantity": q, "amount": round(price * q, 2)})
        products_amount = sum(p["amount"] for p in product_rows)
        amount = money(d)
        deals.append({
            "kind": "deal", "id": str(d.get("ID")), "title": d.get("TITLE") or f"Сделка {d.get('ID')}",
            "category_id": cid, "manager": user_name(meta, d.get("ASSIGNED_BY_ID")), "source": src,
            "group": source_group(src), "stage": deal_stage_name, "stage_id": d.get("STAGE_ID"),
            "created": created.isoformat() if created else None, "close": close.isoformat() if close else None,
            "period_type": ptype, "creation_week": week_of_month(created, month_start), "sale_week": week_of_month(close, month_start),
            "sale_in_report_month": bool(close and month_start <= close < next_start), "is_won": bool(is_won),
            "moved_time": moved.isoformat() if moved else None,
            "amount": round(amount, 2), "paid_amount": pay_amount(d), "net_revenue": num(d.get(F_NET_REVENUE)),
            "products": product_rows, "url": make_deal_url(client.portal, d.get("ID")),
        })

    leads = []
    qualified_needle = "качественный лид"
    for l in leads_raw:
        created = parse_dt(l.get("DATE_CREATE"), tz)
        ptype = "current" if created and month_start <= created < next_start else "older"
        status = stage_name(meta, l.get("STATUS_ID"), "STATUS")
        src = source_name(meta, l)
        leads.append({
            "kind": "lead", "id": str(l.get("ID")), "title": l.get("TITLE") or f"Лид {l.get('ID')}",
            "manager": user_name(meta, l.get("ASSIGNED_BY_ID")), "source": src, "group": source_group(src),
            "status": status, "is_qualified": norm_text(status) == qualified_needle or str(l.get("STATUS_ID")) == "CONVERTED",
            "created": created.isoformat() if created else None, "period_type": ptype,
            "week": week_of_month(created, month_start), "url": make_lead_url(client.portal, l.get("ID")),
        })

    records = {"leads": leads, "deals": deals}
    overall = {p: aggregate_sales(records, p, month_start=month_start) for p in ["total", "current", "previous"]}

    groups = []
    for g in ["Холодный звонок", "Входящий звонок (прямой)", "Из реанимации", "Прочее"]:
        row = {"name": g}
        for p in ["total", "current", "previous"]:
            row[p] = aggregate_sales(records, p, group=g, month_start=month_start)
        groups.append(row)

    exact_sources = []
    for s in sorted({r["source"] for r in leads + deals}):
        row = {"name": s, "group": source_group(s)}
        for p in ["total", "current", "previous"]:
            row[p] = aggregate_sales(records, p, source=s, month_start=month_start)
        exact_sources.append(row)

    managers = []
    for m in sorted({r["manager"] for r in leads + deals if r.get("manager")}):
        row = {"name": m}
        for p in ["total", "current", "previous"]:
            row[p] = aggregate_sales(records, p, manager=m, month_start=month_start)
        row["groups"] = []
        for g in ["Холодный звонок", "Входящий звонок (прямой)", "Из реанимации", "Прочее"]:
            grow = {"name": g}
            for p in ["total", "current", "previous"]:
                grow[p] = aggregate_sales(records, p, manager=m, group=g, month_start=month_start)
            row["groups"].append(grow)
        managers.append(row)

    product_categories = []
    for pc in ["Системы менеджмента", "Специалисты", "Строительство", "Лицензирование", "Продукция", "Не определено"]:
        row = {"name": pc}
        for p in ["total", "current", "previous"]:
            row[p] = aggregate_sales(records, p, product_cat=pc, month_start=month_start)
        if any(row[p]["metrics"]["products"] for p in ["total", "current", "previous"]):
            product_categories.append(row)

    product_managers = []
    for m in managers:
        cats = []
        for pc in ["Системы менеджмента", "Специалисты", "Строительство", "Лицензирование", "Продукция", "Не определено"]:
            row = {"name": pc}
            for p in ["total", "current", "previous"]:
                row[p] = aggregate_sales(records, p, manager=m["name"], product_cat=pc, month_start=month_start)
            if any(row[p]["metrics"]["products"] for p in ["total", "current", "previous"]):
                cats.append(row)
        product_managers.append({"name": m["name"], "categories": cats})

    active = await client.deal_list({"CATEGORY_ID": 0, "CLOSED": "N"}, DEAL_SELECT) or []
    stages = defaultdict(lambda: {"count": 0, "amount": 0.0})
    active_records = []
    for d in active:
        name = stage_name(meta, d.get("STAGE_ID"), "DEAL_STAGE")
        stages[name]["count"] += 1
        stages[name]["amount"] += money(d)
        created = parse_dt(d.get("DATE_CREATE"), tz)
        src = source_name(meta, d, False)
        active_records.append({
            "kind":"deal", "id":str(d.get("ID")), "title":d.get("TITLE") or f"Сделка {d.get('ID')}",
            "manager":user_name(meta,d.get("ASSIGNED_BY_ID")), "source":src, "group":source_group(src),
            "stage":name, "stage_id":d.get("STAGE_ID"), "amount":round(money(d),2),
            "created":created.isoformat() if created else None, "url":make_deal_url(client.portal,d.get("ID")),
        })
    stage_rows = [{"name": k, "count": v["count"], "amount": round(v["amount"], 2)} for k, v in stages.items()]
    stage_rows.sort(key=lambda x: -x["amount"])
    records["active"] = active_records

    return {
        "overall": overall, "groups": groups, "exact_sources": exact_sources, "managers": managers,
        "product_categories": product_categories, "product_managers": product_managers,
        "stages": stage_rows, "active_deals_count": len(active),
        "sale_filter": {
            "stage_ids": sorted(success_stage_ids),
            "stage_names": success_stage_names,
            "rule": "Переход в стадию «15. Продажа успешна» в выбранном периоде; дата продажи = дата изменения стадии (MOVED_TIME)",
            "amount_source": "Поле «Сумма» сделки Bitrix (OPPORTUNITY)",
        },
        "_records": records,
    }


def prod_item(client, meta, d, tz, month_start, next_start, role="production"):
    created = parse_dt(d.get("DATE_CREATE"), tz)
    modified = parse_dt(d.get("DATE_MODIFY"), tz)
    close = parse_dt(d.get("CLOSEDATE"), tz)
    prod_start = parse_dt(d.get(F_PROD_START), tz)
    expected = parse_dt(d.get(F_EXPECTED_CLOSE), tz)
    service = d.get(F_SERVICE) or "Не указано"
    norm_name, norm_spec = match_norm_name(str(service))
    prod_days = business_days(prod_start, close)
    full_days = calendar_days(created, close)
    norm_days = num((norm_spec or {}).get("norm_days")) if norm_spec else 0
    in_norm = bool(prod_days is not None and norm_days > 0 and prod_days <= norm_days)
    reasons = []
    for f in [F_STUCK_REASON_OLD, F_STUCK_REASON_NEW]:
        raw = enum_label(meta, f, d.get(f))
        if isinstance(raw, list):
            reasons.extend([str(x) for x in raw if x])
        elif raw:
            reasons.append(str(raw))
    reasons = list(dict.fromkeys(reasons))
    return {
        "kind": role, "id": str(d.get("ID")), "title": d.get("TITLE") or f"Сделка {d.get('ID')}",
        "service": str(service), "norm_name": norm_name, "complexity": (norm_spec or {}).get("complexity"),
        "base_bonus": num((norm_spec or {}).get("base_bonus")), "norm_days": norm_days,
        "category": product_category(str(service)), "expert": user_name(meta, d.get("ASSIGNED_BY_ID")),
        "stage": stage_name(meta, d.get("STAGE_ID"), "DEAL_STAGE_28" if role == "production" else "DEAL_STAGE_30"), "stage_id": d.get("STAGE_ID"), "amount": round(money(d), 2),
        "created": created.isoformat() if created else None, "modified": modified.isoformat() if modified else None,
        "close": close.isoformat() if close else None, "prod_start": prod_start.isoformat() if prod_start else None,
        "expected_close": expected.isoformat() if expected else None, "prod_days": prod_days, "full_cycle_days": full_days,
        "in_norm": in_norm, "deviation_days": round((prod_days or 0) - norm_days, 1) if prod_days is not None and norm_days else None,
        "nps": num(d.get(F_NPS)), "act": enum_label(meta, F_ACT, d.get(F_ACT)),
        "return_reason": enum_label(meta, F_RETURN_REASON, d.get(F_RETURN_REASON)), "stuck_reasons": reasons,
        "inactive_days": (datetime.now(tz).date() - modified.date()).days if modified else None,
        "url": make_deal_url(client.portal, d.get("ID")),
    }


def aggregate_prod_rows(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    closed = [r for r in rows if r.get("is_closed_success")]
    days = [r["prod_days"] for r in closed if r.get("prod_days") is not None]
    normed = [r for r in closed if r.get("norm_days")]
    deviations = [r["deviation_days"] for r in closed if r.get("deviation_days") is not None]
    acts = [r for r in closed if norm_text(r.get("act")) == "да"]
    return {
        "closed_count": len(closed), "closed_amount": round(sum(r["amount"] for r in closed), 2),
        "avg_check": round(sum(r["amount"] for r in closed) / len(closed), 2) if closed else 0,
        "avg_production_days": round(sum(days) / len(days), 1) if days else 0,
        "avg_deviation_days": round(sum(deviations) / len(deviations), 1) if deviations else 0,
        "within_norm_pct": pct(sum(1 for r in normed if r.get("in_norm")), len(normed)),
        # NPS в приложении только ручной. Bitrix-поле не участвует в расчёте.
        "nps_avg": 0,
        "act_share_pct": pct(len(acts), len(closed)),
    }


async def load_production(client, month_key: str, period: str, meta: Dict[str, Any], tz_name: str, custom_start: str = "", custom_end: str = ""):
    month_start, next_start, _, _ = month_bounds(month_key, tz_name)
    range_start, range_end, period_label = period_bounds(month_key, period, tz_name, custom_start, custom_end)
    tz = ZoneInfo(tz_name)
    now = datetime.now(tz)

    new_task = client.deal_list({"CATEGORY_ID": PROD_CATEGORY, ">=DATE_CREATE": iso(range_start), "<DATE_CREATE": iso(range_end)}, DEAL_SELECT)
    closed_task = client.deal_list({"CATEGORY_ID": PROD_CATEGORY, "STAGE_ID": PROD_WON, ">=CLOSEDATE": iso(range_start), "<CLOSEDATE": iso(range_end)}, DEAL_SELECT)
    returns_task = client.deal_list({"CATEGORY_ID": PROD_CATEGORY, "STAGE_ID": PROD_RETURN, ">=CLOSEDATE": iso(range_start), "<CLOSEDATE": iso(range_end)}, DEAL_SELECT)
    active_task = client.deal_list({"CATEGORY_ID": PROD_CATEGORY, "CLOSED": "N"}, DEAL_SELECT)
    dormant_task = client.deal_list({"CATEGORY_ID": DORMANT_CATEGORY, "CLOSED": "N"}, DEAL_SELECT)
    returned_task = client.deal_list({"CATEGORY_ID": DORMANT_CATEGORY, "STAGE_ID": DORMANT_TO_PROD, ">=CLOSEDATE": iso(range_start), "<CLOSEDATE": iso(range_end)}, DEAL_SELECT)
    new_raw, closed_raw, returns_raw, active_raw, dormant_raw, returned_raw = await asyncio.gather(
        new_task, closed_task, returns_task, active_task, dormant_task, returned_task
    )
    new_raw, closed_raw, returns_raw, active_raw, dormant_raw, returned_raw = [x or [] for x in [new_raw, closed_raw, returns_raw, active_raw, dormant_raw, returned_raw]]

    def convert(rows, role="production"):
        return [prod_item(client, meta, d, tz, month_start, next_start, role=role) for d in rows]

    new = convert(new_raw)
    closed = convert(closed_raw)
    returns = convert(returns_raw)
    active = convert(active_raw)
    dormant = convert(dormant_raw, role="dormant")
    returned = convert(returned_raw, role="dormant")

    closed_ids = {r["id"] for r in closed}
    new_ids = {r["id"] for r in new}
    for r in closed:
        r["is_closed_success"] = True
        r["is_new_in_period"] = r["id"] in new_ids
    for coll in [new, active, returns, dormant, returned]:
        for r in coll:
            r["is_closed_success"] = r["id"] in closed_ids
            r["is_new_in_period"] = r["id"] in new_ids

    period_closed = [r for r in closed if r["id"] in new_ids]
    capacity = [r for r in active if (x := parse_dt(r.get("expected_close"), tz)) and range_start <= x < range_end]
    overdue = [r for r in active if (x := parse_dt(r.get("expected_close"), tz)) and x.date() < now.date()]
    dormant_expected = [r for r in dormant if (x := parse_dt(r.get("expected_close"), tz)) and range_start <= x < range_end]
    dormant_overdue = [r for r in dormant if (x := parse_dt(r.get("expected_close"), tz)) and x.date() < now.date()]
    active_missing_expected = [r for r in active if not r.get("expected_close")]
    active_missing_service = [r for r in active if norm_text(r.get("service")) in {"", "не указано"}]
    active_missing_expert = [r for r in active if norm_text(r.get("expert")) in {"", "не указан", "не указано"}]
    closed_without_act = [r for r in closed if norm_text(r.get("act")) != "да"]

    closed_stats = aggregate_prod_rows(closed)
    kpi = {
        **closed_stats,
        "closed_amount": closed_stats["closed_amount"], "closed_count": closed_stats["closed_count"],
        "new_count": len(new), "new_amount": round(sum(r["amount"] for r in new), 2),
        "period_closed_count": len(period_closed), "period_closed_amount": round(sum(r["amount"] for r in period_closed), 2),
        "new_to_success_pct": pct(len(period_closed), len(new)),
        "capacity_count": len(capacity), "capacity_amount": round(sum(r["amount"] for r in capacity), 2),
        "returns_count": len(returns), "returns_amount": round(sum(r["amount"] for r in returns), 2),
        "dormant_count": len(dormant), "dormant_amount": round(sum(r["amount"] for r in dormant), 2),
        "returned_to_production": len(returned), "returned_to_production_amount": round(sum(r["amount"] for r in returned), 2),
        "dormant_expected_count": len(dormant_expected), "dormant_overdue_count": len(dormant_overdue),
        "active_missing_expected_count": len(active_missing_expected),
        "active_missing_service_count": len(active_missing_service),
        "active_missing_expert_count": len(active_missing_expert),
        "closed_without_act_count": len(closed_without_act),
    }
    with_reason = [r for r in dormant if r.get("stuck_reasons")]
    kpi["dormant_with_reason_pct"] = pct(len(with_reason), len(dormant))

    product_names = sorted({r["service"] for r in new + closed + active + returns if r.get("service")})
    products = []
    for name in product_names:
        nr = [r for r in new if r["service"] == name]
        cr = [r for r in closed if r["service"] == name]
        pr = [r for r in period_closed if r["service"] == name]
        ar = [r for r in active if r["service"] == name]
        rr = [r for r in returns if r["service"] == name]
        cap = [r for r in capacity if r["service"] == name]
        s = aggregate_prod_rows(cr)
        norm_name, norm_spec = match_norm_name(name)
        products.append({
            "name": name, "category": product_category(name), "complexity": (norm_spec or {}).get("complexity"), "norm_days": num((norm_spec or {}).get("norm_days")),
            "new_count": len(nr), "new_amount": round(sum(r["amount"] for r in nr),2),
            "closed_count": len(cr), "closed_amount": round(sum(r["amount"] for r in cr),2),
            "period_closed_count": len(pr), "conversion_pct": pct(len(pr), len(nr)),
            "capacity_count": len(cap), "capacity_amount": round(sum(r["amount"] for r in cap),2),
            "returns_count": len(rr), "returns_amount": round(sum(r["amount"] for r in rr),2),
            "active_count": len(ar), **s,
        })
    products.sort(key=lambda x: (-x["closed_amount"], x["name"]))

    experts = []
    names = sorted({r["expert"] for r in new + closed + active + returns if r.get("expert")})
    for name in names:
        nr = [r for r in new if r["expert"] == name]
        cr = [r for r in closed if r["expert"] == name]
        ar = [r for r in active if r["expert"] == name]
        rr = [r for r in returns if r["expert"] == name]
        s = aggregate_prod_rows(cr)
        pmap = defaultdict(lambda: {"closed_count":0,"closed_amount":0.0,"days":[],"normed":0,"in_norm":0})
        for r in cr:
            x=pmap[r["service"]]; x["closed_count"]+=1; x["closed_amount"]+=r["amount"]
            if r.get("prod_days") is not None: x["days"].append(r["prod_days"])
            if r.get("norm_days"): x["normed"]+=1; x["in_norm"] += 1 if r.get("in_norm") else 0
        prod_breakdown=[]
        for p,x in pmap.items():
            prod_breakdown.append({"name":p,"closed_count":x["closed_count"],"closed_amount":round(x["closed_amount"],2),
                "avg_days":round(sum(x["days"])/len(x["days"]),1) if x["days"] else 0,
                "within_norm_pct":pct(x["in_norm"],x["normed"])})
        prod_breakdown.sort(key=lambda x:-x["closed_amount"])
        experts.append({
            "name": name, "new_count": len(nr), "active_count": len(ar), "returns_count": len(rr),
            **s, "products": prod_breakdown,
        })
    experts.sort(key=lambda x: (-x["closed_amount"], x["name"]))

    stages_acc = defaultdict(lambda:{"count":0,"amount":0.0})
    for r in active:
        x=stages_acc[r["stage"]]; x["count"]+=1; x["amount"]+=r["amount"]
    stages=[{"name":k,"count":v["count"],"amount":round(v["amount"],2)} for k,v in stages_acc.items()]
    stages.sort(key=lambda x:-x["amount"])

    reasons_acc=defaultdict(int)
    for r in dormant:
        for reason in r.get("stuck_reasons",[]): reasons_acc[reason]+=1
    reasons=[{"name":k,"count":v,"pct":pct(v,len(dormant))} for k,v in sorted(reasons_acc.items(),key=lambda kv:(-kv[1],kv[0]))]

    returns_acc=defaultdict(lambda:{"count":0,"amount":0.0})
    for r in returns:
        reason=r.get("return_reason") or "Не указана"
        x=returns_acc[str(reason)]; x["count"]+=1; x["amount"]+=r["amount"]
    return_reasons=[{"name":k,"count":v["count"],"amount":round(v["amount"],2),"pct":pct(v["count"],len(returns))} for k,v in sorted(returns_acc.items(),key=lambda kv:-kv[1]["count"])]

    buckets={"1–7 дней":0,"8–14 дней":0,"15–30 дней":0,"30+ дней":0}
    for r in overdue:
        x=parse_dt(r.get("expected_close"),tz)
        days=(now.date()-x.date()).days if x else 0
        if days<=7:buckets["1–7 дней"]+=1
        elif days<=14:buckets["8–14 дней"]+=1
        elif days<=30:buckets["15–30 дней"]+=1
        else:buckets["30+ дней"]+=1

    return {
        "period_label": period_label, "kpi": kpi, "products": products, "experts": experts, "stages": stages,
        "dormant": {"reasons": reasons, "with_reason_count": len(with_reason), "with_reason_pct": pct(len(with_reason),len(dormant))},
        "return_reasons": return_reasons,
        "overdue": {"count":len(overdue),"amount":round(sum(r["amount"] for r in overdue),2),"buckets":buckets},
        "_records": {"new":new,"closed":closed,"period_closed":period_closed,"active":active,"returns":returns,
                     "capacity":capacity,"dormant":dormant,"returned":returned,"overdue":overdue,
                     "dormant_expected":dormant_expected,"dormant_overdue":dormant_overdue,
                     "active_missing_expected":active_missing_expected,"active_missing_service":active_missing_service,
                     "active_missing_expert":active_missing_expert,"closed_without_act":closed_without_act},
    }


def month_pace(month_key: str, tz_name: str):
    start, end, _, _ = month_bounds(month_key,tz_name)
    tz=ZoneInfo(tz_name); now=datetime.now(tz)
    days=[]; d=start.date()
    while d<end.date():
        if d.weekday()<5:days.append(d)
        d+=timedelta(days=1)
    elapsed=[d for d in days if d<=min(now.date(),end.date()-timedelta(days=1))]
    return {"business_days_total":len(days),"business_days_elapsed":len(elapsed),"share":round(len(elapsed)/len(days),4) if days else 0}


async def build_snapshot(client, month_key: str, period: str, tz_name: str, custom_start: str = "", custom_end: str = ""):
    meta=await client.meta()
    sales_task=load_sales(client,month_key,meta,tz_name)
    prod_task=load_production(client,month_key,period,meta,tz_name,custom_start,custom_end)
    sales,production=await asyncio.gather(sales_task,prod_task)
    details={"sales":sales.pop("_records"),"production":production.pop("_records")}
    start,end,_,updated_at=month_bounds(month_key,tz_name)
    period_start,period_end,_=period_bounds(month_key,period,tz_name,custom_start,custom_end)
    return {
        "ok":True,"updated_at":updated_at,"month_key":month_key,"period":period,
        "month_start":start.isoformat(),"month_end":end.isoformat(),"period_start":period_start.isoformat(),"period_end":period_end.isoformat(),"pace":month_pace(month_key,tz_name),
        "sales":sales,"production":production,"_details":details,
        "available_users": sorted(set((meta.get("users") or {}).values())),
        "available_dormant_stages": sorted(set((meta.get("status_by_entity") or {}).get("DEAL_STAGE_30", {}).values())),
        "metric_status": {
            "upsells": {"connected": False, "note":"В Bitrix не найдено отдельное надежное поле «Допродажа» — требуется mapping."},
            "upsell_bonus": {"connected": False, "note":"Расчет премии за допродажи подключится после mapping поля допродажи."},
            "total_bonus": {"connected": False, "note":"Итоговая премия эксперта будет считаться после подключения допродаж; базовая премия уже считается по справочнику."},
            "expert_rework_pct": {"connected": False, "note":"В Bitrix нет отдельного признака «переделка по вине эксперта»."},
            "manual_nps": {"connected": True, "note":"NPS не рассчитывается из Bitrix: руководитель вводит его вручную по каждому эксперту."}
        }
    }


def filter_sales_details(details, metric, period_type="current", manager=None, group=None, source=None, product=None, week=None, stage=None):
    leads=details.get("leads",[]); deals=details.get("deals",[]); active=details.get("active",[])
    def common(r):
        if manager and r.get("manager")!=manager:return False
        if group and r.get("group")!=group:return False
        if source and r.get("source")!=source:return False
        return True
    if stage:
        rows=[r for r in active if common(r) and r.get("stage")==stage]
        return rows
    lead_rows=[r for r in leads if common(r) and (period_type!="previous" and r.get("period_type")=="current")]
    deal_rows=[r for r in deals if common(r) and (period_type=="total" or r.get("period_type")==period_type)]
    if product:
        deal_rows=[r for r in deal_rows if any(p.get("category")==product or p.get("name")==product for p in r.get("products",[]))]
    if metric in {"leads","qualified","qualified_rate","lead_to_deal_rate"}:
        rows=lead_rows if metric=="leads" else [r for r in lead_rows if r.get("is_qualified")]
        if week is not None: rows=[r for r in rows if r.get("week")==int(week)]
        return rows
    if metric in {"sales","sales_amount","average_check","sold_products","sold_product_amount","average_product_check","product_sale_rate","paid_amount","net_revenue"}:
        rows=[r for r in deal_rows if r.get("is_won") and r.get("sale_in_report_month")]
        if week is not None: rows=[r for r in rows if r.get("sale_week")==int(week)]
        return rows
    rows=deal_rows
    if week is not None: rows=[r for r in rows if r.get("creation_week")==int(week)]
    return rows


def filter_prod_details(details, metric, expert=None, product=None, stage=None, reason=None):
    metric_map={
        "closed_count":"closed","closed_amount":"closed","avg_check":"closed","avg_production_days":"closed","avg_deviation_days":"closed","within_norm_pct":"closed","nps_avg":"closed","act_share_pct":"closed",
        "new_count":"new","new_amount":"new","period_closed_count":"period_closed","period_closed_amount":"period_closed","new_to_success_pct":"period_closed",
        "capacity_count":"capacity","capacity_amount":"capacity","returns_count":"returns","returns_amount":"returns",
        "dormant_count":"dormant_expected","dormant_with_reason_pct":"dormant_expected","returned_to_production":"returned","overdue":"overdue",
        "dormant_expected_count":"dormant_expected","dormant_overdue_count":"dormant_overdue",
        "active_missing_expected_count":"active_missing_expected","active_missing_service_count":"active_missing_service",
        "active_missing_expert_count":"active_missing_expert","closed_without_act_count":"closed_without_act"
    }
    rows=list(details.get(metric_map.get(metric,"active"),[]))
    if expert: rows=[r for r in rows if r.get("expert")==expert]
    if product: rows=[r for r in rows if r.get("service")==product or r.get("category")==product]
    if stage: rows=[r for r in rows if r.get("stage")==stage]
    if reason:
        rows=[r for r in rows if reason in (r.get("stuck_reasons") or []) or r.get("return_reason")==reason]
    return rows


async def build_trends_light(client, end_month: str, months: int, tz_name: str):
    tz=ZoneInfo(tz_name)
    meta = await client.meta()
    success_stage_ids = successful_sale_stage_ids(meta)
    y,m=map(int,end_month.split('-'))
    keys=[]
    for i in range(months-1,-1,-1):
        yy=y; mm=m-i
        while mm<=0: yy-=1; mm+=12
        while mm>12: yy+=1; mm-=12
        keys.append(f"{yy:04d}-{mm:02d}")
    start=month_bounds(keys[0],tz_name)[0]
    end=month_bounds(keys[-1],tz_name)[1]
    sales_created_task=client.deal_list({"CATEGORY_ID":0,">=DATE_CREATE":iso(start),"<DATE_CREATE":iso(end)},DEAL_SELECT)
    async def _load_success():
        rows=[]
        for sid in success_stage_ids:
            rows.extend(await client.deal_list({"CATEGORY_ID":0,"STAGE_ID":sid,">=MOVED_TIME":iso(start),"<MOVED_TIME":iso(end)},DEAL_SELECT) or [])
        return list({str(d.get("ID")):d for d in rows}.values())
    sales_won_task=_load_success()
    leads_task=client.lead_list({">=DATE_CREATE":iso(start),"<DATE_CREATE":iso(end)},LEAD_SELECT)
    prod_new_task=client.deal_list({"CATEGORY_ID":PROD_CATEGORY,">=DATE_CREATE":iso(start),"<DATE_CREATE":iso(end)},DEAL_SELECT)
    prod_closed_task=client.deal_list({"CATEGORY_ID":PROD_CATEGORY,"STAGE_ID":PROD_WON,">=CLOSEDATE":iso(start),"<CLOSEDATE":iso(end)},DEAL_SELECT)
    prod_returns_task=client.deal_list({"CATEGORY_ID":PROD_CATEGORY,"STAGE_ID":PROD_RETURN,">=CLOSEDATE":iso(start),"<CLOSEDATE":iso(end)},DEAL_SELECT)
    sc,sw,leads,pn,pc,pr=await asyncio.gather(sales_created_task,sales_won_task,leads_task,prod_new_task,prod_closed_task,prod_returns_task)
    out={k:{"month":k,"deals":0,"sales":0,"sales_amount":0.0,"avg_check":0.0,"leads":0,"qualified":0,
            "prod_new":0,"prod_new_amount":0.0,"prod_closed":0,"prod_closed_amount":0.0,"prod_conversion":0.0,
            "avg_prod_days":0.0,"returns":0} for k in keys}
    def key_of(v):
        d=parse_dt(v,tz);return d.strftime('%Y-%m') if d else None
    for d in sc or []:
        k=key_of(d.get('DATE_CREATE')); 
        if k in out: out[k]['deals']+=1
    for d in sw or []:
        k=key_of(d.get('MOVED_TIME'))
        if k in out: out[k]['sales']+=1; out[k]['sales_amount']+=money(d)
    qneedle='качественный лид'
    for l in leads or []:
        k=key_of(l.get('DATE_CREATE'))
        if k in out:
            out[k]['leads']+=1
            if str(l.get('STATUS_ID') or '').upper()=='CONVERTED':out[k]['qualified']+=1
    for d in pn or []:
        k=key_of(d.get('DATE_CREATE'))
        if k in out: out[k]['prod_new']+=1; out[k]['prod_new_amount']+=money(d)
    days_by={k:[] for k in keys}; period_closed={k:0 for k in keys}
    for d in pc or []:
        k=key_of(d.get('CLOSEDATE'))
        if k in out:
            out[k]['prod_closed']+=1; out[k]['prod_closed_amount']+=money(d)
            s=parse_dt(d.get(F_PROD_START),tz); c=parse_dt(d.get('CLOSEDATE'),tz)
            bd=business_days(s,c)
            if bd is not None:days_by[k].append(bd)
            if key_of(d.get('DATE_CREATE'))==k:period_closed[k]+=1
    for d in pr or []:
        k=key_of(d.get('CLOSEDATE'))
        if k in out: out[k]['returns']+=1
    rows=[]
    for k in keys:
        x=out[k]
        x['sales_amount']=round(x['sales_amount'],2);x['prod_new_amount']=round(x['prod_new_amount'],2);x['prod_closed_amount']=round(x['prod_closed_amount'],2)
        x['avg_check']=round(x['sales_amount']/x['sales'],2) if x['sales'] else 0
        x['prod_conversion']=pct(period_closed[k],x['prod_new'])
        x['avg_prod_days']=round(sum(days_by[k])/len(days_by[k]),1) if days_by[k] else 0
        rows.append(x)
    return rows
