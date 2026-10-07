import tempfile
import asyncio
from pathlib import Path

import app.main as main
from app.daily_sales import archive_snapshot
from app.storage import Storage


def test_daily_sales_archive_keeps_first_snapshot_for_a_day():
    with tempfile.TemporaryDirectory() as directory:
        storage = Storage(Path(directory) / "dashboard.sqlite3")
        first, created = storage.save_daily_sales_archive(
            "2026-10-06", {"date": "2026-10-06", "leads": {"total": 7}}, "2026-10-07T00:10:00+03:00"
        )
        second, created_again = storage.save_daily_sales_archive(
            "2026-10-06", {"date": "2026-10-06", "leads": {"total": 99}}, "2026-10-07T00:20:00+03:00"
        )

        assert created is True
        assert created_again is False
        assert second == first
        assert storage.daily_sales_archive("2026-10-06") == first


def test_past_day_reads_archive_without_requesting_bitrix(monkeypatch):
    with tempfile.TemporaryDirectory() as directory:
        storage = Storage(Path(directory) / "dashboard.sqlite3")
        archived = archive_snapshot(
            {"ok": True, "date": "2026-10-06", "leads": {"total": 7}}, "2026-10-07T00:10:00+03:00"
        )
        storage.save_daily_sales_archive("2026-10-06", archived, "2026-10-07T00:10:00+03:00")
        monkeypatch.setattr(main, "storage", storage)

        async def no_bitrix(*args, **kwargs):
            raise AssertionError("Bitrix must not be requested for an archived day")

        monkeypatch.setattr(main, "_load_daily_sales_live", no_bitrix)
        assert asyncio.run(main.load_daily_sales("2026-10-06")) == archived


def test_past_day_without_archive_is_marked_as_current_bitrix_data(monkeypatch):
    with tempfile.TemporaryDirectory() as directory:
        storage = Storage(Path(directory) / "dashboard.sqlite3")
        monkeypatch.setattr(main, "storage", storage)

        async def bitrix_report(*args, **kwargs):
            return {"ok": True, "date": "2026-10-06", "leads": {"total": 7}}

        monkeypatch.setattr(main, "_load_daily_sales_live", bitrix_report)
        result = asyncio.run(main.load_daily_sales("2026-10-06"))
        assert result["snapshot"]["mode"] == "historical_live"


def test_daily_sales_report_does_not_wait_for_finance(monkeypatch):
    main.daily_sales_cache.clear()
    main.daily_sales_cache_time.clear()

    async def bitrix_report(*args, **kwargs):
        return {"ok": True, "date": "2026-10-07", "leads": {"total": 7}}

    async def finance_call(*args, **kwargs):
        raise AssertionError("daily CRM report must not wait for finance")

    monkeypatch.setattr(main, "build_daily_sales_report", bitrix_report)
    monkeypatch.setattr(main, "load_clean_revenue_day", finance_call)
    monkeypatch.setattr(main, "load_clean_revenue_through", finance_call)

    result = asyncio.run(main._load_daily_sales_live("2026-10-07", force=True))

    assert result == {"ok": True, "date": "2026-10-07", "leads": {"total": 7}}


def test_daily_sales_finance_loads_after_the_crm_report(monkeypatch):
    main.daily_sales_finance_cache.clear()
    main.daily_sales_finance_cache_time.clear()

    async def clean_revenue(day):
        assert day == "2026-10-07"
        return {"status": "online", "value": 1250.50, "incoming_amount": 1450.50}

    async def month_revenue(month, report_at):
        assert month == "2026-10"
        assert report_at.date().isoformat() == "2026-10-07"
        return {"status": "online", "value": 5200.0}

    monkeypatch.setattr(main, "load_clean_revenue_day", clean_revenue)
    monkeypatch.setattr(main, "load_clean_revenue_through", month_revenue)
    monkeypatch.setattr(main, "_sales_plan_amount", lambda month: 135000.0)

    result = asyncio.run(main.load_daily_sales_finance("2026-10-07"))

    assert result == {
        "ok": True, "date": "2026-10-07",
        "clean_revenue": {"status": "online", "value": 1250.50, "incoming_amount": 1450.50},
        "month_clean_revenue": {"status": "online", "value": 5200.0},
        "sales_plan_amount": 135000.0,
    }
