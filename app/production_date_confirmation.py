"""Opt-in, authenticated production stage transition and deadline history.

SAFETY: This does not and cannot intercept standard Bitrix24 kanban moves.
Use only for a controlled pilot; hard enforcement requires separate rights design.
"""
from __future__ import annotations

import asyncio
import os
from datetime import date, datetime, timezone
from typing import Any

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field

CATEGORY = '28'
FIELD = 'UF_CRM_1765875991647'
AUDIT_KEY = 'production_deadline_confirmations_v1'
_lock = asyncio.Lock()


class ConfirmTransition(BaseModel):
    deal_id: int = Field(gt=0)
    current_stage: str = Field(min_length=1, max_length=80)
    next_stage: str = Field(min_length=1, max_length=80)
    confirmed_date: date
    acknowledged: bool


def enabled() -> bool:
    return os.environ.get('PRODUCTION_DATE_CONFIRM_ENABLED', '') == '1'


def authorized_deal(deal: dict, user_id: str, is_director: bool) -> bool:
    return (str(deal.get('CATEGORY_ID') or '') == CATEGORY and
            (is_director or str(deal.get('ASSIGNED_BY_ID') or '') == str(user_id)))


def new_log_entry(deal: dict, identity: Any, date_value: str, target: str) -> dict:
    old = str(deal.get(FIELD) or '')[:10]
    return {
        'deal_id': str(deal['ID']), 'title': str(deal.get('TITLE') or ''),
        'user_id': str(identity.user_id),
        'old_date': old, 'new_date': date_value,
        'old_stage': str(deal.get('STAGE_ID') or ''), 'new_stage': target,
        'confirmed_at': datetime.now(timezone.utc).isoformat(),
        'date_changed': old != date_value,
    }


def register(app, client, storage, require_identity, require_full):
    async def fetch_deal(deal_id: int, identity):
        result = await client.call('crm.deal.get', {'id': deal_id})
        deal = result.get('result') or {}
        if not authorized_deal(deal, identity.user_id, identity.role == 'director'):
            raise HTTPException(403, 'Доступ разрешён только ответственному эксперту или руководителю')
        return deal

    async def stage_choices():
        response = await client.call('crm.status.list', {'filter': {'ENTITY_ID': 'DEAL_STAGE_28'}})
        stages = response.get('result') or []
        return [{'id': str(x.get('STATUS_ID') or ''), 'name': str(x.get('NAME') or '')}
                for x in stages if str(x.get('STATUS_ID') or '').startswith('C28:')]

    @app.get('/api/cabinet/production-date/deal')
    async def production_date_deal(request: Request, deal_id: int):
        identity = require_identity(request)
        deal = await fetch_deal(deal_id, identity)
        return {
            'deal_id': str(deal['ID']), 'title': str(deal.get('TITLE') or ''),
            'current_stage': str(deal.get('STAGE_ID') or ''),
            'date': str(deal.get(FIELD) or '')[:10],
            'stages': await stage_choices(), 'writes_enabled': enabled(),
        }

    @app.post('/api/cabinet/production-date/confirm')
    async def production_date_confirm(request: Request, body: ConfirmTransition):
        identity = require_identity(request)
        if not enabled():
            raise HTTPException(503, 'Пилотный режим записи отключён')
        if request.headers.get('content-type', '').split(';')[0].strip() != 'application/json':
            raise HTTPException(415, 'Ожидается JSON')
        if request.headers.get('x-mavis-action') != 'confirm-production-date':
            raise HTTPException(403, 'Подтвердите действие из приложения')
        if not body.acknowledged:
            raise HTTPException(400, 'Необходимо подтвердить проверку срока')
        async with _lock:
            deal = await fetch_deal(body.deal_id, identity)
            if str(deal.get('STAGE_ID')) != body.current_stage:
                raise HTTPException(409, 'Стадия уже изменилась. Обновите карточку и повторите проверку')
            choices = await stage_choices()
            if body.next_stage == body.current_stage or body.next_stage not in {s['id'] for s in choices}:
                raise HTTPException(400, 'Выберите другую стадию из воронки производства')
            # A single REST update changes both values, avoiding the date-empty interval.
            await client.call('crm.deal.update', {
                'id': body.deal_id,
                'fields': {FIELD: body.confirmed_date.isoformat(), 'STAGE_ID': body.next_stage},
            })
            entry = new_log_entry(deal, identity, body.confirmed_date.isoformat(), body.next_stage)
            # Pilot journal in the dashboard's existing durable storage; non-transactional
            # across multiple worker processes, so not a replacement for Bitrix event history.
            rows = storage.get_setting(AUDIT_KEY, [])
            if not isinstance(rows, list):
                rows = []
            try:
                storage.set_setting(AUDIT_KEY, ([entry] + rows)[:1000])
            except Exception:
                raise HTTPException(503, 'Стадия изменена, но журнал не сохранился. Сообщите руководителю') from None
            return {'ok': True, 'entry': entry}

    @app.get('/api/production-date/journal')
    async def production_date_journal(request: Request, limit: int = 100):
        require_full(request)
        rows = storage.get_setting(AUDIT_KEY, [])
        return {'rows': (rows if isinstance(rows, list) else [])[:max(1, min(500, limit))],
                'note': 'Только переходы через кнопку подтверждения. Обычные перемещения в Bitrix24 пока не отслеживаются.'}
