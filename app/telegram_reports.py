"""Server-side rendering and delivery of the daily Telegram reports.

The image is intentionally captured from Bitrix BI Builder itself.  It is never
reconstructed from operational-dashboard data: numeric text and BI image are
separate, traceable sources.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

RUSSIAN_WEEKDAYS = ("Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье")
RUSSIAN_MONTHS_GENITIVE = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)
SALES_BI_MANAGERS = (
    "Алена Хурсик",
    "Ирина Базылева",
    "Ирина Богомольцева",
    "Роман Авсеенко",
)


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
    finance = snapshot.get("clean_revenue") or {}
    if finance.get("status") in {"online", "stale"} and finance.get("value") is not None:
        return _finite_number(finance["value"], "чистая выручка")
    raise ReportDeliveryError("Чистая выручка из «Графика платежей» недоступна")


def _plan_or_dash(snapshot: dict, key: str) -> str:
    value = (snapshot.get("plans") or {}).get(key, {}).get("sales_amount")
    if value is None:
        return "—"
    return _format_byn(value)


def build_daily_report_texts(snapshot: dict, generated_at: datetime) -> DailyReportTexts:
    """Return the agreed manager-style text without inventing missing plans."""
    month_name = RUSSIAN_MONTHS_GENITIVE[generated_at.month - 1]
    production = snapshot.get("production") or {}
    kpi = production.get("kpi") or {}
    date = russian_date(generated_at)
    sales_amount = _clean_sales_amount(snapshot)
    sales_plan = _plan_or_dash(snapshot, "sales|overall|")
    closed_count = _format_count(kpi.get("closed_count", 0))
    closed_amount = _format_byn(kpi.get("closed_amount", 0))

    return DailyReportTexts(
        sales=(
            f"{date}\n\n"
            f"💰 Сумма продаж - {_format_byn(sales_amount)}\n\n"
            f"📈 Факт плана продаж {month_name} - {_format_byn(sales_amount)} / {sales_plan}"
        ),
        experts=(
            f"{date} 🍂\n\n"
            f"✅ Количество закрытых продуктов - {closed_count} шт\n"
            f"💰 Сумма закрытых актов - {closed_amount}\n\n"
            f"✔ Факт отдела {month_name} - {closed_amount}"
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
    frame: object, *, timeout_ms: int = 60_000, poll_ms: int = 500, stable_ms: int = 1_000
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
        if not visible and (loading_seen or attempt >= 10):
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
        # Resetting the multi-select between employees prevents Bitrix from
        # treating a filter query as text in an already-selected tag.
        await control.press("Escape")
        # Bitrix renders the selector under an animated surface.  Normal
        # pointer checks time out in headless Chromium although the control
        # itself is interactive, so target it directly.
        try:
            await control.click(timeout=10_000, force=True)
        except Exception as exc:
            raise ReportDeliveryError("Не удалось открыть список сотрудников BI-конструктора") from exc
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

    await control.press("Escape")
    await frame.wait_for_timeout(250)

    selected = await control.inner_text()
    missing = [manager for manager in SALES_BI_MANAGERS if manager not in selected]
    if missing:
        raise ReportDeliveryError("Не удалось применить фильтр сотрудников отдела продаж")

    apply_button = await _last_visible(frame.get_by_text("Применить", exact=True))
    if apply_button is None or not await apply_button.is_enabled():
        raise ReportDeliveryError("Не удалось применить фильтр сотрудников отдела продаж")
    await apply_button.click(timeout=10_000)
    await frame.wait_for_timeout(500)


async def _apply_relative_date_filter(frame: object, label: str) -> None:
    """Choose a named BI period before the shared filters are applied."""
    if label not in {"Сегодня", "Вчера"}:
        raise ReportDeliveryError("Некорректная дата BI-отчёта")
    # Date and employee filters use different DOM nesting in BI Builder.  The
    # selected period is the reliable clickable part of the date control.
    control = await _last_visible(frame.get_by_text(re.compile(r"^(Сегодня|Вчера)$")))
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
