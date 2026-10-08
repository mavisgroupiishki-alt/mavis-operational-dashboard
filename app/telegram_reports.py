"""Server-side rendering and delivery of source-backed daily Telegram reports."""

from __future__ import annotations

import math
import re
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from .sales_team import SALES_BI_MANAGERS

RUSSIAN_WEEKDAYS = ("Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье")
RUSSIAN_MONTHS_GENITIVE = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)
DASHBOARD_FINANCE_WAIT_MS = 100_000
DASHBOARD_FINANCE_POLL_MS = 500


class ReportDeliveryError(RuntimeError):
    """A safe, user-facing report delivery failure."""


@dataclass(frozen=True)
class DailyReportTexts:
    sales: str
    experts: str


def _finite_number(value: object, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ReportDeliveryError(f"Нет корректного значения: {field}") from exc
    if not math.isfinite(number):
        raise ReportDeliveryError(f"Нет корректного значения: {field}")
    return number


def _format_byn(value: object) -> str:
    amount = _finite_number(value, "сумма")
    rendered = f"{amount:,.0f}".replace(",", " ")
    return f"{rendered} BYN"


def _format_count(value: object) -> str:
    return f"{_finite_number(value, 'количество'):,.0f}".replace(",", " ")


def russian_date(value: datetime) -> str:
    return f"{RUSSIAN_WEEKDAYS[value.weekday()]}, {value.day} {RUSSIAN_MONTHS_GENITIVE[value.month - 1]} {value.year}"


def _clean_sales_amount(snapshot: dict) -> float:
    """Return month-to-date net revenue for the plan/fact line."""
    finance = snapshot.get("clean_revenue") or {}
    if finance.get("status") in {"online", "stale"} and finance.get("value") is not None:
        return _finite_number(finance["value"], "чистая выручка")
    raise ReportDeliveryError("Чистая выручка из «Графика платежей» недоступна")


def _daily_sales_amount(snapshot: dict) -> float:
    """Return net revenue only for the report date, never the whole month."""
    finance = ((snapshot.get("daily_sales") or {}).get("clean_revenue") or {})
    if finance.get("status") in {"online", "stale"} and finance.get("value") is not None:
        return _finite_number(finance["value"], "дневная чистая выручка")
    raise ReportDeliveryError("Чистая выручка за день из «Графика платежей» недоступна")


def _plan_or_dash(snapshot: dict, key: str) -> str:
    value = (snapshot.get("plans") or {}).get(key, {}).get("sales_amount")
    if value is None:
        return "—"
    return _format_byn(value)


def _daily_production_totals(production: dict, generated_at: datetime) -> tuple[float, float]:
    """Return production closures for the report day, not the month-to-date KPI."""
    days = ((production.get("weekly") or {}).get("days") or {})
    index = generated_at.day - 1
    try:
        count = days["closed_count"][index]
        amount = days["closed_amount"][index]
    except (IndexError, KeyError, TypeError) as exc:
        raise ReportDeliveryError("Нет дневных данных закрытий экспертов") from exc
    return (
        _finite_number(count, "дневное количество закрытых продуктов"),
        _finite_number(amount, "дневная сумма закрытых актов"),
    )


def build_daily_report_texts(snapshot: dict, generated_at: datetime) -> DailyReportTexts:
    """Return the agreed manager-style text without inventing missing plans."""
    month_name = RUSSIAN_MONTHS_GENITIVE[generated_at.month - 1]
    production = snapshot.get("production") or {}
    kpi = production.get("kpi") or {}
    date = russian_date(generated_at)
    daily_sales_amount = _daily_sales_amount(snapshot)
    month_sales_amount = _clean_sales_amount(snapshot)
    sales_plan = _plan_or_dash(snapshot, "sales|overall|")
    daily_closed_count, daily_closed_amount = _daily_production_totals(production, generated_at)
    month_closed_amount = _format_byn(kpi.get("closed_amount", 0))
    closed_count = _format_count(daily_closed_count)
    closed_amount = _format_byn(daily_closed_amount)

    return DailyReportTexts(
        sales=(
            f"{date}\n\n"
            f"💰 Сумма продаж - {_format_byn(daily_sales_amount)}\n\n"
            f"📈 Факт плана продаж {month_name} - {_format_byn(month_sales_amount)} / {sales_plan}"
        ),
        experts=(
            f"{date} 🍂\n\n"
            f"✅ Количество закрытых продуктов - {closed_count} шт\n"
            f"💰 Сумма закрытых актов - {closed_amount}\n\n"
            f"✔ Факт отдела {month_name} - {month_closed_amount}"
        ),
    )


def _report_configuration(login: str, password: str, report_url: str) -> None:
    if not login or not password:
        raise ReportDeliveryError("Не заданы BITRIX_BI_LOGIN или BITRIX_BI_PASSWORD")
    if not report_url.startswith("https://"):
        raise ReportDeliveryError("Адрес BI-отчёта должен быть HTTPS")


def _safe_page_location(url: str) -> str:
    """Return diagnostic page location without OAuth query parameters."""
    parsed = urlsplit(url)
    return f"{parsed.netloc}{parsed.path}" if parsed.netloc else "неизвестная страница"


def _dashboard_financial_values_ready(values: list[str]) -> bool:
    """Return true only when all three dashboard finance cards show money.

    The page initially renders the same three cards with the ``Считаю…``
    placeholder. Presence of the elements alone must never permit a report
    screenshot, otherwise a valid-looking but financially empty report is
    sent.
    """
    if len(values) != 3:
        return False
    return all("BYN" in value.upper() and bool(re.search(r"\d", value)) for value in values)


def _financial_texts_match(rendered: tuple[str, ...], expected: tuple[str, ...]) -> bool:
    """Compare monetary strings despite browser non-breaking separators."""
    normalize = lambda value: re.sub(r"[\s\u00a0\u202f]+", " ", value).strip()
    return len(rendered) == len(expected) and all(
        normalize(actual) == normalize(wanted)
        for actual, wanted in zip(rendered, expected, strict=True)
    )


def dashboard_finance_display_values(finance: dict) -> tuple[str, str, str]:
    """Format the finance API result used for the two server-side images."""
    daily = finance.get("clean_revenue") or {}
    month = finance.get("month_clean_revenue") or {}
    if daily.get("status") not in {"online", "stale"}:
        raise ReportDeliveryError("Чистая выручка за день из «Графика платежей» недоступна")
    if month.get("status") not in {"online", "stale"}:
        raise ReportDeliveryError("Факт плана из «Графика платежей» недоступен")
    return (
        _format_byn(daily.get("incoming_amount")),
        _format_byn(daily.get("value")),
        f"{_format_byn(month.get('value'))} / {_format_byn(finance.get('sales_plan_amount'))}",
    )


def _daily_report_font(size: int, *, bold: bool = False):
    """Load a Cyrillic font installed in both Render and local test hosts."""
    from PIL import ImageFont

    filenames = (
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf")
        if bold else
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/System/Library/Fonts/Supplemental/Arial Unicode.ttf")
    )
    for filename in filenames:
        try:
            return ImageFont.truetype(filename, size=size)
        except OSError:
            continue
    raise ReportDeliveryError("В Render не найден шрифт для изображения ежедневного отчёта")


def _daily_report_row_value(value: object) -> str:
    """Keep integer report metrics compact while preserving decimal minutes."""
    number = _finite_number(value, "значение отчёта")
    if number.is_integer():
        return f"{number:,.0f}".replace(",", " ")
    return f"{number:,.1f}".replace(",", " ").replace(".", ",")


def _daily_report_text(value: object, max_chars: int = 42) -> str:
    text = str(value or "—").strip()
    return text if len(text) <= max_chars else f"{text[:max_chars - 1]}…"


def _daily_report_table(draw, *, x: int, y: int, width: int, title: str,
                        headers: tuple[str, ...], rows: list[tuple[str, ...]]) -> int:
    """Draw one compact, readable dashboard table and return its bottom edge."""
    from PIL import ImageDraw

    body_rows = rows or [("Нет данных",) + tuple("—" for _ in headers[1:])]
    row_height = 48
    title_height = 48
    header_height = 40
    height = title_height + header_height + row_height * len(body_rows) + 24
    radius = 24
    draw.rounded_rectangle((x, y, x + width, y + height), radius=radius,
                           fill="#ffffff", outline="#d4e3ed", width=2)
    title_font = _daily_report_font(22, bold=True)
    head_font = _daily_report_font(15, bold=True)
    body_font = _daily_report_font(17, bold=False)
    draw.text((x + 26, y + 16), title, font=title_font, fill="#183b56")
    table_y = y + title_height
    draw.rounded_rectangle((x + 20, table_y, x + width - 20, table_y + header_height), radius=8,
                           fill="#edf5fa")
    columns = len(headers)
    first_width = int((width - 40) * (0.54 if columns > 1 else 1))
    other_width = ((width - 40 - first_width) // max(1, columns - 1)) if columns > 1 else 0
    for index, header in enumerate(headers):
        cell_x = x + 28 if index == 0 else x + 20 + first_width + other_width * (index - 1) + 12
        draw.text((cell_x, table_y + 11), header.upper(), font=head_font, fill="#6e879a")
    for row_index, row in enumerate(body_rows):
        row_y = table_y + header_height + row_height * row_index
        if row_index % 2:
            draw.rectangle((x + 20, row_y, x + width - 20, row_y + row_height), fill="#f8fbfd")
        draw.line((x + 20, row_y + row_height, x + width - 20, row_y + row_height), fill="#e5eef4", width=1)
        for col, value in enumerate(row):
            if col == 0:
                cell_x = x + 28
                rendered = _daily_report_text(value, 43 if columns == 2 else 27)
            else:
                cell_x = x + 20 + first_width + other_width * (col - 1) + 12
                rendered = _daily_report_text(value, 16)
            draw.text((cell_x, row_y + 13), rendered, font=body_font, fill="#25394a")
    return y + height


def _daily_report_card(draw, *, x: int, y: int, width: int, label: str, value: str) -> None:
    draw.rounded_rectangle((x, y, x + width, y + 132), radius=22,
                           fill="#ffffff", outline="#d4e3ed", width=2)
    draw.text((x + 24, y + 22), label, font=_daily_report_font(16, bold=True), fill="#7690a3")
    draw.text((x + 24, y + 62), value, font=_daily_report_font(29, bold=True), fill="#17435f")


def render_dashboard_daily_reports(
    *, report_date: str, report: dict, finance: dict,
    leads_output_path: Path, calls_output_path: Path,
) -> tuple[Path, Path]:
    """Create the two daily report images without launching Chromium on Render.

    The payload is the same direct Bitrix24 and payment-ledger data used by the
    dashboard. Rendering it locally avoids a browser process being killed by
    Render before the upload is complete.
    """
    from PIL import Image, ImageDraw

    try:
        report_day = datetime.fromisoformat(report_date)
    except ValueError as exc:
        raise ReportDeliveryError("Дата снимка дашборда задана неверно") from exc
    finance_values = dashboard_finance_display_values(finance)
    leads_output_path.parent.mkdir(parents=True, exist_ok=True)
    calls_output_path.parent.mkdir(parents=True, exist_ok=True)

    background = "#f2f8fb"
    width = 1800
    margin = 36
    gutter = 28
    column_width = (width - margin * 2 - gutter) // 2
    lead_data = report.get("leads") or {}
    deal_data = report.get("deals") or {}
    call_data = report.get("calls") or {}

    lead_source_rows = [(_daily_report_text(row.get("name")), _daily_report_row_value(row.get("count", 0)))
                        for row in (lead_data.get("by_source") or [])]
    lead_manager_rows = [
        (_daily_report_text(row.get("name")), _daily_report_row_value(row.get("count", 0)),
         _daily_report_text(" · ".join(
             f"{source.get('name')} · {_daily_report_row_value(source.get('count', 0))}"
             for source in (row.get("sources") or [])
         ), 30))
        for row in (lead_data.get("by_manager_source") or [])
    ]
    deal_source_rows = [(_daily_report_text(row.get("name")), _daily_report_row_value(row.get("count", 0)))
                        for row in (deal_data.get("by_source") or [])]
    deal_stage_rows = [(_daily_report_text(row.get("name")), _daily_report_row_value(row.get("count", 0)))
                       for row in (deal_data.get("by_stage") or [])]
    deal_stage_source_rows = [
        (_daily_report_text(row.get("name")), _daily_report_row_value(row.get("count", 0)),
         _daily_report_text(" · ".join(
             f"{source.get('name')} · {_daily_report_row_value(source.get('count', 0))}"
             for source in (row.get("sources") or [])
         ), 30))
        for row in (deal_data.get("by_stage_source") or [])
    ]
    deal_manager_rows = [
        (_daily_report_text(row.get("name")), _daily_report_row_value(row.get("count", 0)),
         _daily_report_text(" · ".join(
             f"{client_type.get('name')} · {_daily_report_row_value(client_type.get('count', 0))}"
             for client_type in (row.get("client_types") or [])
         ), 30))
        for row in (deal_data.get("by_manager_client_type") or [])
    ]

    top_left_rows = lead_source_rows[:7]
    top_right_rows = lead_manager_rows[:7]
    lower_left_rows = deal_source_rows[:7]
    lower_right_rows = deal_stage_rows[:7]
    final_left_rows = deal_stage_source_rows[:7]
    final_right_rows = deal_manager_rows[:7]
    leads_height = (
        480
        + max(len(top_left_rows), len(top_right_rows)) * 48
        + max(len(lower_left_rows), len(lower_right_rows)) * 48
        + max(len(final_left_rows), len(final_right_rows)) * 48
    )
    leads_image = Image.new("RGB", (width, max(1420, leads_height)), background)
    leads_draw = ImageDraw.Draw(leads_image)
    leads_draw.rounded_rectangle((margin, 28, width - margin, 188), radius=28, fill="#ffffff", outline="#c9e0ee", width=2)
    leads_draw.text((margin + 28, 54), "Отдел продаж · Bitrix24", font=_daily_report_font(16, bold=True), fill="#68869b")
    leads_draw.text((margin + 28, 87), "Ежедневный отчёт", font=_daily_report_font(38, bold=True), fill="#163c59")
    leads_draw.text((margin + 28, 142), russian_date(report_day), font=_daily_report_font(19), fill="#668298")
    cards_y = 222
    card_width = (width - margin * 2 - gutter * 2) // 3
    _daily_report_card(leads_draw, x=margin, y=cards_y, width=card_width, label="Поступления за день", value=finance_values[0])
    _daily_report_card(leads_draw, x=margin + card_width + gutter, y=cards_y, width=card_width, label="Чистая выручка за день", value=finance_values[1])
    _daily_report_card(leads_draw, x=margin + (card_width + gutter) * 2, y=cards_y, width=card_width, label="Факт плана октября", value=finance_values[2])
    summary_y = cards_y + 164
    _daily_report_card(leads_draw, x=margin, y=summary_y, width=column_width, label="Лиды", value=_daily_report_row_value(lead_data.get("total", 0)))
    _daily_report_card(leads_draw, x=margin + column_width + gutter, y=summary_y, width=column_width, label="Созданные сделки", value=_daily_report_row_value(deal_data.get("total", 0)))
    tables_y = summary_y + 164
    left_bottom = _daily_report_table(leads_draw, x=margin, y=tables_y, width=column_width,
                                      title="Лиды по источникам", headers=("Источник", "Лиды"), rows=top_left_rows)
    right_bottom = _daily_report_table(leads_draw, x=margin + column_width + gutter, y=tables_y, width=column_width,
                                       title="Лиды по менеджерам", headers=("Менеджер", "Лиды", "Источники"), rows=top_right_rows)
    tables_y = max(left_bottom, right_bottom) + 28
    left_bottom = _daily_report_table(leads_draw, x=margin, y=tables_y, width=column_width,
                                      title="Созданные сделки по источникам", headers=("Источник", "Сделки"), rows=lower_left_rows)
    right_bottom = _daily_report_table(leads_draw, x=margin + column_width + gutter, y=tables_y, width=column_width,
                                       title="Созданные сделки по стадиям", headers=("Стадия", "Сделки"), rows=lower_right_rows)
    tables_y = max(left_bottom, right_bottom) + 28
    _daily_report_table(leads_draw, x=margin, y=tables_y, width=column_width,
                        title="Стадии и источники", headers=("Стадия", "Сделки", "Источники"), rows=final_left_rows)
    _daily_report_table(leads_draw, x=margin + column_width + gutter, y=tables_y, width=column_width,
                        title="Сделки по менеджерам и типу клиента", headers=("Менеджер", "Сделки", "Тип клиента"), rows=final_right_rows)
    leads_image.save(leads_output_path, format="PNG", optimize=True)

    call_rows = call_data.get("by_manager") or []
    call_count_rows = [
        (_daily_report_text(row.get("name")), _daily_report_row_value(row.get("incoming_count", 0)),
         _daily_report_row_value(row.get("outgoing_count", 0)))
        for row in call_rows
    ]
    call_duration_rows = [
        (_daily_report_text(row.get("name")), _daily_report_row_value(row.get("incoming_minutes", 0)),
         _daily_report_row_value(row.get("outgoing_minutes", 0)))
        for row in call_rows
    ]
    calls_height = max(720, 400 + len(call_rows) * 48)
    calls_image = Image.new("RGB", (width, calls_height), background)
    calls_draw = ImageDraw.Draw(calls_image)
    calls_draw.rounded_rectangle((margin, 28, width - margin, 188), radius=28, fill="#ffffff", outline="#c9e0ee", width=2)
    calls_draw.text((margin + 28, 54), "Отдел продаж · Bitrix24", font=_daily_report_font(16, bold=True), fill="#68869b")
    calls_draw.text((margin + 28, 87), "Ежедневный отчёт по звонкам", font=_daily_report_font(38, bold=True), fill="#163c59")
    calls_draw.text((margin + 28, 142), russian_date(report_day), font=_daily_report_font(19), fill="#668298")
    calls_card_y = 222
    _daily_report_card(calls_draw, x=margin, y=calls_card_y, width=card_width, label="Звонки", value=_daily_report_row_value(call_data.get("total", 0)))
    _daily_report_card(calls_draw, x=margin + card_width + gutter, y=calls_card_y, width=card_width,
                       label="Не классифицировано", value=_daily_report_row_value(call_data.get("unclassified_count", 0)))
    _daily_report_card(calls_draw, x=margin + (card_width + gutter) * 2, y=calls_card_y, width=card_width,
                       label="Без длительности", value=_daily_report_row_value(call_data.get("without_duration_count", 0)))
    table_y = calls_card_y + 164
    _daily_report_table(calls_draw, x=margin, y=table_y, width=column_width,
                        title="Количество звонков по менеджерам", headers=("Менеджер", "Входящие", "Исходящие"), rows=call_count_rows)
    _daily_report_table(calls_draw, x=margin + column_width + gutter, y=table_y, width=column_width,
                        title="Длительность звонков по менеджерам", headers=("Менеджер", "Входящие, мин", "Исходящие, мин"), rows=call_duration_rows)
    calls_image.save(calls_output_path, format="PNG", optimize=True)
    return leads_output_path, calls_output_path


async def _bitrix_auth_blocker(page: object) -> str:
    """Describe a post-submit Bitrix auth screen without reading user data."""
    one_time_code = page.locator(
        "input[autocomplete='one-time-code'], input[name*='code' i], input[id*='code' i]"
    )
    if await one_time_code.count():
        return "Bitrix24 требует одноразовый код подтверждения"
    password_input = page.locator("input[type='password']:visible")
    if await password_input.count():
        return "Bitrix24 не принял пароль: проверьте BITRIX_BI_PASSWORD"
    return "Bitrix24 не завершил авторизацию"


async def _wait_for_bi_report_ready(
    frame: object, *, timeout_ms: int = 60_000, poll_ms: int = 500, stable_ms: int = 2_000
) -> None:
    """Wait until BI Builder has finished preparing the visible report data."""
    loading = frame.get_by_text("Готовим данные отчёта", exact=True)

    async def loading_is_visible() -> bool:
        for index in range(await loading.count()):
            if await loading.nth(index).is_visible():
                return True
        return False

    loading_seen = False
    attempts = max(1, timeout_ms // poll_ms)
    for attempt in range(attempts):
        visible = await loading_is_visible()
        loading_seen = loading_seen or visible
        # Filter changes start asynchronous BI requests after the browser has
        # accepted the click.  In production that loader can first appear
        # later than the old five-second grace period, producing a screenshot
        # with “Готовим данные отчёта”.  Keep observing for twelve seconds
        # before accepting an initially quiet report.
        if not visible and (loading_seen or attempt >= 24):
            # BI Builder replaces several widgets independently.  Require one
            # additional quiet moment so a late widget cannot produce a blank
            # screenshot after the first loader has disappeared.
            await frame.wait_for_timeout(stable_ms)
            stable = not await loading_is_visible()
            if stable:
                return
        await frame.wait_for_timeout(poll_ms)
    raise ReportDeliveryError("BI-конструктор не завершил подготовку данных отчёта")


async def _last_visible(locator: object) -> object | None:
    """Return the last visible element from a Playwright locator collection."""
    for index in range(await locator.count() - 1, -1, -1):
        candidate = locator.nth(index)
        if await candidate.is_visible():
            return candidate
    return None


async def _apply_sales_manager_filter(frame: object) -> None:
    """Set the BI employee filter to the current sales department only."""
    # BI Builder keeps a user click on a chart as a cross-filter.  It is not
    # part of the scheduled report and can leave every widget empty, so clear
    # all transient filters before setting the explicit department selection.
    reset_button = await _last_visible(frame.get_by_text("Сбросить", exact=True))
    if reset_button is not None and await reset_button.is_enabled():
        await reset_button.click(timeout=10_000, force=True)
        await frame.wait_for_timeout(500)
    employee_label = None
    for _ in range(60):
        employee_label = await _last_visible(frame.get_by_text(re.compile(r"Сотрудник", re.IGNORECASE)))
        if employee_label is not None:
            break
        await frame.wait_for_timeout(500)
    if employee_label is None:
        raise ReportDeliveryError("Не найден фильтр «Сотрудник» в BI-конструкторе")
    control = None
    for candidate in (
        employee_label.locator("xpath=following-sibling::*[1]"),
        employee_label.locator("xpath=../following-sibling::*[1]"),
        employee_label.locator("xpath=..").locator("input, button, [role='combobox']"),
        frame.get_by_text(re.compile(r"^\d+\s+вариант", re.IGNORECASE)),
    ):
        control = await _last_visible(candidate)
        if control is not None:
            break
    if control is None:
        raise ReportDeliveryError("Не найден фильтр «Сотрудник» в BI-конструкторе")

    for manager in SALES_BI_MANAGERS:
        # Bitrix renders the selector under an animated surface.  Normal
        # pointer checks time out in headless Chromium although the control
        # itself is interactive, so target it directly.
        try:
            await control.click(timeout=10_000, force=True)
        except Exception as exc:
            # After a selection Bitrix replaces the initial "79 вариантов"
            # node with selected tags.  Re-open through the live filter input
            # instead of reusing that replaced node.
            opener = await _last_visible(
                frame.locator("input[type='search'], input[type='text'], input:not([type]), [contenteditable='true']")
            )
            if opener is None:
                raise ReportDeliveryError("Не удалось открыть список сотрудников BI-конструктора") from exc
            try:
                await opener.click(timeout=10_000, force=True)
            except Exception as open_exc:
                raise ReportDeliveryError("Не удалось открыть список сотрудников BI-конструктора") from open_exc
        search = await _last_visible(
            frame.locator("input[type='search'], input[type='text'], input:not([type]), [contenteditable='true']")
        )
        if search is None:
            raise ReportDeliveryError("Не найден поиск сотрудников в BI-конструкторе")
        try:
            await search.fill(manager, timeout=10_000, force=True)
        except Exception as exc:
            raise ReportDeliveryError("Не удалось найти сотрудника в списке BI-конструктора") from exc
        option = None
        for _ in range(40):
            option = await _last_visible(frame.get_by_text(manager, exact=True))
            if option is not None:
                break
            await frame.wait_for_timeout(250)
        if option is None:
            raise ReportDeliveryError(f"В BI-конструкторе не найден сотрудник: {manager}")
        try:
            await option.click(timeout=10_000, force=True)
        except Exception as exc:
            raise ReportDeliveryError(f"Не удалось выбрать сотрудника: {manager}") from exc
        await frame.wait_for_timeout(250)
        # Bitrix closes the result list after each choice, but leaves its
        # search input visible.  Close it explicitly so the next control
        # click always opens a fresh employee search, not a selected tag.
        try:
            await search.press("Escape", timeout=1_000)
        except Exception:
            pass

    await frame.wait_for_timeout(250)

    # The initial "N вариантов" element is replaced by selected chips, so it
    # cannot be used to read the final state.  The visible chips themselves
    # are stable after the popup closes.
    missing = []
    for manager in SALES_BI_MANAGERS:
        if await _last_visible(frame.get_by_text(manager, exact=True)) is None:
            missing.append(manager)
    if missing:
        raise ReportDeliveryError("Не удалось применить фильтр сотрудников отдела продаж")

    apply_button = await _last_visible(frame.get_by_text("Применить", exact=True))
    if apply_button is None or not await apply_button.is_enabled():
        raise ReportDeliveryError("Не удалось применить фильтр сотрудников отдела продаж")
    try:
        await apply_button.click(timeout=10_000, force=True)
    except Exception as exc:
        raise ReportDeliveryError("Не удалось применить фильтр сотрудников отдела продаж") from exc
    await frame.wait_for_timeout(500)


async def _apply_relative_date_filter(frame: object, label: str) -> None:
    """Choose a named BI period before the shared filters are applied."""
    if label not in {"Сегодня", "Вчера"}:
        raise ReportDeliveryError("Некорректная дата BI-отчёта")
    # Date and employee filters use different DOM nesting in BI Builder.  The
    # selected period is the reliable clickable part of the date control.
    control = None
    for _ in range(60):
        control = await _last_visible(frame.get_by_text(re.compile(r"^(Сегодня|Вчера)$")))
        if control is not None:
            break
        await frame.wait_for_timeout(500)
    if control is None:
        raise ReportDeliveryError("Не найден фильтр даты в BI-конструкторе")
    # BI renders the period picker above a transparent animation layer in
    # headless Chromium.  A forced click reaches the actual selected-period
    # control without relying on that transient layer.
    await control.click(timeout=10_000, force=True)
    await frame.wait_for_timeout(300)
    option = await _last_visible(frame.get_by_text(label, exact=True))
    if option is None:
        raise ReportDeliveryError(f"В BI-конструкторе не найдена дата: {label}")
    await option.click(timeout=10_000, force=True)
    await frame.wait_for_timeout(250)
    if label not in await control.inner_text():
        raise ReportDeliveryError("Не удалось применить дату BI-отчёта")


async def _find_bi_filter_context(page: object) -> object:
    """Find the BI frame that owns the left-side dashboard filters."""
    for _ in range(60):
        for frame in page.frames:
            employee_label = await _last_visible(frame.get_by_text(re.compile(r"Сотрудник", re.IGNORECASE)))
            if employee_label is not None:
                return frame
        await page.wait_for_timeout(500)
    locations = ", ".join(sorted({_safe_page_location(frame.url) for frame in page.frames}))
    raise ReportDeliveryError(f"Не найден фильтр «Сотрудник» в BI-конструкторе ({locations})")


async def capture_bitrix_bi_reports(
    *,
    login: str,
    password: str,
    report_url: str,
    leads_output_path: Path,
    calls_output_path: Path,
    relative_date_label: str | None = None,
) -> tuple[Path, Path]:
    """Capture the two adjacent tabs of the same BI Builder page."""
    _report_configuration(login, password, report_url)
    stage = "запуск браузера"
    page_location = ""
    try:
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError
        from playwright.async_api import async_playwright
    except ImportError as exc:  # local unit tests do not require Chromium
        raise ReportDeliveryError("В образе Render не установлен Playwright") from exc

    leads_output_path.parent.mkdir(parents=True, exist_ok=True)
    calls_output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                headless=True,
                args=["--disable-dev-shm-usage", "--no-sandbox", "--disable-gpu", "--disable-extensions"],
            )
            try:
                # BI Builder hides its desktop filter sidebar at narrower
                # viewport widths; use the same wide layout as the source UI.
                page = await browser.new_page(viewport={"width": 1920, "height": 1200}, device_scale_factor=1)
                stage = "открытие страницы отчёта"
                await page.goto(report_url, wait_until="domcontentloaded", timeout=45_000)
                page_location = _safe_page_location(page.url)

                # The unauthenticated server is redirected to Bitrix24 Network OAuth.
                if "auth2.bitrix24.by" in page.url:
                    stage = "ожидание поля логина Bitrix24"
                    login_input = page.locator("input[type='tel'], input[name='LOGIN'], input[name='login'], input[type='text']").first
                    await login_input.wait_for(state="visible", timeout=20_000)
                    await login_input.fill(login)
                    stage = "отправка логина Bitrix24"
                    await page.get_by_role("button").filter(has_text="Продолжить").first.click(timeout=8_000)
                    stage = "ожидание поля пароля Bitrix24"
                    password_input = page.locator("input[type='password']").first
                    await password_input.wait_for(state="visible", timeout=20_000)
                    await password_input.fill(password)
                    stage = "отправка пароля Bitrix24"
                    # Bitrix24 varies the visible submit label by its login
                    # flow.  Submitting the password field works for both.
                    await password_input.press("Enter")
                    stage = "переход из Bitrix24 к BI-отчёту"
                    try:
                        await page.wait_for_url("**/bi/dashboard/detail/80/**", timeout=45_000)
                    except PlaywrightTimeoutError as exc:
                        if "auth2.bitrix24.by" in page.url:
                            raise ReportDeliveryError(await _bitrix_auth_blocker(page)) from exc
                        raise
                    page_location = _safe_page_location(page.url)

                stage = "проверка доступности BI-отчёта"
                unavailable = page.get_by_text("Отчёт недоступен", exact=True)
                try:
                    await unavailable.wait_for(state="visible", timeout=4_000)
                except PlaywrightTimeoutError:
                    pass
                else:
                    raise ReportDeliveryError("BI-конструктор вернул «Отчёт недоступен»")

                # This is the neighboring tab in the same BI report, exactly
                # as it appears next to «Отчет по Лидам/Сделкам» in Bitrix24.
                stage = "открытие вкладки «Звонки»"
                calls_tab = None
                calls_frame = None
                for _ in range(90):
                    for frame in page.frames:
                        candidate = frame.get_by_text(re.compile(r"Отч[её]т по звонкам", re.IGNORECASE))
                        if await candidate.count():
                            calls_tab = candidate.first
                            calls_frame = frame
                            break
                    if calls_tab:
                        break
                    await page.wait_for_timeout(500)
                if calls_tab is None or calls_frame is None:
                    # Preserve the actual BI screen for authenticated preview
                    # diagnostics; never send it to Telegram.
                    await page.screenshot(path=str(leads_output_path), full_page=True, timeout=45_000)
                    raise ReportDeliveryError("Вкладка «Звонки» не появилась в текущем BI-отчёте")
                if "auth2.bitrix24.by" in page.url:
                    raise ReportDeliveryError("Bitrix24 требует интерактивное подтверждение входа")
                stage = "фильтрация по менеджерам отдела продаж"
                filter_context = await _find_bi_filter_context(page)
                await _apply_sales_manager_filter(filter_context)
                if relative_date_label:
                    # Selecting the date redraws the side panel in BI Builder,
                    # but preserves already applied employee filters.
                    stage = "выбор даты BI-отчёта"
                    filter_context = await _find_bi_filter_context(page)
                    await _apply_relative_date_filter(filter_context, relative_date_label)
                stage = "ожидание данных «Лиды/Сделки»"
                await _wait_for_bi_report_ready(calls_frame)
                stage = "создание снимка «Лиды/Сделки»"
                await page.screenshot(path=str(leads_output_path), full_page=True, timeout=45_000)
                await calls_tab.click(timeout=15_000)
                stage = "ожидание заголовка вкладки «Звонки»"
                await calls_frame.get_by_text(re.compile(r"Ежедневный отч[её]т по звонкам", re.IGNORECASE)).wait_for(
                    state="visible", timeout=30_000
                )
                stage = "ожидание данных вкладки «Звонки»"
                await _wait_for_bi_report_ready(calls_frame)
                stage = "создание снимка «Звонки»"
                await page.screenshot(path=str(calls_output_path), full_page=True, timeout=45_000)
            finally:
                await browser.close()
    except ReportDeliveryError:
        raise
    except PlaywrightTimeoutError as exc:
        location = f" ({page_location})" if page_location else ""
        raise ReportDeliveryError(f"BI-конструктор остановился на этапе: {stage}{location}") from exc
    except Exception as exc:
        raise ReportDeliveryError("Не удалось получить снимок BI-конструктора") from exc
    return leads_output_path, calls_output_path


async def _capture_dashboard_daily_reports_in_browser(
    *,
    dashboard_url: str,
    access_cookie: str,
    legacy_access_cookie: str,
    report_date: str,
    finance: dict,
    leads_output_path: Path,
    calls_output_path: Path,
) -> tuple[Path, Path]:
    """Capture the dashboard's compact daily blocks without a desktop cursor.

    The report is rendered by a headless browser on Render.  It opens the
    dashboard's direct Bitrix/ledger report, not the BI Builder page, and
    captures only the report element rather than the whole application shell.
    """
    if not dashboard_url.startswith("https://"):
        raise ReportDeliveryError("Адрес дашборда для снимка должен быть HTTPS")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", report_date):
        raise ReportDeliveryError("Дата снимка дашборда задана неверно")
    finance_values = dashboard_finance_display_values(finance)
    try:
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise ReportDeliveryError("В образе Render не установлен Playwright") from exc

    leads_output_path.parent.mkdir(parents=True, exist_ok=True)
    calls_output_path.parent.mkdir(parents=True, exist_ok=True)
    stage = "запуск браузера"
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                headless=True,
                args=["--disable-dev-shm-usage", "--no-sandbox", "--disable-gpu", "--disable-extensions"],
            )
            try:
                context = await browser.new_context(viewport={"width": 1680, "height": 1200}, device_scale_factor=1)
                cookies = []
                if access_cookie:
                    cookies.append({
                        "name": "mavis_access", "value": access_cookie,
                        "url": dashboard_url,
                        "httpOnly": True, "secure": True, "sameSite": "Lax",
                    })
                if legacy_access_cookie:
                    cookies.append({
                        "name": "mavis_view", "value": legacy_access_cookie,
                        "url": dashboard_url,
                        "httpOnly": True, "secure": True, "sameSite": "Lax",
                    })
                if cookies:
                    await context.add_cookies(cookies)
                page = await context.new_page()
                finance_payload = json.dumps(finance, ensure_ascii=False)

                async def fulfill_finance(route):
                    await route.fulfill(
                        status=200,
                        content_type="application/json; charset=utf-8",
                        body=finance_payload,
                    )

                # The page normally gets this same payload from the dashboard
                # API. In an isolated headless context its in-flight request
                # can race the screenshot. Feed it the already validated
                # server result so the DOM is rendered normally and cannot
                # regress to a loading placeholder.
                await page.route("**/api/sales-daily-finance?*", fulfill_finance)
                stage = "открытие ежедневного отчёта дашборда"
                await page.goto(f"{dashboard_url}/#sales", wait_until="domcontentloaded", timeout=45_000)
                if "/login" in page.url:
                    raise ReportDeliveryError("Render не смог авторизоваться в дашборде для снимка")

                stage = "открытие ежедневной вкладки"
                await page.get_by_role("tab", name="Ежедневный отчёт", exact=True).click(timeout=20_000)
                date_input = page.locator("[data-daily-sales-date]")
                await date_input.wait_for(state="visible", timeout=20_000)
                await date_input.fill(report_date)
                await date_input.press("Tab")
                await page.locator("[data-daily-sales-refresh]").click(timeout=15_000)

                report = page.locator(".daily-sales-report")
                capture = page.locator(".daily-sales-capture")
                stage = "ожидание проверенных дневных поступлений"
                await report.get_by_text("Поступления за день", exact=True).wait_for(state="visible", timeout=90_000)
                financial_values = report.locator(".daily-sales-finance strong")
                for _ in range(DASHBOARD_FINANCE_WAIT_MS // DASHBOARD_FINANCE_POLL_MS):
                    if await financial_values.count() == 3:
                        rendered = tuple(await financial_values.nth(index).inner_text() for index in range(3))
                        if _financial_texts_match(rendered, finance_values):
                            break
                    await page.wait_for_timeout(DASHBOARD_FINANCE_POLL_MS)
                else:
                    raise ReportDeliveryError("Дашборд не применил проверенные финансовые значения")

                stage = "создание снимка лидов и сделок"
                await capture.screenshot(path=str(leads_output_path), timeout=45_000)

                stage = "открытие вкладки звонков"
                await page.get_by_role("tab", name="Звонки", exact=True).click(timeout=15_000)
                await report.get_by_text("Количество звонков по менеджерам", exact=True).wait_for(
                    state="visible", timeout=45_000
                )
                stage = "создание снимка звонков"
                await capture.screenshot(path=str(calls_output_path), timeout=45_000)
            finally:
                await browser.close()
    except ReportDeliveryError:
        raise
    except PlaywrightTimeoutError as exc:
        raise ReportDeliveryError(f"Дашборд остановился на этапе: {stage}") from exc
    except Exception as exc:
        raise ReportDeliveryError("Не удалось создать снимок ежедневного отчёта дашборда") from exc
    return leads_output_path, calls_output_path


async def capture_dashboard_daily_reports(
    *,
    dashboard_url: str,
    access_cookie: str,
    legacy_access_cookie: str,
    report_date: str,
    report: dict,
    finance: dict,
    leads_output_path: Path,
    calls_output_path: Path,
) -> tuple[Path, Path]:
    """Render the two report cards from verified dashboard payloads.

    ``dashboard_url`` and the access cookies remain in the interface so the
    scheduler configuration stays backwards-compatible.  Screenshots no
    longer launch a second Chromium inside the Render web process: that can
    exceed the instance memory limit and makes Render return a 502 before an
    image is written.
    """
    del dashboard_url, access_cookie, legacy_access_cookie
    return render_dashboard_daily_reports(
        report_date=report_date,
        report=report,
        finance=finance,
        leads_output_path=leads_output_path,
        calls_output_path=calls_output_path,
    )


async def send_telegram_reports(
    *,
    token: str,
    chat_id: str,
    texts: DailyReportTexts,
    image_paths: tuple[Path, Path],
    include_texts: bool = True,
    include_experts: bool = True,
) -> None:
    if not token:
        raise ReportDeliveryError("Не задан TELEGRAM_BOT_TOKEN")
    if not chat_id.strip():
        raise ReportDeliveryError("Не указан Telegram chat_id")
    import httpx

    def accepted(response: httpx.Response) -> bool:
        try:
            return response.status_code == 200 and bool(response.json().get("ok"))
        except ValueError:
            return False

    base_url = f"https://api.telegram.org/bot{token}"
    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            report_texts = (texts.sales, texts.experts) if include_experts else (texts.sales,)
            for text in report_texts if include_texts else ():
                response = await client.post(f"{base_url}/sendMessage", data={"chat_id": chat_id, "text": text})
                if not accepted(response):
                    raise ReportDeliveryError("Telegram не принял текст отчёта")
            for image_path, caption in zip(
                image_paths,
                ("Ежедневный отчёт Bitrix24 — Лиды и сделки", "Ежедневный отчёт Bitrix24 — Звонки"),
                strict=True,
            ):
                with image_path.open("rb") as image:
                    response = await client.post(
                        f"{base_url}/sendPhoto",
                        data={"chat_id": chat_id, "caption": caption},
                        files={"photo": (image_path.name, image, "image/png")},
                    )
                if not accepted(response):
                    raise ReportDeliveryError("Telegram не принял снимок BI-конструктора")
    except httpx.HTTPError as exc:
        raise ReportDeliveryError("Не удалось связаться с Telegram") from exc
