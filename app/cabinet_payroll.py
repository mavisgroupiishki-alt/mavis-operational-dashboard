"""MAVIS payroll: Bitrix24 successful deals as source and editable CRM reconciliation.
No CRM writes; closed sales are not proof of bank receipt. Estimates before taxes.
"""
from __future__ import annotations

import asyncio
import calendar
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, Request
from .metrics import F_SERVICE, F_DEAL_CLIENT_TYPE, money as crm_money, month_bounds, successful_sale_stage_ids, source_name
from pydantic import BaseModel, Field

_LOCK = asyncio.Lock()
RATES = [
    (150, 10.0, 8.0), (120, 8.5, 6.5), (110, 8.0, 6.0),
    (100, 6.0, 4.0), (90, 5.8, 3.8), (80, 5.2, 3.2), (0, 5.0, 3.0),
]
CATEGORIES = ('cold', 'warm', 'expert')
REASONS = ('unpaid', 'paid', 'vacation', 'sick', 'other')


def cash(value: Any) -> float:
    return float(Decimal(str(value or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))


def seed_profile(name: str) -> dict:
    name = name.casefold().replace('ё', 'е')
    if 'хурсик' in name or 'алена' in name or 'алёна' in name:
        return {'plan': 55000, 'base': 1500, 'rates_enabled': True, 'expert_rate': 2.0, 'adjustment': 0, 'workdays_override': None}
    if 'игор' in name or 'наст' in name:
        return {'plan': 25000, 'base': 0, 'rates_enabled': False, 'expert_rate': 2.0, 'adjustment': 0, 'workdays_override': None}
    return {'plan': 0, 'base': 0, 'rates_enabled': False, 'expert_rate': 2.0, 'adjustment': 0, 'workdays_override': None}


def settings_key(user_id: str, month: str) -> str:
    return f'cabinet_payroll_config_v1:{user_id}:{month}'


def ledger_key(user_id: str, month: str) -> str:
    return f'cabinet_payroll_ledger_v1:{user_id}:{month}'


def absence_key(user_id: str, month: str) -> str:
    return f'cabinet_payroll_absences_v1:{user_id}:{month}'


def valid_month(month: str):
    try:
        datetime.strptime(month, '%Y-%m')
    except (TypeError, ValueError):
        raise HTTPException(400, 'Месяц должен быть в формате YYYY-MM')


def workdays(month: str) -> int:
    y, m = map(int, month.split('-'))
    return sum(date(y, m, d).weekday() < 5 for d in range(1, calendar.monthrange(y, m)[1] + 1))


def rate_for(percent: float) -> tuple[float, float]:
    return next((cold, warm) for threshold, cold, warm in RATES if percent >= threshold)


def calculate(month: str, config: dict, payments: list, absences: list) -> dict:
    approved = [p for p in payments if p.get('approved')]
    cold = cash(sum(float(p['amount']) for p in approved if p.get('category') == 'cold'))
    warm = cash(sum(float(p['amount']) for p in approved if p.get('category') == 'warm'))
    expert = cash(sum(float(p['amount']) for p in approved if p.get('category') == 'expert'))
    gross_sales = cash(cold + warm + expert)
    plan = float(config.get('plan') or 0)
    pct = round(gross_sales / plan * 100, 2) if plan > 0 else None
    has_rates = bool(config.get('rates_enabled')) and pct is not None
    cold_rate, warm_rate = rate_for(pct or 0) if has_rates else (0.0, 0.0)
    cold_bonus = cash(cold * cold_rate / 100)
    warm_bonus = cash(warm * warm_rate / 100)
    expert_bonus = cash(expert * float(config.get('expert_rate') or 0) / 100) if has_rates else 0
    total_workdays = int(config.get('workdays_override') or workdays(month))
    unpaid_days = sum(float(a.get('days') or 0) for a in absences if not a.get('paid'))
    paid_days = max(0, total_workdays - unpaid_days)
    base = float(config.get('base') or 0)
    base_accrued = cash(base * paid_days / total_workdays) if total_workdays else 0
    adjustment = cash(config.get('adjustment') or 0)
    return {'plan': plan, 'plan_percent': pct, 'rates_enabled': has_rates,
        'cold_amount': cold, 'warm_amount': warm, 'expert_amount': expert,
        'gross_sales': gross_sales, 'cold_rate': cold_rate, 'warm_rate': warm_rate,
        'expert_rate': float(config.get('expert_rate') or 0),
        'cold_bonus': cold_bonus, 'warm_bonus': warm_bonus, 'expert_bonus': expert_bonus,
        'base': base, 'base_accrued': base_accrued, 'adjustment': adjustment,
        'workdays': total_workdays, 'unpaid_days': unpaid_days, 'paid_days': paid_days,
        'total': cash(base_accrued + cold_bonus + warm_bonus + expert_bonus + adjustment),
        'average_check': cash(gross_sales / len(approved)) if approved else 0,
        'payment_count': len(approved), 'pending_count': len(payments) - len(approved),
        'estimate_only': True}


class PaymentBody(BaseModel):
    month: str
    id: str | None = None
    paid_on: date
    deal_id: int = Field(gt=0)
    company: str = Field(min_length=1, max_length=180)
    product: str = Field(min_length=1, max_length=160)
    category: str
    amount: float = Field(gt=0, le=10_000_000)
    contractor_amount: float = Field(default=0, ge=0, le=10_000_000)
    approved: bool = False
    note: str = Field(default='', max_length=400)


class AbsenceBody(BaseModel):
    month: str
    id: str | None = None
    day: date
    days: float = Field(gt=0, le=31)
    reason: str
    paid: bool
    note: str = Field(default='', max_length=400)


class ConfigBody(BaseModel):
    month: str
    plan: float = Field(ge=0, le=10_000_000)
    base: float = Field(ge=0, le=1_000_000)
    rates_enabled: bool
    expert_rate: float = Field(ge=0, le=100)
    adjustment: float = Field(ge=-1_000_000, le=1_000_000)
    workdays_override: int | None = Field(default=None, ge=1, le=31)


def register(app, storage, identity_provider, subject_provider, roster_provider, timezone_name: str, client):
    async def subject(request, month):
        valid_month(month)
        identity, user_id = await subject_provider(request)
        name = f'Сотрудник {user_id}'
        if identity.role == 'director':
            roster = await roster_provider()
            name = next((row['name'] for row in roster if str(row.get('id')) == str(user_id)), name)
        else:
            # The employee's display name is resolved by caller's own live user metadata where possible.
            try:
                roster = await roster_provider()
                name = next((row['name'] for row in roster if str(row.get('id')) == str(user_id)), name)
            except Exception:
                pass
        return identity, str(user_id), name

    async def context(request, month):
        identity, user_id, name = await subject(request, month)
        key = settings_key(user_id, month)
        existing = storage.get_setting(key, None)
        default = seed_profile(name)
        cfg = {**default, **(existing if isinstance(existing, dict) else {})}
        payments = storage.get_setting(ledger_key(user_id, month), [])
        absences = storage.get_setting(absence_key(user_id, month), [])
        return identity, user_id, name, cfg, payments if isinstance(payments, list) else [], absences if isinstance(absences, list) else []

    @app.get('/api/cabinet/payroll')
    async def get_payroll(request: Request, month: str):
        _, user_id, name, config, payments, absences = await context(request, month)
        return {'ok': True, 'user_id': user_id, 'name': name, 'month': month,
                'config': config, 'payments': payments, 'absences': absences,
                'summary': calculate(month, config, payments, absences), 'tiers': RATES,
                'notice': 'Предварительный расчёт до налогов и обязательных удержаний. Не заменяет бухгалтерский расчёт.'}

    async def crm_closed_sales(user_id: str, month: str) -> list[dict]:
        """Read successful sales deals belonging to the selected manager.

        CLOSEDATE is the CRM sales closing date, NOT a verified bank payment date.
        """
        start, end, _, _ = month_bounds(month, timezone_name)
        meta = await client.meta()
        won_stages = successful_sale_stage_ids(meta)
        select = ['ID', 'TITLE', 'COMPANY_ID', 'CATEGORY_ID', 'STAGE_ID', 'ASSIGNED_BY_ID',
                  'CLOSEDATE', 'OPPORTUNITY', 'CURRENCY_ID', 'SOURCE_ID', 'SOURCE_DESCRIPTION',
                  F_SERVICE, F_DEAL_CLIENT_TYPE]
        deals = await client.deal_list({'CATEGORY_ID': 0, 'ASSIGNED_BY_ID': user_id,
                         '>=CLOSEDATE': start.isoformat(), '<CLOSEDATE': end.isoformat()}, select)
        deals = [row for row in deals or [] if str(row.get('STAGE_ID') or '') in won_stages]
        # Product names are sourced from real CRM product rows, not guessed from the deal title.
        try:
            product_map = await client.product_rows_many(deals)
        except Exception:
            product_map = {}
        result = []
        for row in deals:
            deal_id = str(row.get('ID') or '')
            if not deal_id.isdigit():
                continue
            source = str(source_name(meta, row) or row.get('SOURCE_ID') or '')
            product_rows = product_map.get(deal_id) or []
            products = list(dict.fromkeys(str(r.get('PRODUCT_NAME') or r.get('productName') or r.get('NAME') or '').strip() for r in product_rows))
            products = [name for name in products if name]
            service = ', '.join(products) if products else str(row.get(F_SERVICE) or 'Не определено')
            result.append({'id': 'crm:' + deal_id, 'deal_id': int(deal_id),
                'company': str(row.get('TITLE') or 'Сделка №' + deal_id)[:180],
                'product': service[:160], 'products': products, 'amount': cash(crm_money(row)),
                'contractor_amount': 0.0,
                'paid_on': str(row.get('CLOSEDATE') or '')[:10],
                'source': 'bitrix', 'source_label': source,
                'category': 'cold' if any(token in source.casefold() for token in ('холод', 'cold')) else 'warm',
                'category_needs_review': True,
                'approved': False,
                'note': 'Из закрытой успешной сделки Bitrix24. Дата = CLOSEDATE, не подтверждение банковской оплаты.'})
        return result

    @app.post('/api/cabinet/payroll/bitrix-compare')
    async def compare_with_bitrix(request: Request, month: str):
        """Read-only comparison. Does not change report or paid/approved flags."""
        _, user_id, _ = await subject(request, month)
        crm = await crm_closed_sales(user_id, month)
        ledger = storage.get_setting(ledger_key(user_id, month), [])
        ledger = ledger if isinstance(ledger, list) else []
        by_deal = {str(x.get('deal_id')): x for x in ledger if x.get('deal_id')}
        crm_ids = {str(x['deal_id']) for x in crm}
        differences = []
        for x in crm:
            existing = by_deal.get(str(x['deal_id']))
            if not existing:
                differences.append({'type':'missing', 'deal_id':x['deal_id'], 'crm':x})
            elif abs(float(existing.get('amount') or 0)-float(x['amount']))>0.009:
                differences.append({'type':'amount', 'deal_id':x['deal_id'],
                                    'crm':x, 'report':existing})
        for x in ledger:
            if x.get('deal_id') and str(x['deal_id']) not in crm_ids:
                differences.append({'type':'report_only','deal_id':x['deal_id'],'report':x})
        return {'ok':True, 'month':month, 'rows':crm, 'differences':differences,
                'crm_count':len(crm), 'crm_amount':cash(sum(x['amount'] for x in crm)),
                'report_count':len(ledger),
                'note':'Сравнение закрытых успешных сделок Bitrix24. CRM CLOSEDATE и OPPORTUNITY не являются банковской выпиской. Совпадения по ID сделки; при нескольких оплатах по одной сделке нужна отдельная сверка.'}

    @app.post('/api/cabinet/payroll/bitrix-sync')
    async def sync_from_bitrix(request: Request, month: str):
        """Add missing CRM sales to personal report without overwriting edits."""
        _, user_id, _ = await subject(request, month)
        crm = await crm_closed_sales(user_id, month)
        key = ledger_key(user_id, month)
        async with _LOCK:
            ledger = storage.get_setting(key, [])
            ledger = ledger if isinstance(ledger, list) else []
            existing_ids = {str(x.get('deal_id')) for x in ledger}
            fresh = [x for x in crm if str(x['deal_id']) not in existing_ids]
            if len(ledger)+len(fresh)>2000:
                raise HTTPException(400, 'Слишком много строк, требуется постраничная загрузка')
            storage.set_setting(key, ledger + fresh)
        return {'ok':True,'added':len(fresh),'crm_count':len(crm),
                'note':'Добавлены только отсутствующие сделки. Исправления в личном отчёте не перезаписаны; подтверждения банковской оплаты не выставлены.'}

    @app.put('/api/cabinet/payroll/config')
    async def set_config(request: Request, body: ConfigBody):
        identity, user_id, _ = await subject(request, body.month)
        if identity.role != 'director':
            raise HTTPException(403, 'Изменять оклад, план и ставки может только руководитель')
        storage.set_setting(settings_key(user_id, body.month), body.model_dump(exclude={'month'}))
        return {'ok': True}

    @app.post('/api/cabinet/payroll/payment')
    async def save_payment(request: Request, body: PaymentBody):
        identity, user_id, _ = await subject(request, body.month)
        if body.category not in CATEGORIES or body.paid_on.strftime('%Y-%m') != body.month:
            raise HTTPException(400, 'Проверьте месяц оплаты и категорию')
        if body.contractor_amount > body.amount:
            raise HTTPException(400, 'Сумма подрядчика превышает платёж')
        async with _LOCK:
            key = ledger_key(user_id, body.month)
            rows = storage.get_setting(key, [])
            rows = rows if isinstance(rows, list) else []
            record = body.model_dump(mode='json', exclude={'month'})
            record['id'] = body.id or uuid4().hex
            # Manager can enter a payment but only a director can approve it for commission.
            if identity.role != 'director':
                record['approved'] = False
            record['source'] = str((next((x for x in rows if x.get('id') == record['id']), None) or {}).get('source') or 'manual')
            record['updated_by'] = str(identity.user_id)
            record['updated_at'] = datetime.now(timezone.utc).isoformat()
            found = next((i for i, r in enumerate(rows) if r.get('id') == record['id']), None)
            if found is not None:
                previous = rows[found]
                if identity.role != 'director' and previous.get('approved'):
                    raise HTTPException(403, 'Подтверждённую оплату может менять только руководитель')
                rows[found] = record
            else:
                rows.append(record)
            if len(rows) > 2000:
                raise HTTPException(400, 'Достигнут лимит записей месяца')
            storage.set_setting(key, rows)
        return {'ok': True, 'id': record['id']}

    @app.delete('/api/cabinet/payroll/payment/{payment_id}')
    async def delete_payment(request: Request, payment_id: str, month: str):
        identity, user_id, _ = await subject(request, month)
        key = ledger_key(user_id, month)
        async with _LOCK:
            rows = storage.get_setting(key, [])
            rows = rows if isinstance(rows, list) else []
            match = next((r for r in rows if r.get('id') == payment_id), None)
            if not match:
                raise HTTPException(404, 'Оплата не найдена')
            if identity.role != 'director':
                raise HTTPException(403, 'Удаление оплат доступно только руководителю')
            storage.set_setting(key, [r for r in rows if r.get('id') != payment_id])
        return {'ok': True}

    @app.post('/api/cabinet/payroll/absence')
    async def save_absence(request: Request, body: AbsenceBody):
        identity, user_id, _ = await subject(request, body.month)
        if identity.role != 'director':
            raise HTTPException(403, 'Отсутствия и их оплату фиксирует руководитель')
        if body.reason not in REASONS or body.day.strftime('%Y-%m') != body.month:
            raise HTTPException(400, 'Проверьте дату и причину отсутствия')
        async with _LOCK:
            key = absence_key(user_id, body.month)
            rows = storage.get_setting(key, [])
            rows = rows if isinstance(rows, list) else []
            row = body.model_dump(mode='json', exclude={'month'})
            row['id'] = body.id or uuid4().hex
            pos = next((i for i, x in enumerate(rows) if x.get('id') == row['id']), None)
            if pos is not None: rows[pos] = row
            else: rows.append(row)
            storage.set_setting(key, rows)
        return {'ok': True}

    @app.delete('/api/cabinet/payroll/absence/{absence_id}')
    async def delete_absence(request: Request, absence_id: str, month: str):
        identity, user_id, _ = await subject(request, month)
        if identity.role != 'director':
            raise HTTPException(403, 'Только руководитель')
        key = absence_key(user_id, month)
        rows = storage.get_setting(key, [])
        storage.set_setting(key, [r for r in (rows if isinstance(rows, list) else []) if r.get('id') != absence_id])
        return {'ok': True}
