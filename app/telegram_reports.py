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


def _incoming_sales_amount(snapshot: dict) -> float:
    finance = snapshot.get("clean_revenue") or {}
    if finance.get("status") in {"online", "stale"} and finance.get("incoming_amount") is not None:
        return _finite_number(finance["incoming_amount"], "поступления продаж")
    raise ReportDeliveryError("Поступления продаж из «Графика платежей» недоступны")


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
    sales_amount = _incoming_sales_amount(snapshot)
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


async def capture_bitrix_bi_reports(
    *, login: str, password: str, report_url: str, leads_output_path: Path, calls_output_path: Path
) -> tuple[Path, Path]:
    """Capture both BI Builder tabs without retaining two report trees in RAM."""
    _report_configuration(login, password, report_url)
    session_path = leads_output_path.parent / ".bitrix-bi-report-session.json"

    # A full BI report is a sizeable single-page application.  Render runs the
    # dashboard and Chromium in the same container, so closing Chromium after
    # each tab is more reliable than retaining the first report while loading
    # the second one.  Its short-lived Bitrix session is passed to the second
    # clean browser process and removed immediately afterwards.
    try:
        await _capture_bitrix_bi_tab(
            login=login,
            password=password,
            report_url=report_url,
            output_path=leads_output_path,
            tab="leads",
            session_path=session_path,
            save_session=True,
        )
        await _capture_bitrix_bi_tab(
            login=login,
            password=password,
            report_url=report_url,
            output_path=calls_output_path,
            tab="calls",
            session_path=session_path,
        )
    finally:
        session_path.unlink(missing_ok=True)
    return leads_output_path, calls_output_path


async def _capture_bitrix_bi_tab(
    *,
    login: str,
    password: str,
    report_url: str,
    output_path: Path,
    tab: str,
    session_path: Path | None = None,
    save_session: bool = False,
) -> None:
    """Open one BI tab in an isolated browser process and save a screenshot."""
    stage = "запуск браузера"
    page_location = ""
    try:
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError
        from playwright.async_api import async_playwright
    except ImportError as exc:  # local unit tests do not require Chromium
        raise ReportDeliveryError("В образе Render не установлен Playwright") from exc

    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                headless=True,
                args=["--disable-dev-shm-usage", "--no-sandbox", "--disable-gpu", "--disable-extensions"],
            )
            try:
                context_options = {"viewport": {"width": 1440, "height": 1000}, "device_scale_factor": 1}
                if session_path and session_path.is_file():
                    context_options["storage_state"] = str(session_path)
                context = await browser.new_context(**context_options)
                page = await context.new_page()
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

                if save_session and session_path:
                    await context.storage_state(path=str(session_path))

                stage = "проверка доступности BI-отчёта"
                unavailable = page.get_by_text("Отчёт недоступен", exact=True)
                try:
                    await unavailable.wait_for(state="visible", timeout=4_000)
                except PlaywrightTimeoutError:
                    pass
                else:
                    raise ReportDeliveryError("BI-конструктор вернул «Отчёт недоступен»")

                stage = "отрисовка BI-отчёта"
                await page.wait_for_timeout(3_000)
                if "auth2.bitrix24.by" in page.url:
                    raise ReportDeliveryError("Bitrix24 требует интерактивное подтверждение входа")
                if tab == "calls":
                    stage = "открытие вкладки «Звонки»"
                    calls_tab = page.get_by_text(re.compile(r"Отч[её]т по звонкам", re.IGNORECASE))
                    # BI Builder renders the shell before the report tabs are
                    # interactive.  Render has no user's VPN cache, so wait
                    # for the real tab rather than treating a slow render as
                    # a missing report.
                    try:
                        await calls_tab.wait_for(state="visible", timeout=45_000)
                    except PlaywrightTimeoutError as exc:
                        body_text = await page.locator("body").inner_text(timeout=5_000)
                        clues = [
                            line.strip() for line in body_text.splitlines()
                            if "отч" in line.lower() or "звон" in line.lower() or "ошиб" in line.lower()
                        ]
                        summary = " / ".join(clues)[:300] or "названия вкладок не найдены"
                        raise ReportDeliveryError(f"Вкладка «Звонки» не появилась: {summary}") from exc
                    await calls_tab.click(timeout=15_000)
                    stage = "отрисовка вкладки «Звонки»"
                    await page.get_by_text(re.compile(r"Ежедневный отч[её]т по звонкам", re.IGNORECASE)).wait_for(
                        state="visible", timeout=30_000
                    )
                    await page.wait_for_timeout(2_000)
                    stage = "создание снимка «Звонки»"
                else:
                    stage = "создание снимка «Лиды/Сделки»"
                await page.screenshot(path=str(output_path), full_page=True, timeout=45_000)
            finally:
                await browser.close()
    except ReportDeliveryError:
        raise
    except PlaywrightTimeoutError as exc:
        location = f" ({page_location})" if page_location else ""
        raise ReportDeliveryError(f"BI-конструктор остановился на этапе: {stage}{location}") from exc
    except Exception as exc:
        raise ReportDeliveryError("Не удалось получить снимок BI-конструктора") from exc


async def send_telegram_reports(
    *, token: str, chat_id: str, texts: DailyReportTexts, image_paths: tuple[Path, Path], include_texts: bool = True
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
            for text in (texts.sales, texts.experts) if include_texts else ():
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
